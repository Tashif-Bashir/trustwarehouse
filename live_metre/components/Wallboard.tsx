'use client'

import { useEffect, useRef, useState } from 'react'
import Celebration from '@/components/Celebration'
import ColumnChart from '@/components/ColumnChart'
import DoorsCelebration from '@/components/DoorsCelebration'
import EodCelebration from '@/components/EodCelebration'
import Header from '@/components/Header'
import Leaderboard from '@/components/Leaderboard'
import PipelineTakeover from '@/components/PipelineTakeover'
import { BarRow, LastSaleBanner, StatBarList, StaticSalesKpis } from '@/components/SalesTiles'
import SummaryCards from '@/components/SummaryCards'
import {
  BOARDS, CELEBRATION, DOORS_CELEBRATION, EOD_CELEBRATION, PIPELINE_TAKEOVER, POLL_INTERVAL_MS,
  SALES_SOUND, STALE_AFTER_MS,
} from '@/lib/config'
import {
  FileSoundHandle, playFileSound, playSaleSound, primeSaleFile, tryAutoUnlock, unlockSound,
} from '@/lib/sound'
import type { AgentMetrics, Metrics } from '@/lib/types'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`
// Fade-out length when the EOD clip is cut short by the takeover ending or the
// board unmounting — the track (212s) far outlasts the ~45s takeover.
const EOD_SOUND_FADE_MS = 2000
const sellerRows = (list: { name: string; color: string; total: number; count: number }[]): BarRow[] =>
  list.map((r) => ({
    key: r.name.toLowerCase(),
    name: r.name,
    color: r.color,
    value: r.total,
    valueLabel: gbp(r.total),
    subs: [String(r.count)],
  }))

// Calls: total drives the bar, with over-1min (and its %) and talktime as
// trailing columns — the three charts the rotating board used a whole view for.
const callRows = (agents: AgentMetrics[]): BarRow[] =>
  agents.map((a) => ({
    key: a.id,
    name: a.name,
    color: a.color,
    value: a.totalCalls,
    valueLabel: String(a.totalCalls),
    subs: [
      a.totalCalls > 0
        ? `${a.callsOver1m} (${Math.round((a.callsOver1m / a.totalCalls) * 100)}%)`
        : '0',
      String(Math.round(a.talktimeSeconds / 60)),
    ],
  }))

// Team totals, previously the SummaryCards strip on the calls view.
const callTotals = (agents: AgentMetrics[]) => {
  const sum = (f: (a: AgentMetrics) => number) => agents.reduce((n, a) => n + f(a), 0)
  const mins = Math.round(sum((a) => a.talktimeSeconds) / 60)
  return `${sum((a) => a.totalCalls)} calls · ${sum((a) => a.callsOver1m)} over 1m · ${mins} mins talk`
}

export default function Wallboard({ boardId }: { boardId: string }) {
  const board = BOARDS[boardId] ?? BOARDS.telesales
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
        // ?doors=1 forwards ?morning=1 so the demo takeover has fresh-leads
        // data even outside the real morning window — an ordinary poll never
        // sets this, so the server only pays for that query in the window
        // itself (see app/api/metrics/route.ts).
        const forceMorning = new URLSearchParams(window.location.search).has('doors')
        const res = await fetch(
          `/api/metrics?board=${board.id}${forceMorning ? '&morning=1' : ''}`,
          { cache: 'no-store' }
        )
        if (!res.ok) return
        const data: Metrics = await res.json()
        if (cancelled) return

        // Pulse-highlight any agent whose appointment count just went up.
        if (board.features.appointments) {
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
  }, [board.id, board.features.appointments])

  // ── End-of-day celebration (telesales board only): 16:59 UK weekdays,
  //    once per day per screen; ?celebrate=1 forces a demo run. ──
  const [celebrating, setCelebrating] = useState<AgentMetrics[] | null>(null)
  const celebrationTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const demoDone = useRef(false)

  useEffect(() => {
    if (!board.features.celebration || celebrating) return
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
      // Friday finishes at 16:00 — its celebration runs at 15:59
      const t = get('weekday') === 'Fri' ? CELEBRATION.friday : CELEBRATION
      const start = t.hour * 60 + t.minute
      if (mins < start || mins >= start + CELEBRATION.graceMinutes) return
      if (localStorage.getItem('metre:celebrated') === today) return
      localStorage.setItem('metre:celebrated', today)
    }

    setCelebrating(list.filter((a) => a.appointmentsBooked === max))
    celebrationTimer.current = setTimeout(() => setCelebrating(null), CELEBRATION.durationMs)
  }, [nowMs, metrics, celebrating, board.features.celebration])

  useEffect(
    () => () => {
      if (celebrationTimer.current) clearTimeout(celebrationTimer.current)
    },
    []
  )

  // ── End-of-day celebration (SALES & OPS STATIC BOARD ONLY — gated on
  //    board.features.sales, which only the team board has, same as the coins
  //    effects below): this UK time, EVERY weekday (no Friday exception, unlike
  //    the telesales CELEBRATION above), once per day per screen; ?eod=1 forces
  //    a demo run without marking the day as celebrated. Unrelated to, and
  //    does not touch, the telesales celebration above. ──
  const [eodCelebrating, setEodCelebrating] = useState(false)
  const eodTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const eodDemoDone = useRef(false)
  // The clip runs far longer than the takeover (212s vs ~45s) — fire-and-forget
  // left it playing under the board long after the takeover unmounted. Keep the
  // handle so the timer (and any unmount) can fade it out instead.
  const eodSound = useRef<FileSoundHandle | null>(null)

  useEffect(() => {
    if (!board.features.sales || !EOD_CELEBRATION.enabled || eodCelebrating) return
    if (!metrics?.sales) return

    const forced = new URLSearchParams(window.location.search).has('eod')
    if (forced) {
      if (eodDemoDone.current) return
      eodDemoDone.current = true
    } else {
      const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(
        new Date(nowMs)
      )
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/London',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(new Date(nowMs))
      const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
      if (EOD_CELEBRATION.weekdaysOnly && ['Sat', 'Sun'].includes(get('weekday'))) return
      const mins = Number(get('hour')) * 60 + Number(get('minute'))
      const start = EOD_CELEBRATION.hour * 60 + EOD_CELEBRATION.minute
      if (mins < start || mins >= start + EOD_CELEBRATION.graceMinutes) return
      if (localStorage.getItem('metre:eod-celebrated') === today) return
      localStorage.setItem('metre:eod-celebrated', today)
    }

    setEodCelebrating(true)
    // FAIL SOFT: a missing/undecodable clip plays nothing (no synth fallback,
    // unlike the sale ka-ching) — the takeover itself is never blocked on audio.
    // file: null = music retired (owner 20 Aug 2026); the takeover runs silent.
    if (EOD_CELEBRATION.sound.file) {
      eodSound.current = playFileSound(EOD_CELEBRATION.sound.file, {
        volume: EOD_CELEBRATION.sound.volume,
      })
    }
    eodTimer.current = setTimeout(() => {
      setEodCelebrating(false)
      // The clip outlasts the takeover, so fade it out here rather than let it
      // keep playing under the board once the DOM has already unmounted.
      eodSound.current?.stop(EOD_SOUND_FADE_MS)
      eodSound.current = null
    }, EOD_CELEBRATION.durationMs)
  }, [nowMs, metrics, eodCelebrating, board.features.sales])

  useEffect(
    () => () => {
      if (eodTimer.current) clearTimeout(eodTimer.current)
      // Board navigated away / unmounted mid-takeover — same fade-out, not an
      // abrupt cut. stop() no-ops if the timer callback already fired.
      eodSound.current?.stop(EOD_SOUND_FADE_MS)
      eodSound.current = null
    },
    []
  )

  // ── Doors-open morning takeover (BOTH boards): 08:50 UK weekdays, once per
  //    day per screen; ?doors=1 forces a demo run without marking the day.
  //    No sound (owner brief). If ?eod=1 is ALSO in the URL, EOD wins — we
  //    check the raw param here (not eodCelebrating state) so the two demo
  //    effects can't race on the same mount. ──
  const [doorsCelebrating, setDoorsCelebrating] = useState(false)
  const doorsTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const doorsDemoDone = useRef(false)

  useEffect(() => {
    if (!DOORS_CELEBRATION.enabled || doorsCelebrating) return
    if (!metrics) return

    const search = new URLSearchParams(window.location.search)
    if (search.has('eod')) return // EOD wins when both are forced in a demo

    const forced = search.has('doors')
    if (forced) {
      if (doorsDemoDone.current) return
      doorsDemoDone.current = true
    } else {
      const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(
        new Date(nowMs)
      )
      const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Europe/London',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(new Date(nowMs))
      const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
      if (DOORS_CELEBRATION.weekdaysOnly && ['Sat', 'Sun'].includes(get('weekday'))) return
      const mins = Number(get('hour')) * 60 + Number(get('minute'))
      const start = DOORS_CELEBRATION.hour * 60 + DOORS_CELEBRATION.minute
      if (mins < start || mins >= start + DOORS_CELEBRATION.graceMinutes) return
      if (localStorage.getItem('metre:doors-celebrated') === today) return
      localStorage.setItem('metre:doors-celebrated', today)
    }

    setDoorsCelebrating(true)
    doorsTimer.current = setTimeout(() => setDoorsCelebrating(false), DOORS_CELEBRATION.durationMs)
  }, [nowMs, metrics, doorsCelebrating])

  useEffect(
    () => () => {
      if (doorsTimer.current) clearTimeout(doorsTimer.current)
    },
    []
  )

  // ── Rep pipeline takeover (SALES & OPS board only): unlike the once-per-
  //    day celebrations above, this recurs all day the board is up — every
  //    PIPELINE_TAKEOVER.everyMs of normal board time it shows full-screen
  //    for .durationMs, then melts back, indefinitely. ?pipeline=1 forces one
  //    immediate demo showing; the recurring cadence carries on after it
  //    ends. Actual visibility is also gated at render time against
  //    eodCelebrating/doorsCelebrating and an empty pipeline (celebrations
  //    win; nothing to chase means nothing to show), so this timer only
  //    needs to track "is it that point in the cycle" — not who else is on
  //    screen. ──
  const [pipelineShowing, setPipelineShowing] = useState(false)
  const pipelineShowTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pipelineHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pipelineForceDone = useRef(false)

  useEffect(() => {
    if (!board.features.pipeline || !PIPELINE_TAKEOVER.enabled) return

    function armNextShowing(delay: number) {
      pipelineShowTimer.current = setTimeout(() => {
        const weekday = new Intl.DateTimeFormat('en-GB', {
          timeZone: 'Europe/London',
          weekday: 'short',
        }).format(new Date())
        if (PIPELINE_TAKEOVER.weekdaysOnly && ['Sat', 'Sun'].includes(weekday)) {
          armNextShowing(PIPELINE_TAKEOVER.everyMs)
          return
        }
        setPipelineShowing(true)
        pipelineHideTimer.current = setTimeout(() => {
          setPipelineShowing(false)
          armNextShowing(PIPELINE_TAKEOVER.everyMs)
        }, PIPELINE_TAKEOVER.durationMs)
      }, delay)
    }

    const forced = new URLSearchParams(window.location.search).has('pipeline')
    if (forced && !pipelineForceDone.current) {
      pipelineForceDone.current = true
      armNextShowing(0)
    } else {
      armNextShowing(PIPELINE_TAKEOVER.everyMs)
    }

    return () => {
      if (pipelineShowTimer.current) clearTimeout(pipelineShowTimer.current)
      if (pipelineHideTimer.current) clearTimeout(pipelineHideTimer.current)
    }
  }, [board.features.pipeline])

  // ── Coins when a new sale lands. Keyed on the month's SALE COUNT so it
  //    fires once per sale, not once per revenue card, and never on the first
  //    paint (or the board would ring every time a screen reloads). ──
  const [soundLocked, setSoundLocked] = useState(false)
  // Bumped on each new sale; StaticSalesKpis watches it and runs the three
  // cards through a staggered pop so the screen celebrates in time with the till.
  const [salePulse, setSalePulse] = useState(0)
  const prevSaleCount = useRef<number | null>(null)
  const prevMonthRevenue = useRef(0)

  useEffect(() => {
    if (!board.features.sales || !SALES_SOUND.enabled) return
    // A wall screen has nobody to click anything, so try to arm audio on our
    // own first — that works when the kiosk is launched with
    // --autoplay-policy=no-user-gesture-required. Only if the browser refuses
    // do we fall back to showing the badge.
    let cancelled = false
    tryAutoUnlock().then((armed) => {
      if (cancelled) return
      setSoundLocked(!armed)
      if (armed) {
        primeSaleFile(SALES_SOUND.file)
        // Pre-decode the end-of-day clip too, so it's ready to fire the moment
        // the 16:59 gate opens instead of racing a fetch at takeover time.
        if (EOD_CELEBRATION.enabled && EOD_CELEBRATION.sound.file) {
          primeSaleFile(EOD_CELEBRATION.sound.file)
        }
      }
      // ?sound=1 fires the whole celebration — sound and card pop — once, so it
      // can be checked without waiting for a real sale.
      if (new URLSearchParams(window.location.search).has('sound')) {
        setSalePulse((p) => p + 1)
        if (armed) {
          playSaleSound({
            volume: SALES_SOUND.volume, amount: 12_000, style: SALES_SOUND.style,
            file: SALES_SOUND.file, repeat: SALES_SOUND.repeat,
          })
        }
      }
    })
    return () => {
      cancelled = true
    }
  }, [board.features.sales])

  // ?demo=1 replays the celebration every few seconds so it can be judged on
  // the actual wall screen without waiting for real sales to land.
  useEffect(() => {
    if (!board.features.sales) return
    if (!new URLSearchParams(window.location.search).has('demo')) return
    const t = setInterval(() => {
      setSalePulse((p) => p + 1)
      playSaleSound({
        volume: SALES_SOUND.volume, amount: 12_000, style: SALES_SOUND.style,
        file: SALES_SOUND.file, repeat: SALES_SOUND.repeat,
      })
    }, 7500)
    return () => clearInterval(t)
  }, [board.features.sales])

  useEffect(() => {
    const sales = metrics?.sales
    if (!board.features.sales || !sales) return
    const count = sales.monthCount
    const prev = prevSaleCount.current
    if (prev !== null && count > prev) {
      // the visual celebration runs whether or not audio was ever unlocked
      setSalePulse((p) => p + 1)
    }
    if (!SALES_SOUND.enabled) {
      prevSaleCount.current = count
      prevMonthRevenue.current = sales.monthRevenue
      return
    }
    if (prev !== null && count > prev) {
      playSaleSound({
        volume: SALES_SOUND.volume,
        style: SALES_SOUND.style,
        file: SALES_SOUND.file,
        repeat: SALES_SOUND.repeat,
        amount: Math.max(0, sales.monthRevenue - prevMonthRevenue.current),
      })
    }
    prevSaleCount.current = count
    prevMonthRevenue.current = sales.monthRevenue
  }, [metrics?.sales, board.features.sales])

  const secondsAgo =
    lastFetchedAt === null ? null : Math.max(0, Math.floor((nowMs - lastFetchedAt) / 1000))
  const stale = lastFetchedAt === null || nowMs - lastFetchedAt > STALE_AFTER_MS
  const agents = metrics?.agents ?? []
  const rolesLegend = board.agents
    .filter((a) => a.role)
    .map((a) => `${a.name} — ${a.role}`)
    .join(' · ')

  const callsSection = (
    <>
      <SummaryCards agents={agents} showAppointments={board.features.appointments} />

      {board.features.leaderboard && agents.length > 0 && (
        <Leaderboard agents={agents} flashingIds={flashingIds} />
      )}

      <section className="grid grid-cols-1 gap-10 md:grid-cols-3">
        <ColumnChart
          title="Total calls (in + out)"
          delayMs={board.features.leaderboard ? 480 : 240}
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
          delayMs={board.features.leaderboard ? 560 : 320}
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
          delayMs={board.features.leaderboard ? 640 : 400}
          columns={agents.map((a) => ({
            id: a.id,
            name: a.name,
            color: a.color,
            value: Math.round(a.talktimeSeconds / 60),
            label: String(Math.round(a.talktimeSeconds / 60)),
          }))}
        />
      </section>
    </>
  )

  const sales = board.features.sales ? metrics?.sales : undefined

  return (
    <main className="mx-auto flex max-w-[1760px] flex-col gap-8 p-6 lg:p-8">
      <div className="fade-up">
        <Header
          title={board.title}
          source={metrics?.source ?? '—'}
          secondsAgo={secondsAgo}
          stale={stale}
        />
        {rolesLegend && <p className="mt-2 text-base text-neutral-500">{rolesLegend}</p>}
      </div>

      {sales && soundLocked && (
        // Shown once per page load: browsers won't play the ka-ching until the
        // page has had a real click. One tap on the wall screen and it's armed.
        <button
          type="button"
          onClick={() => {
            void unlockSound().then((armed) => {
              if (!armed) return
              primeSaleFile(SALES_SOUND.file)
              playSaleSound({
                volume: SALES_SOUND.volume, amount: 12_000, style: SALES_SOUND.style,
                file: SALES_SOUND.file, repeat: SALES_SOUND.repeat,
              })
              setSoundLocked(false)
            })
          }}
          className="fade-up self-start rounded-lg border-[0.5px] border-hairline bg-surface px-5 py-2.5 text-base font-medium text-neutral-300 transition-colors hover:text-white"
        >
          🔔 Tap once to enable the sale sound
        </button>
      )}

      {sales ? (
        // Everything on one screen, nothing rotates: reps ranked on the left;
        // month/week/today + Dec&Josh + calls stacked on the right.
        <div className="flex flex-col gap-7">
          <LastSaleBanner sales={sales} />
          <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
            <div className="rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6">
              <StatBarList
                title="Reps — sold this month"
                rows={sellerRows(sales.reps)}
                columns={['Sold', 'Sales']}
              />
            </div>
            <div className="flex flex-col gap-7">
              <StaticSalesKpis sales={sales} pulse={salePulse} />
              <div className="rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6">
                <StatBarList
                  title="Dec & Josh — sold this month"
                  rows={sellerRows(sales.sellers)}
                  columns={['Sold', 'Sales']}
                />
              </div>
              <div className="rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6">
                <StatBarList
                  title="Calls today"
                  rows={callRows(agents)}
                  columns={['Calls', '1 min+', 'Mins']}
                  totals={callTotals(agents)}
                />
              </div>
            </div>
          </div>
        </div>
      ) : (
        callsSection
      )}

      {celebrating && <Celebration winners={celebrating} />}
      {eodCelebrating && sales && <EodCelebration sales={sales} />}
      {/* EOD wins if both are somehow active (see the gating effect above —
          this is a belt-and-braces second check). */}
      {doorsCelebrating && !eodCelebrating && (
        <DoorsCelebration
          isSalesBoard={board.features.sales}
          sales={sales}
          doors={metrics?.doors}
          nowMs={nowMs}
        />
      )}
      {/* Celebrations win: never show the pipeline takeover over EOD/DOORS,
          and never show it with nothing to chase. */}
      {pipelineShowing &&
        !eodCelebrating &&
        !doorsCelebrating &&
        metrics?.pipeline &&
        metrics.pipeline.count > 0 && <PipelineTakeover pipeline={metrics.pipeline} />}
    </main>
  )
}
