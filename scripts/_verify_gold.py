"""Verify new columns landed correctly in silver and gold."""
import duckdb
import os
from dotenv import load_dotenv

load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")


def run(label, sql):
    print(f"\n=== {label} ===")
    for r in con.execute(sql).fetchall():
        print(r)


run("customer_type in silver", """
    SELECT customer_type, count(*) n
    FROM silver.silver_sharpspring_leads
    GROUP BY 1 ORDER BY 2 DESC
""")

run("domestic sold leads — appointment_date range", """
    SELECT count(*) total_sold_domestic,
           count(appointment_date) has_appt_date,
           min(appointment_date) earliest,
           max(appointment_date) latest
    FROM gold.gold_lead_activity
    WHERE is_sold = true AND customer_type = 'domestic'
""")

run("recent domestic sold leads", """
    SELECT first_name, last_name, appointment_status, appointment_date, created_date, quote_amount, deal_amount
    FROM gold.gold_lead_activity
    WHERE is_sold = true AND customer_type = 'domestic'
    ORDER BY created_date DESC
    LIMIT 10
""")

run("campaign attribution: sales by platform", """
    SELECT platform,
           sum(leads) leads,
           sum(appointments_booked) appts,
           sum(sales) sales,
           round(sum(spend_gbp) / nullif(sum(sales), 0), 2) blended_cps
    FROM gold.gold_campaign_attribution
    GROUP BY platform ORDER BY sales DESC
""")

run("agent performance: sales per agent", """
    SELECT agent_name,
           sum(appointments_booked) appts,
           sum(sales_confirmed) sales,
           sum(total_deal_value) deal_value
    FROM gold.gold_agent_performance_daily
    WHERE sales_confirmed > 0
    GROUP BY agent_name ORDER BY sales DESC
    LIMIT 10
""")
