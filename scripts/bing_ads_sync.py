"""Direct Bing Ads (Microsoft Advertising) ingestion -> BigQuery bronze.

Replaces/mirrors the 13 Airbyte `bing_ads*` bronze tables with a raw
requests + SOAP-XML client (no bingads SDK, no dlt, no google-cloud-bigquery
python client — writes go through the `bq` CLI). Bronze rule: every landed
column is STRING (plus a `_synced_at` TIMESTAMP), values are exactly what the
API returned, no casting, no opinions.

Auth: OAuth2 refresh-token flow against Azure AD (public client, no
client_secret), scope "https://ads.microsoft.com/msads.manage offline_access".
CustomerManagement resolves the CustomerId that owns BING_ADS_ACCOUNT_ID
(GetAccount.ParentCustomerId) — required as a SOAP header for
CampaignManagement/Reporting calls alongside CustomerAccountId.

Usage:
    python scripts/bing_ads_sync.py --streams all --days 30
    python scripts/bing_ads_sync.py --streams campaigns,ad_groups
    python scripts/bing_ads_sync.py --streams account_performance_report_daily --days 14
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_PATH = Path(os.environ.get("BING_ENV_PATH", REPO_ROOT / ".env"))
load_dotenv(ENV_PATH)

BQ_PROJECT = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
BQ_DATASET = "bronze"
BQ_LOCATION = "europe-west2"

TENANT = os.environ["MS_TENANT_ID"]
CLIENT_ID = os.environ["BING_ADS_CLIENT_ID"]
DEV_TOKEN = os.environ["BING_ADS_DEVELOPER_TOKEN"]
ACCOUNT_ID = os.environ["BING_ADS_ACCOUNT_ID"]

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
SCOPE = "https://ads.microsoft.com/msads.manage offline_access"

CUSTOMER_MGMT_URL = (
    "https://clientcenter.api.bingads.microsoft.com/Api/CustomerManagement/v13/"
    "CustomerManagementService.svc"
)
CAMPAIGN_MGMT_URL = (
    "https://campaign.api.bingads.microsoft.com/Api/Advertiser/CampaignManagement/v13/"
    "CampaignManagementService.svc"
)
REPORTING_URL = (
    "https://reporting.api.bingads.microsoft.com/Api/Advertiser/Reporting/v13/"
    "ReportingService.svc"
)

NS_CUSTOMER = "https://bingads.microsoft.com/Customer/v13"
NS_CAMPAIGN = "https://bingads.microsoft.com/CampaignManagement/v13"
NS_REPORTING = "https://bingads.microsoft.com/Reporting/v13"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

CAMPAIGN_TYPES = "Search Shopping DynamicSearchAds Audience Hotel PerformanceMax App ObjectiveBased"
AD_TYPES = "Text Image Product AppInstall ExpandedText DynamicSearch ResponsiveAd ResponsiveSearch Hotel"


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def refresh_access_token() -> str:
    """Exchange the stored refresh token for an access token.

    Public client — no client_secret (sending one fails AADSTS700025). If
    Azure AD rotates the refresh token in the response, rewrite the
    BING_ADS_REFRESH_TOKEN line in .env (regex on that line only).
    """
    refresh_token = os.environ["BING_ADS_REFRESH_TOKEN"]
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": SCOPE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        env_text = ENV_PATH.read_text(encoding="utf-8")
        env_text = re.sub(
            r"^BING_ADS_REFRESH_TOKEN=.*$",
            "BING_ADS_REFRESH_TOKEN=" + new_refresh,
            env_text,
            flags=re.M,
        )
        ENV_PATH.write_text(env_text, encoding="utf-8")
        os.environ["BING_ADS_REFRESH_TOKEN"] = new_refresh
    return tok["access_token"]


# --------------------------------------------------------------------------
# SOAP plumbing
# --------------------------------------------------------------------------


class SoapFault(Exception):
    pass


def _soap_envelope(header_ns: str, header_fields: dict, body_xml: str) -> str:
    headers = "\n".join(
        f'    <h:{name} xmlns:h="{header_ns}">{value}</h:{name}>'
        for name, value in header_fields.items()
        if value is not None
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
{headers}
  </s:Header>
  <s:Body>
{body_xml}
  </s:Body>
</s:Envelope>"""


def soap_call(
    url: str, header_ns: str, header_fields: dict, action: str, body_xml: str, timeout: int = 60
) -> ET.Element:
    """POST a SOAP request, return the <Body>'s single child element.

    Raises SoapFault with the API's error message on an s:Fault response.
    """
    envelope = _soap_envelope(header_ns, header_fields, body_xml)
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": action}
    resp = requests.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout)
    root = ET.fromstring(resp.text)
    body = root.find("{*}Body")
    fault = body.find("{*}Fault")
    if fault is not None:
        raise SoapFault(f"{action}: {ET.tostring(fault, encoding='unicode')[:800]}")
    return list(body)[0]


def _xml_to_py(el: ET.Element):
    """Generic XML element -> python primitive/dict/list, for JSON-serializing
    nested (complex) fields. Bronze rule: no unnesting, just capture what's there."""
    if el.attrib.get(XSI_NIL) == "true":
        return None
    children = list(el)
    if not children:
        return el.text
    tags = {c.tag.split("}")[-1] for c in children}
    if len(tags) == 1:
        return [_xml_to_py(c) for c in children]
    return {c.tag.split("}")[-1]: _xml_to_py(c) for c in children}


def row_from_element(el: ET.Element, columns: list[str]) -> dict:
    """Mirror `columns` (Airbyte's bronze column names) off direct children of
    `el` by exact tag name (namespace-wildcarded). Complex children are
    JSON-serialized whole, not unnested — bronze rule."""
    row: dict = {}
    for col in columns:
        child = el.find(f"{{*}}{col}")
        if child is None or child.attrib.get(XSI_NIL) == "true":
            row[col] = None
            continue
        if len(list(child)) > 0:
            row[col] = json.dumps(_xml_to_py(child))
        else:
            row[col] = child.text
    return row


# --------------------------------------------------------------------------
# CustomerManagement
# --------------------------------------------------------------------------


class BingClient:
    def __init__(self):
        self.access_token = refresh_access_token()
        self.customer_id: str | None = None

    def cm_call(self, action: str, body_xml: str) -> ET.Element:
        headers = {
            "AuthenticationToken": self.access_token,
            "DeveloperToken": DEV_TOKEN,
        }
        return soap_call(CUSTOMER_MGMT_URL, NS_CUSTOMER, headers, action, body_xml)

    def resolve_customer_id(self) -> str:
        """GetAccount(ACCOUNT_ID).ParentCustomerId — the CustomerId required as
        a header for CampaignManagement/Reporting calls against this account."""
        body = f"""<GetAccountRequest xmlns="{NS_CUSTOMER}">
      <AccountId>{ACCOUNT_ID}</AccountId>
    </GetAccountRequest>"""
        el = self.cm_call("GetAccount", body)
        account_el = el.find("{*}Account")
        cid = account_el.find("{*}ParentCustomerId").text
        self.customer_id = cid
        return cid

    def get_account_row(self, columns: list[str]) -> dict:
        body = f"""<GetAccountRequest xmlns="{NS_CUSTOMER}">
      <AccountId>{ACCOUNT_ID}</AccountId>
    </GetAccountRequest>"""
        el = self.cm_call("GetAccount", body)
        account_el = el.find("{*}Account")
        return row_from_element(account_el, columns)

    # ---- CampaignManagement ----

    def cms_call(self, action: str, body_xml: str) -> ET.Element:
        headers = {
            "AuthenticationToken": self.access_token,
            "DeveloperToken": DEV_TOKEN,
            "CustomerAccountId": ACCOUNT_ID,
            "CustomerId": self.customer_id,
        }
        return soap_call(CAMPAIGN_MGMT_URL, NS_CAMPAIGN, headers, action, body_xml, timeout=120)

    def get_campaigns(self) -> list[ET.Element]:
        body = f"""<GetCampaignsByAccountIdRequest xmlns="{NS_CAMPAIGN}">
      <AccountId>{ACCOUNT_ID}</AccountId>
      <CampaignType>{CAMPAIGN_TYPES}</CampaignType>
    </GetCampaignsByAccountIdRequest>"""
        el = self.cms_call("GetCampaignsByAccountId", body)
        container = el.find("{*}Campaigns")
        return list(container) if container is not None else []

    def get_ad_groups(self, campaign_id: str) -> list[ET.Element]:
        body = f"""<GetAdGroupsByCampaignIdRequest xmlns="{NS_CAMPAIGN}">
      <CampaignId>{campaign_id}</CampaignId>
    </GetAdGroupsByCampaignIdRequest>"""
        el = self.cms_call("GetAdGroupsByCampaignId", body)
        container = el.find("{*}AdGroups")
        return list(container) if container is not None else []

    def get_ads(self, ad_group_id: str) -> list[ET.Element]:
        # ArrayOfAdType items are named <AdType> in the CampaignManagement
        # namespace itself (tns), NOT the generic Arrays serialization
        # namespace — confirmed live: prefixing with the Arrays ns silently
        # empties the array server-side ("AdTypes are required").
        body = f"""<GetAdsByAdGroupIdRequest xmlns="{NS_CAMPAIGN}">
      <AdGroupId>{ad_group_id}</AdGroupId>
      <AdTypes>
        {''.join(f'<AdType>{t}</AdType>' for t in AD_TYPES.split())}
      </AdTypes>
    </GetAdsByAdGroupIdRequest>"""
        el = self.cms_call("GetAdsByAdGroupId", body)
        container = el.find("{*}Ads")
        return list(container) if container is not None else []

    def get_keywords(self, ad_group_id: str) -> list[ET.Element]:
        body = f"""<GetKeywordsByAdGroupIdRequest xmlns="{NS_CAMPAIGN}">
      <AdGroupId>{ad_group_id}</AdGroupId>
    </GetKeywordsByAdGroupIdRequest>"""
        el = self.cms_call("GetKeywordsByAdGroupId", body)
        container = el.find("{*}Keywords")
        return list(container) if container is not None else []

    def get_label_associations(self, campaign_ids: list[str]) -> list[tuple[str, str]]:
        """(LabelId, EntityId) pairs for Campaign-scoped labels.

        NOTE: the brief named `GetLabelAssociationsByEntityType`, which does
        not exist in the v13 WSDL. The real operation for this shape is
        `GetLabelAssociationsByEntityIds` (confirmed live against the WSDL) —
        using it under the brief's own "or GetLabelsByIds" fallback.
        """
        ids_xml = "".join(
            f'<a:long>{cid}</a:long>' for cid in campaign_ids
        )
        body = f"""<GetLabelAssociationsByEntityIdsRequest xmlns="{NS_CAMPAIGN}">
      <EntityIds xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
        {ids_xml}
      </EntityIds>
      <EntityType>Campaign</EntityType>
    </GetLabelAssociationsByEntityIdsRequest>"""
        el = self.cms_call("GetLabelAssociationsByEntityIds", body)
        container = el.find("{*}LabelAssociations")
        pairs = []
        if container is not None:
            for assoc in container:
                label_id = assoc.find("{*}LabelId").text
                entity_id = assoc.find("{*}EntityId").text
                pairs.append((label_id, entity_id))
        return pairs

    def get_labels_by_ids(self, label_ids: list[str]) -> dict[str, dict]:
        if not label_ids:
            return {}
        ids_xml = "".join(f"<a:long>{lid}</a:long>" for lid in label_ids)
        body = f"""<GetLabelsByIdsRequest xmlns="{NS_CAMPAIGN}">
      <LabelIds xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
        {ids_xml}
      </LabelIds>
    </GetLabelsByIdsRequest>"""
        el = self.cms_call("GetLabelsByIds", body)
        container = el.find("{*}Labels")
        out = {}
        if container is not None:
            for label_el in container:
                lid = label_el.find("{*}Id").text
                out[lid] = {
                    "Name": _text(label_el, "Name"),
                    "Status": _text(label_el, "Status"),
                }
        return out

    # ---- Reporting ----

    def rep_call(self, action: str, body_xml: str) -> ET.Element:
        headers = {
            "AuthenticationToken": self.access_token,
            "DeveloperToken": DEV_TOKEN,
            "CustomerAccountId": ACCOUNT_ID,
            "CustomerId": self.customer_id,
        }
        return soap_call(REPORTING_URL, NS_REPORTING, headers, action, body_xml, timeout=60)

    def submit_report(self, report_type: str, aggregation: str, columns: list[str], since: str, until: str) -> str:
        s_y, s_m, s_d = since.split("-")
        u_y, u_m, u_d = until.split("-")
        cols_xml = "".join(f"<tns:{report_type}Column>{c}</tns:{report_type}Column>" for c in columns)
        body = f"""<SubmitGenerateReportRequest xmlns="{NS_REPORTING}">
      <ReportRequest i:type="{report_type}Request" xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns:tns="{NS_REPORTING}">
        <ExcludeColumnHeaders>true</ExcludeColumnHeaders>
        <ExcludeReportFooter>true</ExcludeReportFooter>
        <ExcludeReportHeader>true</ExcludeReportHeader>
        <Format>Csv</Format>
        <FormatVersion>2.0</FormatVersion>
        <ReportName>{report_type}_{since}_{until}</ReportName>
        <ReturnOnlyCompleteData>false</ReturnOnlyCompleteData>
        <Aggregation>{aggregation}</Aggregation>
        <Columns>{cols_xml}</Columns>
        <Scope>
          <AccountIds xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
            <a:long>{ACCOUNT_ID}</a:long>
          </AccountIds>
        </Scope>
        <Time>
          <CustomDateRangeEnd><Day>{int(u_d)}</Day><Month>{int(u_m)}</Month><Year>{u_y}</Year></CustomDateRangeEnd>
          <CustomDateRangeStart><Day>{int(s_d)}</Day><Month>{int(s_m)}</Month><Year>{s_y}</Year></CustomDateRangeStart>
          <ReportTimeZone>GreenwichMeanTimeDublinEdinburghLisbonLondon</ReportTimeZone>
        </Time>
      </ReportRequest>
    </SubmitGenerateReportRequest>"""
        el = self.rep_call("SubmitGenerateReport", body)
        return el.find("{*}ReportRequestId").text

    def poll_report(self, request_id: str, max_wait_s: int = 300) -> str | None:
        """Poll until Success/CompletedWithoutData, return download URL or None."""
        body = f"""<PollGenerateReportRequest xmlns="{NS_REPORTING}">
      <ReportRequestId>{request_id}</ReportRequestId>
    </PollGenerateReportRequest>"""
        waited = 0
        interval = 5
        while waited < max_wait_s:
            el = self.rep_call("PollGenerateReport", body)
            status_el = el.find("{*}ReportRequestStatus")
            status = status_el.find("{*}Status").text
            if status == "Success":
                url_el = status_el.find("{*}ReportDownloadUrl")
                return url_el.text if url_el is not None else None
            if status == "Error":
                raise RuntimeError(f"Report generation failed: {ET.tostring(el, encoding='unicode')[:500]}")
            time.sleep(interval)
            waited += interval
        raise TimeoutError(f"Report poll timed out after {max_wait_s}s")


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(f"{{*}}{tag}")
    if child is None or child.attrib.get(XSI_NIL) == "true":
        return None
    return child.text


def download_report_csv(url: str) -> list[list[str]]:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode("utf-8-sig")
    return list(csv.reader(io.StringIO(raw)))


# --------------------------------------------------------------------------
# BigQuery via `bq` CLI (no python client in this venv)
# --------------------------------------------------------------------------


def _run_bq(args: list[str], input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    # shell=False + a resolved executable path works on both platforms;
    # shutil.which finds bq.cmd on Windows and the plain binary on Linux.
    bq = shutil.which("bq") or "bq"
    return subprocess.run(
        [bq] + args, input=input_text, capture_output=True, text=True, timeout=timeout
    )


def mirror_columns(airbyte_table: str) -> list[str]:
    """Real column names (order preserved) from an Airbyte bronze table, minus
    Airbyte's _airbyte_* metadata columns. This is how every bing_direct_*
    table's shape is derived — never hand-typed."""
    r = _run_bq(["show", "--schema", "--format=json", f"{BQ_PROJECT}:{BQ_DATASET}.{airbyte_table}"])
    if r.returncode != 0:
        raise RuntimeError(f"bq show schema failed for {airbyte_table}: {r.stderr}")
    fields = json.loads(r.stdout)
    return [f["name"] for f in fields if not f["name"].startswith("_airbyte_")]


def ensure_table(table: str, columns: list[str]) -> None:
    full = f"{BQ_PROJECT}:{BQ_DATASET}.{table}"
    r = _run_bq(["show", full])
    if r.returncode == 0:
        return
    schema = ",".join(f"{c}:STRING" for c in columns) + ",_synced_at:TIMESTAMP"
    r = _run_bq(["mk", "--table", "--location", BQ_LOCATION, full, schema])
    if r.returncode != 0:
        # bq's "already exists" message lands on stdout, not stderr — benign
        # if another process (or a prior partial run) created it first.
        if "already exists" in r.stdout:
            return
        raise RuntimeError(f"bq mk table failed for {table}: stdout={r.stdout!r} stderr={r.stderr!r}")


def bq_load_ndjson(table: str, rows: list[dict], columns: list[str], replace: bool) -> int:
    """Load rows (each dict keyed by `columns` plus already-set _synced_at) into
    bronze.<table>. replace=True truncates first (entity full-replace)."""
    if not rows:
        if replace:
            # still truncate to an empty table on a zero-row snapshot
            _run_bq(
                [
                    "query",
                    "--use_legacy_sql=false",
                    "--location",
                    BQ_LOCATION,
                    f"TRUNCATE TABLE `{BQ_PROJECT}.{BQ_DATASET}.{table}`",
                ]
            )
        return 0
    schema = ",".join(f"{c}:STRING" for c in columns) + ",_synced_at:TIMESTAMP"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ndjson", delete=False, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
        path = f.name
    try:
        args = [
            "load",
            "--source_format=NEWLINE_DELIMITED_JSON",
            "--location",
            BQ_LOCATION,
            "--schema",
            schema,
        ]
        args.append("--replace" if replace else "--noreplace")
        args.append(f"{BQ_PROJECT}:{BQ_DATASET}.{table}")
        args.append(path)
        r = _run_bq(args, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"bq load failed for {table}: stdout={r.stdout!r} stderr={r.stderr!r}")
    finally:
        os.unlink(path)
    return len(rows)


def bq_delete_window(table: str, date_col: str, start_date: str, end_date_exclusive: str) -> None:
    """Delete rows with STRING date_col in [start_date, end_date_exclusive).

    date_col is a bronze STRING and may hold either a bare date ("2026-08-25")
    or a full timestamp ("2026-08-25T13:00:00") depending on the report's
    aggregation — an exclusive upper bound on the *next* day avoids lexical
    ambiguity between the two formats.
    """
    q = (
        f"DELETE FROM `{BQ_PROJECT}.{BQ_DATASET}.{table}` "
        f"WHERE {date_col} >= '{start_date}' AND {date_col} < '{end_date_exclusive}'"
    )
    r = _run_bq(["query", "--use_legacy_sql=false", "--location", BQ_LOCATION, "--nouse_cache", q])
    if r.returncode != 0:
        raise RuntimeError(f"bq delete window failed for {table}: {r.stderr}")


def bq_query_rows(query: str) -> list[dict]:
    r = _run_bq(["query", "--use_legacy_sql=false", "--location", BQ_LOCATION, "--format=json", "--nouse_cache", query])
    if r.returncode != 0:
        raise RuntimeError(f"bq query failed: {r.stderr}\nQUERY: {query}")
    return json.loads(r.stdout) if r.stdout.strip() else []


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --------------------------------------------------------------------------
# Report column enums (v13 WSDL, confirmed live) — the request Columns list
# per stream is whichever of these also appear in the mirrored Airbyte table.
# --------------------------------------------------------------------------

REPORT_COLUMN_ENUMS = {
    "AccountPerformanceReport": {
        "AccountName", "AccountNumber", "AccountId", "TimePeriod", "CurrencyCode", "AdDistribution",
        "Impressions", "Clicks", "Ctr", "AverageCpc", "Spend", "AveragePosition", "Conversions",
        "ConversionRate", "CostPerConversion", "LowQualityClicks", "LowQualityClicksPercent",
        "LowQualityImpressions", "LowQualityImpressionsPercent", "LowQualityConversions",
        "LowQualityConversionRate", "DeviceType", "DeviceOS", "PhoneImpressions", "PhoneCalls", "Ptr",
        "Network", "TopVsOther", "BidMatchType", "DeliveredMatchType", "Assists", "Revenue",
        "ReturnOnAdSpend", "CostPerAssist", "RevenuePerConversion", "RevenuePerAssist", "AccountStatus",
        "LowQualityGeneralClicks", "LowQualitySophisticatedClicks", "CustomerId", "CustomerName",
        "AllConversions", "AllRevenue", "AllConversionRate", "AllCostPerConversion", "AllReturnOnAdSpend",
        "AllRevenuePerConversion", "ViewThroughConversions", "Goal", "GoalType", "AverageCpm",
        "ConversionsQualified",
    },
    "CampaignPerformanceReport": {
        "AccountName", "AccountNumber", "AccountId", "TimePeriod", "CampaignStatus", "CampaignName",
        "CampaignId", "CurrencyCode", "AdDistribution", "Impressions", "Clicks", "Ctr", "AverageCpc",
        "Spend", "AveragePosition", "Conversions", "ConversionRate", "CostPerConversion",
        "LowQualityClicks", "LowQualityClicksPercent", "LowQualityImpressions",
        "LowQualityImpressionsPercent", "LowQualityConversions", "LowQualityConversionRate",
        "DeviceType", "DeviceOS", "QualityScore", "ExpectedCtr", "AdRelevance", "LandingPageExperience",
        "HistoricalQualityScore", "HistoricalExpectedCtr", "HistoricalAdRelevance",
        "HistoricalLandingPageExperience", "PhoneImpressions", "PhoneCalls", "Ptr", "Network",
        "TopVsOther", "BidMatchType", "DeliveredMatchType", "Assists", "Revenue", "ReturnOnAdSpend",
        "CostPerAssist", "RevenuePerConversion", "RevenuePerAssist", "TrackingTemplate",
        "CustomParameters", "AccountStatus", "BudgetName", "BudgetStatus", "BudgetAssociationStatus",
        "LowQualityGeneralClicks", "LowQualitySophisticatedClicks", "CampaignLabels", "CustomerId",
        "CustomerName", "FinalUrlSuffix", "CampaignType", "BaseCampaignId", "AllConversions",
        "AllRevenue", "AllConversionRate", "AllCostPerConversion", "AllReturnOnAdSpend",
        "AllRevenuePerConversion", "ViewThroughConversions", "Goal", "GoalType", "AverageCpm",
        "ConversionsQualified",
    },
    "AdGroupPerformanceReport": {
        "AccountName", "AccountNumber", "AccountId", "TimePeriod", "Status", "CampaignName",
        "CampaignId", "AdGroupName", "AdGroupId", "CurrencyCode", "AdDistribution", "Impressions",
        "Clicks", "Ctr", "AverageCpc", "Spend", "AveragePosition", "Conversions", "ConversionRate",
        "CostPerConversion", "DeviceType", "Language", "DeviceOS", "QualityScore", "ExpectedCtr",
        "AdRelevance", "LandingPageExperience", "HistoricalQualityScore", "HistoricalExpectedCtr",
        "HistoricalAdRelevance", "HistoricalLandingPageExperience", "PhoneImpressions", "PhoneCalls",
        "Ptr", "Network", "TopVsOther", "BidMatchType", "DeliveredMatchType", "Assists", "Revenue",
        "ReturnOnAdSpend", "CostPerAssist", "RevenuePerConversion", "RevenuePerAssist",
        "TrackingTemplate", "CustomParameters", "AccountStatus", "CampaignStatus", "AdGroupLabels",
        "CustomerId", "CustomerName", "FinalUrlSuffix", "CampaignType", "BaseCampaignId",
        "AllConversions", "AllRevenue", "AllConversionRate", "AllCostPerConversion",
        "AllReturnOnAdSpend", "AllRevenuePerConversion", "ViewThroughConversions", "Goal", "GoalType",
        "AdGroupType", "AverageCpm", "ConversionsQualified",
    },
    "AdPerformanceReport": {
        "AccountName", "AccountNumber", "AccountId", "TimePeriod", "CampaignName", "CampaignId",
        "AdGroupName", "AdId", "AdGroupId", "AdTitle", "AdDescription", "AdDescription2", "AdType",
        "CurrencyCode", "AdDistribution", "Impressions", "Clicks", "Ctr", "AverageCpc", "Spend",
        "AveragePosition", "Conversions", "ConversionRate", "CostPerConversion", "DestinationUrl",
        "DeviceType", "Language", "DisplayUrl", "AdStatus", "Network", "TopVsOther", "BidMatchType",
        "DeliveredMatchType", "DeviceOS", "Assists", "Revenue", "ReturnOnAdSpend", "CostPerAssist",
        "RevenuePerConversion", "RevenuePerAssist", "TrackingTemplate", "CustomParameters", "FinalUrl",
        "FinalMobileUrl", "FinalAppUrl", "AccountStatus", "CampaignStatus", "AdGroupStatus",
        "TitlePart1", "TitlePart2", "TitlePart3", "Headline", "LongHeadline", "BusinessName", "Path1",
        "Path2", "AdLabels", "CustomerId", "CustomerName", "CampaignType", "BaseCampaignId",
        "AllConversions", "AllRevenue", "AllConversionRate", "AllCostPerConversion",
        "AllReturnOnAdSpend", "AllRevenuePerConversion", "FinalUrlSuffix", "ViewThroughConversions",
        "Goal", "GoalType", "AverageCpm", "ConversionsQualified",
    },
    "KeywordPerformanceReport": {
        "AccountName", "AccountNumber", "AccountId", "TimePeriod", "CampaignName", "CampaignId",
        "AdGroupName", "AdGroupId", "Keyword", "KeywordId", "AdId", "AdType", "DestinationUrl",
        "CurrentMaxCpc", "CurrencyCode", "DeliveredMatchType", "AdDistribution", "Impressions",
        "Clicks", "Ctr", "AverageCpc", "Spend", "AveragePosition", "Conversions", "ConversionRate",
        "CostPerConversion", "BidMatchType", "DeviceType", "QualityScore", "ExpectedCtr", "AdRelevance",
        "LandingPageExperience", "Language", "HistoricalQualityScore", "HistoricalExpectedCtr",
        "HistoricalAdRelevance", "HistoricalLandingPageExperience", "QualityImpact", "CampaignStatus",
        "AccountStatus", "AdGroupStatus", "KeywordStatus", "Network", "TopVsOther", "DeviceOS",
        "Assists", "Revenue", "ReturnOnAdSpend", "CostPerAssist", "RevenuePerConversion",
        "RevenuePerAssist", "TrackingTemplate", "CustomParameters", "FinalUrl", "FinalMobileUrl",
        "FinalAppUrl", "BidStrategyType", "KeywordLabels", "Mainline1Bid", "MainlineBid",
        "FirstPageBid", "FinalUrlSuffix", "BaseCampaignId", "AllConversions", "AllRevenue",
        "AllConversionRate", "AllCostPerConversion", "AllReturnOnAdSpend", "AllRevenuePerConversion",
        "ViewThroughConversions", "Goal", "GoalType", "AverageCpm", "ConversionsQualified",
    },
}

REPORT_STREAMS = {
    # stream -> (report_type_prefix, aggregation, airbyte_table)
    "account_performance_report_daily": ("AccountPerformanceReport", "Daily", "bing_adsaccount_performance_report_daily"),
    "account_performance_report_hourly": ("AccountPerformanceReport", "Hourly", "bing_adsaccount_performance_report_hourly"),
    "campaign_performance_report_daily": ("CampaignPerformanceReport", "Daily", "bing_adscampaign_performance_report_daily"),
    "campaign_performance_report_hourly": ("CampaignPerformanceReport", "Hourly", "bing_adscampaign_performance_report_hourly"),
    "ad_group_performance_report_daily": ("AdGroupPerformanceReport", "Daily", "bing_adsad_group_performance_report_daily"),
    "ad_performance_report_daily": ("AdPerformanceReport", "Daily", "bing_adsad_performance_report_daily"),
    "keyword_performance_report_daily": ("KeywordPerformanceReport", "Daily", "bing_adskeyword_performance_report_daily"),
}

ENTITY_STREAMS = [
    "accounts",
    "campaigns",
    "ad_groups",
    "ads",
    "keywords",
    "campaign_labels",
]

ALL_STREAMS = list(REPORT_STREAMS) + ENTITY_STREAMS

# Keywords/campaign_labels: the brief's prescribed live SOAP calls return a
# different shape to Airbyte's Bulk-download-style column names (Ad_Group,
# Campaign, Client_Id, Editorial_* etc. aren't in the live API response at
# all). Best-effort semantic map; anything with no live equivalent is left
# NULL (bronze rule: store what arrived, don't fabricate).
KEYWORD_FIELD_MAP = {
    "Id": lambda k, ctx: _text(k, "Id"),
    "Bid": lambda k, ctx: _text(k.find("{*}Bid"), "Amount") if k.find("{*}Bid") is not None else None,
    "Param1": lambda k, ctx: _text(k, "Param1"),
    "Param2": lambda k, ctx: _text(k, "Param2"),
    "Param3": lambda k, ctx: _text(k, "Param3"),
    "Status": lambda k, ctx: _text(k, "Status"),
    "Keyword": lambda k, ctx: _text(k, "Text"),
    "Ad_Group": lambda k, ctx: ctx.get("ad_group_name"),
    "Campaign": lambda k, ctx: ctx.get("campaign_name"),
    "Client_Id": lambda k, ctx: None,
    "Final_Url": lambda k, ctx: (lambda fu: fu.find("{*}string").text if fu is not None and len(list(fu)) else None)(k.find("{*}FinalUrls")),
    "Parent_Id": lambda k, ctx: None,
    "Account_Id": lambda k, ctx: ctx.get("account_id"),
    "Match_Type": lambda k, ctx: _text(k, "MatchType"),
    "Campaign_Id": lambda k, ctx: ctx.get("campaign_id"),
    "Campaign_Type": lambda k, ctx: ctx.get("campaign_type"),
    "Modified_Time": lambda k, ctx: None,
    "Quality_Score": lambda k, ctx: None,
    "Editorial_Term": lambda k, ctx: None,
    "Destination_Url": lambda k, ctx: _text(k, "DestinationUrl"),
    "Custom_Parameter": lambda k, ctx: _text(k, "UrlCustomParameters"),
    "Editorial_Status": lambda k, ctx: _text(k, "EditorialStatus"),
    "Final_Url_Suffix": lambda k, ctx: _text(k, "FinalUrlSuffix"),
    "Mobile_Final_Url": lambda k, ctx: (lambda fu: fu.find("{*}string").text if fu is not None and len(list(fu)) else None)(k.find("{*}FinalMobileUrls")),
    "Bid_Strategy_Type": lambda k, ctx: _text(k, "BidStrategyType"),
    "Keyword_Relevance": lambda k, ctx: None,
    "Tracking_Template": lambda k, ctx: _text(k, "TrackingUrlTemplate"),
    "Editorial_Location": lambda k, ctx: None,
    "Publisher_Countries": lambda k, ctx: None,
    "Editorial_Reason_Code": lambda k, ctx: None,
    "Landing_Page_Relevance": lambda k, ctx: None,
    "Editorial_Appeal_Status": lambda k, ctx: None,
    "Inherited_Bid_Strategy_Type": lambda k, ctx: _text(k, "InheritedBidStrategyType"),
    "Landing_Page_User_Experience": lambda k, ctx: None,
}

CAMPAIGN_LABEL_FIELD_MAP = {
    "Id": lambda label_id, ctx: label_id,
    "Status": lambda label_id, ctx: ctx["labels"].get(label_id, {}).get("Status"),
    "Campaign": lambda label_id, ctx: ctx.get("campaign_name"),
    "Client_Id": lambda label_id, ctx: None,
    "Parent_Id": lambda label_id, ctx: None,
    "Account_Id": lambda label_id, ctx: ACCOUNT_ID,
    "Campaign_Id": lambda label_id, ctx: ctx.get("campaign_id"),
    "Campaign_Type": lambda label_id, ctx: ctx.get("campaign_type"),
    "Modified_Time": lambda label_id, ctx: None,
}


# --------------------------------------------------------------------------
# Stream runners
# --------------------------------------------------------------------------


def run_report_stream(client: BingClient, stream: str, days: int) -> dict:
    report_type, aggregation, airbyte_table = REPORT_STREAMS[stream]
    columns = mirror_columns(airbyte_table)
    request_columns = [c for c in columns if c in REPORT_COLUMN_ENUMS[report_type]]
    table = f"bing_direct_{stream}"
    ensure_table(table, columns)

    until = date.today()
    since = until - timedelta(days=days - 1)
    since_s, until_s = since.isoformat(), until.isoformat()

    print(f"  [{stream}] requesting {report_type} ({aggregation}) {since_s} -> {until_s}, "
          f"{len(request_columns)} columns")
    request_id = client.submit_report(report_type, aggregation, request_columns, since_s, until_s)
    url = client.poll_report(request_id)
    if url is None:
        print(f"  [{stream}] CompletedWithoutData — no rows in window")
        rows_csv = []
    else:
        rows_csv = download_report_csv(url)

    synced_at = now_iso()
    rows = []
    for r in rows_csv:
        row = {col: (r[i] if i < len(r) and r[i] != "" else None) for i, col in enumerate(request_columns)}
        for col in columns:
            row.setdefault(col, None)
        row["_synced_at"] = synced_at
        rows.append(row)

    date_col = "TimePeriod"
    until_exclusive = (until + timedelta(days=1)).isoformat()
    bq_delete_window(table, date_col, since_s, until_exclusive)
    loaded = bq_load_ndjson(table, rows, columns, replace=False)
    print(f"  [{stream}] fetched {len(rows)} rows, loaded {loaded}")
    return {"stream": stream, "fetched": len(rows), "loaded": loaded, "table": table}


def run_accounts(client: BingClient) -> dict:
    columns = mirror_columns("bing_adsaccounts")
    table = "bing_direct_accounts"
    ensure_table(table, columns)
    row = client.get_account_row(columns)
    row["_synced_at"] = now_iso()
    loaded = bq_load_ndjson(table, [row], columns, replace=True)
    print(f"  [accounts] fetched 1, loaded {loaded}")
    return {"stream": "accounts", "fetched": 1, "loaded": loaded, "table": table}


def run_campaigns(client: BingClient) -> tuple[dict, list[ET.Element]]:
    columns = mirror_columns("bing_adscampaigns")
    table = "bing_direct_campaigns"
    ensure_table(table, columns)
    campaign_els = client.get_campaigns()
    synced_at = now_iso()
    rows = []
    for c in campaign_els:
        row = row_from_element(c, columns)
        row["_synced_at"] = synced_at
        rows.append(row)
    loaded = bq_load_ndjson(table, rows, columns, replace=True)
    print(f"  [campaigns] fetched {len(rows)}, loaded {loaded}")
    return {"stream": "campaigns", "fetched": len(rows), "loaded": loaded, "table": table}, campaign_els


def run_ad_groups(client: BingClient, campaign_els: list[ET.Element]) -> tuple[dict, list[tuple[ET.Element, str, str]]]:
    columns = mirror_columns("bing_adsad_groups")
    table = "bing_direct_ad_groups"
    ensure_table(table, columns)
    synced_at = now_iso()
    rows = []
    ad_group_ctx = []  # (ad_group_el, campaign_id, campaign_name)
    for c in campaign_els:
        campaign_id = _text(c, "Id")
        campaign_name = _text(c, "Name")
        try:
            ad_group_els = client.get_ad_groups(campaign_id)
        except SoapFault as e:
            print(f"    ad_groups: skip campaign {campaign_id} ({e})")
            continue
        for ag in ad_group_els:
            row = row_from_element(ag, columns)
            row["_synced_at"] = synced_at
            rows.append(row)
            ad_group_ctx.append((ag, campaign_id, campaign_name))
    loaded = bq_load_ndjson(table, rows, columns, replace=True)
    print(f"  [ad_groups] fetched {len(rows)}, loaded {loaded}")
    return {"stream": "ad_groups", "fetched": len(rows), "loaded": loaded, "table": table}, ad_group_ctx


def run_ads(client: BingClient, ad_group_ctx: list[tuple[ET.Element, str, str]]) -> dict:
    columns = mirror_columns("bing_adsads")
    table = "bing_direct_ads"
    ensure_table(table, columns)
    synced_at = now_iso()
    rows = []
    for ag_el, _campaign_id, _campaign_name in ad_group_ctx:
        ad_group_id = _text(ag_el, "Id")
        try:
            ad_els = client.get_ads(ad_group_id)
        except SoapFault as e:
            print(f"    ads: skip ad_group {ad_group_id} ({e})")
            continue
        for ad_el in ad_els:
            row = row_from_element(ad_el, columns)
            if "Type" in columns and row.get("Type") is None:
                # Ad "Type" often carries as an xsi:type attribute, not a child element.
                row["Type"] = ad_el.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type")
            row["_synced_at"] = synced_at
            rows.append(row)
    loaded = bq_load_ndjson(table, rows, columns, replace=True)
    print(f"  [ads] fetched {len(rows)}, loaded {loaded}")
    return {"stream": "ads", "fetched": len(rows), "loaded": loaded, "table": table}


def run_keywords(client: BingClient, ad_group_ctx: list[tuple[ET.Element, str, str]]) -> dict:
    columns = mirror_columns("bing_adskeywords")
    table = "bing_direct_keywords"
    ensure_table(table, columns)
    synced_at = now_iso()
    rows = []
    for ag_el, campaign_id, campaign_name in ad_group_ctx:
        ad_group_id = _text(ag_el, "Id")
        ad_group_name = _text(ag_el, "Name")
        try:
            keyword_els = client.get_keywords(ad_group_id)
        except SoapFault as e:
            print(f"    keywords: skip ad_group {ad_group_id} ({e})")
            continue
        ctx = {
            "ad_group_name": ad_group_name,
            "campaign_name": campaign_name,
            "campaign_id": campaign_id,
            "campaign_type": None,
            "account_id": ACCOUNT_ID,
        }
        for kw_el in keyword_els:
            row = {col: KEYWORD_FIELD_MAP[col](kw_el, ctx) for col in columns}
            row["_synced_at"] = synced_at
            rows.append(row)
    loaded = bq_load_ndjson(table, rows, columns, replace=True)
    print(f"  [keywords] fetched {len(rows)}, loaded {loaded}")
    return {"stream": "keywords", "fetched": len(rows), "loaded": loaded, "table": table}


def run_campaign_labels(client: BingClient, campaign_els: list[ET.Element]) -> dict:
    columns = mirror_columns("bing_adscampaign_labels")
    table = "bing_direct_campaign_labels"
    ensure_table(table, columns)
    campaign_ids = [_text(c, "Id") for c in campaign_els]
    campaign_by_id = {_text(c, "Id"): (_text(c, "Name"), _text(c, "CampaignType")) for c in campaign_els}
    pairs = []
    try:
        pairs = client.get_label_associations(campaign_ids)
    except SoapFault as e:
        print(f"    campaign_labels: association fetch failed ({e})")
    label_ids = sorted({p[0] for p in pairs})
    labels = client.get_labels_by_ids(label_ids) if label_ids else {}
    synced_at = now_iso()
    rows = []
    for label_id, campaign_id in pairs:
        campaign_name, campaign_type = campaign_by_id.get(campaign_id, (None, None))
        ctx = {"labels": labels, "campaign_name": campaign_name, "campaign_id": campaign_id, "campaign_type": campaign_type}
        row = {col: CAMPAIGN_LABEL_FIELD_MAP[col](label_id, ctx) for col in columns}
        row["_synced_at"] = synced_at
        rows.append(row)
    loaded = bq_load_ndjson(table, rows, columns, replace=True)
    print(f"  [campaign_labels] fetched {len(rows)}, loaded {loaded}")
    return {"stream": "campaign_labels", "fetched": len(rows), "loaded": loaded, "table": table}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", default="all", help="comma list of stream names, or 'all'")
    ap.add_argument("--days", type=int, default=30, help="report lookback window (hourly reports use min(days,7))")
    args = ap.parse_args()

    streams = ALL_STREAMS if args.streams == "all" else [s.strip() for s in args.streams.split(",")]
    unknown = [s for s in streams if s not in ALL_STREAMS]
    if unknown:
        print(f"Unknown streams: {unknown}. Valid: {ALL_STREAMS}")
        return 2

    client = BingClient()
    customer_id = client.resolve_customer_id()
    print(f"Auth OK. CustomerId={customer_id} AccountId={ACCOUNT_ID}")

    results = []
    campaign_els: list[ET.Element] = []
    ad_group_ctx: list[tuple[ET.Element, str, str]] = []
    entity_deps_needed = any(s in streams for s in ["campaigns", "ad_groups", "ads", "keywords", "campaign_labels"])

    if entity_deps_needed and "campaigns" in streams:
        r, campaign_els = run_campaigns(client)
        results.append(r)
    elif entity_deps_needed:
        # ad_groups/ads/keywords/campaign_labels requested without campaigns:
        # still need campaign list to walk the tree, but don't report it as a stream result.
        _, campaign_els = run_campaigns(client)

    for stream in streams:
        try:
            if stream == "accounts":
                results.append(run_accounts(client))
            elif stream == "campaigns":
                continue  # already run above
            elif stream == "ad_groups":
                r, ad_group_ctx = run_ad_groups(client, campaign_els)
                results.append(r)
            elif stream == "ads":
                if not ad_group_ctx:
                    _, ad_group_ctx = run_ad_groups(client, campaign_els)
                results.append(run_ads(client, ad_group_ctx))
            elif stream == "keywords":
                if not ad_group_ctx:
                    _, ad_group_ctx = run_ad_groups(client, campaign_els)
                results.append(run_keywords(client, ad_group_ctx))
            elif stream == "campaign_labels":
                results.append(run_campaign_labels(client, campaign_els))
            elif stream in REPORT_STREAMS:
                report_days = min(args.days, 7) if "hourly" in stream else args.days
                results.append(run_report_stream(client, stream, report_days))
        except Exception as e:  # noqa: BLE001 - continue with remaining streams, report the failure
            print(f"  [{stream}] FAILED: {e}")
            results.append({"stream": stream, "fetched": 0, "loaded": 0, "error": str(e)})

    print("\n=== Summary ===")
    for r in results:
        status = "OK" if not r.get("error") else f"ERROR: {r['error'][:120]}"
        print(f"  {r['stream']:40s} fetched={r.get('fetched', 0):>7} loaded={r.get('loaded', 0):>7}  {status}")

    return 0 if not any(r.get("error") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
