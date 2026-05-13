"""Smoke test the Wildix client against both APIs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.wildix.client import WildixClient

c = WildixClient()

colleagues = c.get_all_colleagues()
print(f"Colleagues: {len(colleagues)}")
print(f"  Sample: ext={colleagues[0].get('extension')} name={colleagues[0].get('displayName') or colleagues[0].get('name')} dept={colleagues[0].get('department')}")

calls = c.get_calls_for_user(colleagues[0]["id"], date_from="2026-05-13T00:00:00Z")
print(f"Calls today for user {colleagues[0]['id']}: {len(calls)}")
if calls:
    c0 = calls[0]
    print(f"  Sample: status={c0.get('callStatus')} direction={c0.get('direction')} talkTime={c0.get('talkTime')}")

print("OK")
