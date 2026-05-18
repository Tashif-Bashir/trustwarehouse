import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== appointment_booked_at coverage for booked appointments ===")
r = con.execute("""
    SELECT
        COUNT(*) as total_booked,
        SUM(CASE WHEN appointment_booked_at IS NOT NULL THEN 1 ELSE 0 END) as has_booked_at,
        SUM(CASE WHEN appointment_booked_at IS NULL THEN 1 ELSE 0 END) as missing_booked_at
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
""").fetchone()
print(f"Total booked appointments: {r[0]}")
print(f"  Has appointment_booked_at: {r[1]} ({round(r[1]/r[0]*100,1)}%)")
print(f"  Missing:                   {r[2]} ({round(r[2]/r[0]*100,1)}%)")

print("\n=== Appointments booked on 2026-05-14 by field ===")
rows = con.execute("""
    SELECT
        agent_name,
        COUNT(*) as appts
    FROM (
        SELECT
            case
                when lower(appointment_made_by) in ('lily', 'lily harpham')          then 'Lily'
                when lower(appointment_made_by) in ('sue', 'susan england')           then 'Sue'
                when lower(appointment_made_by) in ('dec', 'declan franks')           then 'Dec'
                when lower(appointment_made_by) in ('alisha', 'alisha moore')         then 'Alisha'
                else appointment_made_by
            end as agent_name
        FROM silver.silver_sharpspring_leads
        WHERE appointment_booked = 'Yes'
        AND appointment_made_by IS NOT NULL
        AND appointment_booked_at IS NOT NULL
        AND date_trunc('day', try_cast(appointment_booked_at as timestamp)) = DATE '2026-05-14'
    )
    GROUP BY 1
    ORDER BY 2 DESC
""").fetchall()
print("Appointments with booked_at = 2026-05-14:")
for row in rows:
    print(f"  {row[0]}: {row[1]}")

print("\n=== What day range has the most appointment_booked_at data? ===")
rows = con.execute("""
    SELECT
        date_trunc('month', try_cast(appointment_booked_at as timestamp)) as month,
        COUNT(*) as cnt
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND appointment_booked_at IS NOT NULL
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT 6
""").fetchall()
for row in rows:
    print(f"  {row[0]}: {row[1]} appointments")
