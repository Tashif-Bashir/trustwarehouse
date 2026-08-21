"""Detects SharpSpring leads that have re-enquired (returning leads).

SharpSpring dedupes by email: when someone who already has a lead fills in a
website form again, the CRM does not create a new lead — it silently
overwrites the existing lead's re-enquiry signal fields
(``page_submitted_5af30a9090796``, ``exact_marketing_url_64d0bebced518``,
``description``) with the new visit's values. Because ``bronze.sharpspring_leads``
is dlt-merged on ``id`` (latest-state only), these returns are invisible —
the old values are gone the moment the merge lands.

This module takes a snapshot of every lead's signal fields *before* the
pipeline run (while bronze still holds the old values), then compares that
snapshot against the freshly-loaded rows *after* the run to detect changes.
Detected events are recorded in ``bronze.sharpspring_lead_reenquiries``.

Owner ruling (21 Aug 2026): a returning-lead event is an EXISTING lead,
created more than 14 days before detection, where any of the three signal
fields changed (trimmed comparison) and the new value is non-empty. At most
one event is recorded per lead per Europe/London calendar day.

Guards (mirrors ``deletions.py``):
    - Coverage guard: skip detection entirely unless the pre-load snapshot
      covers at least 95% of the expected row count. Protects against a
      failed/partial snapshot query wrongly flagging thousands of leads.
    - Per-day dedupe: a lead already flagged for today's Europe/London date
      is skipped, keeping repeated ~35-minute VM runs idempotent.

Can be wired into ``pipeline.py`` (snapshot before ``pipeline.run()``, detect
after) or run standalone for testing the compare logic.
"""

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import google.auth
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

_PROJECT = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")
_BQ_LOCATION = "europe-west2"
_LEADS_TABLE = f"{_PROJECT}.bronze.sharpspring_leads"
_REENQUIRIES_TABLE = f"{_PROJECT}.bronze.sharpspring_lead_reenquiries"
_MIN_COVERAGE = 0.95
_RETURNING_AGE = timedelta(days=14)
_LONDON = ZoneInfo("Europe/London")

# The three re-enquiry signal fields, in the order changed_fields is reported.
SIGNAL_FIELDS = (
    "page_submitted_5af30a9090796",
    "exact_marketing_url_64d0bebced518",
    "description",
)


def _bq_client() -> bigquery.Client:
    """Build a BigQuery client using application-default credentials."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=_PROJECT, credentials=creds, location=_BQ_LOCATION)


def ensure_reenquiries_table(bq: bigquery.Client) -> None:
    """Create ``bronze.sharpspring_lead_reenquiries`` if it does not exist yet."""
    schema = [
        bigquery.SchemaField("lead_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("detected_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("event_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("lead_created_ts", "TIMESTAMP"),
        bigquery.SchemaField("changed_fields", "STRING"),
        bigquery.SchemaField("old_marketing_url", "STRING"),
        bigquery.SchemaField("new_marketing_url", "STRING"),
        bigquery.SchemaField("old_page_submitted", "STRING"),
        bigquery.SchemaField("new_page_submitted", "STRING"),
        bigquery.SchemaField("old_description", "STRING"),
        bigquery.SchemaField("new_description", "STRING"),
    ]
    table = bigquery.Table(_REENQUIRIES_TABLE, schema=schema)
    bq.create_table(table, exists_ok=True)


def snapshot_bronze_leads(bq: bigquery.Client) -> dict[str, dict]:
    """Pre-load snapshot: every bronze lead id mapped to its current signal fields.

    Must be called BEFORE ``pipeline.run()`` — the merge overwrites these
    values with the new load's values, destroying the "old" state.

    Returns:
        Dict of lead id -> {page_submitted, marketing_url, description,
        create_timestamp (datetime | None)}.
    """
    job = bq.query(f"""
        SELECT
            id,
            page_submitted_5af30a9090796 AS page_submitted,
            exact_marketing_url_64d0bebced518 AS marketing_url,
            description,
            create_timestamp
        FROM `{_LEADS_TABLE}`
        """)
    snapshot: dict[str, dict] = {}
    for row in job.result():
        snapshot[row["id"]] = {
            "page_submitted": row["page_submitted"] or "",
            "marketing_url": row["marketing_url"] or "",
            "description": row["description"] or "",
            "create_timestamp": row["create_timestamp"],
        }
    return snapshot


def get_expected_lead_count(bq: bigquery.Client) -> int:
    """Current distinct lead count in bronze — the coverage guard's denominator.

    Cheap to call right after ``snapshot_bronze_leads`` since the snapshot
    query already scanned the table; a mismatch here means the snapshot
    query itself returned a truncated/partial result.
    """
    job = bq.query(f"SELECT COUNT(*) AS n FROM `{_LEADS_TABLE}`")
    return next(iter(job.result()))["n"]


def take_preload_snapshot(bq: bigquery.Client | None = None) -> tuple[dict[str, dict] | None, int]:
    """Self-contained pre-load step: snapshot + expected count, with failure isolation.

    Call this BEFORE ``pipeline.run()``. Never raises — any failure (network,
    auth, query error) is caught and reported as a None snapshot so the
    caller's ``detect()`` call skips cleanly instead of aborting the load.

    Args:
        bq: Optional BigQuery client, mainly for tests.

    Returns:
        Tuple of (snapshot or None on failure, expected_count).
    """
    try:
        bq = bq or _bq_client()
        snapshot = snapshot_bronze_leads(bq)
        expected = get_expected_lead_count(bq)
        return snapshot, expected
    except Exception as exc:  # noqa: BLE001 — a snapshot failure must never abort the sync
        print(
            f"sharpspring_reenquiries: snapshot query failed ({exc}) — will skip detection.",
            flush=True,
        )
        return None, 0


def _existing_today_ids(bq: bigquery.Client, event_date: date) -> set[str]:
    """Lead ids already flagged today — for per-day dedupe."""
    job = bq.query(
        f"SELECT lead_id FROM `{_REENQUIRIES_TABLE}` WHERE event_date = @event_date",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("event_date", "DATE", event_date)]
        ),
    )
    return {row["lead_id"] for row in job.result()}


def compute_coverage(snapshot_count: int, expected_count: int) -> float:
    """Fraction of the expected row count the pre-load snapshot covers."""
    return snapshot_count / expected_count if expected_count else 1.0


def compute_reenquiries(
    incoming: dict[str, dict],
    snapshot: dict[str, dict],
    already_flagged_today: set[str],
    now: datetime,
    min_age: timedelta = _RETURNING_AGE,
) -> list[dict]:
    """Pure diff: which leads re-enquired between snapshot and this load.

    Args:
        incoming: lead id -> {page_submitted, marketing_url, description,
            create_timestamp} captured from the rows the pipeline just
            yielded (the NEW state, post-load).
        snapshot: lead id -> same shape, captured BEFORE the load (the OLD
            state). See ``snapshot_bronze_leads``.
        already_flagged_today: lead ids that already have a reenquiries row
            for today's event_date — skipped for per-day dedupe.
        now: current time, timezone-aware (injected for deterministic
            tests). Used both for ``detected_at`` and to compute
            ``event_date`` (Europe/London day) and lead age.
        min_age: minimum lead age (vs ``lead_created_ts``) to qualify as
            "returning" rather than a same-visit edit.

    Returns:
        List of row dicts ready to insert into
        ``bronze.sharpspring_lead_reenquiries``.
    """
    event_date = now.astimezone(_LONDON).date()
    rows: list[dict] = []

    for lead_id, new in incoming.items():
        if lead_id in already_flagged_today:
            continue
        old = snapshot.get(lead_id)
        if old is None:
            continue  # brand new lead this run — not a returning event

        created_ts = new.get("create_timestamp") or old.get("create_timestamp")
        if created_ts is None:
            continue  # can't establish age — do not guess
        if now - created_ts < min_age:
            continue  # too new to be "returning" — a same-visit edit

        changed: list[str] = []
        if _changed(old["page_submitted"], new["page_submitted"]):
            changed.append("page_submitted")
        if _changed(old["marketing_url"], new["marketing_url"]):
            changed.append("marketing_url")
        if _changed(old["description"], new["description"]):
            changed.append("description")

        if not changed:
            continue

        rows.append(
            {
                "lead_id": lead_id,
                "detected_at": now,
                "event_date": event_date,
                "lead_created_ts": created_ts,
                "changed_fields": ",".join(changed),
                "old_marketing_url": old["marketing_url"] or None,
                "new_marketing_url": new["marketing_url"] or None,
                "old_page_submitted": old["page_submitted"] or None,
                "new_page_submitted": new["page_submitted"] or None,
                "old_description": old["description"] or None,
                "new_description": new["description"] or None,
            }
        )

    return rows


def _changed(old_value: str, new_value: str) -> bool:
    """True if ``new_value`` is non-empty and differs (trimmed) from ``old_value``."""
    new_trimmed = (new_value or "").strip()
    if not new_trimmed:
        return False
    return new_trimmed != (old_value or "").strip()


def _insert_rows(bq: bigquery.Client, rows: list[dict]) -> None:
    """Insert new reenquiry rows (append-only — never updated/merged)."""
    query = f"""
        INSERT INTO `{_REENQUIRIES_TABLE}` (
            lead_id, detected_at, event_date, lead_created_ts, changed_fields,
            old_marketing_url, new_marketing_url,
            old_page_submitted, new_page_submitted,
            old_description, new_description
        )
        SELECT
            lead_id, detected_at, event_date, lead_created_ts, changed_fields,
            old_marketing_url, new_marketing_url,
            old_page_submitted, new_page_submitted,
            old_description, new_description
        FROM UNNEST(@rows)
    """
    struct_params = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("lead_id", "STRING", row["lead_id"]),
            bigquery.ScalarQueryParameter("detected_at", "TIMESTAMP", row["detected_at"]),
            bigquery.ScalarQueryParameter("event_date", "DATE", row["event_date"]),
            bigquery.ScalarQueryParameter("lead_created_ts", "TIMESTAMP", row["lead_created_ts"]),
            bigquery.ScalarQueryParameter("changed_fields", "STRING", row["changed_fields"]),
            bigquery.ScalarQueryParameter("old_marketing_url", "STRING", row["old_marketing_url"]),
            bigquery.ScalarQueryParameter("new_marketing_url", "STRING", row["new_marketing_url"]),
            bigquery.ScalarQueryParameter(
                "old_page_submitted", "STRING", row["old_page_submitted"]
            ),
            bigquery.ScalarQueryParameter(
                "new_page_submitted", "STRING", row["new_page_submitted"]
            ),
            bigquery.ScalarQueryParameter("old_description", "STRING", row["old_description"]),
            bigquery.ScalarQueryParameter("new_description", "STRING", row["new_description"]),
        )
        for row in rows
    ]
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("rows", "STRUCT", struct_params)]
    )
    bq.query(query, job_config=job_config).result()


def detect(
    incoming: dict[str, dict],
    snapshot: dict[str, dict] | None,
    expected_count: int,
    bq: bigquery.Client | None = None,
) -> dict[str, int | bool]:
    """Compare ``incoming`` against ``snapshot`` and record returning-lead events.

    Args:
        incoming: lead id -> signal fields captured from this run's yielded
            rows (see ``pipeline.py``'s capture dict).
        snapshot: The pre-load snapshot from ``snapshot_bronze_leads``, or
            None if the snapshot query itself failed.
        expected_count: Row count bronze held before this run (used only to
            size the coverage guard — pass the same figure the snapshot
            query should have returned, e.g. the snapshot's own len() plus
            any known discrepancy check upstream).
        bq: Optional BigQuery client, mainly for tests.

    Returns:
        Counts dict with keys ``checked``, ``changed``, ``inserted``,
        ``skipped`` (True if the coverage guard tripped).
    """
    bq = bq or _bq_client()
    ensure_reenquiries_table(bq)

    if snapshot is None:
        print(
            "sharpspring_reenquiries: SKIPPED — pre-load snapshot query failed. "
            "No changes made.",
            flush=True,
        )
        return {"checked": 0, "changed": 0, "inserted": 0, "skipped": True}

    coverage = compute_coverage(len(snapshot), expected_count)
    if coverage < _MIN_COVERAGE:
        print(
            f"sharpspring_reenquiries: SKIPPED — snapshot ({len(snapshot)} rows) covers "
            f"only {coverage:.1%} of expected ({expected_count}), below the "
            f"{_MIN_COVERAGE:.0%} guard. No changes made.",
            flush=True,
        )
        return {"checked": len(snapshot), "changed": 0, "inserted": 0, "skipped": True}

    now = datetime.now(UTC)
    event_date = now.astimezone(_LONDON).date()
    already_flagged_today = _existing_today_ids(bq, event_date)

    rows = compute_reenquiries(incoming, snapshot, already_flagged_today, now)

    if rows:
        _insert_rows(bq, rows)

    counts = {
        "checked": len(incoming),
        "changed": len(rows),
        "inserted": len(rows),
        "skipped": False,
    }
    print(f"sharpspring_reenquiries: {counts}", flush=True)
    return counts
