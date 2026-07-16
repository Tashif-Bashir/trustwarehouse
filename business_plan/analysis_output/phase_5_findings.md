# Phase 5 Findings — Cross-Cutting Synthesis: What Is Going Wrong (and Right)

Run date: 16 Jul 2026 · Integrates Phases 0–4; every claim traces to a findings file + query.

---

## The one-paragraph diagnosis

The business's *selling* machine is healthy — conversion improving at every human stage, margins
stable, revenue still level. What broke is the *feeding* of that machine: lead costs roughly
doubled after two mistimed budget escalations concentrated money in a saturating Google account,
while ~a quarter of the leads that were bought were never called, evening/weekend demand goes
unworked, and H1-2026 quietly lost several proven closers. Revenue hasn't fallen yet because the
funnel runs on a ~3–6-week lag and the team's conversion gains absorbed the damage — **Aug–Oct
2026 is when the lead drought lands in the bank account unless the input side is fixed now.**

## Problem register (ranked by £ impact × confidence)

| # | Problem | Evidence | Est. £ impact | Conf. | Root cause (vs symptom) |
|---|---|---|---|---|---|
| 1 | **Marketing efficiency collapse** — blended CPL £25–46 → £76–87; CAC ×2 | P2: two March step-changes; Google share 59→78% while its ROAS 5.8→2.7; Meta (stable/improving) cut | **£40–60k/quarter** excess acquisition cost vs 2025 efficiency; £50–90k/yr revenue reallocation upside | HIGH | Budget *process*: raising spend into seasonal troughs with no marginal-return guardrail; channel-mix drift toward the saturating channel. Rising CPL is the symptom. |
| 2 | **Never-called / coverage gap** — 18.5% of phone-bearing leads (~3,400/yr) have a *valid, unmarked* number and never get dialled (~30% in winter peak; invalid numbers & team-marked 'No Number' excluded); zero dialing after 17:00 vs ~30% out-of-hours arrivals; median first call 11–15h | P3 speed/ops tables + `phase3_nevercalled_validation.py` | Recovering half the gap ≈ **+150–300 appts/yr ≈ £150–300k revenue** | HIGH (gap) / MED (uplift) | Capacity + shift design, not effort — in-hours response is a 1-minute median. |
| 3 | **Closer churn H1-2026** — Shane, Chris, Sachin, Ambivo gone/faded; Rob (top-5) inactive since Apr | P3 rep consistency table | ~40–50 sales/mo of proven capacity off the books (~£120–150k/mo gross), partially offset by ramping hires | MED-HIGH | Unknown from data — retention/recruiting question for the owner. Compounds problem 1's revenue lag. |
| 4 | **Possible inbound answering leak** — answer rate reads 50.6% under Ascend (was 90%+); ~200 calls/wk dying in IVR | P3 ops; measurement-confounded (system change) | If even half real: **£10k+/week** at stake | LOW until verified | Needs a physical IVR/queue check — *the highest-value 1-hour verification in this report*. |
| 5 | **Warm-lead limbo** — 2,440 reached-but-unresolved "Follow Up" leads (12mo) + 333 cancelled appointments unrebooked | P3 funnel; earlier diary work | 5–10% conversion on re-work ≈ **£50–150k/yr**, near-zero cost | HIGH | Process: no follow-up SLA/ownership; statuses now degrading too (blank-status spike Jun–Jul). |
| 6 | **Funnel hygiene regression** — reached% 58–62% in Jun–Jul (norm 72–81%); blank statuses 10%+ | P1/P3 | Amplifies 1–5; masks true performance | HIGH | Symptom — of capacity strain + slipping discipline; cheap to reverse with a working rule. |
| 7 | **Tracking decay** — UTM template broken (`/url`), gclid capture halved, postcode capture falling | P1/P2 | Blocks campaign-level optimisation (enabler) | HIGH | Tag-template fix + form fields; not a spend problem. |
| 8 | Internal data issues — PO pagination cap, silver-Bing −18% bug, gold status bug | P0/P1 | Analysis reliability | HIGH | Pipeline fixes, all small. |

**Symptom→cause mapping:** "CPL rising" (symptom) ← budget-into-trough process + mix drift (causes).
"Empty diaries" (symptom) ← lead volume (1) + deepest seasonal trough + coverage (2) + churn (3).
"Revenue about to soften" (symptom) ← all of the above on a 3–6-week lag.

## Top 5 issues — what/why/confirm/act

1. **Marketing efficiency** — *Act:* cap Google at demonstrated-marginal-ROAS level (~£35–40k/mo),
   restore Meta to ~£20k/mo, kill regional-Search campaigns (+TEST), fix UTM template. Re-scale
   budgets to the seasonality curve (up from late Aug, never up in March). *Confirm:* 4-week CPL
   after rebalance.
2. **Coverage** — *Act:* auto-SMS on out-of-hours arrival, Saturday-morning + one evening shift
   pilot, never-called daily worklist (the warehouse can generate it). *Confirm:* called-within-24h
   ≥95%, never-called <5%.
3. **Closer capacity** — *Act:* owner conversation on Rob & leavers; ramp plan + appointment-
   attendance tracking (booking app now records it) so close-rates become measurable. *Confirm:*
   sat-appointments/week restored to spring levels.
4. **Inbound leak** — *Act THIS WEEK:* test-call the IVR, review queue config & Ascend answered
   semantics; then instrument an answered-by-human metric. *Confirm:* true answer rate ≥90%.
5. **Warm-lead recovery** — *Act:* rebooking blitz (333 cancelled), Follow-Up SLA (7-day),
   re-work queue from the warehouse. *Confirm:* Follow-Up stock ↓50% in 6 weeks.

## Top 5 strengths (protect / scale)

1. **Conversion machine improving at every stage** — lead→appt 19%→26%+, appt→sale steady ~27–32%,
   velocity ~2–3 weeks. Do not "fix" the sales team.
2. **Margins are excellent and stable** (60–66% GM) and **Water Heating (82% GM)** is a
   high-margin growth line worth pushing in every appointment.
3. **In-hours responsiveness is world-class** (1-minute median first call) — the machine works
   when it's staffed; that's why extending coverage is high-confidence.
4. **Yorkshire/North-East heartland**: best conversion + biggest revenue cluster (~£450k/yr) —
   the regional playbook to replicate (and the "Yorkshire problem" is officially dead).
5. **Rep bench depth**: top-2 revenue concentration only 22% — no key-person cliff; and the data
   estate (60-sec call sync, clean bronze, booking-app audit trail) now supports weekly
   operational steering.

## Data gaps blocking better answers (priority order)

1. UTM template fix (unlocks campaign-level CPA) — hours of work.
2. Inbound answered-by-human telemetry (post-IVR) — config + one dashboard metric.
3. Appointment-attendance per rep (booking app records from Jun 2026 — keep; enables close-rates).
4. Geo capture at source (postcode field mandatory on forms; capture area on inbound calls).
5. gclid capture regression — investigate tag manager.
6. Purchase-orders pagination fix (unlocks COGS/inbound analysis).
7. CRM picklist hygiene (booked-by names; retire "*Dont Use*" product group).
8. Aug–Dec 2025 sheet tabs (if they exist) + 'Parked' order ruling from ops.
