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


# ── straight copies of the ad platform tables ────────────────────────────────

RAW_COPIES = [
    "google_ads_api_campaign_daily",
    "google_ads_api_geo_target_constants",
    "meta_api_campaign_daily",
    "meta_api_geographic_daily",
    "bing_adsaccount_performance_report_daily",
    "bing_adsaccounts",
    "bing_adsad_group_labels",
    "bing_adsad_group_performance_report_daily",
    "bing_adsad_groups",
    "bing_adsad_performance_report_daily",
    "bing_adsads",
    "bing_adscampaign_labels",
    "bing_adscampaign_performance_report_daily",
    "bing_adscampaigns",
    "bing_adskeyword_labels",
    "bing_adskeyword_performance_report_daily",
    "bing_adskeywords",
    "sharpspring_campaigns",
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

# order matters: leads_per_day reads the lead_attribution table built above
DERIVED = [
    ("sharpspring_leads", SHARPSPRING_LEADS),
    ("lead_attribution", LEAD_ATTRIBUTION),
    ("leads_per_day", LEADS_PER_DAY),
    ("spend_per_day", SPEND_PER_DAY),
    ("calls_per_day", CALLS_PER_DAY),
    ("lead_calls", LEAD_CALLS),
]


def build(name: str, sql: str) -> int:
    client.query(
        f"CREATE OR REPLACE TABLE `{PROJECT}.{DST}.{name}` AS\n{sql}"
    ).result()
    return list(client.query(
        f"SELECT COUNT(*) AS c FROM `{PROJECT}.{DST}.{name}`"
    ).result())[0].c


def main() -> None:
    done, failed = [], []

    for t in RAW_COPIES:
        try:
            n = build(t, f"SELECT * FROM `{PROJECT}.bronze.{t}`")
            done.append((t, n))
            print(f"  ok   {t:<45} {n:>10,}")
        except Exception as e:  # keep going; one bad table shouldn't stall the mart
            failed.append((t, str(e).splitlines()[0][:90]))
            print(f"  FAIL {t:<45} {str(e).splitlines()[0][:55]}")

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

    print(f"\n{len(done)}/{len(RAW_COPIES) + len(DERIVED)} tables, "
          f"{sum(n for _, n in done):,} rows")
    if failed:
        print("FAILURES:")
        for t, e in failed:
            print(f"  {t}: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
