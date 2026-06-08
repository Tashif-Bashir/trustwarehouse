"""Entry point for the Meta Marketing API ingestion.

Usage:
    python -m ingestion.meta --verify                            # auth check, no writes
    python -m ingestion.meta --run                               # 7-day default
    python -m ingestion.meta --run --days 30                     # custom window
    python -m ingestion.meta --run --start-date 2024-01-01       # custom backfill
    python -m ingestion.meta --run --all-time                    # full history
"""

import argparse
import json
import sys


def _verify() -> int:
    from ingestion.meta.client import MetaClient, MetaConfigError, MetaAPIError

    try:
        info = MetaClient().verify()
    except MetaConfigError as e:
        print(f"CONFIG ERROR: {e}")
        return 2
    except MetaAPIError as e:
        print(f"API ERROR: {e}")
        return 1

    tok = info["token"]
    acc = info["account"]
    print(f"Token type:     {tok.get('type')}")
    print(f"Token valid:    {tok.get('is_valid')}")
    print(f"Token expires:  {'NEVER' if tok.get('expires_at') == 0 else tok.get('expires_at')}")
    print(f"Token scopes:   {tok.get('scopes')}")
    print(f"Account:        {acc.get('name')} ({acc.get('id')})")
    print(f"Currency:       {acc.get('currency')}  Timezone: {acc.get('timezone_name')}")
    return 0


def _run(days: int | None, start_date: str | None) -> int:
    from ingestion.meta.pipeline import run_pipeline

    if start_date:
        print(f"Running Meta API -> bronze pipeline (from {start_date} through today)...")
        run_pipeline(lookback_days=None, start_date=start_date)
    else:
        print(f"Running Meta API -> bronze pipeline (last {days} days through today)...")
        run_pipeline(lookback_days=days)
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ingestion.meta")
    p.add_argument("--verify", action="store_true", help="auth check, no writes")
    p.add_argument("--run", action="store_true", help="run the ingestion pipeline")
    p.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    p.add_argument("--start-date", type=str, default=None,
                   help="YYYY-MM-DD start date (overrides --days)")
    p.add_argument("--all-time", action="store_true",
                   help="pull from 2020-01-01 onwards (Meta retains 37+ months)")
    args = p.parse_args(argv)

    if args.verify:
        return _verify()
    if args.run:
        start_date = args.start_date
        if args.all_time:
            # Meta caps insights time_range to 37 months from today. We pick
            # ~36 months to stay safely inside that limit while pulling as
            # much history as the API will return.
            from datetime import date, timedelta
            start_date = (date.today() - timedelta(days=36 * 30)).isoformat()
        return _run(args.days, start_date)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
