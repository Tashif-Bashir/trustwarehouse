"""Calendar watcher — reconcile manual Outlook bookings into app.bookings + the CRM.

Telesales sometimes book appointments straight in the shared Outlook calendar
instead of the booking app. Those appointments are invisible to app.bookings
(so the wallboard undercounts) and never reach the CRM's appointment fields.
This watcher (VM systemd timer, every 5 min) closes the gap:

1. NEW manual events (rep-category event not in app.bookings) get a bookings
   row immediately, then a confident-match ladder tries to find the CRM lead:
     - a UK phone number in the event text -> exact phone match (certain)
     - otherwise a name in the subject matching exactly ONE lead created in
       the last 60 days -> auto-link
     - otherwise a (name + postcode) match with NO age limit -> auto-link
       (old-lead linking; name-only stays 60-day-guarded, postcode corroborates)
     - anything ambiguous -> link_status='needs_link' for the /links page
   On a confident match the CRM is written exactly like an app booking
   (status matrix, appointment fields, owner -> rep, audit note) — UNLESS the
   lead already has a DIFFERENT future appointment (the two-visits case):
   then the CRM is left alone and the row is flagged link_status='conflict'.
   Booker attribution: the lead's PRE-BOOKING ownerID is checked against the
   three-person ruling (resolve_booker) — a valid owner stamps booker_name/
   booker_owner_id AND the CRM "Appointment Booked By" picklist; an invalid
   one (Peter Heaton, Alisha Moore, blank, unknown) leaves booker_name
   'Manual (calendar)' and flags link_status='needs_owner' for the /links
   page's one-click claim buttons.
2. EDITS: an event whose date/time no longer matches its bookings row is
   healed (row updated; CRM appointment time moved if the CRM holds it).
3. DELETIONS: an active future booking whose event has vanished from the
   calendar is marked cancelled (cancelled_by='watcher'). The CRM is never
   auto-cancelled — that stays a human decision.
4. Rows still 'needs_link' with a future appointment are re-tried each run
   (the matching lead may only just have enquired). `--sweep` additionally
   re-tries ALL historical unlinked rows once (past appointments get the
   lead linked for counting, but no CRM write — the visit already happened).
5. SELF-HEAL: watcher rows booked in the last 7 days get their linked lead's
   LIVE CRM "Appointment Booked By" stamp re-checked each run — a human
   correction (or a claim made straight in the CRM) always overrides the
   owner-derived guess, and clears needs_owner -> 'auto'. Never touches rows
   entered_by != 'watcher'.

Owner-agreed behaviour (25 Aug 2026): overwrite past appointments, flag
conflicting future ones; auto-link on unique recent name match; unmatched
rows surface on the booking app's /links page for any telesales user.
Booker attribution + needs_owner + old-lead (name+postcode) linking added
3 Sep 2026 per the owner's approved design.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "availability_app"))

try:  # systemd supplies env via EnvironmentFile; local runs read .env directly
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

import availability_engine as engine  # noqa: E402  (needs sys.path above)
from ingestion.sharpspring.client import SharpSpringClient  # noqa: E402

UK = ZoneInfo("Europe/London")
PROJECT = "trustwarehouse"
BOOKINGS = f"`{PROJECT}.app.bookings`"
WINDOW_DAYS = 60

# SharpSpring custom fields — same constants as availability_app/app.py
SS_F_STATUS = "status_633ae6f6ac6fe"
SS_F_APPT_DT = "appointment_time___date_5ae8ca2f532bc"
SS_F_APPT_BOOKED = "appointment_booked_5ae8cb01a35c6"
SS_F_BOOKED_TS = "date_time_appointment_booked_687fabb701341"
SS_F_APPT_TYPE = "type_of_appointment_606ee2f254f4d"
SS_F_PREV_APPT = "previous_appointment_time___date_6a1d969b9f800"
SS_F_MADE_BY = "appointment_made_by_65e1a90253305"  # "Appointment Booked By" picklist

PHONE_RE = re.compile(r"(?:\+?44[\s\-]?|0)(?:\d[\s\-]?){9,10}")
POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)
PARENS_RE = re.compile(r"\([^)]*\)")

# Owner ruling (3 Sep 2026): a lead's PRE-BOOKING ownerID maps to a booker only
# for these three telesales people — Peter Heaton moved to sales, Alisha Moore
# is out; neither is valid, and any other/blank/unknown owner is not valid
# either. Values: (booker_name for app.bookings, CRM "Appointment Booked By"
# picklist value — note 'Susan England' differs from the app.bookings name).
VALID_BOOKER_OWNERS: dict[str, tuple[str, str]] = {
    "349724672": ("Sue England", "Susan England"),
    "351874048": ("Lily Harpham", "Lily Harpham"),
    "368143360": ("Alicja Aleksiuk", "Alicja Aleksiuk"),
    # Telesales starters Mon 7 Sep 2026 (owner, 3 Sep).
    "377646080": ("Amanda Romans", "Amanda Romans"),
    "377645056": ("Jess Wadkin", "Jess Wadkin"),
}
# Reverse lookup for the self-heal pass: CRM made-by picklist value -> the
# app.bookings booker identity it implies.
MADE_BY_TO_BOOKER: dict[str, tuple[str, str]] = {
    made_by: (booker_name, owner_id)
    for owner_id, (booker_name, made_by) in VALID_BOOKER_OWNERS.items()
}


def _strip_parens(s: str) -> str:
    """Drop parenthetical asides ('(ring first)') before name/customer extraction.

    Deliberately NOT applied to event_text()'s output — a phone number or
    postcode occasionally sits inside the parenthetical ("(ring 07911 222333
    first)") and anchor detection must still see it.
    """
    return re.sub(r"\s+", " ", PARENS_RE.sub(" ", s or "")).strip()


def resolve_booker(owner_id: str | None) -> tuple[str, str, str] | None:
    """Map a lead's PRE-BOOKING ownerID to (booker_name, booker_owner_id, crm_made_by).

    None for anything not in VALID_BOOKER_OWNERS — Peter Heaton, Alisha Moore,
    blank, or an unrecognised id all count as "not valid" per the owner ruling.
    """
    entry = VALID_BOOKER_OWNERS.get(str(owner_id or "").strip())
    if not entry:
        return None
    booker_name, made_by = entry
    return booker_name, str(owner_id).strip(), made_by


def self_heal_decision(row_booker_name: str, crm_made_by: str) -> tuple[str, str] | None:
    """Given a bookings row's current booker_name and the lead's LIVE CRM made-by
    stamp, return (new_booker_name, new_booker_owner_id) if the row should be
    healed to match, else None.

    The CRM stamp (a human's action, possibly made after the watcher's owner
    guess) always wins over the owner-derived guess. No-op if the CRM value
    isn't one of the three valid names, or already matches the row.
    """
    mapped = MADE_BY_TO_BOOKER.get(crm_made_by or "")
    if not mapped:
        return None
    new_name, new_owner_id = mapped
    if row_booker_name == new_name:
        return None
    return new_name, new_owner_id


_bq_client = None
_ss_client = None


def _bq():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=PROJECT)
    return _bq_client


def _ss() -> SharpSpringClient:
    global _ss_client
    if _ss_client is None:
        _ss_client = SharpSpringClient()
    return _ss_client


def _now_uk() -> datetime:
    return datetime.now(UK)


def _log(msg: str) -> None:
    print(f"{datetime.now(UK).strftime('%H:%M:%S')} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def fetch_window() -> list[dict]:
    """All events today .. +WINDOW_DAYS, UK wall-clock times, with id/body/created."""
    token = engine.get_graph_token()
    headers = {"Authorization": f"Bearer {token}",
               "Prefer": 'outlook.timezone="Europe/London"'}
    start = _now_uk().strftime("%Y-%m-%dT00:00:00")
    end = (_now_uk() + timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT23:59:59")
    url = (
        f"https://graph.microsoft.com/v1.0/users/{engine.CALENDAR_MAILBOX}/calendarView"
        f"?startDateTime={start}&endDateTime={end}"
        "&$select=id,subject,start,end,isAllDay,showAs,categories,attendees,"
        "bodyPreview,location,createdDateTime"
        "&$top=200"
    )
    events: list[dict] = []
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        events.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return events


def event_gone(event_id: str) -> bool:
    """True only on a definite 404 for the event — network errors return False."""
    token = engine.get_graph_token()
    try:
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{engine.CALENDAR_MAILBOX}/events/{event_id}"
            "?$select=id",
            headers={"Authorization": f"Bearer {token}"}, timeout=30)
        return resp.status_code == 404
    except requests.RequestException:
        return False


def event_times(event: dict) -> tuple[str, str, str]:
    """(date_iso, start_hhmm, end_hhmm) in UK wall clock (Prefer header applied)."""
    s = (event.get("start") or {}).get("dateTime", "")[:16]
    e = (event.get("end") or {}).get("dateTime", "")[:16]
    return s[:10], s[11:16], e[11:16]


def clean_ts(s: str) -> str:
    """Graph returns 7-digit fractional seconds ('...53.1696563Z') — BigQuery
    TIMESTAMP params only accept up to microseconds."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$", s or "")
    if not m:
        return s
    frac = (m.group(2) or "")[:6]
    return m.group(1) + (f".{frac}" if frac else "") + (m.group(3) or "Z")


def event_text(event: dict) -> str:
    """Searchable text of an event: subject + body + location, with the
    Microsoft Teams boilerplate cut off — Teams meeting IDs look exactly like
    UK phone numbers and would false-anchor internal events as appointments."""
    body = event.get("bodyPreview") or ""
    for marker in ("____", "Microsoft Teams meeting"):
        idx = body.find(marker)
        if idx >= 0:
            body = body[:idx]
    return " | ".join(filter(None, [
        event.get("subject") or "", body.strip(),
        ((event.get("location") or {}).get("displayName") or "")]))


# ---------------------------------------------------------------------------
# Rep + appointment detection
# ---------------------------------------------------------------------------

def rep_owner_map() -> dict[str, str]:
    rows = _bq().query(
        f"SELECT name, sharpspring_owner_id FROM `{PROJECT}.app.reps` "
        "WHERE COALESCE(sharpspring_owner_id, '') != ''").result()
    return {r["name"]: r["sharpspring_owner_id"] for r in rows}


def is_appointment(event: dict, rep_owners: dict[str, str]) -> str | None:
    """Return the field rep's name if this event could be a customer appointment.

    Rep categories are also used for internal events (quizzes, half-day blocks,
    "Teams day"), so this is only the first gate — handle_new additionally
    requires an anchor (postcode, phone, or a CRM lead match) before a row is
    written.
    """
    if event.get("isAllDay"):
        return None
    if engine._is_full_day_off(event) or engine._is_time_off(event) or engine._is_banner(event):
        return None
    s = (event.get("start") or {}).get("dateTime", "")[:16]
    e = (event.get("end") or {}).get("dateTime", "")[:16]
    try:  # day-long blocks (availability/admin) are never customer visits
        hours = (datetime.fromisoformat(e) - datetime.fromisoformat(s)).total_seconds() / 3600
        if hours >= 6:
            return None
    except ValueError:
        pass
    rep = engine._resolve_rep(event)
    return rep if rep in rep_owners else None


# ---------------------------------------------------------------------------
# Lead matching ladder
# ---------------------------------------------------------------------------

def _digits(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _name_segments(subject: str) -> list[str]:
    """Name-looking chunks of the subject: 2-4 capitalisable words, letters only."""
    cleaned = POSTCODE_RE.sub(" ", PHONE_RE.sub(" ", subject or ""))
    segs = re.split(r"[-–—:|/,]+", cleaned)
    out = []
    for seg in segs:
        words = seg.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z'\.]+", w) for w in words):
            out.append(" ".join(words))
    return out


def _fresh_leads_today() -> list[dict]:
    today = _now_uk().strftime("%Y-%m-%d")
    leads, offset = [], 0
    while True:
        resp = _ss()._call("getLeadsDateRange", {
            "startDate": f"{today} 00:00:00", "endDate": f"{today} 23:59:59",
            "timestamp": "create", "limit": 500, "offset": offset})
        batch = resp.get("lead", []) if isinstance(resp, dict) else []
        leads.extend(batch)
        if len(batch) < 500:
            return leads
        offset += 500


def _norm_postcode(pc: str) -> str:
    return re.sub(r"\s+", "", (pc or "").upper())


def _pick_unique(candidates: dict[str, dict]) -> dict | None:
    """A confident match requires exactly one candidate — ambiguous ties go to
    the /links page, not a guess."""
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def match_lead(subject: str, text: str, postcode: str = "") -> tuple[dict | None, str]:
    """Confident-match ladder. Returns (lead-ish dict with id/name/owner, how).

    how: 'phone' | 'name' | 'name+postcode' | '' (no confident match).

    Rung 3 (name+postcode, added for old-lead linking) has NO age limit —
    unlike the name-only rung, which stays 60-day-guarded because a common
    name with no postcode corroboration is too likely to collide across an
    unbounded lead history.
    """
    from google.cloud import bigquery

    phone = PHONE_RE.search(text or "")
    if phone:
        last9 = _digits(phone.group())[-9:]
        if len(last9) == 9:
            rows = list(_bq().query(
                "SELECT id, first_name, last_name, owner_id"
                " FROM `bronze.sharpspring_leads`"
                " WHERE (REGEXP_REPLACE(COALESCE(phone_number,''),r'[^0-9]','') LIKE @ph"
                "     OR REGEXP_REPLACE(COALESCE(mobile_phone_number,''),r'[^0-9]','') LIKE @ph)"
                "   AND id NOT IN (SELECT id FROM `bronze.sharpspring_leads_deleted`)"
                " ORDER BY update_timestamp DESC LIMIT 1",
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("ph", "STRING", f"%{last9}")]),
            ).result())
            if rows:
                r = rows[0]
                return ({"id": str(r["id"]),
                         "name": f"{r['first_name'] or ''} {r['last_name'] or ''}".strip(),
                         "owner_id": r["owner_id"] or ""}, "phone")
            # today's leads may not be in bronze yet
            for lead in _fresh_leads_today():
                pd = _digits((lead.get("phoneNumber") or "") + (lead.get("mobilePhoneNumber") or ""))
                if last9 and last9 in pd:
                    return ({"id": str(lead["id"]),
                             "name": f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip(),
                             "owner_id": lead.get("ownerID") or ""}, "phone")

    candidates: dict[str, dict] = {}
    for seg in _name_segments(subject):
        toks = seg.lower().split()
        conds, params = [], []
        for i, tok in enumerate(toks):
            conds.append(f"LOWER(CONCAT(COALESCE(first_name,''),' ',COALESCE(last_name,''))) LIKE @t{i}")
            params.append(bigquery.ScalarQueryParameter(f"t{i}", "STRING", f"%{tok}%"))
        rows = list(_bq().query(
            "SELECT id, first_name, last_name, owner_id FROM `bronze.sharpspring_leads`"
            f" WHERE {' AND '.join(conds)}"
            "   AND DATE(create_timestamp, 'Europe/London')"
            "       >= DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL 60 DAY)"
            "   AND id NOT IN (SELECT id FROM `bronze.sharpspring_leads_deleted`)"
            " QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY update_timestamp DESC) = 1"
            " LIMIT 5",
            job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
        for r in rows:
            candidates[str(r["id"])] = {
                "id": str(r["id"]),
                "name": f"{r['first_name'] or ''} {r['last_name'] or ''}".strip(),
                "owner_id": r["owner_id"] or ""}
        for lead in _fresh_leads_today() if not rows else []:
            full = f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".lower()
            if all(t in full for t in toks):
                candidates[str(lead["id"])] = {
                    "id": str(lead["id"]),
                    "name": f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip(),
                    "owner_id": lead.get("ownerID") or ""}
    picked = _pick_unique(candidates)
    if picked:
        return picked, "name"

    # Rung 3: unique (name + postcode) match, no age limit — old-lead linking.
    pc_norm = _norm_postcode(postcode)
    if pc_norm:
        pc_candidates: dict[str, dict] = {}
        for seg in _name_segments(subject):
            toks = seg.lower().split()
            conds, params = [], []
            for i, tok in enumerate(toks):
                conds.append(
                    f"LOWER(CONCAT(COALESCE(first_name,''),' ',COALESCE(last_name,''))) LIKE @t{i}")
                params.append(bigquery.ScalarQueryParameter(f"t{i}", "STRING", f"%{tok}%"))
            conds.append("REPLACE(UPPER(COALESCE(zipcode,'')),' ','') = @pc")
            params.append(bigquery.ScalarQueryParameter("pc", "STRING", pc_norm))
            rows = list(_bq().query(
                "SELECT id, first_name, last_name, owner_id FROM `bronze.sharpspring_leads`"
                f" WHERE {' AND '.join(conds)}"
                "   AND id NOT IN (SELECT id FROM `bronze.sharpspring_leads_deleted`)"
                " QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY update_timestamp DESC) = 1"
                " LIMIT 5",
                job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
            for r in rows:
                pc_candidates[str(r["id"])] = {
                    "id": str(r["id"]),
                    "name": f"{r['first_name'] or ''} {r['last_name'] or ''}".strip(),
                    "owner_id": r["owner_id"] or ""}
        picked = _pick_unique(pc_candidates)
        if picked:
            return picked, "name+postcode"

    return None, ""


# ---------------------------------------------------------------------------
# CRM writes (mirror of availability_app/app.py _ss_update_lead, heating path)
# ---------------------------------------------------------------------------

def _created_uk(created: str | None) -> str:
    """Graph createdDateTime (UTC) -> UK-wallclock string; '' if unparseable."""
    try:
        dt = datetime.fromisoformat(clean_ts(created or "").replace("Z", "+00:00"))
        return dt.astimezone(UK).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


def _parse_appt(val: str) -> datetime | None:
    try:
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UK)
    except (ValueError, TypeError):
        return None


def crm_book(lead: dict, *, date_iso: str, start: str, rep_owner_id: str,
             rep_name: str, prev_appt: str, booked_ts: str = "", made_by: str = "") -> bool:
    """booked_ts: UK-wallclock 'YYYY-MM-DD HH:MM:SS' of when the booking was
    MADE (the Outlook event's creation time). The metre counts bookings by this
    field — stamping now() here made backfilled old bookings count as booked
    today (25 Aug incident: the metre jumped by 7).

    made_by: CRM "Appointment Booked By" picklist value — only ever passed
    when the lead's pre-booking owner resolved to one of the three valid
    telesales people (see resolve_booker); never written when unresolved."""
    new_appt = f"{date_iso} {start}:00"
    obj = {
        "id": lead["id"],
        "leadStatus": "qualified",
        SS_F_APPT_DT: new_appt,
        SS_F_APPT_BOOKED: "Yes",
        SS_F_APPT_TYPE: "Physical",
        SS_F_BOOKED_TS: booked_ts or _now_uk().strftime("%Y-%m-%d %H:%M:%S"),
        SS_F_STATUS: "Appointment",
        "ownerID": rep_owner_id or (lead.get("owner_id") or ""),
    }
    if not obj["ownerID"]:
        del obj["ownerID"]  # never let SharpSpring default it to the API account
    if prev_appt and prev_appt != new_appt:
        obj[SS_F_PREV_APPT] = prev_appt
    if made_by:
        obj[SS_F_MADE_BY] = made_by
    resp = _ss()._call("updateLeads", {"objects": [obj]})
    updates = (resp.get("updates") if isinstance(resp, dict) else resp) or []
    ok = bool(updates and updates[0].get("success"))
    if ok:
        try:
            _ss()._call("createNotes", {"objects": [{
                "whoID": lead["id"], "whoType": "lead",
                "note": (f"Appointment {date_iso} {start} with {rep_name} — booked "
                         "manually in the Outlook calendar; auto-linked to this lead "
                         "by the calendar watcher."),
                "authorID": obj.get("ownerID") or (lead.get("owner_id") or "")}]})
        except Exception as exc:  # noqa: BLE001 — the booking write already succeeded
            _log(f"  note failed for lead {lead['id']}: {exc}")
    return ok


def crm_move(lead_id: str, *, date_iso: str, start: str, prev_appt: str) -> bool:
    new_appt = f"{date_iso} {start}:00"
    obj = {"id": lead_id, SS_F_APPT_DT: new_appt}
    if prev_appt and prev_appt != new_appt:
        obj[SS_F_PREV_APPT] = prev_appt
    resp = _ss()._call("updateLeads", {"objects": [obj]})
    updates = (resp.get("updates") if isinstance(resp, dict) else resp) or []
    return bool(updates and updates[0].get("success"))


def get_lead(lead_id: str) -> dict | None:
    resp = _ss()._call("getLeads", {"where": {"id": str(lead_id)}, "limit": 1})
    leads = resp.get("lead", []) if isinstance(resp, dict) else []
    return leads[0] if leads else None


def _book_with_attribution(live: dict, lead_id: str, *, date_iso: str, start: str,
                           rep: str, rep_owners: dict[str, str], prev_appt: str,
                           booked_ts: str) -> tuple[str, str, str, str]:
    """Write the CRM appointment (crm_book) and resolve booker attribution from
    the lead's PRE-BOOKING owner (fetched into `live` before this call — never
    the post-write owner, which crm_book is about to reassign to the rep).

    Returns (crm_status, link_status, booker_name, booker_owner_id).
    link_status is 'auto' when the owner resolved to one of the three valid
    telesales people; otherwise 'needs_owner' — queued on the /links page for
    a human to claim — and booker_name stays 'Manual (calendar)'.
    """
    resolved = resolve_booker(live.get("ownerID") or "")
    made_by = resolved[2] if resolved else ""
    ok = crm_book(live | {"id": lead_id, "owner_id": live.get("ownerID") or ""},
                  date_iso=date_iso, start=start,
                  rep_owner_id=rep_owners.get(rep, ""), rep_name=rep,
                  prev_appt=prev_appt, booked_ts=booked_ts, made_by=made_by)
    crm_status = "updated" if ok else "failed"
    if resolved:
        booker_name, booker_owner_id, _made_by = resolved
        link_status = "auto"
    else:
        booker_name, booker_owner_id = "Manual (calendar)", ""
        link_status = "needs_owner"
    return crm_status, link_status, booker_name, booker_owner_id


# ---------------------------------------------------------------------------
# Bookings table
# ---------------------------------------------------------------------------

def load_bookings() -> dict[str, dict]:
    rows = _bq().query(
        "SELECT event_id, lead_id, status, appt_date, appt_start, appt_end,"
        "       rep_name, link_status, crm_status, customer, postcode, booked_at,"
        "       booker_name, booker_owner_id, entered_by"
        f" FROM {BOOKINGS}").result()
    return {r["event_id"]: dict(r) for r in rows if r["event_id"]}


def insert_booking(**kv) -> None:
    from google.cloud import bigquery
    cols = ("event_id", "lead_id", "booker_username", "booker_owner_id", "booker_name",
            "rep_name", "rep_owner_id", "customer", "postcode", "appt_date",
            "appt_start", "appt_end", "booked_at", "status", "appt_type",
            "is_rebook", "entered_by", "link_status", "crm_status")
    params = [
        bigquery.ScalarQueryParameter(c, "BOOL" if c == "is_rebook" else
                                      "TIMESTAMP" if c == "booked_at" else "STRING", kv[c])
        for c in cols]
    _bq().query(
        f"INSERT INTO {BOOKINGS} ({', '.join(cols)}) VALUES ({', '.join('@' + c for c in cols)})",
        job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def update_booking(event_id: str, sets: dict) -> None:
    from google.cloud import bigquery
    assigns, params = [], [bigquery.ScalarQueryParameter("event_id", "STRING", event_id)]
    for k, v in sets.items():
        typ = "TIMESTAMP" if k.endswith("_at") else "STRING"
        assigns.append(f"{k} = @{k}")
        params.append(bigquery.ScalarQueryParameter(k, typ, v))
    _bq().query(
        f"UPDATE {BOOKINGS} SET {', '.join(assigns)} WHERE event_id = @event_id",
        job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


# ---------------------------------------------------------------------------
# The three reconciliations
# ---------------------------------------------------------------------------

def handle_new(event: dict, rep: str, rep_owners: dict[str, str]) -> None:
    date_iso, start, end = event_times(event)
    raw_subject = event.get("subject") or ""
    subject = _strip_parens(raw_subject)  # keep parentheticals out of name/customer extraction
    text = event_text(event)
    pc = POSTCODE_RE.search(text)
    lead, how = match_lead(subject, text, postcode=(pc.group() if pc else ""))

    # Anchor rule (from the 25 Aug dry run): rep categories are reused for
    # internal events — Trust Quiz, "Ask The Inventor", half-day blocks. Only
    # treat the event as a customer appointment if something ties it to a
    # customer: a postcode, a phone number, or an actual CRM lead match.
    if not pc and not PHONE_RE.search(text) and not lead:
        _log(f"skip (no customer anchor): {raw_subject!r} · {rep} · {date_iso} {start}")
        return

    link_status, crm_status = "needs_link", "skipped"
    booker_name, booker_owner_id = "Manual (calendar)", ""
    # customer fallback: the LAST name-looking chunk of the subject — manual
    # subjects tend to put the name after a dash ("Getting information - X Y")
    lead_id, customer = "", (
        (_name_segments(subject) or [subject.strip()[:80] or "(no subject)"])[-1])
    if lead:
        lead_id, customer = lead["id"], lead["name"] or customer
        live = get_lead(lead_id)
        if live is None:
            link_status, crm_status, lead_id = "needs_link", "not_found", ""
        else:
            existing = live.get(SS_F_APPT_DT) or ""
            existing_dt = _parse_appt(existing)
            new_dt = _parse_appt(f"{date_iso} {start}:00")
            if existing_dt and new_dt and existing_dt > _now_uk() and existing_dt != new_dt:
                # the two-visits case: a DIFFERENT future appointment already
                # in the CRM — never overwrite, flag for a human
                link_status, crm_status = "conflict", "conflict"
            else:
                crm_status, link_status, booker_name, booker_owner_id = _book_with_attribution(
                    live, lead_id, date_iso=date_iso, start=start, rep=rep,
                    rep_owners=rep_owners, prev_appt=existing,
                    booked_ts=_created_uk(event.get("createdDateTime")))

    insert_booking(
        event_id=event["id"], lead_id=lead_id,
        booker_username="watcher", booker_owner_id=booker_owner_id, booker_name=booker_name,
        rep_name=rep, rep_owner_id=rep_owners.get(rep, ""),
        customer=customer, postcode=(pc.group().upper() if pc else ""),
        appt_date=date_iso, appt_start=start, appt_end=end,
        booked_at=clean_ts(event.get("createdDateTime") or "") or datetime.now(timezone.utc).isoformat(),
        status="active", appt_type="heating", is_rebook=False,
        entered_by="watcher", link_status=link_status, crm_status=crm_status)
    _log(f"NEW manual: {customer} · {rep} · {date_iso} {start} · "
         f"link={link_status}({how or '-'}) crm={crm_status} booker={booker_name}")


def handle_drift(event: dict, row: dict) -> None:
    date_iso, start, end = event_times(event)
    if (date_iso, start, end) == (row["appt_date"], row["appt_start"], row["appt_end"]):
        return
    sets = {"appt_date": date_iso, "appt_start": start, "appt_end": end,
            "rescheduled_at": datetime.now(timezone.utc).isoformat(), "rescheduled_by": "watcher"}
    if row["lead_id"] and (row["crm_status"] in (None, "", "updated")):
        moved = crm_move(row["lead_id"], date_iso=date_iso, start=start,
                         prev_appt=f"{row['appt_date']} {row['appt_start']}:00")
        if not moved:
            sets["crm_status"] = "failed"
    update_booking(row["event_id"], sets)
    _log(f"MOVED: {row['customer']} {row['appt_date']} {row['appt_start']} "
         f"-> {date_iso} {start}")


def handle_deletions(bookings: dict[str, dict], seen_ids: set[str]) -> None:
    today = _now_uk().strftime("%Y-%m-%d")
    horizon = (_now_uk() + timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    for event_id, row in bookings.items():
        if (row["status"] == "active" and today <= row["appt_date"] <= horizon
                and event_id not in seen_ids and event_gone(event_id)):
            update_booking(event_id, {
                "status": "cancelled",
                "cancelled_at": datetime.now(timezone.utc).isoformat(),
                "cancelled_by": "watcher"})
            _log(f"CANCELLED (event deleted in Outlook): {row['customer']} "
                 f"{row['appt_date']} {row['appt_start']} — CRM untouched, "
                 f"lead {row['lead_id'] or '(none)'}")


def retry_unlinked(bookings: dict[str, dict], rep_owners: dict[str, str],
                   include_past: bool = False) -> None:
    today = _now_uk().strftime("%Y-%m-%d")
    for row in bookings.values():
        if row["status"] != "active" or row["link_status"] != "needs_link":
            continue
        future = row["appt_date"] >= today
        if not future and not include_past:
            continue
        text = f"{row['customer']} | {row['postcode']}"
        lead, how = match_lead(row["customer"] or "", text, postcode=row.get("postcode") or "")
        if not lead:
            continue
        live = get_lead(lead["id"])
        if live is None:
            continue
        existing = live.get(SS_F_APPT_DT) or ""
        existing_dt = _parse_appt(existing)
        new_dt = _parse_appt(f"{row['appt_date']} {row['appt_start']}:00")
        if future and existing_dt and new_dt and existing_dt > _now_uk() and existing_dt != new_dt:
            update_booking(row["event_id"], {"lead_id": lead["id"],
                                             "link_status": "conflict",
                                             "crm_status": "conflict"})
            _log(f"RETRY -> conflict: {row['customer']} vs lead {lead['id']}")
            continue
        crm = "skipped"
        sets = {"lead_id": lead["id"], "link_status": "auto", "crm_status": crm}
        booker_name = row.get("booker_name") or "Manual (calendar)"  # unchanged unless resolved below
        if future:
            row_booked = row.get("booked_at")
            crm, link_status, booker_name, booker_owner_id = _book_with_attribution(
                live, lead["id"], date_iso=row["appt_date"], start=row["appt_start"],
                rep=row["rep_name"], rep_owners=rep_owners, prev_appt=existing,
                booked_ts=(row_booked.astimezone(UK).strftime("%Y-%m-%d %H:%M:%S")
                           if row_booked else ""))
            sets.update(link_status=link_status, crm_status=crm,
                        booker_name=booker_name, booker_owner_id=booker_owner_id)
        update_booking(row["event_id"], sets)
        _log(f"LINKED ({how}): {row['customer']} -> lead {lead['id']} crm={crm} booker={booker_name}")


def self_heal(bookings: dict[str, dict]) -> None:
    """Each run: for watcher rows booked in the last 7 days, re-check the linked
    lead's LIVE CRM "Appointment Booked By" stamp — a human may have corrected
    it, or set it after the owner-derived guess came up empty. The CRM stamp
    always wins (see self_heal_decision); NEVER touches non-watcher rows.
    """
    cutoff = _now_uk() - timedelta(days=7)
    for row in bookings.values():
        if row.get("entered_by") != "watcher" or not row.get("lead_id"):
            continue
        booked_at = row.get("booked_at")
        if not booked_at:
            continue
        try:
            booked_uk = booked_at.astimezone(UK)
        except (TypeError, ValueError):
            continue
        if booked_uk < cutoff:
            continue
        live = get_lead(row["lead_id"])
        if live is None:
            continue
        decision = self_heal_decision(row.get("booker_name") or "Manual (calendar)",
                                      live.get(SS_F_MADE_BY) or "")
        if decision is None:
            continue
        new_name, new_owner_id = decision
        sets = {"booker_name": new_name, "booker_owner_id": new_owner_id}
        if row.get("link_status") == "needs_owner":
            sets["link_status"] = "auto"
        update_booking(row["event_id"], sets)
        _log(f"SELF-HEAL: {row['customer']} booker -> {new_name} (CRM stamp)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true",
                    help="also retry ALL historical needs_link rows (past appointments"
                         " get linked but never written to the CRM)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rep_owners = rep_owner_map()
    events = fetch_window()
    bookings = load_bookings()
    seen = {e["id"] for e in events}

    appts = [(e, r) for e in events
             if (r := is_appointment(e, rep_owners))]
    # 10-min grace on brand-new events: the app creates the calendar event
    # seconds before inserting its bookings row — without this, the watcher
    # could misread an in-flight app booking as manual and double-write.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    new = [(e, r) for e, r in appts
           if e["id"] not in bookings
           and (e.get("createdDateTime") or "")[:19] < cutoff]
    _log(f"window: {len(events)} events, {len(appts)} appointments, "
         f"{len(new)} new manual, {len(bookings)} booking rows")
    if args.dry_run:
        for e, r in new:
            d, s, _ = event_times(e)
            subject = _strip_parens(e.get("subject") or "")
            text = event_text(e)
            pc = POSTCODE_RE.search(text)
            lead, how = match_lead(subject, text, postcode=(pc.group() if pc else ""))
            anchored = bool(pc or PHONE_RE.search(text) or lead)
            verdict = ("ADD linked=" + (f"{lead['id']} ({how})" if lead else "needs_link")
                       if anchored else "SKIP (no customer anchor)")
            _log(f"  {verdict}: {subject!r} · {r} · {d} {s}")
        return

    for e, r in new:
        handle_new(e, r, rep_owners)
    for e, r in appts:
        if e["id"] in bookings and bookings[e["id"]]["status"] == "active":
            handle_drift(e, bookings[e["id"]])
    handle_deletions(bookings, seen)
    retry_unlinked(bookings, rep_owners, include_past=args.sweep)
    self_heal(bookings)


if __name__ == "__main__":
    main()
