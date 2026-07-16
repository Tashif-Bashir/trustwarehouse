"""Phase 3A.1/3A.4/3A.5 — full-funnel conversion by month & platform, velocity,
lost reasons.

Stage definitions (operational, documented):
- reached  = lead has ANY human outcome status (not blank, not No Contact/No Number/
             Not a Lead/Admin-Finance) — i.e. a conversation happened.
- appt     = Appointment / Appointment Cancelled / WhatsApp Appointment (cohort).
- sold     = email-matched valid Unleashed order within 180d (C: complete Jan 2025+).
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

BASE = """
  leads AS (
    SELECT l.id, DATE(l.create_timestamp) AS d, l.create_timestamp AS cts,
      LOWER(TRIM(l.email_address)) AS email,
      CASE
        WHEN c.campaign_name IN ('Google Ads','Google Search','Google Shopping') THEN 'Google'
        WHEN c.campaign_name = 'Facebook' THEN 'Meta'
        WHEN c.campaign_name IN ('Bing Ads','Bing Search') THEN 'Bing'
        ELSE 'Organic/Other' END AS platform,
      TRIM(COALESCE(l.status_633ae6f6ac6fe,'')) AS status
    FROM `trustwarehouse.bronze.sharpspring_leads` l
    LEFT JOIN `trustwarehouse.bronze.sharpspring_campaigns` c
      ON CAST(c.id AS STRING) = CAST(l.campaign_id AS STRING)
    WHERE l.create_timestamp >= '2024-08-01'
      AND NOT REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(l.first_name,''), ' ', COALESCE(l.last_name,''))),
                              r'zzz|\\btest lead\\b|testlead')
      AND NOT (l.email_address LIKE '%@trustelectricheating.co.uk'
               AND NOT REGEXP_CONTAINS(COALESCE(l.email_address,''), r'^[0-9]+@'))),
  staged AS (
    SELECT *,
      status NOT IN ('', 'No Contact', 'No Number', 'No Number - Follow Up',
                     'Not a Lead', 'Admin/Finance') AS reached,
      status IN ('Appointment','Appointment Cancelled','WhatsApp Appointment') AS is_appt
    FROM leads),
  orders AS (
    SELECT DISTINCT LOWER(TRIM(c.email)) AS email,
      TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(s.order_date, r'([0-9]+)') AS INT64)) AS order_ts
    FROM `trustwarehouse.bronze.unleashed_sales_orders` s
    JOIN `trustwarehouse.bronze.unleashed_customers` c ON s.customer__guid = c.guid
    WHERE s.order_status NOT IN ('Deleted','Parked') AND SAFE_CAST(s.sub_total AS FLOAT64) > 0),
  lead_sold AS (
    SELECT s.id, MIN(o.order_ts) AS first_order
    FROM staged s JOIN orders o
      ON s.email = o.email AND o.order_ts >= s.cts
         AND o.order_ts < TIMESTAMP_ADD(s.cts, INTERVAL 180 DAY)
    WHERE s.email != ''
    GROUP BY s.id)
"""

print("=== funnel by quarter x platform ===")
fq = q(f"""
  WITH {BASE}
  SELECT CONCAT(CAST(EXTRACT(YEAR FROM s.d) AS STRING), '-Q',
                CAST(EXTRACT(QUARTER FROM s.d) AS STRING)) AS q,
         s.platform, COUNT(*) AS leads,
         ROUND(COUNTIF(s.reached)/COUNT(*)*100,1) AS reached_pct,
         ROUND(COUNTIF(s.is_appt)/COUNT(*)*100,1) AS appt_pct,
         ROUND(COUNTIF(s.is_appt)/NULLIF(COUNTIF(s.reached),0)*100,1) AS reached_to_appt_pct,
         ROUND(COUNT(ls.id)/NULLIF(COUNTIF(s.is_appt),0)*100,1) AS appt_to_sale_pct,
         ROUND(COUNT(ls.id)/COUNT(*)*100,1) AS lead_to_sale_pct
  FROM staged s LEFT JOIN lead_sold ls ON s.id = ls.id
  GROUP BY 1, 2 HAVING leads > 100
  ORDER BY q, platform
""")
print(fq.to_string(index=False))
fq.to_csv(OUT + r'\phase3_funnel_quarterly.csv', index=False)

print("\n=== monthly funnel, all platforms combined ===")
fm = q(f"""
  WITH {BASE}
  SELECT FORMAT_DATE('%Y-%m', s.d) AS month, COUNT(*) AS leads,
         ROUND(COUNTIF(s.reached)/COUNT(*)*100,1) AS reached_pct,
         ROUND(COUNTIF(s.is_appt)/COUNT(*)*100,1) AS appt_pct,
         ROUND(COUNT(ls.id)/NULLIF(COUNTIF(s.is_appt),0)*100,1) AS appt_to_sale_pct
  FROM staged s LEFT JOIN lead_sold ls ON s.id = ls.id
  GROUP BY 1 ORDER BY 1
""")
print(fm.to_string(index=False))
fm.to_csv(OUT + r'\phase3_funnel_monthly.csv', index=False)

print("\n=== velocity: median days lead -> first order, by quarter ===")
print(q(f"""
  WITH {BASE}
  SELECT CONCAT(CAST(EXTRACT(YEAR FROM s.d) AS STRING), '-Q',
                CAST(EXTRACT(QUARTER FROM s.d) AS STRING)) AS q,
         COUNT(ls.id) AS sales,
         ROUND(APPROX_QUANTILES(TIMESTAMP_DIFF(ls.first_order, s.cts, HOUR)/24.0, 100)[OFFSET(50)],1) AS median_days,
         ROUND(APPROX_QUANTILES(TIMESTAMP_DIFF(ls.first_order, s.cts, HOUR)/24.0, 100)[OFFSET(75)],1) AS p75_days
  FROM staged s JOIN lead_sold ls ON s.id = ls.id
  GROUP BY 1 ORDER BY 1
""").to_string(index=False))

print("\n=== lost reasons: reached-but-no-appointment, last 12mo by platform ===")
print(q(f"""
  WITH {BASE}
  SELECT s.status, COUNT(*) AS n,
         COUNTIF(s.platform='Google') AS google, COUNTIF(s.platform='Meta') AS meta
  FROM staged s
  WHERE s.d >= '2025-07-01' AND s.reached AND NOT s.is_appt
  GROUP BY 1 ORDER BY n DESC LIMIT 12
""").to_string(index=False))
