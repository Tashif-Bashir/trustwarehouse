import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== Lily's appointments where booked_at = 2026-05-14 ===")
rows = con.execute("""
    SELECT
        lead_id,
        first_name,
        last_name,
        appointment_made_by,
        appointment_booked_at,
        appointment_booked,
        updated_at::date as updated_date
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND lower(appointment_made_by) in ('lily', 'lily harpham')
    AND date_trunc('day', try_cast(appointment_booked_at as timestamp)) = DATE '2026-05-14'
""").fetchall()
print(f"With appointment_booked_at = 2026-05-14: {len(rows)}")
for row in rows:
    print(f"  {row}")

print("\n=== Lily appointments with booked_at NULL but updated_at = 2026-05-14 ===")
rows = con.execute("""
    SELECT
        lead_id,
        first_name,
        last_name,
        appointment_made_by,
        appointment_booked_at,
        updated_at::date as updated_date
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND lower(appointment_made_by) in ('lily', 'lily harpham')
    AND appointment_booked_at IS NULL
    AND updated_at::date = DATE '2026-05-14'
""").fetchall()
print(f"Missing booked_at but updated 2026-05-14: {len(rows)}")
for row in rows:
    print(f"  {row}")

print("\n=== ALL Lily appointments with booked_at near 2026-05-14 ===")
rows = con.execute("""
    SELECT
        lead_id,
        first_name,
        last_name,
        appointment_made_by,
        appointment_booked_at,
        updated_at
    FROM silver.silver_sharpspring_leads
    WHERE appointment_booked = 'Yes'
    AND lower(appointment_made_by) in ('lily', 'lily harpham')
    AND (
        (appointment_booked_at IS NOT NULL AND try_cast(appointment_booked_at as timestamp) >= TIMESTAMP '2026-05-13 00:00:00' AND try_cast(appointment_booked_at as timestamp) < TIMESTAMP '2026-05-16 00:00:00')
        OR
        (appointment_booked_at IS NULL AND updated_at >= TIMESTAMP '2026-05-13 00:00:00' AND updated_at < TIMESTAMP '2026-05-16 00:00:00')
    )
    ORDER BY coalesce(appointment_booked_at, updated_at::varchar) DESC
""").fetchall()
print(f"All Lily appointments in that date window: {len(rows)}")
for row in rows:
    print(f"  booked_at={row[4]}, updated={row[5]}, name={row[2]} {row[3]}, id={row[0]}")
