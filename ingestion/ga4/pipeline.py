"""dlt pipeline — GA4 Data API → BigQuery bronze.

Replaces the previous slim direct-API module (which only produced
ga4direct_session_source_medium) and Airbyte's GA4 sync. Produces seven
bronze tables covering everything the dashboard needs plus the broader
dimensional cuts useful for downstream ML work.

Bronze tables produced:
  - ga4_api_sessions_daily       sessions × source/medium/device/country
  - ga4_api_pages_daily          page-level views + engagement
  - ga4_api_landing_pages_daily  landing page × source/medium (attribution)
  - ga4_api_events_daily         event counts × source
  - ga4_api_geographic_daily     sessions × country/region/city
  - ga4_api_temporal_daily       sessions × hour × dayOfWeek × device
  - ga4_api_demographics_daily   sessions × age × gender

All use `replace` write_disposition over a rolling lookback window. Long
backfills chunk by month to stay inside GA4's per-response row limit.
"""

import os
from datetime import date, timedelta
from typing import Iterator

import dlt
from dotenv import load_dotenv

from ingestion.ga4.client import GA4Client

load_dotenv()


# ----- report definitions --------------------------------------------------
#
# Each report's `primary_key` is the FULL set of dimension columns (snake_case)
# — that lets dlt merge-mode update only the rows in the rolling window and
# preserve everything else, instead of replace-mode wiping the table each run.

REPORTS = {
    "ga4_api_sessions_daily": {
        "dimensions": ["date", "sessionSource", "sessionMedium", "deviceCategory", "country"],
        "metrics": [
            "sessions",
            "totalUsers",
            "newUsers",
            "bounceRate",
            "averageSessionDuration",
            "screenPageViews",
            "userEngagementDuration",
            "conversions",
        ],
        "primary_key": ["date", "session_source", "session_medium", "device_category", "country"],
    },
    "ga4_api_pages_daily": {
        "dimensions": ["date", "pagePath"],
        "metrics": [
            "screenPageViews",
            "totalUsers",
            "userEngagementDuration",
            "bounceRate",
        ],
        "primary_key": ["date", "page_path"],
    },
    "ga4_api_landing_pages_daily": {
        "dimensions": ["date", "landingPagePlusQueryString", "sessionSource", "sessionMedium"],
        "metrics": [
            "sessions",
            "conversions",
            "bounceRate",
            "engagedSessions",
            "userEngagementDuration",
        ],
        "primary_key": ["date", "landing_page_plus_query_string", "session_source", "session_medium"],
    },
    "ga4_api_events_daily": {
        "dimensions": ["date", "eventName", "sessionSource"],
        "metrics": ["eventCount", "eventCountPerUser", "totalUsers"],
        "primary_key": ["date", "event_name", "session_source"],
    },
    "ga4_api_geographic_daily": {
        "dimensions": ["date", "country", "region", "city"],
        "metrics": ["sessions", "totalUsers", "newUsers", "conversions"],
        "primary_key": ["date", "country", "region", "city"],
    },
    "ga4_api_temporal_daily": {
        "dimensions": ["date", "hour", "dayOfWeek", "deviceCategory"],
        "metrics": ["sessions", "totalUsers", "newUsers", "screenPageViews"],
        "primary_key": ["date", "hour", "day_of_week", "device_category"],
    },
    "ga4_api_demographics_daily": {
        "dimensions": ["date", "userAgeBracket", "userGender"],
        "metrics": ["sessions", "totalUsers"],
        "primary_key": ["date", "user_age_bracket", "user_gender"],
    },
}


# ----- helpers -------------------------------------------------------------

def _chunk_dates(since: str, until: str, chunk_days: int = 31):
    """Yield (chunk_start, chunk_end) covering [since, until] in chunk_days
    windows. GA4 caps a single response at 100k rows — chunking by month keeps
    each call well below that for backfills."""
    s = date.fromisoformat(since)
    u = date.fromisoformat(until)
    cur = s
    while cur <= u:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), u)
        yield cur.isoformat(), chunk_end.isoformat()
        cur = chunk_end + timedelta(days=1)


# ----- resources -----------------------------------------------------------

def _make_resource(table_name: str, spec: dict, since: str, until: str):
    @dlt.resource(
        name=table_name,
        write_disposition="merge",
        primary_key=spec["primary_key"],
    )
    def report_resource():
        client = GA4Client()
        for chunk_since, chunk_until in _chunk_dates(since, until, chunk_days=31):
            print(f"  GA4 {table_name}: {chunk_since} -> {chunk_until}")
            for row in client.run_report(
                dimensions=spec["dimensions"],
                metrics=spec["metrics"],
                since=chunk_since,
                until=chunk_until,
            ):
                yield row
    return report_resource


def run_pipeline(lookback_days: int | None = 7, start_date: str | None = None) -> None:
    """Pull GA4 data into bronze across all seven reports.

    Daily run: lookback_days=7 catches any late-arriving GA4 data.
    Backfill: pass start_date='2022-01-01' (or use --all-time in __main__).
    """
    end = date.today()
    if start_date:
        since = start_date
    elif lookback_days:
        since = (end - timedelta(days=lookback_days - 1)).isoformat()
    else:
        raise ValueError("Either lookback_days or start_date must be provided.")
    until = end.isoformat()

    pipeline = dlt.pipeline(
        pipeline_name="ga4_api",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )

    resources = [
        _make_resource(table_name, spec, since, until)()
        for table_name, spec in REPORTS.items()
    ]

    load_info = pipeline.run(resources)
    print(load_info)
