# Availability View — Build Plan

**Status:** building — Phase 1 in progress
**Companion docs:** `availability_diagnosis.md` · `whos_free_use_case.md`

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Calendar data | MS Graph `calendarView` | Already working; shared calendar is the reliable record |
| Backend | Python stdlib `http.server` (existing) | No new framework — just new routes in `dashboard/server.py` |
| Caching | In-memory dict + timestamp | Same pattern already used in `dashboard/data.py`, no new deps |
| Frontend | React (CDN) + CSS vars | Exact pattern in `public/index.html` — new tab, same design system |
| Auth | Client-credentials (existing) | Already in `.env`, already tested |
| **New dependencies** | **None** | Everything reuses what's already there |

---

## Rep → Region Mapping

| Rep | Region | Notes |
|---|---|---|
| Kelly Miller | North East | |
| Rob Chapman | Yorkshire & Humber | |
| Chris Krammer | Yorkshire & Humber | |
| Sam Chapman | North West | |
| Samantha Doyle | North West | |
| Kris Noorouzi | London, South East, East of England | Also works Saturdays |
| Chris Mannix | London, South East, East of England | |
| Niall Devanish | South West | |
| Paul Slade | Wales | |
| Chris Southworth | South East | Freelancer (Ambivo) |
| Chris Cash | Yorkshire & Humber | Freelancer (Ambivo) |
| Keith Wiggins | Yorkshire & Humber | Freelancer (Ambivo) |
| Scott Conor | Any (when needed) | |
| Josh Barron | Any (when needed) | |

---

## Slot Rules

- **Increment:** 30 minutes (09:00, 09:30, 10:00, ...)
- **Working hours:** 09:00–17:00, Mon–Fri for all reps
- **Kris exception:** also works Saturdays 09:00–17:00
- **Minimum job duration:** 1.5 hours — a slot is only shown as `free` if the rep has ≥ 90 min clear from that point
- **Travel time:** agent's judgment for v1 — v2 feature (postcode-to-postcode routing)

---

## Phase 1 — Availability Engine

**File:** `calendar_analysis/availability.py`

Pure Python, no HTTP. Three functions the server will call:

- **`fetch_events(days=14)`** — pulls the shared calendar via Graph, returns raw events
- **`build_grid(events, region)`** — resolves rep per event (email→canonical, fallback category), classifies each event as `appointment / time_off / admin`, then for each rep+day produces a list of 30-min slots labelled `free / booked / off`
- **`REP_REGION_MAP`** — the 14-rep mapping above, hardcoded as the source of truth

**Rep resolver priority:**
1. Attendee email → canonical rep (e.g. `kelly@trustelectricheating.co.uk` → `Kelly Miller`)
2. Category → canonical rep (e.g. `Kourosh` → `Kris Noorouzi`)
3. Unresolved → excluded from grid

**Time-off detection** (regardless of Outlook's `showAs=free` bug):
- All-day events, OR
- Subject contains: `holiday / hols / off / ooo / out of office / annual leave / day off / a/l / sick / no appts / bank holiday / busy / leave / training`

**Done when:** `python -c "from calendar_analysis.availability import build_grid; print(build_grid(...))"` prints a readable grid locally.

---

## Phase 2 — Server Routes

**File:** `dashboard/server.py` (add routes)

- `GET /api/availability?region=Yorkshire+%26+Humber&days=10` → JSON grid, 5-min in-memory cache
- `GET /api/availability/regions` → list of distinct regions (for the dropdown)

Same caching pattern already in the server (`_cache` dict + lock).

**JSON shape:**
```json
{
  "generated_at": "2026-06-24T09:00:00",
  "region": "Yorkshire & Humber",
  "dates": ["2026-06-24", "2026-06-25", ...],
  "reps": [
    {
      "name": "Kelly Miller",
      "region": "North East",
      "today_count": 3,
      "days": {
        "2026-06-24": [
          {"time": "09:00", "status": "booked", "subject": "Mr Smith"},
          {"time": "09:30", "status": "booked", "subject": null},
          {"time": "10:00", "status": "free"},
          ...
        ]
      }
    }
  ]
}
```

**Done when:** `curl http://localhost:8765/api/availability?region=Yorkshire+%26+Humber` returns valid JSON.

---

## Phase 3 — Availability Tab (the grid)

**File:** `public/index.html` (new tab, same sidebar nav)

```
Availability
├── Region dropdown  (Yorkshire & Humber / North East / North West / ...)
├── Date strip  (Mon 30 · Tue 1 · Wed 2 ... next 10 working days, scrollable)
└── Per-rep rows
    ├── Rep name  +  region badge
    ├── Today's load: "3 booked today"
    └── Slot cells:
          green  = free (≥ 90 min clear)
          grey   = booked
          red    = off / time-off
```

**Interactions:**
- Click a free slot → highlights that time column across all reps (shows who else is free at the same time)
- Hover a booked slot → tooltip shows subject (customer name)
- Region dropdown filters to reps in that region; "All" shows everyone

**Done when:** the tab renders live data, time-off shows red, free slots show green.

---

## Phase 4 — Slot Finder Panel

A panel within the Availability tab — the 20-second booking moment.

```
[ Region ▼ ]   [ Date from → to ]   [ Any rep ▼ ]   [ Find slots ]

Results:
  Kelly Miller    ·  Tue 30 Jun  ·  09:00   [ Copy ]
  Rob Chapman     ·  Tue 30 Jun  ·  10:30   [ Copy ]
  Chris Krammer   ·  Wed 1 Jul   ·  09:00   [ Copy ]
```

- **Copy button** copies `"Kelly Miller · Tue 30 Jun · 09:00"` to clipboard — ready to paste into a CRM note while the customer is on the phone
- Results ranked: earliest first, ties broken by rep load (fewer bookings first)

**Done when:** agent can enter a region + date range and get a ranked list of copyable slots.

---

## Phase 5 — Deploy to Vercel

- Add `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` to Vercel environment variables (Settings → Environment Variables)
- Verify Vercel's Python runtime can reach `login.microsoftonline.com` (it can — no restrictions)
- Push and smoke-test the live URL

---

## Build Order

```
Phase 1 (engine) → Phase 2 (routes) → Phase 3 (grid) → Phase 4 (slot finder) → Phase 5 (deploy)
```

Each phase is tested before moving to the next. Phase 1 is the hardest — get the availability logic right and the rest is UI.

---

## Location Lookup (confirmed)

**Primary input:** postcode prefix (e.g. `S14` → Yorkshire & Humber)
**Secondary input:** city name (e.g. `Sheffield` → Yorkshire & Humber)
Both inputs auto-resolve to a region, then show the reps for that region.

### Postcode prefix → region

| Region | Postcode prefixes |
|---|---|
| North East | NE, SR, DH, TS, DL |
| Yorkshire & Humber | LS, BD, HX, HD, WF, DN, S, HU, YO, HG |
| North West | M, L, BL, OL, SK, WN, WA, PR, FY, BB, LA, CH, CA, CW |
| London | E, EC, N, NW, SE, SW, W, WC, BR, CR, DA, EN, HA, IG, KT, RM, SM, TW, UB, WD |
| South East | BN, CT, GU, ME, MK, OX, PO, RG, RH, SL, SO, SP, TN |
| East of England | CB, CM, CO, IP, LU, NR, PE, SG, SS, AL, HP |
| South West | BS, BA, BH, DT, EX, GL, PL, SN, TA, TQ, TR |
| Wales | CF, SA, NP, LL, SY, LD |

### City → region (major cities, normalised to lowercase)

| Region | Cities |
|---|---|
| North East | newcastle, sunderland, durham, middlesbrough, gateshead, stockton, hartlepool, darlington, south shields |
| Yorkshire & Humber | leeds, sheffield, bradford, hull, york, huddersfield, halifax, doncaster, rotherham, wakefield, barnsley, harrogate |
| North West | manchester, liverpool, salford, bolton, stockport, bury, oldham, wigan, warrington, preston, blackpool, blackburn, lancaster, chester, carlisle |
| London | london (and all inner/outer boroughs) |
| South East | brighton, southampton, portsmouth, oxford, reading, milton keynes, maidstone, guildford, crawley, basingstoke, canterbury, eastbourne |
| East of England | norwich, cambridge, ipswich, luton, peterborough, colchester, chelmsford, southend |
| South West | bristol, plymouth, exeter, swindon, gloucester, cheltenham, bath, bournemouth, poole, truro, torquay |
| Wales | cardiff, swansea, newport, wrexham, bangor, aberystwyth |

### Scott Conor & Josh Barron — fallback logic

These two reps are **not assigned to a region**. They appear in the slot finder **only when no regional rep has a free slot** for the requested time window. Shown at the bottom of results under a "No regional rep available — escalation options:" heading.

---

## Separate Internal Webapp (confirmed)

The availability tool is a **separate Vercel project** from the main dashboard. Reasons:
- Main dashboard is company-wide (no login needed there)
- Availability tool is telesales-only — role-gated
- No disruption to the existing dashboard

### Auth design
- Flask app (Vercel Python serverless)
- Username + bcrypt-hashed password in a `users.json` config file (no database needed)
- Session cookie, 8-hour expiry
- Two roles: `admin` (manage users, see all regions) · `user` (telesales — use slot finder)
- Two initial admins (to be named by the developer before deploy)

---

## Out of Scope (v1)

- Travel time between postcodes (v2 — needs routing API + postcode on each booking)
- One-click booking write-back to the calendar (v2 — writes to live calendar, higher risk)
- Mobile-optimised layout (v2)
- Notifications / alerts when a rep's day fills up
