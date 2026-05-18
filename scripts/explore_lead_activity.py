import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== lead_status values ===")
rows = con.execute("""
    SELECT lead_status, COUNT(*) cnt
    FROM silver.silver_sharpspring_leads
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
for row in rows:
    print(f"  {str(row[0]):<30} {row[1]}")

print("\n=== domestic_lead_status values ===")
rows = con.execute("""
    SELECT domestic_lead_status, COUNT(*) cnt
    FROM silver.silver_sharpspring_leads
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
for row in rows:
    print(f"  {str(row[0]):<30} {row[1]}")

print("\n=== Phone join test: how many leads match at least one wildix call ===")
r = con.execute("""
    SELECT
        COUNT(DISTINCT l.lead_id) as total_active_leads,
        COUNT(DISTINCT CASE WHEN c.remote_phone IS NOT NULL THEN l.lead_id END) as leads_with_calls
    FROM silver.silver_sharpspring_leads l
    LEFT JOIN silver.silver_wildix_calls c
        ON c.remote_phone IN (l.phone, l.mobile, l.phone_alt)
        AND c.direction = 'OUTBOUND'
        AND c.call_status = 'COMPLETED'
    WHERE l.is_active = true
""").fetchone()
print(f"  Active leads: {r[0]}, Matched to a call: {r[1]} ({round(r[1]/r[0]*100,1)}%)")

print("\n=== created_at sample (to confirm timezone/format) ===")
rows = con.execute("""
    SELECT created_at, cast(created_at at time zone 'Europe/London' as date) as uk_date
    FROM silver.silver_sharpspring_leads
    ORDER BY created_at DESC
    LIMIT 5
""").fetchall()
for row in rows:
    print(f"  {row[0]}  →  {row[1]}")

print("\n=== Leads created today (UK time) ===")
r = con.execute("""
    SELECT COUNT(*) FROM silver.silver_sharpspring_leads
    WHERE cast(created_at at time zone 'Europe/London' as date) = current_date
    AND is_active = true
""").fetchone()
print(f"  Fresh leads today: {r[0]}")
