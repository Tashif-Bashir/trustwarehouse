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
BG      = "#030d07"
BG2     = "#061209"
BG3     = "#0d1f12"
PRIMARY = "#10b981"
LIGHT   = "#34d399"
GOLD    = "#fbbf24"
RED     = "#f87171"
AMBER   = "#fb923c"
DIM     = "#4a7c62"
BORDER  = "#1a3825"
WHITE   = "#ecfdf5"

STAGE_COLORS = {
    "New":       "#546e7a",
    "Called":    "#0288d1",
    "Qualified": "#7b1fa2",
    "Appointed": PRIMARY,
    "Sold":      GOLD,
}

CHART = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'IBM Plex Sans',sans-serif", color=WHITE, size=12),
    margin=dict(t=52, b=20, l=10, r=10),
    xaxis=dict(gridcolor="rgba(16,185,129,0.08)", linecolor=BORDER, zeroline=False),
    yaxis=dict(gridcolor="rgba(16,185,129,0.08)", linecolor=BORDER, zeroline=False),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02,
        bgcolor="rgba(0,0,0,0)", font=dict(color=DIM)
    ),
    title_font=dict(family="'Playfair Display',serif", size=20, color=PRIMARY),
    hoverlabel=dict(
        bgcolor=BG2, bordercolor=PRIMARY,
        font=dict(family="'IBM Plex Sans',sans-serif", color=WHITE)
    ),
)

EXCLUDE = ("Trust Admin", "admin", "Paris")
STAGES  = ["New", "Called", "Qualified", "Appointed", "Sold"]

# ── PAGE ──────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sales Pipeline — Trust",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html,body,.stApp,[data-testid="stAppViewContainer"]{{
  background-color:{BG}!important;color:{WHITE}!important;
  font-family:'IBM Plex Sans',sans-serif!important
}}
[data-testid="stAppViewContainer"]{{
  background-image:
    radial-gradient(ellipse 55% 35% at 8% 18%,rgba(16,185,129,0.08) 0%,transparent 100%),
    radial-gradient(ellipse 35% 28% at 92% 82%,rgba(251,191,36,0.05) 0%,transparent 100%),
    radial-gradient(ellipse 20% 20% at 60% 10%,rgba(52,211,153,0.04) 0%,transparent 100%)
}}
.block-container{{padding:1rem 2rem 2rem!important;max-width:100%!important}}
#MainMenu,footer,header{{visibility:hidden}}

.hdr{{padding:1.5rem 0 1rem;border-bottom:1px solid {BORDER};margin-bottom:1.2rem;position:relative}}
.hdr-glow{{
  position:absolute;bottom:-1px;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent 0%,{PRIMARY} 45%,{GOLD} 75%,transparent 100%)
}}
.hdr-eye{{font-family:'IBM Plex Mono',monospace;font-size:.6rem;letter-spacing:5px;color:{DIM};text-transform:uppercase;margin-bottom:6px}}
.hdr-title{{
  font-family:'Playfair Display',serif;font-size:3rem;font-weight:900;
  line-height:1.05;margin:0;
  background:linear-gradient(135deg,{LIGHT} 0%,{PRIMARY} 45%,{GOLD} 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text
}}

.kpi{{
  background:{BG2};border:1px solid {BORDER};
  border-top:2.5px solid var(--c,{PRIMARY});
  border-radius:6px;padding:16px 14px 14px;margin-bottom:4px
}}
.kpi-lbl{{font-family:'IBM Plex Mono',monospace;font-size:.56rem;letter-spacing:3px;color:{DIM};text-transform:uppercase;margin-bottom:8px}}
.kpi-val{{
  font-family:'Playfair Display',serif;font-size:2.4rem;font-weight:700;
  line-height:1;color:var(--c,{WHITE});letter-spacing:-1px
}}
.kpi-sub{{font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:{DIM};margin-top:8px;letter-spacing:1px}}
.kpi-sub.g{{color:{PRIMARY}}}.kpi-sub.r{{color:{RED}}}.kpi-sub.a{{color:{AMBER}}}

.sec{{
  font-family:'IBM Plex Mono',monospace;font-size:.68rem;letter-spacing:4px;
  color:{DIM};text-transform:uppercase;margin:.8rem 0 .6rem;
  border-left:2px solid {PRIMARY};padding-left:10px
}}
hr{{border:none!important;border-top:1px solid {BORDER}!important;margin:1.2rem 0!important}}

button[role="tab"]{{
  font-family:'IBM Plex Mono',monospace!important;font-size:.82rem!important;
  letter-spacing:4px!important;color:{DIM}!important;
  border:none!important;background:transparent!important
}}
button[role="tab"][aria-selected="true"]{{color:{PRIMARY}!important;border-bottom:2px solid {PRIMARY}!important}}
button[role="tab"]:hover{{color:{WHITE}!important}}

[data-testid="stButton"]>button{{
  background:transparent!important;border:1px solid {BORDER}!important;
  color:{DIM}!important;font-family:'IBM Plex Mono',monospace!important;
  font-size:.75rem!important;letter-spacing:3px!important;
  border-radius:4px!important;transition:all .2s!important
}}
[data-testid="stButton"]>button:hover{{
  border-color:{PRIMARY}!important;color:{PRIMARY}!important;
  background:rgba(16,185,129,0.05)!important
}}
[data-testid="stSelectbox"]>div>div{{
  background:{BG2}!important;border:1px solid {BORDER}!important;
  color:{WHITE}!important;border-radius:4px!important
}}
[data-testid="stDateInput"] input{{
  background:{BG2}!important;border:1px solid {BORDER}!important;
  color:{WHITE}!important;border-radius:4px!important
}}
[data-testid="stDataFrame"]{{border:1px solid {BORDER}!important;border-radius:6px!important}}
[data-testid="stCheckbox"]>label>div:first-child{{
  background:transparent!important;border-color:{BORDER}!important
}}
.stMultiSelect>div>div{{
  background:{BG2}!important;border:1px solid {BORDER}!important;
  border-radius:4px!important
}}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _connect():
    return duckdb.connect(f"md:trust-pipeline?motherduck_token={os.getenv('MOTHERDUCK_TOKEN','')}")


def kpi(label, value, sub=None, color=None):
    c = color or PRIMARY
    scls = ("g" if sub and str(sub).startswith("+") else
            "r" if sub and str(sub).startswith("-") else "")
    sh = f'<div class="kpi-sub {scls}">{sub}</div>' if sub else ""
    return (f'<div class="kpi" style="--c:{c}">'
            f'<div class="kpi-lbl">{label}</div>'
            f'<div class="kpi-val">{value}</div>{sh}</div>')


def fmt_gbp(v):
    if pd.isna(v) or v == 0:
        return "—"
    return f"£{v:,.0f}"


@st.cache_data(ttl=1800, show_spinner="Loading pipeline…")
def load_leads(d0: str, d1: str) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT
            lead_id,
            first_name,
            last_name,
            email,
            phone,
            created_at,
            created_date,
            lead_status,
            domestic_lead_status,
            appointment_booked,
            appointment_booked_at,
            appointment_date,
            appointment_made_by,
            appointment_type,
            appointment_status,
            customer_type,
            pipeline_category,
            total_call_attempts,
            first_call_at,
            last_call_at,
            last_call_date,
            last_call_agent,
            has_been_called,
            has_qualified_conversation,
            qualified_conversations,
            quote_amount,
            deal_amount,
            order_confirmed,
            order_confirmed_at,
            is_sold,
            CASE
                WHEN is_sold                        THEN 'Sold'
                WHEN appointment_booked = 'Yes'     THEN 'Appointed'
                WHEN has_qualified_conversation     THEN 'Qualified'
                WHEN has_been_called                THEN 'Called'
                ELSE 'New'
            END AS pipeline_stage
        FROM gold.gold_lead_activity
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
        ORDER BY created_at DESC
    """).df()
    con.close()
    return df


@st.cache_data(ttl=1800, show_spinner="Loading trend…")
def load_daily(d0: str, d1: str) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT
            created_date                             AS date,
            count(*)                                 AS leads,
            count(*) FILTER (WHERE appointment_booked = 'Yes') AS appointments,
            count(*) FILTER (WHERE is_sold)          AS sold,
            sum(quote_amount)                        AS quote_pipeline,
            sum(deal_amount) FILTER (WHERE is_sold)  AS deal_value
        FROM gold.gold_lead_activity
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY created_date
        ORDER BY created_date
    """).df()
    con.close()
    return df


# ── PERIOD SELECTOR ───────────────────────────────────────────────────────────
PRESETS = [
    "Yesterday", "Today", "This Week", "Last 7 Working Days",
    "This Month", "Last 30 Days", "Custom",
]


def _working_range(n: int):
    days, d = [], date.today() - timedelta(1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(1)
    return days[-1], days[0]


today = date.today()

PRESET_DATES = {
    "Today":               (today, today),
    "Yesterday":           (today - timedelta(1), today - timedelta(1)),
    "This Week":           (today - timedelta(today.weekday()), today),
    "Last 7 Working Days": _working_range(7),
    "This Month":          (today.replace(day=1), today),
    "Last 30 Days":        (today - timedelta(29), today),
}

# ── HEADER ────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hdr">
  <div class="hdr-eye">Trust Electric Heating &nbsp;/&nbsp; Revenue Pipeline</div>
  <h1 class="hdr-title">Sales Pipeline</h1>
  <div class="hdr-glow"></div>
</div>
""", unsafe_allow_html=True)

hl, hm, hn, hr_ = st.columns([2, 2, 2, 2])
with hl:
    preset = st.selectbox("Period", PRESETS, index=0, label_visibility="collapsed")

if preset == "Custom":
    with hm:
        d0 = st.date_input("From", value=today - timedelta(7),
                           max_value=today, label_visibility="collapsed")
    with hn:
        d1 = st.date_input("To", value=today - timedelta(1),
                           max_value=today, label_visibility="collapsed")
else:
    d0, d1 = PRESET_DATES[preset]

with hr_:
    rc1, rc2 = st.columns([1, 2])
    with rc1:
        if st.button("↺  REFRESH", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with rc2:
        st.markdown(
            f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.6rem;'
            f'color:{DIM};padding-top:12px;letter-spacing:2px;text-align:right">'
            f'GOLD · MOTHERDUCK · 30 MIN</div>',
            unsafe_allow_html=True,
        )

s0 = d0.strftime("%Y-%m-%d")
s1 = d1.strftime("%Y-%m-%d")
period_lbl = (
    d0.strftime("%A %d %B %Y").upper()
    if d0 == d1 else
    (d0.strftime("%d %b") + " – " + d1.strftime("%d %b %Y")).upper()
)
st.markdown(
    f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.78rem;'
    f'color:{PRIMARY};letter-spacing:3px;margin-bottom:1.2rem">▸ {period_lbl}</div>',
    unsafe_allow_html=True,
)

df_ld    = load_leads(s0, s1)
df_daily = load_daily(s0, s1)

# ── TABS ──────────────────────────────────────────────────────────────────────
t_ov, t_pl, t_deals = st.tabs(["OVERVIEW", "PIPELINE", "DEALS"])

# ═══════════════════════════════════ TAB 1 — OVERVIEW ═════════════════════════
with t_ov:
    if df_ld.empty:
        st.warning(f"No lead data for {period_lbl}.")
    else:
        total     = len(df_ld)
        appts     = int((df_ld["appointment_booked"] == "Yes").sum())
        sold      = int(df_ld["is_sold"].sum())
        l2a_pct   = appts / total * 100 if total else 0
        a2s_pct   = sold / appts * 100 if appts else 0
        quote_val = df_ld["quote_amount"].sum(skipna=True)
        deal_val  = df_ld.loc[df_ld["is_sold"], "deal_amount"].sum(skipna=True)

        # ── KPI ROW ───────────────────────────────────────────────────────────
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        with c1:
            st.markdown(kpi("LEADS IN", f"{total:,}", None, PRIMARY), unsafe_allow_html=True)
        with c2:
            l2a_cl = "g" if l2a_pct >= 33 else ("a" if l2a_pct >= 20 else "r")
            st.markdown(kpi("APPOINTMENTS", f"{appts:,}",
                f"{l2a_pct:.1f}% lead→appt", PRIMARY), unsafe_allow_html=True)
        with c3:
            st.markdown(kpi("LEAD → APPT", f"{l2a_pct:.1f}%",
                "target ≥33%",
                PRIMARY if l2a_pct >= 33 else (AMBER if l2a_pct >= 20 else RED)),
                unsafe_allow_html=True)
        with c4:
            st.markdown(kpi("SOLD", f"{sold:,}", None, GOLD), unsafe_allow_html=True)
        with c5:
            st.markdown(kpi("APPT → SALE", f"{a2s_pct:.1f}%",
                "target ≥33%",
                PRIMARY if a2s_pct >= 33 else (AMBER if a2s_pct >= 20 else RED)),
                unsafe_allow_html=True)
        with c6:
            qv_lbl = fmt_gbp(quote_val) if quote_val > 0 else "—"
            st.markdown(kpi("QUOTE PIPELINE", qv_lbl, "open quotes", LIGHT), unsafe_allow_html=True)
        with c7:
            dv_lbl = fmt_gbp(deal_val) if deal_val > 0 else "—"
            st.markdown(kpi("DEAL VALUE", dv_lbl, f"{sold} sales", GOLD), unsafe_allow_html=True)

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── FUNNEL + CONVERSION ───────────────────────────────────────────────
        col_f, col_d = st.columns([3, 2])

        with col_f:
            stage_counts = (
                df_ld["pipeline_stage"]
                .value_counts()
                .reindex(STAGES, fill_value=0)
            )
            fig_f = go.Figure(go.Funnel(
                y=STAGES,
                x=stage_counts.values,
                textinfo="value+percent previous",
                marker=dict(color=[STAGE_COLORS[s] for s in STAGES]),
                connector=dict(line=dict(color=BORDER, width=1)),
                textfont=dict(family="IBM Plex Mono", color=WHITE, size=13),
            ))
            fig_f.update_layout(**CHART, title="CONVERSION FUNNEL", height=320,
                                margin=dict(t=52, b=10, l=0, r=0))
            st.plotly_chart(fig_f, use_container_width=True)

        with col_d:
            ctype_counts = df_ld["customer_type"].fillna("Unknown").value_counts()
            pie_colors   = [PRIMARY, AMBER, DIM]
            fig_d = go.Figure(go.Pie(
                labels=ctype_counts.index,
                values=ctype_counts.values,
                hole=0.6,
                marker=dict(colors=pie_colors[:len(ctype_counts)], line=dict(color=BG, width=2)),
                textinfo="label+percent",
                textfont=dict(family="IBM Plex Mono", color=WHITE, size=11),
                hovertemplate="%{label}: %{value} leads<extra></extra>",
            ))
            fig_d.update_layout(**CHART, title="CUSTOMER TYPE", height=320,
                                margin=dict(t=52, b=10, l=0, r=0),
                                showlegend=False)
            fig_d.add_annotation(
                text=f"<b>{total:,}</b><br>leads",
                x=0.5, y=0.5, font=dict(family="Playfair Display", size=18, color=WHITE),
                showarrow=False,
            )
            st.plotly_chart(fig_d, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown('<div class="sec">Daily Trend</div>', unsafe_allow_html=True)

        # ── DAILY TREND ───────────────────────────────────────────────────────
        if not df_daily.empty:
            fig_t = make_subplots(specs=[[{"secondary_y": True}]])
            fig_t.add_trace(go.Bar(
                x=df_daily["date"], y=df_daily["leads"],
                name="Leads", marker_color=f"rgba(16,185,129,0.35)",
                hovertemplate="%{x|%d %b}: %{y} leads<extra></extra>",
            ), secondary_y=False)
            fig_t.add_trace(go.Scatter(
                x=df_daily["date"], y=df_daily["appointments"],
                name="Appointments", mode="lines+markers",
                line=dict(color=LIGHT, width=2.5),
                marker=dict(size=6, color=LIGHT),
                hovertemplate="%{x|%d %b}: %{y} appts<extra></extra>",
            ), secondary_y=False)
            fig_t.add_trace(go.Scatter(
                x=df_daily["date"], y=df_daily["sold"],
                name="Sold", mode="lines+markers",
                line=dict(color=GOLD, width=2, dash="dot"),
                marker=dict(size=5, color=GOLD),
                hovertemplate="%{x|%d %b}: %{y} sold<extra></extra>",
            ), secondary_y=False)
            fig_t.update_layout(
                **CHART, title="LEADS · APPOINTMENTS · SOLD", height=280,
                barmode="overlay",
            )
            fig_t.update_yaxes(title_text=None, secondary_y=False)
            st.plotly_chart(fig_t, use_container_width=True)

# ═══════════════════════════════════ TAB 2 — PIPELINE ═════════════════════════
with t_pl:
    if df_ld.empty:
        st.warning(f"No lead data for {period_lbl}.")
    else:
        # ── FILTERS ───────────────────────────────────────────────────────────
        fa, fb, fc, _ = st.columns([2, 2, 2, 2])
        with fa:
            ctype_opts = ["All"] + sorted(
                df_ld["customer_type"].dropna().unique().tolist()
            ) + ["Unknown"]
            ctype_filter = st.selectbox("Customer Type", ctype_opts, label_visibility="collapsed")
        with fb:
            stage_opts = ["All Stages"] + STAGES
            stage_filter = st.selectbox("Pipeline Stage", stage_opts, label_visibility="collapsed")
        with fc:
            sold_only = st.checkbox("Sold only", value=False)

        dfp = df_ld.copy()
        if ctype_filter != "All":
            if ctype_filter == "Unknown":
                dfp = dfp[dfp["customer_type"].isna()]
            else:
                dfp = dfp[dfp["customer_type"] == ctype_filter]
        if stage_filter != "All Stages":
            dfp = dfp[dfp["pipeline_stage"] == stage_filter]
        if sold_only:
            dfp = dfp[dfp["is_sold"]]

        st.markdown(
            f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:.65rem;'
            f'color:{DIM};letter-spacing:2px;margin-bottom:.8rem">'
            f'{len(dfp):,} LEADS SHOWN</div>',
            unsafe_allow_html=True,
        )

        # ── STAGE BREAKDOWN BARS + TYPE DONUT ────────────────────────────────
        pl_c1, pl_c2 = st.columns([3, 2])

        with pl_c1:
            stage_counts_f = (
                dfp["pipeline_stage"]
                .value_counts()
                .reindex(STAGES, fill_value=0)
            )
            fig_sb = go.Figure(go.Bar(
                x=STAGES,
                y=stage_counts_f.values,
                marker=dict(color=[STAGE_COLORS[s] for s in STAGES],
                            line=dict(color=BORDER, width=1)),
                text=stage_counts_f.values,
                textposition="outside",
                textfont=dict(family="IBM Plex Mono", color=WHITE, size=12),
                hovertemplate="%{x}: %{y} leads<extra></extra>",
            ))
            fig_sb.update_layout(
                **CHART, title="LEADS BY PIPELINE STAGE", height=300,
                showlegend=False,
                yaxis=dict(visible=False, gridcolor="rgba(16,185,129,0.08)",
                           linecolor=BORDER, zeroline=False),
            )
            st.plotly_chart(fig_sb, use_container_width=True)

        with pl_c2:
            ct = dfp["customer_type"].fillna("Unknown").value_counts()
            fig_ct = go.Figure(go.Pie(
                labels=ct.index, values=ct.values, hole=0.55,
                marker=dict(colors=[PRIMARY, AMBER, DIM][:len(ct)],
                            line=dict(color=BG, width=2)),
                textinfo="label+percent",
                textfont=dict(family="IBM Plex Mono", color=WHITE, size=11),
            ))
            fig_ct.update_layout(
                **CHART, title="BY CUSTOMER TYPE", height=300,
                showlegend=False, margin=dict(t=52, b=10, l=0, r=0),
            )
            st.plotly_chart(fig_ct, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown('<div class="sec">Lead Tracker</div>', unsafe_allow_html=True)

        # ── LEAD TRACKER TABLE ────────────────────────────────────────────────
        tracker = dfp[[
            "first_name", "last_name", "created_date", "customer_type",
            "pipeline_stage", "appointment_status", "last_call_agent",
            "total_call_attempts", "quote_amount", "deal_amount", "is_sold",
        ]].copy()
        tracker["Name"]         = tracker["first_name"].fillna("") + " " + tracker["last_name"].fillna("")
        tracker["Date"]         = pd.to_datetime(tracker["created_date"]).dt.strftime("%d %b")
        tracker["Type"]         = tracker["customer_type"].fillna("Unknown").str.capitalize()
        tracker["Stage"]        = tracker["pipeline_stage"]
        tracker["Appt Status"]  = tracker["appointment_status"].fillna("—")
        tracker["Last Agent"]   = tracker["last_call_agent"].fillna("—")
        tracker["Calls"]        = tracker["total_call_attempts"].fillna(0).astype(int)
        tracker["Quote £"]      = tracker["quote_amount"].apply(
            lambda v: fmt_gbp(v) if pd.notna(v) and v > 0 else "—"
        )
        tracker["Deal £"]       = tracker["deal_amount"].apply(
            lambda v: fmt_gbp(v) if pd.notna(v) and v > 0 else "—"
        )
        tracker["Sold"]         = tracker["is_sold"].map({True: "✓", False: ""})

        show_cols = ["Name", "Date", "Type", "Stage", "Appt Status",
                     "Last Agent", "Calls", "Quote £", "Deal £", "Sold"]
        st.dataframe(
            tracker[show_cols].head(200),
            use_container_width=True,
            hide_index=True,
            height=450,
        )

# ═══════════════════════════════════ TAB 3 — DEALS ════════════════════════════
with t_deals:
    df_sold = df_ld[df_ld["is_sold"]].copy()

    # ── KPI ROW ───────────────────────────────────────────────────────────────
    n_sold      = len(df_sold)
    total_deal  = df_sold["deal_amount"].sum(skipna=True)
    avg_deal    = df_sold["deal_amount"].mean(skipna=True)
    n_deal_set  = int(df_sold["deal_amount"].notna().sum())
    n_order_ok  = int(df_sold["order_confirmed"].eq(True).sum())

    dc1, dc2, dc3, dc4, dc5 = st.columns(5)
    with dc1:
        st.markdown(kpi("TOTAL SOLD", f"{n_sold:,}", None, GOLD), unsafe_allow_html=True)
    with dc2:
        st.markdown(kpi("TOTAL DEAL VALUE", fmt_gbp(total_deal), f"{n_deal_set} with amount", GOLD),
                    unsafe_allow_html=True)
    with dc3:
        st.markdown(kpi("AVG DEAL VALUE", fmt_gbp(avg_deal) if n_deal_set else "—",
                        None, LIGHT), unsafe_allow_html=True)
    with dc4:
        order_pct = n_order_ok / n_sold * 100 if n_sold else 0
        st.markdown(kpi("ORDER CONFIRMED", f"{n_order_ok:,}",
                        f"{order_pct:.0f}% of sold", PRIMARY), unsafe_allow_html=True)
    with dc5:
        quote_total = df_sold["quote_amount"].sum(skipna=True)
        st.markdown(kpi("TOTAL QUOTED", fmt_gbp(quote_total),
                        "for sold leads", DIM), unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    if df_sold.empty:
        st.info(f"No sold leads in {period_lbl}.")
    else:
        dch1, dch2 = st.columns(2)

        with dch1:
            # Deal value distribution
            deals_with_val = df_sold[df_sold["deal_amount"].notna() & (df_sold["deal_amount"] > 0)]
            if not deals_with_val.empty:
                fig_hist = go.Figure(go.Histogram(
                    x=deals_with_val["deal_amount"],
                    nbinsx=20,
                    marker=dict(color=GOLD, line=dict(color=BG, width=1)),
                    hovertemplate="£%{x:,.0f}: %{y} deals<extra></extra>",
                ))
                fig_hist.update_layout(
                    **CHART, title="DEAL VALUE DISTRIBUTION", height=280,
                    showlegend=False,
                )
                st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.info("No deal amounts recorded yet.")

        with dch2:
            # Quote vs deal scatter (for leads that have both)
            scatter_df = df_ld[
                df_ld["quote_amount"].notna() &
                df_ld["deal_amount"].notna() &
                (df_ld["quote_amount"] > 0) &
                (df_ld["deal_amount"] > 0)
            ]
            if not scatter_df.empty:
                fig_sc = go.Figure(go.Scatter(
                    x=scatter_df["quote_amount"],
                    y=scatter_df["deal_amount"],
                    mode="markers",
                    marker=dict(
                        color=scatter_df["is_sold"].map({True: GOLD, False: DIM}),
                        size=8, opacity=0.8,
                        line=dict(color=BG, width=1),
                    ),
                    customdata=scatter_df[["first_name", "last_name"]].fillna(""),
                    hovertemplate=(
                        "%{customdata[0]} %{customdata[1]}<br>"
                        "Quote: £%{x:,.0f}<br>Deal: £%{y:,.0f}<extra></extra>"
                    ),
                ))
                max_val = max(scatter_df[["quote_amount", "deal_amount"]].max())
                fig_sc.add_shape(
                    type="line", x0=0, y0=0, x1=max_val, y1=max_val,
                    line=dict(color=DIM, width=1, dash="dot"),
                )
                fig_sc.update_layout(
                    **CHART, title="QUOTE vs DEAL VALUE",
                    height=280, showlegend=False,
                    xaxis=dict(title="Quote £", gridcolor="rgba(16,185,129,0.08)",
                               linecolor=BORDER, zeroline=False),
                    yaxis=dict(title="Deal £", gridcolor="rgba(16,185,129,0.08)",
                               linecolor=BORDER, zeroline=False),
                )
                st.plotly_chart(fig_sc, use_container_width=True)
            else:
                st.info("No leads with both quote and deal amounts.")

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown('<div class="sec">Sold Leads</div>', unsafe_allow_html=True)

        # ── SOLD LEADS TABLE ──────────────────────────────────────────────────
        sold_tbl = df_sold[[
            "first_name", "last_name", "created_date", "customer_type",
            "appointment_type", "appointment_status", "appointment_made_by",
            "last_call_agent", "quote_amount", "deal_amount", "order_confirmed",
        ]].copy()
        sold_tbl["Name"]          = (sold_tbl["first_name"].fillna("") + " " +
                                     sold_tbl["last_name"].fillna("")).str.strip()
        sold_tbl["Lead Date"]     = pd.to_datetime(sold_tbl["created_date"]).dt.strftime("%d %b %Y")
        sold_tbl["Type"]          = sold_tbl["customer_type"].fillna("Unknown").str.capitalize()
        sold_tbl["Appt Type"]     = sold_tbl["appointment_type"].fillna("—")
        sold_tbl["Appt Status"]   = sold_tbl["appointment_status"].fillna("—")
        sold_tbl["Booked By"]     = sold_tbl["appointment_made_by"].fillna("—")
        sold_tbl["Last Agent"]    = sold_tbl["last_call_agent"].fillna("—")
        sold_tbl["Quote £"]       = sold_tbl["quote_amount"].apply(
            lambda v: fmt_gbp(v) if pd.notna(v) and v > 0 else "—"
        )
        sold_tbl["Deal £"]        = sold_tbl["deal_amount"].apply(
            lambda v: fmt_gbp(v) if pd.notna(v) and v > 0 else "—"
        )
        sold_tbl["Order OK"]      = sold_tbl["order_confirmed"].map(
            {True: "Yes", False: "No", None: "—"}
        ).fillna("—")

        sold_show = ["Name", "Lead Date", "Type", "Appt Type", "Appt Status",
                     "Booked By", "Last Agent", "Quote £", "Deal £", "Order OK"]

        # Sort by deal amount descending (put nulls last)
        sold_tbl["_deal_sort"] = df_sold["deal_amount"].fillna(0)
        sold_tbl = sold_tbl.sort_values("_deal_sort", ascending=False)

        st.dataframe(
            sold_tbl[sold_show],
            use_container_width=True,
            hide_index=True,
            height=500,
        )
