# Commercial Projects Tool — Plan

**Status: ON HOLD (owner decision, 22 Jul 2026).** Nothing is built. Two facts
reshaped the plan before pausing:

1. **No production Glenigan API key — out of budget.** All API-ingestion
   phases below are parked; the team works the Glenigan web portal manually.
   The test key/`reference/` findings remain valid if a key is ever bought.
2. **First real pain point captured + designed (not built): cold-call logging
   OUTSIDE the CRM.** The team cold-calls Glenigan contacts; these must never
   enter SharpSpring, but need a record + the conversation. Agreed design:
   - BigQuery log table (the `app.bookings` pattern): caller, number,
     company/contact, free-text Glenigan project ref (pasted from the
     portal), outcome, notes. Zero SharpSpring contact; a lead is promoted
     to the CRM by a human only when it turns warm.
   - Conversations captured automatically: extend the Ascend transcription
     pipeline to the commercial team's outbound calls regardless of CRM
     lead match (proposed threshold ≥60s).
   - A simple logging page in the usual app stack: each rep's calls
     auto-populated from Ascend CDRs; tap → outcome + project ref + note.
   - Open at pause: exact team roster → Ascend name mapping (Lucy seen in
     call data; Olivia/Merv unverified); threshold sign-off.

This remains a living document — the same role `CRM_UPDATE_PLAN.md` played
for the booking app. Sections marked **HYPOTHESIS** are our best guess and
must be confirmed (or reshuffled) by the commercial team before that phase
is built.

Last updated: 22 Jul 2026

---

## 1. The problem

The commercial team sells electric heating into construction projects. Their
lead source is **Glenigan** (UK/Ireland construction project intelligence —
planning applications, project stages, values, and the companies/contacts on
each project). Two complaints so far, ahead of a proper sit-down:

1. **"Hard to navigate"** — Glenigan's portal is a search engine; the team
   wants a worklist. Finding "my patch's new projects this week" takes
   repeated manual searching.
2. **"Hard to update the CRM when a deal is made"** — progress on a project
   means retyping everything into SharpSpring by hand.

The booking app proved the recipe: don't rebuild the vendor's UI — build the
five clicks the team's day actually consists of, and wire the CRM write-back
so nothing is typed twice.

## 2. What we know about the Glenigan API (confirmed, from public Swagger)

- REST + JSON at `https://www.gleniganapi.com/`, auth = `key` query param on
  every call (`GLENIGAN_API_KEY` in `.env`). **Subscription-scoped** — the key
  only returns what our account pays for.
- 51 endpoints, three families: `/glenigan/project` (+ ~40 filter variants:
  region, county, town, postcode, radius, polygon, sector, stage, status,
  value, role, material, dimensions, planning-application fields),
  `/glenigan/company`, `/glenigan/contact`, plus `/glenigan/health`.
- `GET /glenigan/project/newproject` and `/updatedproject` take a `TimeRange`
  — purpose-built incremental cursors for ingestion.
- `POST /glenigan/project/_search` accepts a raw **Elasticsearch query** body
  — the escape hatch when filter endpoints don't cut it.
- Pagination: `Page` + `Size`, **max 50 rows/page**. `OrderBy=LatestEventDate|Value`.
  Dates `DD-MM-YYYY`; value filters like `From=100k&To=2m`.
- Response fields are NOT documented in the Swagger spec — the **example files
  in `reference/` + the Data Dictionary are the field reference.**

## 2a. Current access — TEST INDEX (verified 10 Jul 2026)

Per the onboarding email (Michael McVeigh, Glenigan) and our verified test call:

- Our key hits a **static test index**: **4,722 projects** with company +
  contact data. It does NOT update — so the `updatedproject` watching feature
  can be *built* against `ProjectHistories` but only properly *tested* once we
  get a live key.
- Limits on this key: **50 results/page, 100 pages/query** (= 5,000 max per
  query via pagination). Live-key limits TBC (§9).
- `health` → 200, `project?Size=1` → 200. Auth confirmed working.
- API support hours 09:00–17:00 Mon–Fri.
- **Confidentiality**: the email, attachments and data are confidential, not
  for circulation outside the company — hence `reference/` is gitignored and
  the app will sit behind login.

## 2b. Response shape (from `Results example.json` — the real reference)

A project record has **128 fields**. The load-bearing ones:

- **Identity/description**: `ProjectId`, `Heading`, `SchemeDescription`,
  `LatestInformation` (plain-English current state — card material),
  `LatestEvent(Date)`, `FirstPublished`, `LastModifiedDate`.
- **Location**: full address fields, `ProjectPostcode`, `ProjectTown`,
  `ProjectCounty`, `ProjectRegion`, `ProjectLocation` = **{lat, lon}** (feeds
  the Three.js map directly), plus hierarchical facets
  `ProjectLocationLevel1/2/3Facet` ("North East#Tyne & Wear#North Shields").
- **Stage/status**: `PlanningStage(Parent)`, `ContractStage(Parent)`,
  `ProjectStatus`, `DevelopmentType`, `PlanningTypes`, start/end dates with
  date-type qualifiers.
- **Size/value**: `Value` (in **£ millions**, `ValueType` calculated/reported),
  `ProjectSize`, `Units`, `Storeys`, `FloorArea`, `SiteArea`.
- **Sectors**: `PrimaryAndSecondarySectors` ("Health#Health Centres/Surgeries"),
  parents for coarse filtering.
- **Who's involved**: `RolesDetails` → role group (Client / Promoter,
  Architect…) → companies (`OfficeId`, business type, contract stage) →
  **named contacts** (`KeyCard_FullContact`, contact id, job title, LinkedIn
  field, phones). `RoleList` = flat variant with addresses + postcodes.
- **⚠ TPS compliance**: phone fields come in `…Phone1NoTps` /
  `…Phone1WithTps` variants — TPS = do-not-call register. **The app must
  surface the NoTps number for cold calls.** This is a compliance feature the
  team currently gets from Glenigan's portal; we must not lose it.
- **`ProjectHistories`**: typed change events (`ProjectHistoryEvent` e.g.
  `PSTG` = planning stage change) with field name, old/new values, timestamp —
  the watching feature is a diff over this list.
- **Parsing gotcha**: multi-value strings use `~` between items and `#`
  between hierarchy levels (e.g. "Windows#Rooflight~Site Works#Railings") —
  handle centrally in silver, not ad-hoc in the app.

**Query language**: the `_search` examples confirm full Elasticsearch bool
queries against these fields (`term` on facets, `range` on `Value`, `nested`
on `ProjectHistories`, relative dates like `now-1d/d`, sort by
`LatestEventDate`). The feed filter will be one saved ES query.

**Data Dictionary** (`reference/Glenigan Data Dictionary 2023.xlsx`): 13
sheets — Project/Company/Office/Contact field definitions + lookup
vocabularies (Category List, Contract Stages, Planning Stages, Application
Types, Role List, Materials, Funding Types, London Boroughs, Procurement
types). The lookup sheets become the app's filter dropdown options.

## 3. What we do NOT know yet (blockers for design)

- ~~Subscription scope~~ → test index confirmed: 4,722 projects incl.
  companies + contacts. **Live subscription scope still TBC** (sectors/regions
  we'll get in production, and live rate limits).
- ~~Response shape~~ → §2b done.
- **The team's actual workflow** — see Open Questions (§8). ← the big one now
- **Volume on a live key**: how many projects match our profile (affects sync
  cadence).
- **CRM shape for commercial**: which SharpSpring pipeline/fields the
  commercial team uses today (they may differ from domestic; `customer_type` /
  `pipeline_category` exist in the lead schema).

## 4. Product shape — HYPOTHESIS until the team confirms

1. **Feed, not search.** Pull only projects matching Trust's ideal profile
   (sectors suited to electric heating, our regions, value band, right
   stages). Each rep sees *their patch*: "14 new projects this week".
2. **Project card.** One screen per project: stage, value, units, timeline,
   companies + named contacts with roles — plus the Trust overlay (claimed by
   whom, status, notes) that Glenigan can't provide.
3. **Workflow states.** New → Claimed → Chasing → Quoted → Won/Lost, plus
   Dismiss ("not for us" — dismissals tune the feed filter over time).
4. **One-click SharpSpring write-back.** Claim/progress/win writes the lead:
   company, contact, owner = rep, note, and the **Glenigan project ID stored
   on the lead** (needs a custom field) — two-way link, no retyping, and
   duplicate-chasing prevention (card shows "already claimed by X").
5. **Watching.** `updatedproject` diffs on claimed projects → "3 of your
   projects moved stage this week" — the moment to ring. The portal makes you
   re-search; the tool watches for you.
6. **3D map view (Three.js — owner requirement).** An interactive UK map:
   projects as markers/columns (height = value) on the rep's patch, click a
   marker → opens the project card. This is the "see what they want to see"
   showcase view. The workhorse screens (feed list, project card, CRM
   actions) stay plain React — Three.js powers the visual layer, not the
   workflow.

## 5. Architecture (mirrors the booking app)

```
Glenigan API ──(ingestion/glenigan/, dlt, newproject+updatedproject cursors,
                50/page pagination, VM systemd timer)──► bronze.glenigan_*
                                                              │
                                              dbt: silver/gold or app dataset
                                                              │
commercial_app/  Flask + in-browser React (+ Three.js for the map)
   ├─ reads BigQuery (feed, cards, map)
   ├─ app.commercial_projects table = Trust overlay (claims, states, notes)
   │    — same pattern as app.bookings
   └─ SharpSpring write-back via the proven client (verify → update → note,
        ownerID always sent, picklists validated via getFields)
Deploy: company Vercel (trustprojects), branch → preview
   (trust-commercial-preview…) → owner verifies → merge main → --prod.
Login: same users model as the booking app (commercial team accounts).
```

**Constraints carried over from the warehouse rules:** free tools only; no
data on the laptop (examples in `reference/` are gitignored vendor material,
not pipeline data); key in `.env`/GitHub Secrets/Vercel env only; Glenigan
data is licensed — the app stays behind login, no public exposure.

## 6. Phases

| Phase | What | Done when |
|---|---|---|
| 0 | **Discovery**: inspect `reference/` files + Data Dictionary; `health` + `Size=1` test call; map subscription scope; sit-down with commercial team (§8) | Scope + field reference documented here; §4 confirmed/reshuffled |
| 1 | **Ingestion**: `ingestion/glenigan/` (client + dlt pipeline), bronze tables, VM timer | Real projects landing in `bronze.glenigan_projects` on schedule |
| 2 | **Feed definition**: the Trust profile filter + BigQuery model feeding the app | Query returns the team's agreed "my patch this week" list |
| 3 | **App skeleton**: login, feed list, project card (read-only) | Team can browse their patch on preview |
| 4 | **Workflow states**: claim/dismiss/chase/quote/win + `app.commercial_projects` | States persist; duplicate-claim prevention works |
| 5 | **CRM write-back**: SharpSpring create/update + Glenigan ID custom field | Deal progress updates CRM in one click, verified on a test lead |
| 6 | **Watching**: updatedproject diffs → "moved stage" panel/digest | Stage changes on claimed projects surface within a day |
| 7 | **Three.js map**: 3D UK patch view wired to the feed | Map ships on prod |

Order of phases 3–7 is negotiable — the team conversation decides what ships
first after the skeleton.

## 7. Design decisions locked so far

- Project lives in this repo at `commercial_app/` (like `availability_app/`);
  ingestion at `ingestion/glenigan/` when Phase 1 starts.
- `commercial_app/reference/` is gitignored (licensed data + real contacts).
- API key: `GLENIGAN_API_KEY` in `.env` (placeholder already in
  `.env.example`). Never printed in chat, logs, or commits.
- Bronze rule applies: store Glenigan responses as-arrived; typing happens in
  silver.
- No API pulls until the owner green-lights the Phase 0 test call.

## 8. Open questions for the commercial team (ask verbatim)

1. Walk me through how you find a project today — where does it hurt first?
2. What makes a project worth chasing? (sector / value band / region / stage)
3. At what stage do you make first contact, and who do you call (developer,
   M&E contractor, architect)?
4. Who covers what patch — regions, sectors, or something else?
5. What do you type into SharpSpring when you start chasing a project? When
   you win one? Which fields matter?
6. How do you avoid two people chasing the same project today?
7. If the tool could tell you ONE thing automatically, what would it be?
8. What does Glenigan's own portal do well that we must not lose?

## 9. Open questions for Glenigan / the API guy

- Rate limits and fair-use policy (not in the Swagger spec).
- Does the subscription include `company` + `contact` endpoints?
- Webhooks or push, or is polling `updatedproject` the intended pattern?
- Licence position on storing their data in our warehouse (standard for API
  customers, but confirm in writing).
