'use client'

import { useEffect, useRef, useState } from 'react'
import Avatar from '@/components/Avatar'
import ColumnChart from '@/components/ColumnChart'
import RollingNumber from '@/components/RollingNumber'
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

// Field reps' month £ on a full-width row — all reps fit at once at wallboard
// widths; pagination only kicks in if the roster ever outgrows a row.
const REPS_PER_SLIDE = 20

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

export function LastSaleBanner({ sales }: { sales: SalesMetrics }) {
  if (!sales.lastSale) return null
  return (
    <div className="fade-up flex items-center gap-4 rounded-xl border-[0.5px] border-hairline bg-surface px-7 py-4">
      <span className="text-2xl">⚡</span>
      <p className="text-2xl font-medium tabular-nums">
        Last sale&ensp;
        <span className="font-display font-semibold">{gbp(sales.lastSale.amount)}</span>
        <span className="text-neutral-500">
          &ensp;&middot;&ensp;{sales.lastSale.typeLabel}
          {sales.lastSale.soldBy ? ` · ${sales.lastSale.soldBy}` : ''}
          &ensp;&middot;&ensp;{sales.lastSale.customer}
          &ensp;&middot;&ensp;{sales.lastSale.atUk}
        </span>
      </p>
    </div>
  )
}

export function SalesRow({ sales }: { sales: SalesMetrics }) {
  return (
    <section className="grid grid-cols-1 gap-10 md:grid-cols-3">
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
    </section>
  )
}

export function RepsBoard({ sales }: { sales: SalesMetrics }) {
  if (sales.reps.length === 0) return null
  return <RepsSlideshow sales={sales} />
}

// ── Static (non-rotating) building blocks for the one-screen sales board ──

export interface BarRow {
  key: string
  name: string
  color: string
  value: number // drives bar width
  valueLabel: string // big right-aligned figure
  subs?: string[] // trailing metric columns, aligned under `columns` headers
}

// A dense horizontal-bar ranking: one row per entity, all visible at once.
// Fits ~15 rows legibly at wallboard distance — the research-backed replacement
// for a paginated vertical column chart. `columns` labels the trailing metrics
// so a second and third number per row stay readable from across the office.
export function StatBarList({
  title,
  rows,
  columns,
  totals,
}: {
  title: string
  rows: BarRow[]
  columns?: string[]
  totals?: string
}) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <div className="fade-up flex h-full flex-col">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="font-display text-3xl font-semibold uppercase tracking-wide">{title}</h3>
        {totals && (
          <span className="shrink-0 font-display text-lg tabular-nums text-neutral-400">
            {totals}
          </span>
        )}
      </div>
      {columns && columns.length > 0 && (
        <div className="mt-3 flex items-center gap-4 text-xs font-medium uppercase tracking-[0.16em] text-neutral-600">
          <span className="w-7 shrink-0" />
          <span className="w-44 shrink-0" />
          <span className="flex-1" />
          <span className="w-32 shrink-0 text-right">{columns[0]}</span>
          {columns.slice(1).map((c) => (
            <span key={c} className="w-16 shrink-0 text-right">
              {c}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-1 flex-col justify-between gap-2">
        {rows.map((r, i) => (
          <div key={r.key} className="flex items-center gap-4">
            <span className="w-7 shrink-0 text-right font-display text-lg font-medium tabular-nums text-neutral-500">
              {i + 1}
            </span>
            <span className="flex w-44 shrink-0 items-center gap-2.5">
              <Avatar id={r.key} name={r.name} color={r.color} size={30} />
              <span className="truncate font-display text-xl font-medium text-neutral-100">
                {r.name}
              </span>
            </span>
            <div className="relative h-7 flex-1 overflow-hidden rounded-md bg-white/[0.04]">
              <div
                className="h-full rounded-md transition-[width] duration-700 ease-out"
                style={{
                  width: `${(r.value / max) * 100}%`,
                  backgroundColor: r.color,
                  boxShadow: `0 0 12px color-mix(in srgb, ${r.color} 20%, transparent)`,
                }}
              />
            </div>
            <span className="w-32 shrink-0 text-right font-display text-2xl font-semibold tabular-nums">
              {r.valueLabel}
            </span>
            {(r.subs ?? []).map((s, j) => (
              <span
                key={j}
                className="w-16 shrink-0 text-right font-display text-base tabular-nums text-neutral-500"
              >
                {s}
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function KpiTile({
  label,
  value,
  count,
  sub,
  stats,
  split,
  children,
  cardRef,
}: {
  label: string
  value: number
  count: number
  sub: string
  stats?: { label: string; value: string }[]
  split?: { heating: number; water: number }
  children?: React.ReactNode
  cardRef?: (el: HTMLDivElement | null) => void
}) {
  return (
    <div
      ref={cardRef}
      className="flex flex-col rounded-xl border-[0.5px] border-hairline bg-surface px-6 py-5"
    >
      <p className="text-sm font-medium uppercase tracking-[0.18em] text-neutral-400">{label}</p>
      <p className="mt-2 flex font-display text-6xl font-semibold tracking-tight tabular-nums">
        {/* mechanical roll; onIncrease is where a money sound would hang */}
        <RollingNumber value={value} prefix="£" />
      </p>
      <p className="mt-2 text-base text-neutral-400">
        <span className="font-semibold text-neutral-200 tabular-nums">{count}</span> {sub}
      </p>
      {split && (
        // Heating / water counts. A sale can include both, so these are sales
        // CONTAINING each product and may add up to more than the sale count.
        // Inline SVG icons, not emoji: the wall Pi's Chromium has no colour
        // emoji font and drew hollow boxes. SVG renders identically anywhere.
        <div className="mt-3 flex gap-2">
          <span className="flex flex-1 items-center justify-between rounded-lg bg-white/[0.04] px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-neutral-400">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="shrink-0">
                <path
                  fill="#fb923c"
                  d="M12 2c1.1 3.2-.4 5-2 6.7C8.3 10.5 6.5 12.2 6.5 15a5.5 5.5 0 0 0 11 0c0-2-1-3.6-2.1-5-.4 1.1-1 2-2 2.6.6-2.9-.1-6.6-1.4-10.6z"
                />
                <path
                  fill="#fde68a"
                  d="M12 21a3.2 3.2 0 0 1-3.2-3.2c0-1.5.9-2.5 1.8-3.5.4.7 1 1.2 1.7 1.5-.1-1 .1-2.1.6-3.1 1.3 1.2 2.3 2.9 2.3 5.1A3.2 3.2 0 0 1 12 21z"
                />
              </svg>
              Heating
            </span>
            <span className="font-display text-2xl font-semibold tabular-nums text-neutral-100">
              {split.heating}
            </span>
          </span>
          <span className="flex flex-1 items-center justify-between rounded-lg bg-white/[0.04] px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-sky-300/80">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="shrink-0">
                <path
                  fill="#38bdf8"
                  d="M12 2.5S5.5 9.6 5.5 14.4a6.5 6.5 0 0 0 13 0C18.5 9.6 12 2.5 12 2.5z"
                />
                <path
                  fill="#bae6fd"
                  d="M9.4 14.8a.9.9 0 0 1 .9.9 1.9 1.9 0 0 0 1.9 1.9.9.9 0 0 1 0 1.8 3.7 3.7 0 0 1-3.7-3.7.9.9 0 0 1 .9-.9z"
                />
              </svg>
              Water
            </span>
            <span className="font-display text-2xl font-semibold tabular-nums text-sky-300">
              {split.water}
            </span>
          </span>
        </div>
      )}
      {stats && stats.length > 0 && (
        // avg / biggest / yesterday — the detail the rotating board buried in
        // its slideshow, kept on screen permanently here.
        <div className="mt-3 flex gap-5 border-t border-hairline pt-3">
          {stats.map((s) => (
            <span key={s.label} className="flex flex-col">
              <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-neutral-500">
                {s.label}
              </span>
              <span className="font-display text-xl font-semibold tabular-nums text-neutral-200">
                {s.value}
              </span>
            </span>
          ))}
        </div>
      )}
      {children}
    </div>
  )
}

// The 7-day strip from the old Today card: today in emerald, the rest sky blue,
// heights in pixels so a quiet day still shows a stub instead of vanishing.
function Last7Strip({ sales }: { sales: SalesMetrics }) {
  const maxDay = Math.max(1, ...sales.last7.map((d) => d.total))
  const dayLetter = (iso: string) =>
    ['S', 'M', 'T', 'W', 'T', 'F', 'S'][new Date(iso + 'T12:00:00Z').getUTCDay()]
  return (
    <div className="mt-3 border-t border-hairline pt-3">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.16em] text-neutral-500">
        Last 7 days
      </p>
      <div className="flex items-end gap-2">
        {sales.last7.map((d, i) => {
          const isToday = i === sales.last7.length - 1
          const px = Math.max(3, Math.round((d.total / maxDay) * 44))
          return (
            <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
              <div
                className={`w-full rounded-sm ${isToday ? 'bg-emerald-400' : 'bg-sky-500'}`}
                style={{ height: `${px}px` }}
                title={`${d.date}: ${gbp(d.total)}`}
              />
              <span className={`text-[10px] ${isToday ? 'text-emerald-400' : 'text-neutral-600'}`}>
                {dayLetter(d.date)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Money just landed: pop each card in turn. Driven with the Web Animations API
// rather than a CSS class so it re-triggers cleanly on every sale without
// remounting the tiles — a remount would reset the odometer mid-roll.
const POP_MS = 1400
const POP_STAGGER_MS = 460

function pop(el: HTMLElement, delay: number) {
  // Deliberately NOT gated on prefers-reduced-motion: this is a wall display,
  // not someone's personal device, and honouring the OS setting made the whole
  // celebration silently do nothing on a machine with Windows animations off.
  //
  // At this scale a card grows past its grid cell, so lift it above its
  // neighbours for the duration or the edges clip against them.
  el.style.position = 'relative'
  el.style.zIndex = '20'
  const anim = el.animate(
    [
      { transform: 'scale(1) translateX(0)', boxShadow: '0 0 0 rgba(52,211,153,0)' },
      { transform: 'scale(1.13) translateX(-9px)', boxShadow: '0 0 52px rgba(52,211,153,0.55)' },
      { transform: 'scale(1.14) translateX(9px)' },
      { transform: 'scale(1.13) translateX(-7px)' },
      { transform: 'scale(1.10) translateX(6px)', boxShadow: '0 0 40px rgba(52,211,153,0.4)' },
      { transform: 'scale(1.06) translateX(-3px)' },
      { transform: 'scale(1.02) translateX(0)', boxShadow: '0 0 16px rgba(52,211,153,0.15)' },
      { transform: 'scale(1) translateX(0)', boxShadow: '0 0 0 rgba(52,211,153,0)' },
    ],
    { duration: POP_MS, delay, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'none' }
  )
  anim.finished.then(() => {
    el.style.zIndex = ''
  }).catch(() => {
    el.style.zIndex = ''
  })
}

// Month / week / today shown side by side, all live — no slideshow. Every
// figure the rotating board showed is here at once: avg and biggest per sale,
// yesterday's total, and the 7-day trend. `pulse` increments on each new sale
// and runs the cards through a staggered celebration.
export function StaticSalesKpis({ sales, pulse = 0 }: { sales: SalesMetrics; pulse?: number }) {
  const avg = (total: number, n: number) => (n > 0 ? gbp(total / n) : '£0')
  const cards = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    if (!pulse) return // don't fire on first paint
    cards.current.forEach((el, i) => {
      if (el) pop(el, i * POP_STAGGER_MS)
    })
  }, [pulse])

  const ref = (i: number) => (el: HTMLDivElement | null) => {
    cards.current[i] = el
  }

  return (
    <section className="grid grid-cols-3 gap-5">
      <KpiTile
        cardRef={ref(0)}
        label={`${sales.monthLabel} revenue`}
        value={sales.monthRevenue}
        count={sales.monthCount}
        sub="sales"
        split={{ heating: sales.monthHeating, water: sales.monthWater }}
        stats={[
          { label: 'Avg', value: avg(sales.monthRevenue, sales.monthCount) },
          { label: 'Biggest', value: gbp(sales.monthMax) },
        ]}
      />
      <KpiTile
        cardRef={ref(1)}
        label="This week"
        value={sales.weekRevenue}
        count={sales.weekCount}
        sub="sales"
        split={{ heating: sales.weekHeating, water: sales.weekWater }}
        stats={[
          { label: 'Avg', value: avg(sales.weekRevenue, sales.weekCount) },
          { label: 'Biggest', value: gbp(sales.weekMax) },
        ]}
      />
      <KpiTile
        cardRef={ref(2)}
        label="Today domestic"
        value={sales.todayRevenue}
        count={sales.todayCount}
        sub={sales.todayCount === 1 ? 'sale today' : 'sales today'}
        split={{ heating: sales.todayHeating, water: sales.todayWater }}
        stats={[{ label: 'Yesterday', value: gbp(sales.yesterdayRevenue) }]}
      >
        <Last7Strip sales={sales} />
      </KpiTile>
    </section>
  )
}
