"""Unit tests for the SharpSpring CRM-deletion sweep logic.

Pure transform tests — no network calls, no BigQuery client. Fixtures are
synthetic lead ids/names, never real customer data.
"""

from datetime import UTC, datetime, timedelta

from ingestion.sharpspring.deletions import compute_coverage, compute_diff

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


def _snapshot_row(name: str, email: str, status: str, created_ts: datetime | None) -> dict:
    return {
        "name": name,
        "email": email,
        "status": status,
        "created_ts": created_ts,
    }


def test_compute_coverage_full_match():
    assert compute_coverage({"1", "2", "3"}, {"1", "2", "3"}) == 1.0


def test_compute_coverage_partial():
    assert compute_coverage({"1", "2"}, {"1", "2", "3", "4"}) == 0.5


def test_compute_coverage_empty_bronze_is_full_coverage():
    """No bronze rows at all — nothing to compare against, treat as covered."""
    assert compute_coverage(set(), set()) == 1.0


def test_compute_diff_flags_id_missing_from_crm():
    old_ts = NOW - timedelta(days=30)
    snapshot = {
        "1": _snapshot_row("Alan Davies", "alan@example.com", "Appointment", old_ts),
        "2": _snapshot_row("Sue Brown", "sue@example.com", "Follow Up", old_ts),
    }
    rows_to_flag, resurrected = compute_diff(
        crm_ids={"1"}, snapshot=snapshot, existing_deleted_ids=set(), now=NOW
    )
    assert len(rows_to_flag) == 1
    assert rows_to_flag[0]["id"] == "2"
    assert rows_to_flag[0]["last_known_name"] == "Sue Brown"
    assert rows_to_flag[0]["last_known_email"] == "sue@example.com"
    assert rows_to_flag[0]["last_known_status"] == "Follow Up"
    assert rows_to_flag[0]["created_ts"] == old_ts
    assert rows_to_flag[0]["detected_at"] == NOW
    assert resurrected == []


def test_compute_diff_race_guard_skips_recent_leads():
    """A lead created 30 minutes ago and missing from the CRM page must NOT be flagged."""
    recent_ts = NOW - timedelta(minutes=30)
    snapshot = {"1": _snapshot_row("New Lead", "new@example.com", "", recent_ts)}
    rows_to_flag, _ = compute_diff(
        crm_ids=set(), snapshot=snapshot, existing_deleted_ids=set(), now=NOW
    )
    assert rows_to_flag == []


def test_compute_diff_race_guard_boundary_flags_older_than_two_hours():
    old_enough_ts = NOW - timedelta(hours=2, minutes=1)
    snapshot = {"1": _snapshot_row("Old Lead", "old@example.com", "", old_enough_ts)}
    rows_to_flag, _ = compute_diff(
        crm_ids=set(), snapshot=snapshot, existing_deleted_ids=set(), now=NOW
    )
    assert len(rows_to_flag) == 1
    assert rows_to_flag[0]["id"] == "1"


def test_compute_diff_flags_null_created_ts_leads():
    """A missing created_ts can't be race-guarded — flag it (nothing to compare against)."""
    snapshot = {"1": _snapshot_row("Old Lead", "old@example.com", "", None)}
    rows_to_flag, _ = compute_diff(
        crm_ids=set(), snapshot=snapshot, existing_deleted_ids=set(), now=NOW
    )
    assert len(rows_to_flag) == 1
    assert rows_to_flag[0]["created_ts"] is None


def test_compute_diff_resurrects_id_back_in_crm():
    old_ts = NOW - timedelta(days=30)
    snapshot = {"1": _snapshot_row("Back Again", "back@example.com", "Appointment", old_ts)}
    rows_to_flag, resurrected = compute_diff(
        crm_ids={"1"}, snapshot=snapshot, existing_deleted_ids={"1", "2"}, now=NOW
    )
    assert rows_to_flag == []
    assert resurrected == ["1"]  # "2" not in existing_deleted ∩ crm_ids — stays flagged


def test_compute_diff_ignores_ids_not_in_bronze_at_all():
    """Only bronze ids drive the diff — a CRM id with no bronze row yet is not our concern."""
    snapshot = {"1": _snapshot_row("Known Lead", "known@example.com", "", NOW - timedelta(days=1))}
    rows_to_flag, resurrected = compute_diff(
        crm_ids={"1", "999-not-in-bronze-yet"},
        snapshot=snapshot,
        existing_deleted_ids=set(),
        now=NOW,
    )
    assert rows_to_flag == []
    assert resurrected == []
