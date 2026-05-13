"""One-off script to save anonymised SharpSpring API fixtures for testing."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.sharpspring.client import SharpSpringClient


def anonymise_lead(lead: dict) -> dict:
    """Replace PII fields with placeholder values."""
    pii_fields = {
        "firstName", "lastName", "emailAddress", "phoneNumber",
        "officePhoneNumber", "mobilePhoneNumber", "faxNumber",
        "street", "city", "zipcode", "companyName", "description",
    }
    return {k: ("REDACTED" if k in pii_fields and v else v) for k, v in lead.items()}


def main():
    client = SharpSpringClient()
    fixtures_dir = Path("tests/fixtures/sharpspring")

    print("Fetching 3 leads...")
    leads = client.get_leads(limit=3)
    anonymised = [anonymise_lead(l) for l in leads]
    out = fixtures_dir / "sample_leads.json"
    out.write_text(json.dumps(anonymised, indent=2))
    print(f"  Saved {out}")

    print("Fetching campaigns...")
    campaigns = client.get_campaigns()
    out = fixtures_dir / "sample_campaigns.json"
    out.write_text(json.dumps(campaigns[:5], indent=2))
    print(f"  Saved {out}")

    print("Done.")


if __name__ == "__main__":
    main()
