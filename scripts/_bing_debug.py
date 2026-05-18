import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

DATE = "2026-05-17"

print("=== BING BRONZE: columns in campaign_performance_report_daily ===")
cols = con.execute("describe bronze.bing_adscampaign_performance_report_daily").fetchall()
for c in cols:
    print(f"  {c[0]:<40} {c[1]}")

print()
print("=== BING BRONZE: rows for Sunday, grouped by campaign ===")
rows = con.execute(f"""
    select campaignid, campaignname, campaignstatus,
           count(*) as row_count,
           sum(spend) as total_spend,
           min(spend) as min_spend,
           max(spend) as max_spend
    from bronze.bing_adscampaign_performance_report_daily
    where timeperiod = '{DATE}'
    group by 1, 2, 3
    order by total_spend desc
""").fetchall()
for r in rows:
    print(f"  [{r[2]}] {r[4]:>8,.2f}  ({r[1]} rows, min={r[5]:.2f} max={r[6]:.2f})  {r[1]}")

print()
print("=== BING BRONZE: distinct segment values for Sunday (first campaign) ===")
if rows:
    first_id = rows[0][0]
    rows2 = con.execute(f"""
        select network, devicetype, bidmatchtype, deliveredmatchtype, addistribution, topvsother, spend, _airbyte_extracted_at
        from bronze.bing_adscampaign_performance_report_daily
        where timeperiod = '{DATE}' and campaignid = '{first_id}'
        order by _airbyte_extracted_at desc
        limit 20
    """).fetchall()
    for r in rows2:
        print(f"  net={r[0]} dev={r[1]} bid={r[2]} del={r[3]} dist={r[4]} pos={r[5]}  spend={r[6]:.2f}  extracted={r[7]}")
