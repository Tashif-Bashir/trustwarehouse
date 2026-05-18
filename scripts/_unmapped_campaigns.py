import duckdb, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ["MOTHERDUCK_TOKEN"].strip()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

print("=== UNMAPPED CAMPAIGN IDs — with names from SharpSpring ===\n")
rows = con.execute("""
    select
        g.campaign_id,
        c.campaign_name,
        count(*) as total_leads,
        max(g.created_date) as last_lead
    from gold.gold_lead_activity g
    left join silver.campaign_platform_mapping m on g.campaign_id = m.campaign_id
    left join silver.silver_sharpspring_campaigns c on g.campaign_id = c.campaign_id
    where g.campaign_id is not null
    and g.campaign_id != ''
    and m.platform is null
    group by 1, 2
    order by 3 desc
""").fetchall()

for r in rows:
    name = r[1] if r[1] else "-- name not found --"
    print(f"  {r[0]:<25}  leads={r[2]:<6}  last={r[3]}  {name}")

print(f"\nTotal unmapped campaign IDs: {len(rows)}")
print(f"Total unmapped leads: {sum(r[2] for r in rows):,}")
