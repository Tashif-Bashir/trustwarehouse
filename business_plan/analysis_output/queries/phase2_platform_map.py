import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
df = client.query("""
  SELECT c.campaign_name, COUNT(*) leads
  FROM `trustwarehouse.bronze.sharpspring_leads` l
  LEFT JOIN `trustwarehouse.bronze.sharpspring_campaigns` c
    ON CAST(c.id AS STRING)=CAST(l.campaign_id AS STRING)
  WHERE l.create_timestamp >= '2024-08-01'
  GROUP BY 1 ORDER BY leads DESC LIMIT 30
""").to_dataframe()
print(df.to_string(index=False))
