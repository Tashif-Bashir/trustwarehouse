"""Availability internal webapp — Flask app with session auth."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import threading
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, abort,
)

try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from calendar_analysis.availability import (
        fetch_events, build_grid, build_rep_diary, region_from_postcode,
        region_from_city, all_regions, reps_for_region, REP_EMAIL,
        reload_reps, get_graph_token, CALENDAR_MAILBOX,
    )
except ImportError:
    # Vercel deployment: calendar engine is bundled alongside this file
    from availability_engine import (  # type: ignore[no-redef]
        fetch_events, build_grid, build_rep_diary, region_from_postcode,
        region_from_city, all_regions, reps_for_region, REP_EMAIL,
        reload_reps, get_graph_token, CALENDAR_MAILBOX,
    )

app = Flask(__name__)

# Internal tool: keep it out of search engines. noindex stops Google listing
# it; it does NOT make the app private - that is what the login is for.
@app.after_request
def _noindex(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


@app.route("/robots.txt")
def _robots():
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}

app.secret_key = os.environ.get("AVAILABILITY_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=8)

# ---------------------------------------------------------------------------
# Redis slot lock (Upstash REST — no persistent connection needed)
# ---------------------------------------------------------------------------

_REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_LOCK_TTL    = 20  # seconds — long enough for Graph round-trip


def _lock_key(rep_email: str, date_iso: str, start_time: str) -> str:
    safe = f"{rep_email}:{date_iso}:{start_time}".replace("@", "_").replace(".", "_").replace(":", "")
    return f"slot_{safe}"


def _redis_acquire(key: str, value: str) -> bool:
    """SET key value NX EX _LOCK_TTL — returns True if we got the lock."""
    if not _REDIS_URL:
        return True
    try:
        r = requests.post(
            f"{_REDIS_URL}/set/{key}/{value}/NX/EX/{_LOCK_TTL}",
            headers={"Authorization": f"Bearer {_REDIS_TOKEN}"},
            timeout=5,
        )
        return r.json().get("result") == "OK"
    except Exception:
        return True  # Redis down — fail open, don't block bookings


def _redis_release(key: str, value: str) -> None:
    """Delete the lock only if we still own it."""
    if not _REDIS_URL:
        return
    try:
        current = requests.get(
            f"{_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_REDIS_TOKEN}"},
            timeout=5,
        ).json().get("result")
        if current == value:
            requests.post(
                f"{_REDIS_URL}/del/{key}",
                headers={"Authorization": f"Bearer {_REDIS_TOKEN}"},
                timeout=5,
            )
    except Exception:
        pass


def _slot_is_free(rep_email: str, date_iso: str, start_time: str, end_time: str) -> bool:
    """Re-verify via Graph that no event for this rep overlaps the slot."""
    try:
        token = get_graph_token()
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{CALENDAR_MAILBOX}/calendarView"
            f"?startDateTime={date_iso}T{start_time}:00"
            f"&endDateTime={date_iso}T{end_time}:00"
            "&$select=attendees",
            headers={
                "Authorization": f"Bearer {token}",
                "Prefer": 'outlook.timezone="Europe/London"',
            },
            timeout=15,
        )
        if not resp.ok:
            return True  # Can't verify — fail open
        rep_lower = rep_email.lower()
        for event in resp.json().get("value", []):
            for att in event.get("attendees", []):
                if att.get("emailAddress", {}).get("address", "").lower() == rep_lower:
                    return False
    except Exception:
        return True  # Fail open
    return True


# ---------------------------------------------------------------------------
# BigQuery / GCS
# ---------------------------------------------------------------------------

from google.cloud import bigquery, storage

BQ_PROJECT = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
BQ_USERS    = f"`{BQ_PROJECT}.app.users`"
BQ_REPS     = f"`{BQ_PROJECT}.app.reps`"
BQ_BOOKINGS = f"`{BQ_PROJECT}.app.bookings`"
GCS_BUCKET = os.environ.get("GCS_AVATAR_BUCKET", "trustwarehouse-avatars")

_bq_client: bigquery.Client | None = None
_gcs_client: storage.Client | None = None


def _gcp_creds():
    """Return service account credentials from GOOGLE_CREDENTIALS_JSON env var."""
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        return None
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT, credentials=_gcp_creds())
    return _bq_client


def _gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=BQ_PROJECT, credentials=_gcp_creds())
    return _gcs_client


# ---------------------------------------------------------------------------
# Reps store (BigQuery-backed)
# ---------------------------------------------------------------------------

_KNOWN_REGIONS = [
    "North East", "Yorkshire & Humber", "North West",
    "West Midlands", "East Midlands",
    "London", "South East", "East of England", "South West",
    "Wales", "Scotland",
]


def _row_to_rep(row) -> dict:
    return {
        "name":         row["name"],
        "email":        row["email"] or "",
        "regions":      json.loads(row["regions"] or "[]"),
        "fallback":     bool(row["fallback"]),
        "freelancer":   bool(row["freelancer"]),
        "weekend_days": json.loads(row["weekend_days"] or "[]"),
        "aliases":      json.loads(row["aliases"] or "[]"),
        "sharpspring_owner_id": row["sharpspring_owner_id"] or "",
    }


# Valid options for the SharpSpring "Appointment Booked By" picklist
# (field appointment_made_by_65e1a90253305). A booking user's sharpspring_name
# must match one of these exactly, or be left blank.
MADE_BY_OPTIONS = [
    "Gemma Taylor", "Susan England", "Alicja Aleksiuk", "Lily Harpham",
    "Reilly Andrew", "Josh Baron", "Kim Ellis", "Victoria Ramsden",
    "Alice Hardegon", "Declan Franks", "Other", "Amelia Konczewska",
    "Alisha Moore", "Ashleigh Nankervis", "Peter Heaton",
]


def _get_all_reps() -> list[dict]:
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_REPS} ORDER BY created_at"
    ).result())
    return [_row_to_rep(r) for r in rows]


def _rep_owner_id(rep_name: str) -> str:
    """Return a rep's SharpSpring owner ID (for lead reassignment), or '' if unknown."""
    if not rep_name:
        return ""
    rows = list(_bq().query(
        f"SELECT sharpspring_owner_id FROM {BQ_REPS} WHERE name = @n LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("n", "STRING", rep_name),
        ]),
    ).result())
    return (rows[0]["sharpspring_owner_id"] or "") if rows else ""


# Outlook master-category names (the pre-coloured tags), cached ~hourly.
_master_cat_cache: dict = {"ts": 0.0, "names": []}
_master_cat_lock = threading.Lock()


def _master_categories() -> list[str]:
    now = time.time()
    with _master_cat_lock:
        if _master_cat_cache["names"] and now - _master_cat_cache["ts"] < 3600:
            return _master_cat_cache["names"]
    names: list[str] = []
    try:
        token = get_graph_token()
        r = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{CALENDAR_MAILBOX}/outlook/masterCategories",
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.ok:
            names = [c.get("displayName", "") for c in r.json().get("value", []) if c.get("displayName")]
    except Exception:
        app.logger.exception("master categories fetch failed")
    if names:
        with _master_cat_lock:
            _master_cat_cache.update(ts=now, names=names)
        return names
    return _master_cat_cache["names"]


def _rep_outlook_category(rep_name: str) -> str:
    """Return the rep's exact Outlook master-category name (so the colour shows), else first name.

    Matches, in order: full rep name → aliases → first name — against the mailbox's master
    categories. Handles the inconsistent naming (full names, first names, and nicknames like
    'Kourosh' for Kris, 'Sammy' for Samuel).
    """
    if not rep_name:
        return ""
    first = rep_name.split()[0]
    candidates = [rep_name]
    try:
        rows = list(_bq().query(
            f"SELECT aliases FROM {BQ_REPS} WHERE name = @n LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("n", "STRING", rep_name)]),
        ).result())
        if rows:
            candidates += json.loads(rows[0]["aliases"] or "[]")
    except Exception:
        app.logger.exception("rep aliases lookup failed")
    candidates.append(first)
    by_lower = {m.lower(): m for m in _master_categories()}
    for c in candidates:
        if c and c.lower() in by_lower:
            return by_lower[c.lower()]
    return first


def _record_booking(**kv) -> None:
    """Insert an `active` booking row so the appointment can be cancelled later from the diary.

    Keyed by the Graph event id — this is the link between a diary entry and the lead/booker.
    Never raises: a logging failure must not break a successful booking.
    """
    if not kv.get("event_id"):
        return
    try:
        _bq().query(
            f"INSERT INTO {BQ_BOOKINGS}"
            f" (event_id, lead_id, booker_username, booker_owner_id, booker_name,"
            f"  rep_name, rep_owner_id, customer, postcode, appt_date, appt_start, appt_end,"
            f"  appt_type, booked_at, status, is_rebook, entered_by)"
            f" VALUES (@event_id, @lead_id, @booker_username, @booker_owner_id, @booker_name,"
            f"  @rep_name, @rep_owner_id, @customer, @postcode, @appt_date, @appt_start, @appt_end,"
            f"  @appt_type, @booked_ts, 'active', @is_rebook, @entered_by)",
            job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
                booked_ts=datetime.now(timezone.utc).isoformat(),
                is_rebook=bool(kv.pop("is_rebook", False)),
                entered_by=str(kv.pop("entered_by", "") or ""), **kv,
            )),
        ).result()
    except Exception:
        app.logger.exception("Failed to record booking row (booking still succeeded)")


def _annotate_cancellable(diary: dict) -> None:
    """Mark each diary appointment `cancellable` if its event has an active booking row.

    Only appointments booked through the tool (and not yet cancelled) can be cancelled here.
    """
    ids = [a["event_id"] for rep in diary.get("reps", [])
           for a in rep.get("appointments", []) if a.get("event_id")]
    active: set[str] = set()
    if ids:
        try:
            rows = _bq().query(
                f"SELECT event_id FROM {BQ_BOOKINGS} WHERE status = 'active'"
                f" AND event_id IN UNNEST(@ids)",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ArrayQueryParameter("ids", "STRING", ids),
                ]),
            ).result()
            active = {r["event_id"] for r in rows}
        except Exception:
            app.logger.exception("cancellable lookup failed")
    for rep in diary.get("reps", []):
        for a in rep.get("appointments", []):
            a["cancellable"] = a.get("event_id", "") in active


def _get_active_booking(event_id: str) -> dict | None:
    """Return the active booking row for a calendar event, or None."""
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_BOOKINGS} WHERE event_id = @e AND status = 'active' LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("e", "STRING", event_id),
        ]),
    ).result())
    return dict(rows[0]) if rows else None


def _booking_started(booking: dict) -> bool:
    """True once a booking's appointment start is now or in the past.

    Full datetime comparison on Europe/London wall clock (_now_uk — same BST/GMT
    handling as the availability engine's _now_london, just this file's own copy)
    — never UTC, and never date-only (an appointment that started earlier TODAY
    must count as started, not just ones from an earlier date). Used to lock
    Reschedule/Cancel server-side once an appointment is underway or done —
    the UI hides the buttons too, but that alone is bypassable.
    """
    try:
        start_dt = datetime.strptime(
            f"{booking.get('appt_date', '')} {booking.get('appt_start', '')}",
            "%Y-%m-%d %H:%M",
        )
    except (ValueError, TypeError):
        return False  # can't parse -> don't lock on a guess
    return start_dt <= _now_uk()


def _ss_cancel_lead(lead: dict, booker_owner_id: str, appt_type: str = "heating") -> bool:
    """Revert a lead on cancellation: status→Cancelled, Booked→No, owner→booker.

    Only the status field(s) the booking set to Appointment are reverted (per appt_type);
    a Follow Up / Not Interested written on the other pipeline at booking time stays.
    If the booker's owner id is unknown, keep the lead's current owner rather than
    letting SharpSpring reassign it to the API account.
    """
    owner_to_set = booker_owner_id or (lead.get("ownerID") or "")
    obj = {
        "id": str(lead.get("id")),
        _SS_F_APPT_BOOKED: "No",
        _SS_F_APPT_DT: "",    # a cancelled appointment has no time...
        _SS_F_APPT_TYPE: "",  # ...and no Physical/Video type
        # _SS_F_BOOKED_TS deliberately KEPT: the booking event happened, and the
        # dashboard counts bookings permanently by this timestamp (18 Jul 2026).
    }
    old_appt = lead.get(_SS_F_APPT_DT) or ""
    if old_appt:
        obj[_SS_F_PREV_APPT] = old_appt  # ...but it's preserved as the previous one
    if appt_type in ("heating", "both") or appt_type not in APPT_TYPES:
        obj[_SS_F_STATUS] = "Appointment Cancelled"
    if appt_type in ("water", "both"):
        obj[_SS_F_STATUS_WATER] = "Appointment Cancelled"
    if owner_to_set:
        obj["ownerID"] = str(owner_to_set)
    resp = _ss_call("updateLeads", {"objects": [obj]})
    updates = (resp.get("result") or {}).get("updates", []) if resp else []
    return bool(updates and updates[0].get("success"))


def _ss_delete_event(event_id: str) -> bool:
    """Delete a calendar event. True on success or if already gone (404)."""
    try:
        token = get_graph_token()
        r = requests.delete(
            f"https://graph.microsoft.com/v1.0/users/{CALENDAR_MAILBOX}/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        return r.status_code in (204, 404)
    except Exception:
        app.logger.exception("Graph event delete failed")
        return False


def _mark_booking_cancelled(event_id: str, cancelled_by: str) -> None:
    try:
        _bq().query(
            f"UPDATE {BQ_BOOKINGS} SET status = 'cancelled', cancelled_at = @cts,"
            f" cancelled_by = @u WHERE event_id = @e AND status = 'active'",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("cts", "TIMESTAMP", datetime.now(timezone.utc).isoformat()),
                bigquery.ScalarQueryParameter("u", "STRING", cancelled_by),
                bigquery.ScalarQueryParameter("e", "STRING", event_id),
            ]),
        ).result()
    except Exception:
        app.logger.exception("Failed to mark booking cancelled")


# ---------------------------------------------------------------------------
# User helpers (BigQuery-backed)
# ---------------------------------------------------------------------------

def _row_to_user(row) -> dict:
    return {k: row[k] for k in row.keys()}


def _get_user(username: str) -> dict | None:
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_USERS} WHERE username = @u LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "STRING", username),
        ]),
    ).result())
    return _row_to_user(rows[0]) if rows else None


def _get_all_users() -> list[dict]:
    rows = list(_bq().query(
        f"SELECT username, name, email, role, photo_url,"
        f" sharpspring_owner_id, sharpspring_name FROM {BQ_USERS} ORDER BY created_at"
    ).result())
    return [_row_to_user(r) for r in rows]


def _check_password(stored_hash: str, provided: str) -> bool:
    parts = stored_hash.split(":", 3)
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False
    _, algo, salt, expected = parts
    actual = hashlib.pbkdf2_hmac(algo, provided.encode(), salt.encode(), 260000)
    return hmac.compare_digest(actual.hex(), expected)


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"pbkdf2:sha256:{salt}:{h.hex()}"


def _bq_params(**kv) -> list:
    type_map = {str: "STRING", int: "INT64", float: "FLOAT64", bool: "BOOL"}
    params = []
    for name, val in kv.items():
        if name.endswith("_ts"):
            params.append(bigquery.ScalarQueryParameter(name, "TIMESTAMP", val))
        else:
            bq_type = type_map.get(type(val), "STRING")
            params.append(bigquery.ScalarQueryParameter(name, bq_type, val))
    return params


# ---------------------------------------------------------------------------
# SharpSpring CRM integration — lead search + appointment write-back
# ---------------------------------------------------------------------------

_SS_BASE_URL = "https://api.sharpspring.com/pubapi/v1.2/"

# .env fallback so SharpSpring creds resolve in local dev too. On Vercel the real
# environment is used (no .env present); locally we read the repo-root .env.
_DOTENV: dict[str, str] = {}
_dotenv_path = Path(__file__).parent.parent / ".env"
if _dotenv_path.exists():
    for _line in _dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _DOTENV[_k.strip()] = _v.strip().strip('"').strip("'")


def _cfg(key: str) -> str:
    return os.environ.get(key) or _DOTENV.get(key, "")


def _now_uk() -> datetime:
    """Current UK wall-clock time, handling BST/GMT — no tz-data dependency.

    UK clocks are UTC+1 from 01:00 UTC on the last Sunday of March until
    01:00 UTC on the last Sunday of October, otherwise UTC+0.
    """
    now = datetime.now(timezone.utc)
    y = now.year
    mar31, oct31 = date(y, 3, 31), date(y, 10, 31)
    last_sun_mar = mar31.day - ((mar31.weekday() + 1) % 7)
    last_sun_oct = oct31.day - ((oct31.weekday() + 1) % 7)
    bst_start = datetime(y, 3, last_sun_mar, 1, tzinfo=timezone.utc)
    bst_end   = datetime(y, 10, last_sun_oct, 1, tzinfo=timezone.utc)
    if bst_start <= now < bst_end:
        now += timedelta(hours=1)
    return now.replace(tzinfo=None)


# SharpSpring appointment field system names (confirmed against real lead data)
_SS_F_STATUS      = "status_633ae6f6ac6fe"                       # Domestic Lead Status
_SS_F_APPT_DT     = "appointment_time___date_5ae8ca2f532bc"      # Appointment Time & Date
_SS_F_APPT_BOOKED = "appointment_booked_5ae8cb01a35c6"           # Appointment Booked (Yes/No)
_SS_F_MADE_BY     = "appointment_made_by_65e1a90253305"          # Appointment Booked By (picklist)
_SS_F_BOOKED_TS   = "date_time_appointment_booked_687fabb701341"  # timestamp the booking was made
_SS_F_STATUS_WATER = "domestic_lead_status__1__6a0f07b50b5d2"    # Domestic Lead Status WATER
_SS_F_ENQUIRY      = "lead_warmth__1__69ea236712886"             # Enquiry Type (Heating/Heating and Water/Water)
_SS_F_APPT_TYPE    = "type_of_appointment_606ee2f254f4d"         # Type of Appointment (Physical / Video Call)
_SS_F_PREV_APPT    = "previous_appointment_time___date_6a1d969b9f800"  # Previous Appointment Time & Date
# NOTE: the Previous field is labelled "AUTO UPDATED" in the CRM but its automation
# does NOT fire on API writes (live-tested) — the tool maintains it explicitly.

# Appointment types the booking form can submit, and allowed other-side outcomes
APPT_TYPES     = ("heating", "water", "both")
OTHER_OUTCOMES = ("", "Follow Up", "Not Interested")
# Agents you can book on behalf of (the telesales team) — must have
# sharpspring_name + owner id set in app.users.
BOOK_FOR_USERNAMES = ("lily", "sue", "alicja", "alisha", "peter")
ENQUIRY_TYPES  = ("", "Heating", "Water", "Heating and Water")  # '' = don't write


def _ss_call(method: str, params: dict) -> dict:
    """JSON-RPC call to SharpSpring. Returns parsed response, or {} on transport error/missing creds."""
    account_id = _cfg("SHARPSPRING_ACCOUNT_ID")
    secret_key = _cfg("SHARPSPRING_SECRET_KEY")
    if not account_id or not secret_key:
        return {}
    try:
        r = requests.post(
            _SS_BASE_URL,
            params={"accountID": account_id, "secretKey": secret_key},
            json={"method": method, "params": params, "id": secrets.token_hex(8)},
            timeout=20,
        )
        return r.json()
    except Exception:
        return {}


def _ss_get_lead(lead_id: str) -> dict | None:
    """Live lookup of one lead by id. Returns the lead dict, or None if not found/deleted.

    Always call this before writing — createNotes/updateLeads will happily 'succeed'
    against a deleted id, so getLeads is the only reliable existence check.
    """
    if not lead_id:
        return None
    resp = _ss_call("getLeads", {"where": {"id": str(lead_id)}, "limit": 1})
    leads = (resp.get("result") or {}).get("lead", []) if resp else []
    return leads[0] if leads else None


# Fresh-leads cache — today's leads via getLeadsDateRange, refreshed lazily (5-min TTL).
# Covers leads created since the last 30-min BigQuery sync so search finds them too.
_ss_fresh_cache: dict = {"ts": 0.0, "leads": []}
_ss_fresh_lock = threading.Lock()
_SS_FRESH_TTL = 300


def _ss_fresh_leads_today() -> list[dict]:
    now = time.time()
    with _ss_fresh_lock:
        if _ss_fresh_cache["leads"] and now - _ss_fresh_cache["ts"] < _SS_FRESH_TTL:
            return _ss_fresh_cache["leads"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    leads: list[dict] = []
    offset = 0
    while True:
        resp = _ss_call("getLeadsDateRange", {
            "startDate": f"{today} 00:00:00", "endDate": f"{today} 23:59:59",
            "timestamp": "create", "limit": 500, "offset": offset,
        })
        batch = (resp.get("result") or {}).get("lead", []) if resp else []
        leads.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    with _ss_fresh_lock:
        _ss_fresh_cache.update(ts=now, leads=leads)
    return leads


def _ss_update_lead(lead_id: str, *, date_iso: str, start_time: str,
                    rep_owner_id: str = "", made_by_name: str = "",
                    street: str = "", postcode: str = "",
                    appt_type: str = "heating", other_outcome: str = "",
                    enquiry_type: str = "", teams_meeting: bool = False,
                    prev_appt: str = "") -> bool:
    """Write the appointment fields to a lead for a genuine new booking. Returns True on success.

    Always used for /api/book — per the 18 Aug ruling, booking a lead (even one that
    already has a live appointment: a previous customer booking again) is a new sales
    cycle and always stamps a fresh booked-at + applies the full status matrix.
    Moving the date of an EXISTING appointment is a separate action — see
    _ss_reschedule_lead / /api/reschedule — which never calls this function.

    rep_owner_id reassigns the lead to the field rep (omitting ownerID makes SharpSpring
    reassign to the API account owner, so we only send it when known). street/postcode
    update the lead's standard address (from the booking's Location + Postcode).

    appt_type drives the heating/water status matrix:
      both    -> main = Appointment, WATER = Appointment
      heating -> main = Appointment, WATER = other_outcome (if chosen)
      water   -> WATER = Appointment, main = other_outcome (if chosen)
    other_outcome is the telesales person's call on the *other* pipeline
    ('' = leave unchanged, 'Follow Up', 'Not Interested').

    enquiry_type is an independent, human-chosen value for the CRM's Enquiry Type
    picklist ('' = leave unchanged) — telesales decide what the enquiry is about,
    e.g. a customer who enquired about heating but books water.
    """
    new_appt = f"{date_iso} {start_time}:00"
    obj = {
        "id": str(lead_id),
        "leadStatus": "qualified",
        _SS_F_APPT_DT: new_appt,
        _SS_F_APPT_BOOKED: "Yes",
        _SS_F_APPT_TYPE: "Video Call" if teams_meeting else "Physical",
        # SharpSpring stores/displays this as UK local time, so write UK wall-clock
        # (auto-handles BST/GMT) — not UTC, which reads an hour behind in summer.
        _SS_F_BOOKED_TS: _now_uk().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Re-booking: stash the old appointment time before overwriting it.
    if prev_appt and prev_appt != new_appt:
        obj[_SS_F_PREV_APPT] = prev_appt
    if appt_type == "both":
        obj[_SS_F_STATUS] = "Appointment"
        obj[_SS_F_STATUS_WATER] = "Appointment"
    elif appt_type == "water":
        obj[_SS_F_STATUS_WATER] = "Appointment"
        if other_outcome:
            obj[_SS_F_STATUS] = other_outcome
    else:  # heating (default)
        obj[_SS_F_STATUS] = "Appointment"
        if other_outcome:
            obj[_SS_F_STATUS_WATER] = other_outcome
    if enquiry_type:
        obj[_SS_F_ENQUIRY] = enquiry_type
    if rep_owner_id:
        obj["ownerID"] = str(rep_owner_id)
    if made_by_name:
        obj[_SS_F_MADE_BY] = made_by_name
    if street:
        obj["street"] = street
    if postcode:
        obj["zipcode"] = postcode
    resp = _ss_call("updateLeads", {"objects": [obj]})
    updates = (resp.get("result") or {}).get("updates", []) if resp else []
    return bool(updates and updates[0].get("success"))


def _ss_reschedule_lead(lead_id: str, *, date_iso: str, start_time: str, prev_appt: str = "") -> bool:
    """Move a lead's appointment time only. Returns True on success.

    Per the 18 Aug ruling a reschedule is an EDIT of an existing appointment, not a
    new booking: only the appointment time field moves (old time preserved in the
    Previous Appointment field). Status, booked flag, type-of-appointment, owner and
    the booked-at timestamp are deliberately left untouched — see _ss_update_lead
    (used only by the genuine-new-booking path) for the fields this does NOT write.
    """
    new_appt = f"{date_iso} {start_time}:00"
    obj = {"id": str(lead_id), _SS_F_APPT_DT: new_appt}
    if prev_appt and prev_appt != new_appt:
        obj[_SS_F_PREV_APPT] = prev_appt
    resp = _ss_call("updateLeads", {"objects": [obj]})
    updates = (resp.get("result") or {}).get("updates", []) if resp else []
    return bool(updates and updates[0].get("success"))


def _ss_create_note(lead_id: str, text: str, owner_id: str = "") -> bool:
    """Create a note in the lead's activity feed. owner_id attributes it to that user."""
    if not text:
        return False
    obj = {"whoID": str(lead_id), "whoType": "lead", "note": text}
    if owner_id:
        obj["authorID"] = str(owner_id)
    resp = _ss_call("createNotes", {"objects": [obj]})
    creates = (resp.get("result") or {}).get("creates", []) if resp else []
    return bool(creates and creates[0].get("success"))


def _digits(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _bq_search_leads(name: str, phone: str, email: str, postcode: str, limit: int = 25) -> list[dict]:
    """Search the synced lead history in BigQuery. Provided fields are AND-combined."""
    conds, params = [], []
    if name:
        # Tokenise: each word must appear somewhere in "first last" — order/whitespace independent.
        for i, tok in enumerate(name.split()):
            conds.append(
                f"LOWER(CONCAT(COALESCE(first_name,''),' ',COALESCE(last_name,''))) LIKE @nm{i}")
            params.append(bigquery.ScalarQueryParameter(f"nm{i}", "STRING", f"%{tok.lower()}%"))
    if email:
        conds.append("LOWER(COALESCE(email_address,'')) LIKE @email")
        params.append(bigquery.ScalarQueryParameter("email", "STRING", f"%{email.lower()}%"))
    if postcode:
        conds.append("REPLACE(LOWER(COALESCE(zipcode,'')),' ','') LIKE @pc")
        params.append(bigquery.ScalarQueryParameter("pc", "STRING", f"%{postcode.lower().replace(' ', '')}%"))
    if phone:
        conds.append("(REGEXP_REPLACE(COALESCE(phone_number,''),r'[^0-9]','') LIKE @ph"
                     " OR REGEXP_REPLACE(COALESCE(mobile_phone_number,''),r'[^0-9]','') LIKE @ph)")
        params.append(bigquery.ScalarQueryParameter("ph", "STRING", f"%{_digits(phone)}%"))
    if not conds:
        return []
    sql = (
        "SELECT id, first_name, last_name, email_address, phone_number,"
        " mobile_phone_number, zipcode, owner_id,"
        " status_633ae6f6ac6fe AS dom_status,"
        " lead_warmth___1___69ea236712886 AS enquiry_type"
        " FROM bronze.sharpspring_leads"
        f" WHERE {' AND '.join(conds)}"
        " ORDER BY update_timestamp DESC"
        f" LIMIT {limit}"
    )
    rows = _bq().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return [dict(r) for r in rows]


def _search_leads(name: str, phone: str, email: str, postcode: str) -> list[dict]:
    """Merge BigQuery history + today's fresh SharpSpring leads, deduped by id (fresh wins)."""
    name_tokens = name.lower().split() if name else []
    em = email.lower() if email else ""
    pc = postcode.lower().replace(" ", "") if postcode else ""
    ph = _digits(phone)

    merged: dict[str, dict] = {}
    try:
        for r in _bq_search_leads(name, phone, email, postcode):
            merged[str(r["id"])] = {
                "id": str(r["id"]),
                "name": f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip(),
                "email": r.get("email_address") or "",
                "phone": r.get("phone_number") or r.get("mobile_phone_number") or "",
                "postcode": r.get("zipcode") or "",
                "status": r.get("dom_status") or "",
                "enquiry_type": r.get("enquiry_type") or "",
                "source": "history",
            }
    except Exception as exc:  # noqa: BLE001 — search must degrade gracefully
        print(f"WARNING: BigQuery lead search failed: {exc}", file=sys.stderr)

    for lead in _ss_fresh_leads_today():
        full = f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".lower()
        if name_tokens and not all(t in full for t in name_tokens):
            continue
        if em and em not in (lead.get("emailAddress") or "").lower():
            continue
        if pc and pc not in (lead.get("zipcode") or "").lower().replace(" ", ""):
            continue
        if ph:
            pd = _digits((lead.get("phoneNumber") or "") + (lead.get("mobilePhoneNumber") or ""))
            if ph not in pd:
                continue
        merged[str(lead.get("id"))] = {
            "id": str(lead.get("id")),
            "name": f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip(),
            "email": lead.get("emailAddress") or "",
            "phone": lead.get("phoneNumber") or lead.get("mobilePhoneNumber") or "",
            "postcode": lead.get("zipcode") or "",
            "status": lead.get("status_633ae6f6ac6fe") or "",
            "enquiry_type": lead.get(_SS_F_ENQUIRY) or "",
            "source": "fresh",
        }

    return list(merged.values())[:25]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Availability cache
# ---------------------------------------------------------------------------

_avail_cache: dict = {}
_avail_lock = threading.Lock()
_diary_cache: dict = {}
_diary_lock = threading.Lock()
_AVAIL_TTL = 300


def _get_grid(region: str | None, days: int, start_date=None) -> dict:
    key = f"{region}:{days}:{start_date or 'today'}"
    with _avail_lock:
        cached = _avail_cache.get(key)
        if cached and time.time() - cached["ts"] < _AVAIL_TTL:
            return cached["data"]
    events = fetch_events(days=days + 2, start_date=start_date)
    grid = build_grid(events, region=region, days=days, start_date=start_date)
    with _avail_lock:
        _avail_cache[key] = {"data": grid, "ts": time.time()}
    return grid


# ---------------------------------------------------------------------------
# Routes — auth
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = _get_user(username)
        if user and _check_password(user["password_hash"], password):
            session.permanent = True
            session["username"]  = username
            session["role"]      = user.get("role") or "user"
            session["name"]      = user.get("name") or username
            session["email"]     = user.get("email") or ""
            session["photo_url"] = user.get("photo_url") or ""
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        error = "Incorrect username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes — main app
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template(
        "availability.html",
        username=session.get("name"),
        login_username=session.get("username", ""),
        role=session.get("role"),
        user_email=session.get("email", ""),
        photo_url=session.get("photo_url", ""),
        regions=all_regions(),
    )


# ---------------------------------------------------------------------------
# Routes — profile
# ---------------------------------------------------------------------------

def _profile_ctx(**extra):
    return dict(
        username=session.get("name"),
        role=session.get("role"),
        user_email=session.get("email", ""),
        photo_url=session.get("photo_url", ""),
        login_username=session.get("username"),
        **extra,
    )


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", **_profile_ctx())


@app.route("/profile/update", methods=["POST"])
@login_required
def profile_update():
    name  = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    if not name:
        return render_template("profile.html", **_profile_ctx(
            profile_error="Name cannot be empty."
        ))
    uname = session["username"]
    now   = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"UPDATE {BQ_USERS} SET name = @name, email = @email, updated_at = @now_ts"
        f" WHERE username = @u",
        job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
            name=name, email=email, now_ts=now, u=uname,
        )),
    ).result()
    session["name"]  = name
    session["email"] = email
    return render_template("profile.html", **_profile_ctx(profile_ok="Profile updated."))


@app.route("/profile/password", methods=["POST"])
@login_required
def profile_password():
    current = request.form.get("current_password") or ""
    new_pw  = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    uname   = session["username"]
    user    = _get_user(uname)

    if not user or not _check_password(user["password_hash"], current):
        return render_template("profile.html", **_profile_ctx(
            pw_error="Current password is incorrect."
        ))
    if len(new_pw) < 8:
        return render_template("profile.html", **_profile_ctx(
            pw_error="New password must be at least 8 characters."
        ))
    if new_pw != confirm:
        return render_template("profile.html", **_profile_ctx(
            pw_error="Passwords do not match."
        ))

    now = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"UPDATE {BQ_USERS} SET password_hash = @h, updated_at = @now_ts WHERE username = @u",
        job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
            h=_hash_password(new_pw), now_ts=now, u=uname,
        )),
    ).result()
    return render_template("profile.html", **_profile_ctx(pw_ok="Password updated."))


@app.route("/profile/photo", methods=["POST"])
@login_required
def profile_photo():
    f = request.files.get("photo")
    if not f or not f.filename:
        return redirect(url_for("profile"))

    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    content_type = f.content_type or ""
    if content_type not in allowed:
        return render_template("profile.html", **_profile_ctx(
            photo_error="Only JPEG, PNG, GIF, or WebP images are accepted."
        ))

    ext_map = {"image/jpeg": "jpg", "image/png": "png",
               "image/gif": "gif", "image/webp": "webp"}
    ext   = ext_map[content_type]
    uname = session["username"]
    blob  = _gcs().bucket(GCS_BUCKET).blob(f"avatars/{uname}.{ext}")
    blob.upload_from_file(f.stream, content_type=content_type)
    blob.make_public()
    photo_url = blob.public_url

    now = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"UPDATE {BQ_USERS} SET photo_url = @p, updated_at = @now_ts WHERE username = @u",
        job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
            p=photo_url, now_ts=now, u=uname,
        )),
    ).result()
    session["photo_url"] = photo_url
    return redirect(url_for("profile"))


# ---------------------------------------------------------------------------
# Routes — API (all login-required)
# ---------------------------------------------------------------------------

@app.route("/api/regions")
@login_required
def api_regions():
    return jsonify({"regions": all_regions()})


@app.route("/api/availability")
@login_required
def api_availability():
    region = request.args.get("region") or None
    days = min(int(request.args.get("days", 10)), 40)
    location = request.args.get("location") or None
    start_date_str = request.args.get("start_date") or None

    if location and not region:
        region = region_from_postcode(location) or region_from_city(location)

    start_date = None
    if start_date_str:
        try:
            start_date = date.fromisoformat(start_date_str)
        except ValueError:
            pass

    try:
        grid = _get_grid(region, days, start_date=start_date)
        return jsonify(grid)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/resolve-location")
@login_required
def api_resolve_location():
    location = (request.args.get("q") or "").strip()
    if not location:
        return jsonify({"region": None})
    region = region_from_postcode(location) or region_from_city(location)
    reps = reps_for_region(region) if region else []
    return jsonify({"region": region, "reps": reps})


@app.route("/api/availability/refresh")
@login_required
def api_refresh():
    with _avail_lock:
        _avail_cache.clear()
    return jsonify({"ok": True})


@app.route("/api/search_leads", methods=["POST"])
@login_required
def api_search_leads():
    """Find a SharpSpring lead by name/phone/email/postcode (BigQuery + today's fresh leads)."""
    data = request.get_json(silent=True) or {}
    name     = (data.get("name") or "").strip()
    phone    = (data.get("phone") or "").strip()
    email    = (data.get("email") or "").strip()
    postcode = (data.get("postcode") or "").strip()
    if not any([name, phone, email, postcode]):
        return jsonify({"leads": []})
    return jsonify({"leads": _search_leads(name, phone, email, postcode)})


@app.route("/api/lead_enquiry")
@login_required
def api_lead_enquiry():
    """Live Enquiry Type for a lead, straight from SharpSpring.

    The search results carry enquiry_type from BigQuery (up to ~30 min stale);
    this endpoint gives the booking form the current value at selection time —
    telesales often set the enquiry type during the call and book immediately.
    """
    lead_id = (request.args.get("id") or "").strip()
    lead = _ss_get_lead(lead_id) if lead_id else None
    return jsonify({"enquiry_type": (lead or {}).get(_SS_F_ENQUIRY) or ""})


@app.route("/api/bookings/recent")
@login_required
def api_bookings_recent():
    """Tool-adoption stats: today's via-app booking count + the last 7 days' bookings.

    Reads app.bookings (written on every successful booking). Test-lead bookings are
    excluded so demos don't inflate the adoption number.
    """
    rows = list(_bq().query(f"""
        SELECT booker_name, customer, postcode, rep_name, appt_type, status,
               appt_date, appt_start,
               FORMAT_TIMESTAMP('%Y-%m-%d', booked_at, 'Europe/London') AS booked_day,
               FORMAT_TIMESTAMP('%H:%M', booked_at, 'Europe/London') AS booked_time
        FROM {BQ_BOOKINGS}
        WHERE booked_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
          AND customer NOT LIKE 'Zzz Testlead%'
        ORDER BY booked_at DESC
        LIMIT 40
    """).result())
    bookings = [dict(r) for r in rows]
    today = _now_uk().strftime("%Y-%m-%d")
    return jsonify({
        "today": sum(1 for b in bookings if b["booked_day"] == today),
        "bookings": bookings,
    })


@app.route("/api/book", methods=["POST"])
@login_required
def api_book():
    data = request.get_json(silent=True) or {}
    rep_name   = (data.get("rep") or "").strip()
    date_iso   = (data.get("date") or "").strip()
    start_time = (data.get("start") or "").strip()
    end_time   = (data.get("end") or "").strip()
    customer   = (data.get("customer_name") or "").strip()
    postcode   = (data.get("postcode") or "").strip().upper()
    cust_email = (data.get("customer_email") or "").strip()
    cc_emails  = [e.strip() for e in (data.get("cc_emails") or []) if str(e).strip()]
    notes      = (data.get("notes") or "").strip()
    teams      = bool(data.get("teams_meeting", False))
    lead_id    = (data.get("lead_id") or "").strip()
    skip_crm   = bool(data.get("skip_crm", False))
    location   = (data.get("location") or "").strip()
    appt_type  = (data.get("appt_type") or "heating").strip().lower()
    other_outcome = (data.get("other_outcome") or "").strip()
    enquiry_type  = (data.get("enquiry_type") or "").strip()
    if appt_type not in APPT_TYPES:
        appt_type = "heating"
    if other_outcome not in OTHER_OUTCOMES:
        other_outcome = ""
    if enquiry_type not in ENQUIRY_TYPES:
        enquiry_type = ""
    if appt_type == "both":
        other_outcome = ""  # no "other side" when both are booked

    if not all([rep_name, date_iso, start_time, end_time, customer, postcode]):
        return jsonify({"ok": False, "message": "Missing required fields"}), 400

    rep_email = REP_EMAIL.get(rep_name)
    if not rep_email:
        return jsonify({"ok": False, "message": f"No email found for rep: {rep_name}"}), 400

    # ── Slot lock: prevent two agents booking the same slot simultaneously ──
    lock_key = _lock_key(rep_email, date_iso, start_time)
    lock_val = secrets.token_hex(8)
    if not _redis_acquire(lock_key, lock_val):
        return jsonify({"ok": False, "message": "This slot is being booked right now by someone else. Please pick another time."}), 409

    # ── Re-verify via Graph that the slot is still free ──
    if not _slot_is_free(rep_email, date_iso, start_time, end_time):
        _redis_release(lock_key, lock_val)
        return jsonify({"ok": False, "message": "This slot was just booked. Please pick another time."}), 409

    subject  = f"{postcode} - {customer}"
    rep_category = _rep_outlook_category(rep_name)  # exact Outlook category so the colour shows

    booker_email = session.get("email", "").strip()
    booker_name  = session.get("name", "Telesales")

    # Booking user's SharpSpring identity — for note attribution + "Appointment Booked By"
    _actual = _get_user(session.get("username", "")) or {}
    actual_owner_id = _actual.get("sharpspring_owner_id") or ""
    booker_owner_id = actual_owner_id
    booker_made_by  = _actual.get("sharpspring_name") or ""

    # ── Book on behalf of an absent colleague (telesales only): attribution
    #    (CRM Made By, lead owner on cancel, board credit) goes to them;
    #    entered_by keeps the honest record of who physically booked it. ──
    entered_by_name = booker_name
    booker_username = session.get("username", "")
    booked_for = (data.get("booked_for") or "").strip().lower()
    if booked_for and booked_for != booker_username and booked_for in BOOK_FOR_USERNAMES:
        behalf = _get_user(booked_for)
        if behalf and (behalf.get("sharpspring_name") or "").strip():
            booker_username = booked_for
            booker_name     = behalf.get("name") or booked_for.title()
            booker_owner_id = behalf.get("sharpspring_owner_id") or ""
            booker_made_by  = behalf.get("sharpspring_name") or ""
        else:
            booked_for = ""
    else:
        booked_for = ""

    _TELESALES = "telesales@trustelectricheating.co.uk"

    # The booking agent is deliberately NOT an attendee — agents don't want
    # invites to appointments they merely booked. Who-booked-it is preserved in
    # app.bookings, the CRM note/picklist, and the "Booked by" line in the body.
    attendees = []
    # telesales inbox always receives every booking
    attendees.append({
        "emailAddress": {"address": _TELESALES, "name": "Telesales"},
        "type": "required",
    })
    attendees.append({
        "emailAddress": {"address": rep_email, "name": rep_name},
        "type": "required",
    })
    for cc in cc_emails:
        attendees.append({
            "emailAddress": {"address": cc, "name": cc},
            "type": "optional",
        })
    # The customer is deliberately NOT an attendee — attendees receive calendar
    # invites, and customers must never get one. Their email goes in the body
    # instead so the rep can still see it.

    would_create = {
        "subject": subject,
        "categories": [rep_category] if rep_category else [],
        "location": {"displayName": location} if location else {"displayName": ""},
        "start": {"dateTime": f"{date_iso}T{start_time}:00", "timeZone": "Europe/London"},
        "end":   {"dateTime": f"{date_iso}T{end_time}:00",   "timeZone": "Europe/London"},
        "attendees": attendees,
        "body": {"contentType": "Text",
                 "content": notes
                 + (f"\n\nCustomer email: {cust_email}" if cust_email else "")
                 + f"\n\nBooked by: {booker_name}"
                 + (f" (entered by {entered_by_name})" if booked_for else "")},
        "showAs": "busy",
        "isOnlineMeeting": teams,
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 60,
    }
    if teams:
        would_create["onlineMeetingProvider"] = "teamsForBusiness"

    try:
        token = get_graph_token()
        graph_resp = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{CALENDAR_MAILBOX}/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": 'outlook.timezone="Europe/London"',
            },
            json=would_create,
            timeout=30,
        )
        if not graph_resp.ok:
            err = graph_resp.json().get("error", {})
            err_msg = err.get("message") or graph_resp.text[:300]
            app.logger.error("Graph booking error %s: %s", graph_resp.status_code, err_msg)
            return jsonify({"ok": False, "message": f"Calendar error ({graph_resp.status_code}): {err_msg}"}), 500

        event_id = (graph_resp.json() or {}).get("id", "")

        with _avail_lock:
            _avail_cache.clear()
        with _diary_lock:
            _diary_cache.clear()

        # ── CRM write-back — runs only after the calendar booking succeeds, and
        #    never blocks it. Locked ordering: verify lead → update → note. ──
        # Per the 18 Aug ruling: /api/book is ALWAYS a genuine new booking —
        # even for a lead that already has a live appointment (a previous
        # customer booking again is a new sales cycle: new event, full status
        # matrix, full booking credit). Moving the date of an EXISTING
        # appointment is no longer done through this endpoint — that's
        # /api/reschedule, an in-place edit that never lands here.
        crm_status = "skipped"
        if lead_id and not skip_crm:
            try:
                lead = _ss_get_lead(lead_id)
                if lead is None:
                    crm_status = "not_found"
                else:
                    # Reassign to the field rep if we know their owner id; otherwise
                    # preserve the lead's current owner (never let it default to the API account).
                    owner_id = _rep_owner_id(rep_name) or (lead.get("ownerID") or "")
                    updated = _ss_update_lead(
                        lead_id, date_iso=date_iso, start_time=start_time,
                        rep_owner_id=owner_id, made_by_name=booker_made_by,
                        street=location, postcode=postcode,
                        appt_type=appt_type, other_outcome=other_outcome,
                        enquiry_type=enquiry_type, teams_meeting=teams,
                        prev_appt=(lead.get(_SS_F_APPT_DT) or ""),
                    )
                    if notes or booked_for:
                        # note stays authored by whoever actually typed it
                        note_text = notes + (
                            f"\n\nBooked on behalf of {booker_name} — entered by {entered_by_name}"
                            if booked_for else ""
                        )
                        _ss_create_note(lead_id, note_text.strip(), owner_id=actual_owner_id)
                    crm_status = "updated" if updated else "failed"
            except Exception:
                app.logger.exception("CRM write-back failed (booking still succeeded)")
                crm_status = "failed"

        # ── Record the booking so it can be cancelled later from the diary. ──
        # Store lead_id only when the CRM was actually updated, so cancel reverts
        # CRM only for bookings that changed it; others cancel calendar-only.
        # is_rebook is always False here now — reschedules (which used to set it)
        # go through /api/reschedule instead, which updates this row in place
        # rather than inserting a new one. Column kept for historical rows and
        # because the wallboard/dashboard queries still COALESCE on it.
        _record_booking(
            event_id=event_id,
            lead_id=(lead_id if crm_status == "updated" else ""),
            booker_username=booker_username,
            booker_owner_id=booker_owner_id,
            booker_name=booker_name,
            entered_by=(session.get("username", "") if booked_for else ""),
            rep_name=rep_name,
            rep_owner_id=_rep_owner_id(rep_name),
            customer=customer,
            postcode=postcode,
            appt_date=date_iso,
            appt_start=start_time,
            appt_end=end_time,
            appt_type=appt_type,
            is_rebook=False,
        )

        booked_by = f" — booked by {booker_name}" if booker_email else ""
        if booked_for:
            booked_by = f" — booked by {booker_name} (entered by {entered_by_name})"
        crm_tail = {
            "updated":     " · CRM updated",
            "failed":      " · CRM update failed — update SharpSpring manually",
            "not_found":   " · lead not found in CRM — update SharpSpring manually",
            "skipped":     " · CRM NOT updated — no lead was linked",
        }[crm_status]
        message = (
            f"Booked: {rep_name} · {date_iso} · {start_time}–{end_time} "
            f"· {customer} ({postcode}){booked_by}{crm_tail}"
        )
        return jsonify({"ok": True, "dry_run": False, "message": message,
                        "crm_status": crm_status})

    except Exception as ex:
        app.logger.exception("Booking request failed")
        return jsonify({"ok": False, "message": f"Booking failed: {ex}"}), 500

    finally:
        _redis_release(lock_key, lock_val)


@app.route("/api/cancel", methods=["POST"])
@login_required
def api_cancel():
    """Cancel a tool-booked appointment: delete the calendar event + revert the CRM."""
    data = request.get_json(silent=True) or {}
    event_id = (data.get("event_id") or "").strip()
    if not event_id:
        return jsonify({"ok": False, "message": "Missing event_id"}), 400

    booking = _get_active_booking(event_id)
    if not booking:
        return jsonify({"ok": False, "message": "This appointment can't be cancelled here "
                        "(it wasn't booked through this tool)."}), 404

    if _booking_started(booking):
        return jsonify({"ok": False, "message": "This appointment has already started "
                        "and can't be cancelled here."}), 409

    # 1. Remove the calendar event (the appointment itself). Critical — abort if it fails,
    #    so we never revert the CRM while the event still stands.
    if not _ss_delete_event(event_id):
        return jsonify({"ok": False, "message": "Couldn't remove the calendar event — please try again."}), 502

    # 2. Revert the CRM (best-effort — the appointment is already gone from the calendar).
    crm_status = "skipped"
    lead_id = booking.get("lead_id") or ""
    if lead_id:
        try:
            lead = _ss_get_lead(lead_id)
            if lead is None:
                crm_status = "not_found"
            else:
                ok = _ss_cancel_lead(lead, booking.get("booker_owner_id") or "",
                                     appt_type=(booking.get("appt_type") or "heating"))
                canceller = _get_user(session.get("username", "")) or {}
                _ss_create_note(
                    lead_id,
                    f"Appointment cancelled by {session.get('name', 'Telesales')} "
                    f"on {_now_uk().strftime('%d %b %Y')}.",
                    owner_id=(canceller.get("sharpspring_owner_id") or ""),
                )
                crm_status = "reverted" if ok else "failed"
        except Exception:
            app.logger.exception("CRM cancel failed (calendar event already removed)")
            crm_status = "failed"

    # 3. Mark the booking cancelled + refresh caches.
    _mark_booking_cancelled(event_id, session.get("username", ""))
    with _avail_lock:
        _avail_cache.clear()
    with _diary_lock:
        _diary_cache.clear()

    tail = {
        "reverted":  " CRM reverted.",
        "failed":    " CRM revert failed — update SharpSpring manually.",
        "not_found": " (lead no longer in CRM).",
        "skipped":   "",
    }[crm_status]
    return jsonify({"ok": True, "crm_status": crm_status,
                    "message": f"Appointment cancelled.{tail}"})


@app.route("/api/reschedule", methods=["POST"])
@login_required
def api_reschedule():
    """Move a tool-booked appointment to a new date/time — an in-place EDIT.

    Per the 18 Aug ruling this is NOT a new booking: same event_id (Graph PATCH,
    not delete+create), same app.bookings row (UPDATE, no insert), CRM appointment
    time field only (old time preserved in Previous Appointment) — no status change,
    no re-stamped booked-at, no booking-count credit. Attendees/body/category are
    untouched because only start/end are sent in the PATCH.
    """
    data = request.get_json(silent=True) or {}
    event_id  = (data.get("event_id") or "").strip()
    new_date  = (data.get("date") or "").strip()
    new_start = (data.get("start") or "").strip()
    new_end   = (data.get("end") or "").strip()
    if not all([event_id, new_date, new_start, new_end]):
        return jsonify({"ok": False, "message": "Missing required fields"}), 400

    booking = _get_active_booking(event_id)
    if not booking:
        return jsonify({"ok": False, "message": "This appointment can't be rescheduled here "
                        "(it wasn't booked through this tool)."}), 404

    if _booking_started(booking):
        return jsonify({"ok": False, "message": "This appointment has already started "
                        "and can't be rescheduled here."}), 409

    rep_name = booking.get("rep_name") or ""
    rep_email = REP_EMAIL.get(rep_name)
    if not rep_email:
        return jsonify({"ok": False, "message": f"No email found for rep: {rep_name}"}), 400

    old_date  = booking.get("appt_date") or ""
    old_start = booking.get("appt_start") or ""
    old_end   = booking.get("appt_end") or ""
    if (new_date, new_start, new_end) == (old_date, old_start, old_end):
        return jsonify({"ok": False, "message": "That's already the current time."}), 400

    # ── Slot lock + re-verify via Graph — a reschedule must respect availability
    #    exactly like a new booking would. ──
    lock_key = _lock_key(rep_email, new_date, new_start)
    lock_val = secrets.token_hex(8)
    if not _redis_acquire(lock_key, lock_val):
        return jsonify({"ok": False, "message": "This slot is being booked right now by someone else. Please pick another time."}), 409
    if not _slot_is_free(rep_email, new_date, new_start, new_end):
        _redis_release(lock_key, lock_val)
        return jsonify({"ok": False, "message": "This slot was just booked. Please pick another time."}), 409

    try:
        # 1. Move the calendar event in place — PATCH start/end only, same event_id.
        token = get_graph_token()
        patch_resp = requests.patch(
            f"https://graph.microsoft.com/v1.0/users/{CALENDAR_MAILBOX}/events/{event_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": 'outlook.timezone="Europe/London"',
            },
            json={
                "start": {"dateTime": f"{new_date}T{new_start}:00", "timeZone": "Europe/London"},
                "end":   {"dateTime": f"{new_date}T{new_end}:00",   "timeZone": "Europe/London"},
            },
            timeout=30,
        )
        if not patch_resp.ok:
            err = patch_resp.json().get("error", {})
            err_msg = err.get("message") or patch_resp.text[:300]
            app.logger.error("Graph reschedule error %s: %s", patch_resp.status_code, err_msg)
            return jsonify({"ok": False, "message": f"Calendar error ({patch_resp.status_code}): {err_msg}"}), 500

        # 2. CRM — appointment time only, best-effort, never blocks the move
        #    (event already moved). Verify the lead still exists first — see
        #    _ss_get_lead docstring: updateLeads/createNotes 'succeed' on deleted ids.
        crm_status = "skipped"
        lead_id = booking.get("lead_id") or ""
        old_when = f"{old_date} {old_start}" if old_date and old_start else "an earlier time"
        new_when = f"{new_date} {new_start}"
        rescheduler_name = session.get("name", "Telesales")
        if lead_id:
            try:
                lead = _ss_get_lead(lead_id)
                if lead is None:
                    crm_status = "not_found"
                else:
                    ok = _ss_reschedule_lead(
                        lead_id, date_iso=new_date, start_time=new_start,
                        prev_appt=(lead.get(_SS_F_APPT_DT) or ""),
                    )
                    if ok:
                        actor = _get_user(session.get("username", "")) or {}
                        _ss_create_note(
                            lead_id,
                            f"Rescheduled by {rescheduler_name} from {old_when} to {new_when}.",
                            owner_id=(actor.get("sharpspring_owner_id") or ""),
                        )
                    crm_status = "updated" if ok else "failed"
            except Exception:
                app.logger.exception("CRM reschedule failed (calendar event already moved)")
                crm_status = "failed"

        # 3. app.bookings — UPDATE the existing row in place. No new row, no
        #    status/is_rebook/booked_at change — just the new time + an audit trail.
        try:
            _bq().query(
                f"UPDATE {BQ_BOOKINGS} SET appt_date = @d, appt_start = @s, appt_end = @e,"
                f" rescheduled_at = @rts, rescheduled_by = @u"
                f" WHERE event_id = @ev AND status = 'active'",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("d", "STRING", new_date),
                    bigquery.ScalarQueryParameter("s", "STRING", new_start),
                    bigquery.ScalarQueryParameter("e", "STRING", new_end),
                    bigquery.ScalarQueryParameter("rts", "TIMESTAMP", datetime.now(timezone.utc).isoformat()),
                    bigquery.ScalarQueryParameter("u", "STRING", session.get("username", "")),
                    bigquery.ScalarQueryParameter("ev", "STRING", event_id),
                ]),
            ).result()
        except Exception:
            app.logger.exception("Failed to update booking row after reschedule (calendar + CRM already moved)")

        with _avail_lock:
            _avail_cache.clear()
        with _diary_lock:
            _diary_cache.clear()

        tail = {
            "updated":   " · CRM updated",
            "failed":    " · CRM update failed — update SharpSpring manually",
            "not_found": " · lead not found in CRM — update SharpSpring manually",
            "skipped":   "",
        }[crm_status]
        message = f"Rescheduled to {new_date} · {new_start}–{new_end}{tail}"
        return jsonify({"ok": True, "message": message, "crm_status": crm_status})

    except Exception as ex:
        app.logger.exception("Reschedule request failed")
        return jsonify({"ok": False, "message": f"Reschedule failed: {ex}"}), 500

    finally:
        _redis_release(lock_key, lock_val)


# ---------------------------------------------------------------------------
# Routes — rep diary
# ---------------------------------------------------------------------------

@app.route("/reps")
@login_required
def rep_diary():
    return render_template(
        "reps.html",
        username=session.get("name"),
        role=session.get("role"),
        user_email=session.get("email", ""),
        photo_url=session.get("photo_url", ""),
    )


@app.route("/api/reps/diary")
@login_required
def api_rep_diary():
    days_back = min(int(request.args.get("days_back", 7)), 90)
    days_forward = 60
    key = f"diary:{days_back}"
    with _diary_lock:
        cached = _diary_cache.get(key)
        if cached and time.time() - cached["ts"] < _AVAIL_TTL:
            return jsonify(cached["data"])
    try:
        start = date.today() - timedelta(days=days_back)
        events = fetch_events(days=days_back + days_forward, start_date=start)
        data = build_rep_diary(events)
        _annotate_cancellable(data)
        with _diary_lock:
            _diary_cache[key] = {"data": data, "ts": time.time()}
        return jsonify(data)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reps/diary/refresh")
@login_required
def api_diary_refresh():
    with _diary_lock:
        _diary_cache.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin routes — users
# ---------------------------------------------------------------------------

@app.route("/admin/users")
@admin_required
def admin_users():
    users = _get_all_users()
    return render_template("admin_users.html", users=users, made_by_options=MADE_BY_OPTIONS)


@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    role     = request.form.get("role", "user")
    name     = (request.form.get("name") or username).strip()
    email    = (request.form.get("email") or "").strip().lower()

    if not username or not password:
        abort(400)

    if _get_user(username):
        return redirect(url_for("admin_users"))

    now = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"INSERT INTO {BQ_USERS}"
        f" (username, password_hash, name, email, role, photo_url, created_at, updated_at)"
        f" VALUES (@username, @ph, @name, @email, @role, NULL, @now_ts, @now_ts)",
        job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
            username=username, ph=_hash_password(password),
            name=name, email=email, role=role, now_ts=now,
        )),
    ).result()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/sharpspring", methods=["POST"])
@admin_required
def admin_set_user_sharpspring():
    """Set a user's SharpSpring owner ID (note attribution) and Booked-By picklist name."""
    username = (request.form.get("username") or "").strip().lower()
    owner_id = (request.form.get("sharpspring_owner_id") or "").strip()
    ss_name  = (request.form.get("sharpspring_name") or "").strip()
    if not username:
        abort(400)
    if ss_name and ss_name not in MADE_BY_OPTIONS:
        ss_name = ""  # never store a value that isn't a valid picklist option
    now = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"UPDATE {BQ_USERS} SET sharpspring_owner_id = @oid, sharpspring_name = @nm,"
        f" updated_at = @now_ts WHERE username = @u",
        job_config=bigquery.QueryJobConfig(query_parameters=_bq_params(
            oid=owner_id, nm=ss_name, u=username, now_ts=now,
        )),
    ).result()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete/<username>", methods=["POST"])
@admin_required
def admin_delete_user(username: str):
    if username == session.get("username"):
        abort(400)
    _bq().query(
        f"DELETE FROM {BQ_USERS} WHERE username = @u",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("u", "STRING", username),
        ]),
    ).result()
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Admin routes — reps
# ---------------------------------------------------------------------------

@app.route("/admin/reps")
@admin_required
def admin_reps():
    return render_template("admin_reps.html", reps=_get_all_reps(), all_regions=_KNOWN_REGIONS)


@app.route("/admin/reps/add", methods=["POST"])
@admin_required
def admin_add_rep():
    name         = (request.form.get("name") or "").strip()
    email        = (request.form.get("email") or "").strip().lower()
    regions      = request.form.getlist("regions")
    fallback     = bool(request.form.get("fallback"))
    freelancer   = bool(request.form.get("freelancer"))
    weekend_days = [int(d) for d in request.form.getlist("weekend_days")]
    aliases_raw  = (request.form.get("aliases") or "").strip()
    aliases      = [a.strip().lower() for a in aliases_raw.split(",") if a.strip()]

    if not name or not email:
        abort(400)

    existing = list(_bq().query(
        f"SELECT name FROM {BQ_REPS} WHERE name = @n LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("n", "STRING", name),
        ]),
    ).result())
    if existing:
        return redirect(url_for("admin_reps"))

    now = datetime.now(timezone.utc).isoformat()
    _bq().query(
        f"INSERT INTO {BQ_REPS}"
        f" (name, email, regions, fallback, freelancer, weekend_days, aliases, created_at)"
        f" VALUES (@name, @email, @regions, @fallback, @freelancer, @weekend_days, @aliases, @now_ts)",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("name",         "STRING",    name),
            bigquery.ScalarQueryParameter("email",        "STRING",    email),
            bigquery.ScalarQueryParameter("regions",      "STRING",    json.dumps(regions)),
            bigquery.ScalarQueryParameter("fallback",     "BOOL",      fallback),
            bigquery.ScalarQueryParameter("freelancer",   "BOOL",      freelancer),
            bigquery.ScalarQueryParameter("weekend_days", "STRING",    json.dumps(weekend_days)),
            bigquery.ScalarQueryParameter("aliases",      "STRING",    json.dumps(aliases)),
            bigquery.ScalarQueryParameter("now_ts",       "TIMESTAMP", now),
        ]),
    ).result()
    reload_reps()
    return redirect(url_for("admin_reps"))


@app.route("/admin/reps/owner", methods=["POST"])
@admin_required
def admin_set_rep_owner():
    """Set a rep's SharpSpring owner ID (used to reassign the lead on booking)."""
    name     = (request.form.get("name") or "").strip()
    owner_id = (request.form.get("sharpspring_owner_id") or "").strip()
    if not name:
        abort(400)
    _bq().query(
        f"UPDATE {BQ_REPS} SET sharpspring_owner_id = @oid WHERE name = @n",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("oid", "STRING", owner_id or None),
            bigquery.ScalarQueryParameter("n",   "STRING", name),
        ]),
    ).result()
    reload_reps()
    return redirect(url_for("admin_reps"))


@app.route("/admin/reps/delete/<path:name>", methods=["POST"])
@admin_required
def admin_delete_rep(name: str):
    _bq().query(
        f"DELETE FROM {BQ_REPS} WHERE name = @n",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("n", "STRING", name),
        ]),
    ).result()
    reload_reps()
    return redirect(url_for("admin_reps"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(_hash_password(sys.argv[2]))
    else:
        app.run(debug=True, port=5050)
