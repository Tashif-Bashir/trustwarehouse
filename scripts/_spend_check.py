import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

print("=== SILVER GOOGLE (last 3 days) ===")
rows = con.execute("select date, sum(spend_gbp) as spend from silver.silver_google_ads_spend where date >= '2026-05-15' group by date order by date").fetchall()
for r in rows: print(f"  {r[0]}: GBP {r[1]:,.2f}")

print("\n=== SILVER META (last 3 days) ===")
rows = con.execute("select date, sum(spend_gbp) as spend from silver.silver_meta_spend where date >= '2026-05-15' group by date order by date").fetchall()
for r in rows: print(f"  {r[0]}: GBP {r[1]:,.2f}")

print("\n=== SILVER BING (last 3 days) ===")
rows = con.execute("select date, sum(spend_gbp) as spend from silver.silver_bing_spend where date >= '2026-05-15' group by date order by date").fetchall()
for r in rows: print(f"  {r[0]}: GBP {r[1]:,.2f}")

print("\n=== GOLD CAMPAIGN ATTRIBUTION (last 3 days) ===")
rows = con.execute("select date, platform, spend_gbp, leads from gold.gold_campaign_attribution where date >= '2026-05-15' order by date, platform").fetchall()
for r in rows: print(f"  {r[0]} | {r[1]:<8} spend GBP {r[2]:>8,.2f}  leads {r[3]}")
