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
# (GSC_COPIES below already has one, for its much larger tables). Hourly for
# a month: ~0.46GB * 24 * 30 / 1024 = ~0.32TB * £4.7/TB ≈ £1.55/month. Re-check
# this threshold if Airbyte lands a new large ad report table.

AD_PLATFORM_PREFIXES = ["google_ads%", "meta_api%", "bing_ads%"]


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


# ── Search Console straight copies (renamed, same region) ───────────────────
# Currently backed by the one-off 16-month API backfill in bronze; Google's
# native `searchconsole` bulk export was enabled 10 Aug 2026 and once its
# daily tables start landing these switch to a union/replace of backfill +
# native rows. Both sources are europe-west2, same as the mart, so this is a
# plain CREATE TABLE AS SELECT - not the cross-region dataframe path used for
# app.sales (US). The mart drops the "_backfill" suffix; marketing shouldn't
# care about provenance.
# The big table is ~520MB and its source changes at most daily, so the hourly
# run skips the copy when source and mart row counts already match — the
# check reads __TABLES__ metadata, which BigQuery answers without scanning.

GSC_COPIES = [
    ("gsc_search_analytics", "gsc_search_analytics_backfill"),
    ("gsc_daily_totals", "gsc_daily_totals_backfill"),
]


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
  exact_marketing_url_64d0bebced518 AS marketing_url,
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
  {norm_phone('mobile_phone_number')} AS mobile_normalised
FROM `{PROJECT}.bronze.sharpspring_leads`
"""

LEAD_ATTRIBUTION = f"""
WITH src AS (
  SELECT
    id AS lead_id,
    DATE(create_timestamp) AS created_date,
    create_timestamp,
    exact_marketing_url_64d0bebced518 AS url,
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
SELECT SAFE_CAST(TimePeriod AS DATE), 'Bing', ROUND(SUM(Spend), 2), SUM(Clicks), SUM(Impressions)
FROM `{PROJECT}.bronze.bing_adsaccount_performance_report_daily` GROUP BY 1
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
        | {dest for dest, _ in GSC_COPIES}
        | {name for name, _ in DERIVED}
        | {"sales"}
    )
    collisions = set(ad_tables) & other_names
    if collisions:
        raise SystemExit(
            f"COLLISION: discovered ad table name(s) {collisions} clash with "
            "an existing RAW_COPIES/GSC_COPIES/DERIVED/cross-region table name. "
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

    gsc_counts = {
        (r.dataset, r.table_id): r.row_count
        for r in client.query(f"""
            SELECT 'bronze' AS dataset, table_id, row_count
            FROM `{PROJECT}.bronze.__TABLES__` WHERE table_id LIKE 'gsc%'
            UNION ALL
            SELECT '{DST}', table_id, row_count
            FROM `{PROJECT}.{DST}.__TABLES__` WHERE table_id LIKE 'gsc%'
        """).result()
    }
    for dest, src in GSC_COPIES:
        try:
            src_n = gsc_counts.get(("bronze", src))
            if src_n is not None and gsc_counts.get((DST, dest)) == src_n:
                done.append((dest, src_n))
                print(f"  skip {dest:<45} {src_n:>10,} (source unchanged)")
                continue
            # bronze keeps date as the API's raw string; the mart types it so
            # consumers can write `WHERE date >= <date>` without casting
            n = build(dest, f"SELECT * REPLACE (DATE(date) AS date) FROM `{PROJECT}.bronze.{src}`")
            done.append((dest, n))
            print(f"  ok   {dest:<45} {n:>10,}")
        except Exception as e:
            failed.append((dest, str(e).splitlines()[0][:90]))
            print(f"  FAIL {dest:<45} {str(e).splitlines()[0][:55]}")

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

    print(f"\n{len(done)}/{len(RAW_COPIES) + len(ad_tables) + len(GSC_COPIES) + len(DERIVED) + 1} tables, "
          f"{sum(n for _, n in done):,} rows")
    if failed:
        print("FAILURES:")
        for t, e in failed:
            print(f"  {t}: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
