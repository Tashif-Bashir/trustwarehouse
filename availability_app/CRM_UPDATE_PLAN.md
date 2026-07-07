# CRM Auto-Update on Booking — Implementation Plan

## What this feature does

When a telesales person books an appointment in the webapp, it automatically updates the SharpSpring lead so they don't have to switch to the CRM and do it manually.

## Test lead

**Name:** Zzz Testlead Donotuse  
**ID:** `2000146206227458`  
**Email:** zzz.testlead.donotuse@trustwarehouse.internal  
**Phone:** 07700900123 · **Postcode:** LS1 1AB  

Use this lead for all local testing before deploying. (Two earlier test leads were deleted by staff mid-test — hence the obvious do-not-use name. Always `getLeads`-verify the ID before each test write.)

### Phase 2 findings (SharpSpring notes)
- The create-note method is **`createNotes`** (plural), not `createNote`. Object needs `whoID` + `whoType='lead'` + `note`, and `authorID` for attribution.
- **`createNotes` succeeds even when `whoID` points to a deleted/nonexistent lead** — it does not validate the parent. So success is NOT proof the lead is real.
- There is **no `getNotes`** read method, and `bronze.sharpspring_notes` only syncs daily — so note author attribution can only be confirmed visually in the SharpSpring UI.
- **Locked ordering for booking:** `getLeads`-verify the lead exists → `updateLeads` → `createNotes`. Never create a note without verifying the lead first.

---

## SharpSpring updates triggered on booking

### 1. `updateLeads` — 1 API call

| Field (system name) | Value set | Notes |
|---|---|---|
| `status_633ae6f6ac6fe` | `"Appointment"` | Domestic Lead Status — the key field |
| `appointment_time___date_5ae8ca2f532bc` | e.g. `"2026-07-01 10:00:00"` | Appointment datetime (UTC) |
| `appointment_booked_5ae8cb01a35c6` | `"Yes"` | Picklist |
| `appointment_made_by_65e1a90253305` | e.g. `"Alicja Aleksiuk"` | Picklist — must match exactly or leave blank |
| `date_time_appointment_booked_687fabb701341` | current datetime | When the booking was made |
| `ownerID` | rep's SharpSpring owner ID | Reassigns lead to the field rep |
| `leadStatus` | `"qualified"` | |

**ownerID rule:** fetch the lead's current `ownerID` first, then overwrite with the rep's ID if known. If rep's ID is unknown, preserve existing ownerID (don't default to API account owner).

### 2. `createNote` — 1 API call

Creates a note in the lead's activity feed (the Notes tab in SharpSpring), attributed to the telesales person who booked it.

**Note content:**
```
Appointment booked: [DATE] [START]–[END] with [REP NAME]
Postcode: [POSTCODE] | Customer: [CUSTOMER NAME]

[NOTES TYPED IN BOOKING FORM]
```

**Attribution:** pass `ownerID` = telesales person's SharpSpring owner ID so their name appears (e.g. "Alicja Aleksiuk · Jun 30, 2026"). If owner ID unknown, note still gets created but attributes to API account.

**Total SharpSpring API calls per booking: 2** (well within 50,000/day quota)

---

## Setup required before building

### A. Field rep SharpSpring owner IDs → `app.reps` table

Add `sharpspring_owner_id` column to `app.reps` in BigQuery. Pre-populated from inference:

| Rep | SharpSpring owner ID | Confidence |
|---|---|---|
| Scott Conor | `313417658` | Confirmed |
| Samuel Hamilton | `375396352` | High |
| Niall Devanish | `348844032` | High |
| Kris Noorouzi | `354337792` | High |
| Josh Barron | `365659136` | High |
| Sam Chapman | `347165696` | High |
| Samantha Doyle | `374417408` | Medium |
| Kelly Miller | `343922688` | Medium |
| Paul Slade | `375397376` | Medium |
| Chris Mannix | `367741952` | Medium |
| Rob Chapman | `376562688` | Medium (new) |
| Chris Krammer | `343919616` | Uncertain |
| Chris Southworth | unknown | Freelancer — may not have SS account |
| Chris Cash | unknown | Freelancer — may not have SS account |
| Keith Wiggins | unknown | Freelancer — may not have SS account |

Admin can verify/correct via the Manage Reps page.

### B. Telesales user SharpSpring owner IDs → webapp users

Add `sharpspring_owner_id` field to each webapp user record (users.json or equivalent). This is used to:
1. Attribute the created note to the correct person (shows their name in SharpSpring activity feed)
2. Map to the `appointment_made_by` picklist value

Valid `appointment_made_by` picklist values:
`Gemma Taylor`, `Susan England`, `Alicja Aleksiuk`, `Lily Harpham`, `Reilly Andrew`, `Josh Baron`, `Kim Ellis`, `Victoria Ramsden`, `Alice Hardegon`, `Declan Franks`, `Other`, `Amelia Konczewska`, `Alisha Moore`, `Ashleigh Nankervis`

Admin sets these in Manage Users page.

---

## Architecture: lead search (and the freshness gap)

SharpSpring API only allows filtering leads by `id` or `emailAddress` — name/postcode/phone search is **not** supported (confirmed: the `where` clause rejects every other field). That is exactly why search runs against BigQuery, not the API.

### The freshness gap — and why it's safe

`bronze.sharpspring_leads` is synced from SharpSpring **every 30 minutes**. A lead created in the last 30 min will not be in BigQuery yet. Because the team works to a ~5-min-to-first-call target, booking a brand-new lead is a **daily occurrence, not an edge case**.

**Key insight:** BigQuery staleness only affects *findability*, never *correctness*. At booking time we always read+write **live** SharpSpring data:
- Always fetch the live lead by `id` (or `email`) at booking — gets the current `ownerID` so we never wipe it, and confirms the lead still exists.
- Then `updateLeads` + `createNote` against live SharpSpring.

So BigQuery is purely a convenience for finding the lead ID without copy-pasting. The actual booking is always live.

### The human never touches a lead ID

The SharpSpring lead ID is **not visible/findable** in the SharpSpring UI for telesales staff (confirmed: nobody on the team, including the owner, can locate it). Therefore the ID must never be a human-facing input. The telesales person only ever types what they can **see**: name, postcode, or phone. The app resolves the hidden ID itself from whichever source returns the lead.

### Two merged search sources — covers every case

| Source | Covers | SS API cost |
|---|---|---|
| **BigQuery** `bronze.sharpspring_leads` | All leads > ~30 min old (the full 60k history) | 0 |
| **`getLeadsDateRange`** (today, `timestamp='create'`), cached ~5 min in memory | Today's fresh leads not yet synced to BigQuery | ~1 call / 5 min (lazy) |

`getLeadsDateRange` is confirmed working on this account. Today's fresh set is tiny (≈9 leads by mid-morning), so one call returns all of it. Even phone-only inbound leads get an auto-generated email (`<id>@trustelectricheating.co.uk`) and carry the **phone number as their name**, so they're findable by phone. Every returned lead includes its `id`, so the app always obtains the ID without the human seeing it.

**UI flow — multi-field "Find the lead" form (filled once, one search):**
Explicit fields so telesales never has to be told "now type email, now type X". They fill whatever they have; the more fields, the narrower the result.

| Field | Match logic |
|---|---|
| Full Name | partial `LIKE` (case-insensitive) |
| Phone | normalised both sides (reuse `normalise_phone`: `07…`/`+44…`/`0044…` all equal) — usually unique |
| Email | exact match (also the SharpSpring fresh-lookup key) |
| Postcode | partial `LIKE` — narrows common names |

1. Telesales fills any combination of the fields → one **Search** (button / Enter), `POST /api/search_leads` with the filled fields.
2. Backend combines the non-empty fields (AND them for precision) and runs the query against **both** sources — BigQuery (history) + today's fresh-leads cache — merges, dedupes by lead `id`.
3. Matches shown in a list (name, postcode, phone, current status). A lead created seconds ago appears alongside year-old ones — single result set, no separate "fresh lead" path.
4. User clicks a result → customer name + postcode auto-fill into the booking form, lead `id` captured in a hidden field.
5. **Skip option:** "Book without CRM update" — calendar invite still created, CRM skipped (for the genuinely-not-found case; no worse than today's manual process).

### Fresh-leads cache (quota-smart)
- In-memory cache of today's `getLeadsDateRange` result, refreshed lazily only when a search arrives and the cache is older than 5 min.
- ≈1 call per 5 min while searches are happening, 0 when idle. Fresh leads become searchable within ~5 min of creation (vs 30 min for the BigQuery sync).

### Explicitly NOT doing
- **"Paste the lead ID" anything** — the ID is unfindable for users; dropped entirely.
- **Speeding up the SharpSpring full sync** — burns quota; the lazy fresh-leads cache closes the gap far more cheaply.

### API calls per booking (recap)
- **Known rep** (we have their owner ID): `getLeads`-by-id (confirm + show) + `updateLeads` + `createNote` = **3 calls**. (The confirm read can be skipped if the lead came from a fresh SS lookup we just did.)
- Either way ≤3 calls/booking. At ~50 bookings/day that's ~150 calls vs the 50,000/day quota — negligible.

---

## Build phases

### Phase 1: Data setup ✅ DONE
- [x] Add `sharpspring_owner_id` column to `app.reps` BigQuery table
- [x] Add `sharpspring_owner_id` + `sharpspring_name` fields to `app.users`
- [x] Infer owner IDs — used `bronze.sharpspring_notes` (`author_id`→`display_name`), authoritative; corrected 3 earlier regional guesses (Kelly=343919616, Rob Chapman=343922688, Josh Barron=370671616)
- [x] Add owner ID field + inline save to Manage Reps admin page (`/admin/reps/owner`)
- [x] Add owner ID + Booked-By picklist to Manage Users admin page (`/admin/users/sharpspring`, validates against `MADE_BY_OPTIONS`)
- [x] Keep both engine copies in sync (`availability_engine.py` + `calendar_analysis/availability.py`)
- Verified: admin pages render with new fields; both POST routes round-trip; bad picklist value rejected.

**Needs owner verification (open items):**
- Chris Cash & Keith Wiggins reps have **no** SharpSpring owner ID (freelancers, likely no SS account) — confirm.
- **Gia Rose** is not in the `appointment_made_by` picklist → her Booked-By is blank. Decide: add "Gia Rose" to the SharpSpring picklist, or she logs as "Other".
- Sanity-check the rep→owner-ID table on the Manage Reps page.

### Phase 2: Backend — SharpSpring helpers ✅ DONE
- [x] Verify create-note works → method is **`createNotes`**; tested on test lead
- [x] `_ss_call()` generic JSON-RPC helper (+ `_cfg()` .env fallback for local dev)
- [x] `_ss_get_lead(lead_id)` — verified: returns lead when live, **None when deleted**
- [x] `_ss_fresh_leads_today()` — getLeadsDateRange today, 5-min lazy cache
- [x] `_ss_update_lead(...)` — verified: sets status/appt/booked/made_by, **reassigns ownerID to rep**
- [x] `_ss_create_note(lead_id, text, owner_id)` — verified success
- [x] `POST /api/search_leads` — verified: finds the fresh lead (not yet in BigQuery) by name/phone/postcode; merges history + fresh; dedupes by id
- Note: BigQuery `[history]` can return leads since deleted in SharpSpring — handled by the booking-time `getLeads`-verify (locked ordering).

**Visual check ✅ CONFIRMED (30 Jun):** lead `2000146206227458` shows the note authored by **"Alicja Aleksiuk"** (so `authorID` controls attribution), owner reassigned to **Scott**, and appointment fields set. SharpSpring also auto-created an Opportunity on status→Appointment (its own automation, same as manual booking — no action needed).

### Phase 3: Backend — wire into booking ✅ DONE
- [x] `api_book()` accepts `lead_id` + `skip_crm`
- [x] CRM block runs only after the calendar event succeeds; ordering verify → update → note
- [x] Reassign to rep owner id; if rep id unknown, preserve lead's current owner (never default to API account)
- [x] `made_by` from booker's `sharpspring_name`; note attributed via booker's `sharpspring_owner_id`
- [x] CRM failure never blocks booking (own try/except)
- [x] Returns `crm_status`: updated / failed / not_found / skipped
- Verified end-to-end (real booking + cleanup): valid lead→updated (status, made_by=Alicja, owner=Scott); deleted lead→not_found; no lead→skipped; skip_crm→skipped. Booking succeeds in all cases.

### Phase 4: Frontend — booking modal changes ✅ DONE
- [x] "Find the lead" section (Full Name, Phone, Email, Postcode) at top of booking form
- [x] Search button + Enter → `POST /api/search_leads`; results list (name · postcode · phone · status)
- [x] Selecting a result fills customer name/postcode/email + captures hidden `lead_id`; "change" to unlink
- [x] No-match state message; "Book calendar only — don't update SharpSpring" checkbox when linked
- [x] Confirm modal + success message reflect whether SharpSpring will be / was updated
- [x] Fixed pre-existing bug: `clearSelection` called undefined `setCcEmail` (now `setCcEmails([''])`)
- Verified: page renders (200), markup present, and the in-browser JSX compiles cleanly via `@babel/standalone` (same transformer the browser uses).

### Session fixes (found during local testing) ✅
- [x] **Slot-end model** — clicking start→end now books *to the end slot's time* (15:00→16:00 = 15:00–16:00), not +30. Single-click = 30-min appointment (also books the last slot of the day). Conflict check uses only the occupied blocks.
- [x] **"Calendar only" toggle** moved out of the `leadId` block — now always visible, so you can choose calendar-only before/without finding a lead.
- [x] **Telesales booked-timestamp** (`date_time_appointment_booked`) was written in UTC → read 1h behind during BST. Now writes UK wall-clock via a no-dependency `_now_uk()` BST helper (verified against zoneinfo; 2026 transitions Mar 29 / Oct 25 correct). No `requirements.txt` change.

### Phase 5: Local testing (before deploying) ✅ DONE
- [x] Local dev server (`127.0.0.1:5050`) with `.env` loaded + template auto-reload
- [x] Searched & linked the test lead via the UI
- [x] Booked end-to-end; verified in SharpSpring: status=Appointment, appt time, booked=Yes, Booked-By name, owner→rep, note in activity feed under the booker's name
- [x] Slot-end and timestamp fixes verified by the owner through the UI
- [x] (Manual-ID fallback dropped from design — lead ID is never human-facing)

### Phase 6: Deploy — ✅ DONE (deployed to production)
- [x] Added `SHARPSPRING_ACCOUNT_ID` + `SHARPSPRING_SECRET_KEY` to Vercel production (via REST API — the CLI's stdin piping kept saving empty values on Git-Bash/Windows). Verified via `env pull` (32/32 match).
- [x] Verified `availability_engine.py` (Vercel copy) has all feature code + only differs from local by the intended credential handling
- [x] `vercel --prod` → build OK → live at **https://trust-availability.vercel.app**
- [x] Smoke test passed: login 302; `/api/reps/diary` 200 (15 reps, BigQuery+Graph); `/api/search_leads` 200 (25 leads, SharpSpring+BigQuery)
- [ ] **Follow-up:** the feature code is still **uncommitted** — commit it so git matches production (owner's call; on `main`, branch first per repo convention)
- [ ] **Optional:** one live book→cancel on the test lead through the prod UI for final confidence

---

# Feature 2: One-click Appointment Cancellation (from the rep diary)

**Goal:** from the rep diary, cancel an appointment in one click — delete the calendar event **and** revert the CRM — so telesales never touch SharpSpring to cancel.

## Decisions locked
- **Scope:** **tool-booked appointments only** (we recorded the lead link at booking). 100% reliable, zero mismatch risk. Manually-/legacy-booked appointments get no Cancel button (do those in the CRM). Coverage grows as the team books through the tool.
- **Owner revert:** back to the **telesales person who booked it** (the booker).
- **On cancel, in SharpSpring:** `status_633ae6f6ac6fe` → **`Appointment Cancelled`**, `ownerID` → booker, `appointment_booked_5ae8cb01a35c6` → **`No`**, plus a note *"Appointment cancelled by {canceller} on {date}"* (attributed to whoever clicks cancel).
- Also **delete the Graph calendar event**. CRM revert and event delete each fail-open (one failing doesn't abort the other); report partial failures.

## The crux — backtracking event → lead (solved by recording the link)
A diary entry is just a calendar event ("POSTCODE - customer · rep · time") — it carries no lead ID or booker. So we **record the link at booking time** in a new table, keyed by the Graph event ID.

### New table: `app.bookings`
| column | purpose |
|---|---|
| `event_id` (STRING) | Graph calendar event id — the join key to a diary entry |
| `lead_id` (STRING, nullable) | SharpSpring lead (null = calendar-only booking) |
| `booker_username`, `booker_owner_id`, `booker_name` | who booked (owner revert + note) |
| `rep_name`, `rep_owner_id` | field rep the lead was assigned to |
| `customer`, `postcode`, `appt_start` | display/audit |
| `booked_at` (TIMESTAMP) | audit |
| `status` (STRING) | `active` / `cancelled` |
| `cancelled_at`, `cancelled_by` | audit on cancel |

Doubles as an audit trail for the later sales/performance work.

## Build phases

### Phase 7: Booking records the link ✅ DONE
- [x] Created `app.bookings` in BigQuery (16 cols; safe additive — live app doesn't read it)
- [x] `api_book` captures the Graph event id from the create response
- [x] `_record_booking()` inserts an `active` row on every booking (fail-open). Stores `lead_id` only when `crm_status == 'updated'`, so cancel reverts CRM only for bookings that changed it; others cancel calendar-only.
- Verified end-to-end: a booking wrote a full row (event_id, lead_id, booker alicja/368143360, rep Scott/313417658, appt date/start/end, status=active); cleaned up after.

### Phase 8: Diary surfaces what's cancellable ✅ DONE
- [x] `build_rep_diary` adds `event_id` to each appointment (both engine copies)
- [x] `_annotate_cancellable()` marks each appointment `cancellable` if its event has an `active` `app.bookings` row (single `IN UNNEST` query; runs before caching, cache cleared on book/cancel)
- Verified: the tool-booked appointment showed `cancellable: true`; all 175 existing non-tool appointments showed `false`.

### Phase 9: Cancel backend — `POST /api/cancel` ✅ DONE
- [x] `_get_active_booking` lookup by `event_id` (404 if not tool-booked)
- [x] Ordering: **delete event first** (abort 502 if it fails — never revert CRM with the event still standing) → then best-effort CRM revert
- [x] `_ss_cancel_lead`: status `Appointment Cancelled`, Booked `No`, owner→booker (preserves current owner if booker id unknown) + cancellation note (attributed to canceller via `_now_uk` date)
- [x] `_mark_booking_cancelled` (status/cancelled_at/cancelled_by) + caches cleared
- Verified end-to-end: book→cancel reverted status/Booked/owner (back to Alicja the booker), row→cancelled, event 404 (deleted).

### Phase 10: Rep diary UI ✅ DONE
- [x] "Cancel" button on `ApptRow` — shown only when `cancellable && !is_past` (appears on row hover; always on today's rows)
- [x] Confirm modal (subject · rep · date/time + warning that it removes the event and reverts the CRM)
- [x] `confirmCancel` → `POST /api/cancel` → refreshes the diary; result shown in a toast
- Verified: `reps.html` JSX compiles via `@babel/standalone`.

### Phase 11: Local test (before deploy)
- [ ] Book the test lead → confirm an `app.bookings` row is written with the event id
- [ ] Cancel from the diary → verify: event deleted; lead status `Appointment Cancelled`; owner back to booker; `Appointment Booked`=No; cancellation note present; row marked `cancelled`
- [ ] Verify a non-tool event has no Cancel button

> Cancel depends on the booking feature being live, so the `app.bookings` table starts empty and fills as the team books via the tool. Booking + Cancel deploy together (still on hold until owner approves).

---

# Feature 3: Heating / Water appointment types (Enquiry Type → dual lead statuses)

**Goal:** the CRM tracks heating and water as parallel pipelines. When booking, telesales must be able to say *what* the appointment is for, and the tool must update the right status field(s) — plus record the customer's stance on the other product — so nobody touches the CRM manually.

## CRM fields (confirmed via getFields)
| Field | System name | Notes |
|---|---|---|
| Enquiry Type | `lead_warmth__1__69ea236712886` | picklist: `Heating` / `Heating and Water` / `Water` (repurposed old "lead warmth" field). **Human-chosen on the form** (design changed during preview testing): a third dropdown, pre-filled from the **live** CRM value at lead selection (`/api/lead_enquiry` — search's BigQuery copy can lag ≤30 min), independent of the two status dropdowns, written back exactly as picked ("— leave as is —" = don't write). Covers the rare case where a customer enquires about one product but books another. |
| Domestic Lead Status (main/heating) | `status_633ae6f6ac6fe` | already written today |
| **Domestic Lead Status WATER** | `domestic_lead_status__1__6a0f07b50b5d2` | same 17 options as main |

(The CRM has a whole parallel water pipeline — Appointment Status WATER, Appointment Amount WATER (£), Installation/Delivery Date WATER — out of scope here, but relevant to the future sales scorecard.)

## Decisions locked (with owner)
- **Status matrix** ("other side" outcome is the telesales person's call, per the customer's stance):

| Booked | Main status | WATER status |
|---|---|---|
| Heating + Water | `Appointment` | `Appointment` |
| Heating only | `Appointment` | `Follow Up` / `Not Interested` / unchanged — telesales picks |
| Water only | `Follow Up` / `Not Interested` / unchanged — telesales picks | `Appointment` |

- **UI: two dropdowns.** "Appointment for": Heating / Water / Heating + Water — **pre-filled from the linked lead's Enquiry Type** (Heating if unknown), editable. When one-sided, a second dropdown appears — "Other enquiry": **Leave unchanged (default)** / Follow Up / Not Interested. Hidden when Heating + Water.
- **No automatic other-side writes** — nothing is written to the other pipeline unless telesales actively picks it (default Leave unchanged). Avoids wrong writes on pure single-product enquiries.
- **Generic appointment fields unchanged** — Appointment Time & Date, Appointment Booked=Yes, Booked By, telesales timestamp, owner reassignment, note: all still written for every type. Only the two status fields vary.
- **Cancel reverts appointment fields only** — whichever status fields the booking set to `Appointment` become `Appointment Cancelled`; any Follow Up / Not Interested written on the other side stays. Requires recording the appointment type on the booking row.

## Build phases

### Phase 12: Backend ✅ DONE
- [x] Verified bronze columns: `lead_warmth___1___69ea236712886`, `domestic_lead_status___1___6a0f07b50b5d2`; live write of the WATER field on the test lead confirmed
- [x] Search returns `enquiry_type` (BigQuery + fresh paths; note: history value can lag the CRM by ≤30 min — fine for an editable pre-fill)
- [x] `api_book` accepts + validates `appt_type` / `other_outcome` (both ⇒ other forced empty)
- [x] `_ss_update_lead` status matrix implemented
- [x] `app.bookings.appt_type` column added (NULL = heating for old rows)
- [x] `/api/cancel` reverts per `appt_type`
- Verified live, all 3 cycles book→cancel: water+FollowUp → main=Follow Up/water=Appointment → cancel: water=Cancelled, **Follow Up preserved**; heating+NotInterested mirror-image ✓; both → both Appointment → both Cancelled ✓

### Phase 13: Frontend (booking modal) ✅ DONE
- [x] "Appointment for" dropdown (Heating/Water/Heating + Water), pre-filled from linked lead's `enquiry_type`, shown when a lead is linked
- [x] Conditional "Other enquiry" dropdown (label flips to "Heating enquiry"/"Water enquiry"; default Leave unchanged; hidden for both)
- [x] Confirm modal spells out exactly which statuses will be written
- [x] Payload includes `appt_type` + `other_outcome`; JSX validated via @babel/standalone

### Phase 14: Local + preview testing ✅ DONE
- [x] All 3 status-matrix cycles (book→cancel) verified live via test client; other-side outcomes preserved on cancel
- [x] Enquiry Type: live pre-fill at selection (`/api/lead_enquiry`), independent human-chosen dropdown, write + leave-as-is both verified
- [x] Owner verified end-to-end on the preview URL

### Phase 15: Preview deploy → verify → promote ✅ DONE
- [x] Preview env vars set up (11 vars; GOOGLE_CREDENTIALS_JSON etc. recovered from the SA key file — the Production copies are `sensitive`-type, unreadable)
- [x] SSO Deployment Protection disabled (app has its own login; previews are public like production)
- [x] Stable preview alias: **trust-availability-preview.vercel.app** (re-point on each preview deploy)
- [x] UX polish added during preview: booking success = popup ("Appointment booked" → OK → drawer closes + grid refreshes); errors stay inline with Try again
- [x] Owner approved on preview → merged to main → promoted to production

---

# Feature 4: West Midlands & East Midlands regions

**Gap:** the app has 9 regions; the Midlands don't exist. Birmingham/Coventry/Stoke/Derby/Nottingham/Leicester etc. postcodes resolve to **no region** → "no regional rep" for a large chunk of England.

## Rep assignments (owner-specified)
| Region | Reps |
|---|---|
| **West Midlands** | Sam Chapman, Samantha Doyle, Chris Krammer |
| **East Midlands** | Rob Chapman, Chris Krammer |

(All keep their existing regions — these are additions: Sam/Samantha keep North West, Chris K & Rob keep Yorkshire & Humber.)

## How regions flow (analysis)
- `all_regions()` is **derived from rep data** (`app.reps.regions`) — the new regions appear in dropdowns as soon as the data is updated, no code needed for that part.
- Postcode → region and city → region are **static maps in both engine copies** (`POSTCODE_TO_REGION`, `CITY_TO_REGION`) — these need code.
- `_KNOWN_REGIONS` in app.py (Manage Reps checkboxes) is static — needs the two entries.
- None of the Midlands postcode areas are currently mapped to anything, so this is purely additive — **no existing region loses a postcode** (MK stays South East, DN/S stay Yorkshire).

## Postcode areas to add (official UK region definitions)
| Region | Postcode areas |
|---|---|
| West Midlands | **B** (Birmingham), **CV** (Coventry), **DY** (Dudley), **ST** (Stoke), **TF** (Telford), **WR** (Worcester), **WS** (Walsall), **WV** (Wolverhampton), **HR** (Hereford) |
| East Midlands | **DE** (Derby), **LE** (Leicester), **LN** (Lincoln), **NG** (Nottingham), **NN** (Northampton) |

Cities added to the city map accordingly (birmingham, coventry, wolverhampton, walsall, dudley, solihull, west bromwich, stoke-on-trent, telford, stafford, worcester, hereford, nuneaton, tamworth, redditch → West Mids; derby, nottingham, leicester, lincoln, northampton, mansfield, chesterfield, loughborough, kettering, corby → East Mids).

## Rollout order (shared-DB safety)
1. Code on a branch: both engine maps + `_KNOWN_REGIONS` → preview.
2. **Then** update `app.reps` regions data (instant everywhere; harmless before code ships — the region simply appears in dropdowns and works by manual selection; postcode typing starts resolving once code is live).
3. Verify on preview (type `B1 1AA` → West Midlands with the 3 reps; `NG1 1AA` → East Midlands with the 2), merge → production.

---

# Deployment workflow (from Feature 3 onward): branch → Vercel preview → merge → production

The team actively uses `trust-availability.vercel.app`, so new features are no longer deployed straight to production. Instead:

1. **Branch:** develop on a feature branch (e.g. `feat/water-appointments`) — `main` stays equal to what production runs.
2. **Local test first** (as before, against test lead `2000146206227458`).
3. **Preview deploy:** `vercel` (NO `--prod`) from `availability_app/` → builds a **preview deployment** on its own URL (`trust-availability-<hash>-trustprojects.vercel.app`). **Production is untouched** — the team keeps using the old version.
4. **Verify on the preview URL** (owner + telesales if wanted).
5. **Promote:** merge branch → `main`, push, then `vercel --prod`. Production switches only at this moment.

**One-time setup needed before the first preview:**
- [ ] Copy all env vars to the **Preview** environment (they currently exist in **Production only** — a preview would boot without credentials). Same REST API method as before (`target: ["preview"]`).
- [ ] Check **Deployment Protection** on the first preview — team projects often require a Vercel login to view preview URLs; disable for previews or use a share link if it blocks testers.

**Caveats:**
- Preview and production share the **same live backend** (BigQuery, SharpSpring, calendar, Redis) — a booking made on the preview URL is real. Always test with the Zzz test lead.
- We deploy from the working tree via CLI (not git-connected), so the branch is for git hygiene + rollback safety; the preview builds whatever is checked out locally.

---

## Graceful degradation rules

| Scenario | Behaviour |
|---|---|
| No lead selected | Calendar booked, CRM skipped, user sees "Booked (no CRM update)" |
| SharpSpring API down | Calendar booked, CRM skipped silently, logged to server |
| Lead not found by ID | Calendar booked, CRM skipped, user sees warning |
| `appointment_made_by` name not in picklist | Set field blank rather than sending bad value |
| Rep owner ID unknown | Preserve existing `ownerID`, don't overwrite |

---

## Files to change

| File | Change |
|---|---|
| `availability_app/app.py` | Add search endpoint, SS helpers, modify `api_book()` |
| `availability_app/availability_engine.py` | Same SS helpers (Vercel bundle) |
| `availability_app/templates/availability.html` | Lead search UI in booking modal |
| `availability_app/templates/admin_users.html` | Add SS owner ID + SS name fields per user |
| `availability_app/templates/reps.html` or admin reps page | Add SS owner ID field per rep |
| BigQuery `app.reps` | Add `sharpspring_owner_id` column |
| `availability_app/users.json` | Add `sharpspring_owner_id` + `sharpspring_name` per user |

---

## Local dev vs production

The feature is gated on `lead_id` being present — if no lead is selected, the booking works exactly as it does today. So no feature flag is needed. Local testing uses the real SharpSpring API against the test lead (`2000146205551618`). Deploy only after local end-to-end passes.

---

# Feature 5: Book reps from other regions (collapsed grid section)

**Ask:** telesales want to book reps outside the customer's region (border postcodes, reps willing to travel). Decision: instead of per-rep postcode exception lists (Option C of the border analysis — now superseded), show **all** other regions' reps in the grid below the fallback section, **collapsed by default** — human judgement, zero config to maintain.

- Engine (`build_grid`, both copies): when a region is selected, every non-regional/non-fallback rep is emitted with `is_other: true` (full slot data included).
- UI: "▸ Other regions' reps (N) — click to show · travel may apply" toggle row under Flexible Coverage; expanded rows show home-region badges; booking works identically from any row.
- Verified: Yorkshire → 4 regional + 2 fallback + 9 other, all with slots.
