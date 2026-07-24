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
  monthMax: number // biggest single sale this month
  weekRevenue: number
  weekCount: number
  weekMax: number
  todayRevenue: number
  todayCount: number
  yesterdayRevenue: number
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
