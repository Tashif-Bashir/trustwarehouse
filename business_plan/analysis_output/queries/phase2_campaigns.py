"""Phase 2.4/2.5 — campaign winners/losers (last 12 months) + Yorkshire focus.
Campaign-level lead joins use UTM (43-52% coverage — C2 caveat); spend is exact."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 260)
OUT = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data'

print("=== Google campaigns, last 12 months: spend + utm-matched outcomes ===")
g = q("""
  WITH sp AS (
    SELECT campaign_name, ROUND(SUM(spend_gbp),0) AS spend, SUM(clicks) AS clicks
    FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
    WHERE DATE(date) BETWEEN '2025-07-01' AND '2026-06-30'
    GROUP BY 1),
  ld AS (
    SELECT exact_marketing_campaign_64d0b4a09e91b AS utm, COUNT(*) AS utm_leads,
      COUNTIF(TRIM(COALESCE(status_633ae6f6ac6fe,'')) IN
        ('Appointment','Appointment Cancelled','WhatsApp Appointment')) AS utm_appts
    FROM `trustwarehouse.bronze.sharpspring_leads`
    WHERE create_timestamp BETWEEN '2025-07-01' AND '2026-06-30'
      AND TRIM(COALESCE(exact_marketing_campaign_64d0b4a09e91b,'')) != ''
    GROUP BY 1)
  SELECT sp.campaign_name, sp.spend, sp.clicks, ld.utm_leads, ld.utm_appts,
         ROUND(SAFE_DIVIDE(sp.spend, ld.utm_leads),0) AS cpl_utm,
         ROUND(SAFE_DIVIDE(sp.spend, ld.utm_appts),0) AS cpa_utm
  FROM sp LEFT JOIN ld ON LOWER(TRIM(sp.campaign_name)) = LOWER(TRIM(ld.utm))
  WHERE sp.spend > 500
  ORDER BY sp.spend DESC
""")
print(g.to_string(index=False))
g.to_csv(OUT + r'\phase2_google_campaigns_12mo.csv', index=False)

print("\n=== Meta campaigns, last 12 months (spend only — names drift; id-keyed) ===")
mt = q("""
  SELECT ANY_VALUE(campaign_name) AS latest_name, campaign_id,
         ROUND(SUM(spend_gbp),0) AS spend
  FROM `trustwarehouse.bronze.meta_api_campaign_daily`
  WHERE DATE(date) BETWEEN '2025-07-01' AND '2026-06-30'
  GROUP BY campaign_id HAVING spend > 500 ORDER BY spend DESC LIMIT 15
""")
print(mt.to_string(index=False))

print("\n=== Yorkshire: region-targeted spend (campaign names) vs Yorkshire leads ===")
print(q("""
  SELECT 'google_yorkshire_campaigns' AS what, ROUND(SUM(spend_gbp),0) AS v
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
  WHERE LOWER(campaign_name) LIKE '%york%' AND DATE(date) BETWEEN '2025-07-01' AND '2026-06-30'
  UNION ALL
  SELECT 'meta_yorkshire_campaigns', ROUND(SUM(spend_gbp),0)
  FROM `trustwarehouse.bronze.meta_api_campaign_daily`
  WHERE LOWER(campaign_name) LIKE '%york%' AND DATE(date) BETWEEN '2025-07-01' AND '2026-06-30'
  UNION ALL
  SELECT 'yorkshire_region_leads_12mo', COUNT(*)
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE TRIM(COALESCE(location_6349396e4a08d,'')) = 'Yorkshire and the Humber'
    AND create_timestamp BETWEEN '2025-07-01' AND '2026-06-30'
  UNION ALL
  SELECT 'yorkshire_region_appts_12mo', COUNTIF(TRIM(COALESCE(status_633ae6f6ac6fe,'')) IN
    ('Appointment','Appointment Cancelled','WhatsApp Appointment'))
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE TRIM(COALESCE(location_6349396e4a08d,'')) = 'Yorkshire and the Humber'
    AND create_timestamp BETWEEN '2025-07-01' AND '2026-06-30'
""").to_string(index=False))

print("\n=== weekly blended, last 12 weeks ===")
print(q("""
  WITH sp AS (
    SELECT DATE_TRUNC(DATE(date), WEEK(MONDAY)) AS wk, SUM(spend_gbp) AS s
    FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
    WHERE DATE(date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 84 DAY) GROUP BY 1
    UNION ALL
    SELECT DATE_TRUNC(DATE(date), WEEK(MONDAY)), SUM(spend_gbp)
    FROM `trustwarehouse.bronze.meta_api_campaign_daily`
    WHERE DATE(date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 84 DAY) GROUP BY 1
    UNION ALL
    SELECT DATE_TRUNC(SAFE_CAST(TimePeriod AS DATE), WEEK(MONDAY)), SUM(SAFE_CAST(Spend AS FLOAT64))
    FROM `trustwarehouse.bronze.bing_adsaccount_performance_report_daily`
    WHERE SAFE_CAST(TimePeriod AS DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 84 DAY) GROUP BY 1),
  ld AS (
    SELECT DATE_TRUNC(DATE(create_timestamp), WEEK(MONDAY)) AS wk, COUNT(*) AS leads
    FROM `trustwarehouse.bronze.sharpspring_leads`
    WHERE create_timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 84 DAY))
    GROUP BY 1)
  SELECT wk, ROUND(SUM(s),0) AS paid_spend, ANY_VALUE(leads) AS all_leads,
         ROUND(SUM(s)/ANY_VALUE(leads),0) AS blended_cpl_allleads
  FROM sp JOIN ld USING (wk) GROUP BY wk ORDER BY wk
""").to_string(index=False))
