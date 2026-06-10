"""dlt pipeline — Google Ads API → BigQuery bronze (campaign-level daily).

Phase 1 minimum viable replacement for Airbyte's `google_adscampaign` table.
Produces `bronze.google_ads_api_campaign_daily` at campaign × date × ad-network
granularity — same fields silver_google_ads_spend needs, so we can swap
silver's source over with a small change.

Write disposition is `replace` — we re-pull the rolling lookback window in
full each run, so duplicate handling lives in the API call, not in silver.
"""

import os
from datetime import date, timedelta
from typing import Iterator

import dlt
from dotenv import load_dotenv

from ingestion.google_ads.client import operating_customer_id, search_stream

load_dotenv()


CAMPAIGN_DAILY_GAQL = """
    SELECT
      campaign.id,
      campaign.name,
      campaign.status,
      campaign.advertising_channel_type,
      campaign_budget.amount_micros,
      segments.date,
      segments.ad_network_type,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM campaign
    WHERE {date_filter}
"""

GEO_DAILY_GAQL = """
    SELECT
      campaign.id,
      campaign.name,
      geographic_view.country_criterion_id,
      geographic_view.location_type,
      segments.date,
      segments.geo_target_city,
      segments.geo_target_metro,
      segments.geo_target_most_specific_location,
      segments.geo_target_region,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.conversions_value
    FROM geographic_view
    WHERE {date_filter}
      AND geographic_view.country_criterion_id = 2826
"""

GEO_TARGET_GAQL = """
    SELECT
      geo_target_constant.id,
      geo_target_constant.name,
      geo_target_constant.country_code,
      geo_target_constant.target_type,
      geo_target_constant.canonical_name
    FROM geo_target_constant
    WHERE geo_target_constant.country_code = 'GB'
      AND geo_target_constant.status = 'ENABLED'
"""


def _criterion_id(resource_name: str | None) -> str | None:
    if not resource_name:
        return None
    s = str(resource_name).strip()
    if not s:
        return None
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    return s if s.isdigit() else None


def _date_filter(lookback_days: int | None = None, start_date: str | None = None) -> str:
    end = date.today()
    if start_date:
        start = date.fromisoformat(start_date)
    elif lookback_days:
        start = end - timedelta(days=lookback_days - 1)
    else:
        raise ValueError("Either lookback_days or start_date must be provided.")
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


def _row_campaign(row) -> dict:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "campaign_status": row.campaign.status.name,
        "channel_type": row.campaign.advertising_channel_type.name,
        "budget_micros": row.campaign_budget.amount_micros,
        "date": str(row.segments.date),
        "ad_network_type": row.segments.ad_network_type.name,
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "cost_micros": row.metrics.cost_micros,
        "spend_gbp": (row.metrics.cost_micros or 0) / 1_000_000.0,
        "conversions": row.metrics.conversions,
        "conversions_value": row.metrics.conversions_value,
    }


def _row_geo(row) -> dict:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "country_criterion_id": str(row.geographic_view.country_criterion_id),
        "location_type": row.geographic_view.location_type.name,
        "date": str(row.segments.date),
        "city_criterion_id": _criterion_id(str(row.segments.geo_target_city)),
        "metro_criterion_id": _criterion_id(str(row.segments.geo_target_metro)),
        "most_specific_criterion_id": _criterion_id(
            str(row.segments.geo_target_most_specific_location)
        ),
        "region_criterion_id": _criterion_id(str(row.segments.geo_target_region)),
        "impressions": row.metrics.impressions,
        "clicks": row.metrics.clicks,
        "cost_micros": row.metrics.cost_micros,
        "spend_gbp": (row.metrics.cost_micros or 0) / 1_000_000.0,
        "conversions": row.metrics.conversions,
        "conversions_value": row.metrics.conversions_value,
    }


def _row_geo_target(row) -> dict:
    target_type = row.geo_target_constant.target_type
    return {
        "criterion_id": str(row.geo_target_constant.id),
        "name": row.geo_target_constant.name,
        "country_code": row.geo_target_constant.country_code,
        "target_type": target_type.name if hasattr(target_type, "name") else str(target_type),
        "canonical_name": row.geo_target_constant.canonical_name,
    }


def _geo_daily_resource(lookback_days: int | None = None, start_date: str | None = None):
    @dlt.resource(
        name="google_ads_api_geographic_daily",
        write_disposition="merge",
        primary_key=["date", "campaign_id", "location_type", "most_specific_criterion_id"],
    )
    def geo_daily():
        query = GEO_DAILY_GAQL.format(
            date_filter=_date_filter(lookback_days=lookback_days, start_date=start_date)
        )
        for row in search_stream(query):
            # location_type enum can't be filtered in GAQL — filter in Python instead
            if row.geographic_view.location_type.name == "USER_LOCATION":
                yield _row_geo(row)
    return geo_daily


def _geo_target_resource():
    @dlt.resource(
        name="google_ads_api_geo_target_constants",
        write_disposition="replace",
    )
    def geo_targets():
        for row in search_stream(GEO_TARGET_GAQL):
            yield _row_geo_target(row)
    return geo_targets


def _campaign_daily_resource(lookback_days: int | None = None, start_date: str | None = None):
    @dlt.resource(
        name="google_ads_api_campaign_daily",
        write_disposition="merge",
        primary_key=["date", "campaign_id", "ad_network_type"],
    )
    def campaign_daily():
        query = CAMPAIGN_DAILY_GAQL.format(
            date_filter=_date_filter(lookback_days=lookback_days, start_date=start_date)
        )
        for row in search_stream(query):
            yield _row_campaign(row)
    return campaign_daily


def run_pipeline(lookback_days: int | None = 30, start_date: str | None = None) -> None:
    """Pull campaign-level daily data into bronze.

    Modes:
      - Daily run: lookback_days=7 (rolling window, catches late attribution).
      - Backfill: start_date='2020-01-01' (or any cutoff) for a wider pull.
      - All-time: pass start_date='2020-01-01' — Google retains ~63 months of
        detail (anything older returns nothing, which is fine).
    """
    if not operating_customer_id():
        raise RuntimeError(
            "GOOGLE_ADS_CUSTOMER_ID or GOOGLE_ADS_LOGIN_CUSTOMER_ID must be set in .env."
        )

    pipeline = dlt.pipeline(
        pipeline_name="google_ads_api",
        destination=dlt.destinations.bigquery(location="europe-west2"),
        dataset_name="bronze",
    )
    load_info = pipeline.run([
        _campaign_daily_resource(lookback_days=lookback_days, start_date=start_date)(),
        _geo_daily_resource(lookback_days=lookback_days, start_date=start_date)(),
        _geo_target_resource()(),
    ])
    print(load_info)
