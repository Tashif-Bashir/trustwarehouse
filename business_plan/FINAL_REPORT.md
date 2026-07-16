# Trust Electric Heating — Business Diagnostic, July 2026

**Prepared:** 16 Jul 2026 · **Evidence base:** company data warehouse (CRM, phones, all ad platforms,
Unleashed, sales sheets), Aug 2024 – Jul 2026. Every number traces to a phase findings file and a
saved query in `analysis_output/`. Charts referenced are in `analysis_output/charts/`.

---

## Executive summary (the one page)

**The good news: the team is not the problem.** People who ring in or fill a form are more likely
than ever to end up with an appointment (26 in 100 now vs 19 in 100 two years ago), the reps close
appointments at a steady ~3 in 10, a sale completes in about 2–3 weeks, and product margins are
strong and stable. Revenue for the first half of 2026 is level with — probably slightly ahead of —
last year.

**The bad news: feeding that team has become twice as expensive, and part of what we buy is wasted.**
A lead cost ~£30 in late 2024; it costs ~£80–86 now *(chart 1)*. That happened in two identifiable
steps — **March 2025 and March 2026 — both times the ad budget was raised heavily just as seasonal
demand fell** (March is one of the weakest months for heating interest). Most of the extra money
went to Google, whose return fell from ~£5.80 back per £1 to ~£2.70 as it was force-fed *(chart 2)* —
while Facebook, whose return was improving, was cut. On top of that: **roughly 1 in 4 leads we pay
for never receives a phone call** (up to 4 in 10 during the busy winter), nobody dials after 5pm
although ~30% of leads arrive in the evening or weekend, and during the first half of 2026 the
business quietly lost several proven sales reps whose replacements are still ramping up.

**Why it doesn't show in revenue yet:** sales lag leads by 3–6 weeks, and the team's improving
conversion has been absorbing the damage *(charts 3 & 5)*. July's soft numbers are the first sign.
**August–October is when the lead drought reaches the bank account — unless the input side is fixed
now.** The fixes are specific, mostly cheap, and listed below with owners.

One number to remember: **acquiring a new customer cost ~£500 a year ago; it costs ~£950 now**
*(chart 4)*. Nothing else in this report matters more than bending that curve back.

---

## 1. Marketing (detail: `phase_2_findings.md`)

- Blended cost per lead £25–46 (Aug 24–Feb 25) → £76–87 (2026). Two March step-changes, both
  budget-driven, visible in chart 1.
- Channel returns last 12 months (revenue matched to orders): Google 3.3×, Meta 3.8×, Bing 3.9× —
  the money concentrated in the weakest returner (Google reached 78% of paid spend).
- Campaign level: regional **Search** campaigns are systematic losers (worst: £2,707 per conversion
  vs £132 account median); regional **Pmax** is fine. £26k/yr of direct waste identified, including
  £5.9k on a campaign named "TEST".
- Seasonality is strong and now quantified: peaks Sep–Nov & Jan; troughs Jul & Dec; March–June flat.
  Budget should follow this curve — it currently does the opposite at the worst moment.
- "The Yorkshire problem" is dead: Yorkshire converts above average and anchors the biggest revenue
  region. The real gap was missing geo data, now traced to tagging (fixable at source).

## 2. Sales operations (detail: `phase_3_findings.md`)

- **Speed-to-lead**: median time to first call is 11–15 *hours*; only ~25% called within 10 minutes.
  When staffed, the team is exceptional (1-minute median for office-hours arrivals) — the problem is
  coverage, not effort.
- **The never-called block**: ~25% of leads get no call within 14 days (40% in winter peak). These
  still convert at 15% by themselves — called leads convert at 22–27%. This is the single most
  recoverable operational loss (£150–300k/yr potential).
- **Nothing is dialled after 17:00** (verified zero) vs ~30% of leads arriving out of hours.
- **Possible inbound leak**: under the new phone system the answered rate reads ~51% (was 90%+).
  Partly a measurement change, but ~200 calls/week appear to die in the phone menu.
  **One hour of test-calling the IVR this week settles it** — potentially the highest-£/hour action
  in this report.
- **2,440 warm "Follow Up" leads + 333 cancelled appointments** sit unresolved — a nearly-free
  re-work pipeline.
- **Rep churn**: Shane, Chris, Sachin and Ambivo left/faded in H1-2026 and Rob (a top-5 closer) has
  been inactive since April — ~40–50 sales/month of proven capacity lost while new hires ramp.
- June–July hygiene slip: 10%+ of leads now end with **no status at all** (norm ≤3%) — outcomes are
  going unrecorded exactly when every lead is precious.

## 3. Financial (detail: `phase_4_findings.md`)

- Revenue level (H1-26 ≈ H1-25 +13% like-for-like); margins healthy (60–66% GM) and stable.
- **Water Heating: 82% gross margin** — the most profitable thing sold; push it in every appointment.
- CAC ×2 YoY; marketing % of revenue 12–15% → 20%+. Still profitable per order; direction unsustainable.
- Build-to-order model confirmed: inventory is a non-issue.
- Revenue heartland: Yorkshire/North-East (~£450k/yr), then Midlands, Thames Valley, East Anglia, South West.

## 4. Data quality (detail: `phase_1_findings.md`)

Mostly trustworthy (that's why this report can be specific), with fix-list: UTM tracking template
broken (campaign-level measurement impossible until fixed), gclid capture halved, postcode capture
falling, purchase-order sync capped at 1,000 rows, one silver-layer Bing bug (−18%), CRM picklist
name hygiene. None block the actions below.

---

## Action plan

### Quick wins — this month
| # | Action | Owner (suggested) | Expected effect |
|---|---|---|---|
| 1 | **Test-call the IVR / verify inbound answering** (1 hour) | Office manager + Tashif | Confirms or kills a potentially £10k+/week leak |
| 2 | **Rebooking blitz: 333 cancelled appointments** | Telesales lead | ~80 appointments at zero media cost |
| 3 | **Never-called daily worklist** (warehouse generates it) | Telesales lead | Kills the 25% never-called loss going forward |
| 4 | **Kill regional-Search campaigns + "TEST"** | Marketing/agency | ~£26k/yr direct waste stopped |
| 5 | **Auto-SMS on out-of-hours lead arrival** ("we'll call at 9am — reply with a better time") | Tashif (build) | Holds the 30% out-of-hours wave warm |
| 6 | **Status-required working rule** (no lead closed without an outcome) | Telesales lead | Reverses the June hygiene slip; restores measurement |

### Structural — this quarter
| # | Action | Owner | Expected effect |
|---|---|---|---|
| 7 | **Rebalance media**: cap Google at demonstrated-return level (~£35–40k/mo), restore Meta ~£20k/mo, keep Bing modest | Marketing + Tashif (weekly CPL/CPA readout) | Bends CAC back toward £600; £40–60k/qtr efficiency |
| 8 | **Coverage pilot**: Saturday morning + one evening shift (2 people) | Ops | Works the 28% weekend/evening arrivals; measured vs control |
| 9 | **Follow-Up SLA (7-day) + re-work queue** from warehouse | Telesales lead | Drains the 2,440-lead limbo, £50–150k/yr |
| 10 | **Fix UTM template + form geo fields + gclid tag** | Tashif + agency | Unlocks campaign-level optimisation permanently |
| 11 | **Closer capacity plan**: Rob conversation, ramp targets for Apr–Jun hires, appointment-attendance now tracked via booking app | Sales director | Restores 40–50 sales/mo sat capacity |
| 12 | **September scale-up plan** built on the seasonality curve (budgets rise late Aug; never in March) | Marketing | Rides the strongest quarter instead of chasing it |

### Strategic — this year
| # | Action | Rationale |
|---|---|---|
| 13 | **Push Water Heating hard** (82% GM) — target every heating appointment carries the water pitch | Highest-margin growth line |
| 14 | **Regional playbook**: replicate the Yorkshire/NE model (regional Pmax + strong rep coverage) in under-indexed high-revenue-potential regions | Data-backed expansion |
| 15 | **Budget-allocation model** (ML): seasonality curve + channel marginal-return curves now quantified — automate monthly budget proposal | The two March mistakes become impossible |
| 16 | **Commercial (Glenigan) tool** as a second demand engine independent of paid media | Diversifies away from rising CPL |

## Measurement plan — the monthly eight

| Metric | Definition | Target | Lives in |
|---|---|---|---|
| Blended CPL | paid spend ÷ paid leads | back under £55 by Oct | warehouse (gold view) |
| Cost per appointment | spend ÷ cohort appts | < £250 | warehouse |
| Blended CAC | spend ÷ new customers | < £650 | warehouse |
| Never-called % | leads w/o dial in 48h | < 5% | warehouse (calls join) |
| Called-within-10-min % | office-hours leads | > 60% | warehouse |
| True inbound answer rate | answered-by-human ÷ inbound | > 90% | Ascend + config fix |
| Appointments per week | cohort + booked-by | ≥ 90 | warehouse / booking app |
| Marketing % of revenue | spend ÷ ex-VAT revenue | ≤ 15% | warehouse |

All eight are computable today from bronze; recommend one `gold` scorecard model + the existing
dashboard. Review monthly against this report's baselines.

## Notes for the planned ML/budget model (plan 6.5)

Feed it: (1) the quantified month-of-year demand curve (Phase 2 — strong, two-year consistent);
(2) channel marginal-return evidence (Google saturates above ~£40k/mo — two natural experiments;
Meta stable to at least £27k/mo); (3) the speed-to-lead/conversion relationship is **confounded**
in observational data (late-called leads include self-selecting bookers) — do NOT let the model
learn "calling late is fine"; treat coverage as a constraint, not a variable; (4) cost-per-sale
should use the unified sales definition (Unleashed ex-VAT, Parked excluded) with the 180-day
attribution window; (5) exclude Jan-2025 Unleashed backlog month from any training data.

---
*Full traceability: `analysis_output/phase_0..5_findings.md`, queries in `analysis_output/queries/`,
raw outputs in `analysis_output/data/`, charts in `analysis_output/charts/`. Data caveats C1–C8 in
`phase_1_findings.md` apply as stated inline.*
