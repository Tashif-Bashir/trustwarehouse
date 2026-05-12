# PROMPT.md

Step-by-step build instructions for Claude Code.
Read `CLAUDE.md` and `ARCHITECTURE.md` first every session.

---

## Rules — read before starting any phase

1. Work through phases **in order**. Never skip ahead.
2. **Stop at the end of every phase.** Report what was done. Wait for the developer to confirm before moving on.
3. If anything is ambiguous — **ask**. Never guess.
4. Never invent column names, API field names, or table names. If you have not seen the real data, say so and ask for it.
5. Run the verification step for every phase. Do not claim done without running it.
6. Commit at the end of every phase using Conventional Commits.
7. Claude Code cloud routines, Playwright, and browser automation are **not used anywhere in this project**. Do not suggest them.
8. There is no separate GitHub data repo. All data goes directly to Motherduck. Do not create file-staging patterns.

---

# PHASE 0 — Foundation

**Goal:** Working repo, project structure, dependencies, CI.

## Steps

### Part A — Install Claude Code dbt skills (do this first, before any code)

1. Inside Claude Code, run:
   ```bash
   /plugin marketplace add AltimateAI/data-engineering-skills
   /plugin install dbt-skills@data-engineering-skills
   ```
   Confirm the install succeeds. These skills activate automatically throughout all dbt phases (Phases 11–19) and significantly improve model creation, debugging, and testing accuracy.

   **Do NOT install `snowflake-skills` — wrong database stack for this project.**

### Part B — Project initialisation

2. Initialise git repo, create `main` branch.

3. Initialise Python project:
   ```bash
   uv init --package heating-warehouse
   ```

3. Add dependencies:
   ```bash
   uv add dlt[duckdb] duckdb python-dotenv pandera pydantic
   uv add dbt-core dbt-duckdb
   uv add --dev pytest pytest-cov ruff black
   ```

4. Create `.python-version` containing `3.11`

5. Create `.gitignore`:
   ```
   .venv/
   .env
   *.duckdb
   *.duckdb.wal
   __pycache__/
   .pytest_cache/
   .ruff_cache/
   dbt_project/target/
   dbt_project/dbt_packages/
   dbt_project/logs/
   .DS_Store
   ```

6. Create `.env.example` from the template in `CLAUDE.md`. Do not create a real `.env` yet.

7. Create the full directory structure from `CLAUDE.md` using `.gitkeep` in empty folders.

8. Create a brief `README.md` — what this is, how to set it up locally, project structure.

9. Create `.github/workflows/ci.yml`:
   - Triggers on pull requests
   - Sets up Python 3.11 + uv
   - Runs `ruff check .`
   - Runs `pytest`

## Verification

```bash
uv sync
uv run pytest      # passes with zero tests
uv run ruff check .
git status         # clean
```

Push to GitHub. CI must be green before moving on.

## Definition of Done

- [ ] Repo on GitHub, CI green
- [ ] `.env.example` committed, no real `.env` in repo
- [ ] Committed: `chore: initialise project structure`

**Stop. Report. Wait for confirmation.**

---

# PHASE 1 — Motherduck connection

**Goal:** Connect to the warehouse. Confirm it is reachable.

**Inputs:** Developer has Motherduck account, token, and database created in EU region.

## Steps

1. Ask developer to confirm:
   - Motherduck account created at motherduck.com
   - Service token copied from Settings → Tokens
   - Database `heating_warehouse` created
   - EU region selected during setup

2. Create `shared/motherduck.py`:
   - `get_connection() -> duckdb.DuckDBPyConnection`
   - Reads `MOTHERDUCK_TOKEN` and `MOTHERDUCK_DATABASE` from environment
   - Raises a clear descriptive error if either is missing
   - Returns connection to `md:{database}?motherduck_token={token}`

3. Create `tests/test_motherduck.py`:
   - Skip if `MOTHERDUCK_TOKEN` not set
   - Otherwise connect, run `SELECT 1`, assert result

4. Help developer create local `.env` from `.env.example` and add Motherduck credentials. Remind them `.env` is gitignored.

## Verification

```bash
uv run python -c "
from shared.motherduck import get_connection
result = get_connection().sql('SELECT 1 as test').fetchone()
assert result == (1,)
print('Motherduck connection confirmed')
"
```

## Definition of Done

- [ ] `shared/motherduck.py` implemented and tested
- [ ] Developer confirms connection works
- [ ] `.env` populated locally, not committed
- [ ] Committed: `feat: add motherduck connection helper`

**Stop. Report.**

---

# PHASE 2 — Phone normalisation utility

**Goal:** Phone normalisation with 20+ tests. Used everywhere in the pipeline.

**Inputs:** Phase 0 complete.

## Steps

1. Create `shared/phone.py` with `normalise_phone()` exactly as in `CLAUDE.md`.

2. Create `tests/test_phone.py` — minimum 20 cases:
   - `"07700 900123"` → `"447700900123"`
   - `"+44 7700 900123"` → `"447700900123"`
   - `"+447700900123"` → `"447700900123"`
   - `"00447700900123"` → `"447700900123"`
   - `"(0) 7700 900123"` → `"447700900123"`
   - `"020 7946 0958"` → `"442079460958"`
   - `"7700900123"` → `"7700900123"` (no leading zero, no prefix added)
   - `""` → `None`
   - `None` → `None`
   - `"not a number"` → `None`
   - 10+ more variations with dashes, mixed punctuation, spaces

3. Create `dbt_project/macros/normalise_phone.sql` from `CLAUDE.md`.

## Verification

```bash
uv run pytest tests/test_phone.py -v
# All 20+ tests pass
```

## Definition of Done

- [ ] 20+ tests, all passing
- [ ] SQL macro file created
- [ ] Committed: `feat: add phone normalisation utility`

**Stop. Report.**

---

# PHASE 3 — Airbyte destination configuration

**Goal:** Airbyte Cloud syncs all three ad platforms directly into Motherduck bronze. This is the fastest value delivery in the entire project — no code required.

**Inputs:** Developer has Airbyte Cloud account with Google Ads, Meta, and Bing connected as sources. Motherduck token and database available.

## Steps

This phase is **configuration in the Airbyte UI**, not code. Guide the developer through it step by step.

### Part A — Configure Motherduck as destination in Airbyte

1. In Airbyte Cloud go to: **Destinations → New Destination**
2. Search for **DuckDB** or **MotherDuck** (Airbyte has a native connector)
3. Configure with:
   - Connection string: `md:heating_warehouse?motherduck_token=YOUR_TOKEN`
   - Schema: `bronze`
4. Test the connection. Save.

### Part B — Create connections for each ad platform

For each of the three sources (Google Ads, Meta, Bing):

1. Go to **Connections → New Connection**
2. Select the source (already connected)
3. Select the Motherduck destination (just created)
4. Set sync frequency:
   - Google Ads: daily
   - Meta: daily
   - Bing: daily
5. Choose incremental sync mode where available
6. Enable the streams/tables you need:
   - Google Ads: campaigns, ad groups, ad group performance, campaign performance
   - Meta: campaigns, ads, ads insights
   - Bing: campaigns, ad performance report
7. Save and trigger a manual sync for each

### Part C — Inspect what Airbyte created

After each sync completes, connect to Motherduck and run:

```sql
SHOW TABLES IN bronze;
```

Document every table name Airbyte created in `docs/data_dictionary.md`. These exact names are what the silver dbt models will use as sources. **Do not guess them — read them from the actual database.**

Also run for each table:
```sql
DESCRIBE bronze.{table_name};
```

Document the exact column names and types.

## Verification

```sql
-- After all three syncs
SHOW TABLES IN bronze;
-- Should show tables for google_ads, meta, and bing

SELECT count(*) FROM bronze.{first_google_ads_table};
SELECT count(*) FROM bronze.{first_meta_table};
SELECT count(*) FROM bronze.{first_bing_table};
-- All should return rows > 0
```

## Definition of Done

- [ ] Motherduck configured as Airbyte destination
- [ ] All three ad platform connections created
- [ ] Manual sync triggered and completed for all three
- [ ] Real data visible in Motherduck bronze schema
- [ ] All Airbyte-created table names and column names documented in data dictionary
- [ ] Committed: `docs: document airbyte bronze table schemas`

**Stop. Report. This is a big milestone — real data in the warehouse with zero code written.**

---

# PHASE 4 — Wildix API credential test

**Goal:** Confirm Wildix credentials work and understand the real API response shape before writing any code.

**Inputs:** Developer has Wildix API credentials. Phase 1 complete.

## Steps

1. Ask the developer to provide:
   - The Wildix API base URL
   - The authentication method (API key in header, query param, basic auth — whichever it is)
   - The endpoint for CDR / call history data

   **Do not proceed to Step 2 until these are provided. Do not guess the URL or auth method.**

2. Write a minimal test script `scripts/test_wildix_credentials.py`:
   - Makes a single API call to the CDR endpoint
   - Requests the last 24 hours of data
   - Prints the raw response
   - Does not write to Motherduck — just prints and exits

3. Run it with the developer watching:
   ```bash
   uv run python scripts/test_wildix_credentials.py
   ```

4. If it works:
   - Save a sample response (anonymised) to `tests/fixtures/wildix/sample_response.json`
   - Document every field name and type in `docs/data_dictionary.md`
   - Note the incremental key (likely a timestamp field)
   - **If `json-to-types` skill is available:** paste the raw response into the skill and generate Python dataclasses immediately — use these as the foundation for `ingestion/wildix/schemas.py` in Phase 8

5. If it does not work:
   - Document the error clearly
   - Do not proceed to Phase 5 until credentials are working
   - Help the developer troubleshoot (wrong base URL, missing header, wrong auth format, etc.)

## Verification

```
Script runs successfully
Raw Wildix API response is printed to the terminal
At least one call record is visible in the response
Sample response saved to tests/fixtures/wildix/
```

## Definition of Done

- [ ] Wildix credentials confirmed working
- [ ] Real API response shape documented
- [ ] Exact field names saved as a fixture
- [ ] Committed: `docs: document wildix api response schema`

**Stop. Report. Do not build the Wildix pipeline until this phase is fully complete.**

---

# PHASE 5 — SharpSpring API client

**Goal:** Working Python client that calls SharpSpring and returns real data.

**Inputs:** SharpSpring accountID and secretKey in local `.env`. Phase 1 complete.

## Steps

1. Create `ingestion/sharpspring/client.py`:
   - Class `SharpSpringClient`
   - Reads credentials from environment if not passed directly
   - `_call(method, params)` — JSON-RPC POST with rate limiting (8 req/sec max) and exponential backoff (3 retries)
   - `get_leads(updated_since=None, limit=500, offset=0)`
   - `get_campaigns()`
   - `get_owners()`

2. Create `ingestion/sharpspring/schemas.py`:
   - Pandera schemas for the shape of each API response
   - Loose — allow unknown columns, only validate key fields
   - **If `json-to-types` skill is available:** paste the real `getLeads` response JSON into the skill first — it generates Python dataclasses automatically. Use those as the basis for the pandera schemas rather than writing from scratch.

3. Create `tests/test_sharpspring_client.py`:
   - Mock HTTP layer
   - Test: correct JSON-RPC body formed
   - Test: 429 triggers backoff and retry
   - Test: pagination works beyond 500 results
   - Test: auth failure raises a clear error
   - **If `data-faker` skill is available:** use it to generate 50 realistic fake lead records matching the SharpSpring schema for use in mock responses — no real customer data in fixtures

4. Create `scripts/smoke_test_sharpspring.py`:
   - Calls `get_campaigns()` (small, fast)
   - Prints count and first 3 records
   - Validates against pandera schema

5. Run the smoke test with the developer watching.

## Verification

```bash
uv run pytest tests/test_sharpspring_client.py -v
# All unit tests pass (mocked HTTP)

uv run python scripts/smoke_test_sharpspring.py
# Prints real campaign data from the actual account
```

## Definition of Done

- [ ] Client implemented with rate limiting and retries
- [ ] Unit tests passing
- [ ] Live smoke test confirmed with real data
- [ ] Sample responses saved to `tests/fixtures/sharpspring/`
- [ ] Committed: `feat: add sharpspring api client`

**Stop. Report.**

---

# PHASE 6 — SharpSpring bronze ingestion

**Goal:** dlt pipeline loads SharpSpring data into Motherduck bronze.

**Inputs:** Phase 5 complete.

## Steps

1. Check current dlt documentation for Motherduck destination syntax before writing. Dlt evolves — do not rely on memory.

2. Create `ingestion/sharpspring/pipeline.py`:
   - `dlt.source` with three resources: `leads`, `campaigns`, `owners`
   - `leads` uses `updateTimestamp` as incremental cursor
   - Destination: Motherduck
   - Dataset: `bronze`

3. Create `ingestion/sharpspring/__main__.py` so it runs as:
   ```bash
   uv run python -m ingestion.sharpspring
   ```

4. Run it. Inspect:
   ```sql
   SELECT count(*) FROM bronze.sharpspring_leads;
   SELECT * FROM bronze.sharpspring_leads LIMIT 3;
   ```

5. Run it a second time. Confirm incremental load — only new or updated leads loaded, not all 500+ again.

6. Document the dlt-created columns (including `_dlt_load_id`, `_dlt_id`) in `docs/data_dictionary.md`.

## Verification

- `bronze.sharpspring_leads` exists with rows
- Second run loads fewer rows than first (incremental confirmed)
- Row counts shared with developer for sanity check

## Definition of Done

- [ ] Three bronze tables created: leads, campaigns, owners
- [ ] Incremental loading verified
- [ ] Data dictionary updated
- [ ] Committed: `feat: add sharpspring bronze ingestion`

**Stop. Report.**

---

# PHASE 7 — SharpSpring sync scheduled

**Goal:** SharpSpring syncs hourly in GitHub Actions without manual intervention.

**Inputs:** Phase 6 complete. Developer has access to GitHub Secrets.

## Steps

1. Walk developer through adding GitHub Secrets:
   - `MOTHERDUCK_TOKEN`
   - `MOTHERDUCK_DATABASE`
   - `SHARPSPRING_ACCOUNT_ID`
   - `SHARPSPRING_SECRET_KEY`

2. Create `.github/workflows/sync-sharpspring.yml`:
   ```yaml
   name: Sync SharpSpring

   on:
     schedule:
       - cron: '0 * * * *'
     workflow_dispatch:

   jobs:
     sync:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.11'
         - run: pip install uv && uv sync
         - name: Run sync
           env:
             MOTHERDUCK_TOKEN: ${{ secrets.MOTHERDUCK_TOKEN }}
             MOTHERDUCK_DATABASE: ${{ secrets.MOTHERDUCK_DATABASE }}
             SHARPSPRING_ACCOUNT_ID: ${{ secrets.SHARPSPRING_ACCOUNT_ID }}
             SHARPSPRING_SECRET_KEY: ${{ secrets.SHARPSPRING_SECRET_KEY }}
           run: uv run python -m ingestion.sharpspring
   ```

3. Commit, push, trigger manually from Actions tab. Confirm success.

## Verification

- Green tick in GitHub Actions tab
- New rows appearing in `bronze.sharpspring_leads`
- No secrets visible in logs

## Definition of Done

- [ ] Workflow running on schedule
- [ ] At least one manual trigger confirmed green
- [ ] Committed: `ci: add hourly sharpspring sync`

**Stop. Report.**

---

# PHASE 8 — Wildix bronze ingestion

**Goal:** dlt pipeline loads Wildix CDR data into Motherduck bronze.

**Inputs:** Phase 4 complete (credentials confirmed, response shape documented). Phase 1 complete.

**Optional skills that help here:**
- `data-faker` — generate a realistic fake CDR dataset for CI to run against, so tests never depend on real call records
- `json-to-types` — if you have a real JSON response from the Wildix API (not CSV), paste it in to generate typed dataclasses for `schemas.py` instantly

## Steps

1. Refer to the response shape documented in Phase 4. Use the **exact field names** from `tests/fixtures/wildix/sample_response.json`. Do not invent field names.

2. Create `ingestion/wildix/client.py`:
   - Class `WildixClient`
   - Uses the exact auth method confirmed in Phase 4
   - Method `get_calls(since: datetime) -> list[dict]`
   - Rate limiting and exponential backoff

3. Create `ingestion/wildix/pipeline.py`:
   - dlt pipeline using `call_datetime` (or whatever the real timestamp field is called) as incremental cursor
   - Destination: Motherduck bronze

4. Create `ingestion/wildix/__main__.py`

5. Run it. Inspect:
   ```sql
   SELECT count(*) FROM bronze.wildix_calls;
   SELECT * FROM bronze.wildix_calls LIMIT 3;
   ```

## Verification

- `bronze.wildix_calls` exists with rows
- Second run is incremental
- Row counts confirmed sensible by developer

## Definition of Done

- [ ] `bronze.wildix_calls` populated with real data
- [ ] Incremental loading working
- [ ] Committed: `feat: add wildix bronze ingestion`

**Stop. Report.**

---

# PHASE 9 — Wildix sync scheduled

**Goal:** Wildix syncs hourly automatically.

## Steps

Mirror Phase 7 for Wildix. Add `WILDIX_API_BASE_URL` and `WILDIX_API_KEY` (or whatever the real secret names are) to GitHub Secrets. Create `.github/workflows/sync-wildix.yml`.

## Definition of Done

- [ ] Hourly Wildix sync running in GitHub Actions
- [ ] Committed: `ci: add hourly wildix sync`

**Stop. Report.**

---

# PHASE 10 — Manual CSV loader

**Goal:** Generic loader for manual CSV uploads into bronze.

**Inputs:** Developer describes each CSV they have.

**Optional skill that helps here:** `csv-analyzer` — before writing any loader, run this on each real CSV the developer provides. It profiles the file automatically: column types, null rates, value distributions, quality flags. The output Markdown report tells you exactly what you're dealing with before you write a line of code. Saves the manual inspection step entirely.

## Steps

1. **Ask the developer to describe each manual CSV:**
   - What is in it?
   - How often does it get updated?
   - What are the column headers? (ask for a real sample if available)
   - **If `csv-analyzer` is available and a sample file exists:** run the profiler on it now rather than relying on verbal description alone

   Do not build specific loaders until the CSVs are understood.

2. Create `ingestion/manual/csv_loader.py`:
   - Takes a CSV path and a target bronze table name
   - All columns stored as strings (bronze rule)
   - Adds `_loaded_at` and `_source_file` metadata columns
   - Deduplicates using a configurable primary key column
   - Appends to the target Motherduck bronze table

3. Create a simple CLI:
   ```bash
   uv run python -m ingestion.manual \
     --file path/to/file.csv \
     --table manual_secured_leads \
     --key lead_id
   ```

4. Test with each real CSV the developer provides.

## Definition of Done

- [ ] Generic loader working for each CSV the developer has described
- [ ] Each CSV has its own bronze table
- [ ] Committed: `feat: add manual csv loader`

**Stop. Report.**

---

# PHASE 11 — dbt project and silver: SharpSpring leads

**Goal:** dbt initialised. `silver.silver_sharpspring_leads` exists and is clean.

**Inputs:** Phase 6 complete. Real bronze data exists.

**Active skills:** The `creating-dbt-models` and `testing-dbt-models` skills should be active from Phase 0. If Claude Code is not following the discover → write → build → verify workflow, re-run the install command from Phase 0 before continuing.

## Steps

1. Initialise dbt project in `dbt_project/`.

2. Create `profiles.yml.example` showing Motherduck profile. Real `profiles.yml` is gitignored.

3. Declare bronze tables as dbt sources in `_silver__sources.yml`.

4. Create `silver_sharpspring_leads.sql`:
   - Casts every column to correct type
   - Applies `{{ normalise_phone() }}` to phone columns
   - Maps `leadStatus` to internal `new/contacted/appointment/closed`
   - Deduplicates on `lead_id` keeping most recent `_dlt_load_id`
   - Derives `canonical_agent_name` from `owner_id` (placeholder until Phase 12)

5. Add dbt tests: `unique` and `not_null` on `lead_id`, `unique` on `phone_normalised` where not null.

6. Run `dbt build --select silver_sharpspring_leads`.

   **3-failure rule:** If the build fails three times in a row, stop patching. Re-read the upstream bronze table schema, re-read the DuckDB syntax notes in `CLAUDE.md`, and reassess from scratch.

7. Run `dbt show --select silver_sharpspring_leads --limit 5` to verify actual output. Compile alone is not enough.

## Verification

```sql
SELECT count(*) FROM silver.silver_sharpspring_leads;
SELECT phone_normalised FROM silver.silver_sharpspring_leads LIMIT 10;
-- All digits, starting with 44
```

All dbt tests pass.

## Definition of Done

- [ ] dbt project initialised
- [ ] `silver_sharpspring_leads` built and typed
- [ ] Tests passing
- [ ] Committed: `feat: add silver_sharpspring_leads`

**Stop. Report.**

---

# PHASE 12 — Agent reconciliation seed

**Goal:** All sources produce a canonical agent name.

**Inputs:** Developer must provide real agent data before this phase starts. Do not use placeholder values.

## Steps

1. **Ask developer for:**
   - Each agent's exact full name as it appears in SharpSpring
   - Each agent's Wildix extension number
   - Each agent's Wildix alias if different
   - SharpSpring owner ID for each agent (Settings → Users)

2. Create `dbt_project/seeds/agent_name_mapping.csv` with real values.

3. Run `dbt seed`.

4. Create `silver_agents.sql` from the seed.

5. Create `normalise_agent_name.sql` macro — takes any raw identifier, returns `canonical_name`, falls back to `'Other'`.

6. Update `silver_sharpspring_leads.sql` to use the macro properly.

## Verification

```sql
SELECT canonical_agent_name, count(*)
FROM silver.silver_sharpspring_leads
GROUP BY canonical_agent_name;
-- Should show exactly: Lily, Sue, Alicja, Elisha, Other — no NULLs
```

## Definition of Done

- [ ] Seed populated with real values confirmed by developer
- [ ] `silver_agents` model built
- [ ] Macro working
- [ ] No NULL canonical_agent_name values
- [ ] Committed: `feat: add agent name reconciliation`

**Stop. Report.**

---

# PHASE 13 — Silver: Wildix calls

**Goal:** `silver.silver_wildix_calls` — clean, typed, with normalised phones and canonical agent names.

**Inputs:** Phase 8 and 12 complete.

**Active skills:** `creating-dbt-models` activates automatically. After build, always run `dbt show --select silver_wildix_calls --limit 5` to verify real output — do not rely on a passing build alone.

## Steps

Use exact column names from Phase 4 fixture — never invent them.

Create `silver_wildix_calls.sql`:
- Proper types for all columns
- `{{ normalise_phone() }}` on caller and called number
- `{{ normalise_agent_name() }}` using Wildix extension
- `is_outbound` boolean
- `is_qualified_conversation` boolean (`duration_seconds >= 120`)
- Drop rows where call_id is null
- Deduplicate on `call_id`

Add dbt tests: `unique` on `call_id`, `not_null` on key fields.

## Verification

```sql
SELECT canonical_agent_name,
       count(*) as calls,
       avg(duration_seconds) as avg_duration,
       count(*) filter (where is_qualified_conversation) as qual_convs
FROM silver.silver_wildix_calls
GROUP BY canonical_agent_name;
```

Numbers should look realistic to the developer.

## Definition of Done

- [ ] `silver_wildix_calls` built
- [ ] Tests pass
- [ ] Per-agent numbers confirmed sensible
- [ ] Committed: `feat: add silver_wildix_calls`

**Stop. Report.**

---

# PHASE 14 — Silver: ad platform spend

**Goal:** One silver model per ad platform, joinable to SharpSpring campaigns on campaign name.

**Inputs:** Phase 3 complete (Airbyte synced real data). Exact Airbyte table names and column names documented in data dictionary.

**Active skills:** `creating-dbt-models` activates automatically. Read the Airbyte bronze tables before writing any SQL — the convention discovery step in the skill enforces this. Never assume Airbyte column names.

## Steps

**Before writing any SQL — read the actual Airbyte bronze tables:**

```sql
DESCRIBE bronze.{actual_google_ads_table_name};
DESCRIBE bronze.{actual_meta_table_name};
DESCRIBE bronze.{actual_bing_table_name};
```

Use the real column names you see. Do not assume column names.

Create three silver models:
- `silver_google_ads_spend.sql` — one row per campaign per day, spend in GBP, clicks, impressions
- `silver_meta_spend.sql` — same grain
- `silver_bing_spend.sql` — same grain

Each model:
- Deduplicates appropriately
- Casts to correct types
- Normalises campaign name to lowercase trimmed string for joining
- Handles currency conversion if Airbyte returns in a different currency

Add dbt tests on each.

## Verification

```sql
SELECT campaign_name_normalised, sum(spend_gbp), sum(clicks)
FROM silver.silver_google_ads_spend
WHERE date >= current_date - 7
GROUP BY campaign_name_normalised;
```

## Definition of Done

- [ ] Three silver ad spend models built using real Airbyte column names
- [ ] Tests pass
- [ ] Spend numbers confirmed correct by developer
- [ ] Committed: `feat: add silver ad spend models`

**Stop. Report.**

---

# PHASE 15 — Gold: leads enriched

**Goal:** `gold.gold_leads_enriched` — every lead with all calls and KPIs attached.

**Inputs:** Silver layer for SharpSpring leads and Wildix calls complete.

**Active skills:** `creating-dbt-models` and `testing-dbt-models` activate automatically. This is the most complex model in the project — follow the full discover → write → build → verify → test cycle without shortcuts. If the phone join produces unexpected row counts (more rows than leads = duplicate join), use the `debugging-dbt-errors` skill to diagnose.

## Steps

Create `gold_leads_enriched.sql`:
- Starts from `silver_sharpspring_leads`
- LEFT JOINs `silver_wildix_calls` on normalised phone
- Aggregates per lead: `attempt_count`, `first_call_at`, `last_call_at`, `longest_call_seconds`, `has_qualified_conversation`, `minutes_to_first_call`
- Derives: `is_fresh_lead`, `meets_attempt_target`, `called_within_10_min`
- Pre-computes status flags for every KPI target

Document every column in `_gold__models.yml`.

dbt tests: `unique` on `lead_id`, all counts ≥ 0.

## Verification

```sql
SELECT
    count(*) as total_leads,
    count(*) filter (where appointment_booked) as appointments,
    round(100.0 * count(*) filter (where appointment_booked) / count(*), 1) as conversion_pct
FROM gold.gold_leads_enriched
WHERE created_at >= current_date - 30;
```

Developer sees the conversion rate for the first time from real joined data.

## Definition of Done

- [ ] `gold_leads_enriched` built
- [ ] Tests pass
- [ ] Developer runs conversion query and confirms number looks right
- [ ] Committed: `feat: add gold_leads_enriched`

**Stop. Report.**

---

# PHASE 16 — Gold: agent performance daily

**Goal:** One row per agent per day with all KPIs and status flags.

## Steps

Create `gold_agent_performance_daily.sql` with grain `canonical_agent_name` + `date`.

Include every KPI from the calculations table in `CLAUDE.md`. Pre-compute all status flags as `'green'` or `'red'`.

dbt tests: `unique` on (`canonical_agent_name`, `date`), all percentages between 0 and 100.

## Verification

```sql
SELECT * FROM gold.gold_agent_performance_daily
WHERE date = current_date - 1
ORDER BY conversion_rate_pct DESC;
```

Developer confirms numbers match their expectations per agent.

## Definition of Done

- [ ] One row per agent per day
- [ ] All KPIs correct
- [ ] Status flags working
- [ ] Committed: `feat: add gold_agent_performance_daily`

**Stop. Report.**

---

# PHASE 17 — Gold: campaign attribution

**Goal:** One row per campaign per day with spend and conversion joined.

**Inputs:** Phases 14 and 15 complete.

## Steps

Create `gold_campaign_attribution.sql`:
- Grain: `campaign_name` + `date`
- Joins spend from all three silver ad models (UNION then join to leads)
- Joins lead counts from `silver_sharpspring_leads` by source
- Joins appointment counts from `gold_leads_enriched`
- Calculates `cost_per_lead`, `cost_per_appointment`, `lead_to_appointment_rate`
- Organic channels: spend is 0, cost metrics are null (no division by zero)

## Verification

```sql
SELECT
    campaign_name,
    sum(spend_gbp) as total_spend,
    sum(leads) as leads,
    sum(appointments) as appointments,
    round(sum(spend_gbp) / nullif(sum(appointments), 0), 2) as cost_per_appt
FROM gold.gold_campaign_attribution
WHERE date >= current_date - 30
GROUP BY campaign_name
ORDER BY total_spend DESC;
```

Developer can now answer "which channel gives the cheapest appointments?"

## Definition of Done

- [ ] `gold_campaign_attribution` built
- [ ] No division by zero errors
- [ ] Developer confirms numbers make sense
- [ ] Committed: `feat: add gold_campaign_attribution`

**Stop. Report.**

---

# PHASE 18 — Orchestration and monitoring

**Goal:** Full pipeline runs automatically end-to-end. You get alerted when anything breaks.

## Steps

1. Create `.github/workflows/pipeline-build.yml`:
   - Triggers after any sync workflow completes (`workflow_run`)
   - Runs `dbt build` (all models)
   - On failure: automatically opens a GitHub Issue with the error log

2. Add `dbt source freshness` — fails build if any bronze source is stale beyond expected interval.

3. Write `docs/runbook.md`:
   - Pipeline failed — what to check first
   - How to backfill a missed day
   - How to manually trigger any sync
   - What to do if Airbyte sync fails

## Verification

- Force a deliberate failure (break a dbt model with bad SQL)
- Confirm GitHub Issue opens automatically
- Fix it, confirm next run is green

## Definition of Done

- [ ] Full pipeline runs automatically
- [ ] Failures create GitHub Issues
- [ ] Freshness tests working
- [ ] Runbook written
- [ ] Committed: `feat: add orchestration and monitoring`

**Stop. Report.**

---

# PHASE 19 — Final documentation

**Goal:** Anyone can understand and run this project without asking the developer.

**Active skills:** `documenting-dbt-models` activates automatically when you say "document the models" or "add descriptions". Use it to generate the `schema.yml` descriptions for all silver and gold models systematically.

## Steps

1. Complete `README.md` with architecture diagram, setup steps, how to trigger syncs manually, how to add a new source.

2. Complete `docs/data_dictionary.md` — every column in every gold table with description, type, and example value.

3. Create `docs/example_queries.sql`:
   - Lead to appointment conversion this month
   - Cost per appointment by campaign last 30 days
   - Agent leaderboard by conversion rate
   - Average time to first call by lead source
   - Fresh leads not called within 10 minutes today

4. Verify every example query runs against the gold layer without modification.

## Definition of Done

- [ ] README readable to a new joiner
- [ ] Data dictionary complete for all gold tables
- [ ] All example queries run successfully
- [ ] Committed: `docs: complete v1 documentation`

---

**v1 warehouse complete.**

The pipeline runs automatically. All data is clean. Gold tables answer business questions. The dashboard for Fiona is now a separate project reading from the gold layer.

---

# Out of scope for v1

- WhatsApp ad platform (add once access arranged — follows Airbyte pattern)
- Wildix via Airbyte (possible future replacement for the dlt client)
- Dashboard UI
- ML or predictive models
- Real-time data
- Claude Code cloud routines (not used)
- Playwright or browser automation (not needed)
- Separate GitHub data repo (not needed)