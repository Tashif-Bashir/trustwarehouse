"""Drop all wildix_calls* tables and dlt state for the wildix pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.motherduck import get_connection

con = get_connection()

# Drop all wildix_calls child and parent tables
tables = con.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema='bronze' AND table_name LIKE 'wildix_calls%'"
).fetchall()
for (t,) in tables:
    con.execute(f"DROP TABLE IF EXISTS bronze.{t}")
    print(f"Dropped bronze.{t}")

# Drop bronze_staging schema if it exists (dlt staging area)
try:
    staging_tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='bronze_staging' AND table_name LIKE 'wildix_calls%'"
    ).fetchall()
    for (t,) in staging_tables:
        con.execute(f"DROP TABLE IF EXISTS bronze_staging.{t}")
        print(f"Dropped bronze_staging.{t}")
except Exception:
    pass

# Clear dlt pipeline state rows for wildix pipeline
try:
    con.execute("DELETE FROM bronze._dlt_pipeline_state WHERE pipeline_name='wildix'")
    print("Cleared dlt pipeline state for wildix")
except Exception as e:
    print(f"Could not clear pipeline state: {e}")

print("Done.")
