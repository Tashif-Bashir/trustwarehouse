"""Phase 6.2 — headline trend charts from the phase CSVs."""
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data'
CH = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\charts'
INK, SLATE, EMBER, GOOD, LIGHT = "#20262E", "#5B6572", "#D4551E", "#1A7A5A", "#C9CFD6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": LIGHT, "axes.grid": True, "grid.color": "#EEF0F2",
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 13, "axes.titleweight": "bold",
})

def style(ax, title):
    ax.set_title(title, loc="left", color=INK, pad=12)
    ax.tick_params(colors=SLATE)
    ax.set_xlabel("")

# 1. blended CPL & cost per appointment
b = pd.read_csv(DATA + r'\phase2_blended_monthly.csv')
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(b.month, b.cpl, color=EMBER, lw=2.5, marker="o", ms=3, label="Cost per lead")
ax2 = ax.twinx()
ax2.plot(b.month, b.cpa, color=SLATE, lw=2, marker="o", ms=3, label="Cost per appointment")
ax2.spines.top.set_visible(False)
ax.axvline(x=list(b.month).index("2025-03"), color=LIGHT, ls="--")
ax.axvline(x=list(b.month).index("2026-03"), color=LIGHT, ls="--")
ax.text(list(b.month).index("2025-03") + 0.1, ax.get_ylim()[1]*0.95, "Mar-25 budget push", fontsize=8, color=SLATE)
ax.text(list(b.month).index("2026-03") + 0.1, ax.get_ylim()[1]*0.87, "Mar-26 budget push", fontsize=8, color=SLATE)
ax.set_xticks(range(0, len(b), 3))
ax.set_xticklabels(b.month[::3], rotation=45, ha="right")
ax.set_ylabel("£ per lead", color=EMBER)
ax2.set_ylabel("£ per appointment", color=SLATE)
style(ax, "Paid lead costs — the two March step-changes (blended: Google+Meta+Bing)")
fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.92), frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(CH + r'\1_cost_per_lead_appointment.png', dpi=150)

# 2. Google share of spend vs Google ROAS (quarterly)
m = pd.read_csv(DATA + r'\phase2_monthly_platform.csv')
m = m[m.platform.isin(["Google", "Meta", "Bing"])].copy()
m["q"] = m.month.str[:4] + "-Q" + ((m.month.str[5:7].astype(int) - 1) // 3 + 1).astype(str)
qs = m.groupby(["q", "platform"]).agg(spend=("spend", "sum"), revenue=("revenue", "sum")).reset_index()
piv = qs.pivot(index="q", columns="platform", values="spend").fillna(0)
share = (piv["Google"] / piv.sum(axis=1) * 100)
g = qs[qs.platform == "Google"].set_index("q")
roas = g.revenue / g.spend
q_idx = [x for x in share.index if x < "2026-Q3"]
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.bar(q_idx, share[q_idx], color=LIGHT, label="Google share of paid spend (%)")
ax2 = ax.twinx()
ax2.plot(q_idx, roas[q_idx], color=EMBER, lw=2.5, marker="o", label="Google ROAS (rev ÷ spend)")
ax2.spines.top.set_visible(False)
ax.set_ylabel("share of paid spend %", color=SLATE)
ax2.set_ylabel("ROAS", color=EMBER)
style(ax, "The mix drifted toward Google exactly as Google's return fell")
fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.92), frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(CH + r'\2_google_share_vs_roas.png', dpi=150)

# 3. funnel: leads + appointment rate monthly
f = pd.read_csv(DATA + r'\phase3_funnel_monthly.csv')
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.bar(f.month, f.leads, color=LIGHT, label="Leads")
ax2 = ax.twinx()
ax2.plot(f.month, f.appt_pct, color=GOOD, lw=2.5, marker="o", label="Lead → appointment %")
ax2.plot(f.month, f.reached_pct, color=SLATE, lw=1.5, ls="--", label="Reached %")
ax2.spines.top.set_visible(False)
ax.set_xticks(range(0, len(f), 3))
ax.set_xticklabels(f.month[::3], rotation=45, ha="right")
ax.set_ylabel("leads", color=SLATE)
ax2.set_ylabel("%", color=GOOD)
style(ax, "Lead volume collapsed; the team's conversion kept climbing")
fig.legend(loc="upper right", bbox_to_anchor=(0.92, 0.92), frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(CH + r'\3_funnel_volume_vs_conversion.png', dpi=150)

# 4. CAC and marketing % of revenue
c = pd.read_csv(DATA + r'\phase4_cac_monthly.csv')
c = c[c.month >= "2025-02"]  # drop Jan-25 backlog artefact
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(c.month, c.blended_cac, color=EMBER, lw=2.5, marker="o", label="Blended CAC (£/new customer)")
ax2 = ax.twinx()
ax2.plot(c.month, c.mkt_pct_of_revenue, color=SLATE, lw=2, marker="o", label="Marketing % of revenue")
ax2.spines.top.set_visible(False)
ax.set_xticks(range(0, len(c), 2))
ax.set_xticklabels(c.month[::2], rotation=45, ha="right")
ax.set_ylabel("£", color=EMBER)
ax2.set_ylabel("%", color=SLATE)
style(ax, "Customer acquisition cost has roughly doubled in a year")
fig.legend(loc="upper left", bbox_to_anchor=(0.08, 0.92), frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(CH + r'\4_cac_and_marketing_pct.png', dpi=150)

# 5. revenue & orders monthly
r = pd.read_csv(DATA + r'\phase4_revenue_monthly.csv')
r = r[r.month >= "2025-02"]
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.bar(r.month, r.revenue_exvat / 1000, color=LIGHT, label="Revenue £k (ex-VAT)")
ax2 = ax.twinx()
ax2.plot(r.month, r.orders, color=EMBER, lw=2.5, marker="o", label="Orders")
ax2.spines.top.set_visible(False)
ax.set_xticks(range(0, len(r), 2))
ax.set_xticklabels(r.month[::2], rotation=45, ha="right")
ax.set_ylabel("£k", color=SLATE)
ax2.set_ylabel("orders", color=EMBER)
style(ax, "Revenue holding so far — the funnel lag means Aug–Oct is the test")
fig.legend(loc="upper right", bbox_to_anchor=(0.92, 0.92), frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(CH + r'\5_revenue_orders.png', dpi=150)

print("charts written: 5")
