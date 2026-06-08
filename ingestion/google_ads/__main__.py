"""Entry point for the Google Ads API ingestion.

Usage:
    python -m ingestion.google_ads --verify                          # auth check
    python -m ingestion.google_ads --run                             # 30-day default
    python -m ingestion.google_ads --run --days 7                    # daily window
    python -m ingestion.google_ads --run --start-date 2024-01-01     # custom backfill
    python -m ingestion.google_ads --run --all-time                  # full history (~5 yrs)
"""

import argparse
import sys


def _verify() -> int:
    from ingestion.google_ads.client import (
        GoogleAdsConfigError,
        list_accessible_customers,
        operating_customer_id,
    )

    try:
        customers = list_accessible_customers()
    except GoogleAdsConfigError as e:
        print(f"CONFIG ERROR: {e}")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"API ERROR: {type(e).__name__}: {e}")
        return 1

    print(f"Auth OK. Refresh token can access {len(customers)} customer(s):")
    for resource_name in customers:
        print(f"  {resource_name}")

    cid = operating_customer_id()
    if cid:
        print(f"\nOperating customer ID (from env): {cid}")
    else:
        print("\nWARNING: No GOOGLE_ADS_CUSTOMER_ID or GOOGLE_ADS_LOGIN_CUSTOMER_ID set.")

    return 0


def _run(days: int | None, start_date: str | None) -> int:
    from ingestion.google_ads.pipeline import run_pipeline

    if start_date:
        print(f"Running Google Ads API -> bronze pipeline (from {start_date} through today)...")
        run_pipeline(lookback_days=None, start_date=start_date)
    else:
        print(f"Running Google Ads API -> bronze pipeline (last {days} days through today)...")
        run_pipeline(lookback_days=days)
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ingestion.google_ads")
    p.add_argument("--verify", action="store_true", help="auth check, no writes")
    p.add_argument("--run", action="store_true", help="run the ingestion pipeline")
    p.add_argument("--days", type=int, default=30, help="lookback window in days (default 30)")
    p.add_argument("--start-date", type=str, default=None,
                   help="YYYY-MM-DD start date (overrides --days)")
    p.add_argument("--all-time", action="store_true",
                   help="pull from 2020-01-01 onwards (~5 years; Google retains 63 months)")
    args = p.parse_args(argv)

    if args.verify:
        return _verify()
    if args.run:
        start_date = args.start_date
        if args.all_time:
            start_date = "2020-01-01"
        return _run(args.days, start_date)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
