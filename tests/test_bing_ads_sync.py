"""Unit tests for the pure XML/row-shaping helpers in scripts/bing_ads_sync.py.

Pure transform tests only — no network calls, no `bq` subprocess calls, no
live Bing Ads credentials required. The module reads BING_ADS_*/MS_TENANT_ID
from the environment at import time (for its module-level constants), so
this file sets harmless dummy values before importing it, via importlib so
we don't depend on `scripts` being an importable package.

Fixtures are hand-built XML fragments shaped like real Bing Ads v13 SOAP
responses (field names/nesting confirmed live 1 Sep 2026) but contain no
real customer data — only fake campaign/ad-group/keyword names and ids.
"""

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def bing_module(tmp_path_factory):
    """Import scripts/bing_ads_sync.py with dummy env vars, once per module."""
    import os

    env_backup = {
        k: os.environ.get(k)
        for k in [
            "MS_TENANT_ID",
            "BING_ADS_CLIENT_ID",
            "BING_ADS_DEVELOPER_TOKEN",
            "BING_ADS_ACCOUNT_ID",
            "BING_ADS_REFRESH_TOKEN",
        ]
    }
    os.environ.setdefault("MS_TENANT_ID", "test-tenant")
    os.environ.setdefault("BING_ADS_CLIENT_ID", "test-client-id")
    os.environ.setdefault("BING_ADS_DEVELOPER_TOKEN", "test-dev-token")
    os.environ.setdefault("BING_ADS_ACCOUNT_ID", "999999999")
    os.environ.setdefault("BING_ADS_REFRESH_TOKEN", "test-refresh-token")
    # Point at a scratch .env-shaped file so refresh_access_token's rewrite
    # logic (if exercised) never touches the real repo .env.
    fake_env = tmp_path_factory.mktemp("env") / ".env"
    fake_env.write_text("BING_ADS_REFRESH_TOKEN=test-refresh-token\n", encoding="utf-8")
    os.environ["BING_ENV_PATH"] = str(fake_env)

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "bing_ads_sync.py"
    spec = importlib.util.spec_from_file_location("bing_ads_sync", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bing_ads_sync"] = module
    spec.loader.exec_module(module)

    yield module

    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --------------------------------------------------------------------------
# _xml_to_py / row_from_element
# --------------------------------------------------------------------------


def test_xml_to_py_nil_returns_none(bing_module):
    el = ET.fromstring(
        '<Foo xmlns:i="http://www.w3.org/2001/XMLSchema-instance" i:nil="true"/>'
    )
    assert bing_module._xml_to_py(el) is None


def test_xml_to_py_leaf_returns_text(bing_module):
    el = ET.fromstring("<Foo>bar</Foo>")
    assert bing_module._xml_to_py(el) == "bar"


def test_xml_to_py_array_of_same_tag(bing_module):
    el = ET.fromstring(
        '<Languages xmlns:a="ns"><a:string>English</a:string><a:string>French</a:string></Languages>'
    )
    assert bing_module._xml_to_py(el) == ["English", "French"]


def test_xml_to_py_object_of_mixed_tags(bing_module):
    el = ET.fromstring("<Foo><A>1</A><B>2</B></Foo>")
    assert bing_module._xml_to_py(el) == {"A": "1", "B": "2"}


def test_xml_to_py_single_child_is_ambiguous_with_array(bing_module):
    """Known limitation: a complex element with exactly one child (e.g. the
    real <BiddingScheme><Type>EnhancedCpc</Type></BiddingScheme>) can't be
    told apart from a one-item array without a schema, so it serializes as
    a single-item list, not an object. Harmless for bronze (still JSON, still
    exactly what arrived) — documented here so it isn't "fixed" by accident."""
    el = ET.fromstring("<BiddingScheme><Type>EnhancedCpc</Type></BiddingScheme>")
    assert bing_module._xml_to_py(el) == ["EnhancedCpc"]


CAMPAIGN_XML = """<Campaign xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Id>485530451</Id>
  <Name>Search - branded (exact match)</Name>
  <Status>Active</Status>
  <SubType i:nil="true"/>
  <DailyBudget>30</DailyBudget>
  <CampaignType>Search</CampaignType>
  <Languages xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
    <a:string>English</a:string>
  </Languages>
</Campaign>"""


def test_row_from_element_mirrors_named_columns(bing_module):
    el = ET.fromstring(CAMPAIGN_XML)
    columns = ["Id", "Name", "Status", "SubType", "DailyBudget", "CampaignType", "Languages", "BudgetId"]
    row = bing_module.row_from_element(el, columns)
    assert row["Id"] == "485530451"
    assert row["Name"] == "Search - branded (exact match)"
    assert row["Status"] == "Active"
    assert row["SubType"] is None  # xsi:nil
    assert row["DailyBudget"] == "30"
    assert row["CampaignType"] == "Search"
    assert row["BudgetId"] is None  # not present at all in the element
    # Complex (multi-child) field is JSON-serialized whole, not unnested.
    assert row["Languages"] == '["English"]'


def test_row_from_element_missing_column_is_none(bing_module):
    el = ET.fromstring("<Ad><Id>1</Id></Ad>")
    row = bing_module.row_from_element(el, ["Id", "Headline"])
    assert row == {"Id": "1", "Headline": None}


# --------------------------------------------------------------------------
# KEYWORD_FIELD_MAP — the brief's prescribed GetKeywordsByAdGroupId shape
# mapped onto Airbyte's bulk-style column names (best-effort; many target
# columns have no live equivalent and must land NULL, not fabricated).
# --------------------------------------------------------------------------

KEYWORD_XML = """<Keyword xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Id>111</Id>
  <Bid><Amount>0.45</Amount></Bid>
  <Status>Active</Status>
  <Text>electric heating installer</Text>
  <MatchType>Exact</MatchType>
  <DestinationUrl i:nil="true"/>
  <EditorialStatus>Active</EditorialStatus>
</Keyword>"""


def test_keyword_field_map_semantic_translation(bing_module):
    el = ET.fromstring(KEYWORD_XML)
    ctx = {
        "ad_group_name": "Branded Exact",
        "campaign_name": "Search - branded (exact match)",
        "campaign_id": "485530451",
        "campaign_type": "Search",
        "account_id": "999999999",
    }
    columns = list(bing_module.KEYWORD_FIELD_MAP)
    row = {c: bing_module.KEYWORD_FIELD_MAP[c](el, ctx) for c in columns}
    assert row["Id"] == "111"
    assert row["Bid"] == "0.45"
    assert row["Keyword"] == "electric heating installer"
    assert row["Match_Type"] == "Exact"
    assert row["Ad_Group"] == "Branded Exact"
    assert row["Campaign"] == "Search - branded (exact match)"
    assert row["Account_Id"] == "999999999"
    assert row["Editorial_Status"] == "Active"
    # No live equivalent for these Bulk-download-only fields — must be NULL,
    # never fabricated (bronze rule).
    assert row["Client_Id"] is None
    assert row["Quality_Score"] is None
    assert row["Modified_Time"] is None


# --------------------------------------------------------------------------
# CAMPAIGN_LABEL_FIELD_MAP
# --------------------------------------------------------------------------


def test_campaign_label_field_map(bing_module):
    ctx = {
        "labels": {"777": {"Name": "High priority", "Status": "Active"}},
        "campaign_name": "Search - branded (exact match)",
        "campaign_id": "485530451",
        "campaign_type": "Search",
    }
    columns = list(bing_module.CAMPAIGN_LABEL_FIELD_MAP)
    row = {c: bing_module.CAMPAIGN_LABEL_FIELD_MAP[c]("777", ctx) for c in columns}
    assert row["Id"] == "777"
    assert row["Status"] == "Active"
    assert row["Campaign"] == "Search - branded (exact match)"
    assert row["Campaign_Id"] == "485530451"
    assert row["Campaign_Type"] == "Search"


# --------------------------------------------------------------------------
# Report column selection — request only columns valid for that report type
# --------------------------------------------------------------------------


def test_report_column_enums_intersect_correctly(bing_module):
    mirrored = ["AccountId", "AccountName", "Spend", "NotARealBingColumn", "_synced_at"]
    valid = [c for c in mirrored if c in bing_module.REPORT_COLUMN_ENUMS["AccountPerformanceReport"]]
    assert valid == ["AccountId", "AccountName", "Spend"]
