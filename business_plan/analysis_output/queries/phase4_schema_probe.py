import google.auth
from google.cloud import bigquery
creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def cols(t):
    df = client.query(f"""SELECT column_name FROM `trustwarehouse.bronze.INFORMATION_SCHEMA.COLUMNS`
                          WHERE table_name='{t}' ORDER BY ordinal_position""").to_dataframe()
    return ", ".join(df.column_name)
for t in ['unleashed_products', 'unleashed_sales_orders__sales_order_lines', 'unleashed_stock_on_hand']:
    print(t, "->", cols(t)[:600], "\n")
