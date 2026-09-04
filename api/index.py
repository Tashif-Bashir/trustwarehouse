"""Vercel serverless API — self-contained Flask entry point."""
import os, time, secrets, threading, json as _json
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
from flask import Flask, jsonify, request, redirect, session, Response
from werkzeug.security import check_password_hash

PROJECT   = os.getenv('GCP_PROJECT_ID', 'trustwarehouse')
# Dashboard is now live — VM-side cron syncs every 60-90s and busts this cache
# via /api/refresh after each rebuild. Keep TTL low so the frontend poll picks up
# fresh numbers within the next poll cycle. 60s is a safe ceiling if the cache
# bust ever fails (e.g. Vercel cold start).
CACHE_TTL = 60

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
            -- is_booked_appointment excludes cancellations (audit 20 Aug 2026:
            -- appointment_booked='Yes' never subtracts them; +9 phantom / 15 days)
            COUNT(DISTINCT CASE WHEN la.is_booked_appointment THEN la.lead_id END) as appts,
            COUNT(DISTINCT CASE WHEN la.is_sold=true THEN la.lead_id END) as sales,
            -- Quality funnel (owner ruling 20 Aug 2026): junk = the team's two
            -- CRM verdicts — 'No Number' (number is fake/dead; a filled phone
            -- field proves nothing, 39/39 "callable" day) and 'Not a Lead'.
            -- Workable = leads minus junk; outcomes like Not Interested still
            -- count as workable (real reachable people = what marketing paid for).
            COUNT(DISTINCT CASE WHEN sl.domestic_appointment_status = 'No Number' THEN la.lead_id END) as no_number,
            COUNT(DISTINCT CASE WHEN sl.domestic_appointment_status = 'Not a Lead' THEN la.lead_id END) as not_a_lead
        FROM `{PROJECT}.gold.gold_lead_activity` la
        JOIN `{PROJECT}.silver.silver_sharpspring_leads` sl ON la.lead_id = sl.lead_id
        WHERE la.created_date BETWEEN '{d0}' AND '{d1}'
        GROUP BY 1 ORDER BY 2 DESC
    """)

def _source_cpa(d0, d1):
    """Cost per appointment by lead source.
    Joins paid spend (gold_campaign_attribution) with appointments per platform
    from gold_lead_calls. Only paid platforms have spend, so only paid lead-platforms
    show a meaningful CPA."""
    try:
        return _q(f"""
            WITH source_appts AS (
              -- Cohort basis: leads CREATED in the period, real (non-cancelled)
              -- appointments only — aligns the CPA denominator with the spend
              -- period and stops counting cancelled appointments (20 Aug 2026;
              -- previously counted leads merely CALLED in the period via
              -- gold_lead_calls, with the never-cancelled appointment flag).
              SELECT platform,
                     COUNT(DISTINCT IF(is_booked_appointment, lead_id, NULL)) AS appts
              FROM `{PROJECT}.gold.gold_lead_activity`
              WHERE created_date BETWEEN '{d0}' AND '{d1}'
                AND platform IS NOT NULL
              GROUP BY platform
            ),
            source_spend AS (
              SELECT platform, ROUND(SUM(spend_gbp), 2) AS spend
              FROM `{PROJECT}.gold.gold_campaign_attribution`
              WHERE date BETWEEN '{d0}' AND '{d1}'
              GROUP BY platform
            )
            SELECT s.platform,
                   s.spend,
                   COALESCE(a.appts, 0) AS appts,
                   ROUND(SAFE_DIVIDE(s.spend, a.appts), 2) AS cost_per_appt_gbp
            FROM source_spend s
            LEFT JOIN source_appts a USING(platform)
            ORDER BY s.spend DESC
        """)
    except Exception:
        return pd.DataFrame()

def _qc_flags(d0, d1):
    """Count of attribution data-quality flags from gold_lead_activity for the period.
    Returns one row per qc_flag category."""
    try:
        return _q(f"""
            SELECT
                qc_flag,
                COUNT(*) AS leads
            FROM `{PROJECT}.gold.gold_lead_activity`
            WHERE created_date BETWEEN '{d0}' AND '{d1}'
              AND qc_flag IS NOT NULL
            GROUP BY qc_flag
        """)
    except Exception:
        return pd.DataFrame()

def _qc_lead_details(d0, d1):
    """Per-lead drill-down for the qc card — only flagged leads."""
    try:
        return _q(f"""
            SELECT
                lead_id, first_name, last_name, campaign_id,
                crm_platform, utm_platform, platform, qc_flag, created_date
            FROM `{PROJECT}.gold.gold_lead_activity`
            WHERE created_date BETWEEN '{d0}' AND '{d1}'
              AND qc_flag IN ('crm_no_utm','utm_only','disagree')
            ORDER BY created_date DESC, qc_flag
            LIMIT 50
        """)
    except Exception:
        return pd.DataFrame()

def _water_leads(d0, d1):
    try:
        return _q(f"""
            SELECT
                service_type,
                COUNT(*) as leads,
                COUNTIF(is_sold) as sales
            FROM `{PROJECT}.silver.silver_sharpspring_leads`
            WHERE is_active = true
              AND is_water_lead = true
              AND DATE(created_at, 'Europe/London') BETWEEN '{d0}' AND '{d1}'
            GROUP BY service_type
            ORDER BY leads DESC
        """)
    except Exception:
        return pd.DataFrame()

def _duration_sweet_spot(d0, d1):
    """Talk-time buckets vs honest appt-within-24h rate.
    Source: gold_lead_calls outbound. Answers 'how long should a productive call be?'"""
    try:
        return _q(f"""
            WITH bucketed AS (
              SELECT
                CASE
                  WHEN talk_time_seconds <  30  THEN '<30s'
                  WHEN talk_time_seconds <  60  THEN '30-60s'
                  WHEN talk_time_seconds < 120  THEN '1-2 min'
                  WHEN talk_time_seconds < 300  THEN '2-5 min'
                  WHEN talk_time_seconds < 600  THEN '5-10 min'
                  ELSE '10 min+'
                END AS bucket,
                CASE
                  WHEN talk_time_seconds <  30  THEN 1
                  WHEN talk_time_seconds <  60  THEN 2
                  WHEN talk_time_seconds < 120  THEN 3
                  WHEN talk_time_seconds < 300  THEN 4
                  WHEN talk_time_seconds < 600  THEN 5
                  ELSE 6
                END AS sort_order,
                appt_within_24h AS is_appt
              FROM `{PROJECT}.gold.gold_lead_calls`
              WHERE call_date BETWEEN '{d0}' AND '{d1}'
                AND direction = 'OUTBOUND'
            )
            SELECT bucket, sort_order,
                   COUNT(*) AS calls,
                   COUNTIF(is_appt) AS appts,
                   ROUND(SAFE_DIVIDE(COUNTIF(is_appt), COUNT(*)) * 100, 1) AS rate
            FROM bucketed
            GROUP BY bucket, sort_order
            ORDER BY sort_order
        """)
    except Exception:
        return pd.DataFrame()

def _call_heatmap(d0, d1):
    """Best-time-to-call heatmap data — calls and honest appt-within-24h per (day, hour) cell.
    Source: gold_lead_calls outbound only, weekday hours 8-17. Returns one row per cell.
    Uses appt_within_24h (per-call) not the lead-level flag for honest per-call rates."""
    try:
        return _q(f"""
            SELECT
              call_dow_num  AS dow,        -- 1=Sun, 2=Mon, ..., 7=Sat (BigQuery convention)
              call_dow_name AS dow_name,
              call_hour     AS hour,
              COUNT(*)              AS calls,
              COUNTIF(appt_within_24h) AS appts,
              ROUND(SAFE_DIVIDE(COUNTIF(appt_within_24h), COUNT(*)) * 100, 1) AS rate
            FROM `{PROJECT}.gold.gold_lead_calls`
            WHERE call_date BETWEEN '{d0}' AND '{d1}'
              AND direction = 'OUTBOUND'
              AND call_hour BETWEEN 8 AND 17
            GROUP BY dow, dow_name, hour
            ORDER BY dow, hour
        """)
    except Exception:
        return pd.DataFrame()

def _speed_to_call(d0, d1):
    """Distribution of leads by minutes-to-first-call, plus appointment rate per bucket.
    mins_to_first_call is NULL when the first call happened on a different calendar day
    than the lead's creation date — these leads land in the 'next day+' bucket.
    Tests the CLAUDE.md "respond within 5 minutes" target directly."""
    try:
        return _q(f"""
            WITH bucketed AS (
              SELECT
                CASE
                  WHEN mins_to_first_call IS NULL                       THEN 'next day+'
                  WHEN mins_to_first_call <= 5                          THEN '≤5 min'
                  WHEN mins_to_first_call <= 15                         THEN '5-15 min'
                  WHEN mins_to_first_call <= 60                         THEN '15-60 min'
                  WHEN mins_to_first_call <= 240                        THEN '1-4 hr'
                  ELSE '>4 hr'
                END AS bucket,
                CASE
                  WHEN mins_to_first_call IS NULL                       THEN 6
                  WHEN mins_to_first_call <= 5                          THEN 1
                  WHEN mins_to_first_call <= 15                         THEN 2
                  WHEN mins_to_first_call <= 60                         THEN 3
                  WHEN mins_to_first_call <= 240                        THEN 4
                  ELSE 5
                END AS sort_order,
                is_booked_appointment AS is_appt
              FROM `{PROJECT}.gold.gold_lead_activity`
              WHERE created_date BETWEEN '{d0}' AND '{d1}'
            )
            SELECT bucket, sort_order,
                   COUNT(*) AS leads,
                   COUNTIF(is_appt) AS appts,
                   ROUND(SAFE_DIVIDE(COUNTIF(is_appt), COUNT(*)) * 100, 1) AS appt_rate
            FROM bucketed
            GROUP BY bucket, sort_order
            ORDER BY sort_order
        """)
    except Exception:
        return pd.DataFrame()

# The telesales team is exactly these four agents. Everyone else in
# gold_agent_performance_daily either books occasionally (e.g., Reilly Andrew),
# fields inbound only (e.g., Helen, Lucy), or is in a different department
# (e.g., Josh Baron, Alice Hardegon). The manager's Q2 Telesales Tracker
# spreadsheet has monthly sheets only for these four.
# Alisha left 4 Aug 2026 (kept for history); Amanda Romans + Jess Wadkin
# joined 7 Sep 2026; Peter Heaton (telesales 30 Jul-1 Sep 2026) was never
# added here — he moved to internal sales before this list was touched.
TELESALES_AGENTS = ('Lily', 'Sue', 'Alicja Aleksiuk', 'Alisha', 'Amanda Romans', 'Jess Wadkin')


def _telesales(d0, d1):
    """Per-agent telesales totals over the period.

    Two appointment metrics surfaced:
      - appts (appointments_scheduled) — how many sits the agent has booked
        that are due to happen in the period. This is the metric the telesales
        manager compares against ("how many appointments has Lily got").
      - appts_booked — booking activity in the period (legacy / fallback).
    Plus appts_sat (subset that actually happened) and appts_sold (closed).
    """
    agents_list = "', '".join(TELESALES_AGENTS)
    try:
        return _q(f"""
            SELECT agent_name,
                SUM(total_calls) as total_calls, SUM(outbound_calls) as outbound_calls,
                SUM(inbound_calls) as inbound_calls, SUM(missed_calls) as missed_calls,
                SUM(unique_leads_contacted) as unique_leads, SUM(total_talk_time_seconds) as total_talk_time,
                ROUND(AVG(avg_talk_time_seconds),0) as avg_talk_time, SUM(qualified_conversations) as qual_convos,
                SUM(appointments_scheduled) as appts,
                SUM(appointments_booked) as appts_booked,
                SUM(appointments_sat) as appts_sat,
                SUM(appointments_sold) as appts_sold,
                SUM(sales_confirmed) as sales,
                ROUND(SUM(COALESCE(total_deal_value,0)),2) as deal_value
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}' AND agent_name IN ('{agents_list}')
            GROUP BY agent_name ORDER BY appts DESC, outbound_calls DESC
        """)
    except Exception:
        return pd.DataFrame()

def _ts_daily(d0, d1):
    agents_list = "', '".join(TELESALES_AGENTS)
    try:
        return _q(f"""
            SELECT date, SUM(total_calls) as calls, SUM(outbound_calls) as outbound,
                   SUM(appointments_scheduled) as appts,
                   SUM(appointments_booked) as appts_booked,
                   SUM(appointments_sat) as appts_sat,
                   SUM(sales_confirmed) as sales
            FROM `{PROJECT}.gold.gold_agent_performance_daily`
            WHERE date BETWEEN '{d0}' AND '{d1}' AND agent_name IN ('{agents_list}')
            GROUP BY date ORDER BY date
        """)
    except Exception:
        return pd.DataFrame()


def _telesales_pre_appt(d0, d1):
    """Pre Appt = appointments with sit-date in period that were BOOKED
    before the period started. This is the manager's "carry-over from previous
    month" metric in the bottom table of the June 2026 sheet."""
    agents_list = "', '".join(TELESALES_AGENTS)
    try:
        return _q(f"""
            SELECT
              CASE
                WHEN LOWER(appointment_made_by) IN ('lily','lily harpham') THEN 'Lily'
                WHEN LOWER(appointment_made_by) IN ('sue','susan england') THEN 'Sue'
                WHEN LOWER(appointment_made_by) IN ('alicja','alicja aleksiuk') THEN 'Alicja Aleksiuk'
                WHEN LOWER(appointment_made_by) IN ('alisha','alisha moore') THEN 'Alisha'
                WHEN LOWER(appointment_made_by) IN ('amanda','amanda romans') THEN 'Amanda Romans'
                WHEN LOWER(appointment_made_by) IN ('jess','jess wadkin') THEN 'Jess Wadkin'
                ELSE appointment_made_by
              END AS agent_name,
              COUNT(*) AS pre_appt
            FROM `{PROJECT}.silver.silver_sharpspring_leads`
            WHERE appointment_booked = 'Yes'
              AND appointment_made_by IS NOT NULL
              AND appointment_date BETWEEN '{d0}' AND '{d1}'
              AND DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London') < '{d0}'
              AND LOWER(COALESCE(appointment_status, '')) NOT IN ('appointment cancelled','cancelled','cancel','appointment cancel')
            GROUP BY agent_name
            HAVING agent_name IN ('{agents_list}')
        """)
    except Exception:
        return pd.DataFrame()


def _telesales_whiteboard():
    """Mirror of the team's office whiteboard. Axes:
      Daily  = appointments BOOKED today (productivity — what each agent
               generated today, regardless of when those sits will happen).
      Weekly = appointments BOOKED this Mon-Fri week (productivity).
      Month  = appointments SCHEDULED to sit in this calendar month
               (this is what the 85/agent monthly target is measured
               against). Mixed axis is intentional — matches the office
               whiteboard one-for-one.

    Today/week union TWO sources, deduped on (lead_id, booked day):
      - CRM (silver_sharpspring_leads) — complete (captures manual and
        WhatsApp bookings) but ~30 min stale (bronze sync cadence), and
        lossy for past days: booked-at is a single overwritable field, so
        rebooks and manual edits erase earlier booking events.
      - app.bookings — the booking app's own event log, written the moment
        the booking is made and never deleted (cancels update the row).
        Live to the second, immutable, but only sees app-made bookings.
    Booking events count PERMANENTLY (owner decision 18 Jul 2026, same as
    gold_agent_performance_daily): a lead whose status later moves to
    'Appointment Cancelled' stays counted on the day it was booked."""
    from zoneinfo import ZoneInfo

    crm_case = """
              CASE
                WHEN LOWER(appointment_made_by) IN ('lily','lily harpham') THEN 'Lily'
                WHEN LOWER(appointment_made_by) IN ('sue','susan england') THEN 'Sue'
                WHEN LOWER(appointment_made_by) IN ('alicja','alicja aleksiuk') THEN 'Alicja Aleksiuk'
                WHEN LOWER(appointment_made_by) IN ('alisha','alisha moore') THEN 'Alisha'
                WHEN LOWER(appointment_made_by) IN ('amanda','amanda romans') THEN 'Amanda Romans'
                WHEN LOWER(appointment_made_by) IN ('jess','jess wadkin') THEN 'Jess Wadkin'
                ELSE appointment_made_by
              END"""

    # CRM booking events this week (row-level so we can dedupe against the
    # app log). Filter matches gold_agent_performance_daily: flag still 'Yes'
    # (covers sold leads, whose status moves on) OR a status that proves an
    # appointment existed — including 'Appointment Cancelled' so cancels
    # don't erase the booking from the day it was made.
    try:
        crm_events = _q(f"""
            SELECT lead_id,
              {crm_case} AS agent_name,
              DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London') AS booked_date
            FROM `{PROJECT}.silver.silver_sharpspring_leads`
            WHERE appointment_made_by IS NOT NULL
              AND appointment_booked_at IS NOT NULL
              AND DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London')
                  BETWEEN DATE_TRUNC(CURRENT_DATE('Europe/London'), WEEK(MONDAY))
                      AND CURRENT_DATE('Europe/London')
              AND (appointment_booked = 'Yes'
                   OR LOWER(COALESCE(domestic_appointment_status, '')) IN
                      ('appointment', 'whatsapp appointment', 'appointment cancelled'))
        """)
    except Exception:
        crm_events = pd.DataFrame()

    # Live layer: the booking app's event log (app dataset, US region — must
    # stay a separate query, cross-region joins are impossible).
    try:
        app_events = _q(f"""
            SELECT lead_id,
              CASE
                WHEN LOWER(booker_name) LIKE 'lily%'                                    THEN 'Lily'
                WHEN LOWER(booker_name) LIKE 'sue%' OR LOWER(booker_name) LIKE 'susan%' THEN 'Sue'
                WHEN LOWER(booker_name) LIKE 'alicja%'                                  THEN 'Alicja Aleksiuk'
                WHEN LOWER(booker_name) LIKE 'alisha%'                                  THEN 'Alisha'
                WHEN LOWER(booker_name) LIKE 'amanda%'                                  THEN 'Amanda Romans'
                WHEN LOWER(booker_name) LIKE 'jess%'                                    THEN 'Jess Wadkin'
                ELSE booker_name
              END AS agent_name,
              DATE(booked_at, 'Europe/London') AS booked_date
            FROM `{PROJECT}.app.bookings`
            WHERE DATE(booked_at, 'Europe/London')
                  BETWEEN DATE_TRUNC(CURRENT_DATE('Europe/London'), WEEK(MONDAY))
                      AND CURRENT_DATE('Europe/London')
              AND customer NOT LIKE 'Zzz Testlead%'
              -- unlinked (calendar-only) rows can't dedupe against the CRM and
              -- reschedules aren't new bookings — neither counts (22 Jul 2026)
              AND lead_id IS NOT NULL AND lead_id != ''
              AND COALESCE(is_rebook, FALSE) = FALSE
        """)
    except Exception:
        app_events = pd.DataFrame()

    # month: count by WHEN it sits (diary pipeline against 85/agent target).
    # Unchanged semantics: only ACTIVE sits count toward the target — a
    # cancelled sit is not a sit, so 'Appointment Cancelled' stays excluded
    # here (the manager's convention). Does NOT require appointment_booked_at —
    # some sits are booked without it being populated (e.g. Lily's 4 June sits).
    agents_list = "', '".join(TELESALES_AGENTS)
    try:
        month_df = _q(f"""
            SELECT
              {crm_case} AS agent_name,
              COUNT(*) AS month_appts
            FROM `{PROJECT}.silver.silver_sharpspring_leads`
            WHERE appointment_made_by IS NOT NULL
              AND appointment_date IS NOT NULL
              AND appointment_date BETWEEN DATE_TRUNC(CURRENT_DATE('Europe/London'), MONTH)
                  AND LAST_DAY(CURRENT_DATE('Europe/London'))
              AND LOWER(COALESCE(domestic_appointment_status, '')) IN ('appointment', 'whatsapp appointment')
            GROUP BY agent_name
            HAVING agent_name IN ('{agents_list}')
        """)
    except Exception:
        month_df = pd.DataFrame()

    # Union the two event streams: one booking event per (lead, day). CRM
    # first so its canonical naming wins when both sources have the row.
    events = {}
    for df in (crm_events, app_events):
        if df.empty:
            continue
        for _, r in df.iterrows():
            events.setdefault((str(r['lead_id']), str(r['booked_date'])), str(r['agent_name']))

    today = datetime.now(ZoneInfo('Europe/London')).date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=4)  # Mon-Fri, matches the whiteboard

    rows = {a: {'agent_name': a, 'today_appts': 0, 'week_appts': 0, 'month_appts': 0}
            for a in TELESALES_AGENTS}
    for (lead_id, booked_date), agent in events.items():
        if agent not in rows:
            continue
        d = date.fromisoformat(booked_date)
        if d == today:
            rows[agent]['today_appts'] += 1
        if week_start <= d <= week_end:
            rows[agent]['week_appts'] += 1
    if not month_df.empty:
        for _, r in month_df.iterrows():
            agent = str(r['agent_name'])
            if agent in rows:
                rows[agent]['month_appts'] = int(r['month_appts'])

    return pd.DataFrame(list(rows.values()))

def _ga4_sessions(d0, d1):
    # GA4 Data API returns dates as YYYYMMDD strings (no dashes).
    d0g = d0.replace('-',''); d1g = d1.replace('-','')
    try:
        return _q(f"""
            SELECT
                CASE
                    WHEN LOWER(session_source) IN ('google','googleads') AND LOWER(session_medium) IN ('cpc','ppc','paid','paidsearch') THEN 'Google Paid'
                    WHEN LOWER(session_source) = 'google' AND LOWER(session_medium) = 'organic' THEN 'Google Organic'
                    WHEN LOWER(session_source) IN ('facebookads','facebook','fb','instagram','meta')
                      OR (LOWER(session_source) LIKE '%facebook%' AND LOWER(session_medium) IN ('cpc','paid','paidsocial','social')) THEN 'Meta'
                    WHEN LOWER(session_source) IN ('bing','bingads','microsoft') AND LOWER(session_medium) IN ('cpc','ppc','paid') THEN 'Bing'
                    WHEN LOWER(session_source) = '(direct)' OR LOWER(session_medium) = '(none)' THEN 'Direct'
                    WHEN LOWER(session_medium) = 'organic' THEN 'Organic Search'
                    WHEN LOWER(session_medium) IN ('referral','social') THEN 'Referral'
                    ELSE 'Other'
                END as channel,
                SUM(SAFE_CAST(sessions AS INT64))    as sessions,
                SUM(SAFE_CAST(new_users AS INT64))   as new_users,
                SUM(SAFE_CAST(total_users AS INT64)) as total_users
            FROM `{PROJECT}.bronze.ga4_api_sessions_daily`
            WHERE date BETWEEN '{d0g}' AND '{d1g}'
            GROUP BY 1
            ORDER BY sessions DESC
        """)
    except Exception:
        return pd.DataFrame()

def _ga4_pages(d0, d1):
    # GA4 Data API returns dates as YYYYMMDD strings (no dashes).
    d0g = d0.replace('-',''); d1g = d1.replace('-','')
    try:
        return _q(f"""
            SELECT
                REGEXP_REPLACE(page_path, r'\\?.*', '') as path,
                SUM(SAFE_CAST(screen_page_views AS INT64)) as views,
                SUM(SAFE_CAST(total_users AS INT64)) as users,
                ROUND(SUM(SAFE_CAST(user_engagement_duration AS FLOAT64))
                    / NULLIF(SUM(SAFE_CAST(total_users AS INT64)),0), 0) as avg_eng_secs
            FROM `{PROJECT}.bronze.ga4_api_pages_daily`
            WHERE date BETWEEN '{d0g}' AND '{d1g}'
              AND page_path NOT IN ('/', '', '(not set)')
              AND page_path NOT LIKE '%/wp-%'
            GROUP BY 1
            ORDER BY views DESC
            LIMIT 8
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

def _ts_period_scorecards():
    """Per-agent conversations / appointments / ratio for rolling periods
    (Yesterday, Last 7 days, Last 30 days), always relative to CURRENT_DATE
    (Europe/London) and INDEPENDENT of the page's Month-to-date pinning, so it
    refreshes every day. Conversation = talk_time >= 120s (gold
    qualified_conversations); ratio = conversations / appointments_booked
    (telesales target <= 3 conversations per appointment)."""
    agents_list = "','".join(TELESALES_AGENTS)
    return _q(f"""
        WITH base AS (
          SELECT agent_name, date,
                 qualified_conversations AS conv,
                 appointments_booked      AS appt
          FROM `{PROJECT}.gold.gold_agent_performance_daily`
          WHERE agent_name IN ('{agents_list}')
            AND date BETWEEN DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 30 DAY)
                         AND DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 1 DAY)
        )
        SELECT agent_name,
          SUM(IF(date  = DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 1 DAY), conv, 0)) AS y_conv,
          SUM(IF(date  = DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 1 DAY), appt, 0)) AS y_appt,
          SUM(IF(date >= DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 7 DAY), conv, 0)) AS w_conv,
          SUM(IF(date >= DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 7 DAY), appt, 0)) AS w_appt,
          SUM(conv) AS m_conv,
          SUM(appt) AS m_appt
        FROM base GROUP BY agent_name
    """)


def _hours_split(d0, d1):
    """Leads created in office hours vs out of hours (owner ask 20 Aug 2026).
    In-hours = Mon-Fri 08:30-17:29 Europe/London wall clock; everything else
    (evenings, weekends) is out of hours."""
    try:
        return _q(f"""
            SELECT
              COUNTIF(
                EXTRACT(DAYOFWEEK FROM DATETIME(created_at, 'Europe/London')) BETWEEN 2 AND 6
                AND (EXTRACT(HOUR FROM DATETIME(created_at, 'Europe/London')) * 60
                     + EXTRACT(MINUTE FROM DATETIME(created_at, 'Europe/London'))) BETWEEN 510 AND 1049
              ) AS in_hours,
              COUNT(*) AS total
            FROM `{PROJECT}.gold.gold_lead_activity`
            WHERE created_date BETWEEN '{d0}' AND '{d1}'
        """)
    except Exception:
        return pd.DataFrame()


def _returning(d0, d1):
    """Returning leads — existing leads (>14d) who re-submitted a form, from
    gold_lead_reenquiries (owner design 21 Aug 2026: they count everywhere —
    totals, platform attribution, CPL). Empty until the capture layer's first
    detection; degrades to zero rows before that."""
    try:
        return _q(f"""
            SELECT CAST(event_date AS STRING) AS date,
                   COALESCE(platform, 'Organic') AS source,
                   COUNT(DISTINCT lead_id) AS returning,
                   COUNT(DISTINCT IF(in_hours, lead_id, NULL)) AS in_hours
            FROM `{PROJECT}.gold.gold_lead_reenquiries`
            WHERE event_date BETWEEN '{d0}' AND '{d1}'
            GROUP BY 1, 2
        """)
    except Exception:
        return pd.DataFrame()


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
        'ts_pre':     (f'tspre:{d0s}:{d1s}', lambda: _telesales_pre_appt(d0s, d1s)),
        'ts_wb':      ('tswb',                 _telesales_whiteboard),
        'ts_periods': (f'tsper:{date.today().isoformat()}', _ts_period_scorecards),
        'pipeline':   ('pipeline',            _pipeline),
        'reg_leads':   (f'regl:{d0s}:{d1s}',   lambda: _regional_leads(d0s, d1s)),
        'reg_spend':   (f'regs:{d0s}:{d1s}',   lambda: _regional_spend(d0s, d1s)),
        'ga4_sessions':(f'ga4s:{d0s}:{d1s}',   lambda: _ga4_sessions(d0s, d1s)),
        'ga4_pages':   (f'ga4p:{d0s}:{d1s}',   lambda: _ga4_pages(d0s, d1s)),
        'water':       (f'water:{d0s}:{d1s}',  lambda: _water_leads(d0s, d1s)),
        'water_prev':  (f'water:{p0s}:{p1s}',  lambda: _water_leads(p0s, p1s)),
        'qc':          (f'qc:{d0s}:{d1s}',     lambda: _qc_flags(d0s, d1s)),
        'qc_leads':    (f'qcL:{d0s}:{d1s}',    lambda: _qc_lead_details(d0s, d1s)),
        'source_cpa':  (f'cpa:{d0s}:{d1s}',    lambda: _source_cpa(d0s, d1s)),
        'speed':       (f'spd:{d0s}:{d1s}',    lambda: _speed_to_call(d0s, d1s)),
        'heatmap':     (f'hm:{d0s}:{d1s}',     lambda: _call_heatmap(d0s, d1s)),
        'duration':    (f'dur:{d0s}:{d1s}',    lambda: _duration_sweet_spot(d0s, d1s)),
        'hours':       (f'hrs:{d0s}:{d1s}',    lambda: _hours_split(d0s, d1s)),
        'returning':   (f'ret:{d0s}:{d1s}',    lambda: _returning(d0s, d1s)),
        'returning_prev': (f'ret:{p0s}:{p1s}', lambda: _returning(p0s, p1s)),
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
    df_ts_pre    = results['ts_pre']
    df_ts_wb     = results['ts_wb']
    df_ts_per    = results['ts_periods']
    df_stg, df_rec   = results['pipeline']
    df_reg_leads     = results['reg_leads']
    df_reg_spend     = results['reg_spend']
    df_ga4_sessions  = results['ga4_sessions']
    df_ga4_pages     = results['ga4_pages']
    df_water         = results['water']
    df_water_prev    = results['water_prev']
    df_qc            = results['qc']
    df_qc_leads      = results['qc_leads']
    df_source_cpa    = results['source_cpa']
    df_speed         = results['speed']
    df_heatmap       = results['heatmap']
    df_duration      = results['duration']

    # ── Returning leads (owner ruling 21 Aug 2026: they count EVERYWHERE —
    #    totals, platform leads, CPL, the sources card). Zero rows until the
    #    sync's change-capture makes its first detection. ──
    df_ret      = results.get('returning')
    df_ret_prev = results.get('returning_prev')
    ret_by_src: dict = {}
    ret_daily:  dict = {}
    ret_total = ret_in = 0
    if df_ret is not None and not df_ret.empty:
        for _, rr in df_ret.iterrows():
            src_name = str(rr['source']); n = int(rr['returning'])
            ret_by_src[src_name] = ret_by_src.get(src_name, 0) + n
            ret_daily[(str(rr['date']), src_name)] = n
            ret_total += n
            ret_in += int(rr['in_hours']) if pd.notna(rr.get('in_hours')) else 0
    ret_prev_total = 0
    ret_prev_by_src: dict = {}
    if df_ret_prev is not None and not df_ret_prev.empty:
        for _, rr in df_ret_prev.iterrows():
            ret_prev_by_src[str(rr['source'])] = ret_prev_by_src.get(str(rr['source']), 0) + int(rr['returning'])
            ret_prev_total += int(rr['returning'])

    pa = df_attr.groupby("platform").agg(spend=("spend_gbp","sum"),clicks=("clicks","sum"),impr=("impressions","sum"),leads=("leads","sum")).reset_index()
    pa["leads"] = pa.apply(lambda r: int(r["leads"]) + ret_by_src.get(str(r["platform"]), 0), axis=1)
    pa["cpl"] = (pa["spend"] / pa["leads"].replace(0, float("nan"))).round(2)
    pa["ctr"] = (pa["clicks"] / pa["impr"].replace(0, float("nan")) * 100).round(3)
    tot_sp = float(pa["spend"].sum()); tot_ld = int(pa["leads"].sum()); tot_cl = int(pa["clicks"].sum())

    prev_marketing_totals = None
    if not df_attr_prev.empty:
        pp = df_attr_prev.groupby("platform").agg(spend=("spend_gbp","sum"),leads=("leads","sum")).reset_index()
        pp["leads"] = pp.apply(lambda r: int(r["leads"]) + ret_prev_by_src.get(str(r["platform"]), 0), axis=1)
        p_sp = float(pp["spend"].sum()); p_ld = int(pp["leads"].sum())
        p_all = (int(df_src_prev['leads'].sum()) if not df_src_prev.empty else 0) + ret_prev_total
        prev_marketing_totals = {"spend": p_sp, "leads": p_ld, "cpl": round(p_sp/p_ld,2) if p_ld else 0, "total_leads": p_all}

    platforms = [{'platform':str(r['platform']),'spend':float(r['spend']),'leads':int(r['leads']),'clicks':int(r['clicks']),'cpl':_safe(r['cpl']),'ctr':_safe(r['ctr'])} for _,r in pa.iterrows()]
    daily     = [{'date':str(r['date']),'platform':str(r['platform']),
                  'spend':_safe(float(r['spend_gbp'])),
                  'leads':(int(r['leads']) if pd.notna(r['leads']) else 0)
                          + ret_daily.pop((str(r['date']), str(r['platform'])), 0)}
                 for _,r in df_attr.iterrows()]
    # returning on days/platforms with no spend row still chart (leads-only rows)
    for (rd, rs), rn in ret_daily.items():
        if rs in ('Google', 'Meta', 'Bing'):
            daily.append({'date': rd, 'platform': rs, 'spend': 0.0, 'leads': rn})
    sources   = [{'source':str(r['source']),
                  'leads':int(r['leads']) + ret_by_src.get(str(r['source']), 0),
                  'returning':ret_by_src.get(str(r['source']), 0),
                  'appts':int(r['appts']),'sales':int(r['sales']),
                  'no_number':int(r['no_number']) if pd.notna(r.get('no_number')) else 0,
                  'not_a_lead':int(r['not_a_lead']) if pd.notna(r.get('not_a_lead')) else 0,
                  # a re-enquiry is live interest — returning always counts workable
                  'workable':int(r['leads']) + ret_by_src.get(str(r['source']), 0)
                             - (int(r['no_number']) if pd.notna(r.get('no_number')) else 0)
                             - (int(r['not_a_lead']) if pd.notna(r.get('not_a_lead')) else 0)}
                 for _,r in df_src.iterrows()]
    src_names = {s['source'] for s in sources}
    for rs, rn in ret_by_src.items():
        if rs not in src_names:
            sources.append({'source': rs, 'leads': rn, 'returning': rn, 'appts': 0, 'sales': 0,
                            'no_number': 0, 'not_a_lead': 0, 'workable': rn})
    tot_all   = (int(df_src['leads'].sum()) if not df_src.empty else 0) + ret_total
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

    ga4_sessions = [{'channel':str(r['channel']),'sessions':int(r['sessions']),'new_users':int(r['new_users']),'total_users':int(r['total_users'])} for _,r in df_ga4_sessions.iterrows()] if not df_ga4_sessions.empty else []
    ga4_pages    = [{'path':str(r['path']),'views':int(r['views']),'users':int(r['users']),'avg_eng_secs':int(r['avg_eng_secs']) if pd.notna(r['avg_eng_secs']) else 0} for _,r in df_ga4_pages.iterrows()] if not df_ga4_pages.empty else []

    water_total   = int(df_water['leads'].sum()) if not df_water.empty else 0
    water_split   = [{'type':str(r['service_type']),'leads':int(r['leads']),'sales':int(r['sales'])} for _,r in df_water.iterrows()] if not df_water.empty else []
    water_prev    = int(df_water_prev['leads'].sum()) if not df_water_prev.empty else 0

    # QC flags — leads where CRM and UTM attribution disagree
    qc_counts = {str(r['qc_flag']): int(r['leads']) for _, r in df_qc.iterrows()} if not df_qc.empty else {}
    qc_flagged = sum(v for k, v in qc_counts.items() if k in ('crm_no_utm', 'utm_only', 'disagree'))
    qc = {
        'flagged_total': qc_flagged,
        'agree':       qc_counts.get('agree', 0),
        'clean':       qc_counts.get('clean', 0),
        'crm_no_utm':  qc_counts.get('crm_no_utm', 0),
        'utm_only':    qc_counts.get('utm_only', 0),
        'disagree':    qc_counts.get('disagree', 0),
        'leads': [
            {
                'lead_id':       str(r['lead_id']),
                'name':          (str(r['first_name'] or '') + ' ' + str(r['last_name'] or '')).strip() or '(no name)',
                'campaign_id':   str(r['campaign_id']) if pd.notna(r.get('campaign_id')) else '',
                'crm_platform':  str(r['crm_platform']) if pd.notna(r.get('crm_platform')) else None,
                'utm_platform':  str(r['utm_platform']) if pd.notna(r.get('utm_platform')) else None,
                'attributed':    str(r['platform']) if pd.notna(r.get('platform')) else None,
                'qc_flag':       str(r['qc_flag']),
                'created_date':  str(r['created_date']),
            } for _, r in df_qc_leads.iterrows()
        ] if not df_qc_leads.empty else [],
    }

    if prev_marketing_totals is None:
        prev_marketing_totals = {'spend':0,'leads':0,'cpl':0,'total_leads':0}
    prev_marketing_totals['water_leads'] = water_prev

    source_cpa = [{'platform':str(r['platform']),'spend':float(r['spend']),'appts':int(r['appts']),'cost_per_appt':float(r['cost_per_appt_gbp']) if pd.notna(r.get('cost_per_appt_gbp')) else None} for _, r in df_source_cpa.iterrows()] if not df_source_cpa.empty else []
    df_hours = results.get('hours')
    hrs_in = int(df_hours['in_hours'].iloc[0]) if df_hours is not None and not df_hours.empty else 0
    hrs_tot = int(df_hours['total'].iloc[0]) if df_hours is not None and not df_hours.empty else 0
    marketing = {'totals':{'spend':tot_sp,'leads':tot_ld,'clicks':tot_cl,'cpl':round(tot_sp/tot_ld,2) if tot_ld else 0,'total_leads':tot_all,'water_leads':water_total,
                           'fresh':tot_all - ret_total,'returning':ret_total,
                           'in_hours':hrs_in + ret_in,'out_of_hours':max(0, hrs_tot - hrs_in) + max(0, ret_total - ret_in)},'prev_totals':prev_marketing_totals,'platforms':platforms,'daily':daily,'lead_sources':sources,'regions':regions,'ga4_sessions':ga4_sessions,'ga4_pages':ga4_pages,'water_split':water_split,'qc':qc,'source_cpa':source_cpa}

    agents = []
    if not df_ts.empty:
        for _, r in df_ts.iterrows():
            outb  = int(r['outbound_calls']) if pd.notna(r['outbound_calls']) else 0
            appts = int(r['appts'])          if pd.notna(r['appts'])          else 0
            sales = int(r['sales'])          if pd.notna(r['sales'])          else 0
            # Period-level ratios — sum first, then divide. Per-day versions
            # were wrong because today's calls and today's appointments come
            # from different leads (lead-to-booking lag is days, not zero).
            # Target = 15 calls/appt (was 3, unrealistic — heating outbound
            # to warm leads typically lands 7-20 calls/appt).
            appts_sat   = int(r['appts_sat'])    if pd.notna(r.get('appts_sat'))    else 0
            appts_sold  = int(r['appts_sold'])   if pd.notna(r.get('appts_sold'))   else 0
            appts_bookd = int(r['appts_booked']) if pd.notna(r.get('appts_booked')) else 0
            qual        = int(r['qual_convos'])  if pd.notna(r['qual_convos'])      else 0
            # Telesales manager's headline ratio = Conversations / Appointments,
            # target <= 3 (industry standard for warm-lead outbound telesales).
            # qual_convos now uses >=30s threshold to roughly match her manually-
            # marked "Conversation = Yes" tracking.
            # Period-bounded ratio (kept for non-monthly views) — uses
            # the period's appts as denominator.
            conv_per_appt_period = round(qual/appts, 2) if appts > 0 else None
            agents.append({'name':str(r['agent_name']),'total_calls':int(r['total_calls']) if pd.notna(r['total_calls']) else 0,'outbound':outb,'inbound':int(r['inbound_calls']) if pd.notna(r['inbound_calls']) else 0,'missed':int(r['missed_calls']) if pd.notna(r['missed_calls']) else 0,'unique_leads':int(r['unique_leads']) if pd.notna(r['unique_leads']) else 0,'avg_talk':int(r['avg_talk_time']) if pd.notna(r['avg_talk_time']) else 0,'qual_convos':qual,'appts':appts,'appts_booked':appts_bookd,'appts_sat':appts_sat,'appts_sold':appts_sold,'sales':sales,'deal_value':float(r['deal_value']) if pd.notna(r['deal_value']) else 0,'calls_per_appt':round(outb/appts,1) if appts>0 else None,'conv_per_appt_period':conv_per_appt_period,'pre_appt':0})

    # Merge in pre_appt (appointments with sit-date in period but booked before period started)
    pre_by_agent = {}
    if not df_ts_pre.empty:
        for _, r in df_ts_pre.iterrows():
            pre_by_agent[str(r['agent_name'])] = int(r['pre_appt'])
    # Merge in whiteboard counts (today / this week / this month — always
    # computed from CURRENT_DATE, independent of the period picker).
    wb_by_agent = {}
    if not df_ts_wb.empty:
        for _, r in df_ts_wb.iterrows():
            wb_by_agent[str(r['agent_name'])] = {
                'today_appts': int(r['today_appts']),
                'week_appts':  int(r['week_appts']),
                'month_appts': int(r['month_appts']),
            }
    # Monthly target per agent — matches the team's whiteboard ("TARGET 85")
    # and her xlsx ("Appt Per Month = 85"). Keep this constant in sync with
    # both if it ever changes.
    MONTHLY_TARGET_PER_AGENT = 85

    for a in agents:
        a['pre_appt'] = pre_by_agent.get(a['name'], 0)
        a['new_appt'] = max(0, a['appts'] - a['pre_appt'])  # New = All - Pre
        a['conv_per_new_appt'] = round(a['qual_convos'] / a['new_appt'], 2) if a['new_appt'] > 0 else None
        wb = wb_by_agent.get(a['name'], {})
        a['today_appts'] = wb.get('today_appts', 0)
        a['week_appts']  = wb.get('week_appts', 0)
        a['month_appts'] = wb.get('month_appts', 0)
        a['togo_appts']  = max(0, MONTHLY_TARGET_PER_AGENT - a['month_appts'])
        # Manager's headline ratio = MTD conversations ÷ FULL-MONTH appts
        # (matches her xlsx exactly — she uses sum of "Outcome=Appointment"
        # across all of June as the denominator, NOT just sits that have
        # already happened). Reduces ratio from inflated 3-12x back to
        # the 1-3x range her tracker shows.
        a['conv_per_appt'] = round(a['qual_convos'] / a['month_appts'], 2) if a['month_appts'] > 0 else None
        a['on_target'] = (a['conv_per_appt'] is not None and a['conv_per_appt'] <= 3)

    ts_out = sum(a['outbound'] for a in agents); ts_ap = sum(a['appts'] for a in agents)
    ts_sa  = sum(a['sales'] for a in agents);   ts_on = sum(1 for a in agents if a['on_target'])
    ts_daily_list = [{'date':str(r['date']),'calls':int(r['calls']) if pd.notna(r['calls']) else 0,'outbound':int(r['outbound']) if pd.notna(r['outbound']) else 0,'appts':int(r['appts']) if pd.notna(r['appts']) else 0,'appts_booked':int(r['appts_booked']) if pd.notna(r.get('appts_booked')) else 0,'sales':int(r['sales']) if pd.notna(r['sales']) else 0} for _,r in df_ts_day.iterrows()]
    prev_telesales_totals = None
    if not df_ts_prev.empty:
        p_out  = int(df_ts_prev['outbound_calls'].sum())
        p_ap   = int(df_ts_prev['appts'].sum())
        p_l2a  = round(p_ap / p_out * 100, 1) if p_out else 0
        prev_telesales_totals = {'outbound':p_out,'appts':p_ap,'sales':int(df_ts_prev['sales'].sum()),'on_target_count':int((df_ts_prev['appts']>0).sum()),'l2a':p_l2a}
    # Cost per appt — uses paid spend from the same date range / telesales appts
    cpa = round(tot_sp / ts_ap, 2) if ts_ap else 0
    prev_cpa = round((prev_marketing_totals.get('spend', 0) / prev_telesales_totals['appts']), 2) if prev_telesales_totals and prev_telesales_totals.get('appts') else 0
    if prev_telesales_totals:
        prev_telesales_totals['cpa'] = prev_cpa
    speed_to_call = [
        {'bucket': str(r['bucket']), 'leads': int(r['leads']), 'appts': int(r['appts']),
         'appt_rate': _safe(r['appt_rate'])}
        for _, r in df_speed.iterrows()
    ] if not df_speed.empty else []
    heatmap = [
        {'dow': int(r['dow']), 'dow_name': str(r['dow_name']), 'hour': int(r['hour']),
         'calls': int(r['calls']), 'appts': int(r['appts']), 'rate': _safe(r['rate'])}
        for _, r in df_heatmap.iterrows()
    ] if not df_heatmap.empty else []
    duration_buckets = [
        {'bucket': str(r['bucket']), 'calls': int(r['calls']), 'appts': int(r['appts']),
         'rate': _safe(r['rate'])}
        for _, r in df_duration.iterrows()
    ] if not df_duration.empty else []
    # Team totals — these are what the headline KPI cards show.
    # Conv/Appt target = 3 (industry standard, matches her xlsx).
    # Pace to target = team appts / (4 agents × 85 monthly target).
    ts_conv = sum(a['qual_convos'] for a in agents)
    ts_pre  = sum(a['pre_appt'] for a in agents)
    ts_new  = sum(a['new_appt'] for a in agents)
    ts_today = sum(a['today_appts'] for a in agents)
    ts_week  = sum(a['week_appts']  for a in agents)
    ts_month = sum(a['month_appts'] for a in agents)
    monthly_target_per_agent = MONTHLY_TARGET_PER_AGENT
    team_target = monthly_target_per_agent * len(TELESALES_AGENTS)
    ts_togo = max(0, team_target - ts_month)

    # Detect whether the selected period is a "monthly" view — used by the
    # frontend to decide whether the Pre/New freshness table makes sense.
    is_monthly = False
    try:
        d0_dt = date.fromisoformat(d0s)
        d1_dt = date.fromisoformat(d1s)
        # Monthly = period starts on the 1st of a month AND ends in the SAME
        # calendar month. Covers Month-to-date and Last Month. Excludes
        # Today/Yesterday/Last-7d (those don't start on the 1st) and
        # Quarter-to-date (ends in a later month than it starts).
        is_monthly = (
            d0_dt.day == 1
            and d0_dt.year == d1_dt.year
            and d0_dt.month == d1_dt.month
        )
    except Exception:
        pass

    # Rolling-period scorecards (Yesterday / Last 7d / Last 30d) — per agent +
    # team, refreshed daily, independent of the MTD pinning.
    def _scard(cc, ac):
        rows = []; tc = 0; ta = 0
        for _, r in df_ts_per.iterrows():
            c = int(r[cc]) if pd.notna(r[cc]) else 0
            a = int(r[ac]) if pd.notna(r[ac]) else 0
            tc += c; ta += a
            rows.append({'name': str(r['agent_name']), 'conv': c, 'appts': a,
                         'ratio': round(c / a, 2) if a > 0 else None})
        rows.sort(key=lambda x: -x['conv'])
        return {'agents': rows,
                'team': {'conv': tc, 'appts': ta,
                         'ratio': round(tc / ta, 2) if ta > 0 else None}}
    period_scorecards = {} if df_ts_per.empty else {
        'yesterday': _scard('y_conv', 'y_appt'),
        'last7d':    _scard('w_conv', 'w_appt'),
        'last30d':   _scard('m_conv', 'm_appt'),
    }

    telesales = {
        'agents': agents,
        'period_scorecards': period_scorecards,
        'daily': ts_daily_list,
        'is_monthly': is_monthly,
        'team_target_per_agent': monthly_target_per_agent,
        'team_target': team_target,
        'totals': {
            'outbound': ts_out, 'appts': ts_ap, 'sales': ts_sa,
            'on_target_count': ts_on,
            'on_target_pct': round(ts_on/len(agents)*100) if agents else 0,
            'l2a': round(ts_ap/ts_out*100,1) if ts_out else 0,
            'a2s': round(ts_sa/ts_ap*100,1) if ts_ap else 0,
            'cpa': cpa,
            'conv': ts_conv,
            # Team Conv/Appt uses full-month appts denominator (matches xlsx)
            'conv_per_appt': round(ts_conv/ts_month, 2) if ts_month else None,
            'conv_per_appt_period': round(ts_conv/ts_ap, 2) if ts_ap else None,
            'pre_appt': ts_pre,
            'new_appt': ts_new,
            'conv_per_new_appt': round(ts_conv/ts_new, 2) if ts_new else None,
            'pace_pct': round(ts_ap/team_target*100, 1) if team_target else 0,
            'today_appts': ts_today,
            'week_appts':  ts_week,
            'month_appts': ts_month,
            'togo_appts':  ts_togo,
        },
        'prev_totals': prev_telesales_totals,
        'speed_to_call': speed_to_call, 'heatmap': heatmap, 'duration_buckets': duration_buckets,
    }

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

# Serverless function: no local disk to persist a secret across cold starts.
# DASHBOARD_SECRET_KEY should be set in Vercel env — if it isn't, we fail
# "closed enough": generate a random key per cold start so nothing is ever
# signed with a guessable/empty key, at the cost of sessions dying whenever
# the function cold-starts (same trade-off as sales_app / availability_app).
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)

# ---------------------------------------------------------------------------
# Auth — env-var user store (no local file persistence at runtime here).
# DASHBOARD_USERS = '{"username": "<werkzeug password hash>", ...}'
# ---------------------------------------------------------------------------

try:
    _DASHBOARD_USERS = _json.loads(os.environ.get("DASHBOARD_USERS") or "{}")
except ValueError:
    _DASHBOARD_USERS = {}


def _check_login(username: str, password: str) -> bool:
    stored_hash = _DASHBOARD_USERS.get(username)
    if not stored_hash:
        return False
    return check_password_hash(stored_hash, password)


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not logged in"}), 401
            return redirect(f"/login?next={request.path}")
        return f(*args, **kwargs)
    return wrapped


_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — Trust Dashboard</title>
<style>
  *,*::before,*::after{{ box-sizing:border-box; margin:0; padding:0; }}
  html,body{{
    background:#14161F; color:#E7E9F2;
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    font-size:14px; min-height:100vh;
    display:flex; align-items:center; justify-content:center;
  }}
  .card{{
    background:#1D2030; border:1px solid #2C3046; border-radius:14px;
    box-shadow:0 12px 40px rgba(0,0,0,.45); padding:36px 32px;
    width:100%; max-width:360px;
  }}
  h1{{ font-size:19px; font-weight:700; margin-bottom:4px; }}
  .subtitle{{ color:#8A8FA8; font-size:13px; margin-bottom:24px; }}
  label{{ display:block; font-size:12.5px; font-weight:600; color:#B7BBD1; margin-bottom:6px; }}
  input[type=text], input[type=password]{{
    width:100%; padding:11px 13px; border-radius:9px;
    border:1px solid #2C3046; background:#14161F;
    font-family:inherit; font-size:14px; color:#E7E9F2;
    outline:none; margin-bottom:16px;
  }}
  input:focus{{ border-color:#5B6CFF; }}
  .btn{{
    width:100%; padding:12px; border-radius:9px; border:none;
    background:#5B6CFF; color:#fff; font-family:inherit;
    font-size:14px; font-weight:600; cursor:pointer;
  }}
  .btn:hover{{ opacity:.9; }}
  .error{{
    background:#3A1F26; color:#FF8B98; border-radius:8px;
    padding:10px 13px; font-size:13px; font-weight:500; margin-bottom:16px;
  }}
</style>
</head>
<body>
<div class="card">
  <h1>Sign in</h1>
  <p class="subtitle">Trust Dashboard — internal tool</p>
  {error_html}
  <form method="post">
    <label for="username">Username</label>
    <input type="text" id="username" name="username" autocomplete="username" autofocus required>
    <label for="password">Password</label>
    <input type="password" id="password" name="password" autocomplete="current-password" required>
    <button type="submit" class="btn">Sign in</button>
  </form>
</div>
</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        if _check_login(username, password):
            session.permanent = True
            session["username"] = username
            nxt = request.args.get("next") or "/"
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            return redirect(nxt)
        error = "Incorrect username or password."
    error_html = f'<div class="error">{error}</div>' if error else ""
    return Response(_LOGIN_PAGE.format(error_html=error_html), mimetype="text/html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# Internal tool: keep it out of search engines. noindex stops Google listing
# it; it does NOT make the app private - that is what the login is for.
@app.after_request
def _noindex(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


@app.route("/robots.txt")
def _robots():
    # Deliberately ALLOW crawling: Google must be able to fetch the page to see
    # the X-Robots-Tag noindex above. A Disallow here blocks the crawl, so
    # Google keeps serving its stale cached copy forever (bit us Aug 2026 —
    # a June cache with company numbers survived 11 days of Disallow+noindex).
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


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
@login_required
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

@app.route('/api/refresh', methods=['GET', 'POST'])
@login_required
def refresh():
    with _cache_lock:
        cleared = len(_cache)
        _cache.clear()
    return jsonify({'ok': True, 'cache_cleared': cleared})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@login_required
def serve_frontend(path):
    html = _get_html()
    if html is None:
        return 'Dashboard unavailable', 404
    return Response(html, mimetype='text/html')
