'use client'

import type { PipelineMetrics, PipelineRep } from '@/lib/types'

const gbp = (v: number) => `£${Math.round(v).toLocaleString('en-GB')}`
// Compact form for the headline number only — "£186K" not "£186,214"; an
// estimate built from an average sale value doesn't deserve pound precision.
const gbpK = (v: number) => (v >= 1000 ? `£${Math.round(v / 1000)}K` : gbp(v))

const CHIP_TONE: Record<'green' | 'amber' | 'red', string> = {
  green: 'bg-emerald-400/15 text-emerald-300',
  amber: 'bg-amber-400/15 text-amber-300',
  red: 'bg-red-400/15 text-red-300',
}

// Aging chip for a rep's OLDEST (longest-waiting) lead: green while there's
// still most of the 14-day chase window left, amber inside it, red once the
// window has passed. Owner policy 19 Aug 2026 — reps chase their own
// pipeline within 14 days of the visit.
function AgingChip({ daysSince }: { daysSince: number }) {
  const remaining = 14 - daysSince
  const tone = remaining >= 7 ? 'green' : remaining >= 0 ? 'amber' : 'red'
  const label = remaining >= 0 ? `${remaining}d left` : `${-remaining}d over`
  return (
    <span
      className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums ${CHIP_TONE[tone]}`}
    >
      {label}
    </span>
  )
}

function RepCell({ rep }: { rep: PipelineRep }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border-[0.5px] border-hairline bg-surface px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate font-display text-lg font-semibold text-neutral-100">{rep.name}</p>
        <p className="text-sm text-neutral-400">
          {rep.count} open
          {rep.overdueCount > 0 && (
            <span className="ml-1.5 font-medium text-red-400">
              · {rep.overdueCount} overdue
            </span>
          )}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="font-display text-xl font-semibold tabular-nums text-neutral-100">
          {gbp(rep.estTotal)}
          <span className="ml-1 font-body text-xs font-normal text-neutral-500">est.</span>
        </span>
        <AgingChip daysSince={rep.oldestDaysSince} />
      </div>
    </div>
  )
}

// "The pipeline" (owner-approved concept, sized 19 Aug 2026): appointments a
// rep has ATTENDED that have NOT sold and NOT died — money waiting to be
// chased within 14 days of the visit. Sits beneath the leaderboard, same dark
// aesthetic. Two-column cell grid rather than a long list (wallboard trap:
// full-width rows are safe on the Pi, three-across is not) so ~12 reps fit
// without pushing the leaderboard off a 1080p screen.
export default function PipelineBoard({ pipeline }: { pipeline: PipelineMetrics }) {
  if (pipeline.count === 0) return null

  return (
    <section className="fade-up" style={{ animationDelay: '440ms' }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 className="font-display text-3xl font-semibold uppercase tracking-wide">
          Pipeline{' '}
          <span className="font-body text-lg font-normal normal-case tracking-normal text-neutral-400">
            — money waiting
          </span>
        </h2>
        <p className="flex items-baseline gap-2">
          <span className="font-display text-4xl font-semibold tabular-nums">
            {gbpK(pipeline.estTotal)}
          </span>
          <span className="font-display text-lg font-medium uppercase tracking-wide text-neutral-400">
            waiting
          </span>
          <span className="text-sm text-neutral-500">
            est. &middot; {pipeline.count} lead{pipeline.count === 1 ? '' : 's'}
          </span>
        </p>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {pipeline.reps.map((rep) => (
          <RepCell key={rep.name} rep={rep} />
        ))}
      </div>

      {pipeline.unattributed.count > 0 && (
        <div className="mt-2.5 flex items-center justify-between gap-3 rounded-lg border-[0.5px] border-hairline/60 bg-surface/40 px-4 py-2">
          <span className="text-sm text-neutral-500">Unattributed</span>
          <span className="text-sm tabular-nums text-neutral-500">
            {pipeline.unattributed.count} lead{pipeline.unattributed.count === 1 ? '' : 's'}
            &nbsp;&middot;&nbsp;est. {gbp(pipeline.unattributed.estTotal)}
          </span>
        </div>
      )}
    </section>
  )
}
