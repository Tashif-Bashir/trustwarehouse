"""Verify converted_by and date fields on sold leads."""
import duckdb
import os
from dotenv import load_dotenv

load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")


def run(label, sql):
    print(f"\n=== {label} ===")
    for r in con.execute(sql).fetchall():
        print(r)


run("converted_by values on sold leads", """
    SELECT converted_by, count(*) n
    FROM silver.silver_sharpspring_leads
    WHERE is_sold = true AND converted_by IS NOT NULL
    GROUP BY 1 ORDER BY 2 DESC LIMIT 20
""")

run("order_confirmed_at population on sold leads", """
    SELECT
        count(*) total_sold,
        count(try_cast(order_confirmed_at as timestamp)) has_confirmed_at
    FROM silver.silver_sharpspring_leads
    WHERE is_sold = true
""")

run("domestic sold — by updated_at in last 7 working days", """
    SELECT first_name, last_name, appointment_status,
           cast(updated_at as date) as updated_date,
           cast(created_at as date) as created_date,
           try_cast(appt_amount as decimal(10,2)) as quote,
           try_cast(regexp_replace(deal_amount, ',', '', 'g') as decimal(10,2)) as deal
    FROM silver.silver_sharpspring_leads
    WHERE is_sold = true
      AND customer_type = 'domestic'
      AND cast(updated_at as date) BETWEEN '2026-05-07' AND '2026-05-15'
    ORDER BY updated_date DESC
    LIMIT 20
""")
