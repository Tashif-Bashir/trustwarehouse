"""BigQuery data loading for the analytics dashboard."""
import os, time, threading
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

PROJECT   = os.getenv('GCP_PROJECT_ID', 'trustwarehouse')
CACHE_TTL = 1800  # 30 min

# ── BigQuery client ────────────────────────────────────────────────────────────
_bq      = None
_bq_lock = threading.Lock()

def bq():
    global _bq
    if _bq is None:
        with _bq_lock:
            if _bq is None:
                creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if creds_json:
                    import json as _json
                    from google.oauth2 import service_account
                    creds = service_account.Credentials.from_service_account_info(
                        _json.loads(creds_json),
                        scopes=['https://www.googleapis.com/auth/bigquery'],
                    )
                    _bq = bigquery.Client(project=PROJECT, credentials=creds)
                else:
                    _bq = bigquery.Client(project=PROJECT)
    return _bq

def q(sql):
    return bq().query(sql).to_dataframe()

# ── Cache ──────────────────────────────────────────────────────────────────────
_cache      = {}
_cache_lock = threading.Lock()

def cached(key, fn):
    with _cache_lock:
        if key in _cache:
            data, ts = _cache[key]
            if time.time() - ts < CACHE_TTL:
                return data
    data = fn()
    with _cache_lock:
        _cache[key] = (data, time.time())
    return data

# ── Data helpers ───────────────────────────────────────────────────────────────
def safe(v):
    if v is None: return None
    try:
        if pd.isna(v): return None
    except (TypeError, ValueError): pass
    if hasattr(v, 'item'): return v.item()
    return v

# ── Queries ────────────────────────────────────────────────────────────────────
def _attr(d0, d1):
    return q(f"""
        SELECT * FROM `{PROJECT}.gold.gold_campaign_attribution`
        WHERE date BETWEEN '{d0}' AND '{d1}'
        ORDER BY date DESC, spend_gbp DESC
    """)

def _sources(d0, d1):
    return q(f"""
        SELECT
            COALESCE(platform, 'Organic')               as source,
            COUNT(DISTINCT lead_id)                     as leads,
            -- is_booked_appointment counts real (non-cancelled) appointments via
            -- Domestic Lead Status; the old appointment_booked='Yes' never
            -- subtracted cancellations (audit 20 Aug 2026: +9 phantom in 15 days).
            COUNT(DISTINCT CASE WHEN is_booked_appointment THEN lead_id END) as appts,
            COUNT(DISTINCT CASE WHEN is_sold = true THEN lead_id END)             as sales
        FROM `{PROJECT}.gold.gold_lead_activity`
        WHERE created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1 ORDER BY 2 DESC
    """)

def _telesales(d0, d1):
    try:
        return q(f"""
            SELECT
                agent_name,
                SUM(total_calls)             as total_calls,
                SUM(outbound_calls)          as outbound_calls,
                SUM(inbound_calls)           as inbound_calls,
                SUM(missed_calls)            as missed_calls,
                SUM(unique_leads_contacted)  as unique_leads,
                SUM(total_talk_time_seconds) as total_talk_time,
                ROUND(AVG(avg_talk_time_seconds), 0) as avg_talk_time,
                SUM(qualified_conversations) as qual_convos,
                SUM(appointments_booked)     as appts,
                SUM(sales_confirmed)         as sales,
                ROUND(SUM(COALESCE(total_deal_value, 0)), 2) as deal_value
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}'
              AND agent_name != 'Other'
            GROUP BY agent_name
            ORDER BY appts DESC, outbound_calls DESC
        """)
    except Exception:
        return pd.DataFrame()

def _ts_daily(d0, d1):
    try:
        return q(f"""
            SELECT
                date,
                SUM(total_calls)         as calls,
                SUM(outbound_calls)      as outbound,
                SUM(appointments_booked) as appts,
                SUM(sales_confirmed)     as sales
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}'
              AND agent_name != 'Other'
            GROUP BY date ORDER BY date
        """)
    except Exception:
        return pd.DataFrame()

def _pipeline():
    try:
        stages = q(f"""
            SELECT
                COALESCE(deal_stage_name,'Unknown')       as stage,
                COUNT(*)                                  as count,
                ROUND(SUM(COALESCE(deal_amount,0)),2)     as total_value,
                ROUND(SUM(COALESCE(weighted_amount,0)),2) as weighted_value,
                COUNTIF(is_won)                           as won_count,
                ROUND(SUM(CASE WHEN is_won THEN COALESCE(deal_amount,0) ELSE 0 END),2) as won_value,
                ROUND(AVG(DATE_DIFF(CURRENT_DATE(), DATE(created_date), DAY)), 0) as avg_age_days
            FROM `{PROJECT}.gold.gold_pipeline_opportunities`
            GROUP BY 1 ORDER BY total_value DESC
        """)
        recent = q(f"""
            SELECT
                COALESCE(opportunity_name,'Unnamed')  as name,
                COALESCE(deal_stage_name,'Unknown')   as stage,
                COALESCE(deal_amount,0)               as amount,
                COALESCE(probability,0)               as probability,
                COALESCE(is_won,false)                as is_won,
                COALESCE(is_closed,false)             as is_closed,
                created_date,
                COALESCE(first_name,'')               as first_name,
                COALESCE(last_name,'')                as last_name,
                COALESCE(sector,'')                   as sector,
                COALESCE(customer_type,'')            as customer_type
            FROM `{PROJECT}.gold.gold_pipeline_opportunities`
            WHERE NOT COALESCE(is_closed,false)
            ORDER BY created_date DESC LIMIT 10
        """)
        return stages, recent
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

def _prev_period(d0s: str, d1s: str) -> tuple[str, str]:
    d0_dt = date.fromisoformat(d0s)
    d1_dt = date.fromisoformat(d1s)
    length = (d1_dt - d0_dt).days + 1
    prev_d1 = d0_dt - timedelta(days=1)
    prev_d0 = prev_d1 - timedelta(days=length - 1)
    return prev_d0.isoformat(), prev_d1.isoformat()


# ── Build response payload ─────────────────────────────────────────────────────
def load_all_data(d0s: str, d1s: str) -> dict:
    p0s, p1s = _prev_period(d0s, d1s)

    df_attr         = cached(f'attr:{d0s}:{d1s}',  lambda: _attr(d0s, d1s))
    df_attr_prev    = cached(f'attr:{p0s}:{p1s}',  lambda: _attr(p0s, p1s))
    df_src          = cached(f'src:{d0s}:{d1s}',   lambda: _sources(d0s, d1s))
    df_ts           = cached(f'ts:{d0s}:{d1s}',    lambda: _telesales(d0s, d1s))
    df_ts_prev      = cached(f'ts:{p0s}:{p1s}',    lambda: _telesales(p0s, p1s))
    df_ts_day       = cached(f'tsd:{d0s}:{d1s}',   lambda: _ts_daily(d0s, d1s))
    df_stg, df_rec  = cached('pipeline', _pipeline)

    # ── Marketing ─────────────────────────────────────────────────────────────
    pa = df_attr.groupby("platform").agg(
        spend=("spend_gbp","sum"), clicks=("clicks","sum"), impr=("impressions","sum"),
        leads=("leads","sum"),
    ).reset_index()
    pa["cpl"] = (pa["spend"] / pa["leads"].replace(0, float("nan"))).round(2)
    pa["ctr"] = (pa["clicks"] / pa["impr"].replace(0, float("nan")) * 100).round(3)

    tot_sp = float(pa["spend"].sum())
    tot_ld = int(pa["leads"].sum())
    tot_cl = int(pa["clicks"].sum())

    # ── Marketing prev-period totals ──────────────────────────────────────────
    if not df_attr_prev.empty:
        pp = df_attr_prev.groupby("platform").agg(
            spend=("spend_gbp","sum"), leads=("leads","sum"),
        ).reset_index()
        p_sp = float(pp["spend"].sum())
        p_ld = int(pp["leads"].sum())
        prev_marketing_totals = {
            "spend": p_sp, "leads": p_ld,
            "cpl": round(p_sp / p_ld, 2) if p_ld else 0,
        }
    else:
        prev_marketing_totals = None

    platforms = [
        {'platform': str(r['platform']),  'spend': float(r['spend']),
         'leads': int(r['leads']),         'clicks': int(r['clicks']),
         'cpl': safe(r['cpl']),            'ctr': safe(r['ctr'])}
        for _, r in pa.iterrows()
    ]
    daily = [
        {'date': str(r['date']),          'platform': str(r['platform']),
         'spend': safe(float(r['spend_gbp'])),
         'leads': int(r['leads'])               if pd.notna(r['leads'])               else 0}
        for _, r in df_attr.iterrows()
    ]
    sources = [
        {'source': str(r['source']), 'leads': int(r['leads']),
         'appts': int(r['appts']),   'sales': int(r['sales'])}
        for _, r in df_src.iterrows()
    ]
    tot_all  = int(df_src['leads'].sum()) if not df_src.empty else 0
    marketing = {
        'totals': {
            'spend': tot_sp, 'leads': tot_ld,
            'clicks': tot_cl,
            'cpl': round(tot_sp/tot_ld, 2) if tot_ld else 0,
            'total_leads': tot_all,
        },
        'prev_totals': prev_marketing_totals,
        'platforms': platforms, 'daily': daily, 'lead_sources': sources,
    }

    # ── Telesales ──────────────────────────────────────────────────────────────
    agents = []
    if not df_ts.empty:
        for _, r in df_ts.iterrows():
            outb  = int(r['outbound_calls']) if pd.notna(r['outbound_calls']) else 0
            appts = int(r['appts'])          if pd.notna(r['appts'])          else 0
            sales = int(r['sales'])          if pd.notna(r['sales'])          else 0
            agents.append({
                'name':           str(r['agent_name']),
                'total_calls':    int(r['total_calls'])    if pd.notna(r['total_calls'])    else 0,
                'outbound':       outb,
                'inbound':        int(r['inbound_calls'])  if pd.notna(r['inbound_calls'])  else 0,
                'missed':         int(r['missed_calls'])   if pd.notna(r['missed_calls'])   else 0,
                'unique_leads':   int(r['unique_leads'])   if pd.notna(r['unique_leads'])   else 0,
                'avg_talk':       int(r['avg_talk_time'])  if pd.notna(r['avg_talk_time'])  else 0,
                'qual_convos':    int(r['qual_convos'])    if pd.notna(r['qual_convos'])    else 0,
                'appts':          appts,
                'sales':          sales,
                'deal_value':     float(r['deal_value'])   if pd.notna(r['deal_value'])     else 0,
                'on_target':      (outb/appts <= 3)        if appts > 0                     else False,
                'calls_per_appt': round(outb/appts, 1)    if appts > 0                     else None,
            })

    ts_out = sum(a['outbound'] for a in agents)
    ts_ap  = sum(a['appts']    for a in agents)
    ts_sa  = sum(a['sales']    for a in agents)
    ts_on  = sum(1 for a in agents if a['on_target'])
    ts_daily = [
        {'date':    str(r['date']),
         'calls':   int(r['calls'])    if pd.notna(r['calls'])    else 0,
         'outbound':int(r['outbound']) if pd.notna(r['outbound']) else 0,
         'appts':   int(r['appts'])    if pd.notna(r['appts'])    else 0,
         'sales':   int(r['sales'])    if pd.notna(r['sales'])    else 0}
        for _, r in df_ts_day.iterrows()
    ]
    # ── Telesales prev-period totals ──────────────────────────────────────────
    if not df_ts_prev.empty:
        p_out = int(df_ts_prev['outbound_calls'].sum())
        p_ap  = int(df_ts_prev['appts'].sum())
        p_sa  = int(df_ts_prev['sales'].sum())
        p_on  = int((df_ts_prev['appts'] > 0).sum())
        prev_telesales_totals = {
            'outbound': p_out, 'appts': p_ap, 'sales': p_sa, 'on_target_count': p_on,
        }
    else:
        prev_telesales_totals = None

    telesales = {
        'agents': agents,
        'daily':  ts_daily,
        'totals': {
            'outbound':        ts_out,
            'appts':           ts_ap,
            'sales':           ts_sa,
            'on_target_count': ts_on,
            'on_target_pct':   round(ts_on/len(agents)*100) if agents else 0,
            'l2a': round(ts_ap/ts_out*100, 1) if ts_out else 0,
            'a2s': round(ts_sa/ts_ap*100, 1)  if ts_ap  else 0,
        },
        'prev_totals': prev_telesales_totals,
    }

    # ── Sales ──────────────────────────────────────────────────────────────────
    stages = [
        {'stage':          str(r['stage']),
         'count':          int(r['count']),
         'total_value':    float(r['total_value'])    if pd.notna(r['total_value'])    else 0,
         'weighted_value': float(r['weighted_value']) if pd.notna(r['weighted_value']) else 0,
         'won_count':      int(r['won_count'])        if pd.notna(r['won_count'])      else 0,
         'won_value':      float(r['won_value'])      if pd.notna(r['won_value'])      else 0,
         'avg_age_days':   int(r['avg_age_days'])     if pd.notna(r.get('avg_age_days')) else None}
        for _, r in df_stg.iterrows()
    ]
    recent = []
    for _, r in df_rec.iterrows():
        contact = (str(r['first_name'])+' '+str(r['last_name'])).strip() or '—'
        recent.append({
            'name':          str(r['name']),
            'contact':       contact,
            'stage':         str(r['stage']),
            'amount':        float(r['amount'])      if pd.notna(r['amount'])      else 0,
            'probability':   int(r['probability'])   if pd.notna(r['probability']) else 0,
            'is_won':        bool(r['is_won']),
            'is_closed':     bool(r['is_closed']),
            'created_date':  str(r['created_date'])  if pd.notna(r['created_date']) else '',
            'sector':        str(r['sector'])         if pd.notna(r['sector'])        else '',
            'customer_type': str(r['customer_type']) if pd.notna(r['customer_type']) else '',
        })
    sales_count  = sum(s['count']          for s in stages)
    sales_won    = sum(s['won_count']      for s in stages)
    sales_pipe   = sum(s['total_value']    for s in stages)
    sales_weight = sum(s['weighted_value'] for s in stages)
    sales_won_v  = sum(s['won_value']      for s in stages)
    sales = {
        'stages': stages, 'recent': recent,
        'win_rate_by_stage': [],  # populated when stage-history data is available
        'totals': {
            'count':          sales_count,
            'won':            sales_won,
            'pipeline_value': sales_pipe,
            'weighted_value': sales_weight,
            'won_value':      sales_won_v,
        },
        'prev_totals': None,  # pipeline is not period-filtered; prev delta not applicable
    }

    d0_dt = date.fromisoformat(d0s)
    d1_dt = date.fromisoformat(d1s)
    period = f"{d0_dt.strftime('%d %b')} – {d1_dt.strftime('%d %b %Y')}"
    refreshed_at = datetime.now(timezone.utc).isoformat()
    return {
        'period': period, 'refreshed_at': refreshed_at,
        'marketing': marketing, 'telesales': telesales, 'sales': sales,
    }
