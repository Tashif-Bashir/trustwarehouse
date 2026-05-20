import os, json, math
from datetime import date, timedelta

from google.cloud import bigquery
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

EXCLUDE = ("Trust Admin", "admin", "Paris")

st.set_page_config(page_title="Telesales Operations", page_icon="📞", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
html,body,.stApp,[data-testid="stAppViewContainer"]{background:#F5F1EB!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:0.75rem 1.4rem 0.5rem!important;max-width:100%!important;}
[data-testid="stSelectbox"]>label{display:none!important;}
[data-testid="stSelectbox"]>div>div{background:#fff!important;border:1.5px solid rgba(0,0,0,0.10)!important;border-radius:12px!important;color:#1C1917!important;font-family:'DM Sans',system-ui,sans-serif!important;font-size:14px!important;font-weight:500!important;padding:10px 16px!important;box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;transition:border-color .2s,box-shadow .2s!important;min-height:44px!important;}
[data-testid="stSelectbox"]>div>div:hover{border-color:#E5003B55!important;box-shadow:0 4px 16px rgba(229,0,59,0.08)!important;}
[data-testid="stSelectbox"] svg{color:#E5003B!important;}
[data-testid="stSelectbox"] [data-baseweb="select"]>div{background:#fff!important;border-radius:12px!important;}
[data-baseweb="popover"] ul{background:#fff!important;border-radius:12px!important;border:1.5px solid rgba(0,0,0,0.08)!important;box-shadow:0 8px 32px rgba(0,0,0,0.12)!important;padding:6px!important;font-family:'DM Sans',system-ui,sans-serif!important;}
[data-baseweb="popover"] li{border-radius:8px!important;font-size:14px!important;font-weight:500!important;color:#1C1917!important;padding:8px 14px!important;transition:background .15s!important;}
[data-baseweb="popover"] li:hover{background:#FFF0F3!important;color:#E5003B!important;}
[data-baseweb="popover"] li[aria-selected="true"]{background:#FFF0F3!important;color:#E5003B!important;font-weight:600!important;}
[data-testid="stButton"]>button{background:#fff!important;border:1.5px solid rgba(0,0,0,0.10)!important;color:#1C1917!important;font-family:'DM Sans',system-ui,sans-serif!important;font-weight:600!important;font-size:13px!important;border-radius:12px!important;padding:10px 20px!important;min-height:44px!important;box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;transition:all .2s!important;letter-spacing:.3px!important;}
[data-testid="stButton"]>button:hover{border-color:#E5003B!important;color:#E5003B!important;background:#FFF0F3!important;box-shadow:0 4px 16px rgba(229,0,59,0.10)!important;}
[data-testid="stDateInput"]>label{display:none!important;}
[data-testid="stDateInput"] input{background:#fff!important;border:1.5px solid rgba(0,0,0,0.10)!important;border-radius:12px!important;color:#1C1917!important;font-family:'DM Sans',system-ui,sans-serif!important;font-size:14px!important;font-weight:500!important;padding:10px 14px!important;box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;min-height:44px!important;}
[data-testid="stDateInput"] input:focus{border-color:#E5003B!important;box-shadow:0 0 0 3px rgba(229,0,59,0.10)!important;}
[data-testid="stHorizontalBlock"]{align-items:center!important;}
</style>""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
PROJECT = os.getenv('GCP_PROJECT_ID', 'trustwarehouse')

@st.cache_resource
def _client():
    return bigquery.Client(project=PROJECT)

def safe(v):
    if v is None: return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
    if hasattr(v, 'item'): return v.item()
    return v

def _js_escape(s):
    out = []
    for c in s:
        cp = ord(c)
        if cp < 128:
            out.append(c)
        elif cp < 0x10000:
            out.append(f'\\u{cp:04X}')
        else:
            cp -= 0x10000
            out.append(f'\\u{0xD800 + (cp >> 10):04X}\\u{0xDC00 + (cp & 0x3FF):04X}')
    return ''.join(out)

def _s(val, low, high, inv=False):
    if val is None or (isinstance(val, float) and math.isnan(val)): return 'n'
    ok = (val <= low) if inv else (val >= high)
    warn = (val <= high) if inv else (val >= low)
    return 'g' if ok else ('a' if warn else 'r')

SC = {'g': '#16A34A', 'a': '#D97706', 'r': '#E5003B', 'n': '#78716C'}
SB = {'g': '#DCFCE7', 'a': '#FEF9C3', 'r': '#FFF0F3', 'n': '#F5F1EB'}

# ── DATA LOADERS ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner="Loading agent data…")
def load_agents(d0, d1):
    exclude_list = ','.join(f"'{e}'" for e in EXCLUDE)
    df = _client().query(f"""
        SELECT * FROM `{PROJECT}.gold.gold_agent_performance_daily`
        WHERE date BETWEEN '{d0}' AND '{d1}'
          AND agent_name NOT IN ({exclude_list})
        ORDER BY date, agent_name
    """).to_dataframe()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading leads…")
def load_leads(d0, d1):
    df = _client().query(f"""
        SELECT first_name, last_name, created_date,
               total_call_attempts, mins_to_first_call,
               last_call_agent, has_been_called, has_qualified_conversation,
               appointment_booked, customer_type, is_sold
        FROM `{PROJECT}.gold.gold_lead_activity`
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
        ORDER BY created_date DESC
        LIMIT 500
    """).to_dataframe()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading trend…")
def load_trend(d0, d1):
    exclude_list = ','.join(f"'{e}'" for e in EXCLUDE)
    df = _client().query(f"""
        SELECT date,
               SUM(appointments_booked) AS appointments,
               SUM(outbound_calls)      AS outbound_calls,
               SUM(qualified_conversations) AS qual_convos,
               SUM(missed_calls)        AS missed_calls
        FROM `{PROJECT}.gold.gold_agent_performance_daily`
        WHERE date BETWEEN '{d0}' AND '{d1}'
          AND agent_name NOT IN ({exclude_list})
        GROUP BY date ORDER BY date
    """).to_dataframe()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading appointment metrics…")
def load_appt_metrics(d0, d1):
    rows = _client().query(f"""
        SELECT
            COUNTIF(DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP)) BETWEEN '{d0}' AND '{d1}') as appts_booked,
            COUNTIF(created_date BETWEEN '{d0}' AND '{d1}') as fresh_leads,
            COUNTIF(created_date BETWEEN '{d0}' AND '{d1}'
                    AND DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP)) = created_date) as fresh_appts
        FROM `{PROJECT}.gold.gold_lead_activity`
    """).to_dataframe()
    row = rows.iloc[0]
    return {"appts_booked": int(row['appts_booked'] or 0), "fresh_leads": int(row['fresh_leads'] or 0), "fresh_appts": int(row['fresh_appts'] or 0)}

# ── PERIOD SELECTOR ───────────────────────────────────────────────────────────
PRESETS = ["Last 7 Days","Yesterday","Today","This Week","Last 7 Working Days","This Month","Last 30 Days","Custom"]

def _working_range(n):
    days, d = [], date.today() - timedelta(1)
    while len(days) < n:
        if d.weekday() < 5: days.append(d)
        d -= timedelta(1)
    return days[-1], days[0]

today     = date.today()
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

_cols = st.columns([2, 1.4, 1.4, 0.5])
with _cols[0]:
    preset = st.selectbox("Period", PRESETS, index=0, label_visibility="collapsed")
if preset == "Custom":
    with _cols[1]:
        d0 = st.date_input("From", value=yesterday - timedelta(7), max_value=yesterday,
                           label_visibility="collapsed", key="t_from")
    with _cols[2]:
        d1 = st.date_input("To", value=yesterday, max_value=yesterday,
                           label_visibility="collapsed", key="t_to")
else:
    d0, d1 = PRESET_DATES[preset]
with _cols[3]:
    if st.button("↺ Refresh"):
        st.cache_data.clear(); st.rerun()

s0, s1 = d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")
period_lbl = d0.strftime("%d %b") + " – " + d1.strftime("%d %b %Y")
days_n = (d1 - d0).days + 1

# ── LOAD DATA ─────────────────────────────────────────────────────────────────
df_ag = load_agents(s0, s1)
df_ld = load_leads(s0, s1)
df_tr = load_trend(s0, s1)
am    = load_appt_metrics(s0, s1)

# ── AGENT AGGREGATION ─────────────────────────────────────────────────────────
if not df_ag.empty:
    agg = df_ag.groupby("agent_name").agg(
        outbound=("outbound_calls", "sum"),
        inbound=("inbound_calls", "sum"),
        missed=("missed_calls", "sum"),
        talk=("total_talk_time_seconds", "sum"),
        qual=("qualified_conversations", "sum"),
        qual_o=("qualified_outbound_conversations", "sum"),
        appts=("appointments_booked", "sum"),
        sales=("sales_confirmed", "sum"),
        deal_val=("total_deal_value", "sum"),
    ).reset_index()
    agg["ratio"]  = ((agg["qual"] + agg["qual_o"]) / agg["appts"].replace(0, float("nan"))).round(1)
    agg["cpa"]    = (agg["outbound"] / agg["appts"].replace(0, float("nan"))).round(1)
    agg["talk_h"] = (agg["talk"] / 3600).round(2)
    agg["tgt"]    = (agg["outbound"] / 3).round(1)
    agg["on"]     = agg["cpa"].fillna(999) <= 3
    agg = agg[agg["outbound"] > 0].sort_values("appts", ascending=False)

    ta   = int(df_ag["appointments_booked"].sum())
    out  = int(df_ag["outbound_calls"].sum())
    ti   = int(df_ag["inbound_calls"].sum())
    tm   = int(df_ag["missed_calls"].sum())
    na   = len(agg)
    on_n = int(agg["on"].sum())
    pct_on  = on_n / na * 100 if na else 0
    miss_r  = tm / (out + tm) * 100 if (out + tm) else 0
    d_appt  = ta - out / 3

    called_f    = df_ld[df_ld["mins_to_first_call"].notna()] if not df_ld.empty else pd.DataFrame()
    avg_first   = float(called_f["mins_to_first_call"].mean()) if len(called_f) else None
    avg_first_v = safe(avg_first)

    agents_records = [
        {
            "name": str(r["agent_name"]),
            "outbound": int(r["outbound"]), "inbound": int(r["inbound"]),
            "missed": int(r["missed"]), "qual": int(r["qual"]), "qual_o": int(r["qual_o"]),
            "appts": int(r["appts"]), "sales": int(r["sales"]),
            "deal_val": safe(float(r["deal_val"])) if pd.notna(r["deal_val"]) else 0,
            "talk_h": safe(float(r["talk_h"])),
            "ratio": safe(float(r["ratio"])),
            "cpa": safe(float(r["cpa"])),
            "tgt": safe(float(r["tgt"])),
            "on": bool(r["on"]),
        }
        for _, r in agg.iterrows()
    ]
else:
    ta = out = ti = tm = na = on_n = 0
    pct_on = miss_r = d_appt = 0.0
    avg_first_v = None
    agents_records = []

# ── LEAD METRICS ──────────────────────────────────────────────────────────────
if not df_ld.empty:
    nl   = len(df_ld)
    cal  = int(df_ld["has_been_called"].fillna(False).astype(bool).sum())
    nc   = nl - cal
    w5   = int((df_ld["mins_to_first_call"] <= 5).sum())
    w10  = int(((df_ld["mins_to_first_call"] > 5) & (df_ld["mins_to_first_call"] <= 10)).sum())
    ov10 = int((df_ld["mins_to_first_call"] > 10).sum())
    avg_r_raw = df_ld["mins_to_first_call"].mean()
    avg_r_v   = safe(float(avg_r_raw)) if pd.notna(avg_r_raw) else None
    apt  = int((df_ld["appointment_booked"] == "Yes").sum())
    pc   = cal / nl * 100 if nl else 0
    p5   = w5 / cal * 100 if cal else 0
    cv   = apt / cal * 100 if cal else 0
    ct_counts = {str(k): int(v) for k, v in df_ld["customer_type"].fillna("Unknown").value_counts().to_dict().items()}
    ac_counts = {str(k): int(v) for k, v in df_ld[df_ld["last_call_agent"].notna()]["last_call_agent"].value_counts().head(12).to_dict().items()}
    leads_records = [
        {
            "name": ((str(r.get("first_name") or "")).strip() + " " + (str(r.get("last_name") or "")).strip()).strip() or "—",
            "type": str(r.get("customer_type") or "?"),
            "created": str(r.get("created_date") or ""),
            "calls": int(r.get("total_call_attempts") or 0),
            "mins": safe(float(r["mins_to_first_call"])) if pd.notna(r.get("mins_to_first_call")) else None,
            "agent": str(r.get("last_call_agent") or "—"),
            "qual": r.get("has_qualified_conversation") is True,
            "appt": r.get("appointment_booked") == "Yes",
            "sold": r.get("is_sold") is True,
        }
        for _, r in df_ld.iterrows()
    ]
else:
    nl = cal = nc = w5 = w10 = ov10 = apt = 0
    pc = p5 = cv = 0.0
    avg_r_v = None
    ct_counts = {}; ac_counts = {}; leads_records = []

# ── TREND ─────────────────────────────────────────────────────────────────────
trend_records = [
    {"date": str(r["date"]), "appts": int(r["appointments"]),
     "calls": int(r["outbound_calls"]), "qual": int(r["qual_convos"]), "missed": int(r["missed_calls"])}
    for _, r in df_tr.iterrows()
] if not df_tr.empty else []

# ── SPARKLINES ────────────────────────────────────────────────────────────────
spark_dates = []; sparkline_data = {}
if not df_ag.empty and len(df_tr) > 1:
    spiv = df_ag.pivot_table(index="date", columns="agent_name",
        values="appointments_booked", aggfunc="sum", fill_value=0).reset_index()
    spark_dates = [str(d)[:10] for d in spiv["date"].tolist()]
    for ag in spiv.columns[1:]:
        sparkline_data[str(ag)] = [int(v) for v in spiv[ag].tolist()]

# ── STATUS COLORS ─────────────────────────────────────────────────────────────
appt_s = _s(d_appt, 0, 0)
miss_s = _s(miss_r, 10, 20, inv=True)
pon_s  = _s(pct_on, 50, 80)
avg_s  = _s(avg_first_v, 5, 10, inv=True) if avg_first_v is not None else 'n'
fresh_conv = am["fresh_appts"] / am["fresh_leads"] * 100 if am["fresh_leads"] else 0
fc_s   = 'g' if fresh_conv >= 33 else ('a' if fresh_conv >= 20 else 'r')
a_s    = _s(avg_r_v, 5, 10, inv=True) if avg_r_v is not None else 'n'
cov_s  = _s(pc, 60, 85)
p5_s   = _s(p5, 40, 70)
apt_s  = 'g' if cv >= 33 else 'r'

# ── DATA JSON ─────────────────────────────────────────────────────────────────
DATA_JSON = json.dumps({
    "period": period_lbl, "days": days_n,
    "kpis": {
        "ta": ta, "out": out, "ti": ti, "tm": tm, "on": on_n, "na": na,
        "pct_on": round(pct_on, 1), "miss_r": round(miss_r, 1),
        "d_appt": round(float(d_appt), 1), "avg_r": avg_first_v,
        "appt_col": SC[appt_s], "appt_bg": SB[appt_s],
        "miss_col": SC[miss_s], "miss_bg": SB[miss_s],
        "pon_col":  SC[pon_s],  "pon_bg":  SB[pon_s],
        "avg_col":  SC[avg_s],  "avg_bg":  SB[avg_s],
    },
    "am": {
        "appts_booked": am["appts_booked"], "fresh_leads": am["fresh_leads"],
        "fresh_appts": am["fresh_appts"], "fresh_conv": round(fresh_conv, 1),
        "fc_col": SC[fc_s], "fc_bg": SB[fc_s],
    },
    "agents": agents_records,
    "trend": trend_records,
    "response": {
        "w5": w5, "w10": w10, "ov10": ov10, "nc": nc,
        "avg_r": avg_r_v, "apt": apt, "cal": cal, "nl": nl,
        "pc": round(pc, 1), "p5": round(p5, 1), "cv": round(cv, 1),
        "ct": ct_counts, "ac": ac_counts,
        "cov_col": SC[cov_s], "cov_bg": SB[cov_s],
        "p5_col":  SC[p5_s],  "p5_bg":  SB[p5_s],
        "avg_col": SC[a_s],   "avg_bg":  SB[a_s],
        "apt_col": SC[apt_s], "apt_bg":  SB[apt_s],
    },
    "leads": leads_records,
    "sparklines": {"dates": spark_dates, "agents": sparkline_data},
}, default=str).replace('</', r'<\/')

# ── REACT HTML ────────────────────────────────────────────────────────────────
_REACT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#F5F1EB; --white:#FFFFFF; --border:rgba(0,0,0,0.08); --bh:rgba(0,0,0,0.16);
  --text:#1C1917; --dim:#78716C; --dim2:#A8A29E;
  --amber:#E5003B; --amber-l:#FF3A5E; --amber-bg:#FFF0F3;
  --green:#16A34A; --green-bg:#DCFCE7;
  --warn:#D97706; --warn-bg:#FEF9C3;
  --blue:#1A73E8; --blue-bg:#EEF4FF;
  --teal:#0D9488; --teal-bg:#F0FDF9;
}
html,body{background:var(--bg);color:var(--text);font-family:'DM Sans',system-ui,sans-serif;font-size:14px;}
body{padding:20px 24px 48px;}

@keyframes slideUp{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}
@keyframes countIn{from{opacity:0;transform:translateY(8px)scale(.96);}to{opacity:1;transform:translateY(0)scale(1);}}
@keyframes drawLine{from{stroke-dashoffset:3000;}to{stroke-dashoffset:0;}}
@keyframes popIn{0%{opacity:0;transform:scale(.8);}60%{transform:scale(1.06);}100%{opacity:1;transform:scale(1);}}
@keyframes fadeIn{from{opacity:0;}to{opacity:1;}}

.hdr{margin-bottom:24px;padding-bottom:18px;border-bottom:2px solid rgba(0,0,0,0.06);}
.hdr-eye{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:4px;color:var(--amber);text-transform:uppercase;margin-bottom:8px;}
.hdr-title{font-family:'Barlow Condensed',sans-serif;font-size:2.8rem;font-weight:800;color:var(--text);line-height:1;}
.hdr-rule{height:3px;background:linear-gradient(90deg,var(--amber) 0%,var(--blue) 40%,var(--teal) 70%,transparent 100%);margin-top:14px;border-radius:2px;opacity:.6;}

.tab-bar{display:flex;gap:0;margin-bottom:24px;border-bottom:2px solid rgba(0,0,0,0.07);position:relative;}
.tab-btn{background:none;border:none;padding:10px 22px 12px;font-family:'Barlow Condensed',sans-serif;font-size:1rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--dim2);cursor:pointer;position:relative;transition:color .2s;}
.tab-btn::after{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2.5px;background:var(--amber);border-radius:2px;transform:scaleX(0);transition:transform .25s cubic-bezier(.22,1,.36,1);}
.tab-btn:hover{color:var(--text);}
.tab-btn.active{color:var(--amber);}
.tab-btn.active::after{transform:scaleX(1);}

.card{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:20px;position:relative;overflow:visible;transition:transform .3s cubic-bezier(.22,1,.36,1),box-shadow .3s cubic-bezier(.22,1,.36,1),border-color .3s;animation:slideUp .45s cubic-bezier(.22,1,.36,1) both;}
.card:hover{transform:translateY(-5px);box-shadow:0 20px 60px rgba(0,0,0,0.10),0 4px 12px rgba(0,0,0,0.06);border-color:var(--bh);}
.chart-card{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:20px 20px 16px;transition:transform .3s cubic-bezier(.22,1,.36,1),box-shadow .3s cubic-bezier(.22,1,.36,1),border-color .3s;animation:slideUp .45s cubic-bezier(.22,1,.36,1) both;}
.chart-card:hover{transform:translateY(-4px);box-shadow:0 16px 50px rgba(0,0,0,0.09),0 3px 10px rgba(0,0,0,0.05);border-color:var(--bh);}

.kpi-accent{position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0;}
.kpi-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:3.5px;color:var(--dim2);text-transform:uppercase;margin-bottom:8px;margin-top:4px;}
.kpi-val{font-family:'Barlow Condensed',sans-serif;font-size:2.5rem;font-weight:800;line-height:1;margin-bottom:6px;animation:countIn .6s cubic-bezier(.22,1,.36,1) both;}
.kpi-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--dim2);}
.kpi-icon{position:absolute;top:16px;right:16px;width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:15px;opacity:.75;}

.sec-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:4px;color:var(--dim2);text-transform:uppercase;margin-bottom:12px;}
.divider{height:1px;background:rgba(0,0,0,0.06);margin:22px 0;}
.chart-title{font-family:'Barlow Condensed',sans-serif;font-size:1rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text);opacity:.85;}

.g6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
.g21{display:grid;grid-template-columns:2fr 3fr;gap:14px;}
.g32{display:grid;grid-template-columns:3fr 2fr;gap:14px;}
.sec{margin-bottom:20px;}

.tbl{width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:11px;}
.tbl th{color:var(--dim2);font-weight:500;letter-spacing:2px;font-size:9px;text-transform:uppercase;padding:8px 10px;border-bottom:2px solid rgba(0,0,0,0.06);text-align:left;cursor:pointer;user-select:none;white-space:nowrap;}
.tbl th:hover{color:var(--text);}
.tbl td{padding:8px 10px;border-bottom:1px solid rgba(0,0,0,0.04);color:var(--text);transition:background .15s;white-space:nowrap;}
.tbl tr:hover td{background:#FAFAF8;}

.itip-wrap{position:relative;display:inline-flex;flex-shrink:0;}
.itip-btn{width:15px;height:15px;border-radius:50%;background:rgba(0,0,0,0.06);color:#C0BAB5;font-family:'JetBrains Mono',monospace;font-size:8px;font-weight:700;display:flex;align-items:center;justify-content:center;cursor:pointer;user-select:none;transition:background .15s,color .15s;}
.itip-btn:hover{background:rgba(0,0,0,0.12);color:var(--text);}
.itip-box{position:absolute;bottom:calc(100% + 8px);right:0;background:#1C1917;color:#F5F1EB;padding:10px 13px;border-radius:10px;font-family:'DM Sans',sans-serif;font-size:12px;line-height:1.55;width:220px;z-index:9999;box-shadow:0 8px 28px rgba(0,0,0,0.22);pointer-events:none;white-space:normal;text-align:left;}
.itip-box::after{content:'';position:absolute;top:100%;right:5px;border:5px solid transparent;border-top-color:#1C1917;}

.svg-line{stroke-dasharray:3000;stroke-dashoffset:3000;animation:drawLine 1.8s cubic-bezier(.22,1,.36,1) .3s both;}
.svg-dot{animation:popIn .35s cubic-bezier(.22,1,.36,1) both;}
.tab-content{animation:fadeIn .3s ease both;}

.badge{padding:3px 10px;border-radius:20px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;}
</style>
</head>
<body>
<div id="root"><div style="padding:48px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#A8A29E;">Loading…</div></div>
<script>
const DATA = INJECT_DATA;
const e = React.createElement;
const {useState, useEffect, useRef} = React;

const AMBER='#E5003B', AMBERL='#FF3A5E', AMBERBG='#FFF0F3';
const GREEN='#16A34A', GREENBG='#DCFCE7';
const WARN='#D97706',  WARNBG='#FEF9C3';
const TEXT='#1C1917',  DIM='#78716C', DIM2='#A8A29E';
const BLUE='#1A73E8',  BLUEBG='#EEF4FF';
const TEAL='#0D9488',  TEALBG='#F0FDF9';

function fmtN(v){ return Number(v).toLocaleString('en-GB'); }
function fmtD(d){ if(!d) return '—'; const p=d.split('-'); return p[2]+'/'+p[1]; }
function fmtM(v){ return v==null?'—':Number(v).toFixed(1)+'m'; }
function gbp(v,d=0){ return v!=null?'£'+Number(v).toLocaleString('en-GB',{maximumFractionDigits:d}):'—'; }

function useCountUp(target, delay=0){
  const [v,setV]=useState(0);
  useEffect(()=>{
    if(!target) return;
    const t=setTimeout(()=>{
      let cur=0; const step=target/(900/16);
      const id=setInterval(()=>{ cur=Math.min(cur+step,target); setV(cur); if(cur>=target)clearInterval(id); },16);
      return ()=>clearInterval(id);
    }, delay);
    return ()=>clearTimeout(t);
  },[target]);
  return v;
}

function useMounted(delay=60){
  const [m,setM]=useState(false);
  useEffect(()=>{ const id=setTimeout(()=>setM(true),delay); return ()=>clearTimeout(id); },[]);
  return m;
}

function InfoTip({text}){
  const [show,setShow]=useState(false);
  return e('div',{className:'itip-wrap'},
    e('div',{className:'itip-btn',onMouseEnter:()=>setShow(true),onMouseLeave:()=>setShow(false)},'i'),
    show&&e('div',{className:'itip-box'},text)
  );
}

function KpiCard({label,value,sub,accent,ibg,icon,delay=0,info,prefix='',showZero=false}){
  const num=typeof value==='number'?value:0;
  const counted=useCountUp(num,delay);
  const display=num>0
    ? prefix+Math.round(counted).toLocaleString('en-GB')
    : (showZero&&typeof value==='number' ? prefix+'0' : (value||'—'));
  return e('div',{className:'card',style:{animationDelay:delay+'ms'}},
    e('div',{className:'kpi-accent',style:{background:accent||AMBER}}),
    e('div',{className:'kpi-icon',style:{background:ibg||AMBERBG}},icon||''),
    e('div',{style:{display:'flex',alignItems:'center',gap:5,marginBottom:8,marginTop:4}},
      e('div',{className:'kpi-lbl',style:{marginBottom:0,marginTop:0}},label),
      info&&e(InfoTip,{text:info})
    ),
    e('div',{className:'kpi-val',style:{color:TEXT,animationDelay:(delay+100)+'ms'}},display),
    sub&&e('div',{className:'kpi-sub'},sub)
  );
}

function SecLabel({text}){ return e('div',{className:'sec-lbl'},text); }
function Divider(){ return e('div',{className:'divider'}); }

// ── AGENT BARS CHART (HTML div bars) ─────────────────────────────────────────
function AgentBarsChart({agents}){
  const m=useMounted(120);
  if(!agents||!agents.length) return e('div',{className:'chart-card'},'No agent data.');
  const sorted=[...agents].sort((a,b)=>b.appts-a.appts);
  const maxV=Math.max(...sorted.map(a=>Math.max(a.appts, a.tgt||0)),1)*1.15;
  return e('div',{className:'chart-card',style:{animationDelay:'.1s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:16}},
      e('div',{className:'chart-title'},'Appointments vs Target'),
      e(InfoTip,{text:'Bars = appointments booked. Vertical line = 1:3 target (outbound ÷ 3). Green = on target, amber = below target.'})
    ),
    e('div',{style:{display:'flex',flexDirection:'column',gap:10}},
      sorted.map((ag,i)=>{
        const color=ag.on?GREEN:AMBER;
        const pct=Math.min((ag.appts/maxV)*100,100);
        const tpct=Math.min(((ag.tgt||0)/maxV)*100,100);
        return e('div',{key:ag.name},
          e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:3}},
            e('span',{style:{fontFamily:"'DM Sans'",fontSize:12,fontWeight:500,color:TEXT}},ag.name),
            e('div',{style:{display:'flex',alignItems:'center',gap:10}},
              e('span',{style:{fontFamily:"'Barlow Condensed'",fontSize:20,fontWeight:800,color}},ag.appts),
              e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2}}, 'tgt '+Math.round(ag.tgt||0))
            )
          ),
          e('div',{style:{position:'relative',height:18,background:'rgba(0,0,0,0.04)',borderRadius:4,overflow:'visible'}},
            e('div',{style:{
              height:'100%',borderRadius:4,background:color,opacity:.82,
              width:m?pct+'%':'0%',
              transition:`width 1.1s cubic-bezier(.22,1,.36,1) ${i*0.055}s`,
            }}),
            tpct>0&&e('div',{style:{
              position:'absolute',top:-3,bottom:-3,left:tpct+'%',
              width:2,background:DIM2,borderRadius:1,
              boxShadow:'0 0 0 1.5px white',
            }})
          )
        );
      })
    )
  );
}

// ── TREND CHART (SVG area+line) ───────────────────────────────────────────────
function TrendChart({trend}){
  if(!trend||trend.length<2) return e('div',{className:'chart-card',style:{display:'flex',alignItems:'center',justifyContent:'center',minHeight:200,color:DIM2,fontFamily:"'JetBrains Mono'",fontSize:11}},'Select a multi-day period to see the trend.');
  const W=660,H=200,PL=36,PB=26,PR=10,PT=10;
  const cW=W-PL-PR,cH=H-PB-PT;
  const maxC=Math.max(...trend.map(d=>d.calls),1);
  const maxA=Math.max(...trend.map(d=>d.appts),1);
  const bW=Math.max(3,cW/trend.length-3);
  const bx=i=>PL+i*(cW/trend.length);
  const yC=v=>PT+cH-(v/maxC)*cH;
  const yA=v=>PT+cH-(v/maxA)*cH;
  const xStep=Math.max(1,Math.ceil(trend.length/6));
  const apptPts=trend.map((d,i)=>({x:bx(i)+bW/2,y:yA(d.appts)}));
  const apptLine=apptPts.map((p,i)=>(i===0?'M':'L')+' '+p.x.toFixed(1)+' '+p.y.toFixed(1)).join(' ');
  const apptArea=apptLine+' L '+apptPts[apptPts.length-1].x.toFixed(1)+' '+(PT+cH)+' L '+PL+' '+(PT+cH)+' Z';
  return e('div',{className:'chart-card',style:{animationDelay:'.15s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title'},'Daily Trend'),
      e(InfoTip,{text:'Bars = outbound calls. Red line = appointments booked per day.'})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      e('defs',null,
        e('linearGradient',{id:'tgrd',x1:'0',y1:'0',x2:'0',y2:'1'},
          e('stop',{offset:'5%',stopColor:AMBERL,stopOpacity:.12}),
          e('stop',{offset:'95%',stopColor:AMBERL,stopOpacity:0})
        ),
        e('linearGradient',{id:'bgrd',x1:'0',y1:'0',x2:'0',y2:'1'},
          e('stop',{offset:'0%',stopColor:BLUE,stopOpacity:.18}),
          e('stop',{offset:'100%',stopColor:BLUE,stopOpacity:.04})
        )
      ),
      [0,.5,1].map(t=>e('line',{key:'g'+t,x1:PL,y1:yC(maxC*t).toFixed(1),x2:W-PR,y2:yC(maxC*t).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      trend.filter((_,i)=>i%xStep===0||i===trend.length-1).map(d=>e('text',{key:'x'+d.date,x:(bx(trend.indexOf(d))+bW/2).toFixed(1),y:H-4,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},fmtD(d.date))),
      trend.map((d,i)=>e('rect',{key:'b'+i,x:bx(i).toFixed(1),y:yC(d.calls).toFixed(1),width:bW.toFixed(1),height:(cH-(yC(d.calls)-PT)).toFixed(1),fill:'url(#bgrd)',rx:3})),
      e('path',{d:apptArea,fill:'url(#tgrd)'}),
      e('path',{d:apptLine,fill:'none',stroke:AMBER,strokeWidth:2.5,strokeLinecap:'round',strokeLinejoin:'round',className:'svg-line'}),
      apptPts.map((p,i)=>e('circle',{key:'d'+i,cx:p.x.toFixed(1),cy:p.y.toFixed(1),r:3.5,fill:'#fff',stroke:AMBER,strokeWidth:2,className:'svg-dot',style:{animationDelay:(1.8+i*.04)+'s'}})),
      e('g',{transform:`translate(${PL},${H+6})`},
        e('rect',{x:0,y:1,width:12,height:10,fill:'url(#bgrd)',rx:2}),
        e('text',{x:16,y:10,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'Calls')
      ),
      e('g',{transform:`translate(${PL+70},${H+6})`},
        e('line',{x1:0,y1:5,x2:12,y2:5,stroke:AMBER,strokeWidth:2.5}),
        e('text',{x:16,y:10,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'Appts')
      )
    )
  );
}

// ── SVG DONUT ─────────────────────────────────────────────────────────────────
function Donut({slices,centerVal,centerLbl}){
  const [active,setActive]=useState(null);
  const R=80,r=52,cx=100,cy=100;
  const tot=slices.reduce((s,sl)=>s+sl.val,0);
  if(!tot) return null;
  let angle=-Math.PI/2;
  const paths=slices.map((sl,i)=>{
    const sweep=(sl.val/tot)*Math.PI*2;
    const a1=angle,a2=angle+sweep; angle+=sweep;
    const x1=cx+R*Math.cos(a1),y1=cy+R*Math.sin(a1);
    const x2=cx+R*Math.cos(a2),y2=cy+R*Math.sin(a2);
    const ix1=cx+r*Math.cos(a1),iy1=cy+r*Math.sin(a1);
    const ix2=cx+r*Math.cos(a2),iy2=cy+r*Math.sin(a2);
    const large=sweep>Math.PI?1:0;
    const d=`M${x1.toFixed(2)} ${y1.toFixed(2)} A${R} ${R} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} L${ix2.toFixed(2)} ${iy2.toFixed(2)} A${r} ${r} 0 ${large} 0 ${ix1.toFixed(2)} ${iy1.toFixed(2)}Z`;
    const mid=a1+(a2-a1)/2;
    return {...sl,d,i,mid,pct:(sl.val/tot*100).toFixed(0)+'%',sweep};
  });
  return e('svg',{viewBox:'0 0 200 200',width:'100%',style:{maxWidth:200}},
    paths.map(s=>e('path',{
      key:s.lbl,d:s.d,fill:s.color,
      opacity:active===null||active===s.i?1:.25,
      style:{cursor:'pointer',transition:'opacity .2s,transform .2s',transformOrigin:`${cx}px ${cy}px`,transform:active===s.i?'scale(1.04)':'scale(1)'},
      onMouseEnter:()=>setActive(s.i),onMouseLeave:()=>setActive(null)
    })),
    paths.map(s=>s.sweep>0.3?e('text',{
      key:'t'+s.lbl,
      x:(cx+(R+r)/2*Math.cos(s.mid)).toFixed(1),y:(cy+(R+r)/2*Math.sin(s.mid)).toFixed(1),
      textAnchor:'middle',dominantBaseline:'middle',
      fill:'#fff',style:{fontFamily:"'JetBrains Mono'",fontSize:10,fontWeight:600,pointerEvents:'none'}
    },s.pct):null),
    e('text',{x:cx,y:cy-8,textAnchor:'middle',fill:AMBER,style:{fontFamily:"'Barlow Condensed'",fontSize:22,fontWeight:800}},centerVal),
    e('text',{x:cx,y:cy+10,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:8,letterSpacing:2}},centerLbl)
  );
}

function DonutLegend({slices,total}){
  return e('div',{style:{display:'flex',flexDirection:'column',gap:8}},
    slices.map(s=>e('div',{key:s.lbl,style:{display:'flex',alignItems:'center',gap:8}},
      e('div',{style:{width:10,height:10,borderRadius:'50%',background:s.color,flexShrink:0}}),
      e('div',{style:{fontFamily:"'JetBrains Mono'",fontSize:10,color:DIM2,flex:1}},s.lbl),
      e('div',{style:{fontFamily:"'Barlow Condensed'",fontSize:14,fontWeight:700,color:TEXT}},fmtN(s.val)),
      e('div',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2,width:32,textAlign:'right'}},
        total>0?(s.val/total*100).toFixed(0)+'%':'—')
    ))
  );
}

// ── QUAL CONVOS CHART (HTML bars) ────────────────────────────────────────────
function QualConvosChart({agents}){
  const m=useMounted(150);
  const data=agents.filter(a=>a.ratio!=null).sort((a,b)=>(a.ratio||99)-(b.ratio||99));
  if(!data.length) return null;
  const maxR=Math.max(...data.map(a=>a.ratio||0),1)*1.1;
  const color=r=>r<=3?GREEN:r<=6?WARN:AMBER;
  return e('div',{className:'chart-card',style:{animationDelay:'.2s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:16}},
      e('div',{className:'chart-title'},'Qual Convos per Appointment'),
      e(InfoTip,{text:'Qualified conversations needed per appointment. Lower = more efficient. Target: ≤3.'})
    ),
    e('div',{style:{display:'flex',flexDirection:'column',gap:10}},
      data.map((ag,i)=>{
        const r=ag.ratio||0;
        const pct=Math.min((r/maxR)*100,100);
        const c=color(r);
        return e('div',{key:ag.name},
          e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:3}},
            e('span',{style:{fontFamily:"'DM Sans'",fontSize:12,fontWeight:500,color:TEXT}},ag.name),
            e('span',{style:{fontFamily:"'Barlow Condensed'",fontSize:18,fontWeight:800,color:c}},r!=null?r.toFixed(1):'—')
          ),
          e('div',{style:{height:16,background:'rgba(0,0,0,0.04)',borderRadius:4,overflow:'hidden'}},
            e('div',{style:{
              height:'100%',borderRadius:4,background:c,opacity:.8,
              width:m?pct+'%':'0%',
              transition:`width 1s cubic-bezier(.22,1,.36,1) ${i*0.055}s`,
            }})
          )
        );
      })
    )
  );
}

// ── SCATTER CHART ─────────────────────────────────────────────────────────────
function ScatterChart({agents}){
  const [tip,setTip]=useState(null);
  const data=agents.filter(a=>a.outbound>0);
  if(!data.length) return null;
  const W=580,H=340,PL=48,PB=36,PR=20,PT=20;
  const cW=W-PL-PR,cH=H-PB-PT;
  const maxX=Math.max(...data.map(a=>a.outbound),1)*1.1;
  const maxY=Math.max(...data.map(a=>a.appts),1)*1.1;
  const x=v=>PL+(v/maxX)*cW;
  const y=v=>PT+cH-(v/maxY)*cH;
  const rScale=v=>Math.max(6,Math.min(18,6+Math.sqrt(v||0)*1.5));
  const yTicks=[0,.25,.5,.75,1].map(t=>Math.round(maxY*t));
  const xTicks=[0,.25,.5,.75,1].map(t=>Math.round(maxX*t));
  return e('div',{className:'chart-card',style:{animationDelay:'.1s',position:'relative'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title'},'Efficiency — Calls vs Appointments'),
      e(InfoTip,{text:'Bubble size = qualified conversations. Green = on 1:3 target, amber = below. Dashed line shows the 1:3 target ratio.'})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      yTicks.map(v=>e('line',{key:'gy'+v,x1:PL,y1:y(v).toFixed(1),x2:W-PR,y2:y(v).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      xTicks.filter(v=>v>0).map(v=>e('line',{key:'gx'+v,x1:x(v).toFixed(1),y1:PT,x2:x(v).toFixed(1),y2:H-PB,stroke:'rgba(0,0,0,0.04)',strokeWidth:1,strokeDasharray:'4 3'})),
      yTicks.map(v=>e('text',{key:'yl'+v,x:PL-7,y:(y(v)+4).toFixed(1),textAnchor:'end',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},v)),
      xTicks.filter(v=>v>0).map(v=>e('text',{key:'xl'+v,x:x(v).toFixed(1),y:H-PB+14,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},v)),
      e('text',{x:PL-7,y:PT-6,textAnchor:'end',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:8,letterSpacing:1}},'APPTS'),
      e('text',{x:W-PR,y:H-PB+14,textAnchor:'end',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:8,letterSpacing:1}},'CALLS'),
      e('line',{x1:PL,y1:y(maxX/3),x2:x(maxX),y2:y(maxX),stroke:DIM2,strokeWidth:1.5,strokeDasharray:'6 3'}),
      e('text',{x:x(maxX*0.6),y:(y(maxX*0.6/3)-8).toFixed(1),fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},'1:3 target'),
      data.map((ag,i)=>e('g',{key:ag.name,style:{cursor:'pointer'},
        onMouseEnter:ev=>{
          const bbox=ev.currentTarget.closest('svg').getBoundingClientRect();
          setTip({ag,px:x(ag.outbound),py:y(ag.appts)});
        },
        onMouseLeave:()=>setTip(null)
      },
        e('circle',{cx:x(ag.outbound).toFixed(1),cy:y(ag.appts).toFixed(1),
          r:rScale(ag.qual+ag.qual_o),
          fill:ag.on?GREEN:AMBER,opacity:.75,
          className:'svg-dot',style:{animationDelay:(0.3+i*0.07)+'s'}}),
        e('text',{x:x(ag.outbound).toFixed(1),y:(y(ag.appts)-rScale(ag.qual+ag.qual_o)-4).toFixed(1),
          textAnchor:'middle',fill:TEXT,
          style:{fontFamily:"'DM Sans'",fontSize:11,fontWeight:500,pointerEvents:'none'}
        },ag.name.split(' ')[0])
      )),
      tip&&e('g',null,
        e('rect',{x:(tip.px+8).toFixed(1),y:(tip.py-40).toFixed(1),width:130,height:52,rx:6,fill:'#1C1917',opacity:.92}),
        e('text',{x:(tip.px+14).toFixed(1),y:(tip.py-24).toFixed(1),fill:'#F5F1EB',style:{fontFamily:"'DM Sans'",fontSize:11,fontWeight:600}},tip.ag.name),
        e('text',{x:(tip.px+14).toFixed(1),y:(tip.py-10).toFixed(1),fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},
          tip.ag.outbound+' calls · '+tip.ag.appts+' appts'),
        e('text',{x:(tip.px+14).toFixed(1),y:(tip.py+4).toFixed(1),fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},
          (tip.ag.qual+tip.ag.qual_o)+' qual · CPA '+(tip.ag.cpa?tip.ag.cpa.toFixed(1):'—'))
      )
    )
  );
}

// ── SPARKLINE CHART ───────────────────────────────────────────────────────────
function SparklineChart({sparklines}){
  const {dates,agents}=sparklines;
  if(!dates||dates.length<2||!agents||!Object.keys(agents).length) return null;
  const PAL=[AMBER,GREEN,WARN,BLUE,TEAL,'#7C3AED','#F59E0B','#6366F1'];
  const agNames=Object.keys(agents);
  const W=580,H=160,PL=10,PB=20,PR=10,PT=10;
  const cW=W-PL-PR,cH=H-PB-PT;
  const maxV=Math.max(...agNames.flatMap(a=>agents[a]),1);
  const x=i=>PL+((dates.length>1?i/(dates.length-1):0.5)*cW);
  const y=v=>PT+cH-(v/maxV)*cH;
  const xStep=Math.max(1,Math.ceil(dates.length/5));
  return e('div',{className:'chart-card',style:{animationDelay:'.25s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title'},'Daily Appointments per Agent'),
      e(InfoTip,{text:"Each line = one agent's appointment bookings per day. Spot patterns and outliers."})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      [0,.5,1].map(t=>e('line',{key:'g'+t,x1:PL,y1:y(maxV*t).toFixed(1),x2:W-PR,y2:y(maxV*t).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      dates.filter((_,i)=>i%xStep===0||i===dates.length-1).map((d,_i,arr)=>{
        const idx=dates.indexOf(d);
        return e('text',{key:'xl'+d,x:x(idx).toFixed(1),y:H-4,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},fmtD(d));
      }),
      agNames.flatMap((ag,pi)=>{
        const vals=agents[ag];
        const pts=vals.map((v,i)=>({x:x(i),y:y(v)}));
        const line=pts.map((p,i)=>(i===0?'M':'L')+' '+p.x.toFixed(1)+' '+p.y.toFixed(1)).join(' ');
        const c=PAL[pi%PAL.length];
        return [
          e('path',{key:'sl'+ag,d:line,fill:'none',stroke:c,strokeWidth:2,strokeLinecap:'round',strokeLinejoin:'round',className:'svg-line',style:{animationDelay:(0.3+pi*.12)+'s'}}),
          pts.length&&e('circle',{key:'sd'+ag,cx:pts[pts.length-1].x.toFixed(1),cy:pts[pts.length-1].y.toFixed(1),r:3,fill:c,className:'svg-dot',style:{animationDelay:(2+pi*.08)+'s'}})
        ];
      }),
      agNames.map((ag,i)=>e('g',{key:'leg'+i,transform:`translate(${PL+i*Math.min(100,cW/agNames.length)},${H+10})`},
        e('line',{x1:0,y1:5,x2:12,y2:5,stroke:PAL[i%PAL.length],strokeWidth:2}),
        e('text',{x:15,y:9,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9}},ag.split(' ')[0])
      ))
    )
  );
}

// ── LEADERBOARD ───────────────────────────────────────────────────────────────
function Leaderboard({agents}){
  const [sortIdx,setSortIdx]=useState(5);
  const [asc,setAsc]=useState(false);
  const cols=['Agent','Out','In','Missed','Qual','Appts','Sales','£Deal','Talk(h)','Ratio','CPA','On'];
  const rows=agents.map(a=>[
    a.name, a.outbound, a.inbound, a.missed,
    a.qual+a.qual_o, a.appts, a.sales,
    a.deal_val||0, a.talk_h||0, a.ratio||0, a.cpa||0, a.on?1:0
  ]);
  const sorted=[...rows].sort((a,b)=>{
    const av=a[sortIdx]; const bv=b[sortIdx];
    if(typeof av==='string') return asc?av.localeCompare(bv):bv.localeCompare(av);
    return asc?av-bv:bv-av;
  });
  const fmt=(v,j)=>{
    if(j===0) return v;
    if(j===7) return v>0?gbp(v):'—';
    if(j===8||j===9||j===10) return v?Number(v).toFixed(1):'—';
    if(j===11) return v?'✅':'❌';
    return fmtN(v);
  };
  const maxAppts=Math.max(...rows.map(r=>r[5]),1);
  return e('div',{className:'chart-card',style:{animationDelay:'.2s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title'},'Agent Leaderboard'),
      e(InfoTip,{text:'Click any column header to sort. CPA = calls per appointment. Ratio = qual convos per appointment.'})
    ),
    e('div',{style:{overflowX:'auto'}},
      e('table',{className:'tbl'},
        e('thead',null,e('tr',null,...cols.map((c,i)=>e('th',{key:c,
          style:{color:sortIdx===i?TEXT:'',fontWeight:sortIdx===i?700:500},
          onClick:()=>{ if(sortIdx===i)setAsc(!asc); else{setSortIdx(i);setAsc(false);} }
        },c+(sortIdx===i?(asc?' ↑':' ↓'):''))
        ))),
        e('tbody',null,...sorted.map((row,ri)=>{
          const isTop=ri===0;
          return e('tr',{key:ri},
            ...row.map((cell,j)=>{
              let style={};
              if(j===0&&isTop) style={color:AMBER,fontWeight:700};
              if(j===5) {
                const pct=Number(row[5])/maxAppts;
                style={background:`linear-gradient(90deg,rgba(229,0,59,0.12) ${pct*100}%,transparent ${pct*100}%)`,fontWeight:700};
              }
              if(j===11) style={color:row[11]?GREEN:AMBER,fontSize:14};
              return e('td',{key:j,style},fmt(cell,j));
            })
          );
        }))
      )
    )
  );
}

// ── LEAD CALLED CHART ─────────────────────────────────────────────────────────
function LeadCalledChart({ac}){
  const m=useMounted(150);
  const entries=Object.entries(ac).sort((a,b)=>b[1]-a[1]);
  if(!entries.length) return null;
  const maxV=Math.max(...entries.map(e=>e[1]),1);
  return e('div',{className:'chart-card',style:{animationDelay:'.15s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:16}},
      e('div',{className:'chart-title'},'Leads Called per Agent'),
      e(InfoTip,{text:'Number of fresh leads where this agent made the last call in the period.'})
    ),
    e('div',{style:{display:'flex',flexDirection:'column',gap:10}},
      entries.map(([name,val],i)=>
        e('div',{key:name},
          e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:3}},
            e('span',{style:{fontFamily:"'DM Sans'",fontSize:12,fontWeight:500,color:TEXT}},name),
            e('span',{style:{fontFamily:"'Barlow Condensed'",fontSize:18,fontWeight:800,color:AMBER}},val)
          ),
          e('div',{style:{height:16,background:'rgba(0,0,0,0.04)',borderRadius:4,overflow:'hidden'}},
            e('div',{style:{
              height:'100%',borderRadius:4,background:AMBER,opacity:.75,
              width:m?(val/maxV*100)+'%':'0%',
              transition:`width 1s cubic-bezier(.22,1,.36,1) ${i*0.06}s`,
            }})
          )
        )
      )
    )
  );
}

// ── LEAD TRACKER ──────────────────────────────────────────────────────────────
function LeadTracker({leads}){
  const cols=['Name','Type','Date','Calls','Mins','Last Agent','Qual','Appt','Sold'];
  const minsColor=v=>{
    if(v==null) return {background:'#F5F1EB',color:DIM2};
    if(v<=5)  return {background:GREENBG,color:'#166534'};
    if(v<=10) return {background:WARNBG, color:'#854D0E'};
    return {background:AMBERBG,color:'#9F1239'};
  };
  return e('div',{className:'chart-card',style:{animationDelay:'.25s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title'},'Lead Response Tracker'),
      e(InfoTip,{text:'Up to 500 leads created in the period. Mins = minutes to first outbound call. Green ≤5, amber 6–10, red >10.'})
    ),
    e('div',{style:{overflowX:'auto',maxHeight:440,overflowY:'auto'}},
      e('table',{className:'tbl'},
        e('thead',null,e('tr',null,...cols.map(c=>e('th',{key:c},c)))),
        e('tbody',null,...leads.map((ld,i)=>e('tr',{key:i},
          e('td',null,ld.name),
          e('td',{style:{color:ld.type==='Domestic'?AMBER:ld.type==='Commercial'?'#7C3AED':DIM2,fontWeight:600}},ld.type),
          e('td',null,fmtD(ld.created)),
          e('td',{style:{fontWeight:600}},ld.calls),
          e('td',{style:{...minsColor(ld.mins),borderRadius:6,padding:'3px 8px',fontSize:10}},fmtM(ld.mins)),
          e('td',{style:{color:DIM2}},ld.agent),
          e('td',{style:{textAlign:'center'}},ld.qual?'✅':'—'),
          e('td',{style:{textAlign:'center'}},ld.appt?'✅':'—'),
          e('td',{style:{textAlign:'center'}},ld.sold?'✅':'—')
        )))
      )
    )
  );
}

// ── TAB 1 — DAILY OPS ────────────────────────────────────────────────────────
function DailyOpsTab({D}){
  const {kpis:K,am:A,agents,trend}=D;
  const haveAgents=agents&&agents.length>0;
  const haveTrend=trend&&trend.length>1;
  const respSlices=[
    {lbl:'≤ 5 min',  val:D.response.w5,   color:GREEN},
    {lbl:'6–10 min', val:D.response.w10,  color:WARN},
    {lbl:'> 10 min', val:D.response.ov10, color:AMBER},
    {lbl:'Not called',val:D.response.nc,  color:DIM2},
  ];
  const totalResp=D.response.w5+D.response.w10+D.response.ov10+D.response.nc;
  return e('div',{className:'tab-content'},
    e('div',{className:'sec'},
      e(SecLabel,{text:'Performance Summary'}),
      e('div',{className:'g6'},
        e(KpiCard,{label:'Agent Appts',value:K.ta,sub:(K.d_appt>0?'+':'')+K.d_appt.toFixed(0)+' vs target',accent:K.appt_col,ibg:K.appt_bg,icon:'📅',delay:0,showZero:true,info:'Total appointments attributed to agents in the selected period.'}),
        e(KpiCard,{label:'Outbound',value:K.out,sub:D.days+'-day period',accent:BLUE,ibg:BLUEBG,icon:'📞',delay:60,info:'Total outbound calls made by the team across all agents.'}),
        e(KpiCard,{label:'Inbound',value:K.ti,sub:'answered',accent:TEAL,ibg:TEALBG,icon:'📲',delay:120,info:'Total inbound calls answered by agents.'}),
        e(KpiCard,{label:'Missed',value:K.tm,sub:K.miss_r.toFixed(1)+'% miss rate',accent:K.miss_col,ibg:K.miss_bg,icon:'🔕',delay:180,info:'Calls that rang but were not answered. Target: miss rate ≤10%.'}),
        e(KpiCard,{label:'On Target',value:K.on,sub:K.pct_on.toFixed(0)+'% of '+K.na+' agents',accent:K.pon_col,ibg:K.pon_bg,icon:'🎯',delay:240,info:'Agents hitting the 1:3 appointment:call target.'}),
        e(KpiCard,{label:'Avg Response',value:K.avg_r!=null?K.avg_r.toFixed(1)+'m':'—',sub:'same-day leads',accent:K.avg_col,ibg:K.avg_bg,icon:'⚡',delay:300,info:'Average minutes from lead creation to first call. Target: ≤5 min.'})
      )
    ),
    e('div',{className:'sec'},
      e(SecLabel,{text:'Appointment Analysis'}),
      e('div',{className:'g4'},
        e(KpiCard,{label:'Appts Booked',value:A.appts_booked,sub:'any lead age · by booking date',accent:GREEN,ibg:GREENBG,icon:'✅',delay:0,showZero:true,info:'Appointments where the booking date falls in the period — regardless of when the lead was originally created.'}),
        e(KpiCard,{label:'Fresh Leads',value:A.fresh_leads,sub:'leads created in period',accent:AMBER,ibg:AMBERBG,icon:'👥',delay:60,info:'Total leads that entered SharpSpring during the selected period.'}),
        e(KpiCard,{label:'Fresh Appts',value:A.fresh_appts,sub:'lead & appt same day',accent:GREEN,ibg:GREENBG,icon:'📅',delay:120,showZero:true,info:'Fresh leads where the appointment was booked on the same day the lead came in.'}),
        e(KpiCard,{label:'Fresh Conv.',value:A.fresh_conv.toFixed(0)+'%',sub:'≥33% target',accent:A.fc_col,ibg:A.fc_bg,icon:'📈',delay:180,info:'Fresh appointments ÷ fresh leads. Target ≥33%: one in three fresh leads should convert same day.'})
      )
    ),
    e(Divider),
    e('div',{className:'g32 sec'},
      e(AgentBarsChart,{agents}),
      e(TrendChart,{trend})
    ),
    e(Divider),
    e('div',{className:'g2 sec'},
      e('div',{className:'chart-card',style:{animationDelay:'.2s'}},
        e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
          e('div',{className:'chart-title'},'Lead Response Breakdown'),
          e(InfoTip,{text:'How quickly fresh leads were called. Target: ≥70% within 5 minutes.'})
        ),
        e('div',{style:{display:'flex',alignItems:'center',gap:20}},
          e(Donut,{slices:respSlices,centerVal:fmtN(totalResp),centerLbl:'LEADS'}),
          e(DonutLegend,{slices:respSlices,total:totalResp})
        )
      ),
      e(QualConvosChart,{agents})
    )
  );
}

// ── TAB 2 — AGENTS ───────────────────────────────────────────────────────────
function AgentsTab({D}){
  const {agents,sparklines}=D;
  const haveSparklines=sparklines&&sparklines.dates&&sparklines.dates.length>1;
  return e('div',{className:'tab-content'},
    e('div',{className:'g2 sec'},
      e(ScatterChart,{agents}),
      e(QualConvosChart,{agents})
    ),
    e(Divider),
    e('div',{className:'sec'},
      e(Leaderboard,{agents})
    ),
    haveSparklines&&e('div',null,
      e(Divider),
      e('div',{className:'sec'},
        e(SparklineChart,{sparklines})
      )
    )
  );
}

// ── TAB 3 — LEAD RESPONSE ────────────────────────────────────────────────────
function LeadResponseTab({D}){
  const {response:R,leads}=D;
  const respSlices=[
    {lbl:'≤ 5 min',  val:R.w5,   color:GREEN},
    {lbl:'6–10 min', val:R.w10,  color:WARN},
    {lbl:'> 10 min', val:R.ov10, color:AMBER},
    {lbl:'Not called',val:R.nc,  color:DIM2},
  ];
  const totalResp=R.w5+R.w10+R.ov10+R.nc;
  const ctSlices=Object.entries(R.ct||{}).map(([k,v])=>({
    lbl:k.charAt(0).toUpperCase()+k.slice(1),val:v,
    color:k.toLowerCase()==='domestic'?AMBER:k.toLowerCase()==='commercial'?'#7C3AED':DIM2
  }));
  const ctTotal=ctSlices.reduce((s,sl)=>s+sl.val,0);
  return e('div',{className:'tab-content'},
    e('div',{className:'sec'},
      e(SecLabel,{text:'Lead Response Summary'}),
      e('div',{className:'g4'},
        e(KpiCard,{label:'Leads in Period',value:R.nl,sub:'created in period',accent:AMBER,ibg:AMBERBG,icon:'👥',delay:0,info:'Total leads created in SharpSpring during the selected period.'}),
        e(KpiCard,{label:'Called',value:R.cal,sub:R.pc.toFixed(0)+'% coverage',accent:R.cov_col,ibg:R.cov_bg,icon:'📞',delay:60,info:'Leads that received at least one outbound call. Coverage should be ≥85%.'}),
        e(KpiCard,{label:'≤ 5 Min',value:R.w5,sub:R.p5.toFixed(0)+'% of called',accent:R.p5_col,ibg:R.p5_bg,icon:'⚡',delay:120,info:'Leads called within 5 minutes of creation. Target: ≥70% of called leads.'}),
        e(KpiCard,{label:'Avg Response',value:R.avg_r!=null?R.avg_r.toFixed(1)+'m':'—',sub:'same-day calls',accent:R.avg_col,ibg:R.avg_bg,icon:'⏱',delay:180,info:'Average minutes to first call for same-day leads. Target: ≤5 min.'})
      )
    ),
    e(Divider),
    e('div',{className:'g3 sec'},
      e('div',{className:'chart-card',style:{animationDelay:'.1s'}},
        e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
          e('div',{className:'chart-title'},'Response Speed'),
          e(InfoTip,{text:'How quickly fresh leads were called from the moment they arrived.'})
        ),
        e('div',{style:{display:'flex',alignItems:'center',gap:16}},
          e(Donut,{slices:respSlices,centerVal:fmtN(totalResp),centerLbl:'LEADS'}),
          e(DonutLegend,{slices:respSlices,total:totalResp})
        )
      ),
      e('div',{className:'chart-card',style:{animationDelay:'.15s'}},
        e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
          e('div',{className:'chart-title'},'Lead Types'),
          e(InfoTip,{text:'Domestic vs commercial breakdown of leads created in the period.'})
        ),
        ctSlices.length>0&&e('div',{style:{display:'flex',alignItems:'center',gap:16}},
          e(Donut,{slices:ctSlices,centerVal:fmtN(ctTotal),centerLbl:'LEADS'}),
          e(DonutLegend,{slices:ctSlices,total:ctTotal})
        )
      ),
      e(LeadCalledChart,{ac:R.ac||{}})
    ),
    e(Divider),
    e('div',{className:'sec'},
      e(LeadTracker,{leads})
    )
  );
}

// ── APP ───────────────────────────────────────────────────────────────────────
function App(){
  const [tab,setTab]=useState(0);
  const {period,days}=DATA;
  const tabs=['Daily Ops','Agents','Lead Response'];
  return e('div',null,
    e('div',{className:'hdr'},
      e('div',{style:{display:'flex',alignItems:'flex-end',justifyContent:'space-between',flexWrap:'wrap',gap:12}},
        e('div',null,
          e('div',{className:'hdr-eye'},'Trust Electric Heating · Operations Centre'),
          e('div',{className:'hdr-title'},'Telesales Command Centre')
        ),
        e('div',{style:{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:8,paddingBottom:2}},
          e('div',{style:{fontFamily:"'JetBrains Mono',monospace",fontSize:9,color:'#A8A29E',letterSpacing:'2px',textTransform:'uppercase'}},
            'PERIOD: '+period.toUpperCase()+' · '+days+' DAYS'
          ),
          e('div',{style:{display:'flex',gap:6}},
            e('span',{className:'badge',style:{background:GREENBG,border:'1.5px solid '+GREEN+'33',color:GREEN}},'Agents'),
            e('span',{className:'badge',style:{background:BLUEBG, border:'1.5px solid '+BLUE+'33',color:BLUE}},'Leads'),
            e('span',{className:'badge',style:{background:AMBERBG,border:'1.5px solid '+AMBER+'33',color:AMBER}},'Live')
          )
        )
      ),
      e('div',{className:'hdr-rule'})
    ),
    e('div',{className:'tab-bar'},
      tabs.map((t,i)=>e('button',{key:i,className:'tab-btn'+(tab===i?' active':''),onClick:()=>setTab(i)},t))
    ),
    tab===0&&e(DailyOpsTab,{D:DATA}),
    tab===1&&e(AgentsTab,{D:DATA}),
    tab===2&&e(LeadResponseTab,{D:DATA})
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
</script>
</body>
</html>"""
REACT_HTML = _js_escape(_REACT_TEMPLATE).replace('INJECT_DATA', DATA_JSON)


st.components.v1.html(REACT_HTML, height=1800, scrolling=True)
