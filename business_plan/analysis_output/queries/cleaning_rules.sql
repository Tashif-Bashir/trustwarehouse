-- =====================================================================
-- SHARED CLEANING RULES — established Phase 1 (16 Jul 2026)
-- Every analytical query in Phases 2-6 reuses these CTEs verbatim.
-- Bronze is raw; these rules are the documented, reproducible cleaning layer.
-- =====================================================================

-- ---------- LEADS ----------
-- Exclusions: test records only (~34 rows). Phone-artefact leads
-- (^[0-9]+@trustelectricheating) are REAL enquiries (auto-created from inbound
-- calls) and are KEPT — but they carry no usable email/geo.
WITH clean_leads AS (
  SELECT *,
    DATE(create_timestamp) AS created_date,
    REGEXP_REPLACE(COALESCE(NULLIF(TRIM(phone_number),''),
                            NULLIF(TRIM(mobile_phone_number),''), ''), r'[^0-9]', '') AS phone_digits
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE NOT REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))),
                            r'zzz|\btest lead\b|testlead')
    AND NOT (email_address LIKE '%@trustelectricheating.co.uk'
             AND NOT REGEXP_CONTAINS(COALESCE(email_address,''), r'^[0-9]+@'))
),
-- normalised phone: UK 44-prefixed digits (join key to calls)
leads_norm_phone AS (
  SELECT id, CASE WHEN phone_digits LIKE '00%' THEN SUBSTR(phone_digits, 3)
                  WHEN phone_digits LIKE '0%'  THEN CONCAT('44', SUBSTR(phone_digits, 2))
                  ELSE phone_digits END AS phone44
  FROM clean_leads WHERE phone_digits != ''
),

-- ---------- GOOGLE SPEND ----------
-- GRAIN = (date, campaign_id, ad_network_type). The 31k repeated (date,campaign)
-- keys are network slices, NOT duplicates. SUM(spend_gbp) is correct;
-- NEVER dedupe on (date, campaign_id) — that destroys ~40% of real spend.
google_spend AS (
  SELECT DATE(date) AS d, campaign_id, campaign_name, spend_gbp, clicks, impressions
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
),

-- ---------- META SPEND ----------
-- clean grain (date, campaign_id); campaign NAMES drift after renames — key on id.
meta_spend AS (
  SELECT DATE(date) AS d, campaign_id, campaign_name, spend_gbp, clicks, impressions
  FROM `trustwarehouse.bronze.meta_api_campaign_daily`
),

-- ---------- BING SPEND ----------
-- Use the ACCOUNT daily report for totals (matches campaign report to the penny;
-- grain of campaign report = campaign x day x device x network — sums safe).
-- NOTE: silver_bing_spend undercounts ~18% (filter bug) — do not use silver.
bing_spend AS (
  SELECT SAFE_CAST(TimePeriod AS DATE) AS d, SAFE_CAST(Spend AS FLOAT64) AS spend_gbp,
         SAFE_CAST(Clicks AS INT64) AS clicks, SAFE_CAST(Impressions AS INT64) AS impressions
  FROM `trustwarehouse.bronze.bing_adsaccount_performance_report_daily`
),

-- ---------- UNIFIED CALLS (Wildix < 2026-07-01 <= Ascend) ----------
-- Wildix: rows = call LEGS (transfers) + some legs re-loaded across sync windows.
--   149,092 rows -> 141,435 distinct (id, flow_index) legs -> 135,760 distinct calls.
--   Dedupe legs on (id, flow_index) keeping latest load; call-level = one row per id.
-- Wildix talk seconds = talk_time (its `duration` INCLUDES ring time — never use).
-- Ascend: clean; `duration` is talk seconds; answered is a real BOOL.
unified_calls AS (
  SELECT * FROM (
    SELECT id, TIMESTAMP_MILLIS(MIN(start_time)) AS start,
           LOWER(ANY_VALUE(direction)) AS direction,
           ARRAY_AGG(_colleague_name ORDER BY talk_time DESC LIMIT 1)[OFFSET(0)] AS agent,
           ANY_VALUE(remote_phone) AS remote_number,
           SUM(talk_time) AS talk_seconds,
           MAX(talk_time) > 0 AS answered,
           'wildix' AS system
    FROM (SELECT DISTINCT id, flow_index, start_time, direction, _colleague_name,
                 talk_time, remote_phone
          FROM `trustwarehouse.bronze.wildix_calls`)
    GROUP BY id
  ) WHERE start < '2026-07-01'
  UNION ALL
  SELECT id, start, direction,
         CASE WHEN direction = 'outbound' THEN JSON_VALUE(`from`, '$.name')
              ELSE JSON_VALUE(`to`, '$.name') END AS agent,
         CASE WHEN direction = 'outbound' THEN JSON_VALUE(`to`, '$.number')
              ELSE JSON_VALUE(`from`, '$.number') END AS remote_number,
         duration AS talk_seconds, answered, 'ascend' AS system
  FROM `trustwarehouse.bronze.ascend_calls`
  WHERE start >= '2026-07-01'
),

-- ---------- SALES ORDERS (Unleashed, authoritative from Jan 2025) ----------
-- order_date is /Date(ms)/; exclude Deleted+Parked (parked = not completed sales,
-- includes known duplicates); sub_total is ex-VAT.
sales_orders AS (
  SELECT order_number, order_status,
         TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(order_date, r'([0-9]+)') AS INT64)) AS order_ts,
         SAFE_CAST(sub_total AS FLOAT64) AS sub_total_exvat,
         customer__guid
  FROM `trustwarehouse.bronze.unleashed_sales_orders`
  WHERE order_status NOT IN ('Deleted', 'Parked')
    AND SAFE_CAST(sub_total AS FLOAT64) > 0
)
SELECT 1  -- (template terminator; copy CTEs above into analysis queries)
