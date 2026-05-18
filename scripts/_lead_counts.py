"""Lead count check from gold layer (source of truth for dashboards)."""

import duckdb
import os
from dotenv import load_dotenv

load_dotenv()

token = os.environ["MOTHERDUCK_TOKEN"].strip()
db = os.environ.get("MOTHERDUCK_DATABASE", "trust-pipeline")
con = duckdb.connect(f"md:{db}?motherduck_token={token}")

print("=== TODAY (2026-05-18) ===")
r = con.execute("""
    select count(*) as total_leads
    from gold.gold_lead_activity
    where created_date = '2026-05-18'
""").fetchall()
print(f"Leads created today: {r[0][0]}")

print()
print("=== WEEKEND (Sat 16 + Sun 17 + Mon 18 May) ===")
rows = con.execute("""
    select
        created_date as day,
        count(*) as total_leads,
        count(*) filter (where campaign_id is not null and campaign_id != '') as paid_leads
    from gold.gold_lead_activity
    where created_date between '2026-05-16' and '2026-05-18'
    group by 1
    order by 1
""").fetchall()
for row in rows:
    print(f"  {row[0]}: {row[1]} total leads, {row[2]} with campaign_id (paid)")

print()
print("=== BREAKDOWN BY PLATFORM (campaign attribution, weekend) ===")
rows = con.execute("""
    select
        g.created_date as day,
        coalesce(m.platform, 'Organic / Unknown') as platform,
        count(*) as leads
    from gold.gold_lead_activity g
    left join silver.campaign_platform_mapping m on g.campaign_id = m.campaign_id
    where g.created_date between '2026-05-16' and '2026-05-18'
    group by 1, 2
    order by 1, 3 desc
""").fetchall()
for row in rows:
    print(f"  {row[0]} | {row[1]}: {row[2]} leads")

print()
print("=== SOLD / APPOINTMENT STATUS (weekend) ===")
rows = con.execute("""
    select
        created_date as day,
        count(*) filter (where is_sold = true) as sold,
        count(*) filter (where appointment_status is not null and appointment_status != '') as has_appt_status,
        count(*) filter (where has_been_called = true) as called
    from gold.gold_lead_activity
    where created_date between '2026-05-16' and '2026-05-18'
    group by 1
    order by 1
""").fetchall()
for row in rows:
    print(f"  {row[0]}: {row[1]} sold, {row[2]} with appt status, {row[3]} called")

print()
print("=== ALL TIME TOTAL ===")
r = con.execute("select count(*) from gold.gold_lead_activity").fetchall()
print(f"Total leads in gold: {r[0][0]}")
