import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

DATE = "2026-05-17"

print("=== GOOGLE ACCOUNT-LEVEL (bronze) for Sunday ===")
cols = con.execute("describe bronze.google_adsaccount_performance_report").fetchall()
print("Columns:", [c[0] for c in cols])

print()
rows = con.execute(f"""
    select *
    from bronze.google_adsaccount_performance_report
    where segments_date = '{DATE}'
    order by _airbyte_extracted_at desc
""").fetchall()
col_names = [c[0] for c in cols]
for r in rows:
    for name, val in zip(col_names, r):
        if val is not None and val != 0:
            print(f"  {name}: {val}")
    print("  ---")

print()
print("=== CAMPAIGN-LEVEL SUM for comparison ===")
r = con.execute(f"""
    select count(*) as campaigns, sum(spend_gbp) as total_spend
    from silver.silver_google_ads_spend
    where date = '{DATE}'
""").fetchone()
print(f"  {r[0]} campaigns, total spend: £{r[1]:,.2f}")
