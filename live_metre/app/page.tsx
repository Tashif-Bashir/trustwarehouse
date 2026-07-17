'use client'

import { useEffect, useRef, useState } from 'react'
import Header from '@/components/Header'
import Leaderboard from '@/components/Leaderboard'
import MiniBarChart from '@/components/MiniBarChart'
import SummaryCards, { formatTalktime } from '@/components/SummaryCards'
import { POLL_INTERVAL_MS, STALE_AFTER_MS } from '@/lib/config'
import type { Metrics } from '@/lib/types'

export default function Wallboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [flashingIds, setFlashingIds] = useState<Set<string>>(new Set())
  const prevAppointments = useRef<Map<string, number>>(new Map())
  const flashTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false

    async function refresh() {
      try {
        const res = await fetch('/api/metrics', { cache: 'no-store' })
        if (!res.ok) return
        const data: Metrics = await res.json()
        if (cancelled) return

        // Pulse-highlight any agent whose appointment count just went up.
        const increased = data.agents
          .filter((a) => {
            const prev = prevAppointments.current.get(a.id)
            return prev !== undefined && a.appointmentsBooked > prev
          })
          .map((a) => a.id)
        prevAppointments.current = new Map(
          data.agents.map((a) => [a.id, a.appointmentsBooked])
        )
        if (increased.length > 0) {
          setFlashingIds(new Set(increased))
          if (flashTimeout.current) clearTimeout(flashTimeout.current)
          flashTimeout.current = setTimeout(() => setFlashingIds(new Set()), 2600)
        }

        setMetrics(data)
        setLastFetchedAt(Date.now())
      } catch {
        // keep the last good numbers; the pill goes amber once stale
      }
    }

    refresh()
    const poll = setInterval(refresh, POLL_INTERVAL_MS)
    const tick = setInterval(() => setNowMs(Date.now()), 1000)
    return () => {
      cancelled = true
      clearInterval(poll)
      clearInterval(tick)
      if (flashTimeout.current) clearTimeout(flashTimeout.current)
    }
  }, [])

  const secondsAgo =
    lastFetchedAt === null ? null : Math.max(0, Math.floor((nowMs - lastFetchedAt) / 1000))
  const stale = lastFetchedAt === null || nowMs - lastFetchedAt > STALE_AFTER_MS
  const agents = metrics?.agents ?? []

  return (
    <main className="mx-auto flex max-w-[1400px] flex-col gap-5 p-6 lg:p-10">
      <Header
        source={metrics?.source ?? '—'}
        secondsAgo={secondsAgo}
        stale={stale}
      />

      <SummaryCards agents={agents} />

      {agents.length > 0 && <Leaderboard agents={agents} flashingIds={flashingIds} />}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MiniBarChart
          title="Outbound calls"
          bars={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: a.outboundCalls,
            label: String(a.outboundCalls),
          }))}
        />
        <MiniBarChart
          title="Calls over 30s"
          bars={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: a.callsOver30s,
            label:
              a.outboundCalls > 0
                ? `${a.callsOver30s} (${Math.round((a.callsOver30s / a.outboundCalls) * 100)}%)`
                : '0',
          }))}
        />
        <MiniBarChart
          title="Outbound talktime"
          bars={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: a.talktimeSeconds,
            label: formatTalktime(a.talktimeSeconds),
          }))}
        />
      </section>
    </main>
  )
}
