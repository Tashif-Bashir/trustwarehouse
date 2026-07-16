# Phase 1 Findings — Data Quality & Trust Audit

Run date: **16 Jul 2026** · Queries: `queries/phase1_*.py` · Cleaning rules codified: `queries/cleaning_rules.sql`
Monthly completeness trend data: `data/phase1_completeness_monthly.csv`

---

## Trust scorecard (per source)

| Source | Verdict | Why |
|---|---|---|
| SharpSpring leads | 🟢 **GREEN** | 0 duplicate ids in bronze; ~99% have a phone; test pollution negligible (~34 rows); CRM-campaign attribution 96–99%. Caveats: geo + gclid coverage (below). |
| Google spend | 🟢 **GREEN** | Grain = date × campaign × **ad-network** (repeated keys are slices, not dupes — validated: raw sum matches platform-cross-check within 0.02%). No negatives. |
| Meta spend | 🟢 **GREEN** | Clean daily grain, zero dupes/negatives. Campaign *names* drift after renames — always key on campaign_id. |
| Bing spend | 🟡 **AMBER** | Bronze internally consistent (account vs campaign reports agree to the penny) **but starts 2025-01-01** (no H2-2024) — and **silver_bing_spend undercounts ~18%** vs bronze (filter bug; bronze used throughout). |
| Calls (unified) | 🟡 **AMBER** | Ascend clean (0 dupes). Wildix rows are call *legs* with partial re-loads: 149,092 rows → 135,760 real calls — dedupe rule mandatory (in cleaning_rules.sql). History floor 2025-05-20. Wildix `answered` is a proxy (talk_time>0). |
| Unleashed sales | 🟢 **GREEN** (from Jan 2025) | 0 duplicate order numbers, 0 future dates, 26 zero/neg rows (excluded). ⚠ 570 'Parked' orders (£2.09M!) excluded from sales by rule — Phase 4 must examine what Parked means commercially. |
| Sales sheets | 🟡 **AMBER** | Authoritative pre-2025 & for rep attribution; hand-keyed with scorecard blocks inside ledgers (validated parser), mixed VAT, missing Aug–Dec 2025 tabs, layout epochs. |
| Purchase orders | 🔴 **RED** | Exactly 1,000 rows — pagination cap suspected. **Do not use.** |

## 1.1 Completeness — the trends that matter

- **Region picklist automation started Aug 2025** (13% → 97–98% overnight). Regional lead analysis
  before Aug 2025 must use the postcode/city ladder (~25–30% combined coverage) — every pre-Aug-2025
  regional split carries this caveat.
- **Postcode capture is decaying**: 22% (Aug 24) → 6–9% (2026). Cause: rising share of phone-created
  leads (2,410 phone-artefact leads carry no geo/email by construction).
- **gclid capture halved**: ~46% (Dec 24–Feb 25) → 10–15% (mid-2026). Weakens click-level Google
  attribution going forward — worth a pipeline/tagging investigation (register as data-gap #1).
- **Blank Domestic Lead Status spiked to 10.4% in Jun 2026 and 11.5% in Jul** (vs 0–3% norm).
  Some is recency (unworked new leads), but June is closed — this is a live process regression:
  leads leaving the funnel without an outcome. (Feeds Phase 3 & problem register.)

## 1.2 The "Yorkshire campaign" geo gap — corrected picture

There is **no CRM or UTM campaign matching 'york%'** at meaningful volume (5 UTM leads). The plan's
"~4,000 Yorkshire leads" is best read as **leads resolved to Yorkshire**: currently 1,509 leads carry
the Yorkshire region picklist (post-Aug-2025 mostly). Of those, 1,205 (80%) lack city+postcode;
**316 of the 1,205 (26%) have a gclid** → theoretical `click_view` recovery.
⚠ **Practical recovery is far smaller**: Google retains click_view for ~90 days, so only recent
leads are recoverable — treat gclid recovery as a *forward-looking fix* (start capturing
geo at form/call time), not a back-fill miracle.

## 1.3 Duplicates

- Leads: 47 excess email rows + 540 excess phone rows in 24 months (~1.5%) — mostly genuine repeat
  enquirers; **kept for funnel counts**, dedupe-to-latest only for customer-level joins.
- Spend: none (after grain corrections). Orders: none. Wildix: handled by leg-dedupe rule.

## 1.4 Join integrity (attrition ladder)

| Join | Strength |
|---|---|
| Lead → CRM campaign (platform-level attribution) | **96–99%** 🟢 |
| Lead → call record (phone match, recent cohort) | **95.8%** 🟢 |
| Sale → lead (email) | **87.3%** 🟢 |
| Lead → ad-click (gclid, campaign-level Google) | 10–46% by month 🔴 — attribution ceiling for click-level analysis |
| Lead → region | 92%+ post-Aug-2025; ~25–30% before 🟡 |

Attribution confidence ceiling: **platform-level = high; campaign-level = medium (UTM 32–52%);
click/keyword-level = low.** Phases 2–4 report at platform level by default.

## 1.5 Consistency cross-checks

- Google bronze June 2026 = £43,377.97 vs the independent geographic_view pull = £43,369.45
  (**0.02% delta** — different report views; PASS).
- Bing account-report vs campaign-report June 2026: £3,803.56 vs £3,803.60 (PASS).
  → but **silver_bing_spend says £3,223.25 for the same month (−18%)** — silver bug, bronze wins.
- Sheets vs Unleashed: reconciled in Phase 0 (verdict table there).

## 1.6 Anomaly scan

- No negative spend anywhere; no future-dated orders.
- Google row-volume steps (May-2025 ×2, 2026 ×1.5) are **report-grain changes** (network segmentation),
  not spend jumps — spend continuous through them.
- Call volume across the Wildix→Ascend cutover is continuous (weekly 1.6–2.5k, no cliff) —
  call *metrics* comparable across cutover **only** via the unified-view rules (talk_time vs duration).
- One stray Wildix record post-cutover (ignored).

## Caveat register (carried into every later phase)

1. **C1**: pre-Aug-2025 regional splits = ~25–30% coverage only.
2. **C2**: click-level Google attribution ≤46% and falling; use platform level.
3. **C3**: Bing spend absent before Jan 2025 (blended CPL for Aug–Dec 2024 understates spend ~4–6%).
4. **C4**: call metrics start 2025-05-20; Wildix answered = proxy.
5. **C5**: rep attribution weakest Aug–Dec 2025 (no sheet tabs).
6. **C6**: 'Parked' Unleashed orders (£2.09M) excluded — pending Phase 4 ruling.
7. **C7**: phone-artefact leads (2,410) have no email/geo by construction.
8. **C8**: sheet amounts mix VAT treatment; revenue reported ex-VAT from Unleashed where possible.

**GATE:** rules codified in `cleaning_rules.sql`; scorecard above governs every later claim.
