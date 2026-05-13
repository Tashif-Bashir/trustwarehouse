# CLAUDE.md

Technical context for Claude Code. Read this at the start of every session before writing any code.

See `ARCHITECTURE.md` for the high-level "what and why." See `PROMPT.md` for step-by-step build instructions. This file is the technical reference between them.

---

## Project identity

**Name:** Heating Company Data Warehouse
**Purpose:** Cloud-hosted medallion architecture data warehouse
**Sources:** SharpSpring CRM, Wildix phone system, Google Ads, Meta, Bing Ads, manual CSVs
**Owner:** Solo developer, personal GitHub account
**Constraint:** Free tools only. No data stored on the developer's laptop. No Claude Code cloud routines used anywhere.

---

## What we are NOT building yet

- No dashboard
- No CRM replacement
- No real-time data
- No ML models

We are building a data warehouse. Everything else comes later on top of it.

---

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Ad platform ingestion | Airbyte API Key Injestion  | Pre-built connectors, managed scheduling, no custom code needed |
| API ingestion | Python + dlt | Custom logic for SharpSpring (JSON-RPC) and Wildix CDR API |
| Package manager | uv | Fastest Python package manager |
| Warehouse | Motherduck (cloud DuckDB) | Free tier, fast analytics, portable |
| Transformations | dbt-core + dbt-duckdb | Industry standard SQL transformations |
| Orchestration | GitHub Actions | Free, reliable, no server to manage |
| Data validation | pandera (Python) + dbt tests (SQL) | Catch bad data at ingestion and transformation |
| Testing | pytest + dbt tests | Standard Python unit tests + SQL data tests |

**Not used anywhere in this project:**
- Playwright or any browser automation
- Claude Code cloud routines
- A separate GitHub data repo for file staging
- Any local database files

---

## Repository structure

Single code repo. No data repo — all data goes directly to Motherduck.

```
heating-warehouse/
├── ARCHITECTURE.md
├── CLAUDE.md                        ← this file
├── PROMPT.md
├── START_HERE.md
├── README.md
├── pyproject.toml                   ← Python project (uv)
├── .python-version                  ← 3.11
├── .env.example
├── .gitignore
│
├── .github/
│   └── workflows/
│       ├── sync-sharpspring.yml     ← hourly, GitHub Actions
│       ├── sync-wildix.yml          ← hourly, GitHub Actions
│       ├── pipeline-build.yml       ← runs dbt after any sync
│       └── ci.yml                   ← lint + tests on PR
│
├── ingestion/
│   ├── sharpspring/
│   │   ├── __init__.py
│   │   ├── client.py                ← JSON-RPC API client
│   │   ├── pipeline.py              ← dlt pipeline
│   │   └── schemas.py               ← pandera validation schemas
│   ├── wildix/
│   │   ├── __init__.py
│   │   ├── client.py                ← Wildix CDR API client
│   │   ├── pipeline.py              ← dlt pipeline
│   │   └── schemas.py
│   └── manual/
│       ├── __init__.py
│       └── csv_loader.py            ← generic CSV → bronze loader
│
├── dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml.example         ← real profiles.yml is gitignored
│   ├── packages.yml
│   ├── models/
│   │   ├── silver/
│   │   │   ├── _silver__sources.yml
│   │   │   ├── _silver__models.yml
│   │   │   ├── silver_sharpspring_leads.sql
│   │   │   ├── silver_sharpspring_campaigns.sql
│   │   │   ├── silver_wildix_calls.sql
│   │   │   ├── silver_google_ads_spend.sql
│   │   │   ├── silver_meta_spend.sql
│   │   │   ├── silver_bing_spend.sql
│   │   │   └── silver_agents.sql
│   │   └── gold/
│   │       ├── _gold__models.yml
│   │       ├── gold_leads_enriched.sql
│   │       ├── gold_agent_performance_daily.sql
│   │       └── gold_campaign_attribution.sql
│   ├── macros/
│   │   ├── normalise_phone.sql
│   │   └── normalise_agent_name.sql
│   ├── seeds/
│   │   ├── agent_name_mapping.csv
│   │   └── outcome_categories.csv
│   └── tests/
│
├── shared/
│   ├── phone.py                     ← phone normalisation (Python)
│   ├── motherduck.py                ← connection helper
│   └── agent_names.py               ← agent reconciliation helpers
│
├── tests/
│   ├── fixtures/
│   │   ├── sharpspring/             ← sample API responses
│   │   └── wildix/                  ← sample CDR responses
│   ├── test_phone.py
│   └── test_sharpspring_client.py
│
└── docs/
    ├── data_dictionary.md
    ├── example_queries.sql
    ├── runbook.md
    └── adding_a_new_source.md
```

---

## Motherduck schema layout

```
trust-pipeline (database)
│
├── bronze/                          ← raw data, all columns VARCHAR or JSON
│   ├── sharpspring_leads            ← from dlt
│   ├── sharpspring_campaigns        ← from dlt
│   ├── sharpspring_owners           ← from dlt
│   ├── wildix_calls                 ← from dlt
│   ├── google_ads_*                 ← from Airbyte (multiple tables)
│   ├── meta_ads_*                   ← from Airbyte (multiple tables)
│   ├── bing_ads_*                   ← from Airbyte (multiple tables)
│   └── manual_*                     ← from csv_loader.py
│
├── silver/                          ← managed by dbt, one row per entity
│   ├── silver_sharpspring_leads
│   ├── silver_sharpspring_campaigns
│   ├── silver_wildix_calls
│   ├── silver_google_ads_spend
│   ├── silver_meta_spend
│   ├── silver_bing_spend
│   └── silver_agents
│
└── gold/                            ← managed by dbt, joined and calculated
    ├── gold_leads_enriched
    ├── gold_agent_performance_daily
    └── gold_campaign_attribution
```

**Bronze rule:** Store exactly what arrived. All columns VARCHAR or JSON. No casting. No transformation. No opinions.

**Silver rule:** One model per source. Properly typed. Cleaned. Standardised. No joins across sources.

**Gold rule:** Joined across sources. Metrics pre-calculated. Every column documented. This is what consumers query.

---

## Data sources — exact technical details

### SharpSpring

- **Base URL:** `https://api.sharpspring.com/pubapi/v1.2/`
- **Auth:** query string params `?accountID=X&secretKey=Y`
- **Protocol:** JSON-RPC — POST a body `{ method: "getLeads", params: { where: {}, limit: 500, offset: 0 } }`
- **Rate limit:** ~10 req/sec — implement exponential backoff
- **Pagination:** max 500 rows per call, use `offset` to paginate
- **Date format:** `YYYY-MM-DD HH:MM:SS` (no timezone — treat as UK local)
- **Methods used:** `getLeads`, `getCampaigns`, `getOpportunities`, `getOwners`
- **Incremental key:** `updateTimestamp` — use as dlt cursor
- **Quirks:**
  - Custom field labels require a separate `getFields` call to resolve
  - Empty values come back as `""` not `null` — normalise in silver
  - `leadStatus` values: `unqualified`, `qualified`, `contact`, `customer` — map to internal `new / contacted / appointment / closed`
  - `ownerID` is the owner ID field (not `assignedTo` as some docs suggest) — join to owners table to get a name
  - owners API method not yet confirmed — `getOwners` and `getUsers` both return "Invalid method signature"

### Wildix

- **Status:** Credentials obtained, not yet tested
- **Protocol:** REST API (exact base URL and auth method to be confirmed when credentials are tested in Phase 4)
- **Data needed:** CDR endpoint — call ID, datetime, caller, called, duration seconds, direction, agent/extension, disposition
- **Incremental key:** call datetime — only pull calls from the last sync window
- **Important:** Do not build the dlt pipeline until the credentials have been tested and at least one real API response has been inspected. Confirm exact field names from the real response before writing any model.

### Airbyte → Motherduck (Google Ads, Meta, Bing)

- **Setup needed:** Configure Motherduck as the Airbyte destination (one-time, no code)
- **Airbyte handles:** scheduling, incremental loads, retries, schema changes
- **Landing schema:** Airbyte lands into the `bronze` schema in Motherduck
- **Table naming:** Airbyte prefixes tables with the source name — confirm exact table names after first sync before writing silver models
- **Do not write silver models for ad platforms until a real Airbyte sync has run and you can inspect the actual table names and column names**

### Manual CSVs

- **Unknown until described by the developer**
- The csv_loader.py is built generically — each CSV type gets a config entry specifying its columns and target bronze table
- Do not build specific loaders until the developer describes each CSV

---

## Phone number normalisation

Must produce identical output in both Python and SQL.

### Python — `shared/phone.py`

```python
def normalise_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = ''.join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = '44' + digits[1:]
    return digits
```

### SQL — `dbt_project/macros/normalise_phone.sql`

```sql
{% macro normalise_phone(column) %}
    case
        when {{ column }} is null then null
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') = '' then null
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') like '00%'
            then substring(regexp_replace({{ column }}, '[^0-9]', '', 'g'), 3)
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') like '0%'
            then '44' || substring(regexp_replace({{ column }}, '[^0-9]', '', 'g'), 2)
        else regexp_replace({{ column }}, '[^0-9]', '', 'g')
    end
{% endmacro %}
```

Both tested against the same 20+ UK phone format fixtures.

---

## Agent name reconciliation

Each source refers to agents differently:

| Source | How agents appear |
|---|---|
| Wildix | Extension number (`201`) or alias (`L.Smith`) |
| SharpSpring | Full name (`Lily Smith`) or owner ID (`12345`) |
| Manual CSVs | First name only (`Lily`) |

`dbt_project/seeds/agent_name_mapping.csv` is the single source of truth. **Real values must be confirmed by the developer before Phase 6. Do not use placeholder values in production.**

```csv
canonical_name,wildix_extension,wildix_alias,sharpspring_owner_id,sharpspring_full_name,first_name
Lily,201,L.Smith,12345,Lily Smith,Lily
Sue,202,S.Brown,12346,Sue Brown,Sue
Alicja,203,A.Kowalski,12347,Alicja Kowalski,Alicja
Elisha,204,E.Patel,12348,Elisha Patel,Elisha
Other,,,,,Other
```

All silver models produce `canonical_name`. Gold models only ever use `canonical_name`.

---

## Key business calculations

| Metric | Formula | Target |
|---|---|---|
| Lead → Appointment conversion | `appointments / total_leads` | ≥33% |
| Time to first call | `first_outbound_call_datetime - lead.created_at` (minutes) | ≤5 min avg |
| Fresh lead | `created_at >= today_start()` | — |
| Backlog lead | `created_at < today_start() AND status NOT IN (closed, appointment)` | — |
| Attempts per lead | `count(outbound calls for this lead)` | ≥4 |
| Qualified conversation | `call.duration_seconds >= 120` | — |
| Qual conv → appointment | `appointments / qualified_conversations` | ≥33% |
| Fresh not called <10 min % | `count(fresh where mins_to_first > 10 or null) / count(fresh)` | ≤20% |
| Outcomes logged % | `count(leads where outcome is not null) / count(leads)` | 100% |
| Backlog worked % | `count(aged open leads called today) / count(aged open leads)` | ≥80% |

---

## Environment variables

`.env.example` is committed. Real `.env` is gitignored and never committed.

```bash
# Motherduck
MOTHERDUCK_TOKEN=
MOTHERDUCK_DATABASE=trust-pipeline

# SharpSpring
SHARPSPRING_ACCOUNT_ID=
SHARPSPRING_SECRET_KEY=

# Wildix (exact variable names confirmed once API is tested)
WILDIX_API_BASE_URL=
WILDIX_API_KEY=

# Airbyte Cloud
AIRBYTE_API_KEY=
AIRBYTE_WORKSPACE_ID=
```

For GitHub Actions: all variables go in GitHub Secrets (Settings → Secrets and variables → Actions).

---

## Claude Code skills (Altimate dbt skills)

This project uses **Altimate AI's open-source dbt skills** to improve Claude Code's accuracy and discipline when working on dbt models. Install them once — they activate automatically from natural language.

### Install (run inside Claude Code, once per machine)

```bash
/plugin marketplace add AltimateAI/data-engineering-skills
/plugin install dbt-skills@data-engineering-skills
```

Source: https://github.com/AltimateAI/data-engineering-skills

### Skills installed and when they activate

| Skill | Activates when you say... |
|---|---|
| `creating-dbt-models` | "create a model", "build a silver model", "add a gold table" |
| `debugging-dbt-errors` | "fix this error", "build is failing", "debug this model" |
| `testing-dbt-models` | "add tests", "write dbt tests", "test this model" |
| `documenting-dbt-models` | "document this model", "add descriptions", "update schema.yml" |
| `migrating-sql-to-dbt` | "convert this SQL to dbt", "turn this query into a model" |
| `refactoring-dbt-models` | "refactor", "restructure this model", "clean this up" |

### Skills NOT installed — wrong stack

Do NOT install the Snowflake skills (`snowflake-skills@data-engineering-skills`). This project uses DuckDB/Motherduck, not Snowflake. The Snowflake query optimisation and cost analysis skills will not work and will confuse Claude Code.

Do NOT install the Altimate MCP server — it is Snowflake-specific and not compatible with this project.

### What these skills actually change

Without skills, Claude Code knows dbt syntax but:
- Declares "done" after writing SQL without running `dbt build`
- Guesses naming conventions instead of reading existing models first
- Patches failing builds with tiny tweaks instead of stepping back

With skills, Claude Code follows a disciplined workflow for every model:

```
1. Discover conventions  — read 2-3 existing models before writing anything
2. Find upstream models  — check what source tables actually exist
3. Write the model       — matching the patterns found in step 1
4. Run dbt build         — compile alone is NOT enough
5. Verify output         — dbt show --select {model} --limit 5
```

### The 3-failure rule (built into every skill)

If `dbt build` fails three or more times in a row, **stop patching and reassess the entire approach.** Do not keep tweaking the same line. Step back, re-read the upstream model, re-read the source schema, and start fresh with a clear understanding of what the data actually looks like.

This rule is important because DuckDB/Motherduck has some syntax differences from standard SQL (e.g. `regexp_replace` patterns, window function support) that can cause repeated failures if the root cause is not identified properly.

### DuckDB-specific notes for the skills

The Altimate skills were benchmarked on Snowflake. DuckDB syntax differences to watch for:

- Use `regexp_replace(col, '[^0-9]', '', 'g')` not `REGEXP_REPLACE(col, '[^0-9]', '')` — DuckDB requires the global flag
- `current_date` works; `CURRENT_DATE()` (with brackets) does not
- Window functions work normally — no Snowflake-specific quirks
- `QUALIFY` is supported in DuckDB — useful for deduplication
- `PIVOT` is supported natively — no need for manual CASE WHEN pivots
- String concat: use `||` not `CONCAT()` for consistency

When a skill suggests a Snowflake-specific function or syntax, substitute the DuckDB equivalent. If unsure, check the DuckDB documentation before writing.

---

## Optional Agensi skills

These three skills from [agensi.io](https://www.agensi.io/skills/data-engineering) are worth having but not required. The pipeline works fine without them — they just make specific phases faster and produce better output. Think of them as a good linter: useful, not essential.

**Install method (different from Altimate):** Agensi skills are SKILL.md files, not plugins. Purchase → download → place in `.claude/skills/` in the project root. Claude Code picks them up automatically.

```
heating-warehouse/
└── .claude/
    └── skills/
        ├── csv-analyzer.md      ← place downloaded file here
        ├── data-faker.md
        └── json-to-types.md
```

Verify the exact install path at: https://www.agensi.io/learn/how-to-install-skills-claude-code

### `csv-analyzer` — $12 — Kevin Cline

Automates data profiling with type detection, statistical analysis, and quality flags saved to a Markdown report.

**When it helps in this project:**
- Before Phase 8 (Wildix CDR ingestion) — run it on the real CDR export to understand column types, null rates, and value distributions before writing a single line of loader code
- Before Phase 10 (manual CSV loader) — profile each unknown CSV the developer hands over before deciding how to load it
- Any time bronze data produces unexpected results — profile the source to find out why

Without it: you inspect CSVs manually and guess at types. With it: you get a full Markdown report in seconds.

### `data-faker` — $12 — Kevin Cline

Generates realistic JSON or CSV test data from plain-English schema descriptions, up to 1,000 rows.

**When it helps in this project:**
- Phase 5 (SharpSpring schemas) — generate 50 fake leads matching the real schema for pytest fixtures, so `tests/fixtures/sharpspring/` contains no real customer data
- Phase 8 (Wildix CDR) — generate a fake CDR CSV that CI can run against without needing real call records
- Any phase where a test needs realistic data that is not real PII

Without it: you either commit real data (bad for privacy) or hand-craft fixture files (tedious and limited). With it: describe the schema in plain English and get a realistic dataset.

### `json-to-types` — $12 — Kevin Cline

Transforms JSON files or raw strings into production-ready Python dataclasses.

**When it helps in this project:**
- Phase 4 (Wildix credential test) — once you have a real Wildix API response, paste it in and get a Python dataclass back immediately. Use that as the basis for `schemas.py`
- Phase 5 (SharpSpring schemas) — same: paste the real `getLeads` response, get typed dataclasses, convert to pandera schemas

Without it: you write `schemas.py` by hand from reading the raw JSON. With it: you generate the types in seconds and spend your time on the business logic instead.

---

## Coding conventions

### Python
- Formatter: Black, line length 100
- Linter: Ruff with default rules
- Type hints on all functions
- Google-style docstrings on public functions
- pytest with fixtures for sample data

### SQL (dbt)
- Formatter: sqlfluff with dbt dialect
- Two-space indents, lowercase keywords
- One CTE per logical step, named descriptively
- Always `SELECT` columns explicitly — never `SELECT *`
- Every model documented in `_models.yml`

### Git
- Conventional commits: `feat:` `fix:` `refactor:` `docs:` `test:` `chore:`
- One concern per commit
- Never commit `.env`, `.duckdb`, `node_modules/`, `.venv/`

---

## Definition of done — for every phase

A phase is only done when all five are true:

1. ✅ Code written and committed
2. ✅ Tests written and passing
3. ✅ Documented (docstrings and dbt model descriptions)
4. ✅ Verification step from PROMPT.md ran and produced expected output
5. ✅ Commit message describes what changed and why

Do not move to the next phase until all five are true.

---

## Hallucination prevention

Before writing any code, Claude Code must:

1. Confirm exact column names from real source data — never invent them
2. Confirm exact API method names from actual documentation
3. Confirm Airbyte table names after a real sync — never assume naming
4. Confirm Wildix API response shape from a real test call before building models
5. Run the code and verify the output before declaring done
6. When unsure — stop and ask the developer, never guess

---

## Out of scope for v1

- WhatsApp ad platform (add once access arranged)
- Wildix → Airbyte connector (possible future replacement for the dlt client)
- Dashboard UI
- ML or predictive models
- Real-time or streaming data
- Claude Code cloud routines (not used in this project)
- Playwright or browser automation (not needed — Wildix has an API)
- Separate GitHub data repo (not needed — all data goes direct to Motherduck)