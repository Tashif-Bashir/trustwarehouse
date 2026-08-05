import { BigQuery } from '@google-cloud/bigquery'
import { BOARDS, SOURCE_NAMES, TEAM_AGENTS, TEAM_ASCEND_NAMES } from '../config'
import type { Metrics, SalesMetrics } from '../types'

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

// Sales tiles (team board) — live from app.sales (US region), the Trust Sales
// app's event ledger: one row per sale, voids/cancels excluded via status.
// Domestic revenue = heating + water + CHC (the manager's definition).
async function querySales(): Promise<SalesMetrics | null> {
  const amt =
    "COALESCE(heating_amount, 0) + COALESCE(water_amount, 0) + COALESCE(chc_amount, 0)"
  const base = `
    FROM \`${PROJECT}.app.sales\`
    WHERE status = 'active' AND customer_name NOT LIKE 'Zzz Testlead%'
  `
  try {
    const [aggPromise, sellersPromise, lastPromise, rosterPromise] = [
      // daily grain — month/week/today/yesterday and the 7-day strip are all
      // derived from this one result
      client().query({
        query: `
          SELECT CAST(sale_date AS STRING) AS day,
                 COUNT(*) AS n, SUM(${amt}) AS total, MAX(${amt}) AS mx,
                 -- a sale can carry heating AND water, so these are counts of
                 -- sales CONTAINING each product and may sum to more than n
                 COUNTIF(COALESCE(heating_amount, 0) > 0) AS heat_n,
                 COUNTIF(COALESCE(water_amount, 0) > 0) AS water_n
          ${base}
            AND sale_date >= DATE_SUB(DATE_TRUNC(CURRENT_DATE('Europe/London'), MONTH), INTERVAL 7 DAY)
          GROUP BY day
        `,
        location: 'US',
      }),
      client().query({
        query: `
          SELECT sold_by AS name, COUNT(*) AS count, SUM(${amt}) AS total
          ${base}
            AND sold_by IS NOT NULL
            AND sale_date >= DATE_TRUNC(CURRENT_DATE('Europe/London'), MONTH)
          GROUP BY sold_by
          ORDER BY total DESC
        `,
        location: 'US',
      }),
      // the banner shows live app activity only (backfilled history has no
      // meaningful logged-at moment). `day` lets the UI qualify a stale sale
      // rather than implying it just happened.
      client().query({
        query: `
          SELECT customer_name, sale_type, sold_by, ${amt} AS amount,
                 FORMAT_TIMESTAMP('%H:%M', created_at, 'Europe/London') AS at_uk,
                 FORMAT_TIMESTAMP('%Y-%m-%d', created_at, 'Europe/London') AS day,
                 FORMAT_TIMESTAMP('%a %e %b', created_at, 'Europe/London') AS day_label
          ${base}
            AND source = 'app'
          ORDER BY created_at DESC
          LIMIT 1
        `,
        location: 'US',
      }),
      // the booking-app roster: seeds the reps list so it is never empty (e.g.
      // the 1st of a month, before anyone has sold) and new reps appear at £0
      // from their first day. Josh is internal sales — he has his own tile.
      client().query({
        query: `
          SELECT name
          FROM \`${PROJECT}.app.reps\`
          WHERE name != 'Josh Barron'
        `,
        location: 'US',
      }),
    ]
    const [[dailyRows], [sellerRows], [lastRows], [rosterRows]] = await Promise.all([
      aggPromise,
      sellersPromise,
      lastPromise,
      rosterPromise,
    ])

    // derive the windows from the daily grain (all dates are UK-local)
    const today = ukToday()
    const addDays = (s: string, n: number) => {
      const d = new Date(s + 'T12:00:00Z')
      return new Date(d.getTime() + n * 86_400_000).toISOString().slice(0, 10)
    }
    const monthStart = today.slice(0, 8) + '01'
    const dow = new Date(today + 'T12:00:00Z').getUTCDay() // 0 = Sun
    const weekStart = addDays(today, -((dow + 6) % 7))

    type DayAgg = { n: number; total: number; mx: number; heat: number; water: number }
    const EMPTY: DayAgg = { n: 0, total: 0, mx: 0, heat: 0, water: 0 }
    const daily = new Map<string, DayAgg>()
    for (const r of dailyRows as {
      day: string; n: number; total: number; mx: number; heat_n: number; water_n: number
    }[]) {
      daily.set(r.day, {
        n: Number(r.n),
        total: Number(r.total),
        mx: Number(r.mx),
        heat: Number(r.heat_n),
        water: Number(r.water_n),
      })
    }
    const windowSum = (from: string): DayAgg => {
      let n = 0
      let total = 0
      let mx = 0
      let heat = 0
      let water = 0
      for (const [day, v] of daily) {
        if (day >= from && day <= today) {
          n += v.n
          total += v.total
          heat += v.heat
          water += v.water
          mx = Math.max(mx, v.mx)
        }
      }
      return { n, total, mx, heat, water }
    }
    const month = windowSum(monthStart)
    const week = windowSum(weekStart)
    const todayAgg = daily.get(today) ?? EMPTY
    const yesterdayAgg = daily.get(addDays(today, -1)) ?? EMPTY
    const last7 = Array.from({ length: 7 }, (_, i) => {
      const date = addDays(today, i - 6)
      return { date, total: daily.get(date)?.total ?? 0 }
    })
    const allSellers = sellerRows as { name: string; count: number; total: number }[]
    const sellerColor = new Map(TEAM_AGENTS.map((a) => [a.name, a.color]))
    const sellers = ['Dec', 'Josh'].map((name) => {
      const row = allSellers.find((r) => r.name === name)
      return {
        name,
        color: sellerColor.get(name) ?? '#888',
        count: Number(row?.count ?? 0),
        total: Number(row?.total ?? 0),
      }
    })
    // Field reps (everyone who isn't Dec/Josh), £ desc — the slideshow tile
    // pages through these. Colours are assigned by rank from a fixed palette.
    const REP_PALETTE = [
      '#2a78d6', '#1baf7a', '#e87ba4', '#eb6834', '#8b5cf6',
      '#0ea5b7', '#d6a52a', '#d64545', '#5b8a2a', '#7a6ff0',
      '#c257c2', '#4f9d8f', '#b0713a', '#6787b8',
    ]
    // Union of the booking-app roster and whoever actually sold this month:
    // the roster guarantees the panel is never empty and that a new rep appears
    // at £0 from day one; the sellers side means historical/ex-rep names in the
    // ledger still show their revenue instead of being silently dropped.
    const soldThisMonth = allSellers.filter((r) => r.name !== 'Dec' && r.name !== 'Josh')
    const roster = (rosterRows as { name: string }[]).map((r) => r.name)
    const repNames = Array.from(new Set([...soldThisMonth.map((r) => r.name), ...roster]))
    const reps = repNames
      .map((name) => {
        const row = soldThisMonth.find((r) => r.name === name)
        return {
          name,
          count: Number(row?.count ?? 0),
          total: Number(row?.total ?? 0),
        }
      })
      // £ desc, then alphabetical so the not-yet-sold tail has a stable order
      .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name))
      .map((r, i) => ({ ...r, color: REP_PALETTE[i % REP_PALETTE.length] }))

    const typeLabels: Record<string, string> = {
      on_site: 'Sold on Site',
      office: 'Sold in Office',
      chc: 'CHC online',
    }
    const last = (lastRows as {
      customer_name: string
      sale_type: string
      sold_by: string | null
      amount: number
      at_uk: string
      day: string
      day_label: string
    }[])[0]
    // Qualify anything not logged today, so a Monday morning (or the 1st of a
    // month) can't show Friday's sale as if it had just landed.
    const lastSaleWhen = last
      ? last.day === today
        ? last.at_uk
        : last.day === addDays(today, -1)
          ? `Yesterday ${last.at_uk}`
          : `${last.day_label.replace(/\s+/g, ' ').trim()} ${last.at_uk}`
      : ''

    const monthLabel = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/London',
      month: 'long',
    }).format(new Date())

    return {
      monthRevenue: month.total,
      monthCount: month.n,
      monthHeating: month.heat,
      monthWater: month.water,
      monthMax: month.mx,
      weekRevenue: week.total,
      weekCount: week.n,
      weekHeating: week.heat,
      weekWater: week.water,
      weekMax: week.mx,
      todayRevenue: todayAgg.total,
      todayCount: todayAgg.n,
      todayHeating: todayAgg.heat,
      todayWater: todayAgg.water,
      yesterdayRevenue: yesterdayAgg.total,
      last7,
      monthLabel,
      sellers,
      reps,
      lastSale: last
        ? {
            amount: Number(last.amount),
            typeLabel: typeLabels[last.sale_type] ?? last.sale_type,
            soldBy: last.sold_by,
            customer: last.customer_name,
            atUk: lastSaleWhen,
          }
        : null,
    }
  } catch {
    return null // sales tiles degrade to hidden; call bars stay up
  }
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
    const [calls, appointments, sales] = await Promise.all([
      queryCalls(ASCEND_MAP[board.id]),
      board.features.appointments ? queryAppointments() : Promise.resolve(new Map<string, number>()),
      board.features.sales ? querySales() : Promise.resolve(null),
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
    const data: Metrics = {
      asOf: new Date().toISOString(),
      source: board.features.sales ? 'Ascend + Trust Sales' : 'Ascend',
      agents,
      ...(sales ? { sales } : {}),
    }
    caches[board.id] = { data, at: Date.now(), ukDate: today }
    return data
  } catch (err) {
    // BigQuery hiccup: serve the last good numbers if we have any — the
    // frontend's stale pill covers prolonged outages.
    if (cache) return cache.data
    throw err
  }
}
