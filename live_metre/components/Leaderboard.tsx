'use client'

import { TROPHY_MIN_APPTS } from '@/lib/config'
import { useCountUp } from '@/lib/useCountUp'
import type { AgentMetrics } from '@/lib/types'

const ROW_HEIGHT = 72 // px — fixed so rank changes animate via `top`

function TrophyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-label="Leader">
      <path d="M6 3h12v2h3v3c0 2.6-2 4.7-4.5 5-1 1.9-2.7 3.3-4.5 3.8V19h4v2H8v-2h4v-2.2c-1.8-.5-3.5-1.9-4.5-3.8C5 12.7 3 10.6 3 8V5h3V3zm-1 4v1c0 1.3.9 2.5 2.1 2.9A9.4 9.4 0 0 1 6.1 7H5zm14 0h-1.1a9.4 9.4 0 0 1-1 3.9A3.1 3.1 0 0 0 19 8V7z" />
    </svg>
  )
}

function Row({
  agent,
  rank,
  maxAppts,
  hasTrophy,
  flashing,
}: {
  agent: AgentMetrics
  rank: number
  maxAppts: number
  hasTrophy: boolean
  flashing: boolean
}) {
  const displayAppts = useCountUp(agent.appointmentsBooked)
  return (
    <div
      className={`absolute inset-x-0 flex items-center gap-6 rounded-lg transition-[top] duration-700 ease-in-out ${
        flashing ? 'row-flash' : ''
      }`}
      style={{ top: rank * ROW_HEIGHT, height: ROW_HEIGHT, ['--agent' as string]: agent.color }}
    >
      <div className="w-28 shrink-0 font-display text-3xl font-semibold">{agent.name}</div>
      <div className="relative h-9 flex-1 overflow-visible rounded-lg bg-surface">
        <div
          className="absolute inset-y-0 left-0 rounded-lg transition-[width] duration-700 ease-in-out"
          style={{
            width: `${(agent.appointmentsBooked / maxAppts) * 100}%`,
            backgroundColor: agent.color,
            // the neon-strip glow — each bar radiates its own team colour;
            // stronger once the trophy target is reached
            boxShadow: `0 0 ${hasTrophy ? 26 : 16}px color-mix(in srgb, ${agent.color} ${
              hasTrophy ? 38 : 24
            }%, transparent)`,
          }}
        />
      </div>
      <div className="flex w-44 shrink-0 items-center justify-end gap-3">
        <span className="font-display text-3xl font-medium tabular-nums">
          {displayAppts}{' '}
          <span className="text-2xl text-neutral-400">
            appt{agent.appointmentsBooked === 1 ? '' : 's'}
          </span>
        </span>
        {hasTrophy && (
          <TrophyIcon className="h-7 w-7 shrink-0 text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.5)]" />
        )}
      </div>
    </div>
  )
}

interface LeaderboardProps {
  agents: AgentMetrics[]
  flashingIds: Set<string>
}

export default function Leaderboard({ agents, flashingIds }: LeaderboardProps) {
  // Rank purely by appointments booked today (owner decision 18 Jul 2026 —
  // no composite score). Stable sort: config order breaks ties.
  const ranked = [...agents].sort((a, b) => b.appointmentsBooked - a.appointmentsBooked)
  const rankById = new Map(ranked.map((agent, rank) => [agent.id, rank]))
  const maxAppts = Math.max(1, ...agents.map((a) => a.appointmentsBooked))
  // Trophy is a TARGET, not a race (team decision 21 Jul 2026): EVERYONE
  // who books TROPHY_MIN_APPTS today wears one, not just the leader.

  return (
    <section className="fade-up" style={{ animationDelay: '400ms' }}>
      <h2 className="font-display text-3xl font-semibold uppercase tracking-wide">
        Performance today{' '}
        <span className="font-body text-lg font-normal normal-case tracking-normal text-neutral-400">
          — appointments booked
        </span>
      </h2>
      <div className="relative mt-5" style={{ height: agents.length * ROW_HEIGHT }}>
        {agents.map((agent) => (
          <Row
            key={agent.id}
            agent={agent}
            rank={rankById.get(agent.id) ?? 0}
            maxAppts={maxAppts}
            hasTrophy={agent.appointmentsBooked >= TROPHY_MIN_APPTS}
            flashing={flashingIds.has(agent.id)}
          />
        ))}
      </div>
    </section>
  )
}
