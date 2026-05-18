import os
from datetime import date, timedelta

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Trust Telesales",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Gradient header strip */
    .header-strip {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        border-radius: 12px;
        padding: 18px 24px;
        margin-bottom: 1.2rem;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .header-strip h1 {
        margin: 0 !important;
        font-size: 1.8rem !important;
        font-weight: 800 !important;
        color: white !important;
        letter-spacing: -0.5px;
    }
    .header-strip .sub {
        color: #a0aec0;
        font-size: 0.85rem;
        margin-top: 2px;
    }

    /* Dark card styling for metrics */
    [data-testid="metric-container"] {
        background: linear-gradient(145deg, #1a1a2e, #16213e);
        border: 1px solid #2d2d44;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    [data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }

    /* Platform badge pills */
    .platform-google { background:#4285f4; color:white; padding:2px 8px; border-radius:4px; font-size:0.8rem; font-weight:600; }
    .platform-meta   { background:#a855f7; color:white; padding:2px 8px; border-radius:4px; font-size:0.8rem; font-weight:600; }
    .platform-bing   { background:#f59e0b; color:white; padding:2px 8px; border-radius:4px; font-size:0.8rem; font-weight:600; }

    /* Ad spend mini-banner */
    .ad-banner {
        background: linear-gradient(90deg, rgba(66,133,244,0.12), rgba(168,85,247,0.12), rgba(245,158,11,0.12));
        border: 1px solid #2d2d44;
        border-radius: 10px;
        padding: 10px 20px;
        display: flex;
        gap: 24px;
        align-items: center;
        margin-bottom: 1rem;
    }
    .ad-banner .label { color: #a0aec0; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
    .ad-banner .value { font-size: 1.1rem; font-weight: 700; color: white; }

    /* Tab styling */
    [data-testid="stTabs"] button { font-size: 1rem; font-weight: 600; }

    /* Tighter header */
    h1 { margin-bottom: 0.2rem !important; }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }

    /* Dataframe header */
    .stDataFrame thead { background: #1a1a2e; }
</style>
""", unsafe_allow_html=True)

GREEN  = "#00b894"
AMBER  = "#fdcb6e"
RED    = "#d63031"
BLUE   = "#0984e3"
GREY   = "#636e72"

GOOGLE_BLUE   = "#4285f4"
META_PURPLE   = "#a855f7"
BING_AMBER    = "#f59e0b"
PLATFORM_COLORS = {"Google": GOOGLE_BLUE, "Meta": META_PURPLE, "Bing": BING_AMBER}

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font_color="white",
    margin=dict(t=40, b=20, l=10, r=10),
    xaxis=dict(gridcolor="#2d2d44", linecolor="#2d2d44"),
    yaxis=dict(gridcolor="#2d2d44", linecolor="#2d2d44"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, bgcolor="rgba(0,0,0,0)"),
)

EXCLUDE_AGENTS = ("Trust Admin", "admin", "Paris")

# ─── DATA ──────────────────────────────────────────────────────────────────────

def _connect() -> duckdb.DuckDBPyConnection:
    token = os.getenv("MOTHERDUCK_TOKEN", "")
    return duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")


@st.cache_data(ttl=1800, show_spinner="Loading agent data…")
def load_agent_perf(date_from: str, date_to: str) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT *
        FROM gold.gold_agent_performance_daily
        WHERE date BETWEEN '{date_from}' AND '{date_to}'
        AND agent_name NOT IN {EXCLUDE_AGENTS}
        ORDER BY date DESC, appointments_booked DESC
    """).df()
    con.close()
    return df


@st.cache_data(ttl=1800, show_spinner="Loading leads…")
def load_leads(created_date: str) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT *,
            CASE
                WHEN lead_status = 'customer'                            THEN 'sold'
                WHEN lead_status = 'unqualified'                         THEN 'lost'
                WHEN appointment_booked = 'Yes'                          THEN 'appointed'
                WHEN created_date = CURRENT_DATE                         THEN 'fresh'
                WHEN created_date >= CURRENT_DATE - INTERVAL 30 DAYS    THEN 'backlog'
                ELSE 'aged_backlog'
            END AS lead_type
        FROM gold.gold_lead_activity
        WHERE created_date = '{created_date}'
        ORDER BY created_at
    """).df()
    con.close()
    return df


@st.cache_data(ttl=1800, show_spinner="Loading trend…")
def load_trend(days: int = 14) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT
            date,
            SUM(appointments_booked)             AS appointments,
            SUM(outbound_calls)                  AS outbound_calls,
            SUM(qualified_conversations)         AS qualified_conversations,
            SUM(missed_calls)                    AS missed_calls,
            COUNT(DISTINCT CASE WHEN on_target THEN agent_name END) AS agents_on_target,
            COUNT(DISTINCT agent_name)           AS total_agents
        FROM gold.gold_agent_performance_daily
        WHERE date >= CURRENT_DATE - {days}
        AND agent_name NOT IN {EXCLUDE_AGENTS}
        GROUP BY date
        ORDER BY date
    """).df()
    con.close()
    return df


@st.cache_data(ttl=1800, show_spinner="Loading ad spend…")
def load_campaign_attribution(date_from: str, date_to: str) -> pd.DataFrame:
    con = _connect()
    df = con.execute(f"""
        SELECT *
        FROM gold.gold_campaign_attribution
        WHERE date BETWEEN '{date_from}' AND '{date_to}'
        ORDER BY date DESC, spend_gbp DESC
    """).df()
    con.close()
    return df


def _colour(value, low, high, invert=False):
    if pd.isna(value):
        return "⚪"
    ok = value >= high if not invert else value <= low
    warn = value >= low if not invert else value <= high
    if ok:
        return "🟢"
    if warn:
        return "🟡"
    return "🔴"


# ─── HEADER ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="header-strip">
    <span style="font-size:2rem">⚡</span>
    <div>
        <h1>Trust Electric Heating</h1>
        <div class="sub">Telesales Intelligence Dashboard</div>
    </div>
</div>
""", unsafe_allow_html=True)

hdr_left, hdr_mid, hdr_right = st.columns([3, 2, 3])
with hdr_left:
    selected_date = st.date_input(
        "Viewing date",
        value=date.today() - timedelta(days=1),
        max_value=date.today(),
        label_visibility="collapsed",
    )
with hdr_mid:
    if st.button("↺  Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with hdr_right:
    st.caption("Data refreshes every 30 min via GitHub Actions pipeline.")

date_str = selected_date.strftime("%Y-%m-%d")
date_label = selected_date.strftime("%A %d %B %Y")
st.subheader(date_label)

# Load data for selected date
df_agents = load_agent_perf(date_str, date_str)
df_leads  = load_leads(date_str)
df_trend  = load_trend(14)
df_attr_day = load_campaign_attribution(date_str, date_str)

# ─── TABS ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊  Daily Snapshot",
    "🏆  Agent Leaderboard",
    "📞  Lead Pipeline",
    "💰  Ad Spend",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DAILY SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════

with tab1:

    if df_agents.empty:
        st.warning(f"No call data found for {date_label}. Is this a weekend or bank holiday?")
    else:
        # Aggregated totals
        total_appts    = int(df_agents["appointments_booked"].sum())
        total_out      = int(df_agents["outbound_calls"].sum())
        total_missed   = int(df_agents["missed_calls"].sum())
        total_qual     = int(df_agents["qualified_conversations"].sum())
        on_target_n    = int(df_agents["on_target"].sum())
        total_agents_n = len(df_agents)
        appt_target    = total_out / 3
        pct_on_target  = on_target_n / total_agents_n * 100 if total_agents_n else 0
        missed_rate    = total_missed / (total_out + total_missed) * 100 if (total_out + total_missed) else 0

        # Lead response
        called_leads = df_leads[df_leads["mins_to_first_call"].notna()]
        avg_response  = called_leads["mins_to_first_call"].mean() if len(called_leads) else None
        within_5_n    = int((called_leads["mins_to_first_call"] <= 5).sum())
        total_leads_n = len(df_leads)

        # ── KPI ROW ──────────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)

        with k1:
            delta = total_appts - appt_target
            st.metric(
                "Appointments",
                total_appts,
                f"{delta:+.0f} vs target ({appt_target:.0f})",
                delta_color="normal" if delta >= 0 else "inverse",
            )
        with k2:
            st.metric("Outbound Calls", f"{total_out:,}")
        with k3:
            c = _colour(pct_on_target, 50, 80)
            st.metric(f"On Target {c}", f"{on_target_n} / {total_agents_n}", f"{pct_on_target:.0f}%")
        with k4:
            if avg_response is not None:
                c = _colour(avg_response, 5, 10, invert=True)
                st.metric(f"Avg Response {c}", f"{avg_response:.1f} min", "Target ≤ 5 min",
                          delta_color="inverse")
            else:
                st.metric("Avg Response", "No calls yet")
        with k5:
            c = _colour(missed_rate, 10, 20, invert=True)
            st.metric(f"Missed Calls {c}", total_missed, f"{missed_rate:.1f}% of calls",
                      delta_color="inverse")

        # ── AD SPEND BANNER ───────────────────────────────────────────────────
        if not df_attr_day.empty:
            spend_by_platform = df_attr_day.set_index("platform")["spend_gbp"].to_dict()
            g_spend = spend_by_platform.get("Google", 0)
            m_spend = spend_by_platform.get("Meta", 0)
            b_spend = spend_by_platform.get("Bing", 0)
            total_spend = g_spend + m_spend + b_spend

            leads_by_platform = df_attr_day.set_index("platform")["leads"].to_dict()
            g_leads = int(leads_by_platform.get("Google", 0))
            m_leads = int(leads_by_platform.get("Meta", 0))
            b_leads = int(leads_by_platform.get("Bing", 0))

            ab1, ab2, ab3, ab4, ab5 = st.columns(5)
            with ab1:
                st.metric("💙 Google Spend", f"£{g_spend:,.0f}", f"{g_leads} leads")
            with ab2:
                st.metric("💜 Meta Spend", f"£{m_spend:,.0f}", f"{m_leads} leads")
            with ab3:
                st.metric("🟡 Bing Spend", f"£{b_spend:,.0f}", f"{b_leads} leads")
            with ab4:
                st.metric("💳 Total Ad Spend", f"£{total_spend:,.0f}")
            with ab5:
                total_paid_leads = g_leads + m_leads + b_leads
                blended_cpl = total_spend / total_paid_leads if total_paid_leads else 0
                c = _colour(blended_cpl, 50, 80, invert=True)
                st.metric(f"Blended CPL {c}", f"£{blended_cpl:.0f}" if blended_cpl else "—")

        st.divider()

        # ── ROW 2: BAR + TREND ───────────────────────────────────────────────
        col_bar, col_trend = st.columns([6, 4])

        with col_bar:
            df_chart = df_agents.copy()
            df_chart["target"] = (df_chart["outbound_calls"] / 3).round(1)
            df_chart["bar_colour"] = df_chart["on_target"].map({True: GREEN, False: RED})

            fig = go.Figure()
            fig.add_bar(
                x=df_chart["appointments_booked"],
                y=df_chart["agent_name"],
                orientation="h",
                name="Appointments",
                marker_color=df_chart["bar_colour"],
                text=df_chart["appointments_booked"],
                textposition="outside",
                textfont=dict(color="white"),
            )
            fig.add_scatter(
                x=df_chart["target"],
                y=df_chart["agent_name"],
                mode="markers",
                name="Target (1 per 3 calls)",
                marker=dict(symbol="line-ns", size=14, color="white",
                            line=dict(width=2, color="white")),
            )
            fig.update_layout(
                title="Appointments vs Target by Agent",
                height=420,
                **CHART_LAYOUT,
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

        with col_trend:
            if not df_trend.empty:
                fig2 = make_subplots(specs=[[{"secondary_y": True}]])
                fig2.add_trace(
                    go.Scatter(
                        x=df_trend["date"], y=df_trend["appointments"],
                        name="Appointments", line=dict(color=GREEN, width=3),
                        fill="tozeroy", fillcolor="rgba(0,184,148,0.15)",
                    ),
                    secondary_y=False,
                )
                fig2.add_trace(
                    go.Bar(
                        x=df_trend["date"], y=df_trend["outbound_calls"],
                        name="Outbound Calls", marker_color="rgba(9,132,227,0.25)",
                    ),
                    secondary_y=True,
                )
                fig2.update_layout(title="14-Day Trend", height=420, **CHART_LAYOUT)
                fig2.update_yaxes(title_text="Appointments", secondary_y=False, gridcolor="#2d2d44")
                fig2.update_yaxes(title_text="Calls", secondary_y=True, gridcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig2, use_container_width=True)

        st.divider()

        # ── ROW 3: RESPONSE TIME + QUAL CONVOS ───────────────────────────────
        col_resp, col_qual = st.columns(2)

        with col_resp:
            resp_data = pd.DataFrame({
                "Category": ["≤ 5 min ✅", "6–10 min ⚠️", "> 10 min ❌", "Not called"],
                "Count": [
                    int((df_leads["mins_to_first_call"] <= 5).sum()),
                    int(((df_leads["mins_to_first_call"] > 5) & (df_leads["mins_to_first_call"] <= 10)).sum()),
                    int((df_leads["mins_to_first_call"] > 10).sum()),
                    int(df_leads["mins_to_first_call"].isna().sum()),
                ],
            })
            fig3 = px.pie(
                resp_data, values="Count", names="Category", hole=0.55,
                color="Category",
                color_discrete_map={
                    "≤ 5 min ✅": GREEN, "6–10 min ⚠️": AMBER,
                    "> 10 min ❌": RED, "Not called": GREY,
                },
                title=f"Fresh Lead Response — {total_leads_n} leads",
            )
            fig3.update_traces(textinfo="label+value")
            fig3.update_layout(height=380, showlegend=False, **CHART_LAYOUT)
            st.plotly_chart(fig3, use_container_width=True)

        with col_qual:
            df_qual = df_agents[["agent_name", "qualified_conversations",
                                  "qualified_outbound_conversations", "appointments_booked"]].copy()
            df_qual = df_qual[df_qual["qualified_conversations"] > 0]
            df_qual["conv_ratio"] = (
                (df_qual["qualified_conversations"] + df_qual["qualified_outbound_conversations"])
                / df_qual["appointments_booked"].replace(0, float("nan"))
            ).round(1)
            df_qual = df_qual.sort_values("conv_ratio", na_position="last")

            fig4 = px.bar(
                df_qual, x="conv_ratio", y="agent_name", orientation="h",
                text="conv_ratio",
                color="conv_ratio",
                color_continuous_scale=[[0, GREEN], [0.4, AMBER], [1, RED]],
                range_color=[1, 10],
                title="Qual Convos per Appointment (lower = better)",
            )
            fig4.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                               textfont=dict(color="white"))
            fig4.update_layout(height=380, coloraxis_showscale=False, **CHART_LAYOUT)
            fig4.update_yaxes(autorange="reversed")
            st.plotly_chart(fig4, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — AGENT LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab2:

    lb_left, lb_right, _ = st.columns([2, 2, 4])
    with lb_left:
        range_from = st.date_input("From", value=date.today() - timedelta(days=7), key="lb_from")
    with lb_right:
        range_to = st.date_input("To", value=date.today() - timedelta(days=1), key="lb_to")

    df_range = load_agent_perf(
        range_from.strftime("%Y-%m-%d"),
        range_to.strftime("%Y-%m-%d"),
    )

    if df_range.empty:
        st.warning("No data for selected range.")
    else:
        df_agg = (
            df_range.groupby("agent_name")
            .agg(
                department=("department", "first"),
                outbound=("outbound_calls", "sum"),
                inbound=("inbound_calls", "sum"),
                missed=("missed_calls", "sum"),
                qual_conv=("qualified_conversations", "sum"),
                qual_out=("qualified_outbound_conversations", "sum"),
                appointments=("appointments_booked", "sum"),
            )
            .reset_index()
        )
        df_agg["conv_ratio"] = (
            (df_agg["qual_conv"] + df_agg["qual_out"])
            / df_agg["appointments"].replace(0, float("nan"))
        ).round(1)
        df_agg["calls_per_appt"] = (
            df_agg["outbound"] / df_agg["appointments"].replace(0, float("nan"))
        ).round(1)
        df_agg["on_target"] = df_agg["calls_per_appt"] <= 3
        df_agg = df_agg.sort_values("appointments", ascending=False)

        # ── SCATTER + CONV RATIO ─────────────────────────────────────────────
        sc_left, sc_right = st.columns(2)

        with sc_left:
            max_out = df_agg["outbound"].max()
            label_threshold = max(30, max_out * 0.1)
            df_agg["_label"] = df_agg.apply(
                lambda r: r["agent_name"] if r["outbound"] >= label_threshold else "", axis=1
            )
            fig_sc = px.scatter(
                df_agg, x="outbound", y="appointments",
                size="qual_conv", color="on_target",
                color_discrete_map={True: GREEN, False: RED},
                text="_label",
                hover_name="agent_name",
                hover_data={
                    "conv_ratio": ":.1f",
                    "calls_per_appt": ":.1f",
                    "qual_conv": True,
                    "_label": False,
                    "on_target": False,
                },
                title="Efficiency: Calls vs Appointments (bubble = qual convos)",
                labels={"outbound": "Outbound Calls", "appointments": "Appointments Booked",
                        "qual_conv": "Qual Convos", "calls_per_appt": "Calls / Appt"},
            )
            fig_sc.add_trace(go.Scatter(
                x=[0, max_out], y=[0, max_out / 3],
                mode="lines", name="Target (1:3)",
                line=dict(dash="dash", color="white", width=1),
            ))
            fig_sc.update_traces(
                textposition="top center",
                textfont=dict(size=12, color="white"),
                selector=dict(mode="markers+text"),
            )
            fig_sc.update_layout(height=480, **CHART_LAYOUT)
            st.plotly_chart(fig_sc, use_container_width=True)

        with sc_right:
            fig_cv = px.bar(
                df_agg.sort_values("conv_ratio", na_position="last"),
                x="conv_ratio", y="agent_name", orientation="h",
                color="conv_ratio",
                color_continuous_scale=[[0, GREEN], [0.4, AMBER], [1, RED]],
                range_color=[1, 12],
                text="conv_ratio",
                title="Qual Convos per Appointment (lower = better)",
            )
            fig_cv.update_traces(texttemplate="%{text:.1f}", textposition="outside",
                                 textfont=dict(color="white"))
            fig_cv.update_layout(height=420, coloraxis_showscale=False, **CHART_LAYOUT)
            fig_cv.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_cv, use_container_width=True)

        # ── LEADERBOARD TABLE ────────────────────────────────────────────────
        st.subheader("Full Leaderboard")
        display = df_agg[["agent_name", "department", "outbound", "missed",
                           "qual_conv", "appointments", "conv_ratio",
                           "calls_per_appt", "on_target"]].copy()
        display.columns = ["Agent", "Dept", "Outbound", "Missed",
                           "Qual Convos", "Appointments", "Conv Ratio",
                           "Calls / Appt", "On Target"]
        display["On Target"] = display["On Target"].map({True: "✅", False: "❌"})

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Appointments": st.column_config.ProgressColumn(
                    min_value=0,
                    max_value=int(display["Appointments"].max()),
                    format="%d",
                ),
                "Conv Ratio": st.column_config.NumberColumn(format="%.1f"),
                "Calls / Appt": st.column_config.NumberColumn(format="%.1f"),
            },
        )

        # ── WEEKLY SPARKLINES ────────────────────────────────────────────────
        st.subheader("Daily Appointments — Each Agent")
        df_daily = df_range.pivot_table(
            index="date", columns="agent_name",
            values="appointments_booked", aggfunc="sum", fill_value=0
        ).reset_index()

        fig_multi = go.Figure()
        for agent in df_daily.columns[1:]:
            fig_multi.add_trace(go.Scatter(
                x=df_daily["date"], y=df_daily[agent],
                name=agent, mode="lines+markers",
                line=dict(width=2),
            ))
        fig_multi.update_layout(
            height=350,
            title="Appointments per Day by Agent",
            **CHART_LAYOUT,
        )
        st.plotly_chart(fig_multi, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LEAD PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

with tab3:

    if df_leads.empty:
        st.info(f"No leads created on {date_label}.")
    else:
        total_l    = len(df_leads)
        called_l   = int(df_leads["has_been_called"].sum())
        not_called = total_l - called_l
        within_5_l = int((df_leads["mins_to_first_call"] <= 5).sum())
        avg_resp_l = df_leads["mins_to_first_call"].mean()
        appt_l     = int((df_leads["appointment_booked"] == "Yes").sum())
        qual_l     = int(df_leads["has_qualified_conversation"].sum()) if "has_qualified_conversation" in df_leads.columns else 0

        # ── KPI ROW ──────────────────────────────────────────────────────────
        p1, p2, p3, p4, p5 = st.columns(5)

        with p1:
            st.metric("Total Leads", total_l)
        with p2:
            pct_c = called_l / total_l * 100 if total_l else 0
            c = _colour(pct_c, 50, 80)
            st.metric(f"Called {c}", f"{called_l} / {total_l}", f"{pct_c:.0f}%")
        with p3:
            pct_5 = within_5_l / called_l * 100 if called_l else 0
            c = _colour(pct_5, 50, 80)
            st.metric(f"≤ 5 min {c}", within_5_l, f"{pct_5:.0f}% of called")
        with p4:
            if pd.notna(avg_resp_l):
                c = _colour(avg_resp_l, 5, 10, invert=True)
                st.metric(f"Avg Response {c}", f"{avg_resp_l:.1f} min")
            else:
                st.metric("Avg Response", "—")
        with p5:
            conv_l = appt_l / called_l * 100 if called_l else 0
            st.metric("Appointments", appt_l, f"{conv_l:.0f}% of called leads")

        st.divider()

        # ── FUNNEL + DONUT ────────────────────────────────────────────────────
        funnel_col, donut_col = st.columns([5, 5])

        with funnel_col:
            funnel_stages = [
                ("Leads In", total_l),
                ("Called", called_l),
                ("Qualified Convos", qual_l),
                ("Appointments", appt_l),
            ]
            fig_funnel = go.Figure(go.Funnel(
                y=[s[0] for s in funnel_stages],
                x=[s[1] for s in funnel_stages],
                textinfo="value+percent initial",
                textfont=dict(size=15, color="white"),
                marker=dict(color=[BLUE, GREEN, AMBER, GREEN],
                            line=dict(width=2, color="rgba(255,255,255,0.15)")),
                connector=dict(line=dict(color="rgba(255,255,255,0.1)", width=1)),
            ))
            fig_funnel.update_layout(
                title=f"Lead Funnel — {date_label}",
                height=360,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="white",
                margin=dict(t=50, b=20, l=10, r=10),
            )
            st.plotly_chart(fig_funnel, use_container_width=True)

        with donut_col:
            resp_df = pd.DataFrame({
                "Category": ["≤ 5 min", "6–10 min", "> 10 min", "Not called"],
                "Count": [
                    int((df_leads["mins_to_first_call"] <= 5).sum()),
                    int(((df_leads["mins_to_first_call"] > 5) & (df_leads["mins_to_first_call"] <= 10)).sum()),
                    int((df_leads["mins_to_first_call"] > 10).sum()),
                    not_called,
                ],
            })
            fig_d = px.pie(
                resp_df, values="Count", names="Category", hole=0.55,
                color="Category",
                color_discrete_map={
                    "≤ 5 min": GREEN, "6–10 min": AMBER,
                    "> 10 min": RED, "Not called": GREY,
                },
                title="Response Time Breakdown",
            )
            fig_d.update_traces(textinfo="label+value")
            fig_d.update_layout(height=360, showlegend=False, **CHART_LAYOUT)
            st.plotly_chart(fig_d, use_container_width=True)

        st.divider()

        tbl_col, chart_col = st.columns([6, 4])

        with tbl_col:
            st.subheader("Lead Response Tracker")

            disp = df_leads[[
                "first_name", "last_name", "phone",
                "total_call_attempts", "mins_to_first_call",
                "last_call_agent", "has_qualified_conversation",
                "appointment_booked",
            ]].copy()

            disp.insert(0, "Name",
                        disp["first_name"].fillna("").str.strip()
                        + " " + disp["last_name"].fillna("").str.strip())
            disp = disp.drop(columns=["first_name", "last_name"])
            disp.columns = ["Name", "Phone", "Attempts", "Mins to Call",
                             "Last Agent", "Qualified", "Appointment"]

            disp["Appointment"] = disp["Appointment"].map({"Yes": "✅"}).fillna("—")
            disp["Qualified"]   = disp["Qualified"].map({True: "✅", False: "—"})

            def colour_response(val):
                if pd.isna(val):
                    return "background-color: #3d1c1c; color: white"
                if val <= 5:
                    return "background-color: #1c3d2a; color: white"
                if val <= 10:
                    return "background-color: #3d3419; color: white"
                return "background-color: #3d1c1c; color: white"

            styled = disp.style.map(colour_response, subset=["Mins to Call"])
            st.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Mins to Call": st.column_config.NumberColumn(format="%.0f min"),
                    "Attempts": st.column_config.NumberColumn(format="%d"),
                },
                height=420,
            )

        with chart_col:
            # Who called these leads
            agent_counts = (
                df_leads[df_leads["last_call_agent"].notna()]["last_call_agent"]
                .value_counts()
                .reset_index()
            )
            agent_counts.columns = ["Agent", "Leads"]
            if not agent_counts.empty:
                fig_a = px.bar(
                    agent_counts, x="Leads", y="Agent", orientation="h",
                    title="Who Called These Leads",
                    color_discrete_sequence=[BLUE],
                    text="Leads",
                )
                fig_a.update_traces(textposition="outside", textfont=dict(color="white"))
                fig_a.update_layout(height=420, **CHART_LAYOUT)
                fig_a.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_a, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — AD SPEND
# ══════════════════════════════════════════════════════════════════════════════

with tab4:

    # Date range for ad spend analysis
    ad_left, ad_right, _ = st.columns([2, 2, 4])
    with ad_left:
        ad_from = st.date_input("From", value=date.today() - timedelta(days=30), key="ad_from")
    with ad_right:
        ad_to = st.date_input("To", value=date.today() - timedelta(days=1), key="ad_to")

    df_attr = load_campaign_attribution(
        ad_from.strftime("%Y-%m-%d"),
        ad_to.strftime("%Y-%m-%d"),
    )

    if df_attr.empty:
        st.warning("No ad spend data for selected range.")
    else:
        # Aggregate per platform over the period
        plat_agg = (
            df_attr.groupby("platform")
            .agg(
                spend=("spend_gbp", "sum"),
                clicks=("clicks", "sum"),
                impressions=("impressions", "sum"),
                leads=("leads", "sum"),
                appointments=("appointments_booked", "sum"),
            )
            .reset_index()
        )
        plat_agg["cpl"] = (plat_agg["spend"] / plat_agg["leads"].replace(0, float("nan"))).round(2)
        plat_agg["cpa"] = (plat_agg["spend"] / plat_agg["appointments"].replace(0, float("nan"))).round(2)
        plat_agg["ctr"] = (plat_agg["clicks"] / plat_agg["impressions"].replace(0, float("nan")) * 100).round(3)

        total_spend = plat_agg["spend"].sum()
        total_leads = int(plat_agg["leads"].sum())
        total_appts_ad = int(plat_agg["appointments"].sum())
        blended_cpl_ad = total_spend / total_leads if total_leads else 0
        blended_cpa_ad = total_spend / total_appts_ad if total_appts_ad else 0

        # ── TOP KPI ROW ───────────────────────────────────────────────────────
        a1, a2, a3, a4, a5 = st.columns(5)
        with a1:
            st.metric("Total Spend", f"£{total_spend:,.0f}")
        with a2:
            st.metric("Paid Leads", f"{total_leads:,}")
        with a3:
            st.metric("Appointments", f"{total_appts_ad:,}")
        with a4:
            st.metric("Blended CPL", f"£{blended_cpl_ad:.0f}" if blended_cpl_ad else "—")
        with a5:
            st.metric("Blended CPA", f"£{blended_cpa_ad:.0f}" if blended_cpa_ad else "—")

        st.divider()

        # ── ROW 2: SPEND SPLIT + SPEND TREND ─────────────────────────────────
        split_col, trend_col = st.columns([4, 6])

        with split_col:
            fig_donut = go.Figure(go.Pie(
                labels=plat_agg["platform"],
                values=plat_agg["spend"].round(0),
                hole=0.6,
                marker=dict(
                    colors=[PLATFORM_COLORS.get(p, GREY) for p in plat_agg["platform"]],
                    line=dict(color="#1a1a2e", width=3),
                ),
                textinfo="label+percent",
                textfont=dict(size=14),
                hovertemplate="<b>%{label}</b><br>£%{value:,.0f}<br>%{percent}<extra></extra>",
            ))
            fig_donut.update_layout(
                title="Spend Share by Platform",
                height=360,
                paper_bgcolor="rgba(0,0,0,0)",
                font_color="white",
                margin=dict(t=50, b=20, l=10, r=10),
                showlegend=False,
                annotations=[dict(
                    text=f"£{total_spend:,.0f}",
                    x=0.5, y=0.5,
                    font=dict(size=20, color="white", family="Arial Black"),
                    showarrow=False,
                )],
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        with trend_col:
            # Daily spend trend by platform
            df_trend_spend = df_attr.copy()
            df_trend_spend["date"] = pd.to_datetime(df_trend_spend["date"])
            df_pivot_spend = df_trend_spend.pivot_table(
                index="date", columns="platform", values="spend_gbp",
                aggfunc="sum", fill_value=0
            ).reset_index()

            fig_spend_trend = go.Figure()
            for platform in ["Google", "Meta", "Bing"]:
                if platform in df_pivot_spend.columns:
                    fig_spend_trend.add_trace(go.Scatter(
                        x=df_pivot_spend["date"],
                        y=df_pivot_spend[platform],
                        name=platform,
                        mode="lines",
                        line=dict(color=PLATFORM_COLORS[platform], width=2.5),
                        fill="tozeroy",
                        fillcolor=PLATFORM_COLORS[platform].replace(")", ", 0.08)").replace("rgb(", "rgba(").replace("#4285f4", "rgba(66,133,244,0.08)").replace("#a855f7", "rgba(168,85,247,0.08)").replace("#f59e0b", "rgba(245,158,11,0.08)"),
                        hovertemplate="<b>%{x|%d %b}</b><br>£%{y:,.2f}<extra>" + platform + "</extra>",
                    ))
            fig_spend_trend.update_layout(
                title="Daily Spend by Platform",
                height=360,
                **CHART_LAYOUT,
            )
            st.plotly_chart(fig_spend_trend, use_container_width=True)

        st.divider()

        # ── ROW 3: CPL TREND + CPA TREND ─────────────────────────────────────
        cpl_col, cpa_col = st.columns(2)

        with cpl_col:
            df_cpl = df_attr[df_attr["cost_per_lead"].notna()].copy()
            df_cpl["date"] = pd.to_datetime(df_cpl["date"])
            df_pivot_cpl = df_cpl.pivot_table(
                index="date", columns="platform", values="cost_per_lead",
                aggfunc="mean"
            ).reset_index()

            fig_cpl = go.Figure()
            for platform in ["Google", "Meta", "Bing"]:
                if platform in df_pivot_cpl.columns:
                    fig_cpl.add_trace(go.Scatter(
                        x=df_pivot_cpl["date"],
                        y=df_pivot_cpl[platform],
                        name=platform,
                        mode="lines+markers",
                        line=dict(color=PLATFORM_COLORS[platform], width=2),
                        marker=dict(size=5),
                        hovertemplate="<b>%{x|%d %b}</b><br>£%{y:.2f} CPL<extra>" + platform + "</extra>",
                    ))
            fig_cpl.update_layout(
                title="Cost Per Lead Trend",
                height=360,
                yaxis=dict(tickprefix="£", gridcolor="#2d2d44"),
                **{k: v for k, v in CHART_LAYOUT.items() if k != "yaxis"},
            )
            st.plotly_chart(fig_cpl, use_container_width=True)

        with cpa_col:
            df_cpa = df_attr[df_attr["cost_per_appointment"].notna()].copy()
            df_cpa["date"] = pd.to_datetime(df_cpa["date"])
            df_pivot_cpa = df_cpa.pivot_table(
                index="date", columns="platform", values="cost_per_appointment",
                aggfunc="mean"
            ).reset_index()

            fig_cpa = go.Figure()
            for platform in ["Google", "Meta", "Bing"]:
                if platform in df_pivot_cpa.columns:
                    fig_cpa.add_trace(go.Scatter(
                        x=df_pivot_cpa["date"],
                        y=df_pivot_cpa[platform],
                        name=platform,
                        mode="lines+markers",
                        line=dict(color=PLATFORM_COLORS[platform], width=2),
                        marker=dict(size=5),
                        hovertemplate="<b>%{x|%d %b}</b><br>£%{y:.2f} CPA<extra>" + platform + "</extra>",
                    ))
            fig_cpa.update_layout(
                title="Cost Per Appointment Trend",
                height=360,
                yaxis=dict(tickprefix="£", gridcolor="#2d2d44"),
                **{k: v for k, v in CHART_LAYOUT.items() if k != "yaxis"},
            )
            st.plotly_chart(fig_cpa, use_container_width=True)

        st.divider()

        # ── ROW 4: LEADS + APPOINTMENTS BAR CHART ────────────────────────────
        leads_col, bar_col = st.columns(2)

        with leads_col:
            # Leads vs Appointments per platform (grouped bar)
            fig_la = go.Figure()
            fig_la.add_bar(
                x=plat_agg["platform"],
                y=plat_agg["leads"],
                name="Leads",
                marker_color=[PLATFORM_COLORS.get(p, GREY) for p in plat_agg["platform"]],
                text=plat_agg["leads"],
                textposition="outside",
                textfont=dict(color="white"),
            )
            fig_la.add_bar(
                x=plat_agg["platform"],
                y=plat_agg["appointments"],
                name="Appointments",
                marker_color=GREEN,
                text=plat_agg["appointments"],
                textposition="outside",
                textfont=dict(color="white"),
                opacity=0.85,
            )
            fig_la.update_layout(
                title="Leads & Appointments by Platform",
                barmode="group",
                height=360,
                **CHART_LAYOUT,
            )
            st.plotly_chart(fig_la, use_container_width=True)

        with bar_col:
            # CPL and CPA bars side by side
            fig_costs = go.Figure()
            fig_costs.add_bar(
                x=plat_agg["platform"],
                y=plat_agg["cpl"],
                name="Cost Per Lead",
                marker_color=[PLATFORM_COLORS.get(p, GREY) for p in plat_agg["platform"]],
                text=["£" + str(int(v)) if pd.notna(v) else "—" for v in plat_agg["cpl"]],
                textposition="outside",
                textfont=dict(color="white"),
            )
            fig_costs.add_bar(
                x=plat_agg["platform"],
                y=plat_agg["cpa"],
                name="Cost Per Appointment",
                marker_color=AMBER,
                text=["£" + str(int(v)) if pd.notna(v) else "—" for v in plat_agg["cpa"]],
                textposition="outside",
                textfont=dict(color="white"),
                opacity=0.85,
            )
            fig_costs.update_layout(
                title="CPL vs CPA by Platform",
                barmode="group",
                height=360,
                yaxis=dict(tickprefix="£", gridcolor="#2d2d44"),
                **{k: v for k, v in CHART_LAYOUT.items() if k != "yaxis"},
            )
            st.plotly_chart(fig_costs, use_container_width=True)

        # ── SUMMARY TABLE ─────────────────────────────────────────────────────
        st.subheader("Platform Summary")
        summary = plat_agg.copy()
        summary["spend"] = summary["spend"].apply(lambda x: f"£{x:,.2f}")
        summary["cpl"]   = summary["cpl"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
        summary["cpa"]   = summary["cpa"].apply(lambda x: f"£{x:,.2f}" if pd.notna(x) else "—")
        summary["ctr"]   = summary["ctr"].apply(lambda x: f"{x:.3f}%" if pd.notna(x) else "—")
        summary.columns  = ["Platform", "Spend", "Clicks", "Impressions",
                             "Leads", "Appointments", "CPL", "CPA", "CTR"]
        st.dataframe(summary, use_container_width=True, hide_index=True)
