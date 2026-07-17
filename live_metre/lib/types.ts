export interface AgentMetrics {
  id: string
  name: string
  color: string
  outboundCalls: number
  callsOver30s: number
  talktimeSeconds: number
  appointmentsBooked: number
}

export interface Metrics {
  asOf: string // ISO timestamp of when the source produced these numbers
  source: string // human label shown in the header subtitle
  agents: AgentMetrics[]
}
