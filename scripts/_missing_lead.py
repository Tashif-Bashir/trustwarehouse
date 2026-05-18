import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

DATE = "2026-05-17"

print("=== ALL SUNDAY LEADS WITH THEIR CAMPAIGN_IDs ===")
rows = con.execute(f"""
    select
        g.lead_id,
        g.campaign_id,
        m.platform,
        g.first_name,
        g.last_name,
        g.created_at
    from gold.gold_lead_activity g
    left join silver.campaign_platform_mapping m on g.campaign_id = m.campaign_id
    where g.created_date = '{DATE}'
    order by g.created_at
""").fetchall()

for r in rows:
    platform = r[2] if r[2] else "NO MATCH"
    camp = r[1] if r[1] else "NULL"
    print(f"  {r[5]}  campaign={camp:<20}  platform={platform:<20}  {r[3]} {r[4]}")

print()
print(f"Total: {len(rows)} leads")
print(f"With campaign_id: {sum(1 for r in rows if r[1])}")
print(f"Mapped to platform: {sum(1 for r in rows if r[2])}")
print(f"Has campaign_id but NOT mapped: {sum(1 for r in rows if r[1] and not r[2])}")

print()
print("=== UNMAPPED CAMPAIGN IDs (any date) ===")
rows2 = con.execute("""
    select
        g.campaign_id,
        count(*) as leads,
        min(g.created_date) as first_seen,
        max(g.created_date) as last_seen
    from gold.gold_lead_activity g
    left join silver.campaign_platform_mapping m on g.campaign_id = m.campaign_id
    where g.campaign_id is not null
    and g.campaign_id != ''
    and m.platform is null
    group by 1
    order by 2 desc
    limit 20
""").fetchall()
for r in rows2:
    print(f"  campaign_id={r[0]}  leads={r[1]}  first={r[2]}  last={r[3]}")
