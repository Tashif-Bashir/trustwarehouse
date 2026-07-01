# Availability Tool — Bug Log

Bugs found in production use, with root-cause analysis and fix plans. Newest first.
Status keys: 🔴 open · 🟡 in progress · ✅ fixed (deployed)

---

## BUG-001 — Lead search misses leads that exist ✅ fixed + deployed (2026-07-01)
**Reported:** telesales searched "Gillie Gilbert" (an old lead) → didn't show up.

### Analysis (confirmed against data)
The lead exists: `id=2000145757975554`, stored as `first_name='Gillie Gilbert'`, `last_name=''`.
Testing `_search_leads`:
- `"Gillie Gilbert"` → **1 result** (works)
- `"gillie"` → works
- `"Gilbert Gillie"` (words swapped) → **0 results** ✗
- `"gillie  gilbert"` (double space) → **0 results** ✗

Root causes in `_bq_search_leads` (app.py):
1. **Word-order sensitivity** — name match is a single `LIKE '%<whole query>%'` against `first_name || ' ' || last_name`, so the typed words must appear in the exact same order.
2. **Whitespace sensitivity** — a double space (or stray spaces) breaks the substring match.
3. **Cross-field AND** — provided fields are AND-ed; if telesales also typed a postcode/phone that doesn't match this lead (e.g. the lead's postcode is blank), the lead is excluded even on a perfect name match.

### Fix plan
- **Tokenise the name**: split the typed name on whitespace; require **each token** to appear in `first_name || ' ' || last_name` (AND of per-word `LIKE`s). Order- and whitespace-independent → "gilbert gillie", "gillie  gilbert", "gillie" all match.
- Keep phone/email/postcode as additional filters, but reconsider hard-AND for those too (a blank field on the lead shouldn't hide a strong name match). Simplest: only AND fields the user actually filled, and tokenise name; leave phone/email/postcode exact-ish. *(If misses persist, relax non-name fields to OR-boost.)*
- Files: `availability_app/app.py` (`_bq_search_leads`).

---

## BUG-002 — Booked appointment gets a white/wrong Outlook category ✅ fixed + deployed (2026-07-01)
**Reported:** booked calendar-only for Niall (gold tag in Outlook) → event got a **white** tag named "Niall" instead of Niall's gold "Niall Devenish" tag.

### Analysis (confirmed against Graph master categories)
`api_book` sets `categories: [rep_first]` where `rep_first = rep_name.split()[0]` → e.g. `"Niall"`.
But the shared mailbox's **pre-coloured master categories** are named inconsistently:
- Full name: `Scott Conor`, `Paul Slade`, `Chris Southworth`, `Niall Devenish`, `Samantha Doyle`, `Chris Cash`, `Chris Kramer`
- First name: `Rob`, `Josh`, `Kelly`, `Sam`, `Keith`, `Merv`
- Alias/nickname: `Chris M` (Chris Mannix), `Kourosh` (Kris Noorouzi), `Sammy`

`"Niall"` is **not** a master category, so Outlook creates a new colourless one. (Also note spelling drift: our rep is "Niall Dev**a**nish" but the category is "Niall Dev**e**nish"; our "Chris Kra**mm**er" vs category "Chris Kra**m**er".)

### Authoritative category → rep mapping (from owner)
| Outlook master category | Rep (`app.reps` name) |
|---|---|
| Chris Cash | Chris Cash |
| Chris Kramer | Chris Krammer |
| Chris M | Chris Mannix |
| Chris Southworth | Chris Southworth |
| Keith | Keith Wiggins |
| Kelly | Kelly Miller |
| Josh | Josh Barron |
| Kourosh | Kris Noorouzi |
| Niall Devenish | Niall Devanish |
| Paul Slade | Paul Slade |
| Rob | Rob Chapman |
| Sam | Sam Chapman |
| **Sammy** | **Samuel Hamilton** |
| Samantha Doyle | Samantha Doyle |
| Scott Conor | Scott Conor |

**Bonus bug found:** Samantha Doyle currently has alias `sammy`, but "Sammy" is **Samuel**'s category → Samuel's appointments mis-resolve to Samantha in the grid/diary. Fixing the aliases fixes this too.

### Fix plan (no new column — correct the aliases + match to master category)
1. **Correct `app.reps` aliases** so every category resolves to the right rep:
   - Samantha Doyle: remove `sammy` → `[]`
   - Samuel Hamilton: add `sammy` → `["sammy"]`
   - Chris Krammer: add `chris kramer` → `["chris kramer"]`
   (existing good aliases stay: Niall `niall devenish`, Kris `kourosh`, Chris M `chris m`, Sam `sam`, Chris S `chris s`.)
2. **`_master_categories()`** — cached (~1h) fetch of `GET /users/{mailbox}/outlook/masterCategories` display names.
3. **`_rep_outlook_category(rep_name)`** — candidates in order [full name, *aliases, first name]; return the **exact** master-category name that matches (case-insensitive); fallback to first name.
4. `api_book` sets the category from `_rep_outlook_category(rep_name)` instead of the bare first name.
- With corrected aliases, all 15 reps map to their real coloured category. Correcting the aliases also fixes grid/diary resolution (esp. Samuel/Sammy). No engine code change — aliases already flow into `CATEGORY_TO_REP`.
- Files: `availability_app/app.py` (`api_book`, helpers); `app.reps` alias data.

---

## BUG-003 — Need a Location field (Outlook event Location + CRM address) ✅ fixed + deployed (2026-07-01) · decided: Location→Street, Postcode→Zip
**Reported:** the form has Postcode only. Need a **Location** field that (a) populates the calendar event's actual **Location** field, and (b) updates the lead's **standard address** in the CRM (Street/City/State/Zip — *not* the custom region field).

### Analysis
- **Outlook event location:** Graph event has a `location` property (`location: { "displayName": "..." }`) — currently we don't set it. The Location box in the screenshot is Outlook auto-parsing a typed address.
- **CRM standard address:** the lead has standard fields `street`, `city`, `state`, `zipcode`, `country` (distinct from the custom region field `location_6349396e4a08d` / `post_code_5af30a907e7c3`). Today's booking updates none of these.

### Fix plan (needs one decision — see below)
- Add an optional **Location / Address** field to the booking form (React `SlotDrawer`).
- On booking:
  - Set the Graph event `location.displayName` = the Location value.
  - `_ss_update_lead` also writes the standard address: **`street`** = Location, **`zipcode`** = Postcode (already captured). *(City/State: TBD — see decision.)*
- Region detection stays on Postcode (unchanged).
- Files: `availability_app/templates/availability.html` (form + payload), `availability_app/app.py` (`api_book` location on event + `_ss_update_lead` address fields).

**Decision needed:** how to map the Location text to CRM fields —
1. Whole Location string → `street`, Postcode → `zipcode` (simplest, recommended), or
2. Add separate City field too, or
3. Attempt to parse Location into street/city.

---

## Deployment note
Fixes will be developed + tested locally first, then deployed to production (`vercel --prod`) the same way as the initial release. The two engine copies (`calendar_analysis/availability.py` + `availability_app/availability_engine.py`) must stay in sync for any engine change.
