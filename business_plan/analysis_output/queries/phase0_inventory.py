"""Phase 0.1-0.4 + 0.8 — full warehouse inventory: datasets, tables, rows,
date coverage, last-modified (freshness). Read-only; metadata queries are free,
min/max scans limited to bronze + key silver/gold tables."""
import json
import google.auth
from google.cloud import bigquery

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
PROJECT = "trustwarehouse"

def q(sql):
    return client.query(sql).to_dataframe()

# date column candidates per table-name pattern (bronze is source-native)
DATE_COL = [
    ("sharpspring_leads", "TIMESTAMP", "create_timestamp"),
    ("sharpspring_notes", "TIMESTAMP", "create_timestamp"),
    ("sharpspring_opportunities", "TIMESTAMP", "create_timestamp"),
    ("sharpspring_campaigns", None, None),
    ("sharpspring_deal_stages", None, None),
    ("sharpspring_fields", None, None),
    ("ascend_calls", "TIMESTAMP", "start"),
    ("ascend_transcripts", "TIMESTAMP", "call_start"),
    ("wildix_calls", "STRING_DT", "start_time"),
    ("wildix_call_history", "STRING_DT", "start_time"),
    ("google_ads_api_campaign_daily", "DATE_STR", "date"),
    ("meta_api_campaign_daily", "DATE_STR", "date"),
    ("meta_api_geographic_daily", "DATE_STR", "date"),
    ("bing_adsaccount_performance_report_daily", "CAST_DATE", "TimePeriod"),
    ("bing_adscampaign_performance_report_daily", "CAST_DATE", "TimePeriod"),
    ("ga4_api_geographic_daily", "DATE_STR", "date"),
    ("ga4_api_temporal_daily", "DATE_STR", "date"),
    ("unleashed_sales_orders", "MS_DATE", "order_date"),
    ("unleashed_purchase_orders", "MS_DATE", "order_date"),
    ("cms_", None, None),
]

inventory = []
for ds in ["bronze", "silver", "gold", "app", "cms_ingestion", "shared_marketing", "bronze_staging"]:
    try:
        tabs = q(f"""
          SELECT table_id, row_count, size_bytes,
                 TIMESTAMP_MILLIS(last_modified_time) AS last_modified
          FROM `{PROJECT}.{ds}.__TABLES__` ORDER BY table_id
        """)
    except Exception as e:
        print(f"{ds}: SKIP ({str(e)[:80]})")
        continue
    for r in tabs.itertuples():
        row = {"dataset": ds, "table": r.table_id, "rows": int(r.row_count),
               "mb": round(r.size_bytes / 1e6, 1), "last_modified": str(r.last_modified)[:19],
               "date_min": "", "date_max": ""}
        if ds == "bronze":
            for pat, kind, col in DATE_COL:
                if r.table_id == pat or (pat.endswith("_") and r.table_id.startswith(pat)):
                    if kind is None:
                        break
                    try:
                        if kind == "TIMESTAMP":
                            expr_min, expr_max = f"MIN({col})", f"MAX({col})"
                        elif kind == "DATE_STR":
                            expr_min, expr_max = f"MIN(DATE({col}))", f"MAX(DATE({col}))"
                        elif kind == "CAST_DATE":
                            expr_min, expr_max = (f"MIN(SAFE_CAST({col} AS DATE))",
                                                  f"MAX(SAFE_CAST({col} AS DATE))")
                        elif kind == "STRING_DT":
                            expr_min, expr_max = (f"MIN(SAFE_CAST(SUBSTR(CAST({col} AS STRING),1,10) AS DATE))",
                                                  f"MAX(SAFE_CAST(SUBSTR(CAST({col} AS STRING),1,10) AS DATE))")
                        elif kind == "MS_DATE":
                            expr_min, expr_max = (
                                f"MIN(TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT({col}, r'([0-9]+)') AS INT64)))",
                                f"MAX(TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT({col}, r'([0-9]+)') AS INT64)))")
                        d = q(f"SELECT {expr_min} AS lo, {expr_max} AS hi FROM `{PROJECT}.bronze.{r.table_id}`")
                        row["date_min"], row["date_max"] = str(d.lo.iloc[0])[:10], str(d.hi.iloc[0])[:10]
                    except Exception as e:
                        row["date_min"] = "ERR: " + str(e)[:60]
                    break
        inventory.append(row)

import pandas as pd
df = pd.DataFrame(inventory)
df.to_csv(r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data\phase0_table_inventory.csv', index=False)
pd.set_option('display.width', 250)
for ds in df.dataset.unique():
    print(f"\n===== {ds} =====")
    print(df[df.dataset == ds].drop(columns=['dataset']).to_string(index=False))
