"""Unit tests for the Meta ad-level bronze row transforms.

Pure transform tests — no network calls, no dlt pipeline execution. Fixtures
mirror the real API response shapes documented in
business_plan/analysis_output/data/meta_ad_level_probe.md but contain no
real customer PII (only ad copy/creative metadata, which is not PII).
"""

import json

import pytest

from ingestion.meta.pipeline import _row_ad_creative, _row_ad_daily


@pytest.fixture
def ad_insight_row() -> dict:
    """One row as returned by /act_X/insights?level=ad&time_increment=1."""
    return {
        "campaign_id": "120245307286080588",
        "campaign_name": "[TOF]-[ON]-[REGION]-Scotland-QUOTE [2026]",
        "adset_id": "120246147844920588",
        "adset_name": "A50+-broad-scotland-quote",
        "ad_id": "120246147844910588",
        "ad_name": "[21.05.2026]- REAL - Video - Radiator install Olivia",
        "impressions": "144",
        "spend": "5.31",
        "reach": "136",
        "frequency": "1.058824",
        "cpm": "36.875",
        "cpc": "0.66375",
        "inline_link_clicks": "3",
        "cost_per_inline_link_click": "1.77",
        "actions": [
            {"action_type": "link_click", "value": "3"},
            {"action_type": "landing_page_view", "value": "1"},
        ],
        "cost_per_action_type": [
            {"action_type": "link_click", "value": "1.77"},
        ],
        "date_start": "2026-07-28",
        "date_stop": "2026-07-28",
    }


@pytest.fixture
def ad_creative_row() -> dict:
    """One row as returned by /act_X/ads?fields=id,name,...,creative{...}."""
    return {
        "id": "120250542357760588",
        "name": "[09.08.2026]-Why get a free quote",
        "status": "ACTIVE",
        "effective_status": "ACTIVE",
        "updated_time": "2026-08-09T10:43:25+0100",
        "creative": {
            "id": "1402821918473010",
            "name": "Better Control, Better Comfort 2026-06-24-fakehash",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "object_story_spec": {"link_data": {"link": "https://lp.example.co.uk/free-quote/"}},
            "asset_feed_spec": {
                "bodies": [{"text": "Fake body copy"}],
                "titles": [{"text": "Fake title"}],
                "optimization_type": "DEGREES_OF_FREEDOM",
            },
        },
    }


def test_row_ad_daily_casts_numerics(ad_insight_row):
    row = _row_ad_daily(ad_insight_row)
    assert row["date"] == "2026-07-28"
    assert row["campaign_id"] == "120245307286080588"
    assert row["adset_id"] == "120246147844920588"
    assert row["ad_id"] == "120246147844910588"
    assert row["impressions"] == 144
    assert row["spend_gbp"] == pytest.approx(5.31)
    assert row["reach"] == 136
    assert row["inline_link_clicks"] == 3
    assert row["cost_per_inline_link_click"] == pytest.approx(1.77)


def test_row_ad_daily_lands_actions_as_raw_json_string(ad_insight_row):
    """Bronze rule: actions/cost_per_action_type land RAW, no unnesting."""
    row = _row_ad_daily(ad_insight_row)
    assert isinstance(row["actions"], str)
    assert isinstance(row["cost_per_action_type"], str)
    parsed_actions = json.loads(row["actions"])
    assert parsed_actions == ad_insight_row["actions"]
    parsed_costs = json.loads(row["cost_per_action_type"])
    assert parsed_costs == ad_insight_row["cost_per_action_type"]


def test_row_ad_daily_handles_missing_actions():
    row = _row_ad_daily({"ad_id": "1", "date_start": "2026-01-01"})
    assert row["actions"] is None
    assert row["cost_per_action_type"] is None
    assert row["impressions"] is None
    assert row["spend_gbp"] is None


def test_row_ad_creative_flattens_nested_creative(ad_creative_row):
    row = _row_ad_creative(ad_creative_row)
    assert row["ad_id"] == "120250542357760588"
    assert row["ad_name"] == "[09.08.2026]-Why get a free quote"
    assert row["status"] == "ACTIVE"
    assert row["effective_status"] == "ACTIVE"
    assert row["updated_time"] == "2026-08-09T10:43:25+0100"
    assert row["creative_id"] == "1402821918473010"
    assert row["creative_name"] == "Better Control, Better Comfort 2026-06-24-fakehash"
    assert row["thumbnail_url"] == "https://example.com/thumb.jpg"


def test_row_ad_creative_lands_specs_as_raw_json_with_landing_page(ad_creative_row):
    row = _row_ad_creative(ad_creative_row)
    assert isinstance(row["object_story_spec"], str)
    assert isinstance(row["asset_feed_spec"], str)
    oss = json.loads(row["object_story_spec"])
    assert oss["link_data"]["link"] == "https://lp.example.co.uk/free-quote/"
    afs = json.loads(row["asset_feed_spec"])
    assert afs["optimization_type"] == "DEGREES_OF_FREEDOM"


def test_row_ad_creative_handles_missing_creative():
    row = _row_ad_creative({"id": "1", "name": "no creative attached"})
    assert row["creative_id"] is None
    assert row["object_story_spec"] is None
    assert row["asset_feed_spec"] is None
