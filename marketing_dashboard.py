import os, json, math
from datetime import date, timedelta

from google.cloud import bigquery
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Marketing Intelligence", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
html,body,.stApp,[data-testid="stAppViewContainer"]{background:#F5F1EB!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:0.75rem 1.4rem 0.5rem!important;max-width:100%!important;}

/* ── Period selector toolbar ── */
[data-testid="stSelectbox"]>label{display:none!important;}
[data-testid="stSelectbox"]>div>div{
  background:#fff!important;
  border:1.5px solid rgba(0,0,0,0.10)!important;
  border-radius:12px!important;
  color:#1C1917!important;
  font-family:'DM Sans',system-ui,sans-serif!important;
  font-size:14px!important;
  font-weight:500!important;
  padding:10px 16px!important;
  box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;
  transition:border-color .2s,box-shadow .2s!important;
  min-height:44px!important;
}
[data-testid="stSelectbox"]>div>div:hover{
  border-color:#E5003B55!important;
  box-shadow:0 4px 16px rgba(229,0,59,0.08)!important;
}
[data-testid="stSelectbox"] svg{color:#E5003B!important;}
[data-testid="stSelectbox"] [data-baseweb="select"]>div{
  background:#fff!important;border-radius:12px!important;
}

/* Dropdown list */
[data-baseweb="popover"] ul{
  background:#fff!important;
  border-radius:12px!important;
  border:1.5px solid rgba(0,0,0,0.08)!important;
  box-shadow:0 8px 32px rgba(0,0,0,0.12)!important;
  padding:6px!important;
  font-family:'DM Sans',system-ui,sans-serif!important;
}
[data-baseweb="popover"] li{
  border-radius:8px!important;
  font-size:14px!important;
  font-weight:500!important;
  color:#1C1917!important;
  padding:8px 14px!important;
  transition:background .15s!important;
}
[data-baseweb="popover"] li:hover{background:#FFF0F3!important;color:#E5003B!important;}
[data-baseweb="popover"] li[aria-selected="true"]{
  background:#FFF0F3!important;color:#E5003B!important;font-weight:600!important;
}

/* ── Refresh button ── */
[data-testid="stButton"]>button{
  background:#fff!important;
  border:1.5px solid rgba(0,0,0,0.10)!important;
  color:#1C1917!important;
  font-family:'DM Sans',system-ui,sans-serif!important;
  font-weight:600!important;
  font-size:13px!important;
  border-radius:12px!important;
  padding:10px 20px!important;
  min-height:44px!important;
  box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;
  transition:all .2s!important;
  letter-spacing:.3px!important;
}
[data-testid="stButton"]>button:hover{
  border-color:#E5003B!important;
  color:#E5003B!important;
  background:#FFF0F3!important;
  box-shadow:0 4px 16px rgba(229,0,59,0.10)!important;
}

/* ── Date inputs ── */
[data-testid="stDateInput"]>label{display:none!important;}
[data-testid="stDateInput"] input{
  background:#fff!important;
  border:1.5px solid rgba(0,0,0,0.10)!important;
  border-radius:12px!important;
  color:#1C1917!important;
  font-family:'DM Sans',system-ui,sans-serif!important;
  font-size:14px!important;
  font-weight:500!important;
  padding:10px 14px!important;
  box-shadow:0 2px 8px rgba(0,0,0,0.06)!important;
  min-height:44px!important;
}
[data-testid="stDateInput"] input:focus{
  border-color:#E5003B!important;
  box-shadow:0 0 0 3px rgba(229,0,59,0.10)!important;
}

/* Thin separator below toolbar */
[data-testid="stHorizontalBlock"]{align-items:center!important;}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ────────────────────────────────────────────────────────────────────
PROJECT = os.getenv('GCP_PROJECT_ID', 'trustwarehouse')

@st.cache_resource
def _client():
    return bigquery.Client(project=PROJECT)

@st.cache_data(ttl=1800, show_spinner="Loading attribution data…")
def load_attr(d0, d1):
    df = _client().query(f"""
        SELECT * FROM `{PROJECT}.gold.gold_campaign_attribution`
        WHERE date BETWEEN '{d0}' AND '{d1}'
        ORDER BY date DESC, spend_gbp DESC
    """).to_dataframe()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading lead breakdown…")
def load_customer_types(d0, d1):
    df = _client().query(f"""
        SELECT COALESCE(m.platform,'Other Paid') as platform,
               COALESCE(g.customer_type,'Unknown') as customer_type,
               count(*) as leads
        FROM `{PROJECT}.gold.gold_lead_activity` g
        INNER JOIN `{PROJECT}.silver.campaign_platform_mapping` m ON g.campaign_id = m.campaign_id
        WHERE g.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """).to_dataframe()
    return df

@st.cache_data(ttl=1800, show_spinner="Loading lead sources…")
def load_lead_sources(d0, d1):
    df = _client().query(f"""
        SELECT
            COALESCE(m.platform, 'Organic') as source,
            count(*)                                                    as leads,
            COUNTIF(g.appointment_booked = 'Yes')                      as appts,
            COUNTIF(g.is_sold = true)                                  as sales
        FROM `{PROJECT}.gold.gold_lead_activity` g
        LEFT JOIN `{PROJECT}.silver.campaign_platform_mapping` m
            ON g.campaign_id = m.campaign_id
        WHERE g.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1
        ORDER BY 2 DESC
    """).to_dataframe()
    return df

def _working_range(n):
    days, d = [], date.today() - timedelta(1)
    while len(days) < n:
        if d.weekday() < 5: days.append(d)
        d -= timedelta(1)
    return days[-1], days[0]

# ── PERIOD SELECTOR ────────────────────────────────────────────────────────────
PRESETS = ["Last 7 Days","Last 30 Days","This Month","Last 7 Working Days",
           "This Week","Yesterday","Today","Custom"]
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
        d0 = st.date_input("From", value=yesterday - timedelta(30), max_value=yesterday,
                           label_visibility="collapsed", key="m_from")
    with _cols[2]:
        d1 = st.date_input("To", value=yesterday, max_value=yesterday,
                           label_visibility="collapsed", key="m_to")
else:
    d0, d1 = PRESET_DATES[preset]
with _cols[3]:
    if st.button("↺ Refresh"):
        st.cache_data.clear(); st.rerun()

# ── DATA ───────────────────────────────────────────────────────────────────────
df     = load_attr(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))
df_ct  = load_customer_types(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))
df_src = load_lead_sources(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))

if df.empty:
    st.warning("No attribution data for selected period.")
    st.stop()

pa = df.groupby("platform").agg(
    spend=("spend_gbp","sum"), clicks=("clicks","sum"), impr=("impressions","sum"),
    leads=("leads","sum"), appts=("appointments_booked","sum"), sales=("sales","sum"),
).reset_index()
for col, num, den in [("cpl","spend","leads"),("cpa","spend","appts"),("cps","spend","sales")]:
    pa[col] = (pa[num] / pa[den].replace(0, float("nan"))).round(2)
pa["ctr"] = (pa["clicks"] / pa["impr"].replace(0, float("nan")) * 100).round(3)
pa["l2a"] = (pa["appts"] / pa["leads"].replace(0, float("nan")) * 100).round(1)
pa["a2s"] = (pa["sales"] / pa["appts"].replace(0, float("nan")) * 100).round(1)

tot_sp = float(pa["spend"].sum())
tot_ld = int(pa["leads"].sum())
tot_ap = int(pa["appts"].sum())
tot_sa = int(pa["sales"].sum())
tot_cl = int(pa["clicks"].sum())
b_cpl  = round(tot_sp / tot_ld, 2) if tot_ld else 0
b_cpa  = round(tot_sp / tot_ap, 2) if tot_ap else 0
b_cps  = round(tot_sp / tot_sa, 2) if tot_sa else 0

def safe(v):
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    if hasattr(v, 'item'): return v.item()
    return v

platform_records = []
for _, row in pa.iterrows():
    platform_records.append({
        'platform': str(row['platform']),
        'spend': float(row['spend']),
        'leads': int(row['leads']),
        'appts': int(row['appts']),
        'sales': int(row['sales']),
        'clicks': int(row['clicks']),
        'cpl': safe(row['cpl']),
        'cpa': safe(row['cpa']),
        'cps': safe(row['cps']),
        'ctr': safe(row['ctr']),
        'l2a': safe(row['l2a']),
        'a2s': safe(row['a2s']),
    })

daily_records = []
for _, row in df.iterrows():
    daily_records.append({
        'date': str(row['date']),
        'platform': str(row['platform']),
        'spend': safe(float(row['spend_gbp'])),
        'leads': int(row['leads']) if pd.notna(row['leads']) else 0,
        'appts': int(row['appointments_booked']) if pd.notna(row['appointments_booked']) else 0,
        'sales': int(row['sales']) if pd.notna(row['sales']) else 0,
        'clicks': int(row['clicks']) if pd.notna(row['clicks']) else 0,
        'cpl': safe(float(row['cost_per_lead'])) if pd.notna(row.get('cost_per_lead')) else None,
        'cpa': safe(float(row['cost_per_appointment'])) if pd.notna(row.get('cost_per_appointment')) else None,
    })

source_records = []
for _, row in df_src.iterrows():
    source_records.append({
        'source': str(row['source']),
        'leads':  int(row['leads']),
        'appts':  int(row['appts']),
        'sales':  int(row['sales']),
    })

tot_all_leads = int(df_src['leads'].sum()) if not df_src.empty else 0

DATA_JSON = json.dumps({
    'period': f"{d0.strftime('%d %b')} – {d1.strftime('%d %b %Y')}",
    'totals': {
        'spend': tot_sp, 'leads': tot_ld, 'appts': tot_ap,
        'sales': tot_sa, 'clicks': tot_cl,
        'cpl': b_cpl, 'cpa': b_cpa, 'cps': b_cps,
        'total_leads': tot_all_leads,
    },
    'platforms': platform_records,
    'daily': daily_records,
    'lead_sources': source_records,
}).replace('</', r'<\/')

# ── REACT COMPONENT ────────────────────────────────────────────────────────────
REACT_HTML = """<!DOCTYPE html>
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
  --bg:#F5F1EB;
  --white:#FFFFFF;
  --s2:#FEFCF9;
  --border:rgba(0,0,0,0.08);
  --bh:rgba(0,0,0,0.16);
  --text:#1C1917;
  --dim:#78716C;
  --dim2:#A8A29E;
  --amber:#E5003B;
  --amber-l:#FF3A5E;
  --amber-bg:#FFF0F3;
  --google:#1A73E8;
  --google-bg:#EEF4FF;
  --meta:#7C3AED;
  --meta-bg:#F5F3FF;
  --bing:#0D9488;
  --bing-bg:#F0FDF9;
}
html,body{background:var(--bg);color:var(--text);font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.5;}
body{padding:20px 24px 48px;}

/* ── Animations ── */
@keyframes slideUp{
  from{opacity:0;transform:translateY(20px);}
  to{opacity:1;transform:translateY(0);}
}
@keyframes countIn{
  from{opacity:0;transform:translateY(8px)scale(.96);}
  to{opacity:1;transform:translateY(0)scale(1);}
}
@keyframes drawLine{
  from{stroke-dashoffset:2400;}
  to{stroke-dashoffset:0;}
}
@keyframes fillBar{
  from{transform:scaleX(0);}
  to{transform:scaleX(1);}
}
@keyframes popIn{
  0%{opacity:0;transform:scale(.85);}
  60%{transform:scale(1.04);}
  100%{opacity:1;transform:scale(1);}
}
@keyframes shimmer{
  0%{background-position:-200% center;}
  100%{background-position:200% center;}
}
@keyframes pulse{
  0%,100%{transform:scale(1);opacity:1;}
  50%{transform:scale(1.06);opacity:.85;}
}

/* ── Layout ── */
.hdr{margin-bottom:28px;padding-bottom:22px;border-bottom:2px solid rgba(0,0,0,0.06);}
.hdr-eye{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:4px;color:var(--amber);text-transform:uppercase;margin-bottom:8px;}
.hdr-title{font-family:'Barlow Condensed',sans-serif;font-size:3rem;font-weight:800;color:var(--text);letter-spacing:.3px;line-height:1;}
.hdr-title em{color:var(--amber);font-style:normal;}
.hdr-rule{height:3px;background:linear-gradient(90deg,var(--amber) 0%,var(--google) 35%,var(--meta) 65%,var(--bing) 85%,transparent 100%);margin-top:14px;border-radius:2px;opacity:.6;}
.hdr-meta{display:flex;align-items:center;gap:10px;margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);letter-spacing:1.5px;flex-wrap:wrap;}
.badge{padding:3px 10px;border-radius:20px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;}

.g6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;}
.g7{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
.g21{display:grid;grid-template-columns:2fr 3fr;gap:14px;}
.sec{margin-bottom:22px;}
.sec-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:4px;color:var(--dim2);text-transform:uppercase;margin-bottom:12px;}
.div{height:1px;background:rgba(0,0,0,0.06);margin:22px 0;}

/* ── Base card ── */
.card{
  background:var(--white);
  border:1px solid var(--border);
  border-radius:12px;
  padding:20px;
  cursor:default;
  position:relative;
  overflow:visible;
  transition:transform .3s cubic-bezier(.22,1,.36,1),
             box-shadow .3s cubic-bezier(.22,1,.36,1),
             border-color .3s ease;
  animation:slideUp .5s cubic-bezier(.22,1,.36,1) both;
}
.card::before{
  content:'';
  position:absolute;
  inset:0;
  border-radius:12px;
  opacity:0;
  transition:opacity .3s ease;
  pointer-events:none;
}
.card:hover{
  transform:translateY(-5px);
  box-shadow:0 20px 60px rgba(0,0,0,0.1),0 4px 12px rgba(0,0,0,0.06);
  border-color:var(--bh);
}

/* ── KPI cards ── */
.kpi-accent{position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0;}
.kpi-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:3.5px;color:var(--dim2);text-transform:uppercase;margin-bottom:10px;margin-top:4px;}
.kpi-val{font-family:'Barlow Condensed',sans-serif;font-size:2.6rem;font-weight:800;line-height:1;margin-bottom:6px;animation:countIn .6s cubic-bezier(.22,1,.36,1) both;}
.kpi-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--dim2);}
.kpi-icon{position:absolute;top:18px;right:18px;width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;opacity:.7;}

/* ── Platform cards ── */
.plat-top{height:4px;border-radius:12px 12px 0 0;position:absolute;top:0;left:0;right:0;}
.plat-name{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;margin-top:6px;}
.plat-spend{font-family:'Barlow Condensed',sans-serif;font-size:2.4rem;font-weight:800;line-height:1;margin-bottom:4px;}
.plat-track{height:6px;background:rgba(0,0,0,0.06);border-radius:3px;margin:10px 0 14px;overflow:hidden;}
.plat-fill{height:6px;border-radius:3px;transform-origin:left;transition:transform 1.4s cubic-bezier(.22,1,.36,1);}
.plat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--dim2);}
.plat-sv{font-size:13px;font-weight:700;color:var(--text);margin-top:1px;}
.plat-chip{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:20px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;margin-bottom:10px;}

/* ── Chart cards ── */
.chart-card{
  background:var(--white);
  border:1px solid var(--border);
  border-radius:12px;
  padding:20px 20px 16px;
  transition:transform .3s cubic-bezier(.22,1,.36,1),
             box-shadow .3s cubic-bezier(.22,1,.36,1),
             border-color .3s ease;
  animation:slideUp .5s cubic-bezier(.22,1,.36,1) both;
}
.chart-card:hover{
  transform:translateY(-4px);
  box-shadow:0 16px 50px rgba(0,0,0,0.09),0 3px 10px rgba(0,0,0,0.05);
  border-color:var(--bh);
}
.chart-title{font-family:'Barlow Condensed',sans-serif;font-size:1.05rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text);margin-bottom:14px;opacity:.85;}

/* ── Funnel ── */
.fn-row{margin-bottom:10px;}
.fn-labels{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim2);margin-bottom:4px;}
.fn-track{background:rgba(0,0,0,0.05);border-radius:6px;height:28px;overflow:hidden;}
.fn-fill{height:100%;border-radius:6px;display:flex;align-items:center;padding:0 10px;transform-origin:left;transition:transform 1.5s cubic-bezier(.22,1,.36,1);}
.fn-pct{font-family:'JetBrains Mono',monospace;font-size:10px;color:rgba(255,255,255,.9);font-weight:600;}
.fn-footer{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:12px;padding-top:10px;border-top:1px solid rgba(0,0,0,0.05);font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--dim2);}
.fn-footer span{color:var(--text);margin-left:4px;font-weight:600;}

/* ── Table ── */
.tbl{width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:11px;}
.tbl th{color:var(--dim2);font-weight:500;letter-spacing:2px;font-size:9px;text-transform:uppercase;padding:8px 12px;border-bottom:2px solid rgba(0,0,0,0.06);text-align:left;}
.tbl td{padding:9px 12px;border-bottom:1px solid rgba(0,0,0,0.04);color:var(--text);transition:background .15s;}
.tbl tr:hover td{background:#FAFAF8;}

/* ── SVG draw animation ── */
.svg-line{stroke-dasharray:2400;stroke-dashoffset:2400;animation:drawLine 1.8s cubic-bezier(.22,1,.36,1) .4s both;}
.svg-dot{animation:popIn .4s cubic-bezier(.22,1,.36,1) both;}

.footer-note{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--dim2);margin-top:28px;padding-top:16px;border-top:1px solid rgba(0,0,0,0.06);line-height:2;}

/* ── Info Tooltip ── */
.itip-wrap{position:relative;display:inline-flex;flex-shrink:0;}
.itip-btn{
  width:16px;height:16px;border-radius:50%;
  background:rgba(0,0,0,0.06);color:#B0A9A2;
  font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
  display:flex;align-items:center;justify-content:center;
  cursor:pointer;user-select:none;
  transition:background .15s,color .15s;
}
.itip-btn:hover{background:rgba(0,0,0,0.13);color:#1C1917;}
.itip-box{
  position:absolute;bottom:calc(100% + 8px);right:0;
  background:#1C1917;color:#F5F1EB;
  padding:10px 13px;border-radius:10px;
  font-family:'DM Sans',sans-serif;font-size:12px;line-height:1.55;
  width:230px;z-index:9999;
  box-shadow:0 8px 28px rgba(0,0,0,0.22);
  pointer-events:none;white-space:normal;text-align:left;
}
.itip-box::after{
  content:'';position:absolute;top:100%;right:5px;
  border:5px solid transparent;border-top-color:#1C1917;
}

/* ── Platform Filter Pills ── */
.pf-bar{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap;align-items:center;}
.pf-pill{
  padding:5px 14px;border-radius:20px;
  font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  cursor:pointer;border:1.5px solid transparent;
  transition:all .2s cubic-bezier(.22,1,.36,1);
  outline:none;background:none;
}
.pf-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--dim2);letter-spacing:2px;text-transform:uppercase;}

/* Stagger delays */
.d0{animation-delay:0s;} .d1{animation-delay:.06s;} .d2{animation-delay:.12s;}
.d3{animation-delay:.18s;} .d4{animation-delay:.24s;} .d5{animation-delay:.3s;}
.d6{animation-delay:.1s;} .d7{animation-delay:.2s;} .d8{animation-delay:.3s;}
</style>
</head>
<body>
<div id="root"><div style="padding:48px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#A8A29E;">Loading…</div></div>
<script>
const DATA = INJECT_DATA;
const e = React.createElement;
const { useState, useEffect } = React;

const PC    = { Google:'#1A73E8', Meta:'#7C3AED', Bing:'#0D9488' };
const PCbg  = { Google:'#EEF4FF', Meta:'#F5F3FF', Bing:'#F0FDF9' };
const AMBER = '#E5003B', AMBERL = '#FF3A5E', AMBERBG = '#FFF0F3';
const TEXT  = '#1C1917', DIM2 = '#A8A29E';

function gbp(v,d=0){ return v!=null?'£'+Number(v).toLocaleString('en-GB',{maximumFractionDigits:d}):'—'; }
function fmtN(v){ return Number(v).toLocaleString('en-GB'); }
function fmtD(d){ const p=d.split('-'); return p[2]+'/'+p[1]; }

function useCountUp(target,delay=0){
  const [v,setV]=useState(0);
  useEffect(()=>{
    const t=setTimeout(()=>{
      let cur=0; const step=target/(900/16);
      const id=setInterval(()=>{ cur=Math.min(cur+step,target); setV(cur); if(cur>=target)clearInterval(id); },16);
      return ()=>clearInterval(id);
    },delay);
    return ()=>clearTimeout(t);
  },[target]);
  return v;
}

function useMounted(delay=60){
  const [m,setM]=useState(false);
  useEffect(()=>{ const id=setTimeout(()=>setM(true),delay); return ()=>clearTimeout(id); },[]);
  return m;
}

// ── Info Tooltip ──────────────────────────────────────────────────
function InfoTip({text}){
  const [show,setShow]=useState(false);
  return e('div',{className:'itip-wrap'},
    e('div',{className:'itip-btn',onMouseEnter:()=>setShow(true),onMouseLeave:()=>setShow(false)},'i'),
    show&&e('div',{className:'itip-box'},text)
  );
}

// ── KPI Card ──────────────────────────────────────────────────────
function KpiCard({label,value,sub,accent,prefix='',icon,delay=0,bgAccent,info,showZero=false}){
  const num = typeof value==='number'?value:0;
  const counted = useCountUp(num, delay);
  const display = num>0
    ? prefix+Math.round(counted).toLocaleString('en-GB')
    : (showZero && typeof value==='number' ? prefix+'0' : (value||'—'));
  return e('div',{className:`card d${Math.floor(delay/60)}`,style:{animationDelay:delay+'ms'}},
    e('div',{className:'kpi-accent',style:{background:accent||AMBER}}),
    e('div',{className:'kpi-icon',style:{background:bgAccent||AMBERBG}},icon||''),
    e('div',{style:{display:'flex',alignItems:'center',gap:6,marginBottom:10,marginTop:4}},
      e('div',{className:'kpi-lbl',style:{marginBottom:0,marginTop:0}},label),
      info&&e(InfoTip,{text:info})
    ),
    e('div',{className:'kpi-val',style:{color:'#1C1917',animationDelay:(delay+100)+'ms'}},display),
    sub&&e('div',{className:'kpi-sub'},sub)
  );
}

// ── Platform Card ─────────────────────────────────────────────────
function PlatformCard({p,totalSpend,delay=0}){
  const color=PC[p.platform]||AMBER, bg=PCbg[p.platform]||AMBERBG;
  const pct=totalSpend>0?(p.spend/totalSpend*100):0;
  const m=useMounted(80+delay);
  const stats=[
    ['Leads',   fmtN(p.leads)],
    ['Appts',   fmtN(p.appts)],
    ['CPL',     p.cpl?gbp(p.cpl):'—'],
    ['L→A',     p.l2a?p.l2a.toFixed(0)+'%':'—'],
    ['Sales',   fmtN(p.sales)],
    ['CTR',     p.ctr?p.ctr.toFixed(2)+'%':'—'],
  ];
  return e('div',{className:'card',style:{animationDelay:delay+'ms',paddingTop:22}},
    e('div',{className:'plat-top',style:{background:`linear-gradient(90deg,${color},${color}88)`}}),
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:4}},
      e('div',{className:'plat-name',style:{color,marginBottom:0}},p.platform),
      e('div',{style:{display:'flex',alignItems:'center',gap:8}},
        e('div',{className:'plat-chip',style:{background:bg,color}},pct.toFixed(0)+'% of budget'),
        e(InfoTip,{text:'Spend, leads, conversions and efficiency metrics for '+p.platform+' campaigns only.'})
      )
    ),
    e('div',{className:'plat-spend',style:{color}},gbp(p.spend)),
    e('div',{className:'plat-track'},
      e('div',{className:'plat-fill',style:{
        background:`linear-gradient(90deg,${color},${color}99)`,
        transform:m?`scaleX(${Math.min(pct/100,1)})`:'scaleX(0)'
      }})
    ),
    e('div',{className:'plat-grid'},
      ...stats.map(([lbl,val])=>e('div',{key:lbl},
        e('div',null,lbl),
        e('div',{className:'plat-sv'},val)
      ))
    )
  );
}

// ── SVG Area Chart ─────────────────────────────────────────────────
function AreaChart({daily}){
  const dateMap={};
  daily.forEach(r=>{
    if(!dateMap[r.date]) dateMap[r.date]={date:r.date};
    dateMap[r.date][r.platform]=(dateMap[r.date][r.platform]||0)+(r.spend||0);
  });
  const data=Object.values(dateMap).sort((a,b)=>a.date.localeCompare(b.date));
  const platforms=Object.keys(PC).filter(p=>data.some(d=>d[p]));
  if(!data.length) return null;

  const W=680,H=210,PL=50,PB=26,PR=10,PT=10;
  const cW=W-PL-PR, cH=H-PB-PT;
  const maxV=Math.max(...data.flatMap(d=>platforms.map(p=>d[p]||0)),1);
  const x=i=>PL+((data.length>1?i/(data.length-1):0.5)*cW);
  const y=v=>PT+cH-(v/maxV)*cH;
  const yTicks=[0,.25,.5,.75,1].map(t=>maxV*t);
  const xStep=Math.max(1,Math.ceil(data.length/5));

  return e('div',{className:'chart-card',style:{animationDelay:'.2s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Daily Spend by Platform'),
      e(InfoTip,{text:'Daily ad spend per platform. Spot over-spend days, budget gaps, or weekend drop-offs.'})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      e('defs',null,
        ...platforms.map((p,pi)=>e('linearGradient',{key:'g'+pi,id:'ag'+pi,x1:'0',y1:'0',x2:'0',y2:'1'},
          e('stop',{offset:'5%',stopColor:PC[p],stopOpacity:.18}),
          e('stop',{offset:'95%',stopColor:PC[p],stopOpacity:0})
        ))
      ),
      // grid lines
      ...yTicks.map(v=>e('line',{key:'y'+v,x1:PL,y1:y(v).toFixed(1),x2:W-PR,y2:y(v).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      // y labels
      ...yTicks.filter(v=>v>0).map(v=>e('text',{key:'yl'+v,x:PL-7,y:(y(v)+4).toFixed(1),textAnchor:'end',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},
        v>=1000?'£'+(v/1000).toFixed(1)+'k':'£'+v.toFixed(0)
      )),
      // x labels
      ...data.filter((_,i)=>i%xStep===0||i===data.length-1).map(d=>e('text',{key:'xl'+d.date,x:x(data.indexOf(d)).toFixed(1),y:H-4,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},fmtD(d.date))),
      // areas + lines
      ...platforms.flatMap((p,pi)=>{
        const pts=data.map((d,i)=>({x:x(i),y:y(d[p]||0)}));
        const line=pts.map((pt,i)=>(i===0?'M':'L')+' '+pt.x.toFixed(1)+' '+pt.y.toFixed(1)).join(' ');
        const area=line+' L '+pts[pts.length-1].x.toFixed(1)+' '+(PT+cH).toFixed(1)+' L '+PL.toFixed(1)+' '+(PT+cH).toFixed(1)+' Z';
        return [
          e('path',{key:'area'+p,d:area,fill:`url(#ag${pi})`}),
          e('path',{key:'line'+p,d:line,fill:'none',stroke:PC[p],strokeWidth:2.5,strokeLinecap:'round',strokeLinejoin:'round',className:'svg-line',style:{animationDelay:(0.4+pi*0.15)+'s'}}),
          // dots at end
          e('circle',{key:'dot'+p,cx:pts[pts.length-1].x.toFixed(1),cy:pts[pts.length-1].y.toFixed(1),r:4,fill:PC[p],className:'svg-dot',style:{animationDelay:(2.0+pi*0.1)+'s'}}),
        ];
      }),
      // legend
      ...platforms.map((p,i)=>e('g',{key:'leg'+i,transform:`translate(${PL+i*100},${H+6})`},
        e('circle',{cx:5,cy:5,r:4.5,fill:PC[p]}),
        e('text',{x:14,y:9,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},p)
      ))
    )
  );
}

// ── Donut ──────────────────────────────────────────────────────────
function Donut({platforms,total}){
  const [active,setActive]=useState(null);
  const R=84,r=54,cx=110,cy=110;
  const tot=platforms.reduce((s,p)=>s+p.spend,0);
  let angle=-Math.PI/2;
  const slices=platforms.map((p,i)=>{
    const sweep=(p.spend/tot)*Math.PI*2;
    const a1=angle, a2=angle+sweep;
    angle+=sweep;
    const x1=cx+R*Math.cos(a1),y1=cy+R*Math.sin(a1);
    const x2=cx+R*Math.cos(a2),y2=cy+R*Math.sin(a2);
    const ix1=cx+r*Math.cos(a1),iy1=cy+r*Math.sin(a1);
    const ix2=cx+r*Math.cos(a2),iy2=cy+r*Math.sin(a2);
    const large=sweep>Math.PI?1:0;
    const d=`M${x1.toFixed(2)} ${y1.toFixed(2)} A${R} ${R} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} L${ix2.toFixed(2)} ${iy2.toFixed(2)} A${r} ${r} 0 ${large} 0 ${ix1.toFixed(2)} ${iy1.toFixed(2)}Z`;
    const mid=a1+(a2-a1)/2;
    const lx=cx+(R+r)/2*Math.cos(mid), ly=cy+(R+r)/2*Math.sin(mid);
    return {d,color:PC[p.platform]||AMBER,pct:(p.spend/tot*100).toFixed(0)+'%',lx,ly,sweep,i,name:p.platform,spend:p.spend};
  });

  return e('div',{className:'chart-card',style:{animationDelay:'.1s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Spend Distribution'),
      e(InfoTip,{text:'How total budget is split across platforms. Hover each slice to highlight it and see the exact amount.'})
    ),
    e('div',{style:{display:'flex',alignItems:'center',gap:20}},
      e('svg',{viewBox:'0 0 220 220',width:200,style:{flexShrink:0}},
        slices.map(s=>e('path',{
          key:s.name,d:s.d,fill:s.color,
          opacity:active===null||active===s.i?1:.25,
          style:{cursor:'pointer',transition:'opacity .2s,transform .2s',transformOrigin:`${cx}px ${cy}px`,transform:active===s.i?'scale(1.04)':'scale(1)'},
          onMouseEnter:()=>setActive(s.i),onMouseLeave:()=>setActive(null)
        })),
        slices.map(s=>s.sweep>0.35?e('text',{
          key:'t'+s.name,x:s.lx.toFixed(1),y:s.ly.toFixed(1),
          textAnchor:'middle',dominantBaseline:'middle',
          fill:'#fff',style:{fontFamily:"'JetBrains Mono'",fontSize:11,fontWeight:600,pointerEvents:'none'}
        },s.pct):null),
        // center
        e('text',{x:cx,y:cy-10,textAnchor:'middle',fill:AMBER,style:{fontFamily:"'Barlow Condensed'",fontSize:24,fontWeight:800}},gbp(tot)),
        e('text',{x:cx,y:cy+12,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:9,letterSpacing:2}},'TOTAL SPEND')
      ),
      e('div',{style:{display:'flex',flexDirection:'column',gap:12}},
        platforms.map(p=>e('div',{key:p.platform,
          style:{display:'flex',flexDirection:'column',gap:3,padding:'10px 14px',borderRadius:10,background:PCbg[p.platform]||AMBERBG,transition:'transform .2s',cursor:'default'},
          onMouseEnter:e=>{e.currentTarget.style.transform='translateX(4px)'},
          onMouseLeave:e=>{e.currentTarget.style.transform='translateX(0)'}
        },
          e('div',{style:{display:'flex',alignItems:'center',gap:7}},
            e('span',{style:{width:10,height:10,borderRadius:'50%',background:PC[p.platform]||AMBER,display:'inline-block'}}),
            e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:PC[p.platform]||AMBER,letterSpacing:2,fontWeight:700,textTransform:'uppercase'}},p.platform)
          ),
          e('div',{style:{fontFamily:"'Barlow Condensed'",fontSize:'1.5rem',fontWeight:800,color:PC[p.platform]||AMBER}},gbp(p.spend)),
          e('div',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2}},(p.spend/tot*100).toFixed(0)+'% of budget')
        ))
      )
    )
  );
}

// ── Funnel Card ───────────────────────────────────────────────────
function FunnelCard({p,delay=0}){
  const color=PC[p.platform]||AMBER, bg=PCbg[p.platform]||AMBERBG;
  const m=useMounted(100+delay);
  const steps=[
    {lbl:'Leads',       val:p.leads, pct:100,       op:1},
    {lbl:'Appointments',val:p.appts, pct:p.leads>0?(p.appts/p.leads*100):0, op:.75},
    {lbl:'Sales',       val:p.sales, pct:p.leads>0?(p.sales/p.leads*100):0, op:.5},
  ];
  return e('div',{className:'chart-card',style:{animationDelay:delay+'ms',borderTop:`3px solid ${color}`}},
    e('div',{style:{display:'flex',alignItems:'center',gap:8,marginBottom:14}},
      e('div',{className:'chart-title',style:{color,marginBottom:0}},p.platform),
      e('div',{style:{marginLeft:'auto',display:'flex',alignItems:'center',gap:8}},
        e('div',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2,letterSpacing:1}},fmtN(p.leads)+' leads'),
        e(InfoTip,{text:'Lead → appointment → sale funnel for '+p.platform+'. Bar width = conversion rate from total leads into that stage.'})
      )
    ),
    ...steps.map((s,i)=>e('div',{key:s.lbl,className:'fn-row'},
      e('div',{className:'fn-labels'},
        e('span',null,s.lbl),
        e('span',{style:{color:TEXT,fontWeight:700}},fmtN(s.val))
      ),
      e('div',{className:'fn-track'},
        e('div',{className:'fn-fill',style:{
          background:`linear-gradient(90deg,${color},${color}${Math.round(s.op*255).toString(16).padStart(2,'0')})`,
          transform:m?`scaleX(${Math.max(s.pct/100,s.val>0?0.03:0)})`:'scaleX(0)'
        }},
          s.pct>25&&i>0?e('span',{className:'fn-pct'},s.pct.toFixed(0)+'%'):null
        )
      )
    )),
    e('div',{className:'fn-footer'},
      e('div',null,'Lead→Appt',e('span',null,p.l2a?p.l2a.toFixed(0)+'%':'—')),
      e('div',null,'Appt→Sale',e('span',null,p.a2s?p.a2s.toFixed(0)+'%':'—')),
      e('div',null,'CPL',e('span',null,p.cpl?gbp(p.cpl):'—')),
      e('div',null,'CPA',e('span',null,p.cpa?gbp(p.cpa):'—')),
    )
  );
}

// ── CPL Line Chart ────────────────────────────────────────────────
function CplChart({daily}){
  const rows=daily.filter(r=>r.cpl);
  if(!rows.length) return null;
  const dateMap={};
  rows.forEach(r=>{ if(!dateMap[r.date]) dateMap[r.date]={date:r.date}; dateMap[r.date][r.platform]=r.cpl; });
  const data=Object.values(dateMap).sort((a,b)=>a.date.localeCompare(b.date));
  const platforms=Object.keys(PC).filter(p=>data.some(d=>d[p]));
  if(!data.length||!platforms.length) return null;

  const W=640,H=200,PL=52,PB=26,PR=10,PT=10;
  const cW=W-PL-PR,cH=H-PB-PT;
  const maxV=Math.max(...data.flatMap(d=>platforms.map(p=>d[p]||0)),1);
  const x=i=>PL+((data.length>1?i/(data.length-1):0.5)*cW);
  const y=v=>PT+cH-(v/maxV)*cH;
  const xStep=Math.max(1,Math.ceil(data.length/5));
  const yTicks=[0,.25,.5,.75,1].map(t=>maxV*t);

  return e('div',{className:'chart-card',style:{animationDelay:'.15s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Cost Per Lead'),
      e(InfoTip,{text:'Daily CPL per platform (spend ÷ leads). Lower is better — spikes usually mean a poor-quality traffic day.'})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      e('defs',null,
        ...platforms.map((p,pi)=>e('linearGradient',{key:'cpllg'+pi,id:'cplg'+pi,x1:'0',y1:'0',x2:'0',y2:'1'},
          e('stop',{offset:'5%',stopColor:PC[p],stopOpacity:.1}),
          e('stop',{offset:'95%',stopColor:PC[p],stopOpacity:0})
        ))
      ),
      ...yTicks.map(v=>e('line',{key:'y'+v,x1:PL,y1:y(v).toFixed(1),x2:W-PR,y2:y(v).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      ...yTicks.filter(v=>v>0).map(v=>e('text',{key:'yl'+v,x:PL-7,y:(y(v)+4).toFixed(1),textAnchor:'end',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'£'+v.toFixed(0))),
      ...data.filter((_,i)=>i%xStep===0||i===data.length-1).map(d=>e('text',{key:'xl'+d.date,x:x(data.indexOf(d)).toFixed(1),y:H-4,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},fmtD(d.date))),
      ...platforms.flatMap((p,pi)=>{
        const pts=data.filter(d=>d[p]!=null).map(d=>({x:x(data.indexOf(d)),y:y(d[p])}));
        if(!pts.length) return [];
        const line=pts.map((pt,i)=>(i===0?'M':'L')+' '+pt.x.toFixed(1)+' '+pt.y.toFixed(1)).join(' ');
        const area=line+' L '+pts[pts.length-1].x.toFixed(1)+' '+(PT+cH)+' L '+pts[0].x.toFixed(1)+' '+(PT+cH)+' Z';
        return [
          e('path',{key:'ca'+p,d:area,fill:`url(#cplg${pi})`}),
          e('path',{key:'cl'+p,d:line,fill:'none',stroke:PC[p],strokeWidth:2.5,strokeLinecap:'round',strokeLinejoin:'round',className:'svg-line',style:{animationDelay:(0.5+pi*.15)+'s'}}),
          ...pts.map((pt,i)=>e('circle',{key:'cd'+p+i,cx:pt.x.toFixed(1),cy:pt.y.toFixed(1),r:3.5,fill:'#fff',stroke:PC[p],strokeWidth:2,className:'svg-dot',style:{animationDelay:(1.8+i*.04)+'s'}}))
        ];
      }),
      ...platforms.map((p,i)=>e('g',{key:'leg'+i,transform:`translate(${PL+i*100},${H+6})`},
        e('circle',{cx:5,cy:5,r:4.5,fill:PC[p]}),
        e('text',{x:14,y:9,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},p)
      ))
    )
  );
}

// ── Leads/Appts Combo ─────────────────────────────────────────────
function LeadsChart({daily}){
  const dateMap={};
  daily.forEach(r=>{
    if(!dateMap[r.date]) dateMap[r.date]={date:r.date,leads:0,appts:0,sales:0};
    dateMap[r.date].leads+=r.leads||0;
    dateMap[r.date].appts+=r.appts||0;
    dateMap[r.date].sales+=r.sales||0;
  });
  const data=Object.values(dateMap).sort((a,b)=>a.date.localeCompare(b.date));
  if(!data.length) return null;

  const W=640,H=200,PL=36,PB=26,PR=10,PT=10;
  const cW=W-PL-PR,cH=H-PB-PT;
  const maxL=Math.max(...data.map(d=>d.leads),1);
  const maxA=Math.max(...data.map(d=>Math.max(d.appts,d.sales)),1);
  const bW=Math.max(2,cW/data.length-3);
  const bx=i=>PL+i*(cW/data.length);
  const yL=v=>PT+cH-(v/maxL)*cH;
  const yA=v=>PT+cH-(v/maxA)*cH;
  const xStep=Math.max(1,Math.ceil(data.length/5));

  const apptPts=data.map((d,i)=>({x:bx(i)+bW/2,y:yA(d.appts)}));
  const salePts=data.map((d,i)=>({x:bx(i)+bW/2,y:yA(d.sales)}));
  const apptLine=apptPts.map((pt,i)=>(i===0?'M':'L')+' '+pt.x.toFixed(1)+' '+pt.y.toFixed(1)).join(' ');
  const saleLine=salePts.map((pt,i)=>(i===0?'M':'L')+' '+pt.x.toFixed(1)+' '+pt.y.toFixed(1)).join(' ');

  return e('div',{className:'chart-card',style:{animationDelay:'.25s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Leads · Appointments · Sales'),
      e(InfoTip,{text:'Daily volume: bars = new paid leads, red line = appointments booked, blue dashed = confirmed sales.'})
    ),
    e('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',style:{overflow:'visible'}},
      [0,.5,1].map(t=>e('line',{key:'g'+t,x1:PL,y1:yL(maxL*t).toFixed(1),x2:W-PR,y2:yL(maxL*t).toFixed(1),stroke:'rgba(0,0,0,0.05)',strokeWidth:1,strokeDasharray:'4 3'})),
      ...data.filter((_,i)=>i%xStep===0||i===data.length-1).map(d=>e('text',{key:'x'+d.date,x:(bx(data.indexOf(d))+bW/2).toFixed(1),y:H-4,textAnchor:'middle',fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},fmtD(d.date))),
      // bars with gradient
      e('defs',null,
        e('linearGradient',{id:'bargrd',x1:'0',y1:'0',x2:'0',y2:'1'},
          e('stop',{offset:'0%',stopColor:AMBERL,stopOpacity:.45}),
          e('stop',{offset:'100%',stopColor:AMBERL,stopOpacity:.12})
        )
      ),
      ...data.map((d,i)=>e('rect',{key:'b'+i,x:bx(i).toFixed(1),y:yL(d.leads).toFixed(1),width:bW.toFixed(1),height:(cH-(yL(d.leads)-PT)).toFixed(1),fill:'url(#bargrd)',rx:3})),
      // appointment line + dots
      e('path',{key:'al',d:apptLine,fill:'none',stroke:AMBER,strokeWidth:2.5,strokeLinecap:'round',strokeLinejoin:'round',className:'svg-line',style:{animationDelay:'.5s'}}),
      ...apptPts.map((pt,i)=>e('circle',{key:'ad'+i,cx:pt.x.toFixed(1),cy:pt.y.toFixed(1),r:3.5,fill:'#fff',stroke:AMBER,strokeWidth:2,className:'svg-dot',style:{animationDelay:(1.8+i*.03)+'s'}})),
      // sales line
      e('path',{key:'sl',d:saleLine,fill:'none',stroke:'#1A73E8',strokeWidth:2,strokeDasharray:'6 3',strokeLinecap:'round',className:'svg-line',style:{animationDelay:'.65s'}}),
      ...salePts.map((pt,i)=>e('circle',{key:'sd'+i,cx:pt.x.toFixed(1),cy:pt.y.toFixed(1),r:2.5,fill:'#fff',stroke:'#1A73E8',strokeWidth:2,className:'svg-dot',style:{animationDelay:(2.0+i*.03)+'s'}})),
      // legend
      e('g',{transform:`translate(${PL},${H+6})`},
        e('rect',{x:0,y:1,width:12,height:12,fill:'url(#bargrd)',rx:2}),
        e('text',{x:16,y:11,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'Leads')
      ),
      e('g',{transform:`translate(${PL+70},${H+6})`},
        e('line',{x1:0,y1:6,x2:12,y2:6,stroke:AMBER,strokeWidth:2.5}),
        e('text',{x:16,y:11,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'Appointments')
      ),
      e('g',{transform:`translate(${PL+195},${H+6})`},
        e('line',{x1:0,y1:6,x2:12,y2:6,stroke:'#1A73E8',strokeWidth:2,strokeDasharray:'5 2'}),
        e('text',{x:16,y:11,fill:DIM2,style:{fontFamily:"'JetBrains Mono'",fontSize:10}},'Sales')
      )
    )
  );
}

// ── Platform Volumes ──────────────────────────────────────────────
function PlatformBars({platforms}){
  const maxV=Math.max(...platforms.flatMap(p=>[p.leads,p.appts,p.sales]),1);
  const m=useMounted(150);
  return e('div',{className:'chart-card',style:{animationDelay:'.2s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Platform Volumes'),
      e(InfoTip,{text:'Absolute lead, appointment and sale counts per platform. Bar length is relative to the highest value across all platforms.'})
    ),
    e('div',{style:{display:'flex',flexDirection:'column',gap:18}},
      platforms.map(p=>{
        const color=PC[p.platform]||AMBER;
        const bg=PCbg[p.platform]||AMBERBG;
        const bars=[{lbl:'Leads',val:p.leads,op:1},{lbl:'Appts',val:p.appts,op:.65},{lbl:'Sales',val:p.sales,op:.4}];
        return e('div',{key:p.platform},
          e('div',{style:{display:'flex',alignItems:'center',gap:8,marginBottom:8}},
            e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:10,fontWeight:700,color,letterSpacing:2,textTransform:'uppercase'}},p.platform),
            e('span',{style:{marginLeft:'auto',fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2}},'£'+p.spend.toLocaleString('en-GB',{maximumFractionDigits:0}))
          ),
          e('div',{style:{display:'flex',flexDirection:'column',gap:5}},
            bars.map(b=>e('div',{key:b.lbl,style:{display:'flex',alignItems:'center',gap:8}},
              e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2,width:36,flexShrink:0}},b.lbl),
              e('div',{style:{flex:1,height:10,background:'rgba(0,0,0,0.05)',borderRadius:5,overflow:'hidden'}},
                e('div',{style:{height:'100%',borderRadius:5,background:color,opacity:b.op,
                  transform:m?`scaleX(${b.val/maxV})`:'scaleX(0)',transformOrigin:'left',
                  transition:'transform 1.4s cubic-bezier(.22,1,.36,1)'}})
              ),
              e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:10,color:TEXT,fontWeight:600,width:28,textAlign:'right',flexShrink:0}},fmtN(b.val))
            ))
          )
        );
      })
    )
  );
}

// ── Cost Bars ─────────────────────────────────────────────────────
function CostBars({platforms}){
  const maxV=Math.max(...platforms.flatMap(p=>[p.cpl||0,p.cpa||0,p.cps||0]),1);
  const m=useMounted(180);
  return e('div',{className:'chart-card',style:{animationDelay:'.25s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'CPL · CPA · CPS'),
      e(InfoTip,{text:'Cost per lead, per appointment, and per sale by platform. Shorter bar = more efficient spend. CPS is your true cost of acquiring a customer.'})
    ),
    e('div',{style:{display:'flex',flexDirection:'column',gap:18}},
      platforms.map(p=>{
        const color=PC[p.platform]||AMBER;
        const bars=[{lbl:'CPL',val:p.cpl||0,op:.9},{lbl:'CPA',val:p.cpa||0,op:.65},{lbl:'CPS',val:p.cps||0,op:.4}];
        return e('div',{key:p.platform},
          e('div',{style:{display:'flex',alignItems:'center',gap:8,marginBottom:8}},
            e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:10,fontWeight:700,color,letterSpacing:2,textTransform:'uppercase'}},p.platform)
          ),
          e('div',{style:{display:'flex',flexDirection:'column',gap:5}},
            bars.map(b=>e('div',{key:b.lbl,style:{display:'flex',alignItems:'center',gap:8}},
              e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2,width:30,flexShrink:0}},b.lbl),
              e('div',{style:{flex:1,height:10,background:'rgba(0,0,0,0.05)',borderRadius:5,overflow:'hidden'}},
                e('div',{style:{height:'100%',borderRadius:5,background:color,opacity:b.op,
                  transform:b.val>0&&m?`scaleX(${b.val/maxV})`:'scaleX(0)',transformOrigin:'left',
                  transition:'transform 1.5s cubic-bezier(.22,1,.36,1)'}})
              ),
              e('span',{style:{fontFamily:"'JetBrains Mono'",fontSize:10,color:TEXT,fontWeight:600,width:36,textAlign:'right',flexShrink:0}},b.val?gbp(b.val):'—')
            ))
          )
        );
      })
    )
  );
}

// ── Summary Table ─────────────────────────────────────────────────
function SummaryTable({platforms}){
  const [sortIdx,setSortIdx]=useState(1);
  const [asc,setAsc]=useState(false);
  const cols=['Platform','Spend','Leads','Appts','Sales','CPL','CPA','CPS','L→A','A→S','CTR'];
  const rawRows=platforms.map(p=>[
    p.platform, p.spend, p.leads, p.appts, p.sales,
    p.cpl||0, p.cpa||0, p.cps||0,
    p.l2a||0, p.a2s||0, p.ctr||0,
  ]);
  const sorted=[...rawRows].sort((a,b)=>{
    const av=typeof a[sortIdx]==='string'?a[sortIdx]:Number(a[sortIdx])||0;
    const bv=typeof b[sortIdx]==='string'?b[sortIdx]:Number(b[sortIdx])||0;
    return asc?(av>bv?1:-1):(av<bv?1:-1);
  });
  const fmtCell=(v,j)=>{
    if(j===0) return v;
    if(j===1) return gbp(v);
    if(j>=2&&j<=4) return fmtN(v);
    if(j>=5&&j<=7) return v?gbp(v):'—';
    return v?v.toFixed(0)+'%':'—';
  };
  const thStyle=(i)=>({
    cursor:'pointer',userSelect:'none',
    color:sortIdx===i?'#1C1917':'',
    transition:'color .15s',
  });
  const arrow=(i)=>sortIdx===i?(asc?' ↑':' ↓'):'';
  return e('div',{className:'chart-card',style:{animationDelay:'.3s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:14}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Platform Summary'),
      e(InfoTip,{text:'Full breakdown per platform. Click any column header to sort. All metrics reflect the selected date range and platform filter.'})
    ),
    e('table',{className:'tbl'},
      e('thead',null,e('tr',null,...cols.map((c,i)=>e('th',{key:c,style:thStyle(i),
        onClick:()=>{ if(sortIdx===i)setAsc(!asc); else{setSortIdx(i);setAsc(false);} }
      },c+arrow(i))))),
      e('tbody',null,...sorted.map((row,i)=>e('tr',{key:i},
        ...row.map((cell,j)=>e('td',{key:j,style:{
          color:j===0?(PC[cell]||TEXT):TEXT,
          fontWeight:j===0?700:400
        }},fmtCell(cell,j)))
      )))
    )
  );
}

// ── Lead Source Breakdown ─────────────────────────────────────────
function LeadSourceBreakdown({sources}){
  const m=useMounted(120);
  if(!sources||!sources.length) return null;
  const SCOL={Google:'#1A73E8',Meta:'#7C3AED',Bing:'#0D9488',Organic:'#78716C'};
  const SBCOL={Google:'#EEF4FF',Meta:'#F5F3FF',Bing:'#F0FDF9',Organic:'#F5F3F0'};
  const total=sources.reduce((s,r)=>s+r.leads,0);
  // order: paid platforms first, then organic
  const order=['Google','Meta','Bing','Organic'];
  const sorted=[...sources].sort((a,b)=>order.indexOf(a.source)-order.indexOf(b.source));

  return e('div',{className:'chart-card',style:{animationDelay:'.05s'}},
    e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:16}},
      e('div',{className:'chart-title',style:{marginBottom:0}},'Lead Sources'),
      e('div',{style:{display:'flex',alignItems:'center',gap:10}},
        e('div',{style:{fontFamily:"'Barlow Condensed',sans-serif",fontSize:'1.4rem',fontWeight:800,color:TEXT}},fmtN(total)),
        e('div',{style:{fontFamily:"'JetBrains Mono',monospace",fontSize:9,color:DIM2,letterSpacing:2}}, 'TOTAL LEADS'),
        e(InfoTip,{text:'All leads in SharpSpring for the period, split by how they arrived. Paid = linked to a Google, Meta or Bing campaign. Organic = no paid campaign attribution.'})
      )
    ),

    // Stacked proportion bar
    e('div',{style:{display:'flex',height:10,borderRadius:6,overflow:'hidden',marginBottom:20,gap:2}},
      sorted.map(r=>{
        const pct=total>0?r.leads/total:0;
        const color=SCOL[r.source]||'#999';
        return e('div',{key:r.source,title:r.source+': '+r.leads+' leads',style:{
          flex:m?pct:0,
          background:color,
          borderRadius:6,
          transition:'flex 1.4s cubic-bezier(.22,1,.36,1)',
          minWidth:m&&pct>0?2:0,
        }});
      })
    ),

    // Source cards row
    e('div',{style:{display:'grid',gridTemplateColumns:'repeat('+sorted.length+',1fr)',gap:12}},
      sorted.map(r=>{
        const color=SCOL[r.source]||'#999';
        const bg=SBCOL[r.source]||'#F5F5F5';
        const pct=total>0?(r.leads/total*100).toFixed(0):0;
        const l2a=r.leads>0?(r.appts/r.leads*100).toFixed(0):null;
        const isPaid=r.source!=='Organic';
        return e('div',{key:r.source,style:{
          background:bg,borderRadius:10,padding:'14px 16px',
          borderTop:'3px solid '+color,
        }},
          e('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:8}},
            e('div',{style:{fontFamily:"'JetBrains Mono',monospace",fontSize:10,fontWeight:700,color,letterSpacing:2,textTransform:'uppercase'}},r.source),
            e('div',{style:{fontFamily:"'JetBrains Mono',monospace",fontSize:9,color,background:color+'15',padding:'2px 8px',borderRadius:20,fontWeight:700}},pct+'%')
          ),
          e('div',{style:{fontFamily:"'Barlow Condensed',sans-serif",fontSize:'2rem',fontWeight:800,color:TEXT,lineHeight:1,marginBottom:6}},fmtN(r.leads)),
          e('div',{style:{display:'grid',gridTemplateColumns:'1fr 1fr',gap:4,fontFamily:"'JetBrains Mono',monospace",fontSize:9,color:DIM2}},
            e('div',null,'Appts',e('div',{style:{color:TEXT,fontWeight:700,fontSize:12,marginTop:1}},fmtN(r.appts))),
            e('div',null,'L→A',e('div',{style:{color:TEXT,fontWeight:700,fontSize:12,marginTop:1}},l2a?l2a+'%':'—')),
            e('div',null,'Sales',e('div',{style:{color:TEXT,fontWeight:700,fontSize:12,marginTop:1}},fmtN(r.sales))),
            e('div',null,'Type',e('div',{style:{color,fontWeight:700,fontSize:11,marginTop:1}},isPaid?'Paid':'Organic'))
          )
        );
      })
    )
  );
}

// ── Root App ──────────────────────────────────────────────────────
function App(){
  const {totals:T,platforms,daily,period,lead_sources}=DATA;
  const [selP,setSelP]=useState(null);

  // Filtered data based on selected platform
  const fp=selP?platforms.filter(p=>p.platform===selP):platforms;
  const fd=selP?daily.filter(r=>r.platform===selP):daily;
  const fT=fp.reduce((a,p)=>({
    spend:a.spend+p.spend, leads:a.leads+p.leads, appts:a.appts+p.appts,
    sales:a.sales+p.sales, clicks:a.clicks+(p.clicks||0),
  }),{spend:0,leads:0,appts:0,sales:0,clicks:0});
  fT.cpl=fT.leads>0?fT.spend/fT.leads:0;
  fT.cpa=fT.appts>0?fT.spend/fT.appts:0;
  fT.cps=fT.sales>0?fT.spend/fT.sales:0;
  const DT=selP?fT:T;

  const days=[...new Set(daily.map(r=>r.date))].length;

  const organicLeads = T.total_leads > 0 ? T.total_leads - T.leads : 0;
  const kpis=[
    {label:'Total Spend',  value:DT.spend,    prefix:'£', accent:AMBER,     icon:'💷', ibg:AMBERBG,      delay:0,
     info:'Total paid media spend across all active platforms for the selected period.'},
    {label:'Total Leads',  value:T.total_leads, sub:fmtN(T.total_leads)+' across all sources', icon:'👥', ibg:'#F0F4FF', delay:60,
     info:'Every lead that entered SharpSpring in the period, regardless of source — paid, organic, direct, or unknown.'},
    {label:'Paid Leads',   value:DT.leads,    sub:'from '+fmtN(DT.clicks)+' clicks', icon:'📋', ibg:PCbg.Google, delay:120,
     info:'Leads linked to a Google, Meta or Bing campaign via SharpSpring campaign ID. Some campaigns may be unmapped — totals can be understated.'},
    {label:'Appointments', value:DT.appts,    showZero:true, sub:DT.leads>0?(DT.appts/DT.leads*100).toFixed(0)+'% of paid leads':'—', icon:'📅', ibg:PCbg.Meta, delay:180,
     info:'Leads that progressed to a booked survey or appointment. Conversion rate is against paid leads only.'},
    {label:'Sales',        value:DT.sales,    showZero:true, sub:DT.appts>0?(DT.sales/DT.appts*100).toFixed(0)+'% of appts':'—', accent:AMBER, icon:'✅', ibg:AMBERBG, delay:240,
     info:'Appointments that confirmed as a sale. Sub-row shows close rate from appointment to sale.'},
    {label:'Blended CPL',  value:DT.cpl>0?Math.round(DT.cpl):0, prefix:'£', accent:PC.Google, icon:'🎯', ibg:PCbg.Google, delay:300,
     info:'Total spend ÷ total paid leads, blended across all platforms. Lower is better.'},
    {label:'Blended CPS',  value:DT.cps>0?Math.round(DT.cps):0, prefix:'£', accent:PC.Bing,   icon:'📈', ibg:PCbg.Bing,   delay:360,
     info:'Total spend ÷ confirmed sales — your true cost of acquiring a paying customer across all channels.'},
  ];

  // Platform filter pill style
  const pillStyle=(name)=>{
    const active=selP===name;
    const color=name==='All'?AMBER:PC[name];
    const bg=name==='All'?AMBERBG:PCbg[name];
    return {
      background:active?color:'transparent',
      color:active?'#fff':color,
      borderColor:active?color:color+'55',
      boxShadow:active?'0 4px 12px '+color+'44':'none',
      transform:active?'scale(1.05)':'scale(1)',
    };
  };

  return e('div',null,
    // Header
    e('div',{className:'hdr'},
      e('div',{style:{display:'flex',alignItems:'flex-end',justifyContent:'space-between',flexWrap:'wrap',gap:16}},
        e('div',{className:'hdr-title'},'Marketing Analytics'),
        e('div',{style:{display:'flex',flexDirection:'column',alignItems:'flex-end',gap:8,paddingBottom:4}},
          e('div',{style:{fontFamily:"'JetBrains Mono',monospace",fontSize:9,color:'#A8A29E',letterSpacing:'2px',textTransform:'uppercase'}},
            'PERIOD: '+period.toUpperCase()+' · '+days+' DAYS'
          ),
          e('div',{style:{display:'flex',gap:6}},
            ...Object.entries(PC).map(([name,color])=>e('span',{key:name,className:'badge',style:{
              background:PCbg[name]||AMBERBG, border:'1.5px solid '+color+'33', color
            }},name))
          )
        )
      ),
      e('div',{className:'hdr-rule',style:{marginTop:18}})
    ),

    // Platform filter bar
    e('div',{className:'pf-bar'},
      e('span',{className:'pf-lbl'},'Filter:'),
      e('button',{className:'pf-pill',style:pillStyle('All'),onClick:()=>setSelP(null)},'All Platforms'),
      ...Object.entries(PC).map(([name,color])=>
        e('button',{key:name,className:'pf-pill',style:pillStyle(name),
          onClick:()=>setSelP(selP===name?null:name)
        },name)
      )
    ),

    // KPIs
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Summary'),
      e('div',{className:'g7'},...kpis.map((k,i)=>e(KpiCard,{key:i,...k})))
    ),

    e('div',{className:'div'}),

    // Lead Sources
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Lead Sources'),
      e(LeadSourceBreakdown,{sources:lead_sources})
    ),

    e('div',{className:'div'}),

    // Platform cards
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Platform Breakdown'),
      e('div',{className:'g3'},...fp.map((p,i)=>e(PlatformCard,{key:p.platform,p,totalSpend:DT.spend,delay:i*80})))
    ),

    e('div',{className:'div'}),

    // Donut + Area chart
    e('div',{className:'g21 sec'},
      e(Donut,{platforms:fp,total:DT.spend}),
      e(AreaChart,{daily:fd})
    ),

    e('div',{className:'div'}),

    // Funnels
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Lead Funnel by Platform'),
      e('div',{className:'g3'},...fp.map((p,i)=>e(FunnelCard,{key:p.platform,p,delay:i*100})))
    ),

    e('div',{className:'div'}),

    // Performance charts
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Performance Trends'),
      e('div',{className:'g2'},e(CplChart,{daily:fd}),e(LeadsChart,{daily:fd}))
    ),

    e('div',{className:'div'}),

    // Compare bars
    e('div',{className:'g2 sec'},e(PlatformBars,{platforms:fp}),e(CostBars,{platforms:fp})),

    e('div',{className:'div'}),

    e('div',{className:'sec'},e(SummaryTable,{platforms:fp})),

    e('div',{className:'footer-note'},
      '⚠ Lead counts reflect SharpSpring campaign_id attribution only. Some Google campaigns (e.g. Google Search) are not mapped — paid lead totals may be understated.',
      e('br',null),
      'Powered by MotherDuck · dbt · Airbyte · React 18 · Pure SVG'
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
</script>
</body>
</html>
""".replace('INJECT_DATA', DATA_JSON)

st.components.v1.html(REACT_HTML, height=3000, scrolling=True)
