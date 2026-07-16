# Phase 4 Findings — Financial Analysis

Run date: 16 Jul 2026 · Queries: `queries/phase4_financial.py` · Data: `data/phase4_*.csv`
Sources per Phase 0 verdict: Unleashed ex-VAT (Jan 2025+); sheets for 2024 & H1-2025 *timing*
cross-checks. Caveats: C6 (Parked excluded), Jan-2025 Unleashed backlog hump, purchase-order data RED.

---

## 4.1 Revenue trend — level, not (yet) falling

- Steady-state monthly revenue (Unleashed, ex-VAT): **£250k–580k/month**, strong seasonality
  (Nov peak £577k; May trough £200–250k).
- **H1 2026 vs H1 2025:** Unleashed says −11%, but Jan-2025 carries the adoption-backlog hump;
  the sheets (deposit-dated, like-for-like) say **+13%** (£2.28M vs £2.02M, VAT-mixed).
  Honest verdict: **H1 revenue is level to modestly up.** The lead crisis has not reached
  revenue yet — it will from ~Aug/Sep given the 15–19-day lead→sale lag plus the appointment
  slump (July orders pacing ~£135k/2wks confirms softening has begun).
- July 2026 (partial) is pacing at the low end even for the seasonal trough.

## 4.2 Order economics — mix of both, mildly

- Orders/month: ~156 avg (H2 2025) → ~142 (H1 2026): −9%.
- AOV: dipped to £2.5–2.6k (Oct 2025–Mar 2026), recovered to £3.1–3.5k (Apr–Jun 2026).
- Neither has collapsed; the revenue risk is pipeline-lagged, not current-order-driven.

## 4.3 Product performance & margin

| Product group | Revenue (Jan 25–Jun 26) | Gross margin |
|---|---:|---:|
| Radiators — integrated thermostat | **£5.44M (≈80%)** | 60–66%, dipped H2-25, recovered |
| Radiators — wireless thermostat | £0.98M | 63–67% |
| Services/install lines ("ungrouped") | £0.99M | no cost data — margin not measurable |
| **Water Heating** (new, 2026-H1) | **£113k** | **82%** — highest-margin line, growing |
| Thermostats / accessories | ~£140k | 58–64% |

- Margin is **healthy and stable** — no margin-compression problem. The H2-2025 dip (59.8%)
  self-corrected (65.6% in 2026-H1).
- **Water Heating is the standout strategic line**: small but 82% GM — every water appointment
  the telesales push generates is disproportionately profitable.
- Hygiene: a product group literally named "*Dont Use*" took £24k of orders in 2025-H1 (tidy-up).

## 4.4 Marketing payback — the clearest deterioration signal

| Period | Blended CAC (paid spend ÷ new customers) | Marketing % of revenue |
|---|---:|---:|
| 2025 steady-state (Jul–Dec) | **£373–614** | **11–22%, avg ~15%** |
| 2026 H1 | **£607–1,055** | **16–29%, avg ~21%** |

- **CAC has ~doubled year-on-year.** At AOV ~£3.1k and ~63% GM (~£1,950 gross profit/order),
  CAC has gone from ~25% to ~45% of first-order gross profit. Still profitable per order —
  but the headroom halved in 12 months, entirely driven by the Phase-2 lead-cost explosion.
- Marketing-%-of-revenue trending ~20%+ where it ran ~12–15% a year ago.

## 4.5 Geographic revenue

Delivery-postcode coverage of revenue: **96.6%** (far better than lead geo!). Top areas last 12
months: NE £162k, YO £150k, LS £132k (the Yorkshire/North-East cluster ≈ £450k+ is the revenue
heartland — consistent with Yorkshire's strong conversion), then B £119k, RG £109k, NR £107k,
EX+TR (South West) £191k combined. External under-indexing comparison (ONS/EPC/fuel-poverty)
not possible — those datasets aren't in the warehouse (logged as data gap; candidate enrichment).

## 4.6 Inventory signals

Effectively a **build-to-order** operation: finished-radiator stock ≈ £8k (28 units); the ~£126k
holding is components/sheet metal. Zero stale-stock problem (1 SKU >180d, £170). Stock-out *risk*
on fast movers cannot be assessed — purchase-order data is RED (capped) and lead times unknown.
**Inventory is not a financial concern**; skip until the PO pipeline is fixed.

## Top financial concerns (quantified, feed Phase 5)

1. **CAC ×2 YoY** (£~500 → £~950 recent months) — £ impact: at current volumes ≈ **£40–60k/quarter
   of extra acquisition cost** vs 2025 efficiency for the same customer count.
2. **Revenue softening is arriving on a lag** — July pacing low; Aug–Oct at risk from the
   appointment slump + closer churn (Phase 3).
3. Marketing % of revenue >20% and rising — unsustainable direction if CPL isn't fixed.
4. (Positive) margins stable, water line highly profitable, no inventory drag, revenue-per-order healthy.
