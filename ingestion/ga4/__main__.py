"""Entry point for GA4 Data API ingestion.

Usage:
    python -m ingestion.ga4 --verify                            # auth check, no writes
    python -m ingestion.ga4 --run                               # default 7-day pull
    python -m ingestion.ga4 --run --days 30                     # custom window
    python -m ingestion.ga4 --run --start-date 2024-01-01       # custom backfill
    python -m ingestion.ga4 --run --all-time                    # full property history
"""

import argparse
import sys


def _verify() -> int:
    from ingestion.ga4.client import GA4Client

    try:
        info = GA4Client().verify()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    print(f"Auth OK. Property ID: {info['property_id']}")
    rows = info["yesterday_rows"]
    if rows:
        print(f"Yesterday sessions: {rows[0].get('sessions')}")
    else:
        print("Yesterday returned no rows (property may be inactive).")
    return 0


def _run(days: int | None, start_date: str | None) -> int:
    from ingestion.ga4.pipeline import run_pipeline

    if start_date:
        print(f"Running GA4 -> bronze pipeline (from {start_date} through today)...")
        run_pipeline(lookback_days=None, start_date=start_date)
    else:
        print(f"Running GA4 -> bronze pipeline (last {days} days through today)...")
        run_pipeline(lookback_days=days)
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ingestion.ga4")
    p.add_argument("--verify", action="store_true", help="auth check, no writes")
    p.add_argument("--run", action="store_true", help="run the ingestion pipeline")
    p.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    p.add_argument("--start-date", type=str, default=None,
                   help="YYYY-MM-DD start date (overrides --days)")
    p.add_argument("--all-time", action="store_true",
                   help="pull from 2022-01-01 onwards (most properties only retain ~14mo)")
    args = p.parse_args(argv)

    if args.verify:
        return _verify()
    if args.run:
        start_date = args.start_date
        if args.all_time:
            start_date = "2022-01-01"
        return _run(args.days, start_date)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
