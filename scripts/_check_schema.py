import duckdb, os
from dotenv import load_dotenv
load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")

for table, schema in [("gold.gold_lead_activity", "gold"), ("silver.silver_sharpspring_leads", "silver")]:
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    need = ["is_sold", "customer_type", "appointment_date", "appointment_booked_at", "self_described_type"]
    print(f"\n{table}")
    print("  PRESENT:", [c for c in need if c in cols])
    print("  MISSING:", [c for c in need if c not in cols])
