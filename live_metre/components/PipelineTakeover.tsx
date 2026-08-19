'use client'

import { useEffect, useMemo, useState } from 'react'
import { PIPELINE_TAKEOVER } from '@/lib/config'
import type { PipelineMetrics, PipelineRep } from '@/lib/types'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`

// TV-friendly labels for the CRM Appointment Status buckets; anything the
// CRM adds later falls back to the raw value so it still shows.
const STATUS_LABELS: Record<string, string> = {
  'appointment sat': 'Sat — no outcome',
  'follow up': 'Follow up',
  'follow up text': 'Follow up text',
  'no contact': 'No contact',
  'not ready yet': 'Not ready yet',
}

const CHIP_TONE: Record<'green' | 'amber' | 'red', string> = {
  green: 'border-emerald-400/30 bg-emerald-400/15 text-emerald-300',
  amber: 'border-amber-400/30 bg-amber-400/15 text-amber-300',
  red: 'border-red-400/30 bg-red-400/15 text-red-300',
}

// Same 14-day chase-window logic as PipelineBoard's AgingChip (owner policy
// 19 Aug 2026) — duplicated rather than shared because the takeover's chip
// is a different size/shape for TV legibility, not just a restyle.
function agingTone(daysSince: number): 'green' | 'amber' | 'red' {
  const remaining = 14 - daysSince
  return remaining >= 7 ? 'green' : remaining >= 0 ? 'amber' : 'red'
}

function agingLabel(daysSince: number): string {
  const remaining = 14 - daysSince
  return remaining >= 0 ? `${remaining}d left` : `${-remaining}d over`
}

// Phase 1 (headline) hold before shrinking into the phase-2 header strip —
// leaves the rest of PIPELINE_TAKEOVER.durationMs for the rep breakdown.
// 12s, not 9: the status buckets under the total need reading time.
const PHASE1_MS = 12_000
const COUNT_UP_MS = 2_500
// Large cards for room-distance legibility — paginate rather than shrink.
const ITEMS_PER_PAGE = 4
const PAGE_ROTATE_MS = 12_000
// Fade/scale back to the live board in the last stretch of the showing —
// Wallboard still unmounts this component at exactly durationMs; this is
// purely a visual head start on the exit so it never looks like a hard cut.
const EXIT_MS = 500

// Counts up from zero on mount, ease-out — deliberately NOT the shared
// useCountUp hook, which animates from its previous value, not from zero:
// this takeover always mounts fresh per showing (Wallboard unmounts it
// between showings), so "from zero" is exactly the reveal the brief wants.
function useCountFromZero(target: number, durationMs: number): number {
  const [value, setValue] = useState(0)
  useEffect(() => {
    let raf: number
    const start = performance.now()
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(target * eased))
      if (progress < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return value
}

type Item = Pick<PipelineRep, 'name' | 'count' | 'estTotal' | 'oldestDaysSince' | 'overdueCount'> & {
  quiet?: boolean
}

function RepCard({ item }: { item: Item }) {
  const tone = agingTone(item.oldestDaysSince)
  return (
    <div
      className={`flex items-center justify-between gap-6 rounded-2xl border-[0.5px] px-8 py-6 ${
        item.quiet ? 'border-hairline/50 bg-surface/40' : 'border-hairline bg-surface'
      }`}
    >
      <div className="min-w-0 flex-1">
        <p
          className={`truncate font-display font-semibold ${
            item.quiet ? 'text-2xl text-neutral-300' : 'text-4xl text-neutral-50'
          }`}
        >
          {item.name}
        </p>
        <p className={`mt-1 ${item.quiet ? 'text-base text-neutral-500' : 'text-xl text-neutral-400'}`}>
          {item.count} open lead{item.count === 1 ? '' : 's'}
          {item.overdueCount > 0 && (
            <span className="pulse-dot ml-2 inline-block font-semibold text-red-400">
              &middot; {item.overdueCount} overdue
            </span>
          )}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        <span
          className={`font-display font-semibold tabular-nums ${
            item.quiet ? 'text-2xl text-neutral-300' : 'money-glow text-5xl text-neutral-50'
          }`}
        >
          {gbp(item.estTotal)}
        </span>
        {!item.quiet && (
          <span
            className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-base font-semibold tabular-nums ${CHIP_TONE[tone]}`}
          >
            {agingLabel(item.oldestDaysSince)}
          </span>
        )}
      </div>
    </div>
  )
}

// Full-screen rep-pipeline takeover for the sales & ops board: an EVENT, not
// a bolted-on section (owner brief 19 Aug 2026). Phase 1 is a giant counting-
// up headline total; phase 2 shrinks that total to a header strip and
// stacks the per-rep breakdown as large room-legible cards, ranked by est £
// descending, paginating if the roster overflows one screen. Unattributed
// (if any) rides along as the final, visually quieter item. The parent
// (Wallboard) mounts/unmounts this on PIPELINE_TAKEOVER's timer and never
// while EOD/DOORS owns the screen.
export default function PipelineTakeover({ pipeline }: { pipeline: PipelineMetrics }) {
  const [phase, setPhase] = useState<1 | 2>(1)
  const [closing, setClosing] = useState(false)
  const value = useCountFromZero(pipeline.estTotal, COUNT_UP_MS)

  useEffect(() => {
    const t = setTimeout(() => setPhase(2), PHASE1_MS)
    return () => clearTimeout(t)
  }, [])

  useEffect(() => {
    const t = setTimeout(
      () => setClosing(true),
      Math.max(0, PIPELINE_TAKEOVER.durationMs - EXIT_MS)
    )
    return () => clearTimeout(t)
  }, [])

  const items: Item[] = useMemo(() => {
    const list: Item[] = pipeline.reps.map((r) => ({ ...r }))
    if (pipeline.unattributed.count > 0) {
      list.push({
        name: 'Unattributed',
        count: pipeline.unattributed.count,
        estTotal: pipeline.unattributed.estTotal,
        oldestDaysSince: 0,
        overdueCount: 0,
        quiet: true,
      })
    }
    return list
  }, [pipeline])

  const pages = useMemo(() => {
    const chunks: Item[][] = []
    for (let i = 0; i < items.length; i += ITEMS_PER_PAGE) {
      chunks.push(items.slice(i, i + ITEMS_PER_PAGE))
    }
    return chunks.length > 0 ? chunks : [[]]
  }, [items])

  const [page, setPage] = useState(0)
  useEffect(() => {
    if (phase !== 2 || pages.length < 2) return
    const t = setInterval(() => setPage((p) => (p + 1) % pages.length), PAGE_ROTATE_MS)
    return () => clearInterval(t)
  }, [phase, pages.length])

  return (
    <div
      className={`pipeline-takeover fixed inset-0 z-50 flex flex-col items-center overflow-hidden px-10 transition-all duration-500 ease-in ${
        closing ? 'scale-95 opacity-0' : 'scale-100 opacity-100'
      }`}
    >
      {phase === 1 && (
        <div className="relative flex flex-1 flex-col items-center justify-center gap-6 text-center">
          <span
            className="pipeline-glow pointer-events-none absolute h-[60vh] w-[60vh] rounded-full bg-red-500/25 blur-[120px]"
            aria-hidden
          />
          <p className="fade-up relative text-lg font-semibold uppercase tracking-[0.4em] text-red-400/80">
            Waiting to be chased
          </p>
          <p
            className="fade-up money-glow relative font-display font-bold leading-none tracking-tight tabular-nums text-neutral-50"
            style={{ fontSize: 'clamp(6rem, 14vw, 13rem)', animationDelay: '120ms' }}
          >
            {gbp(value)}
          </p>
          <p className="fade-up relative text-2xl text-neutral-400" style={{ animationDelay: '260ms' }}>
            <span className="font-semibold text-neutral-200 tabular-nums">{pipeline.count}</span>{' '}
            lead{pipeline.count === 1 ? '' : 's'} &middot; est.{' '}
            <span className="font-semibold text-neutral-200 tabular-nums">
              {gbp(pipeline.avgSaleValue)}
            </span>{' '}
            each
          </p>

          {/* Where the money sits — one bucket per chase status (owner ask
              19 Aug 2026: "this much in follow up, this much in this"). */}
          {pipeline.statuses.length > 0 && (
            <div className="relative mt-4 flex flex-wrap items-stretch justify-center gap-5">
              {pipeline.statuses.map((s, i) => (
                <div
                  key={s.status}
                  className="fade-up min-w-[13rem] rounded-2xl border-[0.5px] border-hairline bg-surface/60 px-7 py-5 text-center"
                  style={{ animationDelay: `${420 + i * 140}ms` }}
                >
                  <p className="money-glow font-display text-4xl font-bold tabular-nums text-neutral-50">
                    {gbp(s.estTotal)}
                  </p>
                  <p className="mt-2 text-sm font-semibold uppercase tracking-[0.18em] text-red-400/80">
                    {STATUS_LABELS[s.status] ?? s.status}
                  </p>
                  <p className="mt-0.5 text-sm tabular-nums text-neutral-500">
                    {s.count} lead{s.count === 1 ? '' : 's'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {phase === 2 && (
        <div className="fade-up flex w-full max-w-5xl flex-1 flex-col gap-6 py-10">
          <div className="flex items-baseline justify-between gap-6 border-b border-hairline pb-5">
            <p className="text-base font-semibold uppercase tracking-[0.3em] text-red-400/80">
              Pipeline &middot; waiting to be chased
            </p>
            <p className="money-glow font-display text-5xl font-bold tabular-nums text-neutral-50">
              {gbp(pipeline.estTotal)}
              <span className="ml-2 text-lg font-normal text-neutral-500">
                {pipeline.count} lead{pipeline.count === 1 ? '' : 's'}
              </span>
            </p>
          </div>

          <div key={page} className="fade-up flex flex-1 flex-col justify-center gap-4">
            {pages[page].map((item) => (
              <RepCard key={item.name} item={item} />
            ))}
          </div>

          {pages.length > 1 && (
            <div className="flex justify-center gap-2">
              {pages.map((_, i) => (
                <span
                  key={i}
                  className={`h-1.5 w-1.5 rounded-full ${i === page ? 'bg-neutral-300' : 'bg-neutral-700'}`}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
