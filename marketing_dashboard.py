import os, json, math
from datetime import date, timedelta

import duckdb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Marketing Intelligence", page_icon="💰",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700;800;900&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap');
html,body,.stApp,[data-testid="stAppViewContainer"]{background:#07090F!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:0.6rem 1.5rem 1rem!important;max-width:100%!important;}
[data-testid="stSelectbox"]>div>div{background:#0D1120!important;border:1px solid rgba(255,255,255,0.09)!important;color:#CBD5E1!important;border-radius:6px!important;font-family:'DM Sans',sans-serif!important;}
[data-testid="stButton"]>button{background:rgba(245,158,11,0.1)!important;border:1px solid rgba(245,158,11,0.35)!important;color:#F59E0B!important;font-weight:600!important;border-radius:6px!important;font-family:'DM Sans',sans-serif!important;letter-spacing:1px!important;}
[data-testid="stButton"]>button:hover{background:rgba(245,158,11,0.22)!important;border-color:rgba(245,158,11,0.6)!important;}
[data-testid="stDateInput"] input{background:#0D1120!important;border:1px solid rgba(255,255,255,0.09)!important;color:#CBD5E1!important;border-radius:6px!important;}
.stTabs [role="tab"]{color:#4B5563!important;font-family:'JetBrains Mono',monospace!important;font-size:11px!important;letter-spacing:2px!important;text-transform:uppercase!important;}
.stTabs [role="tab"][aria-selected="true"]{color:#F59E0B!important;border-bottom-color:#F59E0B!important;}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ────────────────────────────────────────────────────────────────────
def _connect():
    return duckdb.connect(f"md:trust-pipeline?motherduck_token={os.getenv('MOTHERDUCK_TOKEN','')}")

@st.cache_data(ttl=1800, show_spinner="Querying MotherDuck…")
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
        SELECT coalesce(m.platform,'Other Paid') as platform,
               coalesce(g.customer_type,'Unknown') as customer_type,
               count(*) as leads
        FROM gold.gold_lead_activity g
        INNER JOIN silver.campaign_platform_mapping m ON g.campaign_id = m.campaign_id
        WHERE g.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1,2 ORDER BY 1,3 DESC
    """).df()
    con.close()
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

c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
with c1:
    preset = st.selectbox("Period", PRESETS, index=0, label_visibility="collapsed")
if preset == "Custom":
    with c2:
        d0 = st.date_input("From", value=yesterday - timedelta(30), max_value=yesterday,
                           label_visibility="collapsed", key="m_from")
    with c3:
        d1 = st.date_input("To", value=yesterday, max_value=yesterday,
                           label_visibility="collapsed", key="m_to")
else:
    d0, d1 = PRESET_DATES[preset]
with c4:
    if st.button("↺  REFRESH"):
        st.cache_data.clear(); st.rerun()

# ── DATA ───────────────────────────────────────────────────────────────────────
df    = load_attr(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))
df_ct = load_customer_types(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))

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

# ── SERIALISE DATA ─────────────────────────────────────────────────────────────
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

ct_records = []
for _, row in df_ct.iterrows():
    ct_records.append({'platform': str(row['platform']),
                       'customer_type': str(row['customer_type']),
                       'leads': int(row['leads'])})

DATA_JSON = json.dumps({
    'period': f"{d0.strftime('%d %b')} – {d1.strftime('%d %b %Y')}",
    'totals': {
        'spend': tot_sp, 'leads': tot_ld, 'appts': tot_ap,
        'sales': tot_sa, 'clicks': tot_cl,
        'cpl': b_cpl, 'cpa': b_cpa, 'cps': b_cps,
    },
    'platforms': platform_records,
    'daily': daily_records,
    'customerTypes': ct_records,
})

# ── REACT DASHBOARD ────────────────────────────────────────────────────────────
REACT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/recharts@2.12.7/umd/Recharts.js"></script>
<script src="https://unpkg.com/@babel/standalone@7.24.7/babel.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#07090F;
  --s1:#0D1120;
  --s2:#141929;
  --border:rgba(255,255,255,0.07);
  --bh:rgba(255,255,255,0.14);
  --text:#CBD5E1;
  --dim:#4B5563;
  --gold:#F59E0B;
  --gold2:#FCD34D;
  --google:#4285F4;
  --meta:#8B5CF6;
  --bing:#10B981;
}
html,body{background:var(--bg);color:var(--text);font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.5;}
body{padding:24px 28px 40px;}

/* ── HEADER ── */
.hdr{margin-bottom:28px;padding-bottom:22px;border-bottom:1px solid var(--border);}
.hdr-eye{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:4px;color:var(--gold);opacity:.7;text-transform:uppercase;margin-bottom:6px;}
.hdr-title{font-family:'Barlow Condensed',sans-serif;font-size:2.9rem;font-weight:800;color:var(--text);letter-spacing:.5px;line-height:1.05;}
.hdr-title em{color:var(--gold);font-style:normal;}
.hdr-meta{display:flex;align-items:center;gap:10px;margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);letter-spacing:2px;}
.badge{padding:2px 9px;border-radius:4px;font-size:10px;font-weight:600;letter-spacing:2px;text-transform:uppercase;}

/* ── GRID ── */
.g6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}
.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;}
.g21{display:grid;grid-template-columns:2fr 3fr;gap:14px;}
.section{margin-bottom:22px;}
.sec-label{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:4px;color:var(--dim);text-transform:uppercase;margin-bottom:12px;}
.divider{height:1px;background:var(--border);margin:22px 0;}

/* ── CARDS ── */
.card{
  background:var(--s1);
  border:1px solid var(--border);
  border-radius:8px;
  padding:20px;
  transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease,background .2s ease;
}
.card:hover{
  transform:translateY(-3px);
  border-color:var(--bh);
  box-shadow:0 12px 40px rgba(0,0,0,.5);
  background:var(--s2);
}

/* ── KPI CARDS ── */
.kpi-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:3.5px;color:var(--dim);text-transform:uppercase;margin-bottom:10px;}
.kpi-val{font-family:'Barlow Condensed',sans-serif;font-size:2.55rem;font-weight:700;line-height:1;margin-bottom:6px;}
.kpi-sub{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--dim);}

/* ── PLATFORM CARDS ── */
.plat-name{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;}
.plat-spend{font-family:'Barlow Condensed',sans-serif;font-size:2.3rem;font-weight:700;line-height:1;margin-bottom:6px;}
.plat-bar-track{height:5px;background:rgba(255,255,255,0.06);border-radius:3px;margin:8px 0 14px;}
.plat-bar-fill{height:5px;border-radius:3px;transition:width 1.2s cubic-bezier(.22,1,.36,1);}
.plat-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);}
.plat-stat-val{font-size:13px;font-weight:600;color:var(--text);margin-top:1px;}

/* ── CHART CARDS ── */
.chart-card{
  background:var(--s1);
  border:1px solid var(--border);
  border-radius:8px;
  padding:20px 20px 12px;
  transition:border-color .2s ease;
}
.chart-card:hover{border-color:var(--bh);}
.chart-title{font-family:'Barlow Condensed',sans-serif;font-size:1.05rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text);margin-bottom:16px;}

/* ── FUNNEL ── */
.funnel-row{margin-bottom:10px;}
.funnel-bar-track{background:rgba(255,255,255,0.05);border-radius:4px;height:32px;overflow:hidden;position:relative;}
.funnel-bar-fill{height:100%;border-radius:4px;display:flex;align-items:center;padding:0 10px;transition:width 1.4s cubic-bezier(.22,1,.36,1);}
.funnel-lbl-row{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);margin-bottom:4px;}
.funnel-footer{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:14px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);}
.funnel-footer span{color:var(--text);margin-left:4px;}

/* ── TOOLTIP ── */
.tt{background:#0D1120;border:1px solid rgba(255,255,255,0.13);border-radius:6px;padding:10px 14px;font-family:'JetBrains Mono',monospace;font-size:11px;}
.tt-label{color:#94A3B8;margin-bottom:7px;font-size:10px;}
.tt-row{margin-bottom:3px;}

/* ── TABLE ── */
.data-table{width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:11px;}
.data-table th{color:var(--dim);font-weight:500;letter-spacing:2px;font-size:9px;text-transform:uppercase;padding:8px 12px;border-bottom:1px solid var(--border);text-align:left;}
.data-table td{padding:9px 12px;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--text);transition:background .15s;}
.data-table tr:hover td{background:rgba(255,255,255,0.03);}

/* ── FOOTER ── */
.footer{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--dim);margin-top:28px;padding-top:18px;border-top:1px solid var(--border);line-height:1.8;}

@keyframes fadeUp{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
.fade-in{animation:fadeUp .45s ease both;}
.fade-in-2{animation:fadeUp .45s .1s ease both;}
.fade-in-3{animation:fadeUp .45s .2s ease both;}
.fade-in-4{animation:fadeUp .45s .3s ease both;}
</style>
</head>
<body>
<div id="root"></div>
<script>window.__DATA__ = DATA_PLACEHOLDER;</script>
<script type="text/babel" data-presets="react">
const { useState, useEffect, useRef, useMemo } = React;
const {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ComposedChart,
} = Recharts;

const D = window.__DATA__;
const PC = { Google: '#4285F4', Meta: '#8B5CF6', Bing: '#10B981' };
const GOLD = '#F59E0B';
const DIM  = '#4B5563';

// Count-up number animation
function useCountUp(target, ms = 1100) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let t = 0;
    const step = target / (ms / 16);
    const id = setInterval(() => {
      t = Math.min(t + step, target);
      setV(t);
      if (t >= target) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  }, [target]);
  return v;
}

// Shared tooltip
function TT({ active, payload, label, fmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tt">
      <div className="tt-label">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="tt-row" style={{ color: p.color }}>
          {p.name}: <strong>{fmt ? fmt(p.value, p.name) : p.value}</strong>
        </div>
      ))}
    </div>
  );
}

// KPI card with count-up
function KpiCard({ label, value, sub, accent, prefix = '', suffix = '', delay = '0s' }) {
  const num = typeof value === 'number' ? value : 0;
  const counted = useCountUp(num);
  const formatted = num > 0
    ? prefix + Math.round(counted).toLocaleString('en-GB') + suffix
    : (value === 0 && prefix === '£' ? '£0' : (value || '—'));

  return (
    <div className="card fade-in" style={{ borderLeft: `3px solid ${accent || 'var(--border)'}`, animationDelay: delay }}>
      <div className="kpi-lbl">{label}</div>
      <div className="kpi-val" style={{ color: accent || 'var(--text)' }}>{formatted}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

// Platform summary card
function PlatformCard({ p, totalSpend }) {
  const color = PC[p.platform] || GOLD;
  const pct = totalSpend > 0 ? (p.spend / totalSpend * 100) : 0;
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setTimeout(() => setMounted(true), 100); }, []);

  return (
    <div className="card fade-in-2" style={{ borderTop: `3px solid ${color}` }}>
      <div className="plat-name" style={{ color }}>{p.platform}</div>
      <div className="plat-spend" style={{ color }}>
        £{p.spend.toLocaleString('en-GB', { maximumFractionDigits: 0 })}
      </div>
      <div className="plat-bar-track">
        <div className="plat-bar-fill"
          style={{ width: mounted ? `${Math.min(pct, 100)}%` : '0%', background: color, opacity: .65 }} />
      </div>
      <div className="plat-grid">
        {[
          ['Leads',  p.leads.toLocaleString()],
          ['Appts',  p.appts.toLocaleString()],
          ['CPL',    p.cpl ? `£${Math.round(p.cpl)}` : '—'],
          ['L→A',    p.l2a ? `${p.l2a.toFixed(0)}%` : '—'],
          ['Sales',  p.sales.toLocaleString()],
          ['CTR',    p.ctr ? `${p.ctr.toFixed(2)}%` : '—'],
        ].map(([lbl, val]) => (
          <div key={lbl}>
            <div>{lbl}</div>
            <div className="plat-stat-val">{val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Spend donut
function SpendDonut({ platforms, total }) {
  const [activeIdx, setActiveIdx] = useState(null);
  const data = platforms.map(p => ({ name: p.platform, value: +p.spend.toFixed(2) }));
  const RADIAN = Math.PI / 180;

  const renderLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent, name }) => {
    const r = innerRadius + (outerRadius - innerRadius) * .5;
    const x = cx + r * Math.cos(-midAngle * RADIAN);
    const y = cy + r * Math.sin(-midAngle * RADIAN);
    return percent > .07 ? (
      <text x={x} y={y} fill="rgba(255,255,255,0.9)" textAnchor="middle" dominantBaseline="central"
        style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 600 }}>
        {(percent * 100).toFixed(0)}%
      </text>
    ) : null;
  };

  return (
    <div className="chart-card fade-in-3">
      <div className="chart-title">Spend Distribution</div>
      <div style={{ textAlign: 'center', position: 'relative' }}>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" innerRadius={72} outerRadius={118}
              paddingAngle={3} dataKey="value" labelLine={false} label={renderLabel}
              onMouseEnter={(_, i) => setActiveIdx(i)} onMouseLeave={() => setActiveIdx(null)}>
              {data.map((entry, i) => (
                <Cell key={i} fill={PC[entry.name] || GOLD} stroke="transparent"
                  opacity={activeIdx === null || activeIdx === i ? 1 : .35} />
              ))}
            </Pie>
            <Tooltip content={<TT fmt={(v) => '£' + v.toLocaleString('en-GB', { maximumFractionDigits: 0 })} />} />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', pointerEvents: 'none', textAlign: 'center' }}>
          <div style={{ fontFamily: "'Barlow Condensed'", fontSize: '1.5rem', fontWeight: 700, color: GOLD }}>
            £{Math.round(total).toLocaleString('en-GB')}
          </div>
          <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, color: DIM, letterSpacing: 2, marginTop: 2 }}>TOTAL</div>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 20, marginTop: 8 }}>
        {platforms.map(p => (
          <span key={p.platform} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
            fontFamily: "'JetBrains Mono'", fontSize: 10, color: DIM }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: PC[p.platform], display: 'inline-block' }} />
            {p.platform}
          </span>
        ))}
      </div>
    </div>
  );
}

// Daily spend area chart
function DailySpendChart({ daily }) {
  const dateMap = {};
  daily.forEach(r => {
    if (!dateMap[r.date]) dateMap[r.date] = { date: r.date };
    dateMap[r.date][r.platform] = (dateMap[r.date][r.platform] || 0) + (r.spend || 0);
  });
  const data = Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
  const fmt = d => { const p = d.split('-'); return p[2] + '/' + p[1]; };
  const platforms = Object.keys(PC).filter(p => data.some(d => d[p]));

  return (
    <div className="chart-card fade-in-3">
      <div className="chart-title">Daily Spend by Platform</div>
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <defs>
            {platforms.map(p => (
              <linearGradient key={p} id={`g_${p}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={PC[p]} stopOpacity={0.28} />
                <stop offset="95%" stopColor={PC[p]} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmt}
            tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }}
            tickLine={false} axisLine={false} />
          <YAxis tickFormatter={v => '£' + (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v)}
            tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }}
            tickLine={false} axisLine={false} />
          <Tooltip content={<TT fmt={v => '£' + (v || 0).toFixed(2)} />} labelFormatter={fmt} />
          {platforms.map(p => (
            <Area key={p} type="monotone" dataKey={p} name={p}
              stroke={PC[p]} strokeWidth={2.5} fill={`url(#g_${p})`} dot={false} />
          ))}
          <Legend wrapperStyle={{ fontFamily: "'JetBrains Mono'", fontSize: 10, paddingTop: 8 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// Funnel chart per platform
function FunnelChart({ p }) {
  const color = PC[p.platform] || GOLD;
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setTimeout(() => setMounted(true), 150); }, []);

  const steps = [
    { label: 'Leads',        value: p.leads, pct: 100 },
    { label: 'Appointments', value: p.appts, pct: p.leads > 0 ? p.appts / p.leads * 100 : 0 },
    { label: 'Sales',        value: p.sales, pct: p.leads > 0 ? p.sales / p.leads * 100 : 0 },
  ];
  const opacities = [1, .65, .4];

  return (
    <div className="chart-card fade-in-4">
      <div className="chart-title" style={{ color }}>{p.platform}</div>
      {steps.map((s, i) => (
        <div key={i} className="funnel-row">
          <div className="funnel-lbl-row">
            <span>{s.label}</span>
            <span style={{ color: 'var(--text)', fontWeight: 600 }}>{s.value.toLocaleString()}</span>
          </div>
          <div className="funnel-bar-track">
            <div className="funnel-bar-fill"
              style={{
                width: mounted ? `${Math.max(s.pct, s.value > 0 ? 3 : 0)}%` : '0%',
                background: color,
                opacity: opacities[i],
              }}>
              {s.pct > 20 && i > 0 && (
                <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, color: 'rgba(255,255,255,.85)' }}>
                  {s.pct.toFixed(0)}%
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
      <div className="funnel-footer">
        <div>Lead→Appt <span>{p.l2a ? `${p.l2a.toFixed(0)}%` : '—'}</span></div>
        <div>Appt→Sale <span>{p.a2s ? `${p.a2s.toFixed(0)}%` : '—'}</span></div>
        <div>CPL <span>{p.cpl ? `£${Math.round(p.cpl)}` : '—'}</span></div>
        <div>CPA <span>{p.cpa ? `£${Math.round(p.cpa)}` : '—'}</span></div>
      </div>
    </div>
  );
}

// CPL trend
function CplChart({ daily }) {
  const dateMap = {};
  daily.filter(r => r.cpl).forEach(r => {
    if (!dateMap[r.date]) dateMap[r.date] = { date: r.date };
    dateMap[r.date][r.platform] = r.cpl;
  });
  const data = Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
  if (!data.length) return null;
  const fmt = d => { const p = d.split('-'); return p[2] + '/' + p[1]; };
  const platforms = Object.keys(PC).filter(p => data.some(d => d[p]));

  return (
    <div className="chart-card">
      <div className="chart-title">Cost Per Lead</div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmt}
            tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <YAxis tickFormatter={v => '£' + v}
            tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <Tooltip content={<TT fmt={v => '£' + (v || 0).toFixed(2)} />} labelFormatter={fmt} />
          {platforms.map(p => (
            <Line key={p} type="monotone" dataKey={p} name={p}
              stroke={PC[p]} strokeWidth={2.5} dot={{ r: 4, fill: PC[p], strokeWidth: 0 }}
              activeDot={{ r: 6 }} connectNulls={false} />
          ))}
          <Legend wrapperStyle={{ fontFamily: "'JetBrains Mono'", fontSize: 10, paddingTop: 8 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// Leads vs Appts combo chart
function LeadsApptChart({ daily }) {
  const dateMap = {};
  daily.forEach(r => {
    if (!dateMap[r.date]) dateMap[r.date] = { date: r.date, leads: 0, appts: 0, sales: 0 };
    dateMap[r.date].leads += r.leads || 0;
    dateMap[r.date].appts += r.appts || 0;
    dateMap[r.date].sales += r.sales || 0;
  });
  const data = Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
  const fmt = d => { const p = d.split('-'); return p[2] + '/' + p[1]; };

  return (
    <div className="chart-card">
      <div className="chart-title">Leads · Appointments · Sales</div>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={fmt}
            tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <Tooltip content={<TT />} labelFormatter={fmt} />
          <Bar dataKey="leads" name="Leads" fill="rgba(245,158,11,0.25)" radius={[3, 3, 0, 0]} />
          <Line dataKey="appts" name="Appts" type="monotone"
            stroke={GOLD} strokeWidth={2.5} dot={{ r: 4, fill: GOLD, strokeWidth: 0 }} activeDot={{ r: 6 }} />
          <Line dataKey="sales" name="Sales" type="monotone"
            stroke="#4285F4" strokeWidth={2} strokeDasharray="5 3"
            dot={{ r: 3, fill: '#4285F4', strokeWidth: 0 }} activeDot={{ r: 5 }} />
          <Legend wrapperStyle={{ fontFamily: "'JetBrains Mono'", fontSize: 10, paddingTop: 8 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// Platform comparison bar chart
function PlatformCompareChart({ platforms }) {
  const data = platforms.map(p => ({
    name: p.platform,
    Leads: p.leads,
    Appointments: p.appts,
    Sales: p.sales,
  }));

  return (
    <div className="chart-card">
      <div className="chart-title">Leads · Appointments · Sales by Platform</div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barCategoryGap="30%">
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="name" tick={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fill: DIM }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <Tooltip content={<TT />} />
          {platforms.map((p, i) => null)}
          <Bar dataKey="Leads" fill="rgba(245,158,11,0.55)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Appointments" fill="rgba(245,158,11,0.3)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Sales" fill="rgba(66,133,244,0.5)" radius={[3, 3, 0, 0]} />
          <Legend wrapperStyle={{ fontFamily: "'JetBrains Mono'", fontSize: 10, paddingTop: 8 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// CPM / cost comparison
function CostCompareChart({ platforms }) {
  const data = platforms.map(p => ({
    name: p.platform,
    CPL: p.cpl ? +p.cpl.toFixed(2) : 0,
    CPA: p.cpa ? +p.cpa.toFixed(2) : 0,
    CPS: p.cps ? +p.cps.toFixed(2) : 0,
  }));

  return (
    <div className="chart-card">
      <div className="chart-title">CPL · CPA · CPS by Platform</div>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barCategoryGap="30%">
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
          <XAxis dataKey="name" tick={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fill: DIM }} tickLine={false} axisLine={false} />
          <YAxis tickFormatter={v => '£' + v} tick={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fill: DIM }} tickLine={false} axisLine={false} />
          <Tooltip content={<TT fmt={(v, name) => '£' + (v || 0).toFixed(2)} />} />
          <Bar dataKey="CPL"  fill={PC.Google}           radius={[3,3,0,0]} opacity={.85} />
          <Bar dataKey="CPA"  fill={PC.Meta}             radius={[3,3,0,0]} opacity={.75} />
          <Bar dataKey="CPS"  fill="rgba(245,158,11,.7)" radius={[3,3,0,0]} />
          <Legend wrapperStyle={{ fontFamily: "'JetBrains Mono'", fontSize: 10, paddingTop: 8 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// Data table
function SummaryTable({ platforms }) {
  const cols = ['Platform','Spend','Leads','Appts','Sales','CPL','CPA','CPS','L→A','A→S','CTR'];
  const rows = platforms.map(p => [
    p.platform,
    '£' + p.spend.toLocaleString('en-GB', { maximumFractionDigits: 0 }),
    p.leads.toLocaleString(),
    p.appts.toLocaleString(),
    p.sales.toLocaleString(),
    p.cpl ? '£' + Math.round(p.cpl) : '—',
    p.cpa ? '£' + Math.round(p.cpa) : '—',
    p.cps ? '£' + Math.round(p.cps) : '—',
    p.l2a ? p.l2a.toFixed(0) + '%' : '—',
    p.a2s ? p.a2s.toFixed(0) + '%' : '—',
    p.ctr ? p.ctr.toFixed(2) + '%' : '—',
  ]);

  return (
    <div className="chart-card">
      <div className="chart-title">Platform Summary</div>
      <table className="data-table">
        <thead>
          <tr>{cols.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} style={{ color: j === 0 ? PC[cell] || 'var(--text)' : 'var(--text)' }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Root app
function App() {
  const { totals: T, platforms, daily, period } = D;
  const days = [...new Set(daily.map(r => r.date))].length;

  return (
    <div>
      {/* Header */}
      <div className="hdr">
        <div className="hdr-eye">Trust Electric Heating &nbsp;·&nbsp; Paid Media Intelligence</div>
        <div className="hdr-title">Ad Performance <em>&amp; Attribution</em></div>
        <div className="hdr-meta">
          <span>PERIOD: {period.toUpperCase()}</span>
          <span style={{ color: 'var(--border)' }}>|</span>
          <span>{days} days</span>
          {Object.entries(PC).map(([name, color]) => (
            <span key={name} className="badge" style={{
              background: `${color}1A`, border: `1px solid ${color}44`, color,
            }}>{name}</span>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div className="section">
        <div className="sec-label">Summary</div>
        <div className="g6">
          <KpiCard label="Total Spend"    value={T.spend}  prefix="£" accent={GOLD}   delay="0s"   />
          <KpiCard label="Paid Leads"     value={T.leads}  sub={`from ${T.clicks.toLocaleString()} clicks`} delay=".05s" />
          <KpiCard label="Appointments"   value={T.appts}  sub={T.leads > 0 ? `${(T.appts/T.leads*100).toFixed(0)}% of leads` : '—'} delay=".1s" />
          <KpiCard label="Sales"          value={T.sales}  sub={T.appts > 0 ? `${(T.sales/T.appts*100).toFixed(0)}% of appts` : '—'} accent={GOLD} delay=".15s" />
          <KpiCard label="Blended CPL"    value={Math.round(T.cpl)} prefix="£" accent={GOLD} delay=".2s" />
          <KpiCard label="Blended CPS"    value={T.cps > 0 ? Math.round(T.cps) : '—'} prefix={T.cps > 0 ? '£' : ''} delay=".25s" />
        </div>
      </div>

      <div className="divider" />

      {/* Platform Cards */}
      <div className="section">
        <div className="sec-label">Platform Breakdown</div>
        <div className="g3">
          {platforms.map(p => <PlatformCard key={p.platform} p={p} totalSpend={T.spend} />)}
        </div>
      </div>

      <div className="divider" />

      {/* Spend charts row */}
      <div className="section g21">
        <SpendDonut platforms={platforms} total={T.spend} />
        <DailySpendChart daily={daily} />
      </div>

      <div className="divider" />

      {/* Funnel row */}
      <div className="section">
        <div className="sec-label">Lead Funnel by Platform</div>
        <div className="g3">
          {platforms.map(p => <FunnelChart key={p.platform} p={p} />)}
        </div>
      </div>

      <div className="divider" />

      {/* Performance charts */}
      <div className="section">
        <div className="sec-label">Performance Trends</div>
        <div className="g2">
          <CplChart daily={daily} />
          <LeadsApptChart daily={daily} />
        </div>
      </div>

      <div className="divider" />

      {/* Platform compare */}
      <div className="section g2">
        <PlatformCompareChart platforms={platforms} />
        <CostCompareChart platforms={platforms} />
      </div>

      <div className="divider" />

      {/* Summary table */}
      <div className="section">
        <SummaryTable platforms={platforms} />
      </div>

      {/* Footer */}
      <div className="footer">
        ⚠ Lead counts reflect SharpSpring campaign_id attribution only.
        Some Google campaigns (e.g. Google Search) are not mapped — paid lead totals may be understated.
        Update campaign_platform_mapping seed to include all active campaigns.
        &nbsp;·&nbsp; Powered by MotherDuck · dbt · Airbyte · Recharts
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body>
</html>
""".replace('DATA_PLACEHOLDER', DATA_JSON)

st.components.v1.html(REACT_HTML, height=2800, scrolling=True)
