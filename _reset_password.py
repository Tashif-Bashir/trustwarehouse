"""Reset a user's password in BigQuery. Usage: python _reset_password.py <username> <newpassword>"""
import sys, hashlib, os, secrets
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
from google.cloud import bigquery

if len(sys.argv) != 3:
    print("Usage: python _reset_password.py <username> <newpassword>")
    sys.exit(1)

username, new_pw = sys.argv[1], sys.argv[2]
salt = secrets.token_hex(16)
h    = hashlib.pbkdf2_hmac("sha256", new_pw.encode(), salt.encode(), 260000)
ph   = f"pbkdf2:sha256:{salt}:{h.hex()}"
now  = datetime.now(timezone.utc).isoformat()

bq = bigquery.Client(project="trustwarehouse")
job = bq.query(
    "UPDATE `trustwarehouse.app.users` SET password_hash = @h, updated_at = @t WHERE username = @u",
    job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("h", "STRING", ph),
        bigquery.ScalarQueryParameter("t", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("u", "STRING", username),
    ]),
)
job.result()
print(f"Password for '{username}' updated.")
