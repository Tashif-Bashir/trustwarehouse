"""Verify SharpSpring data landed in bronze schema."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.motherduck import get_connection

con = get_connection()

tables = ["sharpspring_leads", "sharpspring_campaigns", "sharpspring_opportunities",
          "sharpspring_fields", "sharpspring_deal_stages"]

for table in tables:
    try:
        count = con.execute(f"SELECT COUNT(*) FROM bronze.{table}").fetchone()[0]
        print(f"bronze.{table}: {count} rows")
    except Exception as e:
        print(f"bronze.{table}: ERROR — {e}")
