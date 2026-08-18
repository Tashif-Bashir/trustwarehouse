"""
Availability engine — derives per-rep free slots from the shared Outlook calendar.

Data source: MS Graph calendarView on info@trustelectricheating.co.uk
Rep attribution: attendee email (primary) → category (fallback)
Time-off detection: all-day events OR OOO keywords in subject, regardless of showAs flag
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Rep / region master data — loaded from reps.json at the repo root
# ---------------------------------------------------------------------------

# Calendar attendees who appear in events but are not reps (observed in diagnosis)
_NON_REP_EXTRAS: dict[str, str] = {
    "merv":     "Merv",
    "victoria": "Victoria",
    "gia":      "Gia",
    "paula":    "Paula",
}

GENERIC_EMAILS: set[str] = {
    "info@trustelectricheating.co.uk",
    "telesales@trustelectricheating.co.uk",
}


_bq_reps_client = None
_BQ_REPS_PROJECT = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
_BQ_REPS_TABLE   = f"`{_BQ_REPS_PROJECT}.app.reps`"


def _bq_reps():
    global _bq_reps_client
    if _bq_reps_client is None:
        from google.cloud import bigquery as _bq_mod
        _bq_reps_client = _bq_mod.Client(project=_BQ_REPS_PROJECT)
    return _bq_reps_client


def _load_reps() -> list[dict]:
    try:
        rows = list(_bq_reps().query(
            f"SELECT * FROM {_BQ_REPS_TABLE} ORDER BY created_at"
        ).result())
        return [
            {
                "name":         row["name"],
                "email":        row["email"] or "",
                "regions":      json.loads(row["regions"] or "[]"),
                "fallback":     bool(row["fallback"]),
                "freelancer":   bool(row["freelancer"]),
                "weekend_days": json.loads(row["weekend_days"] or "[]"),
                "aliases":      json.loads(row["aliases"] or "[]"),
                "sharpspring_owner_id": (row["sharpspring_owner_id"]
                                         if "sharpspring_owner_id" in row.keys() else "") or "",
            }
            for row in rows
        ]
    except Exception as exc:
        import sys
        print(f"WARNING: could not load reps from BigQuery: {exc}", file=sys.stderr)
        return []


def _build_rep_maps(reps: list[dict]) -> tuple:
    from collections import Counter
    first_counts: Counter = Counter(r["name"].split()[0].lower() for r in reps)

    rep_region: dict[str, list[str]] = {}
    fallback_reps: list[str] = []
    freelancer_reps: set[str] = set()
    weekend_work: dict[str, set[int]] = {}
    email_to_rep: dict[str, str] = dict(_NON_REP_EXTRAS)
    rep_email: dict[str, str] = {}
    category_to_rep: dict[str, str] = {}
    freelancer_email_to_rep: dict[str, str] = {}

    for rep in reps:
        name: str = rep["name"]
        email: str = rep.get("email", "")
        regions: list[str] = rep.get("regions", [])
        is_fallback: bool = rep.get("fallback", False)
        is_freelancer: bool = rep.get("freelancer", False)
        weekend_days: list[int] = rep.get("weekend_days", [])
        aliases: list[str] = rep.get("aliases", [])

        if is_fallback:
            fallback_reps.append(name)
        else:
            rep_region[name] = regions

        if email:
            rep_email[name] = email
            if is_freelancer:
                freelancer_email_to_rep[email.lower()] = name
            else:
                email_to_rep[email.split("@")[0].lower()] = name

        if is_freelancer:
            freelancer_reps.add(name)

        if weekend_days:
            weekend_work[name] = set(weekend_days)

        # Auto first name only when unambiguous; always add full name and explicit aliases
        first = name.split()[0].lower()
        if first_counts[first] == 1:
            category_to_rep[first] = name
        category_to_rep[name.lower()] = name
        for alias in aliases:
            category_to_rep[alias.lower()] = name

    return (rep_region, fallback_reps, freelancer_reps, weekend_work,
            email_to_rep, rep_email, category_to_rep, freelancer_email_to_rep)


def reload_reps() -> None:
    """Reload all rep maps from reps.json in-place. Called after admin saves changes."""
    maps = _build_rep_maps(_load_reps())
    REP_REGION.clear();              REP_REGION.update(maps[0])
    FALLBACK_REPS[:] =               maps[1]
    FREELANCER_REPS.clear();         FREELANCER_REPS.update(maps[2])
    WEEKEND_WORK.clear();            WEEKEND_WORK.update(maps[3])
    EMAIL_TO_REP.clear();            EMAIL_TO_REP.update(maps[4])
    REP_EMAIL.clear();               REP_EMAIL.update(maps[5])
    CATEGORY_TO_REP.clear();         CATEGORY_TO_REP.update(maps[6])
    FREELANCER_EMAIL_TO_REP.clear(); FREELANCER_EMAIL_TO_REP.update(maps[7])


(
    REP_REGION,               # canonical_name → region(s) — non-fallback reps
    FALLBACK_REPS,            # shown only when no regional rep is free
    FREELANCER_REPS,          # shown in region but badged separately
    WEEKEND_WORK,             # rep → set of weekday ints (5=Sat, 6=Sun)
    EMAIL_TO_REP,             # email local-part → canonical name
    REP_EMAIL,                # canonical name → full email
    CATEGORY_TO_REP,          # category text (lowercase) → canonical name
    FREELANCER_EMAIL_TO_REP,  # full email → canonical name (freelancers)
) = _build_rep_maps(_load_reps())

# ---------------------------------------------------------------------------
# Postcode prefix → region
# ---------------------------------------------------------------------------

POSTCODE_TO_REGION: dict[str, str] = {
    # North East
    "NE": "North East", "SR": "North East", "DH": "North East",
    "TS": "North East", "DL": "North East",
    # Yorkshire & Humber
    "LS": "Yorkshire & Humber", "BD": "Yorkshire & Humber",
    "HX": "Yorkshire & Humber", "HD": "Yorkshire & Humber",
    "WF": "Yorkshire & Humber", "DN": "Yorkshire & Humber",
    "S":  "Yorkshire & Humber", "HU": "Yorkshire & Humber",
    "YO": "Yorkshire & Humber", "HG": "Yorkshire & Humber",
    # North West
    "M":  "North West", "L":  "North West", "BL": "North West",
    "OL": "North West", "SK": "North West", "WN": "North West",
    "WA": "North West", "PR": "North West", "FY": "North West",
    "BB": "North West", "LA": "North West", "CH": "North West",
    "CA": "North West", "CW": "North West",
    # London
    "E":  "London", "EC": "London", "N":  "London", "NW": "London",
    "SE": "London", "SW": "London", "W":  "London", "WC": "London",
    "BR": "London", "CR": "London", "DA": "London", "EN": "London",
    "HA": "London", "IG": "London", "KT": "London", "RM": "London",
    "SM": "London", "TW": "London", "UB": "London", "WD": "London",
    # South East
    "BN": "South East", "CT": "South East", "GU": "South East",
    "ME": "South East", "MK": "South East", "OX": "South East",
    "PO": "South East", "RG": "South East", "RH": "South East",
    "SL": "South East", "SO": "South East", "SP": "South East",
    "TN": "South East",
    # East of England
    "CB": "East of England", "CM": "East of England", "CO": "East of England",
    "IP": "East of England", "LU": "East of England", "NR": "East of England",
    "PE": "East of England", "SG": "East of England", "SS": "East of England",
    "AL": "East of England", "HP": "East of England",
    # South West
    "BS": "South West", "BA": "South West", "BH": "South West",
    "DT": "South West", "EX": "South West", "GL": "South West",
    "PL": "South West", "SN": "South West", "TA": "South West",
    "TQ": "South West", "TR": "South West",
    # West Midlands
    "B":  "West Midlands", "CV": "West Midlands", "DY": "West Midlands",
    "ST": "West Midlands", "TF": "West Midlands", "WR": "West Midlands",
    "WS": "West Midlands", "WV": "West Midlands", "HR": "West Midlands",
    # East Midlands
    "DE": "East Midlands", "LE": "East Midlands", "LN": "East Midlands",
    "NG": "East Midlands", "NN": "East Midlands",
    # Wales
    "CF": "Wales", "SA": "Wales", "NP": "Wales",
    "LL": "Wales", "SY": "Wales", "LD": "Wales",
    # Scotland
    "AB": "Scotland", "DD": "Scotland", "DG": "Scotland",
    "EH": "Scotland", "FK": "Scotland", "G":  "Scotland",
    "HS": "Scotland", "IV": "Scotland", "KA": "Scotland",
    "KW": "Scotland", "KY": "Scotland", "ML": "Scotland",
    "PA": "Scotland", "PH": "Scotland", "TD": "Scotland",
    "ZE": "Scotland",
}

# ---------------------------------------------------------------------------
# City → region
# ---------------------------------------------------------------------------

CITY_TO_REGION: dict[str, str] = {
    # North East
    "newcastle": "North East", "newcastle upon tyne": "North East",
    "sunderland": "North East", "durham": "North East",
    "middlesbrough": "North East", "gateshead": "North East",
    "stockton": "North East", "stockton-on-tees": "North East",
    "hartlepool": "North East", "darlington": "North East",
    "south shields": "North East",
    # Yorkshire & Humber
    "leeds": "Yorkshire & Humber", "sheffield": "Yorkshire & Humber",
    "bradford": "Yorkshire & Humber", "hull": "Yorkshire & Humber",
    "kingston upon hull": "Yorkshire & Humber",
    "york": "Yorkshire & Humber", "huddersfield": "Yorkshire & Humber",
    "halifax": "Yorkshire & Humber", "doncaster": "Yorkshire & Humber",
    "rotherham": "Yorkshire & Humber", "wakefield": "Yorkshire & Humber",
    "barnsley": "Yorkshire & Humber", "harrogate": "Yorkshire & Humber",
    "scunthorpe": "Yorkshire & Humber", "grimsby": "Yorkshire & Humber",
    # North West
    "manchester": "North West", "liverpool": "North West",
    "salford": "North West", "bolton": "North West",
    "stockport": "North West", "bury": "North West",
    "oldham": "North West", "wigan": "North West",
    "warrington": "North West", "preston": "North West",
    "blackpool": "North West", "blackburn": "North West",
    "lancaster": "North West", "chester": "North West",
    "carlisle": "North West", "burnley": "North West",
    "rochdale": "North West", "birkenhead": "North West",
    # London
    "london": "London",
    # South East
    "brighton": "South East", "hove": "South East",
    "southampton": "South East", "portsmouth": "South East",
    "oxford": "South East", "reading": "South East",
    "milton keynes": "South East", "maidstone": "South East",
    "guildford": "South East", "crawley": "South East",
    "basingstoke": "South East", "canterbury": "South East",
    "eastbourne": "South East", "folkestone": "South East",
    "hastings": "South East", "worthing": "South East",
    "slough": "South East", "windsor": "South East",
    # East of England
    "norwich": "East of England", "cambridge": "East of England",
    "ipswich": "East of England", "luton": "East of England",
    "peterborough": "East of England", "colchester": "East of England",
    "chelmsford": "East of England", "southend": "East of England",
    "southend-on-sea": "East of England", "stevenage": "East of England",
    "watford": "East of England", "st albans": "East of England",
    # South West
    "bristol": "South West", "plymouth": "South West",
    "exeter": "South West", "swindon": "South West",
    "gloucester": "South West", "cheltenham": "South West",
    "bath": "South West", "bournemouth": "South West",
    "poole": "South West", "truro": "South West",
    "torquay": "South West", "taunton": "South West",
    "weston-super-mare": "South West", "yeovil": "South West",
    # West Midlands
    "birmingham": "West Midlands", "coventry": "West Midlands",
    "wolverhampton": "West Midlands", "walsall": "West Midlands",
    "dudley": "West Midlands", "solihull": "West Midlands",
    "west bromwich": "West Midlands", "stoke": "West Midlands",
    "stoke-on-trent": "West Midlands", "telford": "West Midlands",
    "stafford": "West Midlands", "worcester": "West Midlands",
    "hereford": "West Midlands", "nuneaton": "West Midlands",
    "tamworth": "West Midlands", "redditch": "West Midlands",
    # East Midlands
    "derby": "East Midlands", "nottingham": "East Midlands",
    "leicester": "East Midlands", "lincoln": "East Midlands",
    "northampton": "East Midlands", "mansfield": "East Midlands",
    "chesterfield": "East Midlands", "loughborough": "East Midlands",
    "kettering": "East Midlands", "corby": "East Midlands",
    # Wales
    "cardiff": "Wales", "swansea": "Wales", "newport": "Wales",
    "wrexham": "Wales", "bangor": "Wales", "aberystwyth": "Wales",
    "caerphilly": "Wales", "merthyr tydfil": "Wales",
    "bridgend": "Wales", "neath": "Wales",
    # Scotland
    "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
    "dundee": "Scotland", "inverness": "Scotland", "stirling": "Scotland",
    "perth": "Scotland", "paisley": "Scotland", "east kilbride": "Scotland",
    "livingston": "Scotland", "hamilton": "Scotland", "dunfermline": "Scotland",
    "ayr": "Scotland", "kilmarnock": "Scotland", "cumbernauld": "Scotland",
    "motherwell": "Scotland", "falkirk": "Scotland", "dumfries": "Scotland",
    "greenock": "Scotland", "fort william": "Scotland",
}

# ---------------------------------------------------------------------------
# OOO / time-off keyword detection
# ---------------------------------------------------------------------------

_OOO_RE = re.compile(
    r"\b(ooo|out of office|holiday|hols|annual leave|a/?l\b|day off|dayoff|"
    r"sick|off\b|no appts|bank holiday|busy|leave|training|finish early|"
    r"working from home|wfh|not available|unavailable)\b",
    re.IGNORECASE,
)

# Subset of OOO wording that means the WHOLE day is off regardless of the
# typed times. The team enters day-offs as e.g. 08:30-17:00, which left the
# 17:00 slot bookable ("KRIS DAY OFF", 21 Jul 2026). Partial wording
# (finish early, training, busy, wfh...) keeps respecting the typed window.
_FULL_DAY_OOO_RE = re.compile(
    r"\b(ooo|out of office|holiday|hols|annual leave|a/?l\b|day off|dayoff|"
    r"off\b|sick|no appts|bank holiday|leave)\b",
    re.IGNORECASE,
)


def _is_full_day_off(event: dict) -> bool:
    return bool(_FULL_DAY_OOO_RE.search(event.get("subject") or ""))


def _is_time_off(event: dict) -> bool:
    subject = event.get("subject") or ""
    if event.get("isAllDay"):
        # All-day events are time-off only when the subject says so (or has
        # no subject at all — an untitled block is a block). The old blanket
        # all-day=off rule swallowed informational banners like the
        # "Stephen Bishop Starting- ..." first-day markers (21 Jul 2026) and
        # marked a rep Off on a day he had three real appointments.
        return not subject.strip() or bool(_OOO_RE.search(subject))
    return bool(_OOO_RE.search(subject))


def _is_banner(event: dict) -> bool:
    """All-day informational banner (e.g. 'Stephen Bishop Starting-...').

    Not time-off, but not an appointment either — it must be invisible to
    availability: without this, a banner's 00:00-00:00 span marks every
    slot of the day as booked (observed 21 Jul 2026)."""
    return bool(event.get("isAllDay")) and not _is_time_off(event)


# ---------------------------------------------------------------------------
# Rep resolver
# ---------------------------------------------------------------------------

def _resolve_rep(event: dict) -> str | None:
    """Return canonical rep name from attendee email (primary) or category (fallback)."""
    for attendee in event.get("attendees", []):
        addr = (attendee.get("emailAddress", {}).get("address") or "").lower()
        if addr in GENERIC_EMAILS:
            continue
        # freelancer personal / business emails
        if addr in FREELANCER_EMAIL_TO_REP:
            return FREELANCER_EMAIL_TO_REP[addr]
        # Trust staff emails
        if addr.endswith("@trustelectricheating.co.uk"):
            local = addr.split("@")[0]
            if local in EMAIL_TO_REP:
                return EMAIL_TO_REP[local]
    for cat in (event.get("categories") or []):
        key = cat.lower().strip()
        if key in CATEGORY_TO_REP:
            return CATEGORY_TO_REP[key]
    return None


# ---------------------------------------------------------------------------
# MS Graph auth + event fetch
# ---------------------------------------------------------------------------

_MAILBOX = "info@trustelectricheating.co.uk"
CALENDAR_MAILBOX = _MAILBOX          # public alias for use in app.py
_token_cache: dict[str, Any] = {}


def _get_token() -> str:
    now = time.time()
    if _token_cache.get("expires_at", 0) > now + 60:
        return _token_cache["access_token"]
    env = _load_env()
    resp = requests.post(
        f"https://login.microsoftonline.com/{env['MS_TENANT_ID']}/oauth2/v2.0/token",
        data={
            "client_id": env["MS_CLIENT_ID"],
            "client_secret": env["MS_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["access_token"]


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def get_graph_token() -> str:
    """Return a valid MS Graph bearer token (cached for token lifetime)."""
    return _get_token()


def fetch_events(days: int = 14, start_date: date | None = None) -> list[dict]:
    """Pull all events from the shared calendar for `days` days starting from `start_date` (default today)."""
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Europe/London"',
    }
    if start_date:
        start = f"{start_date.isoformat()}T00:00:00Z"
        end = f"{(start_date + timedelta(days=days)).isoformat()}T23:59:59Z"
    else:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        start = now.strftime("%Y-%m-%dT00:00:00Z")
        end = (now + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59Z")
    url = (
        f"https://graph.microsoft.com/v1.0/users/{_MAILBOX}/calendarView"
        f"?startDateTime={start}&endDateTime={end}"
        "&$select=subject,start,end,isAllDay,showAs,categories,attendees"
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


# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------

def _working_days(from_date: date, days: int) -> list[date]:
    result: list[date] = []
    d = from_date
    while len(result) < days:
        if d.weekday() < 5:  # Mon–Fri
            result.append(d)
        d += timedelta(days=1)
    return result


def _slots_for_day(d: date, rep: str) -> list[str]:
    """Return list of 30-min slot start times for a rep on a given day."""
    if d.weekday() in (5, 6):  # weekend
        if d.weekday() not in WEEKEND_WORK.get(rep, set()):
            return []
    slots = []
    t = datetime(d.year, d.month, d.day, 9, 0)
    end = datetime(d.year, d.month, d.day, 17, 30)
    while t < end:
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots


def _parse_dt(event: dict, key: str) -> datetime | None:
    try:
        return datetime.fromisoformat(event[key]["dateTime"][:19])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main grid builder
# ---------------------------------------------------------------------------

def _now_london() -> datetime:
    """Current datetime in Europe/London (naive, matching slot datetimes)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def build_grid(events: list[dict], region: str | None = None, days: int = 10, start_date: date | None = None) -> dict:
    """
    Build the availability grid.

    Returns:
        {
          "region": str,
          "dates": ["2026-06-24", ...],
          "reps": [
            {
              "name": str,
              "region": str,
              "is_fallback": bool,
              "today_count": int,
              "days": {
                "2026-06-24": [
                  {"time": "09:00", "status": "free"|"booked"|"off", "subject": str|None},
                  ...
                ]
              }
            }
          ]
        }
    """
    actual_today = date.today()
    now_uk = _now_london()
    from_date = start_date if start_date else actual_today
    # build date list from from_date — include all 7 days so weekend-working
    # reps (Kris=Sat, Chris Southworth=Sat+Sun) get their slots shown
    all_dates: list[date] = []
    d = from_date
    while len([x for x in all_dates if x.weekday() < 5]) < days:
        all_dates.append(d)
        d += timedelta(days=1)

    # determine which reps to include — regional reps first, then (when a region is
    # selected) every other region's reps as a collapsed "book anyway" group, so
    # telesales can handle border postcodes / reps willing to travel.
    if region:
        regional_reps = [r for r, regions in REP_REGION.items() if region in regions]
        other_reps = [r for r in REP_REGION if r not in regional_reps]
    else:
        regional_reps = list(REP_REGION.keys())
        other_reps = []

    # classify events per rep per day
    rep_events: dict[str, dict[date, list[dict]]] = {r: {} for r in regional_reps + FALLBACK_REPS + other_reps}
    for event in events:
        rep = _resolve_rep(event)
        if rep not in rep_events:
            continue
        start_dt = _parse_dt(event, "start")
        if start_dt is None:
            continue
        day = start_dt.date()
        rep_events[rep].setdefault(day, []).append(event)

    result_reps = []

    all_output_reps = regional_reps + FALLBACK_REPS + other_reps
    for rep in all_output_reps:
        rep_regions = REP_REGION.get(rep, ["Any"])
        is_fallback = rep in FALLBACK_REPS
        today_count = len([
            e for e in rep_events.get(rep, {}).get(actual_today, [])
            if not _is_time_off(e) and not _is_banner(e)
        ])

        days_out: dict[str, list[dict]] = {}
        for d in all_dates:
            slots = _slots_for_day(d, rep)
            if not slots:
                continue
            # banners are invisible to availability (neither off nor booked)
            day_events = [e for e in rep_events.get(rep, {}).get(d, []) if not _is_banner(e)]

            # build booked/off intervals
            booked_intervals: list[tuple[datetime, datetime]] = []
            off_intervals: list[tuple[datetime, datetime]] = []

            for event in day_events:
                s = _parse_dt(event, "start")
                e = _parse_dt(event, "end")
                if s is None or e is None:
                    continue
                if _is_time_off(event):
                    # all-day events and full-day wording block the whole
                    # day; partial wording (finish early etc.) blocks only
                    # the typed window
                    if event.get("isAllDay") or _is_full_day_off(event):
                        off_intervals.append((
                            datetime(d.year, d.month, d.day, 0, 0),
                            datetime(d.year, d.month, d.day, 23, 59),
                        ))
                    else:
                        off_intervals.append((s, e))
                else:
                    booked_intervals.append((s, e))

            slot_list = []
            for slot_time_str in slots:
                h, m = map(int, slot_time_str.split(":"))
                slot_dt = datetime(d.year, d.month, d.day, h, m)
                slot_end = slot_dt + timedelta(hours=1, minutes=30)  # min job duration

                # check off
                is_off = any(
                    s <= slot_dt < e or (s <= slot_end and slot_dt < e)
                    for s, e in off_intervals
                )
                if is_off:
                    slot_list.append({"time": slot_time_str, "status": "off", "subject": None})
                    continue

                # past slots (today only, before current time) — non-bookable
                slot_is_past = (d == actual_today and slot_dt < now_uk)

                # check booked — overlaps with any appointment
                booked_event = next(
                    (ev for s, e in booked_intervals
                     for ev in [{"s": s, "e": e}]
                     if s <= slot_dt <= e),
                    None,
                )
                # also check the 90-min window is clear
                window_clear = not any(
                    s < slot_end and e > slot_dt
                    for s, e in booked_intervals
                )

                # check if an appointment ended in the 30 min before this slot
                just_after_appt = any(
                    slot_dt - timedelta(minutes=30) <= e < slot_dt
                    for s, e in booked_intervals
                )

                if booked_event is not None:
                    # find the actual subject
                    subj = next(
                        (ev.get("subject") for ev in day_events
                         if not _is_time_off(ev)
                         and _parse_dt(ev, "start") is not None
                         and _parse_dt(ev, "start") <= slot_dt < (_parse_dt(ev, "end") or slot_dt)),
                        None,
                    )
                    slot_list.append({"time": slot_time_str, "status": "booked", "subject": subj})
                elif slot_is_past:
                    slot_list.append({"time": slot_time_str, "status": "past", "subject": None})
                elif not window_clear or just_after_appt:
                    slot_list.append({"time": slot_time_str, "status": "buffer", "subject": None})
                else:
                    slot_list.append({"time": slot_time_str, "status": "free", "subject": None})

            days_out[d.isoformat()] = slot_list

        result_reps.append({
            "name": rep,
            "regions": rep_regions,
            "is_fallback": is_fallback,
            "is_other": rep in other_reps,
            "is_freelancer": rep in FREELANCER_REPS,
            "today_count": today_count,
            "days": days_out,
        })

    return {
        "region": region or "All",
        "dates": [d.isoformat() for d in all_dates],
        "reps": result_reps,
    }


# ---------------------------------------------------------------------------
# Location resolvers
# ---------------------------------------------------------------------------

def region_from_postcode(postcode: str) -> str | None:
    """Return region for a UK postcode prefix. Accepts full or partial postcode."""
    clean = postcode.strip().upper().replace(" ", "")
    # pure letters = city name, not a postcode
    if not any(c.isdigit() for c in clean):
        return None
    # try longest prefix first (2 chars), then 1 char
    for length in (2, 1):
        prefix = "".join(c for c in clean[:length] if c.isalpha())
        if len(prefix) == length and prefix in POSTCODE_TO_REGION:
            return POSTCODE_TO_REGION[prefix]
    return None


def region_from_city(city: str) -> str | None:
    """Return region for a city name (case-insensitive)."""
    return CITY_TO_REGION.get(city.strip().lower())


def reps_for_region(region: str) -> list[str]:
    """Return regional reps for a region. Does not include fallback reps."""
    return [r for r, regions in REP_REGION.items() if region in regions]


def all_regions() -> list[str]:
    """Return sorted list of all distinct regions."""
    seen: set[str] = set()
    for regions in REP_REGION.values():
        seen.update(regions)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Rep diary (per-rep appointment history + upcoming)
# ---------------------------------------------------------------------------

def _split_subject(subject: str) -> tuple[str, str]:
    """Split a booking subject "POSTCODE - Customer Name" into (postcode, customer).

    Booking always writes this exact format (see app.py api_book). Falls back to
    ("", subject) for anything that doesn't match — banners, manually-created
    calendar entries, etc.
    """
    if " - " in subject:
        postcode, _, customer = subject.partition(" - ")
        return postcode.strip(), customer.strip()
    return "", subject.strip()


def build_rep_diary(events: list[dict]) -> dict:
    """Build a per-rep appointment list from a pre-fetched event set.

    Returns past + upcoming appointments grouped by rep, suitable for
    the /reps diary page (both the list view and the calendar view).
    """
    today = date.today()
    all_reps = list(REP_REGION.keys()) + FALLBACK_REPS

    rep_appts: dict[str, list[dict]] = {r: [] for r in all_reps}

    for event in events:
        if _is_time_off(event) or _is_banner(event):
            continue
        rep = _resolve_rep(event)
        if not rep or rep not in rep_appts:
            continue
        start_dt = _parse_dt(event, "start")
        end_dt   = _parse_dt(event, "end")
        if start_dt is None:
            continue
        subject = (event.get("subject") or "").strip()
        postcode, customer = _split_subject(subject)
        rep_appts[rep].append({
            "date":     start_dt.date().isoformat(),
            "start":    start_dt.strftime("%H:%M"),
            "end":      end_dt.strftime("%H:%M") if end_dt else "",
            "subject":  subject,
            "customer": customer,
            "postcode": postcode,
            "event_id": event.get("id", ""),
            "is_past":  start_dt.date() < today,
            "is_today": start_dt.date() == today,
        })

    result = []
    for rep in all_reps:
        appts = sorted(rep_appts[rep], key=lambda a: (a["date"], a["start"]))
        result.append({
            "name":         rep,
            "regions":      REP_REGION.get(rep, []),
            "is_fallback":  rep in FALLBACK_REPS,
            "is_freelancer": rep in FREELANCER_REPS,
            "appointments": appts,
        })

    return {"today": today.isoformat(), "reps": result}


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("Fetching events from Graph...")
    events = fetch_events(days=10)
    print(f"  {len(events)} events fetched")

    print("\nBuilding grid for Yorkshire & Humber...")
    grid = build_grid(events, region="Yorkshire & Humber", days=7)

    for rep in grid["reps"]:
        print(f"\n  {rep['name']} ({'fallback' if rep['is_fallback'] else ', '.join(rep['regions'])}) — {rep['today_count']} booked today")
        for day_str, slots in list(rep["days"].items())[:2]:
            free = [s["time"] for s in slots if s["status"] == "free"]
            booked = [s["time"] for s in slots if s["status"] == "booked"]
            off = [s["time"] for s in slots if s["status"] == "off"]
            print(f"    {day_str}: {len(free)} free  {len(booked)} booked  {len(off)} off")
            if free:
                print(f"      free slots: {free[:6]}")

    print("\nPostcode tests:")
    for pc, expected in [("LS1", "Yorkshire & Humber"), ("M1", "North West"), ("SW1A", "London"), ("CF10", "Wales")]:
        got = region_from_postcode(pc)
        print(f"  {pc:<8} → {got}  {'OK' if got == expected else 'MISMATCH'}")

    print("\nCity tests:")
    for city, expected in [("Sheffield", "Yorkshire & Humber"), ("Manchester", "North West"), ("Cardiff", "Wales")]:
        got = region_from_city(city)
        print(f"  {city:<15} → {got}  {'OK' if got == expected else 'MISMATCH'}")
