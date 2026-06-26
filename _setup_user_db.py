"""
One-time setup: creates BigQuery app.users table and GCS avatar bucket,
then migrates existing users from users.json.
"""
import json, os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from google.cloud import bigquery, storage
from google.api_core.exceptions import Conflict, NotFound

PROJECT   = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
DATASET   = "app"
TABLE     = f"{PROJECT}.{DATASET}.users"
GCS_BUCKET = os.environ.get("GCS_AVATAR_BUCKET", f"{PROJECT}-avatars")

bq  = bigquery.Client(project=PROJECT)
gcs = storage.Client(project=PROJECT)

# ── BigQuery dataset ──────────────────────────────────────────────────────────
try:
    bq.create_dataset(f"{PROJECT}.{DATASET}", exists_ok=True)
    print(f"Dataset {DATASET}: ready")
except Exception as e:
    print(f"Dataset warning: {e}")

# ── BigQuery table ────────────────────────────────────────────────────────────
schema = [
    bigquery.SchemaField("username",      "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("password_hash", "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("name",          "STRING"),
    bigquery.SchemaField("email",         "STRING"),
    bigquery.SchemaField("role",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("photo_url",     "STRING"),
    bigquery.SchemaField("created_at",    "TIMESTAMP"),
    bigquery.SchemaField("updated_at",    "TIMESTAMP"),
]
table_ref = bigquery.Table(TABLE, schema=schema)
try:
    bq.create_table(table_ref)
    print(f"Table {TABLE}: created")
except Conflict:
    print(f"Table {TABLE}: already exists")

# ── GCS bucket ────────────────────────────────────────────────────────────────
try:
    bucket = gcs.create_bucket(GCS_BUCKET, location="EU")
    print(f"Bucket {GCS_BUCKET}: created")
except Conflict:
    bucket = gcs.bucket(GCS_BUCKET)
    print(f"Bucket {GCS_BUCKET}: already exists")

# Make bucket publicly readable for profile photos
try:
    policy = bucket.get_iam_policy(requested_policy_version=3)
    policy.bindings.append({
        "role": "roles/storage.objectViewer",
        "members": {"allUsers"},
    })
    bucket.set_iam_policy(policy)
    print("Bucket IAM: allUsers objectViewer set")
except Exception as e:
    print(f"Bucket IAM warning (may already be set): {e}")

# ── Migrate users.json → BigQuery ─────────────────────────────────────────────
users_file = Path(__file__).parent / "availability_app" / "users.json"
if not users_file.exists():
    print("No users.json found, skipping migration")
else:
    # Check if table already has rows
    existing = list(bq.query(f"SELECT username FROM `{TABLE}`").result())
    if existing:
        print(f"Table already has {len(existing)} user(s), skipping migration")
    else:
        users = json.loads(users_file.read_text()).get("users", [])
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "username":      u["username"],
                "password_hash": u["password_hash"],
                "name":          u.get("name", u["username"]),
                "email":         u.get("email", ""),
                "role":          u.get("role", "user"),
                "photo_url":     None,
                "created_at":    now,
                "updated_at":    now,
            }
            for u in users
        ]
        errors = bq.insert_rows_json(TABLE, rows)
        if errors:
            print(f"Migration errors: {errors}")
        else:
            print(f"Migrated {len(rows)} user(s) to BigQuery")

print("\nDone. Add to .env if not already there:")
print(f"  GCS_AVATAR_BUCKET={GCS_BUCKET}")
