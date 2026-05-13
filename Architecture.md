# ARCHITECTURE.md

The complete system map. The why, the what, and the how — with every component, data flow, and design decision drawn out.

---

## Table of contents

1. [Document purpose](#document-purpose)
2. [Executive summary](#executive-summary)
3. [Business context](#business-context)
4. [System overview](#system-overview)
5. [Architecture principles](#architecture-principles)
6. [Data sources — detailed](#data-sources--detailed)
7. [The three layers (medallion architecture)](#the-three-layers-medallion-architecture)
8. [Identity resolution](#identity-resolution)
9. [Orchestration and scheduling](#orchestration-and-scheduling)
10. [Infrastructure stack](#infrastructure-stack)
11. [Security architecture](#security-architecture)
12. [Data quality and monitoring](#data-quality-and-monitoring)
13. [Failure modes and recovery](#failure-modes-and-recovery)
14. [Performance and capacity](#performance-and-capacity)
15. [Migration paths (future state)](#migration-paths-future-state)
16. [Architecture decision records](#architecture-decision-records)
17. [Glossary](#glossary)

---

## Document purpose

**Audience:** The developer building this (you), future developers who inherit it, and anyone technical who needs to understand how the system works.

**Scope:** The complete data warehouse — from raw data collection through to business-ready gold tables. Does NOT cover dashboard UI (separate future project) or business analysis methodology (lives with the data team).

**Update cadence:** Update this document whenever an architectural decision is made that contradicts what is written here. Append to the ADR section. Never delete past decisions — strike them through.

---

## Executive summary

A cloud-hosted **medallion architecture data warehouse** for a heating company. Pulls together data from six sources (CRM, phone system, three ad platforms, and manual uploads) into one queryable foundation. Built solo by a new hire in 30–40 hours over three weeks. Total monthly running cost: **£0**.

**Built with industry-standard tools:**

```
┌──────────────────────────────────────────────────────────────┐
│  Airbyte Cloud  +  Python (dlt)  +  dbt  +  Motherduck       │
│      Extract            Extract        Transform     Store    │
│   (no code)           (custom code)                          │
└──────────────────────────────────────────────────────────────┘
                              ↓
                  GitHub Actions orchestrates
                  everything on schedule
```

**Three guarantees this design provides:**

1. **All raw data preserved forever** — bronze layer is the audit trail
2. **All transformations are testable and reversible** — dbt models with version control
3. **All consumers read from one place** — gold layer is the single source of truth

---

## Business context

Why this matters in pounds and pence. From the original brief by Fiona (Telesales Manager):

### The revenue model

```
Current state:
   1,520 leads/month × £45 CPL  =  £68,400 spend
   1,520 leads → 380 appointments (1-in-4 telesales conversion)
   380 appointments → 127 customers (1-in-3 rep conversion)
   127 customers × £3,610 AOV  =  £458,470 revenue

Stage 1 improvement (telesales 1-in-4 → 1-in-3):
   1,520 leads → 507 appointments
   507 → 169 customers
   169 × £3,610 = £610,090 revenue
   ┌─────────────────────────────────┐
   │  +£151,620 from telesales only  │
   └─────────────────────────────────┘

Stage 2 improvement (rep conversion 1-in-3 → 1-in-2.5):
   507 → 203 customers
   203 × £3,610 = £732,830 revenue
   ┌─────────────────────────────────┐
   │  +£122,740 additional revenue   │
   └─────────────────────────────────┘

Stage 3 improvement (CPL £45 → £35):
   1,954 leads at £35 CPL = same £68,400 spend
   1,954 → 651 appointments → 260 customers
   260 × £3,610 = £938,600 revenue
   ┌─────────────────────────────────┐
   │  Total uplift: £480,130/year    │
   └─────────────────────────────────┘
```

### Why the company cannot improve any of this today

Because the data needed to make these decisions is **scattered across systems that do not talk to each other:**

```
SharpSpring     ┐
   knows:       │  But knows NOTHING about call durations,
   - which lead │  call counts, time-to-first-call, or which
   - which      │  call duration converts to appointments.
     campaign   │
                ┘

Wildix          ┐
   knows:       │  But knows NOTHING about which calls were
   - call time  │  to leads vs random, which lead source the
   - duration   │  caller came from, or whether the call led
   - agent      │  to an appointment.
                ┘

Google/Meta/    ┐
Bing            │  Know spend but NOTHING about whether that
   know:        │  spend produced appointments or revenue.
   - spend      │  Cost-per-click is visible. Cost-per-
   - clicks     │  appointment is invisible.
                ┘
```

**The warehouse is the join.** Once built, these questions become single SQL queries:

- Which channel gives us the cheapest appointments?
- Are agents calling fresh leads within the 10-minute window?
- Which agent converts qualified conversations (2+ min calls) best?
- What is the ROI on Meta vs Google this month?

---

## System overview

The complete system at a glance:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   COLLECTION TIER                                                           │
│   ─────────────────                                                         │
│                                                                             │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│   │  Google Ads  │    │     Meta     │    │   Bing Ads   │                  │
│   │     API      │    │     API      │    │     API      │                  │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│          │                   │                   │                          │
│          └───────────┬───────┴───────────┬───────┘                          │
│                      │                   │                                  │
│                      ▼                   ▼                                  │
│            ┌──────────────────────────────────┐                             │
│            │      AIRBYTE API KEY Injestion               │                             │
│            │      Daily sync                  │                             │
│            │      Managed scheduler           │                             │
│            │      Schema evolution            │                             │
│            └────────────────┬─────────────────┘                             │
│                             │                                               │
│   ┌──────────────┐          │                                               │
│   │ SharpSpring  │          │     ┌──────────────┐                          │
│   │   JSON-RPC   │──────────┼─────│   PYTHON     │                          │
│   │      API     │          │     │   + dlt      │                          │
│   └──────────────┘          │     │              │                          │
│                             │     │ Hourly sync  │                          │
│   ┌──────────────┐          │     │              │                          │
│   │    Wildix    │──────────┼─────│  Driven by   │                          │
│   │   REST API   │          │     │   GitHub     │                          │
│   │     (CDR)    │          │     │   Actions    │                          │
│   └──────────────┘          │     └──────┬───────┘                          │
│                             │            │                                  │
│   ┌──────────────┐          │            │     ┌─────────────────┐          │
│   │ Manual CSVs  │──────────┼────────────┼─────│ csv_loader.py   │          │
│   │ (drop & run) │          │            │     │ (on demand)     │          │
│   └──────────────┘          │            │     └────────┬────────┘          │
│                             │            │              │                   │
└─────────────────────────────┼────────────┼──────────────┼───────────────────┘
                              │            │              │
                              ▼            ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   STORAGE & TRANSFORMATION TIER  —  MOTHERDUCK                              │
│   ───────────────────────────────────────────                               │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  bronze schema  (raw, immutable, all VARCHAR/JSON)              │       │
│   │  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────┐  │       │
│   │  │ ad platform     │  │ sharpspring  │  │ wildix             │  │       │
│   │  │ tables          │  │ tables       │  │ tables             │  │       │
│   │  │ (Airbyte)       │  │ (dlt)        │  │ (dlt)              │  │       │
│   │  └─────────────────┘  └──────────────┘  └────────────────────┘  │       │
│   │  ┌────────────────────────────────────────────────────────────┐ │       │
│   │  │ manual_* tables                                            │ │       │
│   │  └────────────────────────────────────────────────────────────┘ │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                              │                                              │
│                              ▼ dbt build                                    │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  silver schema  (cleaned, typed, one row per entity)            │       │
│   │  ┌────────────────────────────────┐  ┌────────────────────────┐ │       │
│   │  │ silver_sharpspring_leads       │  │ silver_wildix_calls    │ │       │
│   │  │ silver_sharpspring_campaigns   │  │ silver_agents          │ │       │
│   │  │ silver_google_ads_spend        │  │                        │ │       │
│   │  │ silver_meta_spend              │  │                        │ │       │
│   │  │ silver_bing_spend              │  │                        │ │       │
│   │  └────────────────────────────────┘  └────────────────────────┘ │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                              │                                              │
│                              ▼ dbt build                                    │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │  gold schema  (joined, calculated, ready)                       │       │
│   │  ┌──────────────────────────────────────────────────────────┐   │       │
│   │  │ gold_leads_enriched           ◄─── single source         │   │       │
│   │  │ gold_agent_performance_daily        of truth for         │   │       │
│   │  │ gold_campaign_attribution           consumers            │   │       │
│   │  └──────────────────────────────────────────────────────────┘   │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   CONSUMPTION TIER  (future, not in this project's scope)                   │
│   ──────────────────                                                        │
│                                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │ Dashboards  │  │ Excel/PBI   │  │ Scheduled   │  │ ML models   │        │
│   │ (web app)   │  │ exports     │  │ reports     │  │ (forecasts) │        │
│   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture principles

The non-negotiable rules this system is built on. Every design decision must respect them.

### 1. Separation of concerns

Three distinct tiers, three distinct responsibilities:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  COLLECT     │ ──→ │  STORE &     │ ──→ │  CONSUME     │
│              │     │  TRANSFORM   │     │              │
│  fetches     │     │  organises   │     │  reads       │
│  raw data    │     │  & cleans    │     │  & uses      │
└──────────────┘     └──────────────┘     └──────────────┘
```

Collection knows nothing about how data will be transformed. Transformation knows nothing about who consumes it. Consumers know nothing about how data arrived. Change one tier without breaking the others.

### 2. Raw data is sacred

The bronze layer is **append-only and immutable.** Nothing is ever deleted, edited, or "fixed" in bronze. If raw data is wrong, the fix happens in silver — and the original mistake stays in bronze as evidence.

```
Time T:    Bronze receives 47 records
Time T+1:  Silver builds → reveals 3 records have bad data
Time T+2:  Silver fix deployed → silver corrects on next run
                                  Bronze still has the 47 originals
                                  (you can prove what happened and when)
```

### 3. The pipeline is reproducible

Given the same bronze data, the same dbt models always produce the same silver and gold output. No randomness. No "did you remember to run that script?" No manual SQL hacks against production.

```
Bronze (immutable)
    + 
dbt models (version controlled)
    =
Silver and gold (deterministic)
```

If gold is wrong, the cause is either in bronze (source issue) or dbt models (code issue). Never anywhere else. This shrinks the debugging space dramatically.

### 4. Everything in code, nothing in the UI

No SQL written in Motherduck's UI that isn't also in a dbt file in git. No Airbyte connectors configured then forgotten about. The git repo is the complete description of the system. If you `git clone` it and provision a fresh Motherduck account, the entire warehouse can be rebuilt from scratch.


### 5. Free until proven necessary

Every component uses a free tier. The system scales until volume forces an upgrade. No premature optimisation, no premature spending. When something demands paying, the case is obvious.

### 6. Portable always, locked-in never

Every tool can be swapped out without rewriting the rest:

- **Motherduck → Snowflake/BigQuery/Databricks** — change dbt adapter, models are 95% identical
- **dlt → Airbyte** — Airbyte can replace dlt sources individually as connectors become available
- **Airbyte → dlt** — works the reverse way too if you outgrow Airbyte's free tier
- **GitHub Actions → Airflow/Prefect** — change the orchestrator, scripts are unchanged

No proprietary languages, no vendor APIs that only one cloud provides.

---

## Data sources — detailed

Each source has its own characteristics, quirks, and collection method. This section is the reference for understanding each one.

### Source 1: SharpSpring (CRM)

```
┌──────────────────────────────────────────────────────────┐
│  SharpSpring                                             │
│  Type:              CRM                                  │
│  Owner:             Marketing/Sales                      │
│  Contains:          Leads, contacts, opportunities,      │
│                     campaigns, agent assignments         │
│  Access:            API keys confirmed                   │
│  Protocol:          JSON-RPC over HTTPS                  │
│  Auth:              accountID + secretKey                │
│  Rate limit:        ~10 req/sec                          │
│  Pagination:        Max 500 records per call             │
│  Date format:       YYYY-MM-DD HH:MM:SS (UK local time)  │
│  Volume:            ~1,500 leads/month                   │
│  Update frequency:  Real-time in source                  │
│  Our sync:          Hourly via Python + dlt              │
│  Incremental key:   updateTimestamp                      │
└──────────────────────────────────────────────────────────┘
```

**Data we pull:**
- `getLeads` — full lead records with status, owner, source, contact info
- `getCampaigns` — campaign metadata (matches the campaign list visible in CRM UI)
- `getOwners` — internal user accounts (used for agent name reconciliation)
- `getOpportunities` — deals and their status

**Quirks to handle in silver:**
- Custom field labels require a separate `getFields` call (fields appear as IDs otherwise)
- Empty values come back as `""` not `null`
- `leadStatus` enum needs mapping to internal `new/contacted/appointment/closed`
- `assignedTo` is an owner ID, must join to owners table to get a name

### Source 2: Wildix (Phone System)

```
┌──────────────────────────────────────────────────────────┐
│  Wildix                                                  │
│  Type:              VoIP phone system                    │
│  Owner:             IT                                   │
│  Contains:          Every call ever made — CDRs          │
│  Access:            API credentials obtained             │
│                     ⚠️  NOT YET TESTED                    │
│  Protocol:          REST API (to be confirmed)           │
│  Auth:              API key (method to be confirmed)     │
│  Volume:            ~500–800 calls/day during business   │
│  Update frequency:  Real-time in source                  │
│  Our sync:          Hourly via Python + dlt              │
│  Incremental key:   call_datetime (to be confirmed)      │
└──────────────────────────────────────────────────────────┘
```

**Data we pull (planned):**
- CDR records — one row per call with: id, datetime, caller, called, duration, direction, agent extension, disposition

**Why this source is special:**
- Phone numbers are the join key for everything — when a Wildix call's `called_number` matches a SharpSpring lead's `phone`, we can attribute the call to the lead
- Without Wildix, the warehouse has half the picture — SharpSpring tells us "this lead exists" but only Wildix tells us "we tried to call them 4 times"
- 2-minute calls are "qualified conversations" — a critical KPI

**Status:** Phase 4 of the build is dedicated entirely to testing these credentials and documenting the real response shape. No silver/gold work depends on Wildix until that test passes.

### Source 3, 4, 5: Ad platforms (via Airbyte)

```
┌──────────────────────────────────────────────────────────┐
│  Airbyte Cloud                                           │
│  ────────────────────────────────                        │
│                                                          │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐      │
│  │ Google Ads │    │   Meta     │    │ Bing Ads   │      │
│  │ connector  │    │ connector  │    │ connector  │      │
│  └─────┬──────┘    └─────┬──────┘    └─────┬──────┘      │
│        │                 │                 │             │
│        └─────────────────┼─────────────────┘             │
│                          │                               │
│                          ▼                               │
│              ┌──────────────────────┐                    │
│              │  Motherduck dest     │                    │
│              │  (configured once)   │                    │
│              └──────────────────────┘                    │
│                                                          │
│  Sync schedule:      Daily                               │
│  Sync mode:          Incremental                         │
│  We control:         Source credentials, sync schedule,  │
│                      which streams to enable             │
│  Airbyte handles:    Auth refresh, retries, schema       │
│                      evolution, rate limiting            │
└──────────────────────────────────────────────────────────┘
```

**Why Airbyte for these three but not for SharpSpring/Wildix:**

| Source | Airbyte connector quality | Decision |
|---|---|---|
| Google Ads | Excellent — native, well-maintained | Airbyte |
| Meta | Excellent — native, well-maintained | Airbyte |
| Bing Ads | Good — native | Airbyte |
| SharpSpring | Limited — community connector, less reliable | Python + dlt |
| Wildix | None | Python + dlt |

Use the right tool for each source. Don't force everything through one path.

### Source 6: Manual CSVs

```
┌──────────────────────────────────────────────────────────┐
│  Manual uploads                                          │
│  Type:              Whatever has no API                  │
│  Owner:             Various (sales reps, ops, you)       │
│  Examples:          - Secured leads CSV (sales)          │
│                     - Agent roster                       │
│                     - Historical data backfills          │
│                     - One-off analyses                   │
│  Update frequency:  Ad-hoc (when someone has new data)   │
│  Our sync:          On-demand Python CLI                 │
│                     `python -m ingestion.manual ...`     │
│  Pattern:           Generic loader, configurable per CSV │
└──────────────────────────────────────────────────────────┘
```

**Why this matters:** Real businesses have data that lives nowhere structured. Spreadsheets, exports, ad-hoc reports. The warehouse must accommodate them without requiring an API.

---

## The three layers (medallion architecture)

The medallion pattern is the heart of the warehouse design. Each layer has one job. Each job is sacred.

### Layer 1: Bronze — "Land it exactly"

```
┌──────────────────────────────────────────────────────────┐
│                      BRONZE LAYER                        │
│                                                          │
│  Job:        Land raw data exactly as it arrived.        │
│  Trust:      Trust the source's claim of what arrived.   │
│  Mutate?     NEVER. Append-only. No updates, no deletes. │
│  Schema:     All VARCHAR or JSON. No type opinions.      │
│  Quality:    Whatever the source sent. Bad rows kept.    │
│  Joins:      None. One table per source per entity.      │
│                                                          │
│  Purpose:    Audit trail. Reprocessing source.           │
│              The "I can prove what happened" layer.      │
└──────────────────────────────────────────────────────────┘
```

**Why bronze exists:**

```
Scenario:  Silver model has a bug.
           For 3 days, gold reports show wrong numbers.
           Fiona makes business decisions on bad data.

WITHOUT bronze:
           - Find the bug, fix it, deploy
           - But silver is built from... silver?
           - There's no "original" to rebuild from
           - You have to re-pull from SharpSpring
           - SharpSpring data has since changed
           - You can NEVER reproduce what gold looked like
             on those 3 days
           - You cannot prove what Fiona saw was wrong
             vs the system being inconsistent

WITH bronze:
           - Find the bug, fix the silver model
           - Re-run dbt build from bronze
           - Silver and gold rebuild deterministically
           - You can prove exactly what each day showed
           - Trust is preserved
```

**Bronze schema design:**

```
trust-pipeline.bronze
├── sharpspring_leads
│   ├── lead_id           VARCHAR
│   ├── first_name        VARCHAR
│   ├── last_name         VARCHAR
│   ├── phone_number      VARCHAR  ← unchanged, may be "+44 7700 900 123"
│   ├── email_address     VARCHAR
│   ├── owner_id          VARCHAR
│   ├── lead_status       VARCHAR  ← unchanged, may be "qualified"
│   ├── create_date       VARCHAR  ← unchanged, string not timestamp
│   ├── update_timestamp  VARCHAR
│   ├── _dlt_id           VARCHAR  ← dlt internal
│   ├── _dlt_load_id      VARCHAR  ← dlt internal — our load timestamp
│   └── _loaded_at        TIMESTAMP
│
├── sharpspring_campaigns
├── sharpspring_owners
├── wildix_calls
├── google_ads_*  (multiple tables from Airbyte)
├── meta_*        (multiple tables from Airbyte)
├── bing_*        (multiple tables from Airbyte)
└── manual_secured_leads
```

Note: Every bronze table has `_loaded_at` so you can query the warehouse and answer "when did this row arrive?" — essential for debugging.

### Layer 2: Silver — "Clean and standardise"

```
┌──────────────────────────────────────────────────────────┐
│                      SILVER LAYER                        │
│                                                          │
│  Job:        Make each source consistent and clean.      │
│  Trust:      Trust nothing from bronze. Validate all.    │
│  Mutate?     Rebuilt by dbt from bronze each run.        │
│              Idempotent — same bronze → same silver.     │
│  Schema:     Properly typed. INT, TIMESTAMP, BOOLEAN.    │
│  Quality:    Bad rows flagged or dropped. Logged.        │
│  Joins:      None across sources yet. One model per      │
│              source's primary entity.                    │
│                                                          │
│  Purpose:    The "everything is now trustworthy" layer.  │
│              You could build a warehouse on silver and   │
│              skip gold — but you'd repeat the same       │
│              joins everywhere.                           │
└──────────────────────────────────────────────────────────┘
```

**What silver does for each source:**

```
                    BRONZE                      SILVER
                    ───────                     ───────
SharpSpring leads:
   phone        "+44 7700 900 123"    →    "447700900123"   ← normalised
   create_date  "2026-05-09 14:30:22"  →    TIMESTAMP        ← typed
   owner_id     "12345"                →    "Lily"           ← name resolved
   leadStatus   "qualified"            →    "contacted"      ← mapped
   first/last   "James", "Wilson"      →    "James Wilson"   ← combined

Wildix calls:
   caller       "07700900123"          →    "447700900123"   ← normalised
   call_start   "09/05/2026 14:32"     →    TIMESTAMP        ← parsed
   extension    "201"                  →    "Lily"           ← name resolved
   duration_ms  "180000"               →    180              ← seconds
                                       →    is_qualified=true ← derived (>=120s)

Google Ads spend (Airbyte):
   spend_micros "45000000"             →    45.00            ← divide by 1M
   campaign     "Boiler Repair UK"     →    "boiler repair uk" ← normalised
                                       →    spend_gbp        ← currency
```

**Silver schema design:**

```
trust-pipeline.silver
├── silver_sharpspring_leads
│   ├── lead_id                  INTEGER
│   ├── full_name                VARCHAR
│   ├── phone_normalised         VARCHAR    ← key for joining to calls
│   ├── email                    VARCHAR
│   ├── source                   VARCHAR    ← campaign name
│   ├── created_at               TIMESTAMP
│   ├── canonical_agent_name     VARCHAR    ← from owners join
│   ├── status                   VARCHAR    ← mapped to standard values
│   ├── outcome                  VARCHAR
│   ├── appointment_booked       BOOLEAN
│   ├── appointment_datetime     TIMESTAMP
│   └── _loaded_at               TIMESTAMP
│
├── silver_sharpspring_campaigns
├── silver_wildix_calls
│   ├── call_id                  INTEGER
│   ├── call_datetime            TIMESTAMP
│   ├── caller_phone_normalised  VARCHAR
│   ├── called_phone_normalised  VARCHAR
│   ├── duration_seconds         INTEGER
│   ├── direction                VARCHAR    ('inbound' | 'outbound')
│   ├── canonical_agent_name     VARCHAR
│   ├── is_outbound              BOOLEAN
│   ├── is_qualified_conversation BOOLEAN   ← duration >= 120
│   └── disposition              VARCHAR
│
├── silver_agents                ← from the seed file
├── silver_google_ads_spend
├── silver_meta_spend
└── silver_bing_spend
```

### Layer 3: Gold — "Joined and ready"

```
┌──────────────────────────────────────────────────────────┐
│                       GOLD LAYER                         │
│                                                          │
│  Job:        Answer business questions in one query.     │
│  Trust:      Built from silver. Trust is preserved.      │
│  Mutate?     Rebuilt by dbt from silver each run.        │
│  Schema:     Wide tables. Pre-computed metrics.          │
│  Quality:    Defensively coded. No nulls in key fields.  │
│  Joins:      ACROSS SOURCES. This is gold's purpose.     │
│                                                          │
│  Purpose:    What consumers query. Single source of      │
│              truth for the business.                     │
└──────────────────────────────────────────────────────────┘
```

**The three gold tables:**

```
┌────────────────────────────────────────────────────────────┐
│  gold_leads_enriched                                       │
│  ───────────────────                                       │
│  Grain: one row per lead                                   │
│                                                            │
│  Joins: silver_sharpspring_leads                           │
│       + silver_wildix_calls (LEFT JOIN on phone)           │
│       + silver_secured_leads (LEFT JOIN)                   │
│                                                            │
│  Pre-computed: attempt_count                               │
│                first_call_at                               │
│                longest_call_seconds                        │
│                has_qualified_conversation                  │
│                minutes_to_first_call                       │
│                called_within_10_min                        │
│                meets_attempt_target                        │
│                is_fresh_lead                               │
│                                                            │
│  Answers: "Which leads need action right now?"             │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  gold_agent_performance_daily                              │
│  ────────────────────────────                              │
│  Grain: one row per agent per day                          │
│                                                            │
│  Aggregates from: gold_leads_enriched                      │
│                 + silver_wildix_calls                      │
│                                                            │
│  Pre-computed: conversion_rate_pct                         │
│                qualified_conversion_rate_pct               │
│                avg_minutes_to_first_call                   │
│                avg_attempts_per_lead                       │
│                qualified_conversations_count               │
│                + status flags (green/red per metric)       │
│                                                            │
│  Answers: "Which agent needs coaching today?"              │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  gold_campaign_attribution                                 │
│  ─────────────────────────                                 │
│  Grain: one row per campaign per day                       │
│                                                            │
│  Joins: silver_google_ads_spend                            │
│       + silver_meta_spend                                  │
│       + silver_bing_spend                                  │
│       + silver_sharpspring_leads (by campaign)             │
│       + gold_leads_enriched (for appointments)             │
│                                                            │
│  Pre-computed: total_spend_gbp                             │
│                leads                                       │
│                appointments                                │
│                cost_per_lead                               │
│                cost_per_appointment                        │
│                lead_to_appointment_rate                    │
│                                                            │
│  Answers: "Which channel gives cheapest appointments?"     │
└────────────────────────────────────────────────────────────┘
```

### Layer flow visualised

```
┌──────────────┐
│  Raw source  │  SharpSpring API returns: { "phone": "+44 7700 900 123", ... }
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  BRONZE                                                  │
│  bronze.sharpspring_leads                                │
│  phone = "+44 7700 900 123"  ← stored exactly as arrived │
└──────┬───────────────────────────────────────────────────┘
       │
       │  dbt build
       ▼
┌──────────────────────────────────────────────────────────┐
│  SILVER                                                  │
│  silver.silver_sharpspring_leads                         │
│  phone_normalised = "447700900123"  ← cleaned            │
│  status = "contacted"               ← mapped             │
│  canonical_agent_name = "Lily"      ← resolved           │
└──────┬───────────────────────────────────────────────────┘
       │
       │  dbt build (joins to silver_wildix_calls)
       ▼
┌──────────────────────────────────────────────────────────┐
│  GOLD                                                    │
│  gold.gold_leads_enriched                                │
│  + attempt_count = 3                                     │
│  + minutes_to_first_call = 7                             │
│  + has_qualified_conversation = true                     │
│  + meets_attempt_target = false  (3 < 4)                 │
│  + called_within_10_min = true   (7 ≤ 10)                │
└──────────────────────────────────────────────────────────┘
```

---

## Identity resolution

Different sources call the same things different names. Two specific reconciliations are critical:

### Phone number normalisation

The single most important transformation in the entire warehouse. Without consistent phone numbers, SharpSpring leads cannot be joined to Wildix calls — and the warehouse loses its core value.

```
INPUT (various sources, various formats)
                │
                ▼
   ┌────────────────────────────┐
   │  normalise_phone()         │
   │                            │
   │  1. Strip all non-digits   │
   │  2. If starts with "00"    │
   │     → strip the "00"       │
   │  3. If starts with "0"     │
   │     → replace with "44"    │
   │  4. Return digits only     │
   └────────────────────────────┘
                │
                ▼
   OUTPUT: pure digits, country code first

   "07700 900 123"      → "447700900123"
   "+44 7700 900123"    → "447700900123"
   "+447700900123"      → "447700900123"
   "00447700900123"     → "447700900123"
   "(0) 7700 900-123"   → "447700900123"
   "020 7946 0958"      → "442079460958"
   ""                   → NULL
   NULL                 → NULL
   "no phone given"     → NULL
```

**Why this matters:**

```
SharpSpring lead:  James Wilson, phone "+44 7700 900 123"
                                       ↓ normalise
                                  "447700900123"

Wildix call:       called "07700900123"
                                       ↓ normalise
                                  "447700900123"

                                  MATCH ✓
                   Now we can attribute the call to James.
```

**Implemented in two places that must produce identical output:**

```
┌───────────────────────┐         ┌───────────────────────┐
│  Python               │         │  SQL (dbt macro)      │
│  shared/phone.py      │         │  normalise_phone.sql  │
│                       │         │                       │
│  Used by:             │         │  Used by:             │
│  - dlt pipelines      │         │  - silver models      │
│  - csv loader         │         │  - gold models        │
│  - tests              │         │  - dbt tests          │
└───────────┬───────────┘         └───────────┬───────────┘
            │                                 │
            └────────┬────────────────────────┘
                     │
                     ▼
       Tested against same 20+ UK phone format fixtures.
       Both implementations MUST produce identical output.
       This is the most critical correctness contract in the system.
```

### Agent name reconciliation

Each source identifies agents differently:

```
                        Source                Agent identifier
                        ──────                ────────────────
SharpSpring lead:       owner_id              "12345"
SharpSpring user:       full name             "Lily Smith"
Wildix call:            extension             "201"
Wildix call:            alias                 "L.Smith"
Manual CSV:             first name            "Lily"

                                              ↓
                              ┌──────────────────────────────┐
                              │  agent_name_mapping.csv      │
                              │  (dbt seed — source of truth)│
                              │                              │
                              │  Lily | 201 | L.Smith |      │
                              │  12345| Lily Smith | Lily    │
                              │                              │
                              │  Sue  | 202 | S.Brown |      │
                              │  12346| Sue Brown | Sue      │
                              │                              │
                              │  ...                         │
                              └──────────────────────────────┘
                                              ↓
                              ┌──────────────────────────────┐
                              │  normalise_agent_name()      │
                              │  dbt macro                   │
                              │                              │
                              │  ANY identifier → canonical  │
                              │  No match → "Other"          │
                              └──────────────────────────────┘
                                              ↓
            ┌─────────────────────────────────────────────────┐
            │  All silver and gold tables use canonical_name  │
            │  ────────────────────────────────────────────   │
            │  Gold queries: GROUP BY canonical_agent_name    │
            │  No source-specific name ever in gold output    │
            └─────────────────────────────────────────────────┘
```

**The seed file is the single source of truth.** When a new agent joins, update the seed → run `dbt seed` → everything downstream picks it up. No code changes.

---

## Orchestration and scheduling

The full orchestration picture — what runs when, what triggers what.

### Schedule overview

```
                      Mon-Fri               Mon-Sun
                    Business hours        24 hours
                    ───────────────       ─────────────────────
   00:00 ┐
   01:00 │ SharpSpring sync hourly  ←─── GitHub Actions cron
   02:00 │                                '0 * * * *'
   03:00 │
   ...   │
   ...   │
   06:00 │ + Airbyte ad platform sync  ← Airbyte Cloud schedule
   ...   │   (Google Ads, Meta, Bing)
   ...   │
   09:00 │ + Wildix CDR sync hourly    ← (potentially restricted
   10:00 │   (Mon-Fri business hours      to business hours
   ...   │    if needed for cost           depending on call
   17:00 │    or rate limit reasons)      volume)
   18:00 │
   ...   │
   23:00 │
   00:00 ┘
```

### Trigger chain

```
┌─────────────────────────────────────────────────────────┐
│  Time-based triggers (cron)                             │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   ┌─────────┐  ┌─────────┐  ┌──────────────┐
   │ Hourly  │  │ Hourly  │  │  Daily       │
   │ Sharp-  │  │ Wildix  │  │  Airbyte     │
   │ Spring  │  │ sync    │  │  ad sync     │
   │ sync    │  │         │  │  (cloud-     │
   │         │  │         │  │   managed)   │
   └────┬────┘  └────┬────┘  └──────┬───────┘
        │            │              │
        └────────────┼──────────────┘
                     │
                     ▼ (each sync completes)
   ┌─────────────────────────────────────┐
   │  pipeline-build.yml workflow        │
   │  triggered by: workflow_run         │
   │                                     │
   │  Runs: dbt build                    │
   │   - silver_sharpspring_leads        │
   │   - silver_wildix_calls             │
   │   - silver_google_ads_spend         │
   │   - silver_meta_spend               │
   │   - silver_bing_spend               │
   │   - gold_leads_enriched             │
   │   - gold_agent_performance_daily    │
   │   - gold_campaign_attribution       │
   │                                     │
   │  Also runs: dbt test                │
   │   - all data quality tests          │
   │   - source freshness checks         │
   └─────────────────────────────────────┘
                     │
                     ▼ (if test fails)
   ┌─────────────────────────────────────┐
   │  Auto-open GitHub Issue             │
   │  Title: "Pipeline failed YYYY-MM-DD"│
   │  Body: dbt error log                │
   │  Assignee: developer                │
   └─────────────────────────────────────┘
```

### Event-based triggers

```
┌─────────────────────────────────────────────────────────┐
│  Event triggers (workflow_run, push, etc.)              │
└────────────────────┬────────────────────────────────────┘
                     │
   ┌─────────────────┼──────────────────┐
   │                 │                  │
   ▼                 ▼                  ▼
push to main      sync completes    PR opened
   │                 │                  │
   ▼                 ▼                  ▼
ci.yml runs    pipeline-build.yml   ci.yml runs
- ruff         - dbt build          - lint
- pytest       - dbt test           - tests
                                    - dbt parse
                                      (no build)
```

### Manual triggers

Always available via `workflow_dispatch` on every workflow. Used for:
- Force-syncing a source ad-hoc
- Backfilling a missed period
- Re-running after a manual fix

---

## Infrastructure stack

The complete tech stack and what each piece does.

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   ORCHESTRATION                                              │
│   ──────────────                                             │
│                                                              │
│   GitHub Actions (free tier — 2,000 min/month)               │
│   ├── Triggers Python scripts on schedule                    │
│   ├── Manages secrets (env injection)                        │
│   ├── Runs dbt after each sync                               │
│   ├── Opens GitHub Issues on failure                         │
│   └── Runs CI on PRs                                         │
│                                                              │
│   Airbyte Cloud (free tier)                                  │
│   ├── Manages ad platform syncs                              │
│   ├── Native scheduler — no GH Actions needed for these      │
│   └── Handles auth, retries, schema evolution                │
│                                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   INGESTION                                                  │
│   ─────────                                                  │
│                                                              │
│   Python 3.11                                                │
│   ├── uv         — package manager (faster than pip)         │
│   ├── dlt        — extract from APIs, load to Motherduck     │
│   ├── pandera    — schema validation                         │
│   ├── pydantic   — data models                               │
│   └── pytest     — testing                                   │
│                                                              │
│   Libraries used:                                            │
│   ├── duckdb     — Motherduck connection                     │
│   ├── requests   — API calls (SharpSpring, Wildix)           │
│   ├── csv-parse  — manual CSV loader                         │
│   └── ruff/black — formatting and linting                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   STORAGE & TRANSFORMATION                                   │
│   ───────────────────────────                                │
│                                                              │
│   Motherduck (free tier — 1GB storage)                       │
│   ├── Cloud-hosted DuckDB                                    │
│   ├── EU region for GDPR compliance                          │
│   ├── Hosts bronze, silver, and gold schemas                 │
│   ├── Accessed via DuckDB Python client                      │
│   └── SQL queries from any tool that speaks DuckDB SQL       │
│                                                              │
│   dbt-core + dbt-duckdb                                      │
│   ├── SQL transformations: bronze → silver → gold            │
│   ├── Tests: unique, not_null, accepted_values, custom       │
│   ├── Source freshness checks                                │
│   ├── Documentation: schema.yml files                        │
│   └── Lineage tracking (built in)                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Why each tool was chosen — full reasoning

| Tool | Chosen because | Alternative considered | Why not the alternative |
|---|---|---|---|
| Python | Dominant language in data eng | Node.js | Smaller data ecosystem |
| dlt | Purpose-built for API→warehouse | Custom requests + SQL | Reinventing the wheel |
| Airbyte | Pre-built connectors for ad platforms | Fivetran | Costs money |
| Motherduck | Free, fast for analytics, portable | SQL Server | OLTP, costs money |
| Motherduck | (same) | Snowflake/BigQuery | Costs money, complex setup |
| dbt-core | Industry standard SQL transforms | Custom Python ETL | Tests, docs, lineage built in |
| GitHub Actions | Free orchestration | Airflow | Complex to host, paid managed |
| uv | Faster than pip | pip + venv | Slower, more steps |
| pytest | Standard Python testing | unittest | Less expressive |
| ruff | Fast linter | flake8 + isort | Slower, multiple tools |

---

## Security architecture

How credentials and PII are handled.

### Credential flow

```
┌────────────────────────────────────────────────────────────┐
│  WHERE CREDENTIALS LIVE                                    │
│                                                            │
│  Local development:                                        │
│   .env file (gitignored, never committed)                  │
│   ├── MOTHERDUCK_TOKEN                                     │
│   ├── SHARPSPRING_ACCOUNT_ID + SECRET_KEY                  │
│   └── WILDIX_API_KEY                                       │
│                                                            │
│  Production (GitHub Actions):                              │
│   GitHub Secrets (encrypted at rest, injected at runtime)  │
│   ├── MOTHERDUCK_TOKEN                                     │
│   ├── SHARPSPRING_ACCOUNT_ID + SECRET_KEY                  │
│   ├── WILDIX_API_KEY                                       │
│   └── AIRBYTE_API_KEY (if needed for triggers)             │
│                                                            │
│  Airbyte:                                                  │
│   Airbyte's own secret store                               │
│   ├── Google Ads credentials                               │
│   ├── Meta credentials                                     │
│   └── Bing credentials                                     │
└────────────────────────────────────────────────────────────┘
```

### What never happens

- ❌ No credential in any file in any git repo, ever
- ❌ No credential pasted into Claude Code chat
- ❌ No credential logged to any output
- ❌ No credential in Motherduck data
- ❌ No "convenience" credential in source code

### PII handling

The bronze layer contains real PII (names, phone numbers, emails). This is acceptable because:

1. **Bronze is in Motherduck**, which is GDPR-compliant when the EU region is selected
2. **Bronze is private** — not accessible without the Motherduck token
3. **The token is in GitHub Secrets** — encrypted at rest, injected only at runtime

Test fixtures committed to git **must not contain real PII.** Use `data-faker` (if available) or anonymise manually.

---

## Data quality and monitoring

How we know the pipeline is working — and how we know when it isn't.

### Quality checks at every layer

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   COLLECTION                                                │
│   ───────────                                               │
│                                                             │
│   At ingestion:                                             │
│   ├── pandera schemas validate API response shape           │
│   ├── dlt's built-in retries handle transient failures      │
│   └── Failed runs surface as red ticks in GitHub Actions    │
│                                                             │
│   ▼                                                         │
│                                                             │
│   BRONZE                                                    │
│   ──────                                                    │
│                                                             │
│   Freshness:                                                │
│   ├── dbt source freshness on every bronze table            │
│   ├── "warn" if no data in last 2 hours                     │
│   └── "error" if no data in last 6 hours                    │
│                                                             │
│   ▼                                                         │
│                                                             │
│   SILVER                                                    │
│   ──────                                                    │
│                                                             │
│   dbt tests:                                                │
│   ├── unique on primary keys                                │
│   ├── not_null on key fields                                │
│   ├── accepted_values on enum-like fields                   │
│   ├── relationships (FK integrity)                          │
│   └── custom: phone format regex, datetime ranges           │
│                                                             │
│   ▼                                                         │
│                                                             │
│   GOLD                                                      │
│   ────                                                      │
│                                                             │
│   Business logic tests:                                     │
│   ├── conversion_rate_pct between 0 and 100                 │
│   ├── attempt_count >= 0                                    │
│   ├── minutes_to_first_call >= 0 when not null              │
│   ├── one row per agent per day (no duplicates)             │
│   └── total leads = sum of leads by agent                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Monitoring and alerting

```
                Pipeline runs successfully?
                          │
              ┌───────────┼───────────┐
              │                       │
             YES                      NO
              │                       │
              ▼                       ▼
       Green tick in           ┌──────────────┐
       Actions tab             │ Auto-open    │
       (no notification        │ GitHub Issue │
        — assumed working)     │              │
                               │ Email sent   │
                               │ to developer │
                               │ (GitHub      │
                               │  default)    │
                               └──────┬───────┘
                                      │
                                      ▼
                               Developer investigates
                                 using runbook in
                                 docs/runbook.md
```

---

## Failure modes and recovery

What can break, and what to do about it.

### Common failure modes

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  FAILURE: SharpSpring API returns 401                    │
│  ────────────────────────────────────                    │
│  Likely cause:                                           │
│    API key rotated, secret expired, or revoked.          │
│  Symptom:                                                │
│    sync-sharpspring.yml run fails. GitHub Issue opens.   │
│  Recovery:                                               │
│    1. Verify credentials still valid in SharpSpring UI.  │
│    2. Update GitHub Secret.                              │
│    3. Re-run failed workflow manually.                   │
│  Data impact:                                            │
│    Bronze paused. Silver/gold show last successful run.  │
│    No data loss — picks up on next successful sync.      │
│                                                          │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                                                          │
│  FAILURE: dbt test fails on silver_sharpspring_leads     │
│  ───────────────────────────────────────────────────     │
│  Likely cause:                                           │
│    Duplicate lead_id arrived, or NULL where unexpected.  │
│  Symptom:                                                │
│    pipeline-build.yml fails. Issue opened with details.  │
│  Recovery:                                               │
│    1. Query bronze to see the offending records.         │
│    2. Determine if source data issue or model bug.       │
│    3. If source: contact SharpSpring or flag to ignore.  │
│       If model: fix dbt model and redeploy.              │
│  Data impact:                                            │
│    Gold not rebuilt. Consumers see stale data until      │
│    fix deployed.                                         │
│                                                          │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                                                          │
│  FAILURE: Motherduck unreachable                         │
│  ────────────────────────────                            │
│  Likely cause:                                           │
│    Motherduck outage (rare), token revoked, quota hit.   │
│  Symptom:                                                │
│    All syncs and dbt builds fail.                        │
│  Recovery:                                               │
│    1. Check status.motherduck.com.                       │
│    2. Verify token in dashboard.                         │
│    3. Check storage quota — upgrade if at limit.         │
│  Data impact:                                            │
│    Pipeline paused. Resumes once Motherduck back.        │
│    No data loss.                                         │
│                                                          │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                                                          │
│  FAILURE: GitHub Actions free tier exhausted             │
│  ──────────────────────────────────────────              │
│  Likely cause:                                           │
│    Scheduled syncs + ad-hoc runs > 2,000 min/month.      │
│  Symptom:                                                │
│    Workflows queued or rejected. No new syncs.           │
│  Recovery:                                               │
│    Short term: pay GitHub for additional minutes (~£3).  │
│    Long term: optimise sync frequency or move to VPS.    │
│  Data impact:                                            │
│    Sync delays. Pipeline catches up after fix.           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Backfill procedure

When data is missing for a specific period:

```
1. Identify the gap window
   SELECT min(_loaded_at), max(_loaded_at) FROM bronze.x

2. Manually trigger sync with date range override
   gh workflow run sync-sharpspring.yml -f since=2026-05-01

3. Verify bronze rows for the period
   SELECT count(*) FROM bronze.x WHERE created_at BETWEEN ...

4. Force dbt rebuild
   gh workflow run pipeline-build.yml

5. Verify gold reflects the backfilled data
   SELECT * FROM gold.gold_leads_enriched WHERE ...
```

---

## Performance and capacity

Where the system stands today and when it will need to scale.

### Current scale (estimated)

```
Source                  Volume                Daily writes
──────                  ──────                ──────────────
SharpSpring leads       1,500 / month         50 / day
SharpSpring campaigns   ~10 active            unchanged
SharpSpring owners      ~5 active             unchanged
Wildix calls            500-800 / day         500-800 / day
Google Ads spend        50 rows / day         50 / day
Meta spend              50 rows / day         50 / day
Bing spend              50 rows / day         50 / day
Manual CSVs             ad-hoc                ad-hoc

Total bronze writes:    ~700 rows / day
Total bronze size after 1 year:  ~256k rows
Storage estimate:       <100 MB
```

The Motherduck **1 GB free tier accommodates 10+ years of data at current volume.**

### When to upgrade

```
Trigger                                      → Action
───────                                      → ──────
Storage approaching 1 GB (90%)               → Motherduck paid tier (£25/mo)
Bronze writes > 50,000/day sustained         → Consider Snowflake/BigQuery
Gold queries > 10 seconds                    → Add materialised aggregates
GitHub Actions usage > 1,800 min/month       → Optimise or upgrade
Wildix volume > 5,000 calls/day              → Move Wildix to streaming
```

### Query performance expectations

```
Query type                          Expected time on current data
──────────                          ─────────────────────────────
"SELECT * FROM gold.x WHERE date    < 100 ms
 = today" (single row return)

"Aggregate gold metrics for         < 500 ms
 last 30 days"

"Full table scan on bronze for      1-3 seconds
 a quarter"

"Complex multi-source join across   3-10 seconds
 silver tables (uncached)"
```

All within acceptable bounds for a management dashboard.

---

## Migration paths (future state)

Where the architecture can grow when the company is ready to invest.

### Path 1: Add more data sources

Easy. The pattern is established:

```
For an Airbyte-supported source:
   1. Connect source in Airbyte UI
   2. Configure Motherduck destination
   3. Sync runs
   4. Add silver model for the new bronze tables
   5. Add to gold joins if relevant
   Time: 2-4 hours

For an API source without Airbyte:
   1. Build Python client in ingestion/{source}/
   2. Build dlt pipeline
   3. Add GitHub Actions workflow
   4. Add silver and gold models
   Time: 1-2 days
```

### Path 2: Scale Motherduck → Snowflake

When data volume justifies it:

```
Motherduck dbt project:
   ├── profiles.yml uses dbt-duckdb adapter
   ├── Connection: md:warehouse?token=...
   └── 99% of SQL identical

Snowflake migration:
   ├── Change adapter to dbt-snowflake
   ├── Update profiles.yml connection
   ├── Run dbt build → models recreated in Snowflake
   ├── Update Airbyte destination to Snowflake
   ├── Update dlt pipelines to Snowflake
   └── Done

Tweaks needed:
   ├── Some regex/string function syntax differences
   ├── Some date function syntax differences
   └── ~95% of models work unchanged

Time: 1-2 weeks for a careful migration
Cost: Snowflake starts at ~£100/month for small workloads
```

### Path 3: Add real-time / streaming

For sub-second freshness on Wildix calls:

```
Current:    Wildix API polled hourly       → 1 hour lag
                  ↓
Future:     Wildix webhook → AWS Lambda    → seconds lag
                          → Bronze table

OR use:     Wildix → Kafka → bronze        → seconds lag
            (if Wildix supports this; investigate)
```

Not needed for v1. Mention to the company when the use case justifies it.

### Path 4: Add Wildix to Airbyte

If/when a Wildix Airbyte connector exists, the architecture simplifies:

```
Current state:                Future state:
─────────────                 ─────────────
Wildix → dlt → bronze         Wildix → Airbyte → bronze
        (custom code)                 (managed)

Effort to migrate: 1-2 days.
Wins:              Less code to maintain. Airbyte handles
                   auth refresh and schema evolution.
```

---

## Architecture decision records

The decisions that shaped this system, with reasoning preserved.

### ADR-001: Use medallion architecture (bronze/silver/gold)

**Date:** Project start
**Status:** Accepted

**Context:** Need a pattern that handles raw data, cleaned data, and business-ready data separately.

**Decision:** Adopt medallion architecture as used at Databricks, Airbnb, and Netflix.

**Consequences:**
- ✅ Clear separation of concerns
- ✅ Industry-standard, easy to hire for
- ✅ Bronze provides audit trail
- ✅ Idempotent transformations
- ⚠️ Three layers means more storage (acceptable given free tier capacity)

---

### ADR-002: Use Motherduck instead of Postgres/SQL Server

**Date:** Project start
**Status:** Accepted

**Context:** Need a warehouse. Company has no existing cloud or database.

**Decision:** Use Motherduck (cloud-hosted DuckDB).

**Consequences:**
- ✅ Free tier covers years of data
- ✅ Purpose-built for OLAP (analytical) queries
- ✅ Faster than SQL Server for our workload
- ✅ EU region for GDPR
- ✅ Portable to other warehouses via dbt
- ⚠️ Less familiar to traditional DBAs
- ⚠️ Smaller ecosystem than Snowflake

---

### ADR-003: Use Airbyte for ad platforms, dlt for CRM/phone

**Date:** Mid-project, when Airbyte access was confirmed
**Status:** Accepted

**Context:** Could use one tool for all sources or split between them.

**Decision:** Airbyte for sources with high-quality native connectors (Google Ads, Meta, Bing). dlt for sources requiring custom logic (SharpSpring's JSON-RPC, Wildix's REST API).

**Consequences:**
- ✅ Less custom code to maintain
- ✅ Airbyte handles ad platform complexity (auth refresh, schema evolution)
- ✅ dlt gives full control where needed
- ⚠️ Two ingestion patterns to understand instead of one
- ⚠️ Two places to debug

---

### ADR-004: Use GitHub Actions for orchestration

**Date:** Project start
**Status:** Accepted

**Context:** Need to schedule syncs and dbt builds. No server available.

**Decision:** GitHub Actions for orchestration.

**Consequences:**
- ✅ Free for our volume
- ✅ Native to GitHub — secrets, logs, history all integrated
- ✅ Zero infrastructure to manage
- ⚠️ 2,000 min/month free tier limit
- ⚠️ Cron precision is per-minute, not per-second

**Alternatives considered:** Airflow (requires hosting), Prefect (paid managed), Dagster (paid managed), Anthropic Cloud Routines (wrong tool, wastes AI quota).

---

### ADR-005: Do NOT use a separate GitHub data repo

**Date:** Mid-project, when Wildix API access was confirmed
**Status:** Accepted (replaces earlier decision)

**Context:** Originally planned a data repo to stage Wildix CSV scrapes. With Wildix API access, this is unnecessary.

**Decision:** All data flows directly from source → Motherduck. No file staging.

**Consequences:**
- ✅ Simpler architecture
- ✅ Less to maintain
- ✅ Faster data flow
- ⚠️ Lose the "file backup" benefit of having raw CSVs in git

---

### ADR-006: Do NOT use Playwright for Wildix scraping

**Date:** Mid-project, when Wildix API access was confirmed
**Status:** Accepted (replaces earlier decision)

**Context:** Without API access, would have needed browser automation.

**Decision:** Use the Wildix API instead. Skip Playwright entirely.

**Consequences:**
- ✅ More reliable (APIs > scrapers)
- ✅ Less brittle to UI changes
- ✅ Faster
- ✅ One ingestion pattern instead of two
- ⚠️ Requires the credentials to actually work (Phase 4 dependency)

---

### ADR-007: Use dbt-core, not dbt Cloud

**Date:** Project start
**Status:** Accepted

**Context:** Need a transformation tool.

**Decision:** dbt-core (open source) run via GitHub Actions.

**Consequences:**
- ✅ Free
- ✅ Industry standard
- ✅ Same SQL works on dbt Cloud later if needed
- ⚠️ Less polished UX than dbt Cloud
- ⚠️ Manual setup for things dbt Cloud automates

---

### ADR-008: Phone number normalisation in two places

**Date:** Phase 1 of build
**Status:** Accepted

**Context:** Phone normalisation needed in both Python (ingestion) and SQL (dbt).

**Decision:** Implement in both `shared/phone.py` and `dbt_project/macros/normalise_phone.sql`. Test both against identical fixtures.

**Consequences:**
- ✅ Same logic available everywhere it's needed
- ⚠️ Two implementations to keep in sync (mitigated by shared test fixtures)

**Alternative considered:** Only in Python, with bronze pre-normalised. Rejected because bronze should be unmodified — silver is the right place for cleaning.

---

## Glossary

**Airbyte** — Managed ETL platform with pre-built connectors. Used here for ad platform data.

**Bronze layer** — Raw landing zone. Data exactly as it arrived. Immutable.

**CDR** — Call Detail Records. The technical name for call logs in phone systems like Wildix.

**dbt** — Data Build Tool. SQL-based transformation framework. Industry standard.

**dlt** — data load tool. Python library for moving data from APIs into warehouses.

**Gold layer** — Business-ready joined and calculated tables. What consumers query.

**Medallion architecture** — Three-layer pattern (bronze/silver/gold) for organising data warehouses.

**Motherduck** — Cloud-hosted version of DuckDB. The warehouse used here.

**OLAP** — Online Analytical Processing. Analytical workloads (warehouses, dashboards). Optimised for reads.

**OLTP** — Online Transaction Processing. Application backends (banking, e-commerce). Optimised for many small reads/writes.

**Silver layer** — Cleaned and standardised data. One row per entity. No cross-source joins yet.