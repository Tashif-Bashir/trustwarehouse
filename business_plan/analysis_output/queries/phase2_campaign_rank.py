import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
df = client.query("""
  SELECT campaign_name,
         ROUND(SUM(spend_gbp),0) AS spend,
         ROUND(SUM(conversions),1) AS conversions,
         ROUND(SAFE_DIVIDE(SUM(spend_gbp), NULLIF(SUM(conversions),0)),0) AS cost_per_conv
  FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
  WHERE DATE(date) BETWEEN '2025-07-01' AND '2026-06-30'
  GROUP BY 1 HAVING spend > 1000
  ORDER BY cost_per_conv DESC
""").to_dataframe()
print(df.to_string(index=False))
tot = df.spend.sum()
med = df.cost_per_conv.median()
waste = df[(df.cost_per_conv > 2*med) | (df.conversions == 0)]
print("\naccount median cost/conv: %.0f | campaigns >2x median or zero-conv: %d | spend there: %.0f (%.0f%% of %.0f)"
      % (med, len(waste), waste.spend.sum(), waste.spend.sum()/tot*100, tot))
df.to_csv(r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data\phase2_google_campaign_rank.csv', index=False)
