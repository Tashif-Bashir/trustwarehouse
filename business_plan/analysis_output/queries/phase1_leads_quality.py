"""Phase 1.1/1.2/1.3/1.7 — lead completeness trends, Yorkshire geo gap + gclid
recovery, duplicates, test-record candidates."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 240)

print("=== 1.1 monthly completeness trend (24 months) ===")
comp = q("""
  SELECT FORMAT_TIMESTAMP('%Y-%m', create_timestamp) AS month, COUNT(*) AS leads,
    ROUND(COUNTIF(TRIM(COALESCE(phone_number,''))='' AND TRIM(COALESCE(mobile_phone_number,''))='')/COUNT(*)*100,1) AS no_phone_pct,
    ROUND(COUNTIF(TRIM(COALESCE(email_address,''))='' OR email_address LIKE '%@trustelectricheating.co.uk')/COUNT(*)*100,1) AS no_real_email_pct,
    ROUND(COUNTIF(TRIM(COALESCE(zipcode,''))!='')/COUNT(*)*100,1) AS postcode_pct,
    ROUND(COUNTIF(TRIM(COALESCE(city,''))!='')/COUNT(*)*100,1) AS city_pct,
    ROUND(COUNTIF(TRIM(COALESCE(location_6349396e4a08d,'')) NOT IN ('','0','132732','No location provided'))/COUNT(*)*100,1) AS region_pct,
    ROUND(COUNTIF(TRIM(COALESCE(gclid1_66dad68843cd4,''))!='')/COUNT(*)*100,1) AS gclid_pct,
    ROUND(COUNTIF(TRIM(COALESCE(status_633ae6f6ac6fe,''))='')/COUNT(*)*100,1) AS blank_status_pct
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE create_timestamp >= '2024-08-01'
  GROUP BY month ORDER BY month
""")
print(comp.to_string(index=False))
comp.to_csv(r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data\phase1_completeness_monthly.csv', index=False)

print("\n=== 1.2 Yorkshire campaign geo gap ===")
print(q("""
  SELECT c.campaign_name, COUNT(*) AS leads,
    ROUND(COUNTIF(TRIM(COALESCE(l.zipcode,''))!='' OR TRIM(COALESCE(l.city,''))!='')/COUNT(*)*100,1) AS has_city_or_pc_pct,
    COUNTIF(TRIM(COALESCE(l.zipcode,''))='' AND TRIM(COALESCE(l.city,''))='') AS geo_null,
    COUNTIF(TRIM(COALESCE(l.zipcode,''))='' AND TRIM(COALESCE(l.city,''))=''
            AND TRIM(COALESCE(l.gclid1_66dad68843cd4,''))!='') AS geo_null_with_gclid
  FROM `trustwarehouse.bronze.sharpspring_leads` l
  JOIN `trustwarehouse.bronze.sharpspring_campaigns` c
    ON CAST(c.id AS STRING)=CAST(l.campaign_id AS STRING)
  WHERE LOWER(c.campaign_name) LIKE '%york%'
  GROUP BY 1 ORDER BY leads DESC
""").to_string(index=False))

print("\n=== same, via region picklist = Yorkshire (any campaign) ===")
print(q("""
  SELECT COUNT(*) AS yorkshire_leads,
    COUNTIF(TRIM(COALESCE(zipcode,''))='' AND TRIM(COALESCE(city,''))='') AS geo_null,
    COUNTIF(TRIM(COALESCE(zipcode,''))='' AND TRIM(COALESCE(city,''))=''
            AND TRIM(COALESCE(gclid1_66dad68843cd4,''))!='') AS geo_null_with_gclid
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE TRIM(COALESCE(location_6349396e4a08d,'')) IN ('Yorkshire and the Humber')
""").to_string(index=False))

print("\n=== 1.3 duplicate leads (same email or phone, 24mo) ===")
print(q("""
  WITH base AS (
    SELECT id, LOWER(TRIM(email_address)) AS em,
      REGEXP_REPLACE(COALESCE(phone_number, mobile_phone_number, ''), r'[^0-9]', '') AS ph
    FROM `trustwarehouse.bronze.sharpspring_leads`
    WHERE create_timestamp >= '2024-08-01')
  SELECT
    (SELECT COUNT(*) FROM base) AS leads_24mo,
    (SELECT COUNT(*) FROM (SELECT em FROM base
      WHERE em != '' AND em NOT LIKE '%@trustelectricheating.co.uk'
      GROUP BY em HAVING COUNT(*) > 1)) AS emails_with_dupes,
    (SELECT SUM(n) - COUNT(*) FROM (SELECT em, COUNT(*) n FROM base
      WHERE em != '' AND em NOT LIKE '%@trustelectricheating.co.uk'
      GROUP BY em HAVING COUNT(*) > 1)) AS excess_email_rows,
    (SELECT SUM(n) - COUNT(*) FROM (SELECT ph, COUNT(*) n FROM base
      WHERE LENGTH(ph) >= 10 GROUP BY ph HAVING COUNT(*) > 1)) AS excess_phone_rows
""").to_string(index=False))

print("\n=== 1.7 test-record candidates ===")
print(q("""
  SELECT
    COUNTIF(LOWER(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))) LIKE '%zzz%') AS zzz_names,
    COUNTIF(REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(first_name,''), COALESCE(last_name,''))), r'\\btest\\b|testlead|test lead')) AS test_names,
    COUNTIF(email_address LIKE '%@trustelectricheating.co.uk'
            AND NOT REGEXP_CONTAINS(COALESCE(email_address,''), r'^[0-9]+@')) AS staff_email_leads,
    COUNTIF(REGEXP_CONTAINS(COALESCE(email_address,''), r'^[0-9]+@trustelectricheating')) AS phone_artefact_leads
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE create_timestamp >= '2024-08-01'
""").to_string(index=False))

print("\n=== duplicate load check: exact duplicate lead ids in bronze ===")
print(q("""
  SELECT COUNT(*) - COUNT(DISTINCT id) AS duplicate_id_rows
  FROM `trustwarehouse.bronze.sharpspring_leads`
""").to_string(index=False))
