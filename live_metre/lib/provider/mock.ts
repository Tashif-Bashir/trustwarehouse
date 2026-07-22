import { BOARDS, WORKDAY } from '../config'
import type { Metrics } from '../types'

// Deterministic, time-drifting mock. Each UK working minute since 08:30 is
// simulated with a PRNG seeded on (day, agent, minute), so every serverless
// instance computes identical numbers for the same wall-clock time — and the
// numbers drift upward through the day exactly like a real dialling floor.
// Before the workday starts everything is zero (the empty-morning state).

// Per-agent dials-per-minute probability. Deliberately uneven so the
// leaderboard reorders during the day.
const DIAL_RATE: Record<string, number> = {
  lily: 0.2,
  sue: 0.12,
  alicja: 0.18,
  alisha: 0.26,
  lucy: 0.08,
  gemma: 0.06,
  dec: 0.22,
  josh: 0.25,
}

function mulberry32(seed: number) {
  let s = seed | 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function ukClock(): { dayKey: number; minutesIntoDay: number } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date())
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0)
  return {
    dayKey: get('year') * 10000 + get('month') * 100 + get('day'),
    minutesIntoDay: get('hour') * 60 + get('minute'),
  }
}

export async function getMockMetrics(boardId: string = 'telesales'): Promise<Metrics> {
  const board = BOARDS[boardId] ?? BOARDS.telesales
  const { dayKey, minutesIntoDay } = ukClock()
  const dayStart = WORKDAY.startHour * 60 + WORKDAY.startMinute
  const dayEnd = WORKDAY.endHour * 60 + WORKDAY.endMinute
  const elapsedMinutes = Math.max(0, Math.min(minutesIntoDay, dayEnd) - dayStart)

  const agents = board.agents.map((agent, idx) => {
    let totalCalls = 0
    let callsOver1m = 0
    let talktimeSeconds = 0
    let appointmentsBooked = 0

    for (let minute = 0; minute < elapsedMinutes; minute++) {
      const rand = mulberry32(dayKey * 131071 + idx * 8191 + minute * 127)
      if (rand() < (DIAL_RATE[agent.id] ?? 0.15)) {
        totalCalls++
        // ~35% of dials never really connect (voicemail drop / no answer)
        const short = rand() < 0.35
        const secs = short
          ? 2 + Math.floor(rand() * 14)
          : 20 + Math.floor(rand() ** 1.6 * 400)
        talktimeSeconds += secs
        if (secs >= 60) callsOver1m++
        // a decent conversation sometimes turns into an appointment
        if (board.features.appointments && secs >= 120 && rand() < 0.12) appointmentsBooked++
      }
      // occasional answered inbound call (missed inbound never counts)
      if (rand() < 0.02) {
        totalCalls++
        const secs = 30 + Math.floor(rand() ** 1.4 * 500)
        talktimeSeconds += secs
        if (secs >= 60) callsOver1m++
      }
    }

    return { ...agent, totalCalls, callsOver1m, talktimeSeconds, appointmentsBooked }
  })

  return { asOf: new Date().toISOString(), source: 'Ascend (mock data)', agents }
}
