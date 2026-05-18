import os
from datetime import date, timedelta

import duckdb
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── PALETTE ───────────────────────────────────────────────────────────────────
BG     = "#070c18"
BG2    = "#0d1426"
GOLD   = "#d4a843"
GOLD_L = "#f0c870"
WHITE  = "#c8d4f0"
DIM    = "#4a6080"
BORDER = "#1a2540"

GOOGLE = "#4285f4"
META   = "#a855f7"
BING   = "#f59e0b"
PC     = {"Google": GOOGLE, "Meta": META, "Bing": BING}
FILL   = {
    "Google": "rgba(66,133,244,0.07)",
    "Meta":   "rgba(168,85,247,0.07)",
    "Bing":   "rgba(245,158,11,0.07)",
}

CHART = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'Nunito Sans',sans-serif", color=WHITE, size=12),
    margin=dict(t=60, b=20, l=10, r=10),
    xaxis=dict(gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
    yaxis=dict(gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, bgcolor="rgba(0,0,0,0)", font=dict(color=DIM)),
    title_font=dict(family="'Playfair Display',serif", size=20, color=GOLD),
    hoverlabel=dict(bgcolor=BG2, bordercolor=GOLD,
        font=dict(family="'Nunito Sans',sans-serif", color=WHITE)),
)

# ── PAGE ──────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Marketing Intelligence", page_icon="💰", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&family=Nunito+Sans:wght@300;400;600;700&family=DM+Mono:wght@400;500&display=swap');

html,body,.stApp,[data-testid="stAppViewContainer"]{{background-color:{BG}!important;color:{WHITE}!important;font-family:'Nunito Sans',sans-serif!important}}
[data-testid="stAppViewContainer"]{{background-image:
  radial-gradient(ellipse 60% 50% at 80% 10%,rgba(212,168,67,0.07) 0%,transparent 70%),
  radial-gradient(ellipse 40% 30% at 10% 90%,rgba(66,133,244,0.04) 0%,transparent 60%)}}
.block-container{{padding:1rem 2.5rem 2rem!important;max-width:100%!important}}
#MainMenu,footer,header{{visibility:hidden}}

.mhdr{{padding:2rem 0 1.5rem;border-bottom:1px solid {BORDER};margin-bottom:1.5rem}}
.mhdr-eye{{font-family:'DM Mono',monospace;font-size:.62rem;letter-spacing:5px;color:{GOLD};opacity:.65;text-transform:uppercase;margin-bottom:6px}}
.mhdr-title{{font-family:'Playfair Display',serif;font-size:3.2rem;font-weight:700;font-style:italic;color:{WHITE};line-height:1.1;margin:0 0 4px}}
.mhdr-title span{{color:{GOLD};font-style:normal}}
.mhdr-rule{{height:1px;background:linear-gradient(90deg,{GOLD} 0%,{META} 33%,{GOOGLE} 66%,transparent 100%);margin-top:1.5rem;opacity:.35}}

.skpi{{background:{BG2};border:1px solid {BORDER};border-left:3px solid var(--a,{GOLD});border-radius:4px;padding:20px 18px;height:100%}}
.skpi-lbl{{font-family:'DM Mono',monospace;font-size:.58rem;letter-spacing:4px;color:{DIM};text-transform:uppercase;margin-bottom:10px}}
.skpi-val{{font-family:'Playfair Display',serif;font-size:2.4rem;font-weight:700;color:var(--a,{WHITE});line-height:1}}
.skpi-sub{{font-family:'DM Mono',monospace;font-size:.62rem;color:{DIM};margin-top:8px;letter-spacing:1px}}

.pb{{display:inline-block;padding:2px 10px;border-radius:3px;font-family:'DM Mono',monospace;font-size:.68rem;letter-spacing:2px;font-weight:500;text-transform:uppercase}}
.pb-g{{background:rgba(66,133,244,.12);color:{GOOGLE};border:1px solid rgba(66,133,244,.25)}}
.pb-m{{background:rgba(168,85,247,.12);color:{META};border:1px solid rgba(168,85,247,.25)}}
.pb-b{{background:rgba(245,158,11,.12);color:{BING};border:1px solid rgba(245,158,11,.25)}}

.msec{{font-family:'Playfair Display',serif;font-size:1.05rem;font-weight:600;font-style:italic;color:{GOLD};margin:1.2rem 0 .7rem;opacity:.85}}

button[role="tab"]{{font-family:'Nunito Sans',sans-serif!important;font-size:.88rem!important;font-weight:700!important;letter-spacing:2px!important;color:{DIM}!important;text-transform:uppercase!important;border:none!important;background:transparent!important}}
button[role="tab"][aria-selected="true"]{{color:{GOLD}!important;border-bottom:2px solid {GOLD}!important}}
button[role="tab"]:hover{{color:{WHITE}!important}}

hr{{border:none!important;border-top:1px solid {BORDER}!important;margin:1.4rem 0!important}}

[data-testid="stButton"]>button{{background:transparent!important;border:1px solid {BORDER}!important;color:{DIM}!important;font-family:'Nunito Sans',sans-serif!important;font-size:.85rem!important;font-weight:700!important;letter-spacing:2px!important;border-radius:3px!important;transition:all .2s!important}}
[data-testid="stButton"]>button:hover{{border-color:{GOLD}!important;color:{GOLD}!important;background:rgba(212,168,67,.05)!important}}
[data-testid="stSelectbox"] > div > div{{background:{BG2}!important;border:1px solid {BORDER}!important;color:{WHITE}!important;border-radius:3px!important}}
[data-testid="stDateInput"] input{{background:{BG2}!important;border:1px solid {BORDER}!important;color:{WHITE}!important;border-radius:3px!important}}
[data-testid="stDataFrame"]{{border:1px solid {BORDER}!important;border-radius:4px!important}}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _connect():
    return duckdb.connect(f"md:trust-pipeline?motherduck_token={os.getenv('MOTHERDUCK_TOKEN','')}")

def skpi(label, value, sub=None, accent=None):
    a = accent or GOLD
    sh = f'<div class="skpi-sub">{sub}</div>' if sub else ""
    return f'<div class="skpi" style="--a:{a}"><div class="skpi-lbl">{label}</div><div class="skpi-val">{value}</div>{sh}</div>'

@st.cache_data(ttl=1800, show_spinner="Loading attribution data…")
def load_attr(d0, d1):
    con = _connect()
    df = con.execute(f"""
        SELECT * FROM gold.gold_campaign_attribution
        WHERE date BETWEEN '{d0}' AND '{d1}'
        ORDER BY date DESC, spend_gbp DESC
    """).df()
    con.close()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading lead breakdown…")
def load_customer_types(d0, d1):
    con = _connect()
    df = con.execute(f"""
        SELECT
            coalesce(m.platform, 'Other Paid') as platform,
            coalesce(g.customer_type, 'Unknown') as customer_type,
            count(*) as leads
        FROM gold.gold_lead_activity g
        INNER JOIN silver.campaign_platform_mapping m ON g.campaign_id = m.campaign_id
        WHERE g.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1, 2
        ORDER BY 1, 3 DESC
    """).df()
    con.close()
    return df

# ── PERIOD SELECTOR ───────────────────────────────────────────────────────────

PRESETS = ["Last 7 Days", "Last 30 Days", "This Month", "Last 7 Working Days",
           "This Week", "Yesterday", "Today", "Custom"]

def _working_range(n):
    days, d = [], date.today() - timedelta(1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(1)
    return days[-1], days[0]

today = date.today()
yesterday = today - timedelta(1)

PRESET_DATES = {
    "Today":               (today, today),
    "Yesterday":           (yesterday, yesterday),
    "Last 7 Days":         (yesterday - timedelta(6), yesterday),
    "This Week":           (today - timedelta(today.weekday()), yesterday),
    "Last 7 Working Days": _working_range(7),
    "This Month":          (today.replace(day=1), yesterday),
    "Last 30 Days":        (today - timedelta(30), yesterday),
}

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="mhdr">
  <div class="mhdr-eye">Trust Electric Heating &nbsp;/&nbsp; Paid Media Intelligence</div>
  <h1 class="mhdr-title">Ad Performance <span>&amp; Attribution</span></h1>
  <div class="mhdr-rule"></div>
</div>
""", unsafe_allow_html=True)

hl, hm, hn, hr_ = st.columns([2, 2, 2, 2])
with hl:
    preset = st.selectbox("Period", PRESETS, index=0, label_visibility="collapsed")

if preset == "Custom":
    with hm:
        d0 = st.date_input("From", value=today - timedelta(30), max_value=today,
            label_visibility="collapsed", key="m_from")
    with hn:
        d1 = st.date_input("To", value=today - timedelta(1), max_value=today,
            label_visibility="collapsed", key="m_to")
else:
    d0, d1 = PRESET_DATES[preset]

with hr_:
    mc1, mc2 = st.columns([1, 2])
    with mc1:
        if st.button("↺ REFRESH", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with mc2:
        st.markdown(
            f'<div style="font-family:\'DM Mono\',monospace;font-size:.65rem;color:{DIM};'
            f'padding-top:12px;letter-spacing:2px">GOLD LAYER · MOTHERDUCK</div>',
            unsafe_allow_html=True)

period = f"{d0.strftime('%d %b')} – {d1.strftime('%d %b %Y')}"
st.markdown(
    f'<div style="font-family:\'DM Mono\',monospace;font-size:.7rem;color:{DIM};'
    f'letter-spacing:2px;margin:.8rem 0 1.4rem">'
    f'PERIOD: {period.upper()} &nbsp;&nbsp;'
    f'<span class="pb pb-g">Google</span> &nbsp;'
    f'<span class="pb pb-m">Meta</span> &nbsp;'
    f'<span class="pb pb-b">Bing</span></div>',
    unsafe_allow_html=True)

df    = load_attr(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))
df_ct = load_customer_types(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))

if df.empty:
    st.warning("No attribution data for selected period.")
    st.stop()

# ── SHARED AGGREGATION ────────────────────────────────────────────────────────
pa = df.groupby("platform").agg(
    spend=("spend_gbp", "sum"),
    clicks=("clicks", "sum"),
    impr=("impressions", "sum"),
    leads=("leads", "sum"),
    appts=("appointments_booked", "sum"),
    sales=("sales", "sum"),
).reset_index()
pa["cpl"]  = (pa["spend"] / pa["leads"].replace(0, float("nan"))).round(2)
pa["cpa"]  = (pa["spend"] / pa["appts"].replace(0, float("nan"))).round(2)
pa["cps"]  = (pa["spend"] / pa["sales"].replace(0, float("nan"))).round(2)
pa["ctr"]  = (pa["clicks"] / pa["impr"].replace(0, float("nan")) * 100).round(3)
pa["l2a"]  = (pa["appts"] / pa["leads"].replace(0, float("nan")) * 100).round(1)
pa["a2s"]  = (pa["sales"] / pa["appts"].replace(0, float("nan")) * 100).round(1)

tot_sp  = pa["spend"].sum()
tot_ld  = int(pa["leads"].sum())
tot_ap  = int(pa["appts"].sum())
tot_sa  = int(pa["sales"].sum())
tot_cl  = int(pa["clicks"].sum())
b_cpl   = tot_sp / tot_ld if tot_ld else 0
b_cpa   = tot_sp / tot_ap if tot_ap else 0
b_cps   = tot_sp / tot_sa if tot_sa else 0

# ── TABS ──────────────────────────────────────────────────────────────────────
t1, t2, t3 = st.tabs(["OVERVIEW", "PERFORMANCE", "PLATFORMS"])

# ═══════════════════════════════════ TAB 1 — OVERVIEW ═════════════════════════
with t1:
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1: st.markdown(skpi("TOTAL SPEND",   f"£{tot_sp:,.0f}",  period, GOLD), unsafe_allow_html=True)
    with k2: st.markdown(skpi("PAID LEADS",    f"{tot_ld:,}",      f"from {tot_cl:,} clicks", WHITE), unsafe_allow_html=True)
    with k3: st.markdown(skpi("APPOINTMENTS",  f"{tot_ap:,}",      f"{tot_ap/tot_ld*100:.0f}% of leads" if tot_ld else "—", WHITE), unsafe_allow_html=True)
    with k4: st.markdown(skpi("SALES",         f"{tot_sa:,}",      f"{tot_sa/tot_ap*100:.0f}% of appts" if tot_ap else "—", GOLD_L), unsafe_allow_html=True)
    with k5: st.markdown(skpi("BLENDED CPL",   f"£{b_cpl:.0f}",   "cost per lead", GOLD), unsafe_allow_html=True)
    with k6: st.markdown(skpi("BLENDED CPS",   f"£{b_cps:.0f}" if tot_sa else "—", "cost per sale", GOLD), unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # Per-platform spend KPIs
    pk = st.columns(len(pa))
    for i, (_, row) in enumerate(pa.iterrows()):
        p = row["platform"]
        c = PC.get(p, GOLD)
        pct = row["spend"] / tot_sp * 100 if tot_sp else 0
        with pk[i]:
            cps_str = f"£{int(row['cps'])} CPS" if pd.notna(row["cps"]) else "CPS —"
            st.markdown(skpi(f"{p.upper()} SPEND", f"£{row['spend']:,.0f}",
                f"{pct:.0f}% of budget · {int(row['leads'])} leads · {cps_str}", c),
                unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    dc, tc = st.columns([4, 6])
    with dc:
        fig_d = go.Figure(go.Pie(
            labels=pa["platform"], values=pa["spend"].round(0), hole=0.65,
            marker=dict(colors=[PC.get(p, DIM) for p in pa["platform"]], line=dict(color=BG, width=4)),
            textinfo="label+percent", textfont=dict(size=13, family="Nunito Sans"),
            hovertemplate="<b>%{label}</b><br>£%{value:,.0f}<br>%{percent}<extra></extra>",
        ))
        fig_d.update_layout(title="Spend Distribution", height=380,
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="'Nunito Sans',sans-serif", color=WHITE),
            title_font=dict(family="'Playfair Display',serif", size=20, color=GOLD),
            showlegend=False, margin=dict(t=60, b=20, l=10, r=10),
            annotations=[dict(text=f"<b>£{tot_sp:,.0f}</b>", x=0.5, y=0.5,
                font=dict(size=18, color=GOLD, family="Playfair Display"), showarrow=False)])
        st.plotly_chart(fig_d, use_container_width=True)

    with tc:
        dts = df.copy()
        dts["date"] = pd.to_datetime(dts["date"])
        piv = dts.pivot_table(index="date", columns="platform",
            values="spend_gbp", aggfunc="sum", fill_value=0).reset_index()
        fig_sp = go.Figure()
        for p in ["Google", "Meta", "Bing"]:
            if p in piv.columns:
                fig_sp.add_trace(go.Scatter(x=piv["date"], y=piv[p], name=p, mode="lines",
                    line=dict(color=PC[p], width=2.5), fill="tozeroy", fillcolor=FILL[p],
                    hovertemplate=f"<b>%{{x|%d %b}}</b><br>£%{{y:,.2f}}<extra>{p}</extra>"))
        fig_sp.update_layout(title="Daily Spend by Platform", height=380, **CHART)
        st.plotly_chart(fig_sp, use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # Full-funnel per platform
    st.markdown('<div class="msec">Lead → Appointment → Sale Funnel by Platform</div>', unsafe_allow_html=True)
    fn_cols = st.columns(len(pa))
    for i, (_, row) in enumerate(pa.iterrows()):
        p = row["platform"]
        c = PC.get(p, GOLD)
        with fn_cols[i]:
            fig_fn = go.Figure(go.Funnel(
                y=["Leads", "Appointments", "Sales"],
                x=[int(row["leads"]), int(row["appts"]), int(row["sales"])],
                textinfo="value+percent initial",
                textfont=dict(size=13, family="Nunito Sans", color=WHITE),
                marker=dict(color=[c, GOLD, GOLD_L], line=dict(width=2, color=BG)),
                connector=dict(line=dict(color=BORDER, width=1)),
            ))
            fig_fn.update_layout(
                title=f"{p} Funnel", height=300,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Nunito Sans", color=WHITE),
                title_font=dict(family="'Playfair Display',serif", size=16, color=c),
                margin=dict(t=50, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_fn, use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="msec">Domestic vs Commercial — Paid Leads by Platform</div>', unsafe_allow_html=True)

    if not df_ct.empty:
        ct_cols = st.columns(len(pa))
        for i, (_, row) in enumerate(pa.iterrows()):
            p = row["platform"]
            c = PC.get(p, GOLD)
            ct_p = df_ct[df_ct["platform"] == p]
            with ct_cols[i]:
                if ct_p.empty:
                    st.markdown(f'<div style="color:{DIM};font-family:DM Mono;font-size:.7rem;padding:20px">No lead data for {p}</div>', unsafe_allow_html=True)
                else:
                    fig_ct = go.Figure(go.Pie(
                        labels=ct_p["customer_type"].str.capitalize(),
                        values=ct_p["leads"],
                        hole=0.6,
                        marker=dict(
                            colors=[c if t.lower() == "domestic" else GOLD if t.lower() == "commercial" else DIM
                                    for t in ct_p["customer_type"]],
                            line=dict(color=BG, width=3)
                        ),
                        textinfo="label+value",
                        textfont=dict(size=12, family="Nunito Sans"),
                        hovertemplate="<b>%{label}</b><br>%{value} leads<extra></extra>",
                    ))
                    dom = ct_p[ct_p["customer_type"] == "domestic"]["leads"].sum()
                    com = ct_p[ct_p["customer_type"] == "commercial"]["leads"].sum()
                    tot = ct_p["leads"].sum()
                    pct_dom = f"{dom/tot*100:.0f}% dom" if tot else "—"
                    fig_ct.update_layout(
                        title=f"{p}",
                        height=280,
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="'Nunito Sans',sans-serif", color=WHITE),
                        title_font=dict(family="'Playfair Display',serif", size=16, color=c),
                        showlegend=False,
                        margin=dict(t=50, b=10, l=10, r=10),
                        annotations=[dict(text=pct_dom, x=0.5, y=0.5,
                            font=dict(size=13, color=c, family="Playfair Display"), showarrow=False)]
                    )
                    st.plotly_chart(fig_ct, use_container_width=True)

    st.markdown(
        f'<div style="font-family:\'DM Mono\',monospace;font-size:.62rem;color:{DIM};'
        f'padding:10px 0;letter-spacing:1px">'
        f'⚠ Lead counts reflect SharpSpring campaign_id attribution only. '
        f'Some Google campaigns (e.g. Google Search) are not yet mapped — '
        f'paid lead totals may be understated. Update campaign_platform_mapping seed to include all active campaigns.'
        f'</div>',
        unsafe_allow_html=True)

# ═══════════════════════════════════ TAB 2 — PERFORMANCE ══════════════════════
with t2:
    cc, ac = st.columns(2)

    with cc:
        dc2 = df[df["cost_per_lead"].notna()].copy()
        dc2["date"] = pd.to_datetime(dc2["date"])
        pv2 = dc2.pivot_table(index="date", columns="platform",
            values="cost_per_lead", aggfunc="mean").reset_index()
        fig_cpl = go.Figure()
        for p in ["Google", "Meta", "Bing"]:
            if p in pv2.columns:
                fig_cpl.add_trace(go.Scatter(x=pv2["date"], y=pv2[p], name=p, mode="lines+markers",
                    line=dict(color=PC[p], width=2.5), marker=dict(size=5, color=PC[p]),
                    hovertemplate=f"<b>%{{x|%d %b}}</b><br>£%{{y:.2f}} CPL<extra>{p}</extra>"))
        fig_cpl.update_layout(title="Cost Per Lead", height=340,
            yaxis=dict(tickprefix="£", gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
            **{k: v for k, v in CHART.items() if k != "yaxis"})
        st.plotly_chart(fig_cpl, use_container_width=True)

    with ac:
        da2 = df[df["cost_per_appointment"].notna()].copy()
        da2["date"] = pd.to_datetime(da2["date"])
        pv3 = da2.pivot_table(index="date", columns="platform",
            values="cost_per_appointment", aggfunc="mean").reset_index()
        fig_cpa = go.Figure()
        for p in ["Google", "Meta", "Bing"]:
            if p in pv3.columns:
                fig_cpa.add_trace(go.Scatter(x=pv3["date"], y=pv3[p], name=p, mode="lines+markers",
                    line=dict(color=PC[p], width=2.5), marker=dict(size=5),
                    hovertemplate=f"<b>%{{x|%d %b}}</b><br>£%{{y:.2f}} CPA<extra>{p}</extra>"))
        fig_cpa.update_layout(title="Cost Per Appointment", height=340,
            yaxis=dict(tickprefix="£", gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
            **{k: v for k, v in CHART.items() if k != "yaxis"})
        st.plotly_chart(fig_cpa, use_container_width=True)

    # CPS trend (only show if we have sales data)
    cps_df = df[df["cost_per_sale"].notna()].copy()
    if not cps_df.empty:
        cps_df["date"] = pd.to_datetime(cps_df["date"])
        pv_cps = cps_df.pivot_table(index="date", columns="platform",
            values="cost_per_sale", aggfunc="mean").reset_index()
        fig_cps = go.Figure()
        for p in ["Google", "Meta", "Bing"]:
            if p in pv_cps.columns:
                fig_cps.add_trace(go.Scatter(x=pv_cps["date"], y=pv_cps[p], name=p, mode="lines+markers",
                    line=dict(color=PC[p], width=2.5), marker=dict(size=5),
                    hovertemplate=f"<b>%{{x|%d %b}}</b><br>£%{{y:.2f}} CPS<extra>{p}</extra>"))
        fig_cps.update_layout(title="Cost Per Sale", height=300,
            yaxis=dict(tickprefix="£", gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
            **{k: v for k, v in CHART.items() if k != "yaxis"})
        st.plotly_chart(fig_cps, use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="msec">Leads &amp; Appointments Over Time</div>', unsafe_allow_html=True)

    dla = df.copy()
    dla["date"] = pd.to_datetime(dla["date"])
    dlg = dla.groupby("date").agg(
        leads=("leads", "sum"), appts=("appointments_booked", "sum"),
        sales=("sales", "sum")).reset_index()

    fig_la = make_subplots(specs=[[{"secondary_y": True}]])
    fig_la.add_trace(go.Bar(x=dlg["date"], y=dlg["leads"], name="Leads",
        marker_color="rgba(212,168,67,0.25)", marker_line_width=0), secondary_y=False)
    fig_la.add_trace(go.Scatter(x=dlg["date"], y=dlg["appts"], name="Appointments",
        line=dict(color=GOLD_L, width=3), mode="lines+markers",
        marker=dict(size=6, color=GOLD_L)), secondary_y=True)
    fig_la.add_trace(go.Scatter(x=dlg["date"], y=dlg["sales"], name="Sales",
        line=dict(color=GOOGLE, width=2, dash="dot"), mode="lines+markers",
        marker=dict(size=5, color=GOOGLE)), secondary_y=True)
    fig_la.update_layout(title="Leads vs Appointments vs Sales (Daily)", height=300, **CHART)
    fig_la.update_yaxes(gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, secondary_y=False)
    fig_la.update_yaxes(gridcolor="rgba(0,0,0,0)", secondary_y=True)
    st.plotly_chart(fig_la, use_container_width=True)

    st.markdown('<div class="msec">Click-to-Lead Rate by Platform</div>', unsafe_allow_html=True)
    dcl = df[df["click_to_lead_rate"].notna()].copy()
    dcl["date"] = pd.to_datetime(dcl["date"])
    pvc = dcl.pivot_table(index="date", columns="platform",
        values="click_to_lead_rate", aggfunc="mean").reset_index()
    fig_cl = go.Figure()
    for p in ["Google", "Meta", "Bing"]:
        if p in pvc.columns:
            fig_cl.add_trace(go.Scatter(x=pvc["date"], y=(pvc[p] * 100).round(3), name=p, mode="lines",
                line=dict(color=PC[p], width=2),
                hovertemplate=f"<b>%{{x|%d %b}}</b><br>%{{y:.2f}}% CTL<extra>{p}</extra>"))
    fig_cl.update_layout(title="Click-to-Lead Rate (%)", height=260,
        yaxis=dict(ticksuffix="%", gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
        **{k: v for k, v in CHART.items() if k != "yaxis"})
    st.plotly_chart(fig_cl, use_container_width=True)

# ═══════════════════════════════════ TAB 3 — PLATFORMS ════════════════════════
with t3:
    gc, ac2 = st.columns(2)

    with gc:
        fig_g = go.Figure()
        fig_g.add_bar(x=pa["platform"], y=pa["leads"], name="Leads",
            marker_color=[PC.get(p, DIM) for p in pa["platform"]],
            text=pa["leads"].astype(int), textposition="outside",
            textfont=dict(color=WHITE, size=13))
        fig_g.add_bar(x=pa["platform"], y=pa["appts"], name="Appointments",
            marker_color=GOLD, opacity=0.75,
            text=pa["appts"].astype(int), textposition="outside",
            textfont=dict(color=WHITE, size=13))
        fig_g.add_bar(x=pa["platform"], y=pa["sales"], name="Sales",
            marker_color=GOLD_L, opacity=0.9,
            text=pa["sales"].astype(int), textposition="outside",
            textfont=dict(color=WHITE, size=13))
        fig_g.update_layout(title="Leads, Appointments & Sales by Platform",
            barmode="group", height=400, **CHART)
        st.plotly_chart(fig_g, use_container_width=True)

    with ac2:
        fig_c = go.Figure()
        fig_c.add_bar(x=pa["platform"], y=pa["cpl"], name="CPL",
            marker_color=[PC.get(p, DIM) for p in pa["platform"]], opacity=0.85,
            text=["£" + str(int(v)) if pd.notna(v) else "—" for v in pa["cpl"]],
            textposition="outside", textfont=dict(color=WHITE, size=13))
        fig_c.add_bar(x=pa["platform"], y=pa["cpa"], name="CPA",
            marker_color=GOLD, opacity=0.7,
            text=["£" + str(int(v)) if pd.notna(v) else "—" for v in pa["cpa"]],
            textposition="outside", textfont=dict(color=WHITE, size=13))
        fig_c.add_bar(x=pa["platform"], y=pa["cps"], name="CPS",
            marker_color=GOLD_L, opacity=0.9,
            text=["£" + str(int(v)) if pd.notna(v) else "—" for v in pa["cps"]],
            textposition="outside", textfont=dict(color=WHITE, size=13))
        fig_c.update_layout(title="CPL, CPA & CPS by Platform", barmode="group", height=400,
            yaxis=dict(tickprefix="£", gridcolor="rgba(212,168,67,0.07)", linecolor=BORDER, zeroline=False),
            **{k: v for k, v in CHART.items() if k != "yaxis"})
        st.plotly_chart(fig_c, use_container_width=True)

    st.markdown('<div class="msec">Platform Summary</div>', unsafe_allow_html=True)
    sm = pa.copy()
    sm["spend"] = sm["spend"].apply(lambda x: f"£{x:,.2f}")
    sm["cpl"]   = sm["cpl"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    sm["cpa"]   = sm["cpa"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    sm["cps"]   = sm["cps"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    sm["ctr"]   = sm["ctr"].apply(lambda x: f"{x:.3f}%" if pd.notna(x) else "—")
    sm["l2a"]   = sm["l2a"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    sm["a2s"]   = sm["a2s"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    sm.columns  = ["Platform", "Spend", "Clicks", "Impressions", "Leads",
                   "Appts", "Sales", "CPL", "CPA", "CPS", "CTR", "Lead→Appt", "Appt→Sale"]
    st.dataframe(sm, use_container_width=True, hide_index=True)

    st.markdown('<div class="msec">Daily Attribution Detail</div>', unsafe_allow_html=True)
    dd = df.copy()
    dd["spend_gbp"]             = dd["spend_gbp"].apply(lambda x: f"£{x:,.2f}")
    dd["cost_per_lead"]         = dd["cost_per_lead"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    dd["cost_per_appointment"]  = dd["cost_per_appointment"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    dd["cost_per_sale"]         = dd["cost_per_sale"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
    dd["click_to_lead_rate"]    = dd["click_to_lead_rate"].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—")
    dd = dd[["date", "platform", "spend_gbp", "clicks", "impressions",
             "leads", "appointments_booked", "sales",
             "cost_per_lead", "cost_per_appointment", "cost_per_sale", "click_to_lead_rate"]]
    dd.columns = ["Date", "Platform", "Spend", "Clicks", "Impressions",
                  "Leads", "Appts", "Sales", "CPL", "CPA", "CPS", "Click→Lead"]
    st.dataframe(dd, use_container_width=True, hide_index=True, height=400)
