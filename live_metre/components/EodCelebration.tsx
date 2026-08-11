'use client'

import { useMemo } from 'react'
import type { SalesMetrics } from '@/lib/types'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`

// Full-screen end-of-day takeover for the SALES & OPS STATIC BOARD ONLY:
// today's domestic revenue, sale count, and (best-effort) today's seller.
// Confetti pattern/CSS classes borrowed straight from Celebration.tsx (the
// telesales top-performer takeover) — same .celebration/.confetti rules in
// globals.css, gold/white palette here since there's no per-agent "winner".
// The parent (Wallboard) mounts/unmounts this on a timer.
export default function EodCelebration({ sales }: { sales: SalesMetrics }) {
  const pieces = useMemo(() => {
    const palette = ['#fbbf24', '#34d399', '#38bdf8', '#ffffff']
    return Array.from({ length: 140 }, (_, i) => ({
      left: Math.random() * 100,
      delay: Math.random() * 5,
      duration: 4 + Math.random() * 4,
      size: 6 + Math.random() * 9,
      color: palette[i % palette.length],
    }))
  }, [])

  // SalesMetrics has no per-rep-per-day breakdown (reps/sellers are month-to-
  // date only, and adding one would mean a new BigQuery query — not allowed
  // here). Best-effort proxy: the last logged sale, ONLY when it was logged
  // TODAY. bronze.ts formats `atUk` as bare "HH:MM" for today's sale, "Yesterday
  // HH:MM" or "<day label> HH:MM" otherwise, so that shape tells today apart
  // without any new field.
  const todaysSale =
    sales.lastSale && /^\d{1,2}:\d{2}$/.test(sales.lastSale.atUk) ? sales.lastSale : null

  return (
    <div className="celebration fixed inset-0 z-50 flex flex-col items-center justify-center gap-8 overflow-hidden">
      {pieces.map((p, i) => (
        <span
          key={i}
          className="confetti"
          style={{
            left: `${p.left}%`,
            width: p.size,
            height: p.size * 0.45,
            backgroundColor: p.color,
            animationDelay: `${p.delay}s`,
            animationDuration: `${p.duration}s`,
          }}
        />
      ))}

      <div className="fade-up font-display text-3xl font-medium uppercase tracking-[0.35em] text-neutral-400">
        That&apos;s a wrap
      </div>

      <div
        className="fade-up flex flex-col items-center gap-3"
        style={{ animationDelay: '150ms' }}
      >
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
          Today domestic
        </p>
        <p className="font-display text-8xl font-semibold leading-none tracking-tight tabular-nums">
          {gbp(sales.todayRevenue)}
        </p>
        <p className="text-2xl text-neutral-400">
          <span className="font-semibold text-neutral-200 tabular-nums">{sales.todayCount}</span>{' '}
          sale{sales.todayCount === 1 ? '' : 's'} today
        </p>
      </div>

      {todaysSale && (
        <div
          className="fade-up flex items-center gap-4 font-display text-4xl font-semibold text-amber-400"
          style={{ animationDelay: '300ms' }}
        >
          {todaysSale.soldBy ?? 'Team'}
          <span className="text-neutral-500">&middot;</span>
          {gbp(todaysSale.amount)}
        </div>
      )}
    </div>
  )
}
