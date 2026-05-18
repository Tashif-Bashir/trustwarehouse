import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

DATE = "2026-05-17"

print("=== GOOGLE: campaigns with spend on Sunday ===")
rows = con.execute(f"""
    select campaign_id, campaign_name, campaign_status, channel_type,
           impressions, clicks, spend_gbp
    from silver.silver_google_ads_spend
    where date = '{DATE}'
    order by spend_gbp desc
""").fetchall()
total = 0
for r in rows:
    total += r[6]
    print(f"  [{r[2]}] {r[3]:<20} £{r[6]:>8,.2f}  {r[1]}")
print(f"  TOTAL: £{total:,.2f}  ({len(rows)} campaigns)")

print()
print("=== BING: campaigns with spend on Sunday ===")
rows = con.execute(f"""
    select campaign_id, campaign_name, campaign_status, currency,
           impressions, clicks, spend_gbp
    from silver.silver_bing_spend
    where date = '{DATE}'
    order by spend_gbp desc
""").fetchall()
total = 0
for r in rows:
    total += r[6]
    print(f"  [{r[2]}] {r[3]}  £{r[6]:>8,.2f}  {r[1]}")
print(f"  TOTAL: £{total:,.2f}  ({len(rows)} campaigns)")

print()
print("=== BING: what does the bronze table date range look like? ===")
rows = con.execute("""
    select timeperiod, sum(spend) as spend, count(*) as rows
    from bronze.bing_adscampaign_performance_report_daily
    where timeperiod >= '2026-05-15'
    group by timeperiod
    order by timeperiod
""").fetchall()
for r in rows:
    print(f"  {r[0]}: £{r[1]:,.2f}  ({r[2]} rows)")
