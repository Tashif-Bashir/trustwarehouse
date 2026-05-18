import duckdb
import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

token = os.environ["MOTHERDUCK_TOKEN"]
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={token}")

# last 7 working days (Mon–Fri) counting back from today
today = date.today()
working_days = []
d = today
while len(working_days) < 7:
    if d.weekday() < 5:
        working_days.append(d)
    d -= timedelta(days=1)
date_from = working_days[-1].isoformat()
date_to   = working_days[0].isoformat()
print(f"Window: {date_from} to {date_to}\n")

q = f"""
SELECT
    first_name,
    last_name,
    customer_type,
    appointment_status,
    appointment_date,
    appointment_booked_at,
    quote_amount,
    deal_amount,
    order_confirmed,
    created_date
FROM gold.gold_lead_activity
WHERE is_sold = true
  AND customer_type = 'domestic'
  AND appointment_date BETWEEN '{date_from}' AND '{date_to}'
ORDER BY appointment_date DESC
"""

rows = con.execute(q).fetchall()
print(f"{len(rows)} domestic sold leads (appointment_date {date_from} to {date_to})\n")
headers = ["first", "last", "type", "status", "appt_date", "booked_at", "quote", "deal", "confirmed", "created"]
print(" | ".join(f"{h:<14}" for h in headers))
print("-" * 130)
for r in rows:
    print(" | ".join(f"{str(x) if x is not None else '—':<14}" for x in r))
