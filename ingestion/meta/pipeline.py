"""dlt pipeline — Meta Marketing API → BigQuery bronze (campaign-level daily).

Phase 1 minimum viable replacement for Airbyte's `facebook_adsads_insights`.
Produces `bronze.meta_api_campaign_daily` at campaign × date granularity.

Write disposition is `replace` — each run rewrites the rolling window in full.
Meta revises attribution within ~28 days, so a 7-day rolling window per
scheduled run catches the bulk of late-arriving conversions without re-pulling
all history each time. All-time backfill is done explicitly via --all-time.
"""

import json
import os
import time
from datetime import date, timedelta

import dlt
from dotenv import load_dotenv

from ingestion.meta.client import MetaClient

load_dotenv()


_AD_DAILY_FIELDS = [
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "impressions",
    "spend",
    "reach",
    "frequency",
    "cpm",
    "cpc",
    "inline_link_clicks",
    "cost_per_inline_link_click",
    "actions",
    "cost_per_action_type",
    "date_start",
    "date_stop",
]

_AD_CREATIVE_FIELDS = [
    "id",
    "name",
    "status",
    "effective_status",
    "updated_time",
    "creative{id,name,thumbnail_url,object_story_spec,asset_feed_spec}",
]

# No filtering param at all — confirmed live: /act_X/ads with no filter
# already excludes DELETED ads by default (7-page, 3,063-row pull with no
# filter showed only ACTIVE/PAUSED/ADSET_PAUSED/CAMPAIGN_PAUSED/WITH_ISSUES,
# never DELETED), so an explicit "exclude DELETED" filter would be a no-op.

_CAMPAIGN_FIELDS = [
    "id",
    "name",
    "status",
    "effective_status",
    "updated_time",
    "objective",
]

_ADSET_FIELDS = [
    "id",
    "name",
    "campaign_id",
    "status",
    "effective_status",
    "updated_time",
]


_GEO_FIELDS = [
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "reach",
    "date_start",
    "date_stop",
]


def _row_campaign_daily(row: dict) -> dict:
    def _f(key: str, default=None):
        v = row.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _i(key: str, default=None):
        v = row.get(key)
        try:
            return int(float(v)) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "date": row.get("date_start"),
        "account_id": row.get("account_id"),
        "account_currency": row.get("account_currency"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "objective": row.get("objective"),
        "spend_gbp": _f("spend"),
        "impressions": _i("impressions"),
        "clicks": _i("clicks"),
        "unique_clicks": _i("unique_clicks"),
        "reach": _i("reach"),
        "frequency": _f("frequency"),
        "cpc": _f("cpc"),
        "cpm": _f("cpm"),
        "ctr": _f("ctr"),
    }


def _row_ad_daily(row: dict) -> dict:
    def _f(key: str, default=None):
        v = row.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _i(key: str, default=None):
        v = row.get(key)
        try:
            return int(float(v)) if v is not None else default
        except (TypeError, ValueError):
            return default

    def _j(key: str):
        # actions / cost_per_action_type land RAW as JSON strings — bronze
        # rule: no unnesting, no opinions on which action_type matters.
        v = row.get(key)
        return json.dumps(v) if v is not None else None

    return {
        "date": row.get("date_start"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "adset_id": row.get("adset_id"),
        "adset_name": row.get("adset_name"),
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "impressions": _i("impressions"),
        "spend_gbp": _f("spend"),
        "reach": _i("reach"),
        "frequency": _f("frequency"),
        "cpm": _f("cpm"),
        "cpc": _f("cpc"),
        "inline_link_clicks": _i("inline_link_clicks"),
        "cost_per_inline_link_click": _f("cost_per_inline_link_click"),
        "actions": _j("actions"),
        "cost_per_action_type": _j("cost_per_action_type"),
    }


def _row_ad_creative(row: dict) -> dict:
    creative = row.get("creative") or {}

    def _j(value):
        return json.dumps(value) if value is not None else None

    return {
        "ad_id": row.get("id"),
        "ad_name": row.get("name"),
        "status": row.get("status"),
        "effective_status": row.get("effective_status"),
        "updated_time": row.get("updated_time"),
        "creative_id": creative.get("id"),
        "creative_name": creative.get("name"),
        "thumbnail_url": creative.get("thumbnail_url"),
        "object_story_spec": _j(creative.get("object_story_spec")),
        "asset_feed_spec": _j(creative.get("asset_feed_spec")),
    }


def _row_campaign(row: dict) -> dict:
    return {
        "campaign_id": row.get("id"),
        "campaign_name": row.get("name"),
        "status": row.get("status"),
        "effective_status": row.get("effective_status"),
        "updated_time": row.get("updated_time"),
        "objective": row.get("objective"),
    }


def _row_adset(row: dict) -> dict:
    return {
        "adset_id": row.get("id"),
        "adset_name": row.get("name"),
        "campaign_id": row.get("campaign_id"),
        "status": row.get("status"),
        "effective_status": row.get("effective_status"),
        "updated_time": row.get("updated_time"),
    }


def _chunk_dates(since: str, until: str, chunk_days: int = 90):
    """Yield (chunk_start, chunk_end) pairs covering [since, until] in
    chunk_days windows. Meta's insights endpoint times out on very long ranges
    so we chunk to keep individual responses small."""
    s = date.fromisoformat(since)
    u = date.fromisoformat(until)
    cur = s
    while cur <= u:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), u)
        yield cur.isoformat(), chunk_end.isoformat()
        cur = chunk_end + timedelta(days=1)


def _campaign_daily_resource(since: str, until: str):
    @dlt.resource(
        name="meta_api_campaign_daily",
        write_disposition="merge",
        primary_key=["date", "campaign_id"],
    )
    def campaign_daily():
        client = MetaClient()
        for chunk_since, chunk_until in _chunk_dates(since, until, chunk_days=90):
            print(f"  Meta chunk: {chunk_since} -> {chunk_until}")
            for row in client.insights(
                level="campaign", since=chunk_since, until=chunk_until, time_increment=1
            ):
                yield _row_campaign_daily(row)
    return campaign_daily


def _geographic_daily_resource(since: str, until: str):
    @dlt.resource(
        name="meta_api_geographic_daily",
        write_disposition="merge",
        primary_key=["date", "campaign_id", "region"],
    )
    def geographic_daily():
        client = MetaClient()
        for chunk_since, chunk_until in _chunk_dates(since, until, chunk_days=90):
            print(f"  Meta geo chunk: {chunk_since} -> {chunk_until}")
            for row in client.insights(
                level="campaign",
                breakdowns=["region"],
                fields=_GEO_FIELDS,
                since=chunk_since,
                until=chunk_until,
                time_increment=1,
            ):
                region = row.get("region") or ""
                yield {
                    "date": row.get("date_start"),
                    "campaign_id": row.get("campaign_id"),
                    "campaign_name": row.get("campaign_name"),
                    "region": region if region else None,
                    "spend_gbp": float(row.get("spend") or 0),
                    "impressions": int(float(row.get("impressions") or 0)),
                    "clicks": int(float(row.get("clicks") or 0)),
                    "reach": int(float(row.get("reach") or 0)),
                }
    return geographic_daily


def _ad_daily_resource(since: str, until: str):
    @dlt.resource(
        name="meta_api_ad_daily",
        write_disposition="merge",
        primary_key=["date", "ad_id"],
    )
    def ad_daily():
        client = MetaClient()
        # level=ad + time_increment=1 reliably 400s (subcode 1504018) beyond
        # ~15-day windows — chunk tighter than the campaign-level pull. A
        # short pause between chunks avoids the app-level "Application
        # request limit reached" 403 (subcode 1504022) confirmed live during
        # backfill testing — polite pacing per the brief.
        chunks = list(_chunk_dates(since, until, chunk_days=15))
        for i, (chunk_since, chunk_until) in enumerate(chunks):
            print(f"  Meta ad-daily chunk: {chunk_since} -> {chunk_until}")
            for row in client.insights(
                level="ad",
                fields=_AD_DAILY_FIELDS,
                since=chunk_since,
                until=chunk_until,
                time_increment=1,
            ):
                yield _row_ad_daily(row)
            if i < len(chunks) - 1:
                time.sleep(5)

    return ad_daily


def _ad_creatives_resource():
    @dlt.resource(
        name="meta_api_ad_creatives",
        write_disposition="replace",
    )
    def ad_creatives():
        client = MetaClient()
        # No effective_status filter — all ads regardless of status (Meta
        # excludes DELETED from this edge by default, confirmed live).
        # page_limit=100: the default 500-row page 500s here once
        # object_story_spec/asset_feed_spec are requested (confirmed live).
        for row in client.ads(fields=_AD_CREATIVE_FIELDS, filtering=None, page_limit=100):
            yield _row_ad_creative(row)

    return ad_creatives


def _campaigns_resource():
    @dlt.resource(
        name="meta_api_campaigns",
        write_disposition="replace",
    )
    def campaigns():
        client = MetaClient()
        for row in client.campaigns(fields=_CAMPAIGN_FIELDS):
            yield _row_campaign(row)

    return campaigns


def _adsets_resource():
    @dlt.resource(
        name="meta_api_adsets",
        write_disposition="replace",
    )
    def adsets():
        client = MetaClient()
        for row in client.adsets(fields=_ADSET_FIELDS):
            yield _row_adset(row)

    return adsets


def backfill_ad_daily(months: int = 12, pause_seconds: float = 8.0) -> list[dict]:
    """Checkpointed historical backfill of bronze.meta_api_ad_daily.

    Runs ONE dlt pipeline.run() PER 15-day CHUNK (oldest chunk first) so each
    chunk commits independently. This matters because a single pipeline.run()
    spanning many chunks only loads at the very end of extraction — if any
    chunk raises partway through, the whole run aborts and NOTHING commits,
    even chunks that were already fetched successfully. Confirmed live: two
    single-run 12-month attempts each lost 22/25 already-fetched chunks to a
    late transient Meta error (a 403 app-throttle, then a 400 "temporarily
    unavailable"). Per-chunk commits avoid that.

    Each chunk gets up to 3 attempts with backoff 30s / 2m / 5m on failure. A
    chunk that still fails after 3 attempts is RECORDED as failed and
    SKIPPED — the loop continues to the next (older-history) chunk rather
    than aborting the whole backfill for one bad window.

    Idempotent re-runs: the resource merges on (date, ad_id), so re-running
    this function — or re-running just the failed chunks individually via
    `_ad_daily_resource(since, until)` — is always safe; it will not
    duplicate rows already landed.

    Args:
        months: how many months of trailing history to backfill.
        pause_seconds: pause between chunks (polite pacing, on top of the
            client's own retry/backoff on individual requests).

    Returns:
        One {"since", "until", "status", "error"} dict per chunk, in the
        order processed, for reporting.
    """
    end = date.today()
    since = (end - timedelta(days=months * 30)).isoformat()
    until = end.isoformat()

    chunks = list(_chunk_dates(since, until, chunk_days=15))
    backoffs = [30, 120, 300]
    outcomes: list[dict] = []

    print(f"Backfilling meta_api_ad_daily: {since} -> {until} ({len(chunks)} chunks, oldest first)")

    for i, (chunk_since, chunk_until) in enumerate(chunks):
        ok = False
        last_err: str | None = None
        for attempt in range(3):
            try:
                pipeline = dlt.pipeline(
                    pipeline_name="meta_api",
                    destination=dlt.destinations.bigquery(location="europe-west2"),
                    dataset_name="bronze",
                )
                pipeline.run([_ad_daily_resource(chunk_since, chunk_until)()])
                ok = True
                break
            except Exception as e:  # noqa: BLE001 - chunk-level catch-all by design, see docstring
                last_err = str(e)
                if attempt < 2:
                    print(
                        f"    attempt {attempt + 1}/3 failed for {chunk_since}->{chunk_until}, "
                        f"backing off {backoffs[attempt]}s: {last_err[:200]}"
                    )
                    time.sleep(backoffs[attempt])

        status = "ok" if ok else "failed"
        print(f"  [{i + 1}/{len(chunks)}] {chunk_since} -> {chunk_until}: {status}")
        outcomes.append(
            {
                "since": chunk_since,
                "until": chunk_until,
                "status": status,
                "error": None if ok else last_err,
            }
        )
        if i < len(chunks) - 1:
            time.sleep(pause_seconds)

    n_ok = sum(1 for o in outcomes if o["status"] == "ok")
    n_failed = len(outcomes) - n_ok
    print(f"Backfill done: {n_ok}/{len(outcomes)} chunks landed, {n_failed} failed.")
    if n_failed:
        print("Failed chunks (re-run individually later — merge on (date, ad_id) is idempotent):")
        for o in outcomes:
            if o["status"] == "failed":
                print(f"  {o['since']} -> {o['until']}: {o['error'][:200]}")

    return outcomes


def run_pipeline(
    lookback_days: int | None = 7,
    start_date: str | None = None,
    ad_daily_lookback_days: int = 3,
) -> None:
    """Pull Meta campaign- and ad-level daily insights, plus ad creatives, into bronze.

    - Daily run: lookback_days=7 for campaign/geo (catches 28-day attribution
      updates well enough with each subsequent run extending the rolling
      window). ad_daily uses its own shorter ad_daily_lookback_days=3 window
      for Meta's restatements, unless a backfill start_date is given, in
      which case ad_daily shares the same start_date as everything else.
    - Backfill / all-time: pass start_date='2020-01-01'.
    - Ad creatives, campaigns and adsets are always full-replaced (small
      dimension tables, all statuses — not just active).
    """
    end = date.today()
    if start_date:
        since = start_date
    elif lookback_days:
        since = (end - timedelta(days=lookback_days - 1)).isoformat()
    else:
        raise ValueError("Either lookback_days or start_date must be provided.")
    until = end.isoformat()

    if start_date:
        ad_since = start_date
    else:
        ad_since = (end - timedelta(days=ad_daily_lookback_days - 1)).isoformat()

    pipeline = dlt.pipeline(
        pipeline_name="meta_api",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )
    load_info = pipeline.run(
        [
            _campaign_daily_resource(since, until)(),
            _geographic_daily_resource(since, until)(),
            _ad_daily_resource(ad_since, until)(),
            _ad_creatives_resource()(),
            _campaigns_resource()(),
            _adsets_resource()(),
        ]
    )
    print(load_info)
