"""Phase 1 drill-down: anatomy of google 'dupes', wildix repeated ids, bing grain."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 240)

print("=== A. google: pick a duplicated (date,campaign_id), show the rows ===")
print(q("""
  WITH d AS (
    SELECT date, campaign_id, COUNT(*) n
    FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
    GROUP BY 1,2 HAVING n > 1 ORDER BY n DESC LIMIT 1)
  SELECT g.* FROM `trustwarehouse.bronze.google_ads_api_campaign_daily` g
  JOIN d USING (date, campaign_id) LIMIT 6
""").to_string(index=False))

print("\n=== A2. do google dupes double-count spend? June 2026 bronze vs dedup ===")
print(q("""
  SELECT ROUND(SUM(spend_gbp),2) AS raw_sum,
         ROUND((SELECT SUM(s) FROM (
            SELECT ANY_VALUE(spend_gbp) AS s
            FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
            WHERE DATE(date) BETWEEN '2026-06-01' AND '2026-06-30'
            GROUP BY date, campaign_id)),2) AS dedup_any_value_sum,
         ROUND((SELECT SUM(s) FROM (
            SELECT MAX(spend_gbp) AS s
            FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
            WHERE DATE(date) BETWEEN '2026-06-01' AND '2026-06-30'
            GROUP BY date, campaign_id)),2) AS dedup_max_sum
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
  WHERE DATE(date) BETWEEN '2026-06-01' AND '2026-06-30'
""").to_string(index=False))

print("\n=== A3. what distinguishes google dupe rows? _dlt_load_id? ===")
print(q("""
  WITH d AS (
    SELECT date, campaign_id
    FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
    WHERE DATE(date) = '2026-06-15'
    GROUP BY 1,2 HAVING COUNT(*) > 1 LIMIT 1)
  SELECT g.date, g.campaign_id, g.spend_gbp, g.clicks, g._dlt_load_id
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily` g JOIN d USING (date, campaign_id)
  ORDER BY g._dlt_load_id LIMIT 8
""").to_string(index=False))

print("\n=== B. wildix repeated ids: legs or load-dupes? ===")
print(q("""
  WITH d AS (
    SELECT id, COUNT(*) n FROM `trustwarehouse.bronze.wildix_calls`
    GROUP BY id HAVING n > 1 ORDER BY n DESC LIMIT 1)
  SELECT w.id, w.flow_index, w._colleague_name, w.direction, w.talk_time, w.duration, w._dlt_load_id
  FROM `trustwarehouse.bronze.wildix_calls` w JOIN d USING (id)
  ORDER BY w.flow_index LIMIT 8
""").to_string(index=False))
print(q("""
  WITH dups AS (SELECT id, COUNT(*) n, COUNT(DISTINCT flow_index) legs,
                       COUNT(DISTINCT _dlt_load_id) loads
                FROM `trustwarehouse.bronze.wildix_calls` GROUP BY id HAVING n > 1)
  SELECT COUNT(*) AS dup_ids,
         COUNTIF(legs = n) AS explained_by_flow_legs,
         COUNTIF(legs < n AND loads > 1) AS explained_by_reloads,
         COUNTIF(legs < n AND loads = 1) AS unexplained
  FROM dups
""").to_string(index=False))

print("\n=== C. bing grain check: June 2026 campaign-report sum vs account-report sum ===")
print(q("""
  SELECT
    (SELECT ROUND(SUM(SAFE_CAST(Spend AS FLOAT64)),2)
     FROM `trustwarehouse.bronze.bing_adscampaign_performance_report_daily`
     WHERE SAFE_CAST(TimePeriod AS DATE) BETWEEN '2026-06-01' AND '2026-06-30') AS campaign_report,
    (SELECT ROUND(SUM(SAFE_CAST(Spend AS FLOAT64)),2)
     FROM `trustwarehouse.bronze.bing_adsaccount_performance_report_daily`
     WHERE SAFE_CAST(TimePeriod AS DATE) BETWEEN '2026-06-01' AND '2026-06-30') AS account_report
""").to_string(index=False))
