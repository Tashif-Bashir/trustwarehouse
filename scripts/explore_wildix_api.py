"""Probe WMS API for all available endpoints."""
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

BASE_URL     = os.getenv("WILDIX_API_BASE_URL", "").rstrip("/")
SIMPLE_TOKEN = os.getenv("WILDIX_SIMPLE_TOKEN", "").strip()

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def wms_get(path):
    url = BASE_URL + "/api/v1/" + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {SIMPLE_TOKEN}", "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            body = json.loads(r.read().decode())
            print(f"  200  /api/v1/{path}")
            print(f"       keys: {list(body.keys())}")
            result = body.get("result", {})
            if isinstance(result, dict):
                print(f"       result keys: {list(result.keys())}")
                records = result.get("records", result.get("items", []))
                if records:
                    print(f"       sample record keys: {list(records[0].keys())}")
                    print(f"       count: {len(records)}")
            elif isinstance(result, list) and result:
                print(f"       result is list, len={len(result)}, sample keys: {list(result[0].keys())}")
            return body
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  {e.code}  /api/v1/{path}")
    except Exception as e:
        print(f"  ERR  /api/v1/{path}  {e}")
    return None


print("=== Probing WMS API endpoints ===\n")

endpoints = [
    "Colleagues/", "Users/", "Extensions/",
    "Queues/", "Queues/?limit=100&offset=0",
    "IVR/", "Ivr/",
    "Recordings/", "Recordings/?limit=10&offset=0",
    "Voicemails/", "Messages/",
    "Departments/", "Groups/",
    "Trunks/", "Phones/", "Devices/",
    "CallHistory/", "CDR/", "Calls/",
    "Statistics/", "Reports/",
    "Contacts/", "Numbers/",
    "Settings/", "Info/", "System/",
    "Licenses/",
]

for ep in endpoints:
    wms_get(ep)
