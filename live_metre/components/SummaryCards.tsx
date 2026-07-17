'use client'

import { useCountUp } from '@/lib/useCountUp'
import type { AgentMetrics } from '@/lib/types'

export function formatTalktime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function Card({
  label,
  value,
  format,
  delayMs,
}: {
  label: string
  value: number
  format: (v: number) => string
  delayMs: number
}) {
  const display = useCountUp(value)
  return (
    <div
      className="fade-up rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
        {label}
      </p>
      <p className="mt-2 font-display text-7xl font-semibold leading-none tracking-tight tabular-nums">
        {format(display)}
      </p>
    </div>
  )
}

export default function SummaryCards({ agents }: { agents: AgentMetrics[] }) {
  const total = (pick: (a: AgentMetrics) => number) =>
    agents.reduce((sum, a) => sum + pick(a), 0)

  return (
    <section className="grid grid-cols-2 gap-5 lg:grid-cols-4">
      <Card label="Outbound calls" value={total((a) => a.outboundCalls)} format={String} delayMs={80} />
      <Card label="Calls over 30s" value={total((a) => a.callsOver30s)} format={String} delayMs={160} />
      <Card
        label="Total talktime"
        value={total((a) => a.talktimeSeconds)}
        format={formatTalktime}
        delayMs={240}
      />
      <Card
        label="Appointments"
        value={total((a) => a.appointmentsBooked)}
        format={String}
        delayMs={320}
      />
    </section>
  )
}
