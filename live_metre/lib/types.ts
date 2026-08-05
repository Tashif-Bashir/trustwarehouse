export interface AgentMetrics {
  id: string
  name: string
  color: string
  role?: string
  // outbound dials (answered or not) + answered inbound; internal and
  // missed-inbound excluded (owner decision 21 Jul 2026)
  totalCalls: number
  callsOver1m: number // >= 60s talk, same in+out scope
  talktimeSeconds: number // in+out talk time, same scope
  appointmentsBooked: number
}

// Sales tiles (team board): live from app.sales, the Trust Sales app's ledger.
export interface SellerSales {
  name: string
  color: string
  count: number
  total: number
}

export interface LastSale {
  amount: number
  typeLabel: string // 'Sold on Site' | 'Sold in Office' | 'CHC online'
  soldBy: string | null
  customer: string
  atUk: string // HH:mm Europe/London when it was logged
}

export interface SalesMetrics {
  monthRevenue: number
  monthCount: number
  // sales CONTAINING each product; a sale can have both, so these can sum
  // to more than the sale count
  monthHeating: number
  monthWater: number
  monthMax: number // biggest single sale this month
  weekRevenue: number
  weekCount: number
  weekHeating: number
  weekWater: number
  weekMax: number
  todayRevenue: number
  todayCount: number
  todayHeating: number
  todayWater: number
  yesterdayRevenue: number
  // six periods each, oldest first, current period last; gaps are zero-filled
  monthTrend: { label: string; total: number }[]
  weekTrend: { label: string; total: number }[]
  // straight-line projection for the month; null before the 5th (too noisy)
  monthPace: number | null
  // whole-domestic revenue target for the current month, from app.targets;
  // null when nobody has set one and the card simply shows no bar
  monthTarget: number | null
  weekTopRep: { name: string; total: number } | null
  last7: { date: string; total: number }[] // 7 days ending today, chronological
  monthLabel: string // e.g. 'July'
  sellers: SellerSales[] // Dec & Josh, month-to-date
  reps: SellerSales[] // field reps month-to-date, £ desc (slideshow tile)
  lastSale: LastSale | null
}

export interface Metrics {
  asOf: string // ISO timestamp of when the source produced these numbers
  source: string // human label shown in the header subtitle
  agents: AgentMetrics[]
  sales?: SalesMetrics // team board only
}
