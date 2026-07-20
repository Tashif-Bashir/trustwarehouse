'use client'

import { useMemo } from 'react'
import Avatar from '@/components/Avatar'
import type { AgentMetrics } from '@/lib/types'

function TrophyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M6 3h12v2h3v3c0 2.6-2 4.7-4.5 5-1 1.9-2.7 3.3-4.5 3.8V19h4v2H8v-2h4v-2.2c-1.8-.5-3.5-1.9-4.5-3.8C5 12.7 3 10.6 3 8V5h3V3zm-1 4v1c0 1.3.9 2.5 2.1 2.9A9.4 9.4 0 0 1 6.1 7H5zm14 0h-1.1a9.4 9.4 0 0 1-1 3.9A3.1 3.1 0 0 0 19 8V7z" />
    </svg>
  )
}

// Full-screen end-of-day takeover: confetti in the winners' colours + gold,
// big photo, name, appointment count. The parent mounts/unmounts it.
export default function Celebration({ winners }: { winners: AgentMetrics[] }) {
  const pieces = useMemo(() => {
    const palette = [...winners.map((w) => w.color), '#fbbf24', '#fbbf24', '#ffffff']
    return Array.from({ length: 140 }, (_, i) => ({
      left: Math.random() * 100,
      delay: Math.random() * 5,
      duration: 4 + Math.random() * 4,
      size: 6 + Math.random() * 9,
      color: palette[i % palette.length],
    }))
  }, [winners])

  const appts = winners[0].appointmentsBooked

  return (
    <div className="celebration fixed inset-0 z-50 flex flex-col items-center justify-center gap-10 overflow-hidden">
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
        {winners.length > 1 ? 'Joint top performers today' : 'Top performer today'}
      </div>

      <div className="fade-up flex items-center gap-16" style={{ animationDelay: '150ms' }}>
        {winners.map((w) => (
          <div key={w.id} className="flex flex-col items-center gap-6">
            <Avatar id={w.id} name={w.name} color={w.color} size={210} />
            <div className="font-display text-7xl font-semibold uppercase tracking-wide">
              {w.name}
            </div>
          </div>
        ))}
      </div>

      <div
        className="fade-up flex items-center gap-5 font-display text-5xl font-semibold text-amber-400"
        style={{ animationDelay: '300ms' }}
      >
        <TrophyIcon className="h-12 w-12 drop-shadow-[0_0_12px_rgba(251,191,36,0.6)]" />
        {appts} appointment{appts === 1 ? '' : 's'}
        <TrophyIcon className="h-12 w-12 drop-shadow-[0_0_12px_rgba(251,191,36,0.6)]" />
      </div>
    </div>
  )
}
