"""Unit tests for SharpSpring returning-lead (re-enquiry) detection.

Pure transform tests — no network calls, no BigQuery client. Fixtures are
synthetic lead ids/values, never real customer data.
"""

from datetime import UTC, datetime, timedelta

from ingestion.sharpspring.reenquiries import (
    compute_coverage,
    compute_reenquiries,
)

NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
OLD_ENOUGH = NOW - timedelta(days=15)  # older than the 14-day returning-lead threshold
TOO_NEW = NOW - timedelta(days=10)  # younger than the threshold


def _fields(page_submitted: str, marketing_url: str, description: str, created_ts) -> dict:
    return {
        "page_submitted": page_submitted,
        "marketing_url": marketing_url,
        "description": description,
        "create_timestamp": created_ts,
    }


def test_compute_coverage_full_match():
    assert compute_coverage(59831, 59831) == 1.0


def test_compute_coverage_partial():
    assert compute_coverage(100, 200) == 0.5


def test_compute_coverage_zero_expected_is_full_coverage():
    assert compute_coverage(0, 0) == 1.0


def test_detects_changed_marketing_url():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("old-page", "new-url.com", "old notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert len(rows) == 1
    assert rows[0]["lead_id"] == "1"
    assert rows[0]["changed_fields"] == "marketing_url"
    assert rows[0]["old_marketing_url"] == "old-url.com"
    assert rows[0]["new_marketing_url"] == "new-url.com"
    assert rows[0]["event_date"] == NOW.date()  # NOW is UTC noon == London 13:00, same day
    assert rows[0]["detected_at"] == NOW


def test_detects_multiple_changed_fields_joined_with_comma():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("new-page", "new-url.com", "old notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows[0]["changed_fields"] == "page_submitted,marketing_url"


def test_no_change_produces_no_row():
    snapshot = {"1": _fields("page", "url.com", "notes", OLD_ENOUGH)}
    incoming = {"1": _fields("page", "url.com", "notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_empty_new_value_ignored_even_if_old_had_content():
    """A field going FROM populated TO blank is not a re-enquiry signal."""
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("", "old-url.com", "old notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_whitespace_only_change_ignored_trimmed_comparison():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("  old-page  ", "old-url.com", "old notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_14_day_rule_skips_leads_created_too_recently():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", TOO_NEW)}
    incoming = {"1": _fields("new-page", "old-url.com", "old notes", TOO_NEW)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_14_day_rule_boundary_flags_leads_older_than_threshold():
    boundary_ts = NOW - timedelta(days=14, minutes=1)
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", boundary_ts)}
    incoming = {"1": _fields("new-page", "old-url.com", "old notes", boundary_ts)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert len(rows) == 1


def test_per_day_dedupe_skips_leads_already_flagged_today():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("new-page", "old-url.com", "old notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today={"1"}, now=NOW)
    assert rows == []


def test_lead_not_in_snapshot_is_ignored_not_a_returning_event():
    """A brand-new lead created this run has no 'old' state — not a returning event."""
    incoming = {"1": _fields("page", "url.com", "notes", NOW)}
    rows = compute_reenquiries(incoming, snapshot={}, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_missing_created_ts_skipped_cannot_establish_age():
    snapshot = {"1": _fields("old-page", "old-url.com", "old notes", None)}
    incoming = {"1": _fields("new-page", "old-url.com", "old notes", None)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows == []


def test_description_change_detected_independently():
    snapshot = {"1": _fields("page", "url.com", "old notes", OLD_ENOUGH)}
    incoming = {"1": _fields("page", "url.com", "brand new notes", OLD_ENOUGH)}
    rows = compute_reenquiries(incoming, snapshot, already_flagged_today=set(), now=NOW)
    assert rows[0]["changed_fields"] == "description"
    assert rows[0]["old_description"] == "old notes"
    assert rows[0]["new_description"] == "brand new notes"
