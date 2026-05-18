import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== Row count in gold model ===")
r = con.execute("SELECT COUNT(*) FROM gold.gold_agent_performance_daily").fetchone()
print(f"Total rows: {r[0]}")

print("\n=== Sample rows (no filter) ===")
rows = con.execute(
    "SELECT date, agent_name, total_calls, appointments_booked FROM gold.gold_agent_performance_daily LIMIT 5"
).fetchall()
for row in rows:
    print(row)

print("\n=== colleague_name NULLs in silver_wildix_calls ===")
r = con.execute(
    "SELECT COUNT(*) total, COUNT(colleague_name) with_name FROM silver.silver_wildix_calls"
).fetchone()
print(f"Total: {r[0]}, With name: {r[1]}")

print("\n=== Sample dates in silver_wildix_calls COMPLETED ===")
rows = con.execute("""
    SELECT date_trunc('day', to_timestamp(start_time / 1000)) as call_date, COUNT(*)
    FROM silver.silver_wildix_calls
    WHERE call_status = 'COMPLETED'
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT 5
""").fetchall()
for row in rows:
    print(row)

print("\n=== appointment_made_by sample in silver_sharpspring_leads ===")
rows = con.execute("""
    SELECT appointment_made_by, COUNT(*) cnt
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND appointment_made_by IS NOT NULL
    GROUP BY 1
    ORDER BY 2 DESC
    LIMIT 10
""").fetchall()
for row in rows:
    print(row)

print("\n=== Date range in gold model ===")
rows = con.execute(
    "SELECT MIN(date), MAX(date), COUNT(*) FROM gold.gold_agent_performance_daily"
).fetchall()
for row in rows:
    print(row)
