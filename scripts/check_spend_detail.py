import duckdb, os
from dotenv import load_dotenv
load_dotenv()

con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")

# Show last 7 days of spend per platform so we can see the exact data
print("=== RAW SPEND last 7 days (from gold_campaign_attribution) ===")
df = con.execute("""
    SELECT date, platform, spend_gbp, leads, clicks, impressions
    FROM gold.gold_campaign_attribution
    WHERE date >= '2026-05-12'
    ORDER BY date DESC, platform
""").df()
print(df.to_string(index=False))

# Show freshness of source data — latest date per platform in silver
print("\n=== LATEST DATE in each silver spend table ===")
for tbl, name in [
    ("silver.silver_google_ads_spend", "Google"),
    ("silver.silver_meta_spend", "Meta"),
    ("silver.silver_bing_spend", "Bing"),
]:
    row = con.execute(f"SELECT max(date) as latest FROM {tbl}").fetchone()
    print(f"  {name}: latest date = {row[0]}")

# Check what currency Google Ads data is actually in
print("\n=== GOOGLE SPEND raw (last 3 days, top 5 rows) ===")
g = con.execute("""
    SELECT date, campaign_id, campaign_name, spend_gbp, clicks, impressions
    FROM silver.silver_google_ads_spend
    WHERE date >= '2026-05-14'
    ORDER BY date DESC, spend_gbp DESC
    LIMIT 10
""").df()
print(g.to_string(index=False))
