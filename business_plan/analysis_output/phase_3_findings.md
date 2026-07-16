# Phase 3 Findings — Sales Funnel, Operations & Rep Performance

Run date: 16 Jul 2026 · Queries: `queries/phase3_*.py` · Data: `data/phase3_*.csv`
Caveats: C4 (call data from May 2025), C5 (rep attribution weakest Aug–Dec 2025), 180-day sale
window censors the most recent ~4 months of appt→sale rates.

---

## 3A.1 The funnel (lead → reached → appointment → sale)

Last-12-months shape (paid channels): **100 leads → ~74 reached → ~21 appointment → ~5.5 sold.**

- **Largest drop-off: reached → appointment (~72% of conversations don't book).** Within that,
  the biggest recoverable block is **"Follow Up" limbo — 2,440 reached-but-unresolved leads in
  12 months** (second only to "Not Interested" 3,166). These are warm conversations nobody closed out.
- **Reached% collapsed in Jun–Jul 2026 to 58–62%** (norm 72–81%) — corroborates the Phase 1
  blank-status spike: leads are leaving the funnel *unworked*, exactly when lead volume is scarcest.
- Appointment rate per lead is **rising** (26%+ in 2026 vs ~19% in 2024) — conversion skill is not
  the problem.
- Appt→sale is stable at **25–32%** through the last reliably-measurable period (to Feb 2026);
  later months are window-censored, not yet judgeable. **No evidence of closing deterioration.**
- Meta's funnel is structurally shallower at every stage (reached 65–75% vs Google 77–81%;
  reached→appt 15–25% vs 25–43%) — priced into Phase 2 economics.

## 3A.4 Velocity

Median lead→sale is **~15–19 days** (2025-H2 onward, stable; Q2-2026 12.5d is recency-biased).
The apparent 2024 slowness (53–112d medians) is the **Unleashed adoption artefact** (orders keyed
months late), not real pipeline speed. **Pipeline is not slowing down.**

## 3A.2 Speed-to-lead — the big operational finding

Distribution (leads with phones, Jun 2025 – Jul 2026; first outbound call matched by number):

- **Median time to first call: 11–15 hours** (663–937 min) every single month.
  p90: **3–6 days**. Only **21–31% called within 10 minutes** (company target: ≤5 min average).
- **The never-called block: ~25% of leads got no dial within 14 days.** Worse in the winter peak —
  **Nov 2025–Mar 2026 ran at 60–72% called** (i.e. up to 40% never attempted) while volume was high;
  recovered to 87–90% in May–Jul 2026 as volume collapsed. **This is a capacity ceiling, measured.**
- Conversion by speed bucket surprises: ≤10min 23.4%, >24h 27.5%, never-called 15.1%. The >24h
  bucket outperforming is confounded (callbacks/self-selected engaged leads book late) — the clean,
  honest claim is: **any call beats no call by ~8–12 points of appointment rate**, and a quarter of
  leads get no call. Eliminating never-called is worth far more than shaving minutes off the fast calls.

## 3A.3 Call operations & coverage

- **Dialing happens 08:00–16:59 only** (verified: zero dials outside). **~30% of leads arrive
  17:00–07:00** + weekends — they wait overnight minimum (ties to the Meta out-of-hours analysis:
  70% of Meta leads arrive out of hours).
- **Inbound answer rate: 90–99% under Wildix; July 2026 shows 50.6% under Ascend.** Part
  measurement change (Ascend logs IVR-abandoned calls as separate unanswered records; Wildix's
  answered flag was a talk-time proxy on merged legs) — **but an independent check found ~197
  inbound calls/week dying in the auto-attendant**. 🔴 URGENT: verify operationally (listen to the
  IVR flow, check queue config). If even half is real, inbound demand is leaking at the reception desk.
- Outbound volume dropped from ~8–9k dials/month (2025-H2) to ~6.5k (Jun 2026) and July pacing ~6k —
  fewer leads to dial, and (below) fewer people dialing.

## 3B Rep performance

### Field reps (closers) — from sales sheets, Jul 2025 + Jan–Jul 2026 (n ≥ 10 sales)

| Rep | Sales | Revenue | AOV | Share |
|---|---:|---:|---:|---:|
| Kelly | 87 | £321k | £3,694 | 12.5% |
| Kris | 67 | £250k | £3,733 | 9.7% |
| Niall | 68 | £243k | £3,578 | 9.4% |
| SamC | 71 | £223k | £3,138 | 8.6% |
| Rob | 72 | £215k | £2,980 | 8.3% |
| (13 more ≥£29k…) | | | | |

- **Revenue concentration is healthy**: top-2 reps = 22% of revenue — no key-person cliff.
- **But H1-2026 churn is severe and under-recognised**: Shane (12–13 sales/mo) gone after Feb;
  Chris gone after Mar; Sachin faded Apr; Ambivo stopped Jun; **Rob — a top-5 producer at 15–17
  sales/mo — has 1 sale since April.** Replacements (ChrisM, Paul, Samuel, Scott, Samantha-ramp)
  started Apr–Jun and are still ramping. **The business lost ~40–50 sales/month of proven closer
  capacity during H1 2026** — this compounds the lead drought in explaining the sales slowdown risk.
- AOV spread £2.5k–£4.7k (Paul, Lucy highest; worth a look at what they sell/quote).
- ⚠ **Close-rate per rep is not computable** — appointments *attended* per rep are recorded nowhere
  structured (booking app captures it only from Jun 2026 onward). Data gap → measurement plan.
- Fairness note per plan: no lead/appointment assignment data exists per rep pre-Jun-2026, so
  channel-mix normalisation is impossible; table above is volume/revenue only, NOT a skill ranking.

### Telesales agents — unified calls + CRM booked-by, last 12 months (n ≥ 1,000 dials)

| Agent | Dials | Conversations (≥30s) | Talk hrs | Appts booked | Appts/100 conv |
|---|---:|---:|---:|---:|---:|
| Lily | 15,117 | 3,585 | 156 | 790 | 22.0 |
| Alicja | 15,791 | 4,714 | 287 | 703 | 14.9 |
| Alisha | 10,185 | 3,126 | 140 | 348 | 11.1 |
| Sue | 16,151 | 9,235 | 312 | *unmapped* | — |
| Dec | 12,329 | 4,147 | 271 | *unmapped* | — |

- Lily and Alicja carry the booking load (~1,500 appointments between them in 12 months).
- Sue's numbers are striking — highest dials AND a 57% conversation rate (everyone else 24–34%) —
  she clearly works callback/warm lists; her bookings don't map because of **booked-by picklist
  name mismatches** (same for Dec/Lucy/Helen) — a 10-minute CRM picklist tidy-up fixes the metric.
  ⚠ Do NOT read the blank as zero bookings.
- Roles differ (cold vs callback vs inbound) — cross-agent ranking on one metric would be unfair;
  the actionable pattern is Lily's 22/100 vs Alicja's 14.9/100 *on broadly similar roles* — worth
  understanding what differs (list mix? pitch?) as coaching input, per plan 3B.6.

## The constraint statement (plan 3 deliverable)

**The constraint is not sales execution.** Conversion is improving at every human stage
(lead→appt 26%, appt→sale steady ~27–32%, velocity ~2–3 weeks and stable). The constraints are,
in order:
1. **Lead volume** (Phase 2: −31% YoY at +19% spend), and
2. **Working capacity/coverage**: 25% of leads never called (40% in the winter peak), zero dialing
   after 17:00 against ~30% out-of-hours arrivals, a possible inbound-answering leak, 2,440 leads
   parked in Follow-Up limbo — plus **a wave of closer churn in H1 2026** that removed ~40–50
   sales/month of sat capacity while it ramps replacements.
