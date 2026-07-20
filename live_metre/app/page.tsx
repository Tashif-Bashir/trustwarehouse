'use client'

import { useEffect, useRef, useState } from 'react'
import Celebration from '@/components/Celebration'
import ColumnChart from '@/components/ColumnChart'
import Header from '@/components/Header'
import Leaderboard from '@/components/Leaderboard'
import SummaryCards from '@/components/SummaryCards'
import { CELEBRATION, POLL_INTERVAL_MS, STALE_AFTER_MS } from '@/lib/config'
import type { AgentMetrics, Metrics } from '@/lib/types'

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

  // ── End-of-day celebration: 16:59 UK on weekdays, once per day per
  //    screen; ?celebrate=1 forces a demo run any time. ──
  const [celebrating, setCelebrating] = useState<AgentMetrics[] | null>(null)
  const celebrationTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const demoDone = useRef(false)

  useEffect(() => {
    if (celebrating) return
    const list = metrics?.agents ?? []
    if (!list.length) return
    const max = Math.max(...list.map((a) => a.appointmentsBooked))
    if (max < 1) return // nothing to celebrate on a dead day

    const forced = new URLSearchParams(window.location.search).has('celebrate')
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(
      new Date(nowMs)
    )
    if (forced) {
      if (demoDone.current) return
      demoDone.current = true
    } else {
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/London',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(new Date(nowMs))
      const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
      if (CELEBRATION.weekdaysOnly && ['Sat', 'Sun'].includes(get('weekday'))) return
      const mins = Number(get('hour')) * 60 + Number(get('minute'))
      const start = CELEBRATION.hour * 60 + CELEBRATION.minute
      if (mins < start || mins >= start + CELEBRATION.graceMinutes) return
      if (localStorage.getItem('metre:celebrated') === today) return
      localStorage.setItem('metre:celebrated', today)
    }

    setCelebrating(list.filter((a) => a.appointmentsBooked === max))
    celebrationTimer.current = setTimeout(() => setCelebrating(null), CELEBRATION.durationMs)
  }, [nowMs, metrics, celebrating])

  useEffect(
    () => () => {
      if (celebrationTimer.current) clearTimeout(celebrationTimer.current)
    },
    []
  )

  const secondsAgo =
    lastFetchedAt === null ? null : Math.max(0, Math.floor((nowMs - lastFetchedAt) / 1000))
  const stale = lastFetchedAt === null || nowMs - lastFetchedAt > STALE_AFTER_MS
  const agents = metrics?.agents ?? []

  return (
    <main className="mx-auto flex max-w-[1500px] flex-col gap-10 p-6 lg:p-10">
      <div className="fade-up">
        <Header
          source={metrics?.source ?? '—'}
          secondsAgo={secondsAgo}
          stale={stale}
        />
      </div>

      <SummaryCards agents={agents} />

      {agents.length > 0 && <Leaderboard agents={agents} flashingIds={flashingIds} />}

      <section className="grid grid-cols-1 gap-10 md:grid-cols-3">
        <ColumnChart
          title="Total calls (in + out)"
          delayMs={480}
          columns={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: a.totalCalls,
            label: String(a.totalCalls),
          }))}
        />
        <ColumnChart
          title="Calls over 1 min"
          delayMs={560}
          columns={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: a.callsOver1m,
            label:
              a.totalCalls > 0
                ? `${a.callsOver1m} (${Math.round((a.callsOver1m / a.totalCalls) * 100)}%)`
                : '0',
          }))}
        />
        <ColumnChart
          title="Total talktime (mins)"
          delayMs={640}
          columns={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: Math.round(a.talktimeSeconds / 60),
            label: String(Math.round(a.talktimeSeconds / 60)),
          }))}
        />
      </section>

      {celebrating && <Celebration winners={celebrating} />}
    </main>
  )
}
