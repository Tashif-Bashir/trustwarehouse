import type { AgentMetrics } from '@/lib/types'

export function formatTalktime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export default function SummaryCards({ agents }: { agents: AgentMetrics[] }) {
  const total = (pick: (a: AgentMetrics) => number) =>
    agents.reduce((sum, a) => sum + pick(a), 0)

  const cards = [
    { label: 'Outbound calls', value: String(total((a) => a.outboundCalls)) },
    { label: 'Calls over 30s', value: String(total((a) => a.callsOver30s)) },
    { label: 'Total talktime', value: formatTalktime(total((a) => a.talktimeSeconds)) },
    { label: 'Appointments', value: String(total((a) => a.appointmentsBooked)) },
  ]

  return (
    <section className="grid grid-cols-2 gap-5 lg:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded-xl bg-neutral-900 px-7 py-6">
          <p className="text-lg text-neutral-400">{card.label}</p>
          <p className="mt-2 text-6xl font-semibold tabular-nums tracking-tight">
            {card.value}
          </p>
        </div>
      ))}
    </section>
  )
}
