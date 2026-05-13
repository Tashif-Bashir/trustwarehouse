"""Smoke test — hits the real SharpSpring API and prints results.

Run with: uv run python scripts/smoke_test_sharpspring.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.sharpspring.client import SharpSpringClient


def main():
    print("Connecting to SharpSpring...")
    client = SharpSpringClient()

    print("Fetching campaigns...")
    campaigns = client.get_campaigns()
    print(f"  {len(campaigns)} campaigns returned")

    if not campaigns:
        print("No campaigns found — check credentials or account data.")
        sys.exit(1)

    print("\nFirst 3 campaigns:")
    for c in campaigns[:3]:
        print(f"  {json.dumps(c, indent=4)}")

    print("\nFetching leads (first page)...")
    leads = client.get_leads(limit=5)
    print(f"  {len(leads)} leads returned (limited to 5)")
    if leads:
        print(f"  Sample lead keys: {list(leads[0].keys())}")
        print(f"  assignedTo value: {leads[0].get('assignedTo', 'N/A')}")

    print("\nSmoke test passed.")
    print("\nNOTE: getOwners/getUsers method name not yet confirmed for this account.")
    print("      Check assignedTo field in leads above to find owner IDs.")


if __name__ == "__main__":
    main()
