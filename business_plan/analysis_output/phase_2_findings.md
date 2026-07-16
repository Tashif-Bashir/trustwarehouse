# Phase 2 Findings — Marketing Performance Deep Dive

Run date: 16 Jul 2026 · Window: Aug 2024 – Jul 2026, primary Jul 2025 – Jun 2026 ·
Queries: `queries/phase2_*.py` · Data: `data/phase2_*.csv`
Caveats carried: C2 (campaign-level lead attribution weak), C3 (no Bing spend pre-2025),
C8 (revenue ex-VAT via Unleashed email-join, complete from Jan 2025 — 2024 ROAS understated).

---

## Channel scorecard — last 12 months (Jul 2025 – Jun 2026)

| | Spend | Leads | Appts | Sold* | Revenue* | CPL | Cost/appt | Cost/sale | ROAS* | Junk% | Appt% | Rev/lead |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Google** | £615.6k | 8,427 | 2,199 | 618 | £2.04M | £73 | £280 | £996 | **3.31** | 12.0 | 26.1 | £245 |
| **Meta** | £213.3k | 7,192 | 1,166 | 238 | £0.82M | £30 | £183 | £896 | **3.82** | 17.6 | 16.2 | £113 |
| **Bing** | £60.6k | 683 | 185 | 72 | £0.23M | £89 | £328 | £841 | **3.85** | 10.0 | 27.1 | £341 |

\* Sold/revenue = email-matched Unleashed orders within 180 days of the lead (87% join coverage).

**The channels have different jobs**: Google/Bing find high-intent searchers (26–27% appt rate,
£245–341 revenue per lead); Meta manufactures cheap demand (16% appt rate, £113/lead) — but on a
**revenue-per-£-spent** basis all three now sit in a 3.3–3.9 band, with Google *worst*. Meta leads
being "lower quality" is priced in and then some.

## Trend narrative — where it broke

1. **Golden era, Aug 2024 – Feb 2025:** blended CPL £25–46, cost/appt £129–185, Google ROAS 5.3–5.8.
2. **Break #1 — March 2025:** spend pushed £50k→£74k/month **into the seasonal demand dip**
   (March is a weak month — see seasonality). CPL jumped to £46, cost/appt to £246. Efficiency
   never returned to January levels.
3. **Plateau, Jul–Dec 2025:** stabilised at CPL £42–57, cost/appt £203–263.
4. **Break #2 — March 2026:** same mistake, bigger: spend £79k→£92k (highest ever) into the
   same seasonal dip. CPL £87, cost/appt £354. Q2-2026 Google CPL hit **£115** (was £33 six
   quarters earlier — 3.5×).
5. **Now:** weekly data (12 recent weeks) shows no *acute* cliff — the damage is structural,
   not a live incident. Blended cost/appt is stuck at ~£315.

**Root pattern:** both step-changes coincide with **raising Google budget into falling seasonal
demand**, and holding it there. Google absorbed the extra money at sharply diminishing returns
(its share of paid spend rose from 59% in Q4-2024 to **78% in Q1-2026** — the mix drifted *toward*
the decaying channel — while Meta, the improving channel, was cut from £65k to £44–49k/quarter).

## Seasonality profile (for the budget model)

Average monthly lead volume across both years: **peak Sep–Nov (1,800–1,980) and Jan (2,020);
troughs Jul (740 — the deepest) and Dec (1,150); March–June flat ~1,350.**
Practical rule the data supports: *scale budgets up from late August, hold through November,
taper December, spike January, then reduce from February — never raise spend in March.*
Current July slump = deepest seasonal trough × structurally-degraded CPL, compounding.

## Campaign winners & losers (Google, platform-tracked conversions, 12 mo)

Full ranking: `data/phase2_google_campaign_rank.csv`. Account median cost/conversion **£132**.

- 🔴 **Systematic loser: regional SEARCH campaigns** — Yorkshire £2,707/conv, Midlands £1,392,
  South West £684, Northern £610 (tiny volume, terrible economics). Regional **Pmax** works
  (£129–170) — the regional *idea* is fine, the Search execution isn't.
- 🔴 Pmax REGION Wales £385/conv — worst Pmax region.
- 🟢 Winners: Branded Search £46, competitor campaign £33, "[Out] Pmax" variants £49–86,
  Pmax GENERAL £92 at £138k scale.
- **Direct waste estimate: ~£19.7k/yr** (campaigns ≥2× median or zero-conv) **+ £5.9k on a Meta
  campaign literally named "TEST [OFF]"** ≈ **£26k/yr**, before the much larger opportunity cost
  of the Google-heavy mix (reallocating Google's worst £100k toward Meta at current marginal
  ROAS ≈ +£50–90k revenue/yr — directional, Phase 5 will refine).

## Yorkshire assessment — the myth corrected

There is no "4,000-lead Yorkshire campaign" (Phase 1). Reality, last 12 months: ~£23.2k
region-named spend (Google £22.9k, Meta £0.3k), **1,340 Yorkshire-region leads, 354 appointments
(26.4% — above account average)**. Yorkshire Pmax is mid-table (£168/conv); Yorkshire *Search* is
the single worst campaign in the account (kill it). Yorkshire as a market: healthy, converts well
(35% of appointments → sales, best in the earlier regional work). **Not a problem region.**
The real Yorkshire issue is the *geo-data gap* (80% of its leads geo-blank — Phase 1), which is a
tagging fix, not a marketing fix.

## Tagging/data gaps found this phase (feed Phase 5 register)

- **UTM tagging is broken**: top "campaign" value is `/url` (5,530 leads/yr); the rest is
  fragmented snake_case tokens that don't match campaign names → campaign-level lead-CPA is
  currently unmeasurable. One UTM-template fix makes the whole campaign layer analysable.
- gclid capture halved since Feb 2025 (Phase 1) — same family of tracking decay.
