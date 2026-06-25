"""
Availability engine — derives per-rep free slots from the shared Outlook calendar.

Data source: MS Graph calendarView on info@trustelectricheating.co.uk
Rep attribution: attendee email (primary) → category (fallback)
Time-off detection: all-day events OR OOO keywords in subject, regardless of showAs flag
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Rep / region master data
# ---------------------------------------------------------------------------

# canonical_name → region(s)
REP_REGION: dict[str, list[str]] = {
    "Kelly Miller":      ["North East"],
    "Rob Chapman":       ["Yorkshire & Humber"],
    "Chris Krammer":     ["Yorkshire & Humber"],
    "Sam Chapman":       ["North West"],
    "Samantha Doyle":    ["North West"],
    "Kris Noorouzi":     ["London", "South East", "East of England"],
    "Chris Mannix":      ["London", "South East", "East of England"],
    "Niall Devanish":    ["South West"],
    "Paul Slade":        ["Wales"],
    "Chris Southworth":  ["South East"],
    "Chris Cash":        ["Yorkshire & Humber"],
    "Keith Wiggins":     ["Yorkshire & Humber"],
}

# Fallback reps — shown only when no regional rep is free
FALLBACK_REPS: list[str] = ["Scott Conor", "Josh Barron"]

# Freelance / Ambivo reps — shown in their region but badged separately
FREELANCER_REPS: set[str] = {"Chris Cash", "Keith Wiggins", "Chris Southworth"}

# Weekend working — rep → set of weekday numbers they work (5=Sat, 6=Sun)
# Add any rep here to enable weekend slots for them
WEEKEND_WORK: dict[str, set[int]] = {
    "Kris Noorouzi":    {5},        # Saturday only
    "Chris Southworth": {5, 6},     # Saturday and Sunday
}

# email local-part (before @) → canonical name  (Trust staff only)
EMAIL_TO_REP: dict[str, str] = {
    "kelly":       "Kelly Miller",
    "rob":         "Rob Chapman",
    "chrisk":      "Chris Krammer",
    "samchapman":  "Sam Chapman",
    "samantha":    "Samantha Doyle",
    "kris":        "Kris Noorouzi",
    "chrism":      "Chris Mannix",
    "niall":       "Niall Devanish",
    "paul":        "Paul Slade",
    "scott":       "Scott Conor",
    "josh":        "Josh Barron",
    # extras observed in diagnosis
    "samuel":      "Samantha Doyle",
    "merv":        "Merv",
    "victoria":    "Victoria",
    "gia":         "Gia",
    "paula":       "Paula",
}

# Full email for every rep — used for sending booking invites
REP_EMAIL: dict[str, str] = {
    "Kelly Miller":     "kelly@trustelectricheating.co.uk",
    "Rob Chapman":      "rob@trustelectricheating.co.uk",
    "Chris Krammer":    "chrisk@trustelectricheating.co.uk",
    "Sam Chapman":      "samchapman@trustelectricheating.co.uk",
    "Samantha Doyle":   "samantha@trustelectricheating.co.uk",
    "Kris Noorouzi":    "kris@trustelectricheating.co.uk",
    "Chris Mannix":     "chrism@trustelectricheating.co.uk",
    "Niall Devanish":   "niall@trustelectricheating.co.uk",
    "Paul Slade":       "paul@trustelectricheating.co.uk",
    "Scott Conor":      "scott@trustelectricheating.co.uk",
    "Josh Barron":      "josh@trustelectricheating.co.uk",
    # Freelancers — confirmed personal/business emails
    "Chris Cash":       "chris.cash@ambivo.co.uk",
    "Keith Wiggins":    "keith.wiggins1@ntlworld.com",
    "Chris Southworth": "chris@nautilussussex.com",
}

# category text (lowercase) → canonical name
CATEGORY_TO_REP: dict[str, str] = {
    "kelly":           "Kelly Miller",
    "rob":             "Rob Chapman",
    "kourosh":         "Kris Noorouzi",
    "kris":            "Kris Noorouzi",
    "chris m":         "Chris Mannix",
    "chris mannix":    "Chris Mannix",
    "sam":             "Sam Chapman",
    "sam chapman":     "Sam Chapman",
    "sammy":           "Samantha Doyle",
    "samuel":          "Samantha Doyle",
    "samantha doyle":  "Samantha Doyle",
    "niall devenish":  "Niall Devanish",
    "niall devanish":  "Niall Devanish",
    "niall":           "Niall Devanish",
    "paul slade":      "Paul Slade",
    "paul":            "Paul Slade",
    "chris southworth":"Chris Southworth",
    "chris s":         "Chris Southworth",
    "chris cash":      "Chris Cash",
    "keith":           "Keith Wiggins",
    "keith wiggins":   "Keith Wiggins",
    "scott conor":     "Scott Conor",
    "scott":           "Scott Conor",
    "josh":            "Josh Barron",
    "josh barron":     "Josh Barron",
}

GENERIC_EMAILS: set[str] = {
    "info@trustelectricheating.co.uk",
    "telesales@trustelectricheating.co.uk",
}

# Full email → rep for freelancers who don't have @trustelectricheating.co.uk addresses
FREELANCER_EMAIL_TO_REP: dict[str, str] = {
    "chris.cash@ambivo.co.uk":      "Chris Cash",
    "keith.wiggins1@ntlworld.com":  "Keith Wiggins",
    "chris@nautilussussex.com":     "Chris Southworth",
}

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
    # Wales
    "CF": "Wales", "SA": "Wales", "NP": "Wales",
    "LL": "Wales", "SY": "Wales", "LD": "Wales",
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
    # Wales
    "cardiff": "Wales", "swansea": "Wales", "newport": "Wales",
    "wrexham": "Wales", "bangor": "Wales", "aberystwyth": "Wales",
    "caerphilly": "Wales", "merthyr tydfil": "Wales",
    "bridgend": "Wales", "neath": "Wales",
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


def _is_time_off(event: dict) -> bool:
    if event.get("isAllDay"):
        return True
    subject = event.get("subject") or ""
    return bool(_OOO_RE.search(subject))


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
    end = datetime(d.year, d.month, d.day, 17, 0)
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
    from_date = start_date if start_date else actual_today
    # build date list from from_date — include all 7 days so weekend-working
    # reps (Kris=Sat, Chris Southworth=Sat+Sun) get their slots shown
    all_dates: list[date] = []
    d = from_date
    while len([x for x in all_dates if x.weekday() < 5]) < days:
        all_dates.append(d)
        d += timedelta(days=1)

    # determine which reps to include
    if region:
        regional_reps = [r for r, regions in REP_REGION.items() if region in regions]
    else:
        regional_reps = list(REP_REGION.keys())

    # classify events per rep per day
    rep_events: dict[str, dict[date, list[dict]]] = {r: {} for r in regional_reps + FALLBACK_REPS}
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

    all_output_reps = regional_reps + FALLBACK_REPS
    for rep in all_output_reps:
        rep_regions = REP_REGION.get(rep, ["Any"])
        is_fallback = rep in FALLBACK_REPS
        today_count = len([
            e for e in rep_events.get(rep, {}).get(actual_today, [])
            if not _is_time_off(e)
        ])

        days_out: dict[str, list[dict]] = {}
        for d in all_dates:
            slots = _slots_for_day(d, rep)
            if not slots:
                continue
            day_events = rep_events.get(rep, {}).get(d, [])

            # build booked/off intervals
            booked_intervals: list[tuple[datetime, datetime]] = []
            off_intervals: list[tuple[datetime, datetime]] = []

            for event in day_events:
                s = _parse_dt(event, "start")
                e = _parse_dt(event, "end")
                if s is None or e is None:
                    continue
                if _is_time_off(event):
                    # all-day: block entire day
                    if event.get("isAllDay"):
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
                elif not window_clear:
                    # slot itself is free but 90-min window is blocked — mark as booked
                    slot_list.append({"time": slot_time_str, "status": "booked", "subject": None})
                else:
                    slot_list.append({"time": slot_time_str, "status": "free", "subject": None})

            days_out[d.isoformat()] = slot_list

        result_reps.append({
            "name": rep,
            "regions": rep_regions,
            "is_fallback": is_fallback,
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
