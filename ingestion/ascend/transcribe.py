"""Transcribe Ascend call recordings into bronze.ascend_transcripts.

Runs as a scheduled batch on the VM (see scripts/systemd/ascend-transcribe.*):
  1. Find agents (user uuids) from bronze.ascend_calls.
  2. List their recent recordings; keep calls >= MIN_SECONDS not yet transcribed.
  3. Stream each MP3 to a temp file, transcribe with faster-whisper, delete the file
     (no audio is retained anywhere — only the text lands in BigQuery).
  4. Match the remote phone number to a SharpSpring lead where possible.

Run: uv run python -m ingestion.ascend.transcribe
Env knobs: ASCEND_TRANSCRIBE_MIN_SECONDS (120), ASCEND_TRANSCRIBE_LOOKBACK_DAYS (3),
           ASCEND_TRANSCRIBE_MAX_PER_RUN (60), ASCEND_WHISPER_MODEL (small)
"""

import os
import tempfile
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from ingestion.ascend.client import AscendClient

warnings.filterwarnings("ignore")
load_dotenv()

PROJECT = os.environ.get("GCP_PROJECT_ID", "trustwarehouse")
TABLE = f"{PROJECT}.bronze.ascend_transcripts"

MIN_SECONDS = int(os.environ.get("ASCEND_TRANSCRIBE_MIN_SECONDS", "120"))
LOOKBACK_DAYS = int(os.environ.get("ASCEND_TRANSCRIBE_LOOKBACK_DAYS", "3"))
MAX_PER_RUN = int(os.environ.get("ASCEND_TRANSCRIBE_MAX_PER_RUN", "60"))
WHISPER_MODEL = os.environ.get("ASCEND_WHISPER_MODEL", "small")

DDL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE}` (
  recording_id INT64,
  call_id STRING,
  user_uuid STRING,
  agent STRING,
  direction STRING,
  remote_phone STRING,
  call_time TIMESTAMP,
  duration_seconds INT64,
  recording_file STRING,
  lead_id STRING,
  transcript STRING,
  model STRING,
  transcribed_at TIMESTAMP
)
"""


def _normalise_phone(raw: str | None) -> str | None:
    """UK phone normalisation — must mirror shared/phone.py."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def _agents(bq: bigquery.Client) -> dict[str, str]:
    """uuid -> display name for every real user seen in the CDRs.

    Auto-attendants/external legs carry pseudo ids (base64-ish, ':E' suffix) that the
    recordings endpoint rejects — only proper GUIDs are real users.
    """
    rows = bq.query(f"""
        SELECT DISTINCT JSON_VALUE(side, '$.userUniqueId') AS uuid,
               JSON_VALUE(side, '$.name') AS name
        FROM `{PROJECT}.bronze.ascend_calls`,
             UNNEST([`from`, `to`]) AS side
        WHERE REGEXP_CONTAINS(JSON_VALUE(side, '$.userUniqueId'),
              r'^[0-9A-Fa-f]{{8}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{12}}$')
    """).result()
    return {r["uuid"]: r["name"] or "" for r in rows}


def _done_ids(bq: bigquery.Client) -> set[int]:
    rows = bq.query(f"SELECT recording_id FROM `{TABLE}`").result()
    return {r["recording_id"] for r in rows}


def _match_leads(bq: bigquery.Client, phones: list[str]) -> dict[str, str]:
    """normalised phone -> SharpSpring lead id (most recently updated wins)."""
    phones = [p for p in phones if p]
    if not phones:
        return {}
    rows = bq.query(
        f"""
        SELECT ph, id FROM (
          SELECT REGEXP_REPLACE(COALESCE(phone_number, ''), r'[^0-9]', '') AS raw_ph,
                 REGEXP_REPLACE(COALESCE(mobile_phone_number, ''), r'[^0-9]', '') AS raw_mob,
                 id, update_timestamp
          FROM `{PROJECT}.bronze.sharpspring_leads`
        ), UNNEST([
             IF(STARTS_WITH(raw_ph, '0') AND NOT STARTS_WITH(raw_ph, '00'), CONCAT('44', SUBSTR(raw_ph, 2)),
                IF(STARTS_WITH(raw_ph, '00'), SUBSTR(raw_ph, 3), raw_ph)),
             IF(STARTS_WITH(raw_mob, '0') AND NOT STARTS_WITH(raw_mob, '00'), CONCAT('44', SUBSTR(raw_mob, 2)),
                IF(STARTS_WITH(raw_mob, '00'), SUBSTR(raw_mob, 3), raw_mob))
           ]) AS ph
        WHERE ph IN UNNEST(@phones) AND ph != ''
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ph ORDER BY update_timestamp DESC) = 1
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("phones", "STRING", phones),
        ]),
    ).result()
    return {r["ph"]: str(r["id"]) for r in rows}


def run() -> None:
    bq = bigquery.Client(project=PROJECT)
    bq.query(DDL).result()

    agents = _agents(bq)
    done = _done_ids(bq)
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    client = AscendClient()

    # Collect the work list first so we can lead-match in one query.
    todo: list[dict] = []
    for uuid, name in agents.items():
        try:
            for rec in client.get_call_recordings(uuid):
                when = datetime.fromisoformat(rec["whenCreated"])
                if when < cutoff:
                    break  # newest-first — everything after this is older
                if rec["id"] in done or rec.get("duration", 0) < MIN_SECONDS:
                    continue
                # Customer calls only (Wildix parity): a short remote number is an
                # internal extension — internal calls are recorded on BOTH sides and
                # would be transcribed twice.
                remote_digits = "".join(c for c in (rec.get("caller", {}).get("phoneNumber") or "") if c.isdigit())
                if len(remote_digits) < 7:
                    continue
                todo.append({**rec, "user_uuid": uuid, "agent": name})
        except Exception as exc:  # noqa: BLE001 — one bad user must not sink the batch
            if "404" in str(exc):
                continue  # recording not enabled for this user (e.g. field reps) — expected
            print(f"  WARNING: listing recordings failed for {name or uuid}: {exc}", flush=True)
    todo.sort(key=lambda r: r["whenCreated"], reverse=True)
    dropped = max(0, len(todo) - MAX_PER_RUN)
    todo = todo[:MAX_PER_RUN]
    print(f"recordings to transcribe: {len(todo)}"
          + (f" (deferring {dropped} to next run)" if dropped else ""))
    if not todo:
        return

    leads = _match_leads(bq, [_normalise_phone(r["caller"]["phoneNumber"]) for r in todo])

    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    rows = []
    for rec in todo:
        tmp = Path(tempfile.gettempdir()) / f"ascend_{rec['id']}.mp3"
        try:
            tmp.write_bytes(client.download_recording(rec["user_uuid"], rec["id"]))
            segments, _info = model.transcribe(str(tmp), language="en", vad_filter=True)
            text = " ".join(s.text.strip() for s in segments)
        finally:
            tmp.unlink(missing_ok=True)  # never retain audio
        phone = _normalise_phone(rec["caller"]["phoneNumber"])
        rows.append({
            "recording_id": rec["id"],
            "call_id": rec.get("callId"),
            "user_uuid": rec["user_uuid"],
            "agent": rec["agent"],
            "direction": rec.get("direction"),
            "remote_phone": rec["caller"]["phoneNumber"],
            "call_time": rec["whenCreated"],
            "duration_seconds": rec.get("duration"),
            "recording_file": rec.get("fileName"),
            "lead_id": leads.get(phone or ""),
            "transcript": text,
            "model": f"faster-whisper-{WHISPER_MODEL}-int8",
            "transcribed_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"  done {rec['id']} ({rec.get('duration')}s, {len(text)} chars)", flush=True)

    errors = bq.insert_rows_json(TABLE, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors[:3]}")
    print(f"inserted {len(rows)} transcripts into {TABLE}")


if __name__ == "__main__":
    run()
