"""Build the marketing data mart: bronze/silver/gold -> marketing_workspace.

WHY THIS EXISTS
---------------
Marketing needs to query lead, campaign and call data, and to write their own
tables (upload logs, staging) for the Google Ads conversion-upload automation.

The obvious design - a dataset of VIEWS over bronze - has a trap. Views can only
read their sources because bronze/silver/gold carry an authorized-DATASET grant,
and that grant trusts *any* view in the dataset, including ones created later by
someone else. So write access to such a dataset is equivalent to read access
over the entire warehouse: a view authored there over gold.gold_sales_reconciled
returns every sale and all revenue.

This mart holds plain TABLES instead. Nothing here is an authorized view, so
marketing can create, drop and rewrite freely with no path back to the layers -
even as owners of the dataset. The trade-off is that these are snapshots: run
this on a timer, and check `_sync_log` for how fresh they are.

Re-runnable and self-healing: CREATE OR REPLACE, so anything the team drops
comes back on the next run.

Usage:  python scripts/sync_marketing_workspace.py
"""

from google.cloud import bigquery

PROJECT = "trustwarehouse"
DST = "marketing_workspace"

client = bigquery.Client(project=PROJECT)


# ── helpers ───────────────────────────────────────────────────────────────────

def norm_phone(col: str) -> str:
    """Reduce a phone number to digits with a 44 country code.

    Matches shared/phone.py and the normalise_phone dbt macro. The CRM stores
    +447442172217 or 07936804647; the phone system stores 447904300630. Without
    a common key the two never join.
    """
    d = f"REGEXP_REPLACE({col}, r'[^0-9]', '')"
    return (
        "CASE "
        f"WHEN {col} IS NULL OR {d} = '' THEN NULL "
        f"WHEN STARTS_WITH({d}, '00') THEN SUBSTR({d}, 3) "
        f"WHEN STARTS_WITH({d}, '0')  THEN CONCAT('44', SUBSTR({d}, 2)) "
        f"ELSE {d} END"
    )


def utm(param: str) -> str:
    """Pull a UTM parameter out of the landing page URL and tidy it.

    '+' means space in a query string, a handful of rows are %20-encoded, and
    everything is lowercased so 'Google' and 'google' don't split a report.
    """
    return (
        "NULLIF(LOWER(TRIM(REPLACE(REPLACE("
        f"REGEXP_EXTRACT(url, r'[?&]{param}=([^&#]*)')"
        ", '+', ' '), '%20', ' '))), '')"
    )


# ── straight copies of non-ad tables (hardcoded — small, stable list) ───────

RAW_COPIES = [
    "sharpspring_campaigns",
]

# ── ad platform tables: RUNTIME DISCOVERY, not a hardcoded list ─────────────
# Owner ruling (11 Aug 2026): marketing_workspace must carry ALL bronze tables
# from the three ad platforms, not a curated subset. A hardcoded list silently
# drifts as Airbyte adds tables. Verified prefixes in bronze (inspected via
# __TABLES__, not assumed): Google Ads lands as `google_ads%` (dlt, includes
# the `google_ads_api_` family), Bing as `bing_ads%`. Meta/Facebook does NOT
# land as `facebook_` — it lands as `meta_api_%`. Mart table name = bronze
# table name, unchanged, so CREATE OR REPLACE makes duplication structurally
# impossible: same name in, same name out, every run.

# Cost (11 Aug 2026 inventory): 17 tables, ~0.36GB raw, ~0.46GB billed after
# the 10MB-per-query floor (11 of the 17 tables are tiny lookup/label tables
# that each round up to 10MB). That is under the ~2GB/run threshold, so this
# stays plain CREATE OR REPLACE copies — no row-count skip-guard needed here
# (GSC_STITCHED below already has one, for its much larger tables). Hourly for
# a month: ~0.46GB * 24 * 30 / 1024 = ~0.32TB * £4.7/TB ≈ £1.55/month. Re-check
# this threshold if Airbyte lands a new large ad report table.

AD_PLATFORM_PREFIXES = ["google_ads%", "meta_api%", "bing_ads%", "bing_direct%"]


def discover_ad_tables() -> list[tuple[str, int, int]]:
    """Return (table_id, row_count, size_bytes) for every bronze ad table.

    Reads __TABLES__ metadata only — no data scanned, zero-cost check.
    """
    where = " OR ".join(f"table_id LIKE '{p}'" for p in AD_PLATFORM_PREFIXES)
    rows = client.query(f"""
        SELECT table_id, row_count, size_bytes
        FROM `{PROJECT}.bronze.__TABLES__`
        WHERE {where}
        ORDER BY table_id
    """).result()
    return [(r.table_id, r.row_count, r.size_bytes) for r in rows]


# ── Search Console stitched tables (renamed, same region) ───────────────────
# The one-off 16-month API backfill in bronze (gsc_search_analytics_backfill /
# gsc_daily_totals_backfill) stopped by design once Google's NATIVE bulk
# export (dataset `searchconsole`, europe-west2, tables
# searchdata_url_impression / searchdata_site_impression) started landing
# daily rows on 10 Aug 2026. Ananthu patched the one missing seam day
# (2026-08-08) into the backfill via the API on 20 Aug 2026, so: backfill
# covers <= GSC_STITCH_DATE, native covers > GSC_STITCH_DATE, no gap. These
# two tables are now a UNION ALL of both sources onto the backfill's schema,
# not a plain copy. Both sources are europe-west2, same as the mart, so this
# is still plain CREATE TABLE AS SELECT - not the cross-region dataframe path
# used for app.sales (US). The mart drops the "_backfill" suffix; marketing
# shouldn't care about provenance.
#
# Native schema notes (checked via INFORMATION_SCHEMA 20 Aug 2026):
#   - data_date -> date, url -> page (already full URLs, matches backfill)
#   - device is already UPPERCASE ('MOBILE'/'DESKTOP'/'TABLET') and country
#     already lowercase ISO3 ('gbr' etc.) in both sources - no casing fix
#     needed, checked distinct values on both sides
#   - search_type must be filtered to 'WEB': the API backfill defaults to
#     web-only (no type param sent in ingestion/gsc/client.py), but the
#     native export also carries IMAGE rows which would inflate
#     clicks/impressions if left in
#   - average position = SUM(sum_position)/SUM(impressions) + 1 for
#     searchdata_url_impression, SUM(sum_top_position)/SUM(impressions) + 1
#     for searchdata_site_impression (GSC convention: the export stores a
#     0-indexed position sum, not an average - PARENT BRIEF CONFIRMED this
#     is the right derivation). Validated 20 Aug 2026 by comparing the seam:
#     site-level derived 08-09 (36 clicks / 6,573 impr / pos 22.4) sits
#     smoothly between 08-08 backfill (31 / 6,247 / 22.3) and 08-10 native
#     (55 / 6,849 / 21.4) - no discontinuity.
#   - searchdata_url_impression is NOT unique per (date, query, url, device,
#     country) - multiple rows can exist per key for different
#     search-appearance flags (is_amp_top_stories etc., seen mostly on
#     anonymized/NULL-query rows) - must GROUP BY and SUM before deriving
#     ctr/position, or clicks/impressions silently overcount (4,037 raw rows
#     vs 3,056 distinct keys on 08-09 alone)
#   - is_anonymized_query=true rows carry query=NULL - kept in, matching real
#     GSC behaviour; the old API backfill simply never had these rows, so
#     NULL-query volume is new starting 2026-08-09 - noted here, not hidden
#   - url_impression's aggregated impressions for 08-09 (7,700) do NOT equal
#     site_impression's 08-09 total (6,573) even though clicks match exactly
#     (36 = 36) - a known GSC bulk-export quirk (the two export tables
#     aggregate differently internally), not a bug introduced here;
#     gsc_search_analytics summed was never guaranteed to equal
#     gsc_daily_totals even on the old API-backfill side
#
# The big table is ~520MB and sources change at most daily, so the hourly run
# skips the rebuild when neither source has moved - see gsc_source_signature()
# below. Because these tables are now derived (GROUP BY + UNION), destination
# row count no longer equals source row count, so the skip-guard can't compare
# row counts directly the way the plain-copy GA4 skip-guard pattern does; it
# instead persists a signature (row_count + last_modified_time per source
# table) in `{DST}._gsc_sync_state` and skips only when that signature is
# unchanged. Still metadata-only (__TABLES__), zero-cost when skipping.

GSC_STITCH_DATE = "2026-08-08"  # backfill <= this date; native > this date

GSC_SOURCE_TABLES = [
    ("bronze", "gsc_search_analytics_backfill"),
    ("bronze", "gsc_daily_totals_backfill"),
    ("searchconsole", "searchdata_url_impression"),
    ("searchconsole", "searchdata_site_impression"),
]

GSC_SEARCH_ANALYTICS_STITCHED = f"""
SELECT date, query, page, device, country, clicks, impressions, ctr, position, _backfilled_at
FROM (
  SELECT
    DATE(date) AS date, query, page, device, country, clicks, impressions,
    ctr, position, _backfilled_at
  FROM `{PROJECT}.bronze.gsc_search_analytics_backfill`
  WHERE DATE(date) <= '{GSC_STITCH_DATE}'
  UNION ALL
  SELECT
    data_date AS date,
    query,
    url AS page,
    device,
    country,
    SUM(clicks) AS clicks,
    SUM(impressions) AS impressions,
    SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
    SAFE_DIVIDE(SUM(sum_position), SUM(impressions)) + 1 AS position,
    CAST(NULL AS TIMESTAMP) AS _backfilled_at
  FROM `{PROJECT}.searchconsole.searchdata_url_impression`
  WHERE search_type = 'WEB' AND data_date > '{GSC_STITCH_DATE}'
  GROUP BY data_date, query, page, device, country
)
"""

GSC_DAILY_TOTALS_STITCHED = f"""
SELECT date, clicks, impressions, ctr, position, _backfilled_at
FROM (
  SELECT DATE(date) AS date, clicks, impressions, ctr, position, _backfilled_at
  FROM `{PROJECT}.bronze.gsc_daily_totals_backfill`
  WHERE DATE(date) <= '{GSC_STITCH_DATE}'
  UNION ALL
  SELECT
    data_date AS date,
    SUM(clicks) AS clicks,
    SUM(impressions) AS impressions,
    SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
    SAFE_DIVIDE(SUM(sum_top_position), SUM(impressions)) + 1 AS position,
    CAST(NULL AS TIMESTAMP) AS _backfilled_at
  FROM `{PROJECT}.searchconsole.searchdata_site_impression`
  WHERE search_type = 'WEB' AND data_date > '{GSC_STITCH_DATE}'
  GROUP BY data_date
)
"""

GSC_STITCHED = [
    ("gsc_search_analytics", GSC_SEARCH_ANALYTICS_STITCHED),
    ("gsc_daily_totals", GSC_DAILY_TOTALS_STITCHED),
]


def gsc_source_signature() -> str:
    """Metadata-only fingerprint of every GSC source table (bronze backfill +
    native searchconsole export), so the hourly run can tell whether either
    side moved without scanning any table data.
    """
    rows = list(client.query(f"""
        SELECT 'bronze' AS ds, table_id, row_count, last_modified_time
        FROM `{PROJECT}.bronze.__TABLES__`
        WHERE table_id IN ('gsc_search_analytics_backfill', 'gsc_daily_totals_backfill')
        UNION ALL
        SELECT 'searchconsole', table_id, row_count, last_modified_time
        FROM `{PROJECT}.searchconsole.__TABLES__`
        WHERE table_id IN ('searchdata_url_impression', 'searchdata_site_impression')
    """).result())
    return "|".join(
        f"{r.ds}.{r.table_id}:{r.row_count}:{r.last_modified_time}"
        for r in sorted(rows, key=lambda r: (r.ds, r.table_id))
    )


# ── derived tables, in dependency order ──────────────────────────────────────

SHARPSPRING_LEADS = f"""
SELECT
  id AS lead_id,
  DATE(create_timestamp) AS created_date,
  create_timestamp,
  lead_status,
  status_633ae6f6ac6fe AS domestic_lead_status,
  domestic_lead_status___1___6a0f07b50b5d2 AS water_lead_status,
  domestic_lead_status___1___64256c8b9804a AS commercial_lead_status,
  chc_lead_status_65c4eb8949156 AS chc_lead_status,
  lead_warmth___1___69ea236712886 AS enquiry_type,
  appointment_booked_5ae8cb01a35c6 AS appointment_booked,
  appointment_time___date_5ae8ca2f532bc AS appointment_time,
  appointment_made_by_65e1a90253305 AS appointment_made_by,
  type_of_appointment_606ee2f254f4d AS type_of_appointment,
  appointment_status_637f8d6fa1096 AS appointment_status,
  date_time_appointment_booked_687fabb701341 AS appointment_booked_at,
  commercial_follow_up_date_6703f8f36026e AS commercial_follow_up_date,
  commercial_appointment_date_and_time_67051136642d9 AS commercial_appointment_date,
  location_6349396e4a08d AS marketing_region,
  city,
  REGEXP_EXTRACT(UPPER(TRIM(zipcode)), r'^[A-Z]{{1,2}}[0-9][A-Z0-9]?') AS postcode_district,
  owner_id,
  campaign_id,
  exact_marketing_campaign_64d0b4a09e91b AS utm_campaign,
  COALESCE(
    NULLIF(TRIM(exact_marketing_url_64d0bebced518), ''),
    NULLIF(TRIM(page_submitted_5af30a9090796), '')
  ) AS marketing_url,
  gclid1_66dad68843cd4 AS gclid,
  tracking_id,
  title,
  first_name,
  last_name,
  TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))) AS customer_name,
  company_name,
  email_address AS email,
  opt_out_of_marketing_emails_only_400000049514498 AS opted_out_of_marketing_emails,
  phone_number AS phone,
  mobile_phone_number AS mobile_phone,
  NULLIF(TRIM(alternative_phone_number_5af46947e2fc1), '') AS alternative_phone,
  {norm_phone('phone_number')} AS phone_normalised,
  {norm_phone('mobile_phone_number')} AS mobile_normalised,
  NULLIF(TRIM(description), '') AS description
FROM `{PROJECT}.bronze.sharpspring_leads`
-- Leads deleted in the CRM stay in bronze forever (merge-only sync) but must
-- not count anywhere downstream (owner ruling 20 Aug 2026) — the sweep in
-- ingestion/sharpspring/deletions.py maintains the junk table.
WHERE CAST(id AS STRING) NOT IN (SELECT id FROM `{PROJECT}.bronze.sharpspring_leads_deleted`)
"""

LEAD_ATTRIBUTION = f"""
WITH src AS (
  SELECT
    id AS lead_id,
    DATE(create_timestamp) AS created_date,
    create_timestamp,
    -- Exact Marketing URL first; fall back to the Page Submitted field, which
    -- often carries the full tagged URL when Exact Marketing URL is empty
    -- (18 Aug 2026: rescued ~9% of leads whose UTMs were sitting unparsed —
    -- found by Ananthu comparing CRM values against the warehouse)
    COALESCE(
      NULLIF(TRIM(exact_marketing_url_64d0bebced518), ''),
      NULLIF(TRIM(page_submitted_5af30a9090796), '')
    ) AS url,
    CASE
      WHEN NULLIF(TRIM(exact_marketing_url_64d0bebced518), '') IS NOT NULL THEN 'exact_marketing_url'
      WHEN NULLIF(TRIM(page_submitted_5af30a9090796), '') IS NOT NULL THEN 'page_submitted'
    END AS url_source,
    -- Meta ad links carry an explicit ?ad_id=<numeric> param since ~18 Aug 2026
    -- (see v_meta_lead_ad_match's ad_id_param method). Parsed here so the raw
    -- lead_attribution table exposes it without every consumer re-deriving it.
    REGEXP_EXTRACT(
      COALESCE(
        NULLIF(TRIM(exact_marketing_url_64d0bebced518), ''),
        NULLIF(TRIM(page_submitted_5af30a9090796), '')
      ), r'[?&]ad_id=([0-9]+)'
    ) AS ad_id,
    -- Lead-magnet / source label the lead came in against (e.g. "2022 Guide
    -- Download", "Book Consultation", "responseIQ: googlecpc Widget ..."),
    -- requested by Ananthu 20 Aug 2026, owner approved.
    NULLIF(TRIM(description), '') AS description,
    NULLIF(NULLIF(LOWER(TRIM(exact_marketing_campaign_64d0b4a09e91b)), ''), '/url')
      AS crm_campaign_field,
    campaign_id,
    location_6349396e4a08d AS marketing_region,
    city,
    REGEXP_EXTRACT(UPPER(TRIM(zipcode)), r'^[A-Z]{{1,2}}[0-9][A-Z0-9]?') AS postcode_district,
    lead_warmth___1___69ea236712886 AS enquiry_type,
    lead_status,
    status_633ae6f6ac6fe AS domestic_lead_status,
    TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))) AS customer_name,
    company_name,
    email_address AS email,
    opt_out_of_marketing_emails_only_400000049514498 AS opted_out_of_marketing_emails,
    phone_number AS phone,
    mobile_phone_number AS mobile_phone
  FROM `{PROJECT}.bronze.sharpspring_leads`
  -- CRM-deleted leads excluded (owner ruling 20 Aug 2026, same as above)
  WHERE CAST(id AS STRING) NOT IN (SELECT id FROM `{PROJECT}.bronze.sharpspring_leads_deleted`)
),
parsed AS (
  SELECT
    s.*,
    {utm('utm_source')} AS utm_source,
    {utm('utm_medium')} AS utm_medium,
    {utm('utm_campaign')} AS utm_campaign_url,
    {utm('utm_content')} AS utm_content,
    {utm('utm_term')} AS utm_term,
    {utm('utm_adgroup')} AS utm_adgroup,
    {utm('utm_matchtype')} AS utm_matchtype,
    REGEXP_EXTRACT(url, r'[?&]gad_campaignid=([0-9]+)') AS google_campaign_id,
    CASE
      WHEN REGEXP_CONTAINS(url, r'[?&]gclid=')   THEN 'gclid'
      WHEN REGEXP_CONTAINS(url, r'[?&]gbraid=')  THEN 'gbraid'
      WHEN REGEXP_CONTAINS(url, r'[?&]wbraid=')  THEN 'wbraid'
      WHEN REGEXP_CONTAINS(url, r'[?&]fbclid=')  THEN 'fbclid'
      WHEN REGEXP_CONTAINS(url, r'[?&]msclkid=') THEN 'msclkid'
    END AS click_id_type,
    NET.HOST(url) AS landing_host,
    NULLIF(REGEXP_EXTRACT(REGEXP_REPLACE(url, r'^https?://[^/]+', ''), r'^[^?#]*'), '')
      AS landing_path
  FROM src s
),
joined AS (
  SELECT
    p.*,
    camp.campaign_name AS crm_channel,
    g.campaign_name AS google_campaign_name
  FROM parsed p
  LEFT JOIN `{PROJECT}.bronze.sharpspring_campaigns` camp
    ON CAST(camp.id AS STRING) = CAST(p.campaign_id AS STRING)
  LEFT JOIN (
    SELECT DISTINCT CAST(campaign_id AS STRING) AS campaign_id, campaign_name
    FROM `{PROJECT}.bronze.google_ads_api_campaign_daily`
  ) g ON g.campaign_id = p.google_campaign_id
)
SELECT
  lead_id,
  created_date,
  create_timestamp,
  CASE
    WHEN REGEXP_CONTAINS(utm_source, r'facebook|instagram|meta|^fb$') THEN 'Meta'
    WHEN REGEXP_CONTAINS(utm_source, r'google')                       THEN 'Google'
    WHEN REGEXP_CONTAINS(utm_source, r'bing|microsoft|msn')           THEN 'Bing'
    WHEN utm_source IS NOT NULL                                       THEN 'Other'
    WHEN crm_channel IN ('Facebook')                                  THEN 'Meta'
    WHEN crm_channel IN ('Google Ads', 'Google Search')               THEN 'Google'
    WHEN crm_channel IN ('Bing Ads', 'Bing Search')                   THEN 'Bing'
    WHEN crm_channel = 'Direct Traffic'                               THEN 'Direct'
    WHEN crm_channel IN ('Email', 'Word of Mouth')                    THEN crm_channel
    ELSE 'Unknown'
  END AS platform,
  utm_source,
  utm_medium,
  COALESCE(utm_campaign_url, crm_campaign_field) AS utm_campaign,
  CASE
    WHEN utm_campaign_url   IS NOT NULL THEN 'url'
    WHEN crm_campaign_field IS NOT NULL THEN 'crm field'
  END AS utm_campaign_source,
  utm_content,
  utm_term,
  utm_adgroup,
  utm_matchtype,
  google_campaign_id,
  google_campaign_name,
  click_id_type,
  click_id_type IS NOT NULL AS is_paid_click,
  utm_source IS NOT NULL OR utm_campaign_url IS NOT NULL AS has_utm,
  NULLIF(customer_name, '') AS customer_name,
  company_name,
  NULLIF(email, '') AS email,
  opted_out_of_marketing_emails,
  phone,
  mobile_phone,
  {norm_phone('phone')} AS phone_normalised,
  url AS marketing_url,
  url_source,
  ad_id,
  description,
  landing_host,
  landing_path,
  crm_channel,
  marketing_region,
  city,
  postcode_district,
  enquiry_type,
  lead_status,
  domestic_lead_status,
  TRIM(domestic_lead_status) IN ('Appointment', 'Appointment Cancelled', 'WhatsApp Appointment')
    AS is_appointment
FROM joined
"""

# built from the table written moments earlier in this same run
LEADS_PER_DAY = f"""
SELECT
  created_date AS date,
  crm_channel AS campaign_name,
  marketing_region,
  COUNT(*) AS leads,
  COUNTIF(is_appointment) AS appointments,
  platform,
  utm_source,
  utm_campaign
FROM `{PROJECT}.{DST}.lead_attribution`
GROUP BY date, campaign_name, marketing_region, platform, utm_source, utm_campaign
"""

SPEND_PER_DAY = f"""
SELECT DATE(date) AS date, 'Google' AS platform, ROUND(SUM(spend_gbp), 2) AS spend_gbp,
       SUM(clicks) AS clicks, SUM(impressions) AS impressions
FROM `{PROJECT}.bronze.google_ads_api_campaign_daily` GROUP BY 1
UNION ALL
SELECT DATE(date), 'Meta', ROUND(SUM(spend_gbp), 2), SUM(clicks), SUM(impressions)
FROM `{PROJECT}.bronze.meta_api_campaign_daily` GROUP BY 1
UNION ALL
-- Bing from the DIRECT API sync (3 Sep 2026, replaced Airbyte): delete-then-
-- insert loads mean no duplicate-sync rows, which also fixes the long-standing
-- double-count this arm had when it summed raw Airbyte bronze.
SELECT SAFE_CAST(TimePeriod AS DATE), 'Bing', ROUND(SUM(SAFE_CAST(Spend AS FLOAT64)), 2),
       SUM(SAFE_CAST(Clicks AS INT64)), SUM(SAFE_CAST(Impressions AS INT64))
FROM `{PROJECT}.bronze.bing_direct_account_performance_report_daily` GROUP BY 1
"""

CALLS_PER_DAY = f"""
SELECT
  DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London') AS date,
  EXTRACT(HOUR FROM TIMESTAMP_MILLIS(start_time) AT TIME ZONE 'Europe/London') AS hour_of_day,
  FORMAT_TIMESTAMP('%A', TIMESTAMP_MILLIS(start_time), 'Europe/London') AS day_of_week,
  LOWER(direction) AS direction,
  phone_system,
  COUNT(*) AS calls,
  COUNTIF(call_status = 'COMPLETED') AS answered_calls,
  COUNTIF(call_status != 'COMPLETED') AS missed_calls,
  ROUND(AVG(duration_seconds)) AS avg_duration_seconds,
  ROUND(SUM(talk_time_seconds) / 60.0) AS total_talk_time_minutes
FROM `{PROJECT}.silver.silver_calls_unified`
WHERE UPPER(direction) IN ('INBOUND', 'OUTBOUND')
GROUP BY date, hour_of_day, day_of_week, direction, phone_system
"""

# app.sales lives in the US multi-region while the mart is europe-west2, so this
# one cannot be a CREATE TABLE AS SELECT - BigQuery will not query across
# regions. It is pulled into memory and loaded back (750 rows, trivial).
# Free-text fields (note, void_reason, cancel_reason) are left out: marketing
# needs the revenue, not internal commentary on individual customers.
SALES_US = """
SELECT
  sale_id,
  lead_id,
  customer_name,
  postcode,
  sale_date,
  sale_type,
  COALESCE(heating_amount, 0) AS heating_amount,
  COALESCE(water_amount, 0)   AS water_amount,
  COALESCE(chc_amount, 0)     AS chc_amount,
  ROUND(COALESCE(heating_amount,0) + COALESCE(water_amount,0)
        + COALESCE(chc_amount,0), 2) AS total_amount,
  sold_by,
  product_bought,
  source,
  status,
  entered_by,
  created_at
FROM `trustwarehouse.app.sales`
WHERE customer_name NOT LIKE 'Zzz Testlead%'
"""

SALES_RECONCILED = f"""
SELECT
  lead_id, customer_name, rep, team, sale_date, sale_month,
  amount_ex_vat, is_water, amount_to_target, source,
  is_provisional, is_unattributed
FROM `{PROJECT}.gold.gold_sales_reconciled`
"""

# Revenue with the marketing attribution already joined on, so "what did this
# campaign actually earn" is one query rather than a join people get wrong.
# Sales whose lead is unknown still appear, with NULL platform/campaign, so the
# revenue total always reconciles to sales_reconciled.
SALES_ATTRIBUTED = f"""
SELECT
  s.lead_id,
  s.customer_name,
  s.sale_date,
  s.sale_month,
  s.amount_ex_vat,
  s.is_water,
  s.rep,
  s.team,
  a.platform,
  a.utm_campaign,
  a.utm_source,
  a.utm_content,
  a.click_id_type,
  a.crm_channel,
  a.marketing_region,
  a.created_date AS lead_created_date,
  DATE_DIFF(s.sale_date, a.created_date, DAY) AS days_lead_to_sale
FROM `{PROJECT}.gold.gold_sales_reconciled` s
LEFT JOIN `{PROJECT}.{DST}.lead_attribution` a
  ON CAST(a.lead_id AS STRING) = CAST(s.lead_id AS STRING)
"""

LEAD_CALLS = f"""
SELECT
  call_id,
  lead_id,
  call_at,
  call_date,
  call_hour,
  call_dow_name,
  NULLIF(TRIM(CONCAT(COALESCE(lead_first_name, ''), ' ', COALESCE(lead_last_name, ''))), '')
    AS customer_name,
  remote_phone,
  CASE
    WHEN remote_phone IS NULL OR REGEXP_REPLACE(remote_phone, r'[^0-9]', '') = '' THEN NULL
    WHEN STARTS_WITH(REGEXP_REPLACE(remote_phone, r'[^0-9]', ''), '00')
      THEN SUBSTR(REGEXP_REPLACE(remote_phone, r'[^0-9]', ''), 3)
    WHEN STARTS_WITH(REGEXP_REPLACE(remote_phone, r'[^0-9]', ''), '0')
      THEN CONCAT('44', SUBSTR(REGEXP_REPLACE(remote_phone, r'[^0-9]', ''), 2))
    ELSE REGEXP_REPLACE(remote_phone, r'[^0-9]', '')
  END AS remote_phone_normalised,
  LOWER(direction) AS direction,
  call_status,
  call_type,
  duration_seconds,
  talk_time_seconds,
  wait_time_seconds,
  participant_count,
  call_seq,
  is_first_call,
  is_qualified_call,
  lead_created_at,
  lead_age_at_call_minutes,
  lead_age_bucket,
  lead_platform,
  lead_crm_platform,
  lead_utm_platform,
  lead_campaign_id,
  lead_customer_type,
  lead_qc_flag,
  lead_appointment_booked,
  lead_appointment_date,
  lead_appointment_booked_at,
  appt_within_1h,
  appt_within_24h,
  appt_within_48h,
  mins_to_appt_after_call
FROM `{PROJECT}.gold.gold_lead_calls`
"""

# Meta creative performance — one row per date x ad, joined to the ACTIVE-only
# creative fetch (LEFT JOIN: historical ads keep NULL creative fields, never
# dropped). JSON shapes confirmed against real rows 11 Aug 2026, see
# business_plan/analysis_output/data/meta_ad_level_probe.md:
#   - actions / cost_per_action_type are JSON arrays of {action_type, value}
#   - four lead-shaped action_types co-occur with IDENTICAL values on every
#     converting row (lead, onsite_web_lead, offsite_lead_add_20_s_calls,
#     offsite_conversion.fb_pixel_lead) - action_type = 'lead' only, or spend
#     gets multiply-counted 4x on results
#   - object_story_spec.video_data (object) -> video; .link_data (object) ->
#     image/link; landing URL is video_data.call_to_action.value.link OR
#     link_data.link; asset_feed_spec.link_urls is empty account-wide, not used
# Scalar subqueries over UNNEST(JSON_EXTRACT_ARRAY(...)) return NULL cleanly
# when the array is NULL/empty or the action_type is absent from that row.
#
# 11 Aug 2026 follow-up: bronze.meta_api_ad_creatives now covers ALL statuses
# (was ACTIVE-only, 150 rows -> now 3,063), and two new dims landed —
# meta_api_campaigns, meta_api_adsets. Added campaign_status/adset_status/
# ad_status (effective_status: reflects inherited pauses, e.g. an ad shows
# paused if its adset or campaign is paused even if the ad object itself is
# still "active" — the truthful field per the coordinator's ruling).
def _ad_copy_cols(alias: str) -> str:
    """Ad copy columns parsed from the creative specs (18 Aug 2026, for
    marketing's copy QC — typos, URL params, variant checks).

    Flexible-format ads carry text as arrays in asset_feed_spec (bodies /
    titles / descriptions — Meta's UI calls these "Primary text" and
    "Headline (ad settings)"); classic ads carry single values in
    object_story_spec.link_data or .video_data. primary_text/headline/
    description give the first (shown) value from whichever exists;
    *_all give every variant, ' | '-joined, for side-by-side QC.
    """
    afs = f"NULLIF({alias}.asset_feed_spec, 'null')"
    oss = f"{alias}.object_story_spec"
    def arr(path: str) -> str:
        return (
            f"ARRAY(SELECT JSON_VALUE(x, '$.text') "
            f"FROM UNNEST(JSON_EXTRACT_ARRAY({afs}, '$.{path}')) x)"
        )
    return f"""
  COALESCE(
    (SELECT JSON_VALUE(x, '$.text')
       FROM UNNEST(JSON_EXTRACT_ARRAY({afs}, '$.bodies')) x LIMIT 1),
    JSON_VALUE({oss}, '$.link_data.message'),
    JSON_VALUE({oss}, '$.video_data.message')
  ) AS primary_text,
  COALESCE(
    (SELECT JSON_VALUE(x, '$.text')
       FROM UNNEST(JSON_EXTRACT_ARRAY({afs}, '$.titles')) x LIMIT 1),
    JSON_VALUE({oss}, '$.link_data.name'),
    JSON_VALUE({oss}, '$.video_data.title')
  ) AS headline,
  COALESCE(
    (SELECT JSON_VALUE(x, '$.text')
       FROM UNNEST(JSON_EXTRACT_ARRAY({afs}, '$.descriptions')) x LIMIT 1),
    JSON_VALUE({oss}, '$.link_data.description')
  ) AS description,
  NULLIF(ARRAY_TO_STRING({arr('bodies')}, ' | '), '') AS primary_text_all,
  NULLIF(ARRAY_TO_STRING({arr('titles')}, ' | '), '') AS headline_all,
  NULLIF(ARRAY_TO_STRING({arr('descriptions')}, ' | '), '') AS description_all,"""


META_CREATIVE_PERFORMANCE = f"""
SELECT
  CAST(d.date AS DATE) AS date,
  d.campaign_id,
  d.campaign_name,
  camp.effective_status AS campaign_status,
  d.adset_name,
  adset.effective_status AS adset_status,
  d.ad_id,
  d.ad_name,
  c.effective_status AS ad_status,
  c.creative_id,
  c.creative_name,
  CASE
    WHEN JSON_QUERY(c.object_story_spec, '$.video_data') IS NOT NULL THEN 'video'
    WHEN JSON_QUERY(c.object_story_spec, '$.link_data')  IS NOT NULL THEN 'image/link'
    WHEN c.object_story_spec IS NOT NULL                              THEN 'other'
  END AS creative_format,
  COALESCE(
    JSON_VALUE(c.object_story_spec, '$.video_data.call_to_action.value.link'),
    JSON_VALUE(c.object_story_spec, '$.link_data.link')
  ) AS landing_page_url,
{_ad_copy_cols('c')}
  d.impressions,
  d.spend_gbp AS spend,
  d.reach,
  d.frequency,
  d.cpm,
  d.cpc,
  d.inline_link_clicks AS link_clicks,
  d.cost_per_inline_link_click AS cost_per_link_click,
  (SELECT SAFE_CAST(JSON_VALUE(a, '$.value') AS FLOAT64)
     FROM UNNEST(JSON_EXTRACT_ARRAY(NULLIF(d.actions, ''))) AS a
    WHERE JSON_VALUE(a, '$.action_type') = 'lead') AS results,
  (SELECT SAFE_CAST(JSON_VALUE(a, '$.value') AS FLOAT64)
     FROM UNNEST(JSON_EXTRACT_ARRAY(NULLIF(d.cost_per_action_type, ''))) AS a
    WHERE JSON_VALUE(a, '$.action_type') = 'lead') AS cost_per_result,
  (SELECT SAFE_CAST(JSON_VALUE(a, '$.value') AS FLOAT64)
     FROM UNNEST(JSON_EXTRACT_ARRAY(NULLIF(d.actions, ''))) AS a
    WHERE JSON_VALUE(a, '$.action_type') = 'landing_page_view') AS landing_page_views,
  (SELECT SAFE_CAST(JSON_VALUE(a, '$.value') AS FLOAT64)
     FROM UNNEST(JSON_EXTRACT_ARRAY(NULLIF(d.cost_per_action_type, ''))) AS a
    WHERE JSON_VALUE(a, '$.action_type') = 'landing_page_view') AS cost_per_landing_page_view,
  c.updated_time AS last_edit_proxy
FROM `{PROJECT}.bronze.meta_api_ad_daily` d
LEFT JOIN `{PROJECT}.bronze.meta_api_ad_creatives` c
  ON c.ad_id = d.ad_id
LEFT JOIN `{PROJECT}.bronze.meta_api_campaigns` camp
  ON camp.campaign_id = d.campaign_id
LEFT JOIN `{PROJECT}.bronze.meta_api_adsets` adset
  ON adset.adset_id = d.adset_id
"""


# One row per ad: the copy QC dim (18 Aug 2026, asked by marketing — "Primary
# text" / "Headline (ad settings)" / URL, so ads can be checked for typos and
# URL-parameter setup without opening Ads Manager). Join to anything by ad_id.
META_AD_CREATIVE_TEXT = f"""
SELECT
  c.ad_id,
  c.ad_name,
  c.effective_status AS ad_status,
  c.creative_id,
  c.creative_name,
  CASE
    WHEN JSON_QUERY(c.object_story_spec, '$.video_data') IS NOT NULL THEN 'video'
    WHEN JSON_QUERY(c.object_story_spec, '$.link_data')  IS NOT NULL THEN 'image/link'
    WHEN c.object_story_spec IS NOT NULL                              THEN 'other'
  END AS creative_format,
  COALESCE(
    JSON_VALUE(c.object_story_spec, '$.video_data.call_to_action.value.link'),
    JSON_VALUE(c.object_story_spec, '$.link_data.link')
  ) AS landing_page_url,
{_ad_copy_cols('c')}
  c.updated_time
FROM `{PROJECT}.bronze.meta_api_ad_creatives` c
"""


def _geo_string(root: str) -> str:
    """Assemble one readable geo string from a targeting JSON sub-object.

    `root` is 'geo_locations' (included) or 'excluded_geo_locations'
    (excluded) inside bronze.meta_api_adsets.targeting. Components, in a
    fixed order: countries -> regions (names) -> medium_geo_areas (names,
    same shape as regions, present on both include and exclude sides in the
    real data even though only the exclude side was called out explicitly)
    -> cities as "name (+Nkm)" or "name (+Nmi)" -> custom_locations as
    "lat,lon (+Nkm)" or "lat,lon (+Nmi)". The unit label is read from each
    location's own `distance_unit` (kilometer -> km, mile -> mi) — never
    relabelled. Checked 13 Aug 2026: every radius row in bronze carries an
    explicit distance_unit (0 absent-unit rows found for cities or
    custom_locations), so 'mi' below is a defensive default only, never
    actually exercised on current data. Every piece is a correlated scalar
    subquery over UNNEST — same idiom as meta_creative_performance's
    actions/cost lookups above — so a missing key just yields NULL and
    drops out of the final ARRAY_TO_STRING silently. No key is assumed
    present.
    """
    countries = (
        f"(SELECT STRING_AGG(x, ', ') FROM UNNEST("
        f"JSON_VALUE_ARRAY(targeting, '$.{root}.countries')) AS x)"
    )
    names = (
        "(SELECT STRING_AGG(JSON_VALUE(x, '$.name'), ', ') FROM UNNEST("
        "JSON_EXTRACT_ARRAY(targeting, '$.{root}.{key}')) AS x)"
    )
    regions = names.format(root=root, key="regions")
    medium_geo_areas = names.format(root=root, key="medium_geo_areas")
    unit_label = (
        "CASE JSON_VALUE(x, '$.distance_unit') "
        "WHEN 'kilometer' THEN 'km' WHEN 'mile' THEN 'mi' ELSE 'mi' END"
    )
    cities = (
        "(SELECT STRING_AGG(CONCAT(JSON_VALUE(x, '$.name'), "
        "IF(JSON_VALUE(x, '$.radius') IS NOT NULL, "
        f"CONCAT(' (+', JSON_VALUE(x, '$.radius'), {unit_label}, ')'), '')), ', ') "
        f"FROM UNNEST(JSON_EXTRACT_ARRAY(targeting, '$.{root}.cities')) AS x)"
    )
    custom_locations = (
        "(SELECT STRING_AGG(CONCAT(JSON_VALUE(x, '$.latitude'), ',', "
        "JSON_VALUE(x, '$.longitude'), "
        "IF(JSON_VALUE(x, '$.radius') IS NOT NULL, "
        f"CONCAT(' (+', JSON_VALUE(x, '$.radius'), {unit_label}, ')'), '')), ', ') "
        f"FROM UNNEST(JSON_EXTRACT_ARRAY(targeting, '$.{root}.custom_locations')) AS x)"
    )
    return (
        "NULLIF(ARRAY_TO_STRING(ARRAY(SELECT p FROM UNNEST(["
        f"{countries}, {regions}, {medium_geo_areas}, {cities}, {custom_locations}"
        "]) AS p WHERE p IS NOT NULL AND p != ''), ', '), '')"
    )


# Meta adset targeting — one row per adset, config parsed from the raw
# `targeting` JSON landed on bronze.meta_api_adsets as of commit d74f974
# (790/790 populated, confirmed 13 Aug 2026). Built defensively: every
# targeting shape below is pulled from a real sample row first (see probe
# queries run this session) and every extraction degrades to NULL rather
# than erroring when a key is absent — targeting shapes vary per adset
# (interest-based adsets carry flexible_spec, radius adsets carry
# custom_locations, broad adsets carry neither).
#   - genders: Meta encodes "All" two ways in this account — the key is
#     either absent, or present as the literal array [0]; [1]=Men, [2]=Women.
#     All three collapse to 'All' here.
#   - geo_included / geo_excluded: see _geo_string() above. Real data shows
#     excluded_geo_locations carrying explicit cities (e.g. London, 40mi
#     exclusion ring) as well as country and region-level excludes.
#   - radius units are mixed (kilometer and mile both appear in
#     distance_unit) — each radius is labelled with its OWN unit ("+Nkm" or
#     "+Nmi"), never relabelled. 13 Aug 2026 correction after an earlier
#     draft literal-labelled everything "mi" per an incorrect brief detail.
META_ADSET_TARGETING = f"""
SELECT
  a.adset_id,
  a.adset_name,
  a.effective_status AS adset_status,
  a.campaign_id,
  camp.campaign_name,
  camp.effective_status AS campaign_status,
  a.daily_budget,
  SAFE_CAST(JSON_VALUE(a.targeting, '$.age_min') AS INT64) AS age_min,
  SAFE_CAST(JSON_VALUE(a.targeting, '$.age_max') AS INT64) AS age_max,
  CASE
    WHEN JSON_QUERY(a.targeting, '$.genders') IS NULL THEN 'All'
    WHEN JSON_QUERY(a.targeting, '$.genders') = '[0]' THEN 'All'
    WHEN JSON_QUERY(a.targeting, '$.genders') = '[1]' THEN 'Men'
    WHEN JSON_QUERY(a.targeting, '$.genders') = '[2]' THEN 'Women'
    ELSE (
      SELECT STRING_AGG(
        CASE CAST(g AS INT64) WHEN 1 THEN 'Men' WHEN 2 THEN 'Women' END, ' + '
      )
      FROM UNNEST(JSON_EXTRACT_ARRAY(a.targeting, '$.genders')) AS g
      WHERE CAST(g AS INT64) != 0
    )
  END AS genders,
  {_geo_string('geo_locations')} AS geo_included,
  {_geo_string('excluded_geo_locations')} AS geo_excluded,
  a.targeting AS targeting_raw
FROM `{PROJECT}.bronze.meta_api_adsets` a
LEFT JOIN `{PROJECT}.bronze.meta_api_campaigns` camp
  ON camp.campaign_id = a.campaign_id
"""

# order matters: leads_per_day and sales_attributed read the lead_attribution
# table built earlier in the same run
DERIVED = [
    ("sharpspring_leads", SHARPSPRING_LEADS),
    ("lead_attribution", LEAD_ATTRIBUTION),
    ("leads_per_day", LEADS_PER_DAY),
    ("spend_per_day", SPEND_PER_DAY),
    ("calls_per_day", CALLS_PER_DAY),
    ("lead_calls", LEAD_CALLS),
    ("sales_reconciled", SALES_RECONCILED),
    ("sales_attributed", SALES_ATTRIBUTED),
    ("meta_creative_performance", META_CREATIVE_PERFORMANCE),
    ("meta_ad_creative_text", META_AD_CREATIVE_TEXT),
    ("meta_adset_targeting", META_ADSET_TARGETING),
]


def build(name: str, sql: str) -> int:
    client.query(
        f"CREATE OR REPLACE TABLE `{PROJECT}.{DST}.{name}` AS\n{sql}"
    ).result()
    return list(client.query(
        f"SELECT COUNT(*) AS c FROM `{PROJECT}.{DST}.{name}`"
    ).result())[0].c


def build_cross_region(name: str, sql: str, source_location: str) -> int:
    """Copy a table from another BigQuery region via the client.

    BigQuery cannot query across regions, so a US table cannot be written into
    the EU mart with SQL. Small tables travel through a dataframe instead.
    """
    df = client.query(sql, location=source_location).result().to_dataframe()
    job = client.load_table_from_dataframe(
        df,
        f"{PROJECT}.{DST}.{name}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        location="europe-west2",
    )
    job.result()
    return len(df)


def assert_no_collisions(ad_tables: list[str]) -> None:
    """Fail loudly if a discovered ad table name collides with anything else
    the mart writes. Mart name = bronze name is only safe while ad-platform
    names stay in their own namespace — this is the tripwire if that ever
    stops being true.
    """
    other_names = (
        set(RAW_COPIES)
        | {dest for dest, _ in GSC_STITCHED}
        | {name for name, _ in DERIVED}
        | {"sales"}
    )
    collisions = set(ad_tables) & other_names
    if collisions:
        raise SystemExit(
            f"COLLISION: discovered ad table name(s) {collisions} clash with "
            "an existing RAW_COPIES/GSC_STITCHED/DERIVED/cross-region table name. "
            "Aborting — mart name = bronze name only works if these namespaces "
            "never overlap."
        )


def main() -> None:
    done, failed = [], []

    ad_tables = discover_ad_tables()
    assert_no_collisions([t for t, _, _ in ad_tables])
    total_bytes = sum(b for _, _, b in ad_tables)
    print(f"discovered {len(ad_tables)} ad-platform bronze tables, "
          f"{total_bytes / (1024**3):.3f} GB total (metadata only, no scan)")

    for t in RAW_COPIES + [t for t, _, _ in ad_tables]:
        try:
            n = build(t, f"SELECT * FROM `{PROJECT}.bronze.{t}`")
            done.append((t, n))
            print(f"  ok   {t:<45} {n:>10,}")
        except Exception as e:  # keep going; one bad table shouldn't stall the mart
            failed.append((t, str(e).splitlines()[0][:90]))
            print(f"  FAIL {t:<45} {str(e).splitlines()[0][:55]}")

    # GSC stitched tables: destination row counts no longer equal any single
    # source's row count once the native side is GROUP BY'd (see
    # gsc_source_signature() above), so the skip-guard compares a persisted
    # metadata signature instead of row counts directly.
    gsc_sig = gsc_source_signature()
    try:
        prev_rows = list(client.query(
            f"SELECT signature FROM `{PROJECT}.{DST}._gsc_sync_state`"
        ).result())
        prev_sig = prev_rows[0].signature if prev_rows else None
    except Exception:
        prev_sig = None  # first run: table doesn't exist yet

    if prev_sig == gsc_sig:
        for dest, _ in GSC_STITCHED:
            n = list(client.query(
                f"SELECT COUNT(*) AS c FROM `{PROJECT}.{DST}.{dest}`"
            ).result())[0].c
            done.append((dest, n))
            print(f"  skip {dest:<45} {n:>10,} (source unchanged)")
    else:
        for dest, sql in GSC_STITCHED:
            try:
                n = build(dest, sql)
                done.append((dest, n))
                print(f"  ok   {dest:<45} {n:>10,}")
            except Exception as e:
                failed.append((dest, str(e).splitlines()[0][:90]))
                print(f"  FAIL {dest:<45} {str(e).splitlines()[0][:55]}")
        client.query(f"""
            CREATE OR REPLACE TABLE `{PROJECT}.{DST}._gsc_sync_state` AS
            SELECT '{gsc_sig}' AS signature, CURRENT_TIMESTAMP() AS synced_at
        """).result()

    # ── GA4 straight copies (19 Aug 2026, marketing asked for "everything in
    # bronze"). Same-name copies of every bronze `ga4_api%` table, with the
    # GSC-style row-count skip-guard: these are daily-grain API pulls (~200MB
    # total, landing_pages alone ~110MB) that change at most once a day, so
    # the hourly run only pays for the copy when bronze actually moved.
    ga4_counts = {
        (r.dataset, r.table_id): r.row_count
        for r in client.query(f"""
            SELECT 'bronze' AS dataset, table_id, row_count
            FROM `{PROJECT}.bronze.__TABLES__` WHERE table_id LIKE 'ga4_api%'
            UNION ALL
            SELECT '{DST}', table_id, row_count
            FROM `{PROJECT}.{DST}.__TABLES__` WHERE table_id LIKE 'ga4_api%'
        """).result()
    }
    ga4_tables = sorted({t for (ds, t) in ga4_counts if ds == "bronze"})
    for t in ga4_tables:
        try:
            src_n = ga4_counts.get(("bronze", t))
            if src_n is not None and ga4_counts.get((DST, t)) == src_n:
                done.append((t, src_n))
                print(f"  skip {t:<45} {src_n:>10,} (source unchanged)")
                continue
            n = build(t, f"SELECT * FROM `{PROJECT}.bronze.{t}`")
            done.append((t, n))
            print(f"  ok   {t:<45} {n:>10,}")
        except Exception as e:
            failed.append((t, str(e).splitlines()[0][:90]))
            print(f"  FAIL {t:<45} {str(e).splitlines()[0][:55]}")

    # before the derived tables, because sales_attributed does not depend on it
    # but a failure here shouldn't stop the rest of the mart rebuilding
    try:
        n = build_cross_region("sales", SALES_US, "US")
        done.append(("sales", n))
        print(f"  ok   {'sales (US -> EU)':<45} {n:>10,}")
    except Exception as e:
        failed.append(("sales", str(e).splitlines()[0][:90]))
        print(f"  FAIL {'sales (US -> EU)':<45} {str(e).splitlines()[0][:55]}")

    for name, sql in DERIVED:
        try:
            n = build(name, sql)
            done.append((name, n))
            print(f"  ok   {name:<45} {n:>10,}")
        except Exception as e:
            failed.append((name, str(e).splitlines()[0][:90]))
            print(f"  FAIL {name:<45} {str(e).splitlines()[0][:55]}")

    rows = ", ".join(
        f"STRUCT('{t}' AS table_name, {n} AS row_count)" for t, n in done
    )
    client.query(f"""
      CREATE OR REPLACE TABLE `{PROJECT}.{DST}._sync_log` AS
      SELECT CURRENT_TIMESTAMP() AS synced_at, table_name, row_count
      FROM UNNEST([{rows}])
    """).result()

    print(f"\n{len(done)}/{len(RAW_COPIES) + len(ad_tables) + len(GSC_STITCHED) + len(DERIVED) + 1} tables, "
          f"{sum(n for _, n in done):,} rows")
    if failed:
        print("FAILURES:")
        for t, e in failed:
            print(f"  {t}: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
