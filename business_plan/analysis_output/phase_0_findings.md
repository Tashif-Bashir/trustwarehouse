# Phase 0 Findings — Environment, Schema Discovery & Data Inventory

Run date: **16 Jul 2026** · Analyst: Claude Code · All queries in `queries/phase0_*.py`, raw outputs in `data/`.
Analysis window per plan: **last 24 months = Aug 2024 – Jul 2026**, primary reporting period **Jul 2025 – Jul 2026**.

---

## 0.1–0.2 Warehouse map

7 datasets. Analysis uses **bronze only** (per plan). Full per-table inventory with row counts,
sizes, date coverage and last-modified: `data/phase0_table_inventory.csv`.

| Dataset | Tables | Role | Note |
|---|---|---|---|
| bronze | 56 | **all analysis** | raw, source-native names |
| bronze_staging | 24 | dlt merge staging | **artefact — never query** (partial copies) |
| silver / gold | 19 / 10 | dbt transforms | out of scope per plan (gold known buggy: `gold_lead_activity.domestic_lead_status` holds a literal field name, bug logged 13 Jul) |
| app | 3 | booking-app operational | bookings audit useful for appointment provenance |
| cms_ingestion | 7 | website form submissions | small (1–66 rows/form) |
| shared_marketing | 21 views | masked window for shared account | ignore |

## 0.3–0.4 Canonical bronze tables

| Entity | Table | Rows | Date coverage | Fresh as of run |
|---|---|---|---|---|
| Leads | `sharpspring_leads` | 58,886 | 2018-04-27 → today | ✅ 30-min sync |
| Lead notes | `sharpspring_notes` | 169,676 | 2018-05-31 → yesterday | ✅ daily 05:30 |
| Opportunities | `sharpspring_opportunities` | 6,452 | 2018 → today | ✅ 30-min |
| Campaign lookup | `sharpspring_campaigns` (+`_deal_stages`,`_fields`) | 66 | — | ✅ |
| Calls (current) | `ascend_calls` | 4,284 | **2026-07-01 → now** | ✅ 60-sec sync |
| Calls (historical) | `wildix_calls` | 149,092 | **2025-05-20 → 2026-06-30** | frozen (retired) |
| Call transcripts | `ascend_transcripts` (39), `wildix_transcripts` (183) | — | samples only; transcription paused | — |
| Google spend | `google_ads_api_campaign_daily` | 53,025 | 2020-01-02 → today | ✅ 8×/day |
| Meta spend | `meta_api_campaign_daily` | 11,057 | 2023-06-24 → today | ✅ 8×/day |
| Bing spend | `bing_adscampaign_performance_report_daily` (+account/adgroup/ad/keyword variants) | 47,966 | **2025-01-01 → today** | ✅ Airbyte |
| Web analytics | `ga4_api_*_daily` (7 tables) | up to 497k | dates as `'YYYYMMDD'` strings — use `PARSE_DATE('%Y%m%d', date)` | ✅ 8×/day |
| Sales orders | `unleashed_sales_orders` (+`__sales_order_lines`) | 3,381 / 16,902 | 2024-03-20 → yesterday (order_date = `/Date(ms)/` — regex-extract millis) | ✅ daily 07:00 |
| Products / stock | `unleashed_products` (887), `unleashed_stock_on_hand` (738) | — | snapshot (full-replace, **no history**) | ✅ |
| Purchase orders | `unleashed_purchase_orders` | **exactly 1,000** | 2025-01-03 → 13 Jul | ⚠ suspected pagination cap — do not trust totals |
| Web form detail | `cms_ingestion.form_*` | 1–66 | — | ✅ |

## 0.5 Telephony cutover: Wildix → Ascend

Established **from the data** (daily counts in `queries/phase0_cutover_joins2.py` output):

- Last full Wildix day: **30 Jun 2026** (329 calls). 13 stragglers on 1 Jul, one stray record 10 Jul (ignore).
- First Ascend day: **1 Jul 2026** (388 calls). **No gap, negligible overlap.**
- **Boundary rule for the unified view: Wildix < 2026-07-01 ≤ Ascend.**
- ⚠ **Call history floor: 2025-05-20.** Wildix bronze starts then — call-based metrics
  (speed-to-lead, call ops) exist for ~14 months, not the full 24-month window.

**Unified call view — field mapping** (comparability traps flagged):

| Concept | Wildix | Ascend | Trap |
|---|---|---|---|
| start | `TIMESTAMP_MILLIS(start_time)` | `start` | both UTC |
| direction | `LOWER(direction)` (OUTBOUND/INBOUND/INTERNAL) | `direction` (outbound/inbound/internal) | same taxonomy ✓ |
| agent | `_colleague_name` | `JSON_VALUE(from/to,'$.name')` by direction | name-spelling variants exist |
| customer no. | `remote_phone` | `JSON_VALUE(from/to,'$.number')` | normalise to 44… digits |
| talk seconds | **`talk_time`** | `duration` | ⚠ Wildix `duration` includes ring — NEVER use it as talk time |
| answered | `talk_time > 0` | `answered` (BOOL) | proxy on Wildix side |

## 0.6 Sales performance spreadsheets — inventory & reconciliation

**Files** (Downloads): `2025 Sales Offline Version.xlsx` (tabs May 2022 → July 2025) and
`2026 Sales offline version.xlsx` (Jan → Jul 2026). Grain: **one row per sale** (per-rep scorecard
blocks sit under each ledger — excluded by validated counting rule, see header of
`queries/phase0_sheets_reconcile.py`). Monthly counts saved to `data/sheet_sales_by_month.json`;
full reconciliation table `data/phase0_sheet_vs_unleashed.csv`.

**Layout epochs:** Jan–Jul 2024 tabs use an older header ('Name', no Date col) — not parseable with
the standard rule, but they fall **outside the 24-month window**. Aug 2024+ parse cleanly.
2024 tabs have 'Sector' instead of 'Dept' (refund filter inactive for 2024 — minor).

**Reconciliation verdict (the Phase 4/3 source-of-truth ruling):**

| Period | Sales counts & revenue | Rep attribution |
|---|---|---|
| **Aug 2024 – Dec 2024** | **Sheets only.** Unleashed was being adopted (1–86 orders/mo vs 179–281 on sheets) | Sheets |
| **Jan 2025 onward** | **Unleashed** (complete; consistently ≥ sheets by 8–50 orders/mo — captures order types the sheets skip). ⚠ Jan 2025 Unleashed (295 orders/£942k) is inflated by adoption-backlog keying of Nov–Dec 2024 sales — use sheets for monthly *timing* in H1 2025 | **Sheets** where tabs exist (rep column reliable, deposit-dated); Unleashed `sales_person` + CRM owner as fallback |
| **Aug – Dec 2025** | Unleashed (sheet tabs absent from the file) | ⚠ weakest period — no sheet tabs; Unleashed/CRM only |
| VAT | Sheets mix inc/ex-VAT per row; Unleashed `sub_total` is clean **ex-VAT** → all Phase 4 revenue reported **ex-VAT from Unleashed** where available | — |

## 0.7 Join-key map (measured, not assumed)

| Join | Key | Measured strength |
|---|---|---|
| Lead ↔ call | normalised phone (44-prefix digits) | **95.8%** of last-14d leads with a phone have ≥1 Ascend call |
| Sale ↔ lead | customer email (Unleashed customer ↔ lead email) | **87.3%** of last-12-mo orders match a lead |
| Lead ↔ CRM campaign | `campaign_id` → `sharpspring_campaigns` | **98–99.6%** |
| Lead ↔ ad-click | `gclid1_66dad68843cd4` | **11.8% (2024) / 32.2% (2025) / 22.1% (2026)** — weak; Google-only |
| Lead ↔ UTM campaign | `exact_marketing_campaign_…` | 31.9% / 42.7% / 51.5% by year |
| Lead → region | `location_…` picklist | **18.2% (2024) → 46.6% (2025) → 91.6% (2026)** — automation ramped late; 2024 regional analysis must fall back to postcode (18.3%) + city |
| Rep identity | names across CRM/phones/sheets | variants known (Kris/Kourosh, Sammy=Samuel, Steve/Stephen…) — resolve via `silver.sales_rep_mapping` seed + manual table in Phase 3 |

## 0.8 Freshness (all confirmed landing on run day)

Ascend 60-sec ✅ · SharpSpring 30-min ✅ · notes daily 05:30 ✅ · Unleashed daily 07:00 ✅ ·
Google/Meta/GA4 8×/day ✅ · Bing (Airbyte) daily ✅ · Wildix frozen since cutover (correct) ·
transcription paused (by decision).

## Gaps I already see (feed Phase 1 & open_questions.md)

1. **Bing spend starts 2025-01-01** — no H2 2024 Bing spend in the warehouse; blended CPL for Aug–Dec 2024 misses Bing (was ~5% of recent spend).
2. **Call history floor 2025-05-20** — no speed-to-lead/ops metrics before then.
3. **`unleashed_purchase_orders` capped at exactly 1,000 rows** — pagination bug suspected; do not use for COGS/inbound analysis until fixed.
4. **Region picklist coverage ramp** (18→92%) makes multi-year regional trends structurally biased — must use the postcode/city ladder for 2024.
5. **Postcode coverage falling** (18% → 8% of leads by year) — phone-lead mix growing.
6. **Aug–Dec 2025 sheet tabs missing** → weakest rep-attribution period.
7. **Jan 2025 Unleashed backlog hump** — adoption artefact, not real January demand.
8. GA4 dates are `YYYYMMDD` strings; Unleashed dates are `/Date(ms)/` — cleaning rules to be codified in Phase 1 `cleaning_rules.sql`.
9. Gold layer has a known field-mapping bug — reinforces the bronze-only rule.

**GATE STATUS: PASSED** — canonical tables confirmed, cutover mapped, reconciliation verdict written.
