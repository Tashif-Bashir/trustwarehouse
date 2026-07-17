import { SCORING } from '@/lib/config'
import type { AgentMetrics } from '@/lib/types'

const ROW_HEIGHT = 68 // px — fixed so rank changes animate via `top`

export function performanceScore(agent: AgentMetrics): number {
  return Math.round(
    agent.appointmentsBooked * SCORING.appointmentPoints +
      (agent.talktimeSeconds / 60) * SCORING.talkMinutePoints
  )
}

function TrophyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-label="Leader">
      <path d="M6 3h12v2h3v3c0 2.6-2 4.7-4.5 5-1 1.9-2.7 3.3-4.5 3.8V19h4v2H8v-2h4v-2.2c-1.8-.5-3.5-1.9-4.5-3.8C5 12.7 3 10.6 3 8V5h3V3zm-1 4v1c0 1.3.9 2.5 2.1 2.9A9.4 9.4 0 0 1 6.1 7H5zm14 0h-1.1a9.4 9.4 0 0 1-1 3.9A3.1 3.1 0 0 0 19 8V7z" />
    </svg>
  )
}

interface LeaderboardProps {
  agents: AgentMetrics[]
  flashingIds: Set<string>
}

export default function Leaderboard({ agents, flashingIds }: LeaderboardProps) {
  const scored = agents.map((agent) => ({ agent, score: performanceScore(agent) }))
  // Stable sort: descending score, config order breaks ties (empty morning).
  const ranked = [...scored].sort((a, b) => b.score - a.score)
  const rankById = new Map(ranked.map((entry, rank) => [entry.agent.id, rank]))
  const maxScore = Math.max(1, ...scored.map((entry) => entry.score))
  const leaderId = ranked[0].score > 0 ? ranked[0].agent.id : null

  return (
    <section>
      <h2 className="text-2xl font-semibold">
        Performance today{' '}
        <span className="font-normal text-neutral-400">
          — weighted: talktime + appointments
        </span>
      </h2>
      <div className="relative mt-4" style={{ height: agents.length * ROW_HEIGHT }}>
        {scored.map(({ agent, score }) => {
          const rank = rankById.get(agent.id) ?? 0
          return (
            <div
              key={agent.id}
              className={`absolute inset-x-0 flex items-center gap-6 rounded-lg transition-[top] duration-700 ease-in-out ${
                flashingIds.has(agent.id) ? 'row-flash' : ''
              }`}
              style={{
                top: rank * ROW_HEIGHT,
                height: ROW_HEIGHT,
                ['--agent' as string]: agent.color,
              }}
            >
              <div className="w-28 shrink-0 text-2xl font-semibold">{agent.name}</div>
              <div className="relative h-9 flex-1 overflow-hidden rounded-lg bg-neutral-900">
                <div
                  className="absolute inset-y-0 left-0 rounded-lg transition-[width] duration-700 ease-in-out"
                  style={{ width: `${(score / maxScore) * 100}%`, backgroundColor: agent.color }}
                />
              </div>
              <div className="flex w-56 shrink-0 items-center justify-end gap-3 text-right">
                <span className="text-2xl font-medium tabular-nums">
                  {score} <span className="text-neutral-400">·</span> {agent.appointmentsBooked}{' '}
                  appt{agent.appointmentsBooked === 1 ? '' : 's'}
                </span>
                {agent.id === leaderId && (
                  <TrophyIcon className="h-6 w-6 shrink-0 text-amber-400" />
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
