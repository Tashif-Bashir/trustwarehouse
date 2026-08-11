'use client'

import { useMemo } from 'react'
import type { DoorsMetrics, SalesMetrics } from '@/lib/types'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`

// Inline SVG sunrise mark — never emoji, the Pi's Chromium has no colour
// emoji font (see SalesTiles.tsx's heating/water icons for the same rule).
function SunriseIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 40" className={className} aria-hidden>
      <path
        d="M6 34a26 26 0 0 1 52 0"
        fill="none"
        stroke="#fbbf24"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx="32" cy="34" r="9" fill="#fbbf24" />
      <path
        d="M2 34h60M14 40h36"
        stroke="#fbbf24"
        strokeWidth="2.5"
        strokeLinecap="round"
        opacity="0.55"
      />
    </svg>
  )
}

// Working weekdays remaining in the current UK month, INCLUDING today —
// denominator for "today's number". Mirrors the Date.UTC + Europe/London
// date-string parsing pattern used throughout lib/provider/bronze.ts.
function workingWeekdaysRemaining(nowMs: number): number {
  const todayUk = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London' }).format(
    new Date(nowMs)
  )
  const [y, m, d] = todayUk.split('-').map(Number)
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate()
  let count = 0
  for (let day = d; day <= daysInMonth; day++) {
    const dow = new Date(Date.UTC(y, m - 1, day)).getUTCDay() // 0 = Sun, 6 = Sat
    if (dow !== 0 && dow !== 6) count++
  }
  return count
}

// Full-screen "doors open" morning takeover for BOTH boards — softer than
// the EOD confetti (EodCelebration.tsx): a warm sunrise gradient, no sound,
// full-width stacked rows (no three-across — Pi-safe per the wallboard
// layout rule). The parent (Wallboard) mounts/unmounts this on a timer.
export default function DoorsCelebration({
  isSalesBoard,
  sales,
  doors,
  nowMs,
}: {
  isSalesBoard: boolean
  sales?: SalesMetrics
  doors?: DoorsMetrics
  nowMs: number
}) {
  // Today's number: what's left of the month target, spread over the working
  // weekdays remaining (today included). Only shown when a target exists —
  // hides gracefully otherwise, same rule TargetBar/LastSaleBanner follow.
  const todaysNumber = useMemo(() => {
    if (!sales || sales.monthTarget === null || sales.monthTarget <= 0) return null
    const remaining = Math.max(1, workingWeekdaysRemaining(nowMs))
    const gap = sales.monthTarget - sales.monthRevenue
    return Math.max(0, gap) / remaining
  }, [sales, nowMs])

  return (
    <div className="doors-takeover fixed inset-0 z-50 flex flex-col items-center justify-center gap-10 overflow-hidden px-10">
      <SunriseIcon className="fade-up h-16 w-24" />

      <div className="fade-up font-display text-3xl font-medium uppercase tracking-[0.35em] text-neutral-300">
        Good morning
      </div>

      {isSalesBoard && sales && (
        <div
          className="fade-up flex w-full max-w-3xl flex-col items-center gap-3"
          style={{ animationDelay: '150ms' }}
        >
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
            Yesterday domestic
          </p>
          <p className="font-display text-8xl font-semibold leading-none tracking-tight tabular-nums text-neutral-50">
            {gbp(sales.yesterdayRevenue)}
          </p>
          <p className="text-2xl text-neutral-400">
            <span className="font-semibold text-neutral-200 tabular-nums">
              {sales.yesterdayCount}
            </span>{' '}
            sale{sales.yesterdayCount === 1 ? '' : 's'}
          </p>
        </div>
      )}

      {isSalesBoard && todaysNumber !== null && (
        <div
          className="fade-up w-full max-w-3xl rounded-xl border-[0.5px] border-hairline bg-black/20 px-8 py-5 text-center"
          style={{ animationDelay: '300ms' }}
        >
          <p className="text-2xl text-neutral-200">
            Today&apos;s number:{' '}
            <span className="font-display text-4xl font-semibold text-amber-300 tabular-nums">
              {gbp(todaysNumber)}
            </span>{' '}
            keeps us on pace
          </p>
        </div>
      )}

      {!isSalesBoard && (
        <div
          className="fade-up flex w-full max-w-3xl flex-col items-center gap-3"
          style={{ animationDelay: '150ms' }}
        >
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
            Yesterday&apos;s appointments
          </p>
          <p className="font-display text-8xl font-semibold leading-none tracking-tight tabular-nums text-neutral-50">
            {doors?.yesterdayAppointments ?? 0}
          </p>
          {doors?.yesterdayTopBooker && (
            <p className="text-2xl text-neutral-400">
              top booker{' '}
              <span className="font-semibold text-neutral-200">{doors.yesterdayTopBooker}</span>
            </p>
          )}
        </div>
      )}

      {!isSalesBoard && typeof doors?.freshLeadsOvernight === 'number' && (
        <div
          className="fade-up w-full max-w-3xl rounded-xl border-[0.5px] border-hairline bg-black/20 px-8 py-5 text-center"
          style={{ animationDelay: '300ms' }}
        >
          <p className="text-2xl text-neutral-200">
            <span className="font-display text-4xl font-semibold text-amber-300 tabular-nums">
              {doors.freshLeadsOvernight}
            </span>{' '}
            new lead{doors.freshLeadsOvernight === 1 ? '' : 's'} to chase — first hour is gold
          </p>
        </div>
      )}
    </div>
  )
}
