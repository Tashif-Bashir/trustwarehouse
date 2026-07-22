import { BigQuery } from '@google-cloud/bigquery'
import { BOARDS, SOURCE_NAMES, TEAM_ASCEND_NAMES } from '../config'
import type { Metrics } from '../types'

// Real data provider.
//
//   Calls        <- silver.silver_ascend_calls (europe-west2), rebuilt by the
//                   warehouse VM every ~60s sync cycle. Deliberately NOT
//                   bronze.ascend_calls: the bronze sync merges its 2h
//                   lookback window by delete-then-reinsert, so a query
//                   landing mid-merge transiently loses up to 2h of recent
//                   calls (observed live 18 Jul 2026 — the board's bars
//                   visibly shrank for one refresh). Silver is an atomic
//                   CREATE OR REPLACE, so it is always complete. A CDR row
//                   exists only once a call has ENDED.
//   Appointments <- union of app.bookings (US region — the booking app's own
//                   event log, live to the second) and the CRM (silver, ~30
//                   min behind, catches manual/WhatsApp bookings), deduped
//                   per lead. Counting is permanent: a booking cancelled
//                   later still counts on the day it was booked.
//
// The two datasets live in different BigQuery regions, so they are always
// separate queries — never joined in SQL.

const PROJECT = 'trustwarehouse'
const CACHE_TTL_MS = 15_000 // several wall screens share one BigQuery fetch

let bq: BigQuery | null = null

function client(): BigQuery {
  if (!bq) {
    const json = process.env.GOOGLE_CREDENTIALS_JSON
    bq = json
      ? new BigQuery({ projectId: PROJECT, credentials: JSON.parse(json) })
      : new BigQuery({ projectId: PROJECT }) // local dev: ADC / GOOGLE_APPLICATION_CREDENTIALS
  }
  return bq
}

// reverse lookups: source-specific name -> agent id (telesales board)
const byAscend = new Map<string, string>()
const byBooker = new Map<string, string>()
const byCrm = new Map<string, string>()
for (const [id, names] of Object.entries(SOURCE_NAMES)) {
  names.ascend.forEach((n) => byAscend.set(n, id))
  names.appBookers.forEach((n) => byBooker.set(n, id))
  names.crm.forEach((n) => byCrm.set(n, id))
}

// sales & ops board: Ascend names only (no appointments on that board)
const byAscendTeam = new Map<string, string>()
for (const [id, names] of Object.entries(TEAM_ASCEND_NAMES)) {
  names.forEach((n) => byAscendTeam.set(n, id))
}

const ASCEND_MAP: Record<string, Map<string, string>> = {
  telesales: byAscend,
  team: byAscendTeam,
}

interface CallRow {
  agent: string
  total_calls: number
  calls_over_1m: number
  talk_seconds: number
}

// A call counts when it's an outbound dial (answered or not — dialling is
// activity) or an ANSWERED inbound; missed inbound isn't the agent's call
// and internal calls are excluded entirely (owner decision 21 Jul 2026).
async function queryCalls(nameMap: Map<string, string>): Promise<Map<string, CallRow>> {
  const [rows] = await client().query({
    query: `
      SELECT
        colleague_name AS agent,
        COUNTIF(direction = 'OUTBOUND'
                OR (direction = 'INBOUND' AND call_status = 'COMPLETED'))  AS total_calls,
        COUNTIF((direction = 'OUTBOUND'
                 OR (direction = 'INBOUND' AND call_status = 'COMPLETED'))
                AND COALESCE(talk_time_seconds, 0) >= 60)                  AS calls_over_1m,
        SUM(IF(direction = 'OUTBOUND'
               OR (direction = 'INBOUND' AND call_status = 'COMPLETED'),
               COALESCE(talk_time_seconds, 0), 0))                         AS talk_seconds
      FROM \`${PROJECT}.silver.silver_ascend_calls\`
      WHERE direction IN ('OUTBOUND', 'INBOUND')
        AND DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London') = CURRENT_DATE('Europe/London')
        AND colleague_name IN UNNEST(@names)
      GROUP BY agent
    `,
    params: { names: [...nameMap.keys()] },
    location: 'europe-west2',
  })
  const out = new Map<string, CallRow>()
  for (const row of rows as CallRow[]) {
    const id = nameMap.get(row.agent)
    if (!id) continue
    // merge if two source-name variants map to the same agent
    const prev = out.get(id)
    out.set(
      id,
      prev
        ? {
            agent: row.agent,
            total_calls: Number(prev.total_calls) + Number(row.total_calls),
            calls_over_1m: Number(prev.calls_over_1m) + Number(row.calls_over_1m),
            talk_seconds: Number(prev.talk_seconds) + Number(row.talk_seconds),
          }
        : row
    )
  }
  return out
}

// Booking events today, one per lead, agent-id attributed. Each source is
// fetched independently and failures degrade to the other source rather
// than blanking the board.
async function queryAppointments(): Promise<Map<string, number>> {
  const crmPromise = client()
    .query({
      query: `
        SELECT lead_id, appointment_made_by AS name
        FROM \`${PROJECT}.silver.silver_sharpspring_leads\`
        WHERE appointment_made_by IN UNNEST(@names)
          AND appointment_booked_at IS NOT NULL
          AND DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London')
              = CURRENT_DATE('Europe/London')
          AND (appointment_booked = 'Yes'
               OR LOWER(COALESCE(domestic_appointment_status, '')) IN
                  ('appointment', 'whatsapp appointment', 'appointment cancelled'))
      `,
      params: { names: [...byCrm.keys()] },
      location: 'europe-west2',
    })
    .then(([rows]) => rows as { lead_id: string; name: string }[])
    .catch(() => [])

  const appPromise = client()
    .query({
      query: `
        SELECT lead_id, booker_name AS name
        FROM \`${PROJECT}.app.bookings\`
        WHERE booker_name IN UNNEST(@names)
          AND DATE(booked_at, 'Europe/London') = CURRENT_DATE('Europe/London')
          AND customer NOT LIKE 'Zzz Testlead%'
          -- unlinked (calendar-only) rows can't be deduped against the CRM
          -- and reschedules aren't new bookings — neither counts (22 Jul 2026)
          AND lead_id IS NOT NULL AND lead_id != ''
          AND COALESCE(is_rebook, FALSE) = FALSE
      `,
      params: { names: [...byBooker.keys()] },
      location: 'US',
    })
    .then(([rows]) => rows as { lead_id: string; name: string }[])
    .catch(() => [])

  const [crmRows, appRows] = await Promise.all([crmPromise, appPromise])

  // dedupe on lead: CRM first so its attribution wins when both have the row
  const agentByLead = new Map<string, string>()
  for (const row of crmRows) {
    const id = byCrm.get(row.name)
    if (id) agentByLead.set(String(row.lead_id), id)
  }
  for (const row of appRows) {
    const id = byBooker.get(row.name)
    if (id && !agentByLead.has(String(row.lead_id))) agentByLead.set(String(row.lead_id), id)
  }

  const counts = new Map<string, number>()
  for (const id of agentByLead.values()) counts.set(id, (counts.get(id) ?? 0) + 1)
  return counts
}

const caches: Record<string, { data: Metrics; at: number; ukDate: string }> = {}

function ukToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/London',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

export async function getBronzeMetrics(boardId: string = 'telesales'): Promise<Metrics> {
  const board = BOARDS[boardId] ?? BOARDS.telesales
  const cache = caches[board.id]
  if (cache && Date.now() - cache.at < CACHE_TTL_MS && cache.ukDate === ukToday()) {
    return cache.data
  }

  try {
    const [calls, appointments] = await Promise.all([
      queryCalls(ASCEND_MAP[board.id]),
      board.features.appointments ? queryAppointments() : Promise.resolve(new Map<string, number>()),
    ])
    const today = ukToday()
    const prevByAgent = new Map(
      cache && cache.ukDate === today ? cache.data.agents.map((a) => [a.id, a]) : []
    )
    const agents = board.agents.map((agent) => {
      const c = calls.get(agent.id)
      // Monotonic guard: cumulative call counts can only rise within a day.
      // If a source read ever comes back lower than what we already served
      // (any transient upstream gap), hold the higher number — the next
      // refresh catches up. Appointments stay live (a genuine CRM
      // correction should show).
      const prev = prevByAgent.get(agent.id)
      return {
        ...agent,
        totalCalls: Math.max(Number(c?.total_calls ?? 0), prev?.totalCalls ?? 0),
        callsOver1m: Math.max(Number(c?.calls_over_1m ?? 0), prev?.callsOver1m ?? 0),
        talktimeSeconds: Math.max(Number(c?.talk_seconds ?? 0), prev?.talktimeSeconds ?? 0),
        appointmentsBooked: appointments.get(agent.id) ?? 0,
      }
    })
    const data: Metrics = { asOf: new Date().toISOString(), source: 'Ascend', agents }
    caches[board.id] = { data, at: Date.now(), ukDate: today }
    return data
  } catch (err) {
    // BigQuery hiccup: serve the last good numbers if we have any — the
    // frontend's stale pill covers prolonged outages.
    if (cache) return cache.data
    throw err
  }
}
