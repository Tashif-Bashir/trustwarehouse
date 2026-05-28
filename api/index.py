"""Vercel serverless API — self-contained Flask entry point."""
import os, time, threading, json as _json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
from flask import Flask, jsonify, request

PROJECT   = os.getenv('GCP_PROJECT_ID', 'trustwarehouse')
CACHE_TTL = 1800

_bq      = None
_bq_lock = threading.Lock()

def _get_bq():
    global _bq
    if _bq is None:
        with _bq_lock:
            if _bq is None:
                creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if creds_json:
                    from google.oauth2 import service_account
                    creds = service_account.Credentials.from_service_account_info(
                        _json.loads(creds_json),
                        scopes=['https://www.googleapis.com/auth/bigquery'],
                    )
                    _bq = bigquery.Client(project=PROJECT, credentials=creds)
                else:
                    _bq = bigquery.Client(project=PROJECT)
    return _bq

def _q(sql):
    return _get_bq().query(sql).to_dataframe()

_cache      = {}
_cache_lock = threading.Lock()

def _cached(key, fn):
    with _cache_lock:
        if key in _cache:
            data, ts = _cache[key]
            if time.time() - ts < CACHE_TTL:
                return data
    data = fn()
    with _cache_lock:
        _cache[key] = (data, time.time())
    return data

def _safe(v):
    if v is None: return None
    try:
        if pd.isna(v): return None
    except (TypeError, ValueError): pass
    if hasattr(v, 'item'): return v.item()
    return v

def _attr(d0, d1):
    return _q(f"SELECT * FROM `{PROJECT}.gold.gold_campaign_attribution` WHERE date BETWEEN '{d0}' AND '{d1}' ORDER BY date DESC, spend_gbp DESC")

def _sources(d0, d1):
    return _q(f"""
        SELECT
            CASE
                WHEN la.platform IS NOT NULL THEN la.platform
                WHEN REGEXP_CONTAINS(LOWER(COALESCE(sl.marketing_url, '')), r'utm_source=sharpspring') THEN 'Email'
                WHEN REGEXP_CONTAINS(LOWER(COALESCE(sl.marketing_url, sl.form_page, '')), r'/news/|guide|/blog') THEN 'Content'
                WHEN COALESCE(sl.marketing_url, sl.form_page) IS NOT NULL THEN 'Enquiry'
                ELSE 'Direct'
            END as source,
            COUNT(DISTINCT la.lead_id) as leads,
            COUNT(DISTINCT CASE WHEN la.appointment_booked='Yes' THEN la.lead_id END) as appts,
            COUNT(DISTINCT CASE WHEN la.is_sold=true THEN la.lead_id END) as sales,
            COUNT(DISTINCT CASE WHEN la.phone IS NOT NULL THEN la.lead_id END) as callable
        FROM `{PROJECT}.gold.gold_lead_activity` la
        JOIN `{PROJECT}.silver.silver_sharpspring_leads` sl ON la.lead_id = sl.lead_id
        WHERE la.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1 ORDER BY 2 DESC
    """)

def _telesales(d0, d1):
    try:
        return _q(f"""
            SELECT agent_name,
                SUM(total_calls) as total_calls, SUM(outbound_calls) as outbound_calls,
                SUM(inbound_calls) as inbound_calls, SUM(missed_calls) as missed_calls,
                SUM(unique_leads_contacted) as unique_leads, SUM(total_talk_time_seconds) as total_talk_time,
                ROUND(AVG(avg_talk_time_seconds),0) as avg_talk_time, SUM(qualified_conversations) as qual_convos,
                SUM(appointments_booked) as appts, SUM(sales_confirmed) as sales,
                ROUND(SUM(COALESCE(total_deal_value,0)),2) as deal_value
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}' AND agent_name != 'Other'
            GROUP BY agent_name ORDER BY appts DESC, outbound_calls DESC
        """)
    except Exception:
        return pd.DataFrame()

def _ts_daily(d0, d1):
    try:
        return _q(f"""
            SELECT date, SUM(total_calls) as calls, SUM(outbound_calls) as outbound,
                   SUM(appointments_booked) as appts, SUM(sales_confirmed) as sales
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}' AND agent_name != 'Other'
            GROUP BY date ORDER BY date
        """)
    except Exception:
        return pd.DataFrame()

def _regional_leads(d0, d1):
    return _q(f"""
        SELECT region, SUM(leads) as leads
        FROM `{PROJECT}.gold.gold_leads_by_region`
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
          AND region != 'Unknown'
        GROUP BY region ORDER BY leads DESC LIMIT 12
    """)

def _regional_spend(d0, d1):
    return _q(f"""
        SELECT region, ROUND(SUM(spend_gbp),2) as spend_gbp
        FROM `{PROJECT}.gold.gold_google_ads_spend_by_region`
        WHERE date BETWEEN '{d0}' AND '{d1}'
          AND region != 'National'
        GROUP BY region ORDER BY spend_gbp DESC
    """)

def _pipeline():
    try:
        stages = _q(f"""
            SELECT COALESCE(deal_stage_name,'Unknown') as stage, COUNT(*) as count,
                ROUND(SUM(COALESCE(deal_amount,0)),2) as total_value,
                ROUND(SUM(COALESCE(weighted_amount,0)),2) as weighted_value,
                COUNTIF(is_won) as won_count,
                ROUND(SUM(CASE WHEN is_won THEN COALESCE(deal_amount,0) ELSE 0 END),2) as won_value,
                ROUND(AVG(DATE_DIFF(CURRENT_DATE(),DATE(created_date),DAY)),0) as avg_age_days
            FROM `{PROJECT}.gold.gold_pipeline_opportunities` GROUP BY 1 ORDER BY total_value DESC
        """)
        recent = _q(f"""
            SELECT COALESCE(opportunity_name,'Unnamed') as name, COALESCE(deal_stage_name,'Unknown') as stage,
                COALESCE(deal_amount,0) as amount, COALESCE(probability,0) as probability,
                COALESCE(is_won,false) as is_won, COALESCE(is_closed,false) as is_closed,
                created_date, COALESCE(first_name,'') as first_name, COALESCE(last_name,'') as last_name,
                COALESCE(sector,'') as sector, COALESCE(customer_type,'') as customer_type
            FROM `{PROJECT}.gold.gold_pipeline_opportunities`
            WHERE NOT COALESCE(is_closed,false) ORDER BY created_date DESC LIMIT 10
        """)
        return stages, recent
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

def _prev_period(d0s, d1s):
    d0_dt = date.fromisoformat(d0s)
    d1_dt = date.fromisoformat(d1s)
    length = (d1_dt - d0_dt).days + 1
    prev_d1 = d0_dt - timedelta(days=1)
    prev_d0 = prev_d1 - timedelta(days=length - 1)
    return prev_d0.isoformat(), prev_d1.isoformat()

def _load_all(d0s, d1s):
    p0s, p1s = _prev_period(d0s, d1s)

    tasks = {
        'attr':       (f'attr:{d0s}:{d1s}',  lambda: _attr(d0s, d1s)),
        'attr_prev':  (f'attr:{p0s}:{p1s}',  lambda: _attr(p0s, p1s)),
        'src':        (f'src:{d0s}:{d1s}',   lambda: _sources(d0s, d1s)),
        'src_prev':   (f'src:{p0s}:{p1s}',   lambda: _sources(p0s, p1s)),
        'ts':         (f'ts:{d0s}:{d1s}',    lambda: _telesales(d0s, d1s)),
        'ts_prev':    (f'ts:{p0s}:{p1s}',    lambda: _telesales(p0s, p1s)),
        'ts_day':     (f'tsd:{d0s}:{d1s}',   lambda: _ts_daily(d0s, d1s)),
        'pipeline':   ('pipeline',            _pipeline),
        'reg_leads':  (f'regl:{d0s}:{d1s}',  lambda: _regional_leads(d0s, d1s)),
        'reg_spend':  (f'regs:{d0s}:{d1s}',  lambda: _regional_spend(d0s, d1s)),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_cached, key, fn): name for name, (key, fn) in tasks.items()}
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    df_attr      = results['attr']
    df_attr_prev = results['attr_prev']
    df_src       = results['src']
    df_src_prev  = results['src_prev']
    df_ts        = results['ts']
    df_ts_prev   = results['ts_prev']
    df_ts_day    = results['ts_day']
    df_stg, df_rec   = results['pipeline']
    df_reg_leads     = results['reg_leads']
    df_reg_spend     = results['reg_spend']

    pa = df_attr.groupby("platform").agg(spend=("spend_gbp","sum"),clicks=("clicks","sum"),impr=("impressions","sum"),leads=("leads","sum")).reset_index()
    pa["cpl"] = (pa["spend"] / pa["leads"].replace(0, float("nan"))).round(2)
    pa["ctr"] = (pa["clicks"] / pa["impr"].replace(0, float("nan")) * 100).round(3)
    tot_sp = float(pa["spend"].sum()); tot_ld = int(pa["leads"].sum()); tot_cl = int(pa["clicks"].sum())

    prev_marketing_totals = None
    if not df_attr_prev.empty:
        pp = df_attr_prev.groupby("platform").agg(spend=("spend_gbp","sum"),leads=("leads","sum")).reset_index()
        p_sp = float(pp["spend"].sum()); p_ld = int(pp["leads"].sum())
        p_all = int(df_src_prev['leads'].sum()) if not df_src_prev.empty else 0
        prev_marketing_totals = {"spend": p_sp, "leads": p_ld, "cpl": round(p_sp/p_ld,2) if p_ld else 0, "total_leads": p_all}

    platforms = [{'platform':str(r['platform']),'spend':float(r['spend']),'leads':int(r['leads']),'clicks':int(r['clicks']),'cpl':_safe(r['cpl']),'ctr':_safe(r['ctr'])} for _,r in pa.iterrows()]
    daily     = [{'date':str(r['date']),'platform':str(r['platform']),'spend':_safe(float(r['spend_gbp'])),'leads':int(r['leads']) if pd.notna(r['leads']) else 0} for _,r in df_attr.iterrows()]
    sources   = [{'source':str(r['source']),'leads':int(r['leads']),'appts':int(r['appts']),'sales':int(r['sales']),'callable':int(r['callable']) if pd.notna(r.get('callable')) else 0} for _,r in df_src.iterrows()]
    tot_all   = int(df_src['leads'].sum()) if not df_src.empty else 0
    spend_map = {str(r['region']): float(r['spend_gbp']) for _, r in df_reg_spend.iterrows()} if not df_reg_spend.empty else {}
    regions = []
    seen = set()
    for _, r in df_reg_leads.iterrows():
        reg = str(r['region']); leads_n = int(r['leads']); sp = spend_map.get(reg, 0); seen.add(reg)
        regions.append({'region': reg, 'leads': leads_n, 'spend_gbp': sp, 'cpl': round(sp / leads_n, 2) if leads_n > 0 and sp > 0 else None})
    for reg, sp in spend_map.items():
        if reg not in seen:
            regions.append({'region': reg, 'leads': 0, 'spend_gbp': sp, 'cpl': None})
    regions.sort(key=lambda x: x['leads'], reverse=True)

    marketing = {'totals':{'spend':tot_sp,'leads':tot_ld,'clicks':tot_cl,'cpl':round(tot_sp/tot_ld,2) if tot_ld else 0,'total_leads':tot_all},'prev_totals':prev_marketing_totals,'platforms':platforms,'daily':daily,'lead_sources':sources,'regions':regions}

    agents = []
    if not df_ts.empty:
        for _, r in df_ts.iterrows():
            outb  = int(r['outbound_calls']) if pd.notna(r['outbound_calls']) else 0
            appts = int(r['appts'])          if pd.notna(r['appts'])          else 0
            sales = int(r['sales'])          if pd.notna(r['sales'])          else 0
            agents.append({'name':str(r['agent_name']),'total_calls':int(r['total_calls']) if pd.notna(r['total_calls']) else 0,'outbound':outb,'inbound':int(r['inbound_calls']) if pd.notna(r['inbound_calls']) else 0,'missed':int(r['missed_calls']) if pd.notna(r['missed_calls']) else 0,'unique_leads':int(r['unique_leads']) if pd.notna(r['unique_leads']) else 0,'avg_talk':int(r['avg_talk_time']) if pd.notna(r['avg_talk_time']) else 0,'qual_convos':int(r['qual_convos']) if pd.notna(r['qual_convos']) else 0,'appts':appts,'sales':sales,'deal_value':float(r['deal_value']) if pd.notna(r['deal_value']) else 0,'on_target':(outb/appts<=3) if appts>0 else False,'calls_per_appt':round(outb/appts,1) if appts>0 else None})

    ts_out = sum(a['outbound'] for a in agents); ts_ap = sum(a['appts'] for a in agents)
    ts_sa  = sum(a['sales'] for a in agents);   ts_on = sum(1 for a in agents if a['on_target'])
    ts_daily_list = [{'date':str(r['date']),'calls':int(r['calls']) if pd.notna(r['calls']) else 0,'outbound':int(r['outbound']) if pd.notna(r['outbound']) else 0,'appts':int(r['appts']) if pd.notna(r['appts']) else 0,'sales':int(r['sales']) if pd.notna(r['sales']) else 0} for _,r in df_ts_day.iterrows()]
    prev_telesales_totals = None
    if not df_ts_prev.empty:
        prev_telesales_totals = {'outbound':int(df_ts_prev['outbound_calls'].sum()),'appts':int(df_ts_prev['appts'].sum()),'sales':int(df_ts_prev['sales'].sum()),'on_target_count':int((df_ts_prev['appts']>0).sum())}
    telesales = {'agents':agents,'daily':ts_daily_list,'totals':{'outbound':ts_out,'appts':ts_ap,'sales':ts_sa,'on_target_count':ts_on,'on_target_pct':round(ts_on/len(agents)*100) if agents else 0,'l2a':round(ts_ap/ts_out*100,1) if ts_out else 0,'a2s':round(ts_sa/ts_ap*100,1) if ts_ap else 0},'prev_totals':prev_telesales_totals}

    stages = [{'stage':str(r['stage']),'count':int(r['count']),'total_value':float(r['total_value']) if pd.notna(r['total_value']) else 0,'weighted_value':float(r['weighted_value']) if pd.notna(r['weighted_value']) else 0,'won_count':int(r['won_count']) if pd.notna(r['won_count']) else 0,'won_value':float(r['won_value']) if pd.notna(r['won_value']) else 0,'avg_age_days':int(r['avg_age_days']) if pd.notna(r.get('avg_age_days')) else None} for _,r in df_stg.iterrows()]
    recent = []
    for _, r in df_rec.iterrows():
        contact = (str(r['first_name'])+' '+str(r['last_name'])).strip() or '—'
        recent.append({'name':str(r['name']),'contact':contact,'stage':str(r['stage']),'amount':float(r['amount']) if pd.notna(r['amount']) else 0,'probability':int(r['probability']) if pd.notna(r['probability']) else 0,'is_won':bool(r['is_won']),'is_closed':bool(r['is_closed']),'created_date':str(r['created_date']) if pd.notna(r['created_date']) else '','sector':str(r['sector']) if pd.notna(r['sector']) else '','customer_type':str(r['customer_type']) if pd.notna(r['customer_type']) else ''})
    sales_count=sum(s['count'] for s in stages); sales_won=sum(s['won_count'] for s in stages)
    sales_pipe=sum(s['total_value'] for s in stages); sales_weight=sum(s['weighted_value'] for s in stages); sales_won_v=sum(s['won_value'] for s in stages)
    sales = {'stages':stages,'recent':recent,'win_rate_by_stage':[],'totals':{'count':sales_count,'won':sales_won,'pipeline_value':sales_pipe,'weighted_value':sales_weight,'won_value':sales_won_v},'prev_totals':None}

    period = f"{date.fromisoformat(d0s).strftime('%d %b')} – {date.fromisoformat(d1s).strftime('%d %b %Y')}"
    return {'period':period,'refreshed_at':datetime.now(timezone.utc).isoformat(),'marketing':marketing,'telesales':telesales,'sales':sales}


app = Flask(__name__)

_html_cache = None
_html_lock  = threading.Lock()

def _get_html():
    global _html_cache
    if _html_cache is None:
        with _html_lock:
            if _html_cache is None:
                here = os.path.dirname(os.path.abspath(__file__))
                for path in [
                    os.path.join(here, '..', 'public', 'index.html'),
                    os.path.join(here, '..', 'index.html'),
                ]:
                    if os.path.exists(path):
                        with open(path, 'rb') as f:
                            _html_cache = f.read()
                        break
    return _html_cache

@app.route('/api/data')
def get_data():
    d0 = request.args.get('d0')
    d1 = request.args.get('d1')
    if not d0 or not d1:
        d1 = (date.today() - timedelta(1)).strftime('%Y-%m-%d')
        d0 = (date.today() - timedelta(7)).strftime('%Y-%m-%d')
    try:
        return jsonify(_load_all(d0, d1))
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500

@app.route('/api/refresh')
def refresh():
    return jsonify({'ok': True})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    from flask import Response
    html = _get_html()
    if html is None:
        return 'Dashboard unavailable', 404
    return Response(html, mimetype='text/html')
