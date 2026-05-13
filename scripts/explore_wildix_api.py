"""Test Wildix WMS + WDA APIs using simple Bearer tokens."""
import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

BASE_URL     = os.getenv("WILDIX_API_BASE_URL", "").rstrip("/")
SIMPLE_TOKEN = os.getenv("WILDIX_SIMPLE_TOKEN", "").strip()
WSK_TOKEN    = os.getenv("WILDIX_WSK_TOKEN", "").strip()

if not all([BASE_URL, SIMPLE_TOKEN, WSK_TOKEN]):
    missing = [k for k, v in {"WILDIX_API_BASE_URL": BASE_URL,
                               "WILDIX_SIMPLE_TOKEN": SIMPLE_TOKEN,
                               "WILDIX_WSK_TOKEN": WSK_TOKEN}.items() if not v]
    print(f"ERROR: missing {missing}")
    sys.exit(1)

WMS_BASE = BASE_URL
WDA_BASE = "https://wda.wildix.com"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def wms_get(path):
    url = WMS_BASE + "/api/v1/" + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {SIMPLE_TOKEN}", "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read().decode())


def wda_post(body, user_id):
    url = f"{WDA_BASE}/v2/history/user/calls?user={user_id}"
    req = urllib.request.Request(url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {WSK_TOKEN}",
                 "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read().decode())


print("=== Step 1: WMS — fetch colleagues ===")
try:
    data = wms_get("Colleagues/?limit=10&offset=0")
    users = data.get("result", {}).get("records", [])
    print(f"Success — {len(users)} users (first page of 10)")
    for u in users[:3]:
        print(f"  ext={u.get('extension')} name={u.get('displayName') or u.get('name')} "
              f"dept={u.get('department')} id={u.get('id')}")
    first_user_id = users[0].get("id") if users else None
except Exception as e:
    print(f"FAILED: {e}")
    first_user_id = None

print()
print("=== Step 2: WDA — fetch call history for first user ===")
if first_user_id:
    try:
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        end   = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = wda_post(
            {"limit": 5, "offset": 0, "filter": {"from": today, "to": end}},
            first_user_id,
        )
        calls = result.get("calls", [])
        print(f"Success — {len(calls)} calls today for user {first_user_id}")
        if calls:
            print(f"  Sample call keys: {list(calls[0].keys())}")
            print(f"  Sample call: {json.dumps(calls[0], indent=2)[:600]}")
    except Exception as e:
        print(f"FAILED: {e}")
else:
    print("Skipped — no user ID from step 1")
