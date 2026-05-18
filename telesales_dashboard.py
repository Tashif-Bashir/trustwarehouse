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
BG      = "#060612"
BG2     = "#0c0c1e"
PRIMARY = "#00d4ff"
GREEN   = "#00e676"
RED     = "#ff1744"
AMBER   = "#ff9100"
GREY    = "#37374f"
WHITE   = "#e8eaf6"
DIM     = "#546e8a"
PURPLE  = "#b39ddb"
STATUS  = {"g": GREEN, "a": AMBER, "r": RED, "n": DIM}
EXCLUDE = ("Trust Admin", "admin", "Paris")

CHART = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'Barlow',sans-serif", color=WHITE, size=12),
    margin=dict(t=52, b=20, l=10, r=10),
    xaxis=dict(gridcolor="rgba(0,212,255,0.06)", linecolor=GREY, zeroline=False),
    yaxis=dict(gridcolor="rgba(0,212,255,0.06)", linecolor=GREY, zeroline=False),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, bgcolor="rgba(0,0,0,0)", font=dict(color=DIM)),
    title_font=dict(family="'Bebas Neue',sans-serif", size=20, color=PRIMARY),
    hoverlabel=dict(bgcolor=BG2, bordercolor=PRIMARY, font=dict(family="'Barlow',sans-serif", color=WHITE)),
)

# ── PAGE ──────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Telesales Operations", page_icon="📞", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Barlow:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap');

html,body,.stApp,[data-testid="stAppViewContainer"]{{background-color:{BG}!important;color:{WHITE}!important;font-family:'Barlow',sans-serif!important}}
[data-testid="stAppViewContainer"]{{background-image:
  radial-gradient(ellipse 70% 40% at 5% 10%,rgba(0,212,255,0.06) 0%,transparent 100%),
  radial-gradient(ellipse 50% 30% at 95% 90%,rgba(0,230,118,0.04) 0%,transparent 100%)}}
.block-container{{padding:1rem 2rem 2rem!important;max-width:100%!important}}
#MainMenu,footer,header{{visibility:hidden}}

.hdr{{padding:1.2rem 0 .8rem;border-bottom:1px solid {GREY};margin-bottom:1.2rem;position:relative}}
.hdr-glow{{position:absolute;bottom:-1px;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,{PRIMARY} 40%,{GREEN} 70%,transparent)}}
.hdr-eye{{font-family:'Share Tech Mono',monospace;font-size:.6rem;letter-spacing:5px;color:{DIM};text-transform:uppercase;margin-bottom:4px}}
.hdr-title{{font-family:'Bebas Neue',sans-serif;font-size:3rem;letter-spacing:6px;line-height:1;background:linear-gradient(90deg,{PRIMARY},{GREEN});-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin:0}}

.kpi{{background:{BG2};border:1px solid {GREY};border-top:2.5px solid var(--c,{PRIMARY});border-radius:6px;padding:14px 12px 12px}}
.kpi-lbl{{font-family:'Share Tech Mono',monospace;font-size:.56rem;letter-spacing:3px;color:{DIM};text-transform:uppercase;margin-bottom:6px}}
.kpi-val{{font-family:'Bebas Neue',sans-serif;font-size:2.6rem;line-height:1;color:var(--c,{WHITE})}}
.kpi-sub{{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:{DIM};margin-top:6px;letter-spacing:1px}}
.kpi-sub.g{{color:{GREEN}}}.kpi-sub.r{{color:{RED}}}.kpi-sub.a{{color:{AMBER}}}

.sec{{font-family:'Bebas Neue',sans-serif;font-size:1rem;letter-spacing:4px;color:{DIM};text-transform:uppercase;margin:.8rem 0 .5rem}}
hr{{border:none!important;border-top:1px solid {GREY}!important;margin:1rem 0!important}}

button[role="tab"]{{font-family:'Bebas Neue',sans-serif!important;font-size:1rem!important;letter-spacing:4px!important;color:{DIM}!important;border:none!important;background:transparent!important}}
button[role="tab"][aria-selected="true"]{{color:{PRIMARY}!important;border-bottom:2px solid {PRIMARY}!important}}
button[role="tab"]:hover{{color:{WHITE}!important}}
[data-testid="stButton"]>button{{background:transparent!important;border:1px solid {GREY}!important;color:{DIM}!important;font-family:'Bebas Neue',sans-serif!important;letter-spacing:3px!important;border-radius:4px!important;transition:all .2s!important}}
[data-testid="stButton"]>button:hover{{border-color:{PRIMARY}!important;color:{PRIMARY}!important;background:rgba(0,212,255,0.05)!important}}
[data-testid="stSelectbox"] > div > div{{background:{BG2}!important;border:1px solid {GREY}!important;color:{WHITE}!important;border-radius:4px!important}}
[data-testid="stDateInput"] input{{background:{BG2}!important;border:1px solid {GREY}!important;color:{WHITE}!important;border-radius:4px!important}}
[data-testid="stDataFrame"]{{border:1px solid {GREY}!important;border-radius:6px!important}}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _connect():
    return duckdb.connect(f"md:trust-pipeline?motherduck_token={os.getenv('MOTHERDUCK_TOKEN','')}")

def _s(val, low, high, inv=False):
    if pd.isna(val): return "n"
    ok   = (val <= low)  if inv else (val >= high)
    warn = (val <= high) if inv else (val >= low)
    return "g" if ok else ("a" if warn else "r")

def kpi(label, value, sub=None, color=None):
    c    = color or PRIMARY
    scls = "g" if sub and str(sub).startswith("+") else ("r" if sub and str(sub).startswith("-") else "")
    sh   = f'<div class="kpi-sub {scls}">{sub}</div>' if sub else ""
    return f'<div class="kpi" style="--c:{c}"><div class="kpi-lbl">{label}</div><div class="kpi-val">{value}</div>{sh}</div>'

@st.cache_data(ttl=1800, show_spinner="Loading agent data…")
def load_agents(d0, d1):
    con = _connect()
    df  = con.execute(f"""
        SELECT * FROM gold.gold_agent_performance_daily
        WHERE date BETWEEN '{d0}' AND '{d1}'
          AND agent_name NOT IN {EXCLUDE}
        ORDER BY date DESC, appointments_booked DESC
    """).df()
    con.close(); return df

@st.cache_data(ttl=1800, show_spinner="Loading lead response data…")
def load_leads(d0, d1):
    con = _connect()
    df  = con.execute(f"""
        SELECT lead_id, first_name, last_name, phone, created_date, created_at,
               total_call_attempts, mins_to_first_call, first_call_at,
               last_call_agent, has_been_called, has_qualified_conversation,
               appointment_booked, appointment_status, customer_type, is_sold
        FROM gold.gold_lead_activity
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
        ORDER BY created_at DESC
    """).df()
    con.close(); return df

@st.cache_data(ttl=1800, show_spinner="Loading trend…")
def load_trend(d0, d1):
    con = _connect()
    df  = con.execute(f"""
        SELECT date,
               SUM(appointments_booked)     AS appointments,
               SUM(outbound_calls)          AS outbound_calls,
               SUM(qualified_conversations) AS qual_convos,
               SUM(missed_calls)            AS missed_calls
        FROM gold.gold_agent_performance_daily
        WHERE date BETWEEN '{d0}' AND '{d1}'
          AND agent_name NOT IN {EXCLUDE}
        GROUP BY date ORDER BY date
    """).df()
    con.close(); return df

# ── PERIOD SELECTOR ───────────────────────────────────────────────────────────

PRESETS = ["Yesterday", "Today", "This Week", "Last 7 Working Days",
           "This Month", "Last 30 Days", "Custom"]

def _working_range(n):
    days, d = [], date.today() - timedelta(1)
    while len(days) < n:
        if d.weekday() < 5: days.append(d)
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
  <div class="hdr-eye">Trust Electric Heating &nbsp;·&nbsp; Telesales Operations</div>
  <h1 class="hdr-title">TELESALES COMMAND CENTRE</h1>
  <div class="hdr-glow"></div>
</div>
""", unsafe_allow_html=True)

hl, hm, hn, hr_ = st.columns([2, 2, 2, 2])
with hl:
    preset = st.selectbox("Period", PRESETS, index=0, label_visibility="collapsed")
if preset == "Custom":
    with hm: d0 = st.date_input("From", value=today-timedelta(7), max_value=today, label_visibility="collapsed")
    with hn: d1 = st.date_input("To",   value=today-timedelta(1), max_value=today, label_visibility="collapsed")
else:
    d0, d1 = PRESET_DATES[preset]
with hr_:
    rc1, rc2 = st.columns([1, 2])
    with rc1:
        if st.button("↺  REFRESH", use_container_width=True):
            st.cache_data.clear(); st.rerun()
    with rc2:
        st.markdown(
            f'<div style="font-family:\'Share Tech Mono\',monospace;font-size:.62rem;color:{DIM};'
            f'padding-top:12px;letter-spacing:2px;text-align:right">GOLD · MOTHERDUCK · 30 MIN</div>',
            unsafe_allow_html=True)

s0 = d0.strftime("%Y-%m-%d"); s1 = d1.strftime("%Y-%m-%d")
period_lbl = (d0.strftime("%A %d %B %Y").upper() if d0 == d1
              else (d0.strftime("%d %b") + " – " + d1.strftime("%d %b %Y")).upper())
st.markdown(f'<div style="font-family:\'Share Tech Mono\',monospace;font-size:.78rem;color:{PRIMARY};'
            f'letter-spacing:3px;margin-bottom:1.2rem">▸ {period_lbl}</div>', unsafe_allow_html=True)

df_ag = load_agents(s0, s1)
df_ld = load_leads(s0, s1)
df_tr = load_trend(s0, s1)

# ── TABS ──────────────────────────────────────────────────────────────────────
t1, t2, t3 = st.tabs(["DAILY OPS", "AGENTS", "LEAD RESPONSE"])

# ═══════════════ TAB 1 — DAILY OPS ════════════════════════════════════════════
with t1:
    if df_ag.empty:
        st.warning(f"No agent data for {period_lbl}.")
    else:
        ta   = int(df_ag["appointments_booked"].sum())
        to_  = int(df_ag["outbound_calls"].sum())
        ti   = int(df_ag["inbound_calls"].sum())
        tm   = int(df_ag["missed_calls"].sum())
        on   = int(df_ag["on_target"].sum())
        na   = len(df_ag)
        tgt  = to_ / 3
        pct_on  = on / na * 100 if na else 0
        miss_r  = tm / (to_ + tm) * 100 if (to_ + tm) else 0
        n_days  = (d1 - d0).days + 1

        called = df_ld[df_ld["mins_to_first_call"].notna()]
        avg_r  = called["mins_to_first_call"].mean() if len(called) else None

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        d_appt = ta - tgt
        with c1: st.markdown(kpi("APPOINTMENTS", f"{ta:,}", f"{d_appt:+.0f} vs target", GREEN if d_appt >= 0 else RED), unsafe_allow_html=True)
        with c2: st.markdown(kpi("OUTBOUND", f"{to_:,}", f"{n_days}-day period", PRIMARY), unsafe_allow_html=True)
        with c3: st.markdown(kpi("INBOUND", f"{ti:,}", "completed calls", DIM), unsafe_allow_html=True)
        with c4: st.markdown(kpi("MISSED", f"{tm:,}", f"{miss_r:.1f}% miss rate", STATUS[_s(miss_r, 10, 20, inv=True)]), unsafe_allow_html=True)
        with c5: st.markdown(kpi("ON TARGET", f"{on}/{na}", f"{pct_on:.0f}% agents", STATUS[_s(pct_on, 50, 80)]), unsafe_allow_html=True)
        with c6:
            if avg_r is not None:
                st.markdown(kpi("AVG RESPONSE", f"{avg_r:.1f}m", "same-day leads", STATUS[_s(avg_r, 5, 10, inv=True)]), unsafe_allow_html=True)
            else:
                st.markdown(kpi("AVG RESPONSE", "—", "no same-day data", DIM), unsafe_allow_html=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        bc, tc = st.columns([6, 4])

        with bc:
            ag_agg = df_ag.groupby("agent_name").agg(
                appts=("appointments_booked", "sum"),
                outbound=("outbound_calls", "sum"),
                pct_on=("on_target", "mean"),
            ).reset_index()
            ag_agg["tgt"] = (ag_agg["outbound"] / 3).round(1)
            ag_agg["col"] = ag_agg["pct_on"].apply(lambda x: GREEN if x >= 0.5 else RED)
            ag_agg = ag_agg.sort_values("appts", ascending=True)
            fig = go.Figure()
            fig.add_bar(x=ag_agg["appts"], y=ag_agg["agent_name"], orientation="h",
                marker_color=ag_agg["col"], text=ag_agg["appts"],
                textposition="outside", textfont=dict(color=WHITE, family="Bebas Neue", size=15), name="Appointments")
            fig.add_scatter(x=ag_agg["tgt"], y=ag_agg["agent_name"], mode="markers", name="Target (1:3)",
                marker=dict(symbol="line-ns", size=14, color=PRIMARY, line=dict(width=2, color=PRIMARY)))
            fig.update_layout(title="APPOINTMENTS VS TARGET", height=400, **CHART)
            st.plotly_chart(fig, use_container_width=True)

        with tc:
            if not df_tr.empty and len(df_tr) > 1:
                fig2 = make_subplots(specs=[[{"secondary_y": True}]])
                fig2.add_trace(go.Scatter(x=df_tr["date"], y=df_tr["appointments"], name="Appts",
                    line=dict(color=GREEN, width=3), fill="tozeroy", fillcolor="rgba(0,230,118,0.08)"), secondary_y=False)
                fig2.add_trace(go.Bar(x=df_tr["date"], y=df_tr["outbound_calls"], name="Calls",
                    marker_color="rgba(0,212,255,0.15)", marker_line_width=0), secondary_y=True)
                fig2.update_layout(title="DAILY TREND", height=400, **CHART)
                fig2.update_yaxes(gridcolor="rgba(0,212,255,0.06)", linecolor=GREY, secondary_y=False)
                fig2.update_yaxes(gridcolor="rgba(0,0,0,0)", secondary_y=True)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Select a multi-day period to see the trend chart.")

        st.markdown("<hr>", unsafe_allow_html=True)
        rc_col, qc_col = st.columns(2)

        with rc_col:
            rd = pd.DataFrame({
                "Cat": ["≤ 5 MIN", "6–10 MIN", "> 10 MIN", "NOT CALLED"],
                "N": [int((df_ld["mins_to_first_call"] <= 5).sum()),
                      int(((df_ld["mins_to_first_call"] > 5) & (df_ld["mins_to_first_call"] <= 10)).sum()),
                      int((df_ld["mins_to_first_call"] > 10).sum()),
                      int(df_ld["mins_to_first_call"].isna().sum())]})
            fig3 = px.pie(rd, values="N", names="Cat", hole=0.6, color="Cat",
                color_discrete_map={"≤ 5 MIN": GREEN, "6–10 MIN": AMBER, "> 10 MIN": RED, "NOT CALLED": GREY},
                title=f"LEAD RESPONSE — {len(df_ld):,} LEADS")
            fig3.update_traces(textinfo="label+value", textfont=dict(family="Share Tech Mono", size=11))
            fig3.update_layout(height=360, showlegend=False, **CHART)
            st.plotly_chart(fig3, use_container_width=True)
            if d0 != d1:
                st.caption("mins_to_first_call is only set for same-day calls — cross-day calls show as Not Called.")

        with qc_col:
            dq = df_ag.groupby("agent_name").agg(
                qual=("qualified_conversations", "sum"),
                qual_o=("qualified_outbound_conversations", "sum"),
                appts=("appointments_booked", "sum"),
            ).reset_index()
            dq = dq[dq["qual"] > 0]
            dq["ratio"] = ((dq["qual"] + dq["qual_o"]) / dq["appts"].replace(0, float("nan"))).round(1)
            dq = dq.sort_values("ratio", na_position="last")
            fig4 = px.bar(dq, x="ratio", y="agent_name", orientation="h", text="ratio",
                color="ratio", color_continuous_scale=[[0, GREEN], [0.4, AMBER], [1, RED]], range_color=[1, 10],
                title="QUAL CONVOS PER APPOINTMENT")
            fig4.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                textfont=dict(color=WHITE, family="Bebas Neue", size=14))
            fig4.update_layout(height=360, coloraxis_showscale=False, **CHART)
            fig4.update_yaxes(autorange="reversed")
            st.plotly_chart(fig4, use_container_width=True)

# ═══════════════ TAB 2 — AGENTS ═══════════════════════════════════════════════
with t2:
    if df_ag.empty:
        st.warning("No agent data for selected period.")
    else:
        agg = df_ag.groupby("agent_name").agg(
            dept=("department", "first"),
            outbound=("outbound_calls", "sum"),
            inbound=("inbound_calls", "sum"),
            missed=("missed_calls", "sum"),
            talk=("total_talk_time_seconds", "sum"),
            qual=("qualified_conversations", "sum"),
            qual_o=("qualified_outbound_conversations", "sum"),
            appts=("appointments_booked", "sum"),
            sales=("sales_confirmed", "sum"),
            deal_val=("total_deal_value", "sum"),
            unique_leads=("unique_leads_contacted", "sum"),
        ).reset_index()
        agg["ratio"] = ((agg["qual"] + agg["qual_o"]) / agg["appts"].replace(0, float("nan"))).round(1)
        agg["cpa"]   = (agg["outbound"] / agg["appts"].replace(0, float("nan"))).round(1)
        agg["talk_h"] = (agg["talk"] / 3600).round(1)
        agg["on"]    = agg["cpa"] <= 3
        agg = agg.sort_values("appts", ascending=False)

        sl, sr = st.columns(2)
        with sl:
            mo = agg["outbound"].max() if not agg.empty else 1
            agg["_lbl"] = agg.apply(lambda r: r["agent_name"] if r["outbound"] >= max(20, mo * 0.1) else "", axis=1)
            fig_sc = px.scatter(agg, x="outbound", y="appts", size="qual",
                color="on", color_discrete_map={True: GREEN, False: RED},
                text="_lbl", hover_name="agent_name",
                hover_data={"ratio": ":.1f", "cpa": ":.1f", "qual": True, "_lbl": False, "on": False},
                title="EFFICIENCY — CALLS vs APPOINTMENTS",
                labels={"outbound": "Outbound Calls", "appts": "Appointments", "qual": "Qual Convos"})
            fig_sc.add_trace(go.Scatter(x=[0, mo], y=[0, mo / 3], mode="lines", name="1:3 Target",
                line=dict(dash="dash", color=PRIMARY, width=1)))
            fig_sc.update_traces(textposition="top center",
                textfont=dict(size=11, color=WHITE, family="Barlow"),
                selector=dict(mode="markers+text"))
            fig_sc.update_layout(height=460, **CHART)
            st.plotly_chart(fig_sc, use_container_width=True)

        with sr:
            fig_cv = px.bar(agg.sort_values("ratio", na_position="last"),
                x="ratio", y="agent_name", orientation="h",
                color="ratio", color_continuous_scale=[[0, GREEN], [0.4, AMBER], [1, RED]],
                range_color=[1, 12], text="ratio", title="QUAL CONVOS PER APPOINTMENT")
            fig_cv.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                textfont=dict(color=WHITE, family="Bebas Neue", size=14))
            fig_cv.update_layout(height=440, coloraxis_showscale=False, **CHART)
            fig_cv.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_cv, use_container_width=True)

        st.markdown('<div class="sec">LEADERBOARD</div>', unsafe_allow_html=True)
        disp = agg[["agent_name", "dept", "outbound", "inbound", "missed",
                     "unique_leads", "qual", "appts", "sales", "deal_val", "talk_h", "ratio", "cpa", "on"]].copy()
        disp.columns = ["Agent", "Dept", "Outbound", "Inbound", "Missed",
                        "Unique Leads", "Qual Convos", "Appts", "Sales", "Deal Value (£)", "Talk (h)", "Conv Ratio", "Calls/Appt", "On Target"]
        disp["On Target"] = disp["On Target"].map({True: "✅", False: "❌"})
        disp["Deal Value (£)"] = disp["Deal Value (£)"].fillna(0).apply(lambda x: f"£{x:,.0f}" if x > 0 else "—")
        st.dataframe(disp, use_container_width=True, hide_index=True,
            column_config={
                "Appts":      st.column_config.ProgressColumn(min_value=0, max_value=int(disp["Appts"].max()), format="%d"),
                "Sales":      st.column_config.ProgressColumn(min_value=0, max_value=max(int(disp["Sales"].max()), 1), format="%d"),
                "Conv Ratio": st.column_config.NumberColumn(format="%.1f"),
                "Calls/Appt": st.column_config.NumberColumn(format="%.1f"),
                "Talk (h)":   st.column_config.NumberColumn(format="%.1f"),
            })

        if len(df_tr) > 1:
            st.markdown('<div class="sec">DAILY SPARKLINES — APPOINTMENTS</div>', unsafe_allow_html=True)
            dpiv = df_ag.pivot_table(index="date", columns="agent_name",
                values="appointments_booked", aggfunc="sum", fill_value=0).reset_index()
            pal = [PRIMARY, GREEN, AMBER, RED, PURPLE, "#80deea", "#ffcc02", "#ff8a65"]
            fig_sp = go.Figure()
            for i, ag in enumerate(dpiv.columns[1:]):
                fig_sp.add_trace(go.Scatter(x=dpiv["date"], y=dpiv[ag], name=ag, mode="lines+markers",
                    line=dict(width=2, color=pal[i % len(pal)]), marker=dict(size=5)))
            fig_sp.update_layout(height=280, title="APPOINTMENTS PER DAY PER AGENT", **CHART)
            st.plotly_chart(fig_sp, use_container_width=True)

# ═══════════════ TAB 3 — LEAD RESPONSE ════════════════════════════════════════
with t3:
    if df_ld.empty:
        st.info(f"No leads for {period_lbl}.")
    else:
        nl  = len(df_ld)
        cal = int(df_ld["has_been_called"].sum())
        nc  = nl - cal
        w5  = int((df_ld["mins_to_first_call"] <= 5).sum())
        w10 = int(((df_ld["mins_to_first_call"] > 5) & (df_ld["mins_to_first_call"] <= 10)).sum())
        ov10= int((df_ld["mins_to_first_call"] > 10).sum())
        avg_r = df_ld["mins_to_first_call"].mean()
        apt = int((df_ld["appointment_booked"] == "Yes").sum())

        r1, r2, r3, r4, r5 = st.columns(5)
        with r1: st.markdown(kpi("LEADS IN PERIOD", f"{nl:,}", period_lbl[:20], PRIMARY), unsafe_allow_html=True)
        with r2:
            pc = cal / nl * 100 if nl else 0
            st.markdown(kpi("CALLED", f"{cal:,}", f"{pc:.0f}% coverage", STATUS[_s(pc, 60, 85)]), unsafe_allow_html=True)
        with r3:
            p5 = w5 / cal * 100 if cal else 0
            st.markdown(kpi("≤ 5 MIN", f"{w5:,}", f"{p5:.0f}% of called", STATUS[_s(p5, 40, 70)]), unsafe_allow_html=True)
        with r4:
            st.markdown(kpi("AVG RESPONSE", f"{avg_r:.1f}m" if pd.notna(avg_r) else "—",
                "same-day calls only", STATUS[_s(avg_r, 5, 10, inv=True)] if pd.notna(avg_r) else "n"),
                unsafe_allow_html=True)
        with r5:
            cv = apt / cal * 100 if cal else 0
            st.markdown(kpi("APPOINTMENTS", f"{apt:,}", f"{cv:.0f}% of called", GREEN if cv >= 33 else RED), unsafe_allow_html=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        pie_c, bar_c = st.columns([4, 6])

        with pie_c:
            rd2 = pd.DataFrame({
                "Cat": ["≤ 5 MIN", "6–10 MIN", "> 10 MIN", "NOT CALLED"],
                "N":   [w5, w10, ov10, nc]})
            fig_pie = px.pie(rd2, values="N", names="Cat", hole=0.62, color="Cat",
                color_discrete_map={"≤ 5 MIN": GREEN, "6–10 MIN": AMBER, "> 10 MIN": RED, "NOT CALLED": GREY},
                title="RESPONSE TIME BREAKDOWN")
            fig_pie.update_traces(textinfo="label+value", textfont=dict(family="Share Tech Mono", size=11))
            fig_pie.update_layout(height=280, showlegend=False, **CHART)
            st.plotly_chart(fig_pie, use_container_width=True)
            if d0 != d1:
                st.caption("Response time only tracked for same-day calls.")

            # Customer type breakdown
            ct = df_ld["customer_type"].fillna("Unknown").value_counts().reset_index()
            ct.columns = ["Type", "Count"]
            ct["Type"] = ct["Type"].str.capitalize()
            fig_ct = px.pie(ct, values="Count", names="Type", hole=0.62,
                color="Type",
                color_discrete_map={"Domestic": PRIMARY, "Commercial": PURPLE, "Unknown": GREY},
                title="DOMESTIC vs COMMERCIAL")
            fig_ct.update_traces(textinfo="label+value", textfont=dict(family="Share Tech Mono", size=11))
            fig_ct.update_layout(height=260, showlegend=False, **CHART)
            st.plotly_chart(fig_ct, use_container_width=True)

        with bar_c:
            ac = df_ld[df_ld["last_call_agent"].notna()]["last_call_agent"].value_counts().reset_index()
            ac.columns = ["Agent", "Leads Called"]
            if not ac.empty:
                fig_ac = px.bar(ac.head(14), x="Leads Called", y="Agent", orientation="h",
                    title="LEADS CALLED PER AGENT", color_discrete_sequence=[PRIMARY], text="Leads Called")
                fig_ac.update_traces(textposition="outside",
                    textfont=dict(color=WHITE, family="Bebas Neue", size=14))
                fig_ac.update_layout(height=380, **CHART)
                fig_ac.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_ac, use_container_width=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown('<div class="sec">LEAD RESPONSE TRACKER</div>', unsafe_allow_html=True)

        dsp = df_ld[["first_name", "last_name", "phone", "customer_type", "created_date",
                      "total_call_attempts", "mins_to_first_call", "last_call_agent",
                      "has_qualified_conversation", "appointment_booked", "is_sold"]].copy().head(500)
        dsp.insert(0, "Name",
            dsp["first_name"].fillna("").str.strip() + " " + dsp["last_name"].fillna("").str.strip())
        dsp = dsp.drop(columns=["first_name", "last_name"])
        dsp = dsp.rename(columns={
            "phone": "Phone", "customer_type": "Type", "created_date": "Created",
            "total_call_attempts": "Calls", "mins_to_first_call": "Mins",
            "last_call_agent": "Last Agent", "has_qualified_conversation": "Qualified",
            "appointment_booked": "Appt", "is_sold": "Sold",
        })
        if "Appt"      in dsp.columns: dsp["Appt"]      = dsp["Appt"].map({"Yes": "✅"}).fillna("—")
        if "Qualified" in dsp.columns: dsp["Qualified"]  = dsp["Qualified"].map({True: "✅", False: "—"})
        if "Sold"      in dsp.columns: dsp["Sold"]       = dsp["Sold"].map({True: "✅", False: "—"})
        if "Type"      in dsp.columns: dsp["Type"]       = dsp["Type"].fillna("?")

        def _cm(v):
            if pd.isna(v): return "background-color:#3d1515;color:white"
            if v <= 5:     return "background-color:#0d2a1a;color:white"
            if v <= 10:    return "background-color:#2a200d;color:white"
            return           "background-color:#3d1515;color:white"

        styled = dsp.style.map(_cm, subset=["Mins"]) if "Mins" in dsp.columns else dsp
        st.dataframe(styled, use_container_width=True, hide_index=True,
            column_config={"Mins": st.column_config.NumberColumn(format="%.0f")}, height=440)
        if len(df_ld) > 500:
            st.caption(f"Showing first 500 of {len(df_ld):,} leads.")
