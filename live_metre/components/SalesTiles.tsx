'use client'

import { useEffect, useState } from 'react'
import ColumnChart from '@/components/ColumnChart'
import { SALES_SLIDE_MS } from '@/lib/config'
import type { SalesMetrics } from '@/lib/types'
import { useCountUp } from '@/lib/useCountUp'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`

// Hero tile: month revenue ⇄ week revenue, rotating on a timer. The key
// change re-triggers the fade so each slide breathes in.
function RevenueSlideshow({ sales }: { sales: SalesMetrics }) {
  const [slide, setSlide] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSlide((s) => (s + 1) % 2), SALES_SLIDE_MS)
    return () => clearInterval(t)
  }, [])

  const isMonth = slide === 0
  const label = isMonth ? `${sales.monthLabel} revenue` : 'This week revenue'
  const value = useCountUp(isMonth ? sales.monthRevenue : sales.weekRevenue)
  const count = isMonth ? sales.monthCount : sales.weekCount
  const max = isMonth ? sales.monthMax : sales.weekMax
  const avg = count > 0 ? (isMonth ? sales.monthRevenue : sales.weekRevenue) / count : 0

  return (
    <div className="flex flex-col rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6">
      <div key={slide} className="fade-up flex flex-1 flex-col">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
            {label}
          </p>
          <span className="flex gap-1.5">
            {[0, 1].map((i) => (
              <span
                key={i}
                className={`h-1.5 w-1.5 rounded-full ${i === slide ? 'bg-neutral-300' : 'bg-neutral-700'}`}
              />
            ))}
          </span>
        </div>
        <p className="mt-2 font-display text-7xl font-semibold leading-none tracking-tight tabular-nums">
          {gbp(value)}
        </p>
        <div className="mt-auto space-y-2 pt-6 text-lg text-neutral-400">
          <p>
            <span className="font-semibold text-neutral-200 tabular-nums">{count}</span> sales
          </p>
          <p>
            avg <span className="font-semibold text-neutral-200 tabular-nums">{gbp(avg)}</span> per sale
          </p>
          <p>
            biggest <span className="font-semibold text-neutral-200 tabular-nums">{gbp(max)}</span>
          </p>
        </div>
      </div>
    </div>
  )
}

function TodayCard({ sales }: { sales: SalesMetrics }) {
  const value = useCountUp(sales.todayRevenue)
  const maxDay = Math.max(1, ...sales.last7.map((d) => d.total))
  const dayLetter = (iso: string) =>
    ['S', 'M', 'T', 'W', 'T', 'F', 'S'][new Date(iso + 'T12:00:00Z').getUTCDay()]
  return (
    <div className="fade-up flex flex-col rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-6">
      <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">
        Today domestic
      </p>
      <p className="mt-2 font-display text-7xl font-semibold leading-none tracking-tight tabular-nums">
        {gbp(value)}
      </p>
      <p className="mt-2 text-lg text-neutral-400">
        <span className="font-semibold text-neutral-200 tabular-nums">{sales.todayCount}</span>{' '}
        sale{sales.todayCount === 1 ? '' : 's'} today · yesterday{' '}
        <span className="font-semibold text-neutral-200 tabular-nums">
          {gbp(sales.yesterdayRevenue)}
        </span>
      </p>
      <div className="mt-auto pt-6">
        <p className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-neutral-500">
          Last 7 days
        </p>
        <div className="flex items-end gap-2">
          {sales.last7.map((d, i) => {
            const isToday = i === sales.last7.length - 1
            const px = Math.max(3, Math.round((d.total / maxDay) * 64))
            return (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                <div
                  className={`w-full rounded-sm ${isToday ? 'bg-emerald-400' : 'bg-sky-500'}`}
                  style={{ height: `${px}px` }}
                  title={`${d.date}: ${gbp(d.total)}`}
                />
                <span
                  className={`text-[10px] ${isToday ? 'text-emerald-400' : 'text-neutral-600'}`}
                >
                  {dayLetter(d.date)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// Field reps' month £, five bars per slide, rotating through the roster on
// the same rhythm as the hero. Ranked £ desc so slide 1 is the top five.
const REPS_PER_SLIDE = 5

function RepsSlideshow({ sales }: { sales: SalesMetrics }) {
  const pages = Math.max(1, Math.ceil(sales.reps.length / REPS_PER_SLIDE))
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (pages < 2) return
    const t = setInterval(() => setPage((p) => (p + 1) % pages), SALES_SLIDE_MS)
    return () => clearInterval(t)
  }, [pages])

  const slice = sales.reps.slice(page * REPS_PER_SLIDE, (page + 1) * REPS_PER_SLIDE)
  return (
    <div className="relative">
      {pages > 1 && (
        <span className="absolute right-1 top-1 z-10 flex gap-1.5">
          {Array.from({ length: pages }, (_, i) => (
            <span
              key={i}
              className={`h-1.5 w-1.5 rounded-full ${i === page ? 'bg-neutral-300' : 'bg-neutral-700'}`}
            />
          ))}
        </span>
      )}
      <div key={page} className="fade-up">
        <ColumnChart
          title="Reps — sold this month"
          delayMs={0}
          columns={slice.map((s) => ({
            id: s.name.toLowerCase(),
            name: `${s.name} (${s.count})`,
            color: s.color,
            value: Math.round(s.total),
            label: gbp(s.total),
          }))}
        />
      </div>
    </div>
  )
}

export default function SalesTiles({ sales }: { sales: SalesMetrics }) {
  return (
    <>
      {sales.lastSale && (
        <div className="fade-up flex items-center gap-4 rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-4">
          <span className="text-2xl">⚡</span>
          <p className="text-2xl font-medium tabular-nums">
            Last sale&ensp;
            <span className="font-display font-semibold">{gbp(sales.lastSale.amount)}</span>
            <span className="text-neutral-500">
              &ensp;·&ensp;{sales.lastSale.typeLabel}
              {sales.lastSale.soldBy ? ` · ${sales.lastSale.soldBy}` : ''}
              &ensp;·&ensp;{sales.lastSale.customer}
              &ensp;·&ensp;{sales.lastSale.atUk}
            </span>
          </p>
        </div>
      )}

      <section className="grid grid-cols-1 gap-10 md:grid-cols-2 xl:grid-cols-4">
        <RevenueSlideshow sales={sales} />
        <TodayCard sales={sales} />
        <ColumnChart
          title="Dec & Josh — sold this month"
          delayMs={160}
          columns={sales.sellers.map((s) => ({
            id: s.name.toLowerCase(),
            name: `${s.name} (${s.count})`,
            color: s.color,
            value: Math.round(s.total),
            label: gbp(s.total),
          }))}
        />
        <RepsSlideshow sales={sales} />
      </section>
    </>
  )
}
