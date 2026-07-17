# Live telesales metre

Full-screen wallboard showing today's outbound activity for the four
telesales agents. Next.js 14 (App Router) + Tailwind, deployed to Vercel
as its own project.

## Tuning

Everything tunable lives in `lib/config.ts`:

- **Agent roster + colours** — colour follows the agent, never the rank.
- **`SCORING`** — the leaderboard weighting (appointment points vs talktime
  minute points).
- **`POLL_INTERVAL_MS` / `STALE_AFTER_MS`** — refresh cadence and when the
  Live pill turns amber.

## Data source

The UI only ever talks to `/api/metrics`, which calls `getMetrics()` in
`lib/provider/index.ts` — the single seam for swapping sources.

- **Now:** `lib/provider/mock.ts` — deterministic simulation seeded on
  (day, agent, minute), so the numbers drift upward through the UK workday
  like a real dialling floor and are identical across serverless instances.
- **To go live:** add `lib/provider/bronze.ts` querying
  `bronze.ascend_calls` (outbound counts / >30s / talktime, ≤90s behind the
  phone system) and the `app.bookings` + CRM union for appointments, then
  route on `DATA_SOURCE=bronze`. See the main dashboard's
  `_telesales_whiteboard()` for the appointment-union reference logic.
