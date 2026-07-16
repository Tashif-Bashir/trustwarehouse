"""Phase 2.1/2.2/2.3/2.6/2.7 — platform economics monthly (24mo), weekly (6mo),
seasonality, channel mix, lead quality by source, cost-per-sale (Jan25+).

Definitions (per cleaning_rules.sql + Phase 0/1):
- Platform from CRM campaign: Google={'Google Ads','Google Search','Google Shopping'},
  Meta={'Facebook'}, Bing={'Bing Ads','Bing Search'}, else Organic/Other.
- Leads exclude test records. Appointments = cohort statuses (incl cancelled + WhatsApp).
- Sold = email-matched valid Unleashed order dated >= lead creation (complete Jan 2025+).
- Spend = bronze sums (Google incl. network slices; Bing account report; C3: no Bing pre-2025).
"""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 260)
OUT = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data'

LEAD_CTE = """
  leads AS (
    SELECT l.id, DATE(l.create_timestamp) AS d,
      LOWER(TRIM(l.email_address)) AS email,
      CASE
        WHEN c.campaign_name IN ('Google Ads','Google Search','Google Shopping') THEN 'Google'
        WHEN c.campaign_name = 'Facebook' THEN 'Meta'
        WHEN c.campaign_name IN ('Bing Ads','Bing Search') THEN 'Bing'
        ELSE 'Organic/Other' END AS platform,
      TRIM(COALESCE(l.status_633ae6f6ac6fe,'')) AS status,
      TRIM(COALESCE(l.status_633ae6f6ac6fe,'')) IN
        ('Appointment','Appointment Cancelled','WhatsApp Appointment') AS is_appt
    FROM `trustwarehouse.bronze.sharpspring_leads` l
    LEFT JOIN `trustwarehouse.bronze.sharpspring_campaigns` c
      ON CAST(c.id AS STRING) = CAST(l.campaign_id AS STRING)
    WHERE l.create_timestamp >= '2024-08-01'
      AND NOT REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(l.first_name,''), ' ', COALESCE(l.last_name,''))),
                              r'zzz|\\btest lead\\b|testlead')
      AND NOT (l.email_address LIKE '%@trustelectricheating.co.uk'
               AND NOT REGEXP_CONTAINS(COALESCE(l.email_address,''), r'^[0-9]+@'))),
  orders AS (
    SELECT DISTINCT LOWER(TRIM(c.email)) AS email,
      TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(s.order_date, r'([0-9]+)') AS INT64)) AS order_ts,
      SAFE_CAST(s.sub_total AS FLOAT64) AS sub_total
    FROM `trustwarehouse.bronze.unleashed_sales_orders` s
    JOIN `trustwarehouse.bronze.unleashed_customers` c ON s.customer__guid = c.guid
    WHERE s.order_status NOT IN ('Deleted','Parked') AND SAFE_CAST(s.sub_total AS FLOAT64) > 0),
  lead_sales AS (
    SELECT l.id, MIN(o.order_ts) AS first_order, SUM(o.sub_total) AS lead_revenue
    FROM leads l JOIN orders o
      ON l.email = o.email AND o.order_ts >= TIMESTAMP(l.d)
         AND o.order_ts < TIMESTAMP_ADD(TIMESTAMP(l.d), INTERVAL 180 DAY)
    WHERE l.email != ''
    GROUP BY l.id),
  spend AS (
    SELECT DATE(date) AS d, 'Google' AS platform, spend_gbp AS s, clicks, impressions
    FROM `trustwarehouse.bronze.google_ads_api_campaign_daily` WHERE DATE(date) >= '2024-08-01'
    UNION ALL
    SELECT DATE(date), 'Meta', spend_gbp, clicks, impressions
    FROM `trustwarehouse.bronze.meta_api_campaign_daily` WHERE DATE(date) >= '2024-08-01'
    UNION ALL
    SELECT SAFE_CAST(TimePeriod AS DATE), 'Bing', SAFE_CAST(Spend AS FLOAT64),
           SAFE_CAST(Clicks AS INT64), SAFE_CAST(Impressions AS INT64)
    FROM `trustwarehouse.bronze.bing_adsaccount_performance_report_daily`
    WHERE SAFE_CAST(TimePeriod AS DATE) >= '2024-08-01')
"""

print("=== monthly platform economics, Aug 2024 - Jul 2026 ===")
monthly = q(f"""
  WITH {LEAD_CTE},
  lm AS (
    SELECT FORMAT_DATE('%Y-%m', l.d) AS month, l.platform,
           COUNT(*) AS leads, COUNTIF(l.is_appt) AS appts,
           COUNT(ls.id) AS sold, ROUND(SUM(ls.lead_revenue), 0) AS revenue
    FROM leads l LEFT JOIN lead_sales ls ON l.id = ls.id
    GROUP BY 1, 2),
  sm AS (
    SELECT FORMAT_DATE('%Y-%m', d) AS month, platform,
           ROUND(SUM(s), 0) AS spend, SUM(clicks) AS clicks
    FROM spend GROUP BY 1, 2)
  SELECT COALESCE(lm.month, sm.month) AS month, COALESCE(lm.platform, sm.platform) AS platform,
         sm.spend, sm.clicks, lm.leads, lm.appts, lm.sold, lm.revenue,
         ROUND(SAFE_DIVIDE(sm.spend, sm.clicks), 2) AS cpc,
         ROUND(SAFE_DIVIDE(sm.spend, lm.leads), 0) AS cpl,
         ROUND(SAFE_DIVIDE(sm.spend, lm.appts), 0) AS cpa,
         ROUND(SAFE_DIVIDE(sm.spend, lm.sold), 0) AS cps,
         ROUND(SAFE_DIVIDE(lm.revenue, sm.spend), 2) AS roas
  FROM lm FULL OUTER JOIN sm USING (month, platform)
  ORDER BY month, platform
""")
monthly.to_csv(OUT + r'\phase2_monthly_platform.csv', index=False)
# condensed print: paid platforms only, quarterly aggregation for the eyeball
m = monthly[monthly.platform.isin(['Google', 'Meta', 'Bing'])].copy()
m['q'] = m.month.str[:4] + '-Q' + ((m.month.str[5:7].astype(int) - 1) // 3 + 1).astype(str)
agg = m.groupby(['q', 'platform']).agg(spend=('spend', 'sum'), leads=('leads', 'sum'),
                                       appts=('appts', 'sum'), sold=('sold', 'sum'),
                                       revenue=('revenue', 'sum')).reset_index()
agg['cpl'] = (agg.spend / agg.leads).round(0)
agg['cpa'] = (agg.spend / agg.appts).round(0)
agg['roas'] = (agg.revenue / agg.spend).round(2)
print(agg.to_string(index=False))

print("\n=== blended (all paid) monthly ===")
b = m.groupby('month').agg(spend=('spend', 'sum'), leads=('leads', 'sum'), appts=('appts', 'sum'),
                           sold=('sold', 'sum'), revenue=('revenue', 'sum')).reset_index()
b['cpl'] = (b.spend / b.leads).round(0)
b['cpa'] = (b.spend / b.appts).round(0)
b['mix_google'] = None
print(b.to_string(index=False))
b.to_csv(OUT + r'\phase2_blended_monthly.csv', index=False)

print("\n=== seasonality: month-of-year (paid leads + organic total, both years) ===")
m['moy'] = m.month.str[5:7]
seas = m.groupby(['moy', 'month']).leads.sum().reset_index().groupby('moy').leads.mean().round(0)
print(seas.to_string())

print("\n=== lead quality by source (last 12 months) ===")
print(q(f"""
  WITH {LEAD_CTE}
  SELECT l.platform, COUNT(*) AS leads,
    ROUND(COUNTIF(l.status IN ('No Number','No Number - Follow Up','Not a Lead','Admin/Finance'))/COUNT(*)*100,1) AS junk_pct,
    ROUND(COUNTIF(l.status = '')/COUNT(*)*100,1) AS no_outcome_pct,
    ROUND(COUNTIF(l.status IN ('Not Interested','Not interested'))/COUNT(*)*100,1) AS not_interested_pct,
    ROUND(COUNTIF(l.is_appt)/COUNT(*)*100,1) AS appt_pct,
    ROUND(COUNT(ls.id)/COUNT(*)*100,1) AS sold_pct,
    ROUND(SUM(ls.lead_revenue)/COUNT(*),0) AS revenue_per_lead
  FROM leads l LEFT JOIN lead_sales ls ON l.id = ls.id
  WHERE l.d >= '2025-07-01'
  GROUP BY 1 ORDER BY leads DESC
""").to_string(index=False))
