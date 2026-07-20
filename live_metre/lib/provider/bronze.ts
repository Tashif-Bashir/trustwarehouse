import { BigQuery } from '@google-cloud/bigquery'
import { AGENTS, SOURCE_NAMES } from '../config'
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

// reverse lookups: source-specific name -> agent id
const byAscend = new Map<string, string>()
const byBooker = new Map<string, string>()
const byCrm = new Map<string, string>()
for (const [id, names] of Object.entries(SOURCE_NAMES)) {
  names.ascend.forEach((n) => byAscend.set(n, id))
  names.appBookers.forEach((n) => byBooker.set(n, id))
  names.crm.forEach((n) => byCrm.set(n, id))
}

interface CallRow {
  agent: string
  outbound_calls: number
  calls_over_30s: number
  calls_over_2m: number
  talk_seconds: number
}

async function queryCalls(): Promise<Map<string, CallRow>> {
  const [rows] = await client().query({
    query: `
      SELECT
        colleague_name                                   AS agent,
        COUNT(*)                                         AS outbound_calls,
        COUNTIF(COALESCE(talk_time_seconds, 0) > 30)     AS calls_over_30s,
        COUNTIF(COALESCE(talk_time_seconds, 0) >= 120)   AS calls_over_2m,
        SUM(COALESCE(talk_time_seconds, 0))              AS talk_seconds
      FROM \`${PROJECT}.silver.silver_ascend_calls\`
      WHERE direction = 'OUTBOUND'
        AND DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London') = CURRENT_DATE('Europe/London')
        AND colleague_name IN UNNEST(@names)
      GROUP BY agent
    `,
    params: { names: [...byAscend.keys()] },
    location: 'europe-west2',
  })
  const out = new Map<string, CallRow>()
  for (const row of rows as CallRow[]) {
    const id = byAscend.get(row.agent)
    if (id) out.set(id, row)
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

let cache: { data: Metrics; at: number; ukDate: string } | null = null

function ukToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/London',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

export async function getBronzeMetrics(): Promise<Metrics> {
  if (cache && Date.now() - cache.at < CACHE_TTL_MS && cache.ukDate === ukToday()) {
    return cache.data
  }

  try {
    const [calls, appointments] = await Promise.all([queryCalls(), queryAppointments()])
    const today = ukToday()
    const prevByAgent = new Map(
      cache && cache.ukDate === today ? cache.data.agents.map((a) => [a.id, a]) : []
    )
    const agents = AGENTS.map((agent) => {
      const c = calls.get(agent.id)
      // Monotonic guard: cumulative call counts can only rise within a day.
      // If a source read ever comes back lower than what we already served
      // (any transient upstream gap), hold the higher number — the next
      // refresh catches up. Appointments stay live (a genuine CRM
      // correction should show).
      const prev = prevByAgent.get(agent.id)
      return {
        ...agent,
        outboundCalls: Math.max(Number(c?.outbound_calls ?? 0), prev?.outboundCalls ?? 0),
        callsOver30s: Math.max(Number(c?.calls_over_30s ?? 0), prev?.callsOver30s ?? 0),
        callsOver2m: Math.max(Number(c?.calls_over_2m ?? 0), prev?.callsOver2m ?? 0),
        talktimeSeconds: Math.max(Number(c?.talk_seconds ?? 0), prev?.talktimeSeconds ?? 0),
        appointmentsBooked: appointments.get(agent.id) ?? 0,
      }
    })
    const data: Metrics = { asOf: new Date().toISOString(), source: 'Ascend', agents }
    cache = { data, at: Date.now(), ukDate: today }
    return data
  } catch (err) {
    // BigQuery hiccup: serve the last good numbers if we have any — the
    // frontend's stale pill covers prolonged outages.
    if (cache) return cache.data
    throw err
  }
}
