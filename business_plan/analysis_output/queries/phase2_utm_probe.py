import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
df = client.query("""
  SELECT exact_marketing_campaign_64d0b4a09e91b AS utm, COUNT(*) leads,
    COUNTIF(TRIM(COALESCE(status_633ae6f6ac6fe,'')) IN
      ('Appointment','Appointment Cancelled','WhatsApp Appointment')) AS appts
  FROM `trustwarehouse.bronze.sharpspring_leads`
  WHERE create_timestamp BETWEEN '2025-07-01' AND '2026-06-30'
    AND TRIM(COALESCE(exact_marketing_campaign_64d0b4a09e91b,'')) != ''
  GROUP BY 1 ORDER BY leads DESC LIMIT 35
""").to_dataframe()
print(df.to_string(index=False))
