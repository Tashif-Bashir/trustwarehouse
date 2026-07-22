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

export interface Metrics {
  asOf: string // ISO timestamp of when the source produced these numbers
  source: string // human label shown in the header subtitle
  agents: AgentMetrics[]
}
