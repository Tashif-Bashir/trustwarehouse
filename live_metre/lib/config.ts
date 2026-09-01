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
  // new starter 30 Jul 2026; Ascend ext 1116, caller name 'Peter'
  { id: 'peter', name: 'Peter', color: '#8b5cf6' },
  // Alisha left the business 4 Aug 2026 — removed from the roster.
]

// Second wallboard: sales & ops (own screen). Calls only — no
// appointments, no leaderboard, no celebration (owner, 22 Jul 2026).
export const TEAM_AGENTS: AgentConfig[] = [
  { id: 'lucy', name: 'Lucy', color: '#2a78d6', role: 'Commercial' },
  { id: 'gemma', name: 'Gemma', color: '#1baf7a', role: 'Operations' },
  { id: 'dec', name: 'Dec', color: '#eb6834', role: 'Internal Sales' },
  { id: 'josh', name: 'Josh', color: '#e87ba4', role: 'Internal Sales' },
  // moved from telesales to internal sales, 1 Sep 2026 (keeps his purple)
  { id: 'peter', name: 'Peter', color: '#8b5cf6', role: 'Internal Sales' },
]

// Exact Ascend caller names for the sales & ops board (verified in call
// data: 'Lucy', 'Gemma Taylor', 'Dec', 'Josh Baron').
export const TEAM_ASCEND_NAMES: Record<string, string[]> = {
  lucy: ['Lucy'],
  gemma: ['Gemma Taylor', 'Gemma'],
  dec: ['Dec', 'Declan'],
  josh: ['Josh Baron', 'Josh'],
  peter: ['Peter'],
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
    // "the pipeline" (owner-approved 19 Aug 2026): field reps' attended-but-
    // unsold appointments, chased within 14 days of the visit. SALES & OPS
    // board (owner ruling 19 Aug: "the live sales metre, not telesales").
    pipeline: boolean
  }
}

export const BOARDS: Record<string, BoardSpec> = {
  telesales: {
    id: 'telesales',
    title: 'Live telesales metre',
    agents: AGENTS,
    features: {
      appointments: true, leaderboard: true, celebration: true, sales: false, pipeline: false,
    },
  },
  team: {
    id: 'team',
    title: 'Live sales & ops metre',
    agents: TEAM_AGENTS,
    features: {
      appointments: false, leaderboard: false, celebration: false, sales: true, pipeline: true,
    },
  },
}

// Cash-register sound when a new sale lands (sales & ops board only). Browsers
// block audio until the page gets a real click, so the board shows a one-time
// "enable sound" badge; a kiosk can skip it by launching Chrome with
// --autoplay-policy=no-user-gesture-required. Add ?sound=1 to test on demand.
// `file` wins if present (drop a real recording at live_metre/public/sounds/ —
// see the README there). Otherwise the sound is synthesised: 'register' = till
// ka-ching, 'coins' = handful of coins landing.
export const SALES_SOUND = {
  enabled: true,
  volume: 0.35,
  style: 'register' as 'coins' | 'register',
  file: '/sounds/sale.mp3' as string | null,
  // Chains the recording back to back. The supplied clip is audible for ~1.3s
  // (the rest of the file is silence, which sound.ts trims), so 2 ≈ 2.6s of
  // continuous till. Raise for longer, set to 1 for a single ka-ching.
  repeat: 2,
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
  // Peter Heaton, started 30 Jul 2026. Ascend caller name is just 'Peter'
  // (ext 1116); CRM user 377190400.
  peter: {
    ascend: ['Peter'],
    appBookers: ['Peter Heaton', 'Peter'],
    crm: ['Peter Heaton', 'Peter'],
  },
}

// The trophy is a daily TARGET: every agent who books at least this many
// appointments today wears one (not just the leader — team decision).
// Raised 5 -> 6, owner 18 Aug 2026.
export const TROPHY_MIN_APPTS = 6

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

// End-of-day celebration for the SALES & OPS STATIC BOARD ONLY (owner
// request, 10 Aug 2026) — the telesales board's CELEBRATION above is a
// separate, unrelated feature and stays untouched. At this UK time, Mon-Fri
// EVERY weekday (no Friday exception — the sales team finishes at 5 daily,
// unlike telesales), the board takes over the screen for durationMs with
// today's numbers and plays sound.file through the existing file-playback
// pipeline (lib/sound.ts). Fires once per day per browser; graceMinutes lets
// a screen that wakes late still celebrate. ?eod=1 forces a demo run without
// marking the day as celebrated.
export const EOD_CELEBRATION = {
  enabled: true,
  hour: 16,
  minute: 59,
  graceMinutes: 5,
  weekdaysOnly: true,
  durationMs: 45_000,
  sound: {
    // MUSIC RETIRED (owner, 20 Aug 2026: "it is annoying") — the takeover
    // runs silently; the per-sale ka-ching stays. To bring a song back,
    // point this at an mp3 under public/sounds/ (was '/sounds/endofday.mp3').
    file: null as string | null,
    volume: SALES_SOUND.volume,
  },
}

// "Doors open" morning takeover: at this UK time on working days, EVERY
// board (telesales AND sales & ops) shows a ~30s takeover — yesterday's
// headline number plus a look at today — then melts back into the live
// board. Softer than the EOD confetti (sunrise gradient, no sound). Fires
// once per day per browser; graceMinutes lets a screen that wakes late still
// catch it. ?doors=1 forces a demo run without marking the day as
// celebrated. If EOD and DOORS are both forced in the same demo, EOD wins
// (Wallboard checks the ?eod param directly, not just state, so the two
// effects can't race on the same mount).
export const DOORS_CELEBRATION = {
  enabled: true,
  hour: 8,
  minute: 50,
  graceMinutes: 5,
  weekdaysOnly: true,
  durationMs: 30_000,
}

// Server-side gate for the telesales "fresh leads overnight" count (lib/
// provider/bronze.ts): that query only runs inside this window (or with a
// ?morning/?doors param), never on every 15s/20s poll all day — a wider
// window than DOORS_CELEBRATION.graceMinutes so the number is ready for
// screens that load a little before/after the takeover itself.
export const MORNING_QUERY_WINDOW = { startHour: 8, startMinute: 30, endHour: 9, endMinute: 30 }

// Frontend polling cadence and the threshold after which the feed is
// declared stale (amber pill).
export const POLL_INTERVAL_MS = 20_000
export const STALE_AFTER_MS = 60_000

// Rep pipeline (money waiting) refresh cadence — server-side cache TTL in
// lib/provider/bronze.ts. Slower than POLL_INTERVAL_MS on purpose: the
// underlying leads barely move minute to minute, so there is no need to pay
// for a fresh BigQuery read on every 20s board poll (owner brief 19 Aug 2026).
export const PIPELINE_REFRESH_MS = 5 * 60_000

// Rep pipeline TAKEOVER (SALES & OPS board only, gated on features.pipeline):
// unlike CELEBRATION/EOD_CELEBRATION/DOORS_CELEBRATION above, this is not a
// once-per-day event — the board runs all day, so the takeover recurs on a
// plain interval: everyMs of normal board time, then durationMs full-screen,
// then back, indefinitely. Owner brief 19 Aug 2026: "make the sales people
// feel how much money is sitting waiting to be chased." Never shows while
// EOD/DOORS owns the screen (Wallboard checks both) or when there's no
// pipeline to show. ?pipeline=1 forces one immediate demo showing; the
// normal recurring cadence carries on once it ends.
export const PIPELINE_TAKEOVER = {
  enabled: true,
  everyMs: 3 * 60_000, // normal board dwell between showings (owner 19 Aug: every 3 min)
  // Owner 20 Aug: "show on the screen for 3 mins ... repeat the whole thing"
  // — the takeover now LOOPS its full sequence (headline+buckets → rep pages)
  // for the whole duration.
  durationMs: 3 * 60_000,
  weekdaysOnly: false,
}

// The mock provider simulates dialling inside these UK working hours.
export const WORKDAY = { startHour: 8, startMinute: 30, endHour: 17, endMinute: 30 }
