"""Validation of the 'never called' finding: decompose by number validity and
CRM status. A UK-valid number normalises to 44 + 10 digits (12 chars, mobile 447%
or landline 441/2/3/8%). Leads the team marked 'No Number'/'Not a Lead' are
treated as correctly-not-dialled."""
import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()

df = q("""
  WITH unified_calls AS (
    SELECT TIMESTAMP_MILLIS(MIN(start_time)) AS start,
           ANY_VALUE(remote_phone) AS remote_number
    FROM (SELECT DISTINCT id, flow_index, start_time, direction, talk_time, remote_phone
          FROM `trustwarehouse.bronze.wildix_calls` WHERE direction = 'OUTBOUND')
    GROUP BY id HAVING start < '2026-07-01'
    UNION ALL
    SELECT start, JSON_VALUE(`to`, '$.number')
    FROM `trustwarehouse.bronze.ascend_calls`
    WHERE start >= '2026-07-01' AND direction = 'outbound'),
  calls_norm AS (
    SELECT start, CASE WHEN n LIKE '00%' THEN SUBSTR(n, 3)
                       WHEN n LIKE '0%' THEN CONCAT('44', SUBSTR(n, 2)) ELSE n END AS phone44
    FROM (SELECT start, REGEXP_REPLACE(COALESCE(remote_number,''), r'[^0-9]', '') AS n
          FROM unified_calls) WHERE LENGTH(n) >= 9),
  leads AS (
    SELECT l.id, l.create_timestamp AS cts,
      TRIM(COALESCE(l.status_633ae6f6ac6fe,'')) AS status,
      CASE WHEN ph LIKE '00%' THEN SUBSTR(ph, 3)
           WHEN ph LIKE '0%' THEN CONCAT('44', SUBSTR(ph, 2)) ELSE ph END AS phone44
    FROM (SELECT *, REGEXP_REPLACE(COALESCE(NULLIF(TRIM(phone_number),''),
                                            NULLIF(TRIM(mobile_phone_number),''), ''), r'[^0-9]', '') AS ph
          FROM `trustwarehouse.bronze.sharpspring_leads`) l
    WHERE l.create_timestamp BETWEEN '2025-06-01' AND '2026-06-30'
      AND LENGTH(ph) >= 9
      AND NOT REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))),
                              r'zzz|\btest lead\b|testlead')),
  classified AS (
    SELECT l.*,
      LENGTH(l.phone44) = 12 AND REGEXP_CONTAINS(l.phone44, r'^44[1237-8]')
        AND NOT REGEXP_CONTAINS(l.phone44, r'^44(0{5,}|1{5,})') AS looks_valid,
      l.status IN ('No Number','No Number - Follow Up','Not a Lead','Admin/Finance') AS marked_uncallable,
      EXISTS (SELECT 1 FROM calls_norm c
              WHERE c.phone44 = l.phone44 AND c.start >= l.cts
                AND c.start < TIMESTAMP_ADD(l.cts, INTERVAL 14 DAY)) AS called
    FROM leads l)
  SELECT
    COUNT(*) AS leads_with_phone,
    COUNTIF(called) AS called_14d,
    COUNTIF(NOT called) AS never_called,
    COUNTIF(NOT called AND NOT looks_valid) AS nc_invalid_format,
    COUNTIF(NOT called AND looks_valid AND marked_uncallable) AS nc_valid_but_marked_nonumber,
    COUNTIF(NOT called AND looks_valid AND NOT marked_uncallable) AS nc_valid_callable,
    ROUND(COUNTIF(NOT called AND looks_valid AND NOT marked_uncallable) / COUNT(*) * 100, 1) AS truly_missed_pct,
    COUNTIF(NOT called AND looks_valid AND NOT marked_uncallable
            AND status IN ('Appointment','Appointment Cancelled','WhatsApp Appointment')) AS nc_but_got_appt
  FROM classified
""")
print(df.to_string(index=False))
