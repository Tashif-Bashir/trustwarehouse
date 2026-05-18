import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== All unique colleague_name values in wildix_calls ===")
rows = con.execute("""
    SELECT colleague_name, COUNT(*) cnt
    FROM silver.silver_wildix_calls
    WHERE colleague_name IS NOT NULL
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
for row in rows:
    print(f"  {row[0]:<30} {row[1]} calls")

print("\n=== All unique appointment_made_by in SharpSpring (booked only) ===")
rows = con.execute("""
    SELECT appointment_made_by, COUNT(*) cnt
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND appointment_made_by IS NOT NULL
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
for row in rows:
    print(f"  {row[0]:<30} {row[1]}")
