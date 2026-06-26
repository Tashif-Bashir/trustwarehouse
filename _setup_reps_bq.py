"""One-time migration: creates BigQuery app.reps table and loads from reps.json."""
import json, os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from google.cloud import bigquery
from google.api_core.exceptions import Conflict

PROJECT   = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
TABLE     = f"{PROJECT}.app.reps"
REPS_FILE = Path(__file__).parent / "reps.json"

bq = bigquery.Client(project=PROJECT)

schema = [
    bigquery.SchemaField("name",         "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("email",        "STRING"),
    bigquery.SchemaField("regions",      "STRING"),   # JSON array
    bigquery.SchemaField("fallback",     "BOOL"),
    bigquery.SchemaField("freelancer",   "BOOL"),
    bigquery.SchemaField("weekend_days", "STRING"),   # JSON array of ints
    bigquery.SchemaField("aliases",      "STRING"),   # JSON array
    bigquery.SchemaField("created_at",   "TIMESTAMP"),
]

try:
    bq.create_table(bigquery.Table(TABLE, schema=schema))
    print(f"Table {TABLE}: created")
except Conflict:
    print(f"Table {TABLE}: already exists")

existing = list(bq.query(f"SELECT name FROM `{TABLE}`").result())
if existing:
    print(f"Table already has {len(existing)} rep(s), skipping migration")
else:
    reps = json.loads(REPS_FILE.read_text(encoding="utf-8")).get("reps", [])
    now  = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "name":         r["name"],
            "email":        r.get("email", ""),
            "regions":      json.dumps(r.get("regions", [])),
            "fallback":     bool(r.get("fallback", False)),
            "freelancer":   bool(r.get("freelancer", False)),
            "weekend_days": json.dumps(r.get("weekend_days", [])),
            "aliases":      json.dumps(r.get("aliases", [])),
            "created_at":   now,
        }
        for r in reps
    ]
    errors = bq.insert_rows_json(TABLE, rows)
    if errors:
        print(f"Migration errors: {errors}")
    else:
        print(f"Migrated {len(rows)} rep(s) to BigQuery")

print("Done.")
