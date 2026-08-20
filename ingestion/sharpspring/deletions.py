"""Detects SharpSpring leads that were deleted from the CRM.

``bronze.sharpspring_leads`` is dlt-merged on ``id`` and has no delete
handling — a lead removed in the CRM stays in bronze forever, and downstream
dashboards keep counting it. This module sweeps bronze's id set against the
live CRM id set after every sync and records anything missing into
``bronze.sharpspring_leads_deleted`` so downstream models can exclude it.

Guards (all mandatory — see ``sweep``):
    - Coverage guard: skip the sweep entirely unless the CRM id set is at
      least 95% of bronze's current distinct id count. Protects against a
      half-failed pagination wrongly flagging thousands of leads as deleted.
    - Race guard: never flag a lead whose ``create_timestamp`` is within the
      last 2 hours — a brand new lead created mid-sync hasn't necessarily
      been picked up by the CRM page we already fetched.

Can run standalone (``python -m ingestion.sharpspring.deletions`` — paginates
the CRM itself, ids only, memory-light) or be called from ``pipeline.py``
after a successful load, passing the id set the pipeline just yielded (no
second paginate needed).
"""

import os
from datetime import UTC, datetime, timedelta

import google.auth
from dotenv import load_dotenv
from google.cloud import bigquery

from ingestion.sharpspring.client import SharpSpringClient

load_dotenv()

_PROJECT = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")
_BQ_LOCATION = "europe-west2"
_DELETED_TABLE = f"{_PROJECT}.bronze.sharpspring_leads_deleted"
_LEADS_TABLE = f"{_PROJECT}.bronze.sharpspring_leads"
_MIN_COVERAGE = 0.95
_RACE_WINDOW = timedelta(hours=2)


def _bq_client() -> bigquery.Client:
    """Build a BigQuery client using application-default credentials."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=_PROJECT, credentials=creds, location=_BQ_LOCATION)


def ensure_deleted_table(bq: bigquery.Client) -> None:
    """Create ``bronze.sharpspring_leads_deleted`` if it does not exist yet."""
    schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("detected_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("last_known_name", "STRING"),
        bigquery.SchemaField("last_known_email", "STRING"),
        bigquery.SchemaField("last_known_status", "STRING"),
        bigquery.SchemaField("created_ts", "TIMESTAMP"),
    ]
    table = bigquery.Table(_DELETED_TABLE, schema=schema)
    bq.create_table(table, exists_ok=True)


def fetch_all_crm_ids() -> set[str]:
    """Paginate ``getLeads`` and keep only ids (memory-light, standalone mode)."""
    client = SharpSpringClient()
    ids: set[str] = set()
    offset = 0
    while True:
        page = client.get_leads(limit=500, offset=offset)
        if not page:
            break
        ids.update(str(row["id"]) for row in page if row.get("id"))
        if len(page) < 500:
            break
        offset += 500
    return ids


def _bronze_lead_snapshot(bq: bigquery.Client) -> dict[str, dict]:
    """Return every bronze lead id mapped to its last-known fields.

    Returns:
        Dict of id -> {name, email, status, created_ts (datetime | None)}.
    """
    job = bq.query(f"""
        SELECT
            id,
            TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, ''))) AS name,
            email_address AS email,
            status_633ae6f6ac6fe AS status,
            create_timestamp
        FROM `{_LEADS_TABLE}`
        """)
    snapshot: dict[str, dict] = {}
    for row in job.result():
        snapshot[row["id"]] = {
            "name": row["name"] or None,
            "email": row["email"] or None,
            "status": row["status"] or None,
            "created_ts": row["create_timestamp"],
        }
    return snapshot


def _existing_deleted_ids(bq: bigquery.Client) -> set[str]:
    job = bq.query(f"SELECT id FROM `{_DELETED_TABLE}`")
    return {row["id"] for row in job.result()}


def compute_coverage(crm_ids: set[str], bronze_ids: set[str]) -> float:
    """Fraction of bronze's distinct id count that the CRM id set covers."""
    return len(crm_ids) / len(bronze_ids) if bronze_ids else 1.0


def compute_diff(
    crm_ids: set[str],
    snapshot: dict[str, dict],
    existing_deleted_ids: set[str],
    now: datetime,
    race_window: timedelta = _RACE_WINDOW,
) -> tuple[list[dict], list[str]]:
    """Pure diff: which bronze ids to (re)flag as deleted, which to un-flag.

    Args:
        crm_ids: Every lead id currently present in the CRM.
        snapshot: bronze id -> {name, email, status, created_ts} (see
            ``_bronze_lead_snapshot``).
        existing_deleted_ids: Ids currently sitting in the junk table.
        now: Current UTC time (injected for deterministic tests).
        race_window: Leads created within this window of ``now`` are never
            flagged, even if missing from ``crm_ids``.

    Returns:
        Tuple of (rows_to_flag, resurrected_ids). ``rows_to_flag`` rows have
        keys id/detected_at/last_known_name/last_known_email/
        last_known_status/created_ts.
    """
    bronze_ids = set(snapshot.keys())
    cutoff = now - race_window
    missing_ids = bronze_ids - crm_ids

    rows_to_flag = []
    for lead_id in missing_ids:
        created_ts = snapshot[lead_id]["created_ts"]
        if created_ts is not None and created_ts > cutoff:
            continue  # race guard — too new to trust as a real deletion
        rows_to_flag.append(
            {
                "id": lead_id,
                "detected_at": now,
                "last_known_name": snapshot[lead_id]["name"],
                "last_known_email": snapshot[lead_id]["email"],
                "last_known_status": snapshot[lead_id]["status"],
                "created_ts": created_ts,
            }
        )

    resurrected_ids = sorted(existing_deleted_ids & crm_ids)
    return rows_to_flag, resurrected_ids


def sweep(crm_ids: set[str], bq: bigquery.Client | None = None) -> dict[str, int | bool]:
    """Compare ``crm_ids`` against bronze and update the junk table.

    Args:
        crm_ids: Every lead id currently present in the CRM (from a full,
            successful pagination — either standalone or the ids the
            pipeline just loaded).
        bq: Optional BigQuery client, mainly for tests. A fresh client using
            application-default credentials is created if omitted.

    Returns:
        Counts dict with keys ``crm_ids``, ``bronze_ids``, ``newly_flagged``,
        ``resurrected`` and ``skipped`` (True if the coverage guard tripped,
        in which case the other counts besides ``crm_ids``/``bronze_ids``
        are 0).
    """
    bq = bq or _bq_client()
    ensure_deleted_table(bq)

    snapshot = _bronze_lead_snapshot(bq)
    bronze_ids = set(snapshot.keys())

    coverage = compute_coverage(crm_ids, bronze_ids)
    if coverage < _MIN_COVERAGE:
        print(
            f"sharpspring_deletions: SKIPPED sweep — CRM id set ({len(crm_ids)}) covers "
            f"only {coverage:.1%} of bronze ({len(bronze_ids)}), below the "
            f"{_MIN_COVERAGE:.0%} guard. No changes made.",
            flush=True,
        )
        return {
            "crm_ids": len(crm_ids),
            "bronze_ids": len(bronze_ids),
            "newly_flagged": 0,
            "resurrected": 0,
            "skipped": True,
        }

    existing_deleted = _existing_deleted_ids(bq)
    rows_to_flag, resurrected_ids = compute_diff(
        crm_ids, snapshot, existing_deleted, datetime.now(UTC)
    )

    if rows_to_flag:
        _upsert_flagged(bq, rows_to_flag)
    if resurrected_ids:
        _remove_resurrected(bq, resurrected_ids)

    counts = {
        "crm_ids": len(crm_ids),
        "bronze_ids": len(bronze_ids),
        "newly_flagged": len(rows_to_flag),
        "resurrected": len(resurrected_ids),
        "skipped": False,
    }
    print(f"sharpspring_deletions: {counts}", flush=True)
    return counts


def _upsert_flagged(bq: bigquery.Client, rows: list[dict]) -> None:
    """Upsert deleted-lead rows into the junk table (detected_at refreshed each sweep)."""
    query = f"""
        MERGE `{_DELETED_TABLE}` T
        USING (
            SELECT
                id,
                detected_at,
                last_known_name,
                last_known_email,
                last_known_status,
                created_ts
            FROM UNNEST(@rows)
        ) S
        ON T.id = S.id
        WHEN MATCHED THEN
            UPDATE SET
                detected_at = S.detected_at,
                last_known_name = S.last_known_name,
                last_known_email = S.last_known_email,
                last_known_status = S.last_known_status,
                created_ts = S.created_ts
        WHEN NOT MATCHED THEN
            INSERT (id, detected_at, last_known_name, last_known_email, last_known_status, created_ts)
            VALUES (
                S.id, S.detected_at, S.last_known_name, S.last_known_email,
                S.last_known_status, S.created_ts
            )
    """
    struct_params = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("id", "STRING", row["id"]),
            bigquery.ScalarQueryParameter("detected_at", "TIMESTAMP", row["detected_at"]),
            bigquery.ScalarQueryParameter("last_known_name", "STRING", row["last_known_name"]),
            bigquery.ScalarQueryParameter("last_known_email", "STRING", row["last_known_email"]),
            bigquery.ScalarQueryParameter("last_known_status", "STRING", row["last_known_status"]),
            bigquery.ScalarQueryParameter("created_ts", "TIMESTAMP", row["created_ts"]),
        )
        for row in rows
    ]
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("rows", "STRUCT", struct_params),
        ]
    )
    bq.query(query, job_config=job_config).result()


def _remove_resurrected(bq: bigquery.Client, ids: list[str]) -> None:
    """Remove ids from the junk table that have reappeared in the CRM."""
    query = f"DELETE FROM `{_DELETED_TABLE}` WHERE id IN UNNEST(@ids)"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]
    )
    bq.query(query, job_config=job_config).result()


def run_standalone_sweep() -> dict[str, int | bool]:
    """Full standalone sweep: paginate the CRM for ids, then run ``sweep``."""
    print("sharpspring_deletions: paginating CRM for the full live id set...", flush=True)
    crm_ids = fetch_all_crm_ids()
    print(f"sharpspring_deletions: fetched {len(crm_ids)} live CRM ids", flush=True)
    return sweep(crm_ids)


if __name__ == "__main__":
    run_standalone_sweep()
