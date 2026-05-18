import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

# List bronze tables to find ad spend tables
print("=== BRONZE AD SPEND TABLES ===")
tables = con.execute("""
    select table_name from information_schema.tables
    where table_schema = 'bronze'
    and (table_name ilike '%google%' or table_name ilike '%meta%' or table_name ilike '%bing%' or table_name ilike '%facebook%')
    order by table_name
""").fetchall()
for t in tables:
    print(f"  {t[0]}")

# Check each for May 17 data
print("\n=== CHECKING BRONZE FOR 2026-05-17 ===")
for (tname,) in tables:
    try:
        cols = con.execute(f"describe bronze.{tname}").fetchall()
        col_names = [c[0].lower() for c in cols]
        date_col = next((c for c in col_names if 'date' in c), None)
        if date_col:
            r = con.execute(f"select count(*) from bronze.{tname} where {date_col} = '2026-05-17'").fetchone()
            print(f"  {tname}.{date_col}: {r[0]} rows for 2026-05-17")
        else:
            print(f"  {tname}: no date column found (cols: {col_names[:5]})")
    except Exception as e:
        print(f"  {tname}: ERROR — {e}")
