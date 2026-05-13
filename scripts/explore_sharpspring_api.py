"""Probe SharpSpring API to discover which methods are available and useful.

Run with: uv run python scripts/explore_sharpspring_api.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.sharpspring.client import SharpSpringClient, SharpSpringError


def try_method(client, method, params, result_key=None):
    try:
        result = client._call(method, params)
        if result is None:
            print(f"  {method}: returned None")
            return None
        if result_key:
            items = result.get(result_key, [])
            print(f"  {method}: OK — {len(items)} {result_key}(s)")
            return items
        print(f"  {method}: OK — keys: {list(result.keys())}")
        return result
    except SharpSpringError as e:
        print(f"  {method}: FAILED — {e}")
        return None


def main():
    client = SharpSpringClient()
    std = {"where": {}, "limit": 5, "offset": 0}

    print("\n=== Testing methods ===")
    results = {}

    results["fields"] = try_method(client, "getFields", std, "field")
    results["activities"] = try_method(client, "getActivityTypes", std, "activityType")
    results["activities2"] = try_method(client, "getActivities", std, "activity")
    results["members"] = try_method(client, "getMembers", std, "member")
    results["users"] = try_method(client, "getUsers", {}, "user")
    results["deal_stages"] = try_method(client, "getDealStages", std, "dealStage")
    results["pipelines"] = try_method(client, "getPipelines", std, "pipeline")
    results["accounts"] = try_method(client, "getAccounts", std, "account")
    results["tasks"] = try_method(client, "getTasks", std, "task")
    results["events"] = try_method(client, "getEvents", std, "event")
    results["email_jobs"] = try_method(client, "getEmailJobs", std, "emailJob")
    results["lead_statuses"] = try_method(client, "getLeadStatuses", {}, "leadStatus")

    print("\n=== Saving successful results ===")
    fixtures_dir = Path("tests/fixtures/sharpspring")
    for name, data in results.items():
        if data:
            out = fixtures_dir / f"sample_{name}.json"
            out.write_text(json.dumps(data[:3] if isinstance(data, list) else data, indent=2))
            print(f"  Saved {out}")

    print("\n=== Field definitions (first 10) ===")
    if results.get("fields"):
        for f in results["fields"][:10]:
            print(f"  {f.get('systemName', '?')} → label: {f.get('label', '?')} | type: {f.get('dataType', '?')}")


if __name__ == "__main__":
    main()
