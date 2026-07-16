"""Phase 1.4/1.5/1.6 — spend & sales quality, anomalies, platform consistency,
join attrition, Yorkshire-by-UTM check."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 240)

print("=== Yorkshire by UTM campaign (plan said ~4,000 leads) ===")
print(q("""
  SELECT COUNT(*) AS utm_yorkshire_leads,
    COUNTIF(TRIM(COALESCE(zipcode,''))='' AND TRIM(COALESCE(city,''))='') AS geo_null,
    COUNTIF(TRIM(COALESCE(zipcode,''))='' AND TRIM(COALESCE(city,''))=''
            AND TRIM(COALESCE(gclid1_66dad68843cd4,''))!='') AS geo_null_with_gclid
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE LOWER(COALESCE(exact_marketing_campaign_64d0b4a09e91b,'')) LIKE '%york%'
""").to_string(index=False))

print("\n=== spend table integrity: dupes / negatives / zeros ===")
for t, datecol, spendcol, keycols in [
    ("google_ads_api_campaign_daily", "date", "spend_gbp", "date, campaign_id"),
    ("meta_api_campaign_daily", "date", "spend_gbp", "date, campaign_id"),
    ("bing_adscampaign_performance_report_daily", "TimePeriod", "Spend", "TimePeriod, CampaignId"),
]:
    d = q(f"""
      SELECT '{t}' AS tbl,
        COUNT(*) AS rows_,
        COUNT(*) - COUNT(DISTINCT CONCAT({keycols.split(',')[0]}, '|', {keycols.split(',')[1].strip()})) AS dup_key_rows,
        COUNTIF(SAFE_CAST({spendcol} AS FLOAT64) < 0) AS negative_spend,
        ROUND(COUNTIF(SAFE_CAST({spendcol} AS FLOAT64) = 0) / COUNT(*) * 100, 1) AS zero_spend_pct
      FROM `trustwarehouse.bronze.{t}`
    """)
    print(d.to_string(index=False))

print("\n=== monthly spend row-volume continuity (step-change scan) ===")
print(q("""
  SELECT FORMAT_DATE('%Y-%m', DATE(date)) AS month,
         COUNTIF(TRUE) AS google_rows, ROUND(SUM(spend_gbp),0) AS google_spend
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
  WHERE DATE(date) >= '2024-08-01' GROUP BY month ORDER BY month
""").to_string(index=False))

print("\n=== sales orders quality ===")
print(q("""
  WITH so AS (
    SELECT order_number, order_status, SAFE_CAST(sub_total AS FLOAT64) AS sub_total,
      TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(order_date, r'([0-9]+)') AS INT64)) AS od
    FROM `trustwarehouse.bronze.unleashed_sales_orders`)
  SELECT COUNT(*) AS orders,
    COUNT(*) - COUNT(DISTINCT order_number) AS dup_order_numbers,
    COUNTIF(sub_total <= 0) AS zero_or_neg_subtotal,
    COUNTIF(od > CURRENT_TIMESTAMP()) AS future_dates,
    COUNTIF(sub_total > 40000) AS over_40k
  FROM so
""").to_string(index=False))
print(q("""
  SELECT order_status, COUNT(*) n,
         ROUND(SUM(SAFE_CAST(sub_total AS FLOAT64)),0) AS subtotal
  FROM `trustwarehouse.bronze.unleashed_sales_orders` GROUP BY 1 ORDER BY n DESC
""").to_string(index=False))

print("\n=== calls: duplicate ids + weekly volume across cutover ===")
print(q("""
  SELECT 'wildix' AS sys, COUNT(*) - COUNT(DISTINCT id) AS dup_ids FROM `trustwarehouse.bronze.wildix_calls`
  UNION ALL
  SELECT 'ascend', COUNT(*) - COUNT(DISTINCT id) FROM `trustwarehouse.bronze.ascend_calls`
""").to_string(index=False))
print(q("""
  WITH u AS (
    SELECT DATE_TRUNC(DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London'), WEEK(MONDAY)) AS wk, COUNT(*) n
    FROM `trustwarehouse.bronze.wildix_calls`
    WHERE TIMESTAMP_MILLIS(start_time) >= '2026-05-25' AND TIMESTAMP_MILLIS(start_time) < '2026-07-01'
    GROUP BY wk
    UNION ALL
    SELECT DATE_TRUNC(DATE(start, 'Europe/London'), WEEK(MONDAY)), COUNT(*)
    FROM `trustwarehouse.bronze.ascend_calls` GROUP BY 1)
  SELECT wk, SUM(n) AS calls FROM u GROUP BY wk ORDER BY wk
""").to_string(index=False))

print("\n=== join attrition: leads with identifiable PAID platform, by month ===")
print(q("""
  SELECT FORMAT_TIMESTAMP('%Y-%m', l.create_timestamp) AS month, COUNT(*) AS leads,
    ROUND(COUNTIF(LOWER(COALESCE(c.campaign_name,'')) IN
      ('google ads','google search','gogle search','facebook','bing ads','bing search','google shopping'))
      / COUNT(*) * 100, 1) AS paid_platform_pct
  FROM `trustwarehouse.bronze.sharpspring_leads` l
  LEFT JOIN `trustwarehouse.bronze.sharpspring_campaigns` c
    ON CAST(c.id AS STRING) = CAST(l.campaign_id AS STRING)
  WHERE l.create_timestamp >= '2025-01-01'
  GROUP BY month ORDER BY month LIMIT 6
""").to_string(index=False))
