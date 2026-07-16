import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
df = client.query("""
  SELECT COUNT(*) AS rows_,
         COUNT(DISTINCT id) AS distinct_calls,
         COUNT(DISTINCT CONCAT(id, '|', CAST(flow_index AS STRING))) AS distinct_legs
  FROM `trustwarehouse.bronze.wildix_calls`
""").to_dataframe()
print(df.to_string(index=False))
