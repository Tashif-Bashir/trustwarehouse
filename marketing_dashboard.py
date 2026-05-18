import os, json, math
from datetime import date, timedelta

import duckdb
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
.block-container{padding:0.5rem 1.4rem 0.5rem!important;max-width:100%!important;}
[data-testid="stSelectbox"]>div>div{background:#fff!important;border:1px solid rgba(0,0,0,0.12)!important;color:#1C1917!important;border-radius:8px!important;}
[data-testid="stButton"]>button{background:#fff!important;border:1px solid rgba(0,0,0,0.15)!important;color:#1C1917!important;font-weight:600!important;border-radius:8px!important;transition:all .2s!important;}
[data-testid="stButton"]>button:hover{border-color:#D97706!important;color:#D97706!important;background:#FFFBF0!important;}
[data-testid="stDateInput"] input{background:#fff!important;border:1px solid rgba(0,0,0,0.12)!important;color:#1C1917!important;border-radius:8px!important;}
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

DATA_JSON = json.dumps({
    'period': f"{d0.strftime('%d %b')} – {d1.strftime('%d %b %Y')}",
    'totals': {
        'spend': tot_sp, 'leads': tot_ld, 'appts': tot_ap,
        'sales': tot_sa, 'clicks': tot_cl,
        'cpl': b_cpl, 'cpa': b_cpa, 'cps': b_cps,
    },
    'platforms': platform_records,
    'daily': daily_records,
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
  --amber:#D97706;
  --amber-l:#F59E0B;
  --amber-bg:#FFFBEB;
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
.hdr-rule{height:3px;background:linear-gradient(90deg,var(--google) 0%,var(--meta) 40%,var(--bing) 70%,transparent 100%);margin-top:14px;border-radius:2px;opacity:.5;}
.hdr-meta{display:flex;align-items:center;gap:10px;margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--dim);letter-spacing:1.5px;flex-wrap:wrap;}
.badge{padding:3px 10px;border-radius:20px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;}

.g6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;}
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
  overflow:hidden;
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
const AMBER = '#D97706', AMBERL = '#F59E0B', AMBERBG = '#FFFBEB';
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

// ── KPI Card ──────────────────────────────────────────────────────
function KpiCard({label,value,sub,accent,prefix='',icon,delay=0,bgAccent}){
  const num = typeof value==='number'?value:0;
  const counted = useCountUp(num, delay);
  const display = num>0 ? prefix+Math.round(counted).toLocaleString('en-GB') : (value||'—');
  return e('div',{className:`card d${Math.floor(delay/60)}`,style:{animationDelay:delay+'ms'}},
    e('div',{className:'kpi-accent',style:{background:accent||AMBER}}),
    e('div',{className:'kpi-icon',style:{background:bgAccent||AMBERBG}},icon||''),
    e('div',{className:'kpi-lbl'},label),
    e('div',{className:'kpi-val',style:{color:accent||AMBER,animationDelay:(delay+100)+'ms'}},display),
    sub && e('div',{className:'kpi-sub'},sub)
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
      e('div',{className:'plat-chip',style:{background:bg,color}},
        pct.toFixed(0)+'% of budget'
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
    e('div',{className:'chart-title'},'Daily Spend by Platform'),
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
    e('div',{className:'chart-title'},'Spend Distribution'),
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
      e('div',{style:{marginLeft:'auto',fontFamily:"'JetBrains Mono'",fontSize:9,color:DIM2,letterSpacing:1}},fmtN(p.leads)+' leads')
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
    e('div',{className:'chart-title'},'Cost Per Lead'),
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
    e('div',{className:'chart-title'},'Leads · Appointments · Sales'),
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
    e('div',{className:'chart-title'},'Platform Volumes'),
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
    e('div',{className:'chart-title'},'CPL · CPA · CPS'),
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
  const cols=['Platform','Spend','Leads','Appts','Sales','CPL','CPA','CPS','L→A','A→S','CTR'];
  const rows=platforms.map(p=>[
    p.platform,gbp(p.spend),fmtN(p.leads),fmtN(p.appts),fmtN(p.sales),
    p.cpl?gbp(p.cpl):'—',p.cpa?gbp(p.cpa):'—',p.cps?gbp(p.cps):'—',
    p.l2a?p.l2a.toFixed(0)+'%':'—',p.a2s?p.a2s.toFixed(0)+'%':'—',p.ctr?p.ctr.toFixed(2)+'%':'—',
  ]);
  return e('div',{className:'chart-card',style:{animationDelay:'.3s'}},
    e('div',{className:'chart-title'},'Platform Summary'),
    e('table',{className:'tbl'},
      e('thead',null,e('tr',null,...cols.map(c=>e('th',{key:c},c)))),
      e('tbody',null,...rows.map((row,i)=>e('tr',{key:i},
        ...row.map((cell,j)=>e('td',{key:j,style:{
          color:j===0?(PC[cell]||TEXT):TEXT,
          fontWeight:j===0?700:400
        }},cell))
      )))
    )
  );
}

// ── Root App ──────────────────────────────────────────────────────
function App(){
  const {totals:T,platforms,daily,period}=DATA;
  const days=[...new Set(daily.map(r=>r.date))].length;
  const ICONS=['💷','📋','📅','✅','🎯','📈'];
  const IBGS=[AMBERBG,PCbg.Google,PCbg.Meta,PCbg.Bing,AMBERBG,PCbg.Google];
  const kpis=[
    {label:'Total Spend',  value:T.spend,   prefix:'£',accent:AMBER,  icon:'💷', ibg:AMBERBG,   delay:0},
    {label:'Paid Leads',   value:T.leads,   sub:'from '+fmtN(T.clicks)+' clicks',icon:'📋',ibg:PCbg.Google,delay:60},
    {label:'Appointments', value:T.appts,   sub:T.leads>0?(T.appts/T.leads*100).toFixed(0)+'% of leads':'—',icon:'📅',ibg:PCbg.Meta,delay:120},
    {label:'Sales',        value:T.sales,   sub:T.appts>0?(T.sales/T.appts*100).toFixed(0)+'% of appts':'—',accent:AMBER,icon:'✅',ibg:AMBERBG,delay:180},
    {label:'Blended CPL',  value:Math.round(T.cpl),prefix:'£',accent:PC.Google,icon:'🎯',ibg:PCbg.Google,delay:240},
    {label:'Blended CPS',  value:T.cps>0?Math.round(T.cps):'—',prefix:T.cps>0?'£':'',accent:PC.Bing,icon:'📈',ibg:PCbg.Bing,delay:300},
  ];

  return e('div',null,
    // Header
    e('div',{className:'hdr'},
      e('div',{className:'hdr-eye'},'Trust Electric Heating · Paid Media Intelligence'),
      e('div',{className:'hdr-title'},'Ad Performance ',e('em',null,'& Attribution')),
      e('div',{className:'hdr-rule'}),
      e('div',{className:'hdr-meta'},
        e('span',null,'PERIOD: '+period.toUpperCase()),
        e('span',{style:{color:'rgba(0,0,0,0.15)'}},'│'),
        e('span',null,days+' DAYS'),
        ...Object.entries(PC).map(([name,color])=>e('span',{key:name,className:'badge',style:{
          background:PCbg[name]||AMBERBG, border:'1.5px solid '+color+'33', color
        }},name))
      )
    ),

    // KPIs
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Summary'),
      e('div',{className:'g6'},...kpis.map((k,i)=>e(KpiCard,{key:i,...k})))
    ),

    e('div',{className:'div'}),

    // Platform cards
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Platform Breakdown'),
      e('div',{className:'g3'},...platforms.map((p,i)=>e(PlatformCard,{key:p.platform,p,totalSpend:T.spend,delay:i*80})))
    ),

    e('div',{className:'div'}),

    // Donut + Area chart
    e('div',{className:'g21 sec'},
      e(Donut,{platforms,total:T.spend}),
      e(AreaChart,{daily})
    ),

    e('div',{className:'div'}),

    // Funnels
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Lead Funnel by Platform'),
      e('div',{className:'g3'},...platforms.map((p,i)=>e(FunnelCard,{key:p.platform,p,delay:i*100})))
    ),

    e('div',{className:'div'}),

    // Performance charts
    e('div',{className:'sec'},
      e('div',{className:'sec-lbl'},'Performance Trends'),
      e('div',{className:'g2'},e(CplChart,{daily}),e(LeadsChart,{daily}))
    ),

    e('div',{className:'div'}),

    // Compare bars
    e('div',{className:'g2 sec'},e(PlatformBars,{platforms}),e(CostBars,{platforms})),

    e('div',{className:'div'}),

    e('div',{className:'sec'},e(SummaryTable,{platforms})),

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
