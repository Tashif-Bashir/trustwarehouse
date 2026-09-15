'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { REP_WEEK_TAKEOVER } from '@/lib/config'
import type { RepWeekMetrics, RepWeekRow, RepWeekWeek } from '@/lib/types'

// Fade back to the live board just before the parent unmounts us, so the
// return is never a hard cut (same trick as PipelineTakeover).
const EXIT_MS = 500

// Smallest cell the fit loop will shrink to before it gives up — below this
// the numbers stop being readable from the floor anyway.
const MIN_CELL_PX = 14

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
// Spelled out rather than taken from Intl: en-GB's short month renders
// September as "Sept", which is a character wider than every other month and
// nudges the column headings around. The approved preview uses "Sep".
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// '2026-09-14' -> '14 Sep'. Straight string arithmetic, no Date and no
// timezone to get wrong: these are already Europe/London calendar dates.
function dayStamp(iso: string): string {
  const [, month, day] = iso.split('-')
  return `${day} ${MONTHS[Number(month) - 1] ?? month}`
}

// A rep's Sat/Sun only count if they actually work weekends; everyone else
// shows those two columns dimmed rather than as holes (owner, 14 Sep 2026).
const isOffDay = (row: RepWeekRow, i: number) => i >= 5 && !row.weekendWorker

function cellClass(row: RepWeekRow, i: number, iso: string, today: string): string {
  if (isOffDay(row, i)) return iso === today ? 'off today' : 'off'
  const n = row.days[i]
  const parts = [n === 0 ? 'n0' : n === 1 ? 'n1' : n === 2 ? 'n2' : 'n3']
  if (iso < today) parts.push('past')
  if (iso === today) parts.push('today')
  return parts.join(' ')
}

function WeekPanel({
  week,
  today,
  active,
  panelRef,
}: {
  week: RepWeekWeek
  today: string
  active: boolean
  panelRef: (el: HTMLElement | null) => void
}) {
  const ticks = week.rows.length > 1 ? week.rows.length - 1 : 0
  return (
    <section
      ref={panelRef}
      className={`repweek-week absolute inset-0 flex flex-col ${active ? 'on' : ''}`}
    >
      <div className="mb-2.5 grid grid-cols-[1fr_auto_1fr] items-center">
        <h2 className="m-0 font-display text-[2.6vh] font-semibold uppercase tracking-[0.06em] text-[#171a2b]">
          {week.label}
        </h2>
        <div className="flex items-end justify-self-center gap-[2.2vw]">
          <div className="flex flex-col items-end leading-none">
            <span className="repweek-stat-n gaps pulse-dot">{week.teamGaps}</span>
            <span className="mt-[0.5vh] whitespace-nowrap text-[1.5vh] text-[#9aa0b4]">
              gaps to fill
            </span>
          </div>
          <div className="flex flex-col items-end leading-none">
            <span className="repweek-stat-n">{week.teamTotal}</span>
            <span className="mt-[0.5vh] whitespace-nowrap text-[1.5vh] text-[#9aa0b4]">
              booked
            </span>
          </div>
          <div className="flex flex-col items-end leading-none">
            <span className="repweek-stat-n">{week.fillPct}%</span>
            <span className="mt-[0.5vh] whitespace-nowrap text-[1.5vh] text-[#9aa0b4]">
              of {week.capacity} slots
            </span>
          </div>
          {week.emptiestDay && (
            <div className="flex flex-col items-end leading-none">
              <span className="repweek-stat-n hole">{week.emptiestDay.label}</span>
              <span className="mt-[0.5vh] whitespace-nowrap text-[1.5vh] text-[#9aa0b4]">
                emptiest day &middot; {week.emptiestDay.holes} holes
              </span>
            </div>
          )}
          <div className="w-[18vw] self-center">
            <div className={`repweek-fill-bar${week.fillPct < 50 ? ' low' : ''}`}>
              <i style={{ width: `${week.fillPct}%` }} />
            </div>
            <div className="repweek-fill-ticks">
              {Array.from({ length: ticks }, (_, k) => (
                <b key={k} style={{ left: `${((k + 1) * 100) / week.rows.length}%` }} />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="repweek-tablewrap min-h-0 flex-1 overflow-hidden">
        <table className="repweek-table">
          <thead>
            <tr>
              <th className="rep">Rep</th>
              {week.days.map((iso, i) => (
                <th key={iso} className={iso === today ? 'today' : undefined}>
                  {DAY_LABELS[i]}
                  <small>{dayStamp(iso)}</small>
                </th>
              ))}
              <th>Total</th>
              <th>Gaps</th>
            </tr>
          </thead>
          <tbody>
            {week.rows.map((row) => (
              <tr key={row.name}>
                <th className="rep">
                  {row.name}
                  {row.weekendWorker && <em>weekends</em>}
                </th>
                {week.days.map((iso, i) => (
                  <td key={iso} className={cellClass(row, i, iso, today)}>
                    <span>{isOffDay(row, i) ? '' : row.days[i]}</span>
                  </td>
                ))}
                <td className="tot">{row.total}</td>
                <td className={row.gaps ? 'gap' : 'gap zero'}>{row.gaps}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th className="rep">Team</th>
              {week.teamDays.map((n, i) => (
                <td key={week.days[i]}>{n}</td>
              ))}
              <td className="tot">{week.teamTotal}</td>
              <td className="gap">{week.teamGaps}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  )
}

// Full-screen "rep week" takeover for the TELESALES board: how full the field
// reps' diaries are this week and next, and how many slots the floor still has
// to fill. Nothing scrolls — the table is measured and the row height shrunk
// until the Team row is inside the panel, then re-measured after webfonts land
// and on every resize. The parent (Wallboard) mounts/unmounts this on
// REP_WEEK_TAKEOVER's timer and never over a celebration.
export default function RepWeekTakeover({
  repWeek,
  durationMs = REP_WEEK_TAKEOVER.durationMs,
  slideMs = REP_WEEK_TAKEOVER.slideMs,
}: {
  repWeek: RepWeekMetrics
  durationMs?: number
  slideMs?: number
}) {
  const weeks = repWeek.weeks
  const [slide, setSlide] = useState(0)
  const [closing, setClosing] = useState(false)
  const panels = useRef<(HTMLElement | null)[]>([])

  // Measure each week and shrink the row height until the whole table —
  // Team row included — sits inside its panel. Both panels are in the DOM
  // (the hidden one is only transparent), so both can be measured up front
  // and neither pops when it comes round.
  const fit = useCallback(() => {
    for (const panel of panels.current) {
      if (!panel) continue
      const wrap = panel.querySelector<HTMLElement>('.repweek-tablewrap')
      const table = panel.querySelector<HTMLElement>('table')
      if (!wrap || !table || wrap.clientHeight === 0) continue
      const slots = panel.querySelectorAll('tbody tr').length + 3 // head, foot, breathing room
      const slotPx = wrap.clientHeight / slots
      let cell = Math.max(MIN_CELL_PX, Math.floor(slotPx * 0.82))
      let gap = Math.max(2, Math.floor(slotPx * 0.16))
      const apply = () => {
        panel.style.setProperty('--cell', `${cell}px`)
        panel.style.setProperty('--gapv', `${gap}px`)
      }
      apply()
      let guard = 40
      while (
        guard-- > 0 &&
        table.getBoundingClientRect().height > wrap.clientHeight - 2 &&
        cell > MIN_CELL_PX
      ) {
        cell -= 1
        gap = Math.max(2, Math.floor(gap * 0.9))
        apply()
      }
    }
  }, [])

  // Layout effect so the first painted frame is already fitted, then again
  // once the webfonts have swapped in (Barlow Condensed changes row height).
  useLayoutEffect(() => {
    fit()
    const timers = [150, 400, 900, 1800, 3500].map((ms) => setTimeout(fit, ms))
    window.addEventListener('resize', fit)
    if (typeof document !== 'undefined' && document.fonts) {
      void document.fonts.ready.then(fit)
    }
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null
    if (ro) {
      for (const panel of panels.current) {
        const wrap = panel?.querySelector('.repweek-tablewrap')
        if (wrap) ro.observe(wrap)
      }
    }
    return () => {
      timers.forEach(clearTimeout)
      window.removeEventListener('resize', fit)
      ro?.disconnect()
    }
  }, [fit, repWeek])

  // This week / next week, flipping while the takeover is up.
  useEffect(() => {
    if (weeks.length < 2) return
    const t = setInterval(() => setSlide((s) => (s + 1) % weeks.length), slideMs)
    return () => clearInterval(t)
  }, [weeks.length, slideMs])

  useEffect(() => {
    const t = setTimeout(() => setClosing(true), Math.max(0, durationMs - EXIT_MS))
    return () => clearTimeout(t)
  }, [durationMs])

  // Nothing scrolls while the takeover owns the screen: the board underneath
  // is taller than the viewport, and its scrollbar would otherwise sit down
  // the right-hand edge of an overlay that is meant to be the whole screen.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  return (
    <div
      className={`repweek fixed inset-0 z-50 flex flex-col overflow-hidden px-[2.2vw] py-[2.2vh] transition-all duration-500 ease-in ${
        closing ? 'scale-95 opacity-0' : 'scale-100 opacity-100'
      }`}
    >
      <div className="mb-1.5">
        <h1 className="m-0 font-display text-[3.6vh] font-semibold uppercase tracking-[0.04em]">
          Rep week
        </h1>
      </div>

      <div className="relative min-h-0 flex-1">
        {weeks.map((week, i) => (
          <WeekPanel
            key={week.label}
            week={week}
            today={repWeek.today}
            active={i === slide}
            panelRef={(el) => {
              panels.current[i] = el
            }}
          />
        ))}
      </div>

      <div className="flex justify-center gap-2 pt-[1vh]">
        {weeks.map((week, i) => (
          <i
            key={week.label}
            className={`h-2.5 w-2.5 rounded-full ${i === slide ? 'bg-[#171a2b]' : 'bg-[#c7cada]'}`}
          />
        ))}
      </div>

      <div className="flex flex-wrap justify-center gap-x-[14px] gap-y-1 pt-[0.6vh] text-[1.6vh] text-[#9aa0b4]">
        <span>
          <i className="mr-[5px] inline-block h-3 w-3 -translate-y-px rounded-[3px] bg-[#ffb3bf] align-middle" />
          0 &middot; a hole
        </span>
        <span>
          <i className="mr-[5px] inline-block h-3 w-3 -translate-y-px rounded-[3px] bg-[#f5d98a] align-middle" />
          1 &middot; light
        </span>
        <span>
          <i className="mr-[5px] inline-block h-3 w-3 -translate-y-px rounded-[3px] bg-[#a6e4cb] align-middle" />
          2 &middot; full
        </span>
        <span>
          <i className="mr-[5px] inline-block h-3 w-3 -translate-y-px rounded-[3px] bg-[#a9ddf7] align-middle" />
          3 &middot; over
        </span>
        <span>
          <i className="mr-[5px] inline-block h-3 w-3 -translate-y-px rounded-[3px] bg-[#e5e7ef] align-middle" />
          not a working day
        </span>
      </div>
    </div>
  )
}
