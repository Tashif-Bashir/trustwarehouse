# Business Analysis Plan

**Status: AWAITING PLAN — paste it below.**

Once the plan is in, Claude will read it, break it into phases, confirm scope,
and carry it out against the warehouse (leads, appointments, sales, spend,
calls, regional and platform data — 2025 to date).

---

<!-- PASTE THE PLAN BELOW THIS LINE -->
# Trust Electric Heating — Deep Business Analysis Plan

**Purpose:** A phased, end-to-end diagnostic of the business using the BigQuery medallion warehouse and connected sources (SharpSpring CRM, Ascend telephony — Wildix for historical periods, Google Ads, Meta Ads, Bing Ads, Unleashed inventory) plus the **sales performance spreadsheets held in the Downloads folder**, which cover sales data not present in Unleashed. The goal is to understand, with evidence, what is going right and what is going wrong — financially, in marketing, in sales operations, in sales rep performance, and in data quality — and to produce a ranked, actionable set of findings.

**Analysis layer:** All warehouse analysis runs against **bronze (raw data)**. Do not rely on silver/gold transformations — apply cleaning, deduplication, and type-casting in-query, and document every cleaning rule applied so results are reproducible and auditable.

**Executor:** Claude Code with BigQuery MCP.
**Working style:** Each phase produces a written findings file before moving on. No phase is skipped. Every headline number must be validated before it is reported.

---

## Operating Rules (read before starting)

1. **Never assume schema.** Discover it. Run `INFORMATION_SCHEMA` queries before writing any analytical SQL. Table and column names in this plan are descriptive placeholders — map them to real names in Phase 0 and record the mapping.
1a. **Bronze is raw.** Expect duplicates, inconsistent types, source-native field names, and unfiltered test/junk records. Every analytical query must handle these explicitly. Build a shared set of cleaning CTEs early (dedupe rules, date parsing, test-record exclusion) and reuse them consistently across phases — record them in `analysis_output/queries/cleaning_rules.sql`.
1b. **Spreadsheets are a first-class source.** The sales performance sheets in the Downloads folder contain sales data not in Unleashed. Inventory and load them in Phase 0, and reconcile them against warehouse data before either is treated as truth.
2. **Validate before reporting.** For every metric: row-count sanity, null check, magnitude check, trend continuity (no unexplained gaps), and aggregation logic (subtotals sum to totals). If a number looks surprising, investigate before writing it down.
3. **Flag uncertainty honestly.** Where data is incomplete (e.g. missing city data, unjoined spend, untagged leads), state the coverage percentage alongside every affected metric. Never smooth over inconsistencies — surface them.
4. **Write as you go.** Create `analysis_output/` with one findings file per phase (`phase_0_findings.md`, `phase_1_findings.md`, ...) plus a running `open_questions.md`. Save every important query into `analysis_output/queries/` so results are reproducible.
5. **Cost discipline.** Preview with `LIMIT` and dry-run byte estimates before running wide scans. Prefer partitioned/date-filtered queries. Default analysis window: **last 24 months**, with the **last 12 months** as the primary reporting period unless a trend demands longer history.
6. **Read-only.** This is a diagnostic. Do not write to, modify, or create tables in bronze/silver/gold without explicit approval. Intermediate results go to local files (CSV/JSON in `analysis_output/data/`).
7. **Currency and units.** All financials in GBP. State clearly whether figures are ex-VAT or inc-VAT once determined in Phase 4 — do not mix.

---

## Phase 0 — Environment, Schema Discovery & Data Inventory

**Objective:** Build a complete map of what data exists, its freshness, and its coverage, so every later phase queries the right thing.

**Tasks:**

1. List all datasets and tables across bronze, silver, and gold layers (`INFORMATION_SCHEMA.TABLES`, `INFORMATION_SCHEMA.COLUMNS`).
2. For every table: row count, min/max of the primary date column, last modified time, partition/cluster setup.
3. Map the **bronze layer in full**: one raw table map per source (SharpSpring, Ascend, Wildix, Google/Meta/Bing Ads, Unleashed), noting source-native field names and any obvious load artefacts (duplicated batches, header rows loaded as data, type mismatches).
4. Identify the canonical bronze tables for: leads, opportunities/deals, appointments, sales/orders, ad spend (per platform), ad clicks, calls (**Ascend for current data, Wildix for historical**), products/inventory (Unleashed), and any cost tables.
5. **Telephony cutover:** establish the exact Wildix → Ascend migration date from the data (last Wildix record, first Ascend record). Check for a gap or overlap period, compare schemas between the two systems, and define a unified call view (mapping table of equivalent fields) so call metrics can be trended continuously across the cutover. Flag any metrics that are not comparable across systems.
6. **Sales performance spreadsheets:** locate and inventory the sheets in the Downloads folder — list every file, its tabs, columns, date coverage, and grain (per rep? per order? per month?). Load them into local dataframes/CSVs under `analysis_output/data/`. Then reconcile: compare spreadsheet sales totals against Unleashed/warehouse order data for overlapping months to determine which source covers what, where they disagree, and which is authoritative for which metric. Record the verdict — this decides the revenue source of truth for Phase 4 and the rep source of truth for Phase 3.
7. Identify join keys between sources (lead ID, email, phone, gclid/fbclid/msclkid, order references, **rep name/ID across CRM, telephony, and spreadsheets** — watch for name spelling variants) and note where joins are known to be weak.
8. Record data freshness: for each source, when did the last pipeline run land data, and are there stale sources? Confirm the Ascend pipeline is landing data correctly since the migration.

**Deliverable:** `phase_0_findings.md` containing the schema map, canonical table list, join-key map, freshness table, and a short "gaps I already see" section.

**Gate:** Do not proceed until the canonical bronze tables for leads, spend, sales, and calls are confirmed, the Wildix→Ascend cutover is mapped, and the spreadsheet-vs-Unleashed reconciliation verdict is written down.

---

## Phase 1 — Data Quality & Trust Audit

**Objective:** Quantify how much of the downstream analysis can be trusted, and where numbers will be systematically biased.

**Tasks:**

1. **Completeness:** null rates on critical fields per table — lead source/channel, city/postcode, gclid, campaign, deal value, close date, call outcome, product line. Report as % of rows, trended by month (has quality degraded or improved over time?).
2. **Known issue — geographic data:** quantify the missing city problem precisely. Of all leads (and specifically the ~4,000 Yorkshire campaign leads), what % have city/postcode? Of null-city leads, what % have a populated gclid (the `click_view` recovery route)? Produce the recovery-potential number.
3. **Duplicates:** duplicate leads by email/phone; duplicate orders; double-counted spend rows.
4. **Join integrity:** what % of spend can be tied to leads? What % of leads tie to a call record? What % of sales tie back to a lead? Report the attrition at each join — this defines the confidence ceiling for attribution.
5. **Consistency:** cross-check totals against source-of-truth where possible (e.g. monthly Google Ads spend in BigQuery vs. platform-reported spend for 2–3 sample months). Flag discrepancies >2%.
6. **Outliers and anomalies:** impossible values (negative spend, £0 or absurd deal values, future dates), and sudden step-changes in row volume suggesting pipeline breaks or double-loads — pay particular attention around the Wildix→Ascend cutover date.
7. **Bronze-specific checks:** duplicate load batches (same records landed twice), test/internal records (staff emails, test phone numbers, £0 test orders) and define the exclusion rules; type integrity (dates stored as strings, numerics with currency symbols).
8. **Spreadsheet quality:** for the sales performance sheets — manual-entry issues (inconsistent rep name spellings, merged cells, subtotal rows mixed with data rows, missing months), and quantify the disagreement found in the Phase 0 reconciliation.

**Deliverable:** `phase_1_findings.md` — a data trust scorecard per source (green/amber/red), the geographic-gap recovery numbers, and a list of caveats that every later phase must carry forward.

**Gate:** Every later finding must reference the relevant caveat from this phase where coverage is <90%.

---

## Phase 2 — Marketing Performance Deep Dive

**Objective:** Understand paid channel performance in depth — where money is working, where it's being wasted, and how trends are moving.

**Tasks:**

1. **Spend and volume trends:** monthly (and weekly for the last 6 months) spend, impressions, clicks, leads by platform (Google/Meta/Bing) for 24 months. Identify inflection points and annotate with known events where possible.
2. **Efficiency metrics per channel and per campaign:** CPC, CPL, lead-to-appointment rate, cost per appointment, and (joining to Phase 4 revenue) cost per sale and ROAS. Trend all of these monthly — a flat CPL with declining lead quality is a common hidden failure, so always pair cost metrics with downstream conversion.
3. **Seasonality:** month-of-year patterns in lead volume, CPL, and conversion (heating is strongly seasonal — quantify the shape, since this feeds the planned ML/budget-allocation model). Compare year-on-year for the same months to separate seasonality from genuine decline/growth.
4. **Campaign-level winners and losers:** rank campaigns by cost per appointment and ROAS over the last 12 months; identify the bottom decile of spend (candidates for cutting) and estimate the £ reallocation opportunity.
5. **Yorkshire campaign focus:** dedicated section — spend to date, leads, CPL, conversion vs. the account average, and the impact of the missing city data on targeting/reporting.
6. **Channel mix over time:** how has the spend split across Google/Meta/Bing shifted, and has blended CPL moved with it? Is the mix drifting toward or away from the efficient channels?
7. **Lead quality by source:** using SharpSpring lead status/stage, compare junk/unqualified rates across channels — cheap leads that never convert are the classic marketing false positive.

**Deliverable:** `phase_2_findings.md` — channel scorecard, trend narrative, seasonality profile, ranked campaign table, wasted-spend estimate in £, and Yorkshire campaign assessment.

---

## Phase 3 — Sales Funnel, Operations & Rep Performance

**Objective:** Find where leads die between enquiry and sale, whether the problem is lead quality, response speed, or sales execution — and build a fair, evidence-based picture of individual sales rep performance to support decisions.

### 3A — Funnel & Operations

1. **Full-funnel conversion:** lead → contacted → appointment → quote → sale, overall and by channel, monthly for 24 months. Identify the single largest drop-off stage and whether it's worsening.
2. **Speed-to-lead:** using call data (Ascend for the current period, Wildix for historical, via the Phase 0 unified call view) joined to lead creation timestamps, measure time from lead creation to first contact attempt, and correlate with conversion. Report the distribution, not just the mean.
3. **Call operations:** answer rates, missed/abandoned calls, calls by hour-of-day and day-of-week vs. lead arrival patterns — is coverage aligned with demand? Quantify leads arriving outside answered hours. Note whether call operations metrics shifted at the Ascend migration (a system change often changes behaviour or measurement, and the two must not be conflated).
4. **Sales velocity:** median days lead-to-sale by channel and by month; is the pipeline slowing down?
5. **Lost-reason analysis:** if loss reasons exist in SharpSpring, aggregate them; if they're mostly null, record that as a process gap finding in itself.

### 3B — Sales Rep Performance (dedicated section)

Use the source-of-truth verdict from Phase 0 (spreadsheets vs. CRM vs. telephony) and join rep identities across all three, resolving name variants first.

1. **Rep scorecard:** for each rep, over the last 12 months and trended monthly — leads handled, appointments set, appointment rate, sales closed, close rate, revenue, average order value, and revenue per lead handled. Present as a single comparable table.
2. **Fairness controls:** normalise for lead mix — reps fed better channels or regions will look better through no skill of their own. Compare each rep's conversion against the expected rate given their channel/region mix, not just the raw average. Require a minimum sample size (state it, e.g. n ≥ 30 leads) before ranking anyone, and mark below-threshold reps as "insufficient data" rather than ranking them.
3. **Activity vs. outcome:** call volume, talk time, and speed-to-first-call per rep (from telephony) against their conversion — separates effort problems from effectiveness problems.
4. **Trend and consistency:** is each rep improving, flat, or declining? Flag reps with high variance month-to-month vs. consistent performers.
5. **Reconciliation with the sales performance sheets:** where the spreadsheets record rep-level figures (targets, commissions, recorded sales), compare against warehouse-derived numbers and flag discrepancies — these matter for both trust and payroll accuracy.
6. **Team-level insights:** distribution of performance (is revenue concentrated in one or two reps — key-person risk?), and what the top performers do differently in the measurable data (speed, call volume, channel handling) as coaching input.

**Deliverable:** `phase_3_findings.md` — funnel diagram with conversion rates and trends, speed-to-lead findings, operational coverage gaps, the full rep scorecard with fairness caveats, and a clear statement of whether the constraint is lead volume, lead quality, or sales conversion.

---

## Phase 4 — Financial Analysis

**Objective:** Understand the money: revenue trends, product economics, marketing payback, and where the financial picture is deteriorating.

**Tasks:**

1. **Revenue trends:** monthly revenue for 24 months, total and by product line/category, using the revenue source of truth established in Phase 0 (sales performance spreadsheets combined with Unleashed/order data — Unleashed alone is incomplete). Present YoY comparison per month, identify declining and growing product lines, and state clearly which months/segments come from which source.
2. **Order economics:** average order value trend, order volume trend — separate "fewer orders" from "smaller orders" as the driver of any revenue decline.
3. **Product performance:** revenue, units, and (if cost data exists in Unleashed) gross margin by product. Flag high-volume/low-margin products and any margin compression over time. If cost data is unavailable, state so explicitly and analyse revenue mix only.
4. **Marketing payback:** blended CAC (total paid spend ÷ new customers) monthly, CAC vs. AOV ratio, and fully-loaded cost per sale by channel. Trend the marketing-cost-as-%-of-revenue line — this is the single clearest "is marketing efficiency deteriorating" signal.
5. **Geographic revenue:** revenue by region/postcode area where address data allows (carrying the Phase 1 coverage caveat), compared against the opportunity datasets (ONS heating type, EPC, fuel poverty) to show where sales under-index against the addressable market.
6. **Inventory signals (if Unleashed data supports it):** stock levels vs. sales velocity — overstocked slow movers and stockout risk on fast movers.

**Deliverable:** `phase_4_findings.md` — revenue and margin narrative, CAC/payback trends, product winners and losers, and a quantified list of the top financial concerns.

---

## Phase 5 — Cross-Cutting Synthesis: What Is Going Wrong

**Objective:** Integrate everything into a ranked diagnosis, separating symptoms from root causes.

**Tasks:**

1. Build a **problem register**: every negative finding from Phases 1–4 with: evidence (query + number), estimated £ impact or risk, confidence level (given data caveats), and root-cause hypothesis.
2. Distinguish root causes from symptoms (e.g. "rising blended CPL" may be a symptom of channel-mix drift found in Phase 2, not of any single channel getting worse).
3. Rank the register by estimated £ impact × confidence.
4. Identify the **top 5 issues** and for each write: what the data shows, why it's happening (or the competing hypotheses if unclear), what would confirm it, and the recommended action.
5. Mirror it with a **top 5 strengths** list — things working that should be protected or scaled.
6. List **data gaps blocking better answers**, prioritised (this feeds the data quality roadmap — gclid city recovery, loss reasons, cost data, etc.).

**Deliverable:** `phase_5_findings.md` — the ranked problem register, top-5 issues and strengths, and the data-gap priority list.

---

## Phase 6 — Executive Report & Recommendations

**Objective:** Produce the final deliverables for Olivia and the wider team.

**Tasks:**

1. Write `FINAL_REPORT.md`: executive summary (one page, plain language, no jargon), then sections for marketing, sales operations, financial, and data quality, each with the key charts/tables referenced and every claim traceable to a phase findings file.
2. Build a small set of supporting visualisations (trend charts for the headline metrics — revenue, blended CPL, funnel conversion, CAC/AOV) saved to `analysis_output/charts/`.
3. Write a **prioritised action plan**: quick wins (this month), structural fixes (this quarter), and strategic moves (this year), each with expected £ impact and owner suggestion.
4. Write a short **measurement plan**: the 6–8 metrics to monitor monthly to know whether the actions are working, and where each should live (gold layer / Trustwarehouse Analytics).
5. Note explicitly which findings should feed the planned ML prediction model (seasonality profile, channel efficiency curves, speed-to-lead effect) so that work starts from evidence rather than assumptions.

**Deliverable:** `FINAL_REPORT.md`, charts, action plan, measurement plan.

---

## Suggested Session Breakdown

- **Session 1:** Phases 0–1 (discovery + quality audit). These are the foundation; rushing them corrupts everything downstream.
- **Session 2:** Phase 2 (marketing) and Phase 3 (funnel/ops).
- **Session 3:** Phase 4 (financial) and Phase 5 (synthesis).
- **Session 4:** Phase 6 (report), plus review and iteration.

At the start of each session, re-read the previous phases' findings files and `open_questions.md` before running new queries.

## Known Context to Carry In

- **All warehouse analysis runs against bronze (raw)** — apply and document cleaning rules in-query; do not rely on silver/gold transformations.
- **Telephony migrated from Wildix to Ascend** — historical call data is Wildix, current is Ascend; establish the cutover date and a unified call view in Phase 0 before trending any call metric across it.
- **Unleashed does not hold all sales data** — the sales performance spreadsheets in the Downloads folder are a required source and must be reconciled against warehouse data in Phase 0.
- ~4,000-lead Yorkshire campaign has majority-missing city data; gclid → `click_view` lookup is the identified recovery route (Google only; Meta fbclid has no equivalent).
- SharpSpring API limits: ~5 req/sec, ~10k req/day (community figures) — but prefer already-landed BigQuery data over live API pulls throughout.
- Radiator/heating demand is strongly seasonal; all YoY comparisons must be same-month.