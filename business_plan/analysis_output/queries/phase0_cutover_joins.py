"""Phase 0.5 + 0.7 — Wildix->Ascend cutover mapping, schema comparison,
and join-key strength probes."""
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()

pd.set_option('display.width', 220)

print("=== wildix_calls columns ===")
wc = q("""SELECT column_name, data_type FROM `trustwarehouse.bronze.INFORMATION_SCHEMA.COLUMNS`
          WHERE table_name='wildix_calls' ORDER BY ordinal_position""")
print(", ".join(f"{r.column_name}({r.data_type})" for r in wc.itertuples()))

print("\n=== ascend_calls columns ===")
ac = q("""SELECT column_name, data_type FROM `trustwarehouse.bronze.INFORMATION_SCHEMA.COLUMNS`
          WHERE table_name='ascend_calls' ORDER BY ordinal_position""")
print(", ".join(f"{r.column_name}({r.data_type})" for r in ac.itertuples()))

print("\n=== wildix sample row ===")
print(q("SELECT * FROM `trustwarehouse.bronze.wildix_calls` LIMIT 2").to_string(index=False))
