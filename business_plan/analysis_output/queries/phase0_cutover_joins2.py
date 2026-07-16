"""Phase 0.5 cutover timeline + 0.7 join-key strength probes."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 220)

print("=== wildix date range + direction/type values ===")
print(q("""
  SELECT MIN(TIMESTAMP_MILLIS(start_time)) AS first_call,
         MAX(TIMESTAMP_MILLIS(start_time)) AS last_call, COUNT(*) AS rows_
  FROM `trustwarehouse.bronze.wildix_calls`
""").to_string(index=False))
print(q("""
  SELECT direction, type, COUNT(*) n FROM `trustwarehouse.bronze.wildix_calls`
  GROUP BY 1,2 ORDER BY n DESC LIMIT 8
""").to_string(index=False))

print("\n=== cutover window: daily calls per system, 20 Jun - 16 Jul ===")
print(q("""
  WITH w AS (
    SELECT DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London') AS d, COUNT(*) AS wildix
    FROM `trustwarehouse.bronze.wildix_calls`
    WHERE TIMESTAMP_MILLIS(start_time) >= '2026-06-20' GROUP BY d),
  a AS (
    SELECT DATE(start, 'Europe/London') AS d, COUNT(*) AS ascend
    FROM `trustwarehouse.bronze.ascend_calls` GROUP BY d)
  SELECT COALESCE(w.d, a.d) AS day, IFNULL(wildix,0) AS wildix, IFNULL(ascend,0) AS ascend
  FROM w FULL OUTER JOIN a ON w.d = a.d
  ORDER BY day
""").to_string(index=False))

print("\n=== join probe A: leads created last 14d with >=1 Ascend call on their number ===")
print(q("""
  WITH leads AS (
    SELECT id,
      REGEXP_REPLACE(COALESCE(NULLIF(TRIM(phone_number),''), NULLIF(TRIM(mobile_phone_number),'')), r'[^0-9]', '') AS ph
    FROM `trustwarehouse.bronze.sharpspring_leads`
    WHERE DATE(create_timestamp) BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 15 DAY)
                                     AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)),
  norm AS (
    SELECT id, CASE WHEN ph LIKE '00%' THEN SUBSTR(ph, 3)
                    WHEN ph LIKE '0%' THEN CONCAT('44', SUBSTR(ph, 2)) ELSE ph END AS ph
    FROM leads WHERE ph IS NOT NULL AND ph != ''),
  callnums AS (
    SELECT DISTINCT CASE WHEN n LIKE '00%' THEN SUBSTR(n, 3)
                         WHEN n LIKE '0%' THEN CONCAT('44', SUBSTR(n, 2)) ELSE n END AS ph
    FROM (SELECT REGEXP_REPLACE(COALESCE(JSON_VALUE(`to`,'$.number'), ''), r'[^0-9]', '') AS n
          FROM `trustwarehouse.bronze.ascend_calls` WHERE direction='outbound'
          UNION ALL
          SELECT REGEXP_REPLACE(COALESCE(JSON_VALUE(`from`,'$.number'), ''), r'[^0-9]', '')
          FROM `trustwarehouse.bronze.ascend_calls` WHERE direction='inbound'))
  SELECT COUNT(DISTINCT norm.id) AS leads_with_phone,
         COUNT(DISTINCT IF(callnums.ph IS NOT NULL, norm.id, NULL)) AS leads_with_call_match,
         ROUND(COUNT(DISTINCT IF(callnums.ph IS NOT NULL, norm.id, NULL)) / COUNT(DISTINCT norm.id) * 100, 1) AS pct
  FROM norm LEFT JOIN callnums USING (ph)
""").to_string(index=False))

print("\n=== join probe B: gclid / utm / campaign coverage on leads by year ===")
print(q("""
  SELECT EXTRACT(YEAR FROM create_timestamp) AS yr, COUNT(*) AS leads,
    ROUND(COUNTIF(TRIM(COALESCE(gclid1_66dad68843cd4,'')) != '') / COUNT(*) * 100, 1) AS gclid_pct,
    ROUND(COUNTIF(TRIM(COALESCE(exact_marketing_campaign_64d0b4a09e91b,'')) != '') / COUNT(*) * 100, 1) AS utm_campaign_pct,
    ROUND(COUNTIF(TRIM(COALESCE(campaign_id,'')) NOT IN ('', '0')) / COUNT(*) * 100, 1) AS crm_campaign_pct,
    ROUND(COUNTIF(TRIM(COALESCE(location_6349396e4a08d,'')) NOT IN ('','0','132732','No location provided')) / COUNT(*) * 100, 1) AS region_pct,
    ROUND(COUNTIF(TRIM(COALESCE(zipcode,'')) != '') / COUNT(*) * 100, 1) AS postcode_pct
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE EXTRACT(YEAR FROM create_timestamp) >= 2024
  GROUP BY yr ORDER BY yr
""").to_string(index=False))

print("\n=== unleashed_sales_orders + customers columns (for sales->lead join) ===")
for t in ['unleashed_sales_orders', 'unleashed_customers']:
    c = q(f"""SELECT column_name FROM `trustwarehouse.bronze.INFORMATION_SCHEMA.COLUMNS`
              WHERE table_name='{t}' ORDER BY ordinal_position""")
    print(t, "->", ", ".join(c.column_name)[:400])

print("\n=== join probe C: sales orders -> lead by customer email/name ===")
print(q("""
  WITH so AS (
    SELECT s.guid, LOWER(TRIM(c.email)) AS email
    FROM `trustwarehouse.bronze.unleashed_sales_orders` s
    LEFT JOIN `trustwarehouse.bronze.unleashed_customers` c
      ON s.customer__guid = c.guid
    WHERE TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(s.order_date, r'([0-9]+)') AS INT64)) >= '2025-07-01'),
  le AS (SELECT DISTINCT LOWER(TRIM(email_address)) AS email
         FROM `trustwarehouse.bronze.sharpspring_leads` WHERE TRIM(COALESCE(email_address,'')) != '')
  SELECT COUNT(*) AS orders_12mo,
         COUNTIF(so.email IS NOT NULL AND so.email != '') AS with_email,
         COUNTIF(le.email IS NOT NULL) AS email_matches_lead,
         ROUND(COUNTIF(le.email IS NOT NULL) / COUNT(*) * 100, 1) AS pct_matched
  FROM so LEFT JOIN le USING (email)
""").to_string(index=False))
