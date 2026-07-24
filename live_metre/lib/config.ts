// Single place to tune the wallboard. Everything the business might want to
// change lives here: the agent roster (colour follows the agent, never the
// rank), the performance weighting, and the polling cadence.

export interface AgentConfig {
  id: string
  name: string
  color: string
  role?: string
}

export const AGENTS: AgentConfig[] = [
  { id: 'lily', name: 'Lily', color: '#2a78d6' },
  { id: 'sue', name: 'Sue', color: '#1baf7a' },
  { id: 'alicja', name: 'Alicja', color: '#e87ba4' },
  { id: 'alisha', name: 'Alisha', color: '#eb6834' },
]

// Second wallboard: sales & ops (own screen). Calls only — no
// appointments, no leaderboard, no celebration (owner, 22 Jul 2026).
export const TEAM_AGENTS: AgentConfig[] = [
  { id: 'lucy', name: 'Lucy', color: '#2a78d6', role: 'Commercial' },
  { id: 'gemma', name: 'Gemma', color: '#1baf7a', role: 'Operations' },
  { id: 'dec', name: 'Dec', color: '#eb6834', role: 'Internal Sales' },
  { id: 'josh', name: 'Josh', color: '#e87ba4', role: 'Internal Sales' },
]

// Exact Ascend caller names for the sales & ops board (verified in call
// data: 'Lucy', 'Gemma Taylor', 'Dec', 'Josh Baron').
export const TEAM_ASCEND_NAMES: Record<string, string[]> = {
  lucy: ['Lucy'],
  gemma: ['Gemma Taylor', 'Gemma'],
  dec: ['Dec', 'Declan'],
  josh: ['Josh Baron', 'Josh'],
}

export interface BoardSpec {
  id: 'telesales' | 'team'
  title: string
  agents: AgentConfig[]
  features: {
    appointments: boolean
    leaderboard: boolean
    celebration: boolean
    sales: boolean
  }
}

export const BOARDS: Record<string, BoardSpec> = {
  telesales: {
    id: 'telesales',
    title: 'Live telesales metre',
    agents: AGENTS,
    features: { appointments: true, leaderboard: true, celebration: true, sales: false },
  },
  team: {
    id: 'team',
    title: 'Live sales & ops metre',
    agents: TEAM_AGENTS,
    features: { appointments: false, leaderboard: false, celebration: false, sales: true },
  },
}

// Hero sales tile slideshow: month revenue ⇄ week revenue, rotating.
export const SALES_SLIDE_MS = 9_000

// Sales & ops board: the whole lower section rotates between views
// (sales tiles → reps chart → calls) so nothing needs scrolling.
export const SALES_VIEW_MS = 15_000

// Exact names each data source uses for an agent (confirmed against real
// rows, 18 Jul 2026). The bronze provider attributes by these; if an agent
// is renamed in Ascend/the CRM, update here.
export const SOURCE_NAMES: Record<
  string,
  { ascend: string[]; appBookers: string[]; crm: string[] }
> = {
  lily: {
    ascend: ['Lily'],
    appBookers: ['Lily Harpman', 'Lily Harpham'],
    crm: ['Lily Harpham', 'Lily'],
  },
  sue: {
    ascend: ['Sue'],
    appBookers: ['Sue England'],
    crm: ['Susan England', 'Sue'],
  },
  alicja: {
    ascend: ['Alicja Aleksiuk'],
    appBookers: ['Alicja Aleksiuk'],
    crm: ['Alicja Aleksiuk', 'Alicja'],
  },
  alisha: {
    ascend: ['Alisha'],
    appBookers: ['Alisha Moore'],
    crm: ['Alisha Moore', 'Alisha'],
  },
}

// The trophy is a daily TARGET: every agent who books at least this many
// appointments today wears one (not just the leader — team decision).
export const TROPHY_MIN_APPTS = 5

// End-of-day celebration: at this UK time on working days, every screen
// showing the board celebrates the day's top performer(s) full-screen for
// durationMs, then returns to the live board. Fires once per day per
// browser; graceMinutes lets a screen that wakes late still celebrate.
// Friday finishes at 16:00, so its celebration runs at 15:59.
export const CELEBRATION = {
  hour: 16,
  minute: 59,
  friday: { hour: 15, minute: 59 },
  graceMinutes: 5,
  durationMs: 30_000,
  weekdaysOnly: true,
}

// Frontend polling cadence and the threshold after which the feed is
// declared stale (amber pill).
export const POLL_INTERVAL_MS = 20_000
export const STALE_AFTER_MS = 60_000

// The mock provider simulates dialling inside these UK working hours.
export const WORKDAY = { startHour: 8, startMinute: 30, endHour: 17, endMinute: 30 }
