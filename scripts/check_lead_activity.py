import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== Row count and lead_type breakdown ===")
rows = con.execute("""
    SELECT lead_type, COUNT(*) cnt
    FROM gold.gold_lead_activity
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
total = sum(r[1] for r in rows)
for row in rows:
    print(f"  {str(row[0]):<12} {row[1]:>6}  ({round(row[1]/total*100,1)}%)")
print(f"  {'TOTAL':<12} {total:>6}")

print("\n=== Backlog stats ===")
r = con.execute("""
    SELECT
        COUNT(*) as total_backlog,
        SUM(CASE WHEN called_today THEN 1 ELSE 0 END) as worked_today,
        SUM(CASE WHEN NOT has_been_called THEN 1 ELSE 0 END) as never_called,
        ROUND(AVG(total_call_attempts), 1) as avg_attempts
    FROM gold.gold_lead_activity
    WHERE lead_type = 'backlog'
""").fetchone()
print(f"  Total backlog: {r[0]}")
print(f"  Worked today:  {r[1]} ({round(r[1]/r[0]*100,1)}%)")
print(f"  Never called:  {r[2]} ({round(r[2]/r[0]*100,1)}%)")
print(f"  Avg attempts:  {r[3]}")

print("\n=== mins_to_first_call distribution (all leads that were called) ===")
rows = con.execute("""
    SELECT
        SUM(CASE WHEN mins_to_first_call <= 5 THEN 1 ELSE 0 END)   as within_5_min,
        SUM(CASE WHEN mins_to_first_call <= 10 THEN 1 ELSE 0 END)  as within_10_min,
        SUM(CASE WHEN mins_to_first_call > 10 THEN 1 ELSE 0 END)   as over_10_min,
        COUNT(mins_to_first_call)                                   as total_called,
        ROUND(AVG(mins_to_first_call), 1)                           as avg_mins
    FROM gold.gold_lead_activity
    WHERE lead_type IN ('fresh', 'backlog')
    AND mins_to_first_call IS NOT NULL
""").fetchone()
print(f"  Called leads: {r[3]}")
print(f"  Called <=5 min: {rows[0]}")
print(f"  Called <=10 min: {rows[1]}")
print(f"  Called >10 min: {rows[2]}")
print(f"  Average mins to first call: {rows[4]}")

print("\n=== Sample backlog leads called today ===")
rows = con.execute("""
    SELECT
        first_name, last_name, lead_status, domestic_lead_status,
        total_call_attempts, last_call_agent, mins_to_first_call
    FROM gold.gold_lead_activity
    WHERE lead_type = 'backlog'
    AND called_today = true
    LIMIT 5
""").fetchall()
for row in rows:
    print(f"  {row[0]} {row[1]} | status={row[2]} | domestic={row[3]} | attempts={row[4]} | agent={row[5]} | mins_first={row[6]}")
