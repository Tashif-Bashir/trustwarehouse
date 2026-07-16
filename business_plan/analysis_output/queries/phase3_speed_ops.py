"""Phase 3A.2/3A.3 — speed-to-lead distribution + conversion correlation,
call-ops coverage vs lead arrival, answer rates across the cutover.
Unified calls per cleaning_rules.sql. Window: Jun 2025+ (C4: wildix floor May 2025)."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 260)
OUT = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data'

UNIFIED = """
  unified_calls AS (
    SELECT * FROM (
      SELECT id, TIMESTAMP_MILLIS(MIN(start_time)) AS start,
             LOWER(ANY_VALUE(direction)) AS direction,
             ANY_VALUE(remote_phone) AS remote_number,
             SUM(talk_time) AS talk_seconds, MAX(talk_time) > 0 AS answered
      FROM (SELECT DISTINCT id, flow_index, start_time, direction, talk_time, remote_phone
            FROM `trustwarehouse.bronze.wildix_calls`)
      GROUP BY id
    ) WHERE start < '2026-07-01'
    UNION ALL
    SELECT id, start, direction,
           CASE WHEN direction = 'outbound' THEN JSON_VALUE(`to`, '$.number')
                ELSE JSON_VALUE(`from`, '$.number') END,
           duration, answered
    FROM `trustwarehouse.bronze.ascend_calls`
    WHERE start >= '2026-07-01'),
  calls_norm AS (
    SELECT *, CASE WHEN n LIKE '00%' THEN SUBSTR(n, 3)
                   WHEN n LIKE '0%' THEN CONCAT('44', SUBSTR(n, 2)) ELSE n END AS phone44
    FROM (SELECT *, REGEXP_REPLACE(COALESCE(remote_number, ''), r'[^0-9]', '') AS n
          FROM unified_calls) WHERE LENGTH(n) >= 9),
  leads AS (
    SELECT l.id, l.create_timestamp AS cts,
      TRIM(COALESCE(l.status_633ae6f6ac6fe,'')) IN
        ('Appointment','Appointment Cancelled','WhatsApp Appointment') AS is_appt,
      CASE WHEN ph LIKE '00%' THEN SUBSTR(ph, 3)
           WHEN ph LIKE '0%' THEN CONCAT('44', SUBSTR(ph, 2)) ELSE ph END AS phone44
    FROM (SELECT *, REGEXP_REPLACE(COALESCE(NULLIF(TRIM(phone_number),''),
                                            NULLIF(TRIM(mobile_phone_number),''), ''), r'[^0-9]', '') AS ph
          FROM `trustwarehouse.bronze.sharpspring_leads`) l
    WHERE l.create_timestamp >= '2025-06-01' AND LENGTH(ph) >= 9
      AND NOT REGEXP_CONTAINS(LOWER(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))),
                              r'zzz|\\btest lead\\b|testlead')),
  first_call AS (
    SELECT l.id, MIN(TIMESTAMP_DIFF(c.start, l.cts, MINUTE)) AS mins_to_call
    FROM leads l JOIN calls_norm c
      ON l.phone44 = c.phone44 AND c.direction = 'outbound'
         AND c.start >= l.cts AND c.start < TIMESTAMP_ADD(l.cts, INTERVAL 14 DAY)
    GROUP BY l.id)
"""

print("=== speed-to-lead distribution by month (leads Jun 2025+) ===")
sp = q(f"""
  WITH {UNIFIED}
  SELECT FORMAT_TIMESTAMP('%Y-%m', l.cts) AS month, COUNT(*) AS leads_w_phone,
    ROUND(COUNT(fc.id)/COUNT(*)*100,1) AS called_within_14d_pct,
    ROUND(APPROX_QUANTILES(fc.mins_to_call, 100)[OFFSET(50)],0) AS median_mins,
    ROUND(APPROX_QUANTILES(fc.mins_to_call, 100)[OFFSET(90)],0) AS p90_mins,
    ROUND(COUNTIF(fc.mins_to_call <= 10)/NULLIF(COUNT(fc.id),0)*100,1) AS pct_within_10min
  FROM leads l LEFT JOIN first_call fc ON l.id = fc.id
  GROUP BY month ORDER BY month
""")
print(sp.to_string(index=False))
sp.to_csv(OUT + r'\phase3_speed_monthly.csv', index=False)

print("\n=== conversion by speed bucket (leads Jun 2025 - May 2026) ===")
print(q(f"""
  WITH {UNIFIED}
  SELECT CASE
      WHEN fc.mins_to_call IS NULL THEN '5. never called'
      WHEN fc.mins_to_call <= 10 THEN '1. <=10 min'
      WHEN fc.mins_to_call <= 60 THEN '2. 10-60 min'
      WHEN fc.mins_to_call <= 1440 THEN '3. 1-24 h'
      ELSE '4. >24 h' END AS bucket,
    COUNT(*) AS leads, ROUND(COUNTIF(l.is_appt)/COUNT(*)*100,1) AS appt_pct
  FROM leads l LEFT JOIN first_call fc ON l.id = fc.id
  WHERE l.cts BETWEEN '2025-06-01' AND '2026-05-31'
  GROUP BY bucket ORDER BY bucket
""").to_string(index=False))

print("\n=== inbound answer rate by month across cutover ===")
print(q(f"""
  WITH {UNIFIED.split(', calls_norm')[0]}
  SELECT FORMAT_TIMESTAMP('%Y-%m', start) AS month,
         COUNTIF(direction='inbound') AS inbound,
         ROUND(COUNTIF(direction='inbound' AND answered)/NULLIF(COUNTIF(direction='inbound'),0)*100,1) AS answered_pct,
         COUNTIF(direction='outbound') AS outbound
  FROM unified_calls GROUP BY month ORDER BY month
""").to_string(index=False))

print("\n=== coverage: lead arrivals vs outbound dials by hour (last 6 months) ===")
print(q(f"""
  WITH {UNIFIED.split(', leads AS')[0]},
  la AS (
    SELECT EXTRACT(HOUR FROM create_timestamp) AS hr, COUNT(*) AS leads
    FROM `trustwarehouse.bronze.sharpspring_leads`
    WHERE create_timestamp >= '2026-01-16' GROUP BY hr),
  oc AS (
    SELECT EXTRACT(HOUR FROM start) AS hr, COUNT(*) AS dials
    FROM unified_calls WHERE direction='outbound' AND start >= '2026-01-16' GROUP BY hr)
  SELECT la.hr, la.leads, IFNULL(oc.dials,0) AS dials
  FROM la LEFT JOIN oc USING (hr) ORDER BY la.hr
""").to_string(index=False))
