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
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, abort,
)

# allow importing from repo root (calendar_analysis module)
sys.path.insert(0, str(Path(__file__).parent.parent))

from calendar_analysis.availability import (
    fetch_events, build_grid, build_rep_diary, region_from_postcode,
    region_from_city, all_regions, reps_for_region, REP_EMAIL,
    reload_reps,
)

app = Flask(__name__)
app.secret_key = os.environ.get("AVAILABILITY_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=8)

# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

_USERS_FILE = Path(__file__).parent / "users.json"
_REPS_FILE  = Path(__file__).parent.parent / "reps.json"

_KNOWN_REGIONS = [
    "North East", "Yorkshire & Humber", "North West",
    "London", "South East", "East of England", "South West",
    "Wales", "Scotland",
]


def _load_reps_json() -> list[dict]:
    if not _REPS_FILE.exists():
        return []
    return json.loads(_REPS_FILE.read_text(encoding="utf-8")).get("reps", [])


def _save_reps_json(reps: list[dict]) -> None:
    _REPS_FILE.write_text(json.dumps({"reps": reps}, indent=2), encoding="utf-8")
    reload_reps()


def _load_users() -> list[dict]:
    if not _USERS_FILE.exists():
        return []
    return json.loads(_USERS_FILE.read_text(encoding="utf-8")).get("users", [])


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


def _get_user(username: str) -> dict | None:
    return next((u for u in _load_users() if u["username"] == username), None)


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
_AVAIL_TTL = 300  # 5 min


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
            session["username"] = username
            session["role"] = user.get("role", "user")
            session["name"] = user.get("name", username)
            session["email"] = user.get("email", "")
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
        role=session.get("role"),
        user_email=session.get("email", ""),
        regions=all_regions(),
    )


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


@app.route("/api/book", methods=["POST"])
@login_required
def api_book():
    """Dry-run booking endpoint — builds the Graph payload but does NOT write to calendar."""
    data = request.get_json(silent=True) or {}
    rep_name   = (data.get("rep") or "").strip()
    date_iso   = (data.get("date") or "").strip()
    start_time = (data.get("start") or "").strip()
    end_time   = (data.get("end") or "").strip()
    customer   = (data.get("customer_name") or "").strip()
    postcode   = (data.get("postcode") or "").strip().upper()
    cust_email = (data.get("customer_email") or "").strip()
    cc_email   = (data.get("cc_email") or "").strip()
    notes      = (data.get("notes") or "").strip()
    teams      = bool(data.get("teams_meeting", False))

    if not all([rep_name, date_iso, start_time, end_time, customer, postcode]):
        return jsonify({"ok": False, "message": "Missing required fields (rep, date, start, end, customer_name, postcode)"}), 400

    rep_email = REP_EMAIL.get(rep_name)
    if not rep_email:
        return jsonify({"ok": False, "message": f"No email found for rep: {rep_name}"}), 400

    # Subject: "YO16 6XY - Susan Barber" — matching existing Outlook naming pattern
    subject = f"{postcode} - {customer}"

    # Category = rep's first name — drives the "Kelly" tag in Outlook and our attribution engine
    rep_first = rep_name.split()[0] if rep_name else ""

    # Booker = logged-in telesales person — auto-added, no form field needed
    booker_email = session.get("email", "").strip()
    booker_name  = session.get("name", "Telesales")

    attendees = []
    if booker_email:
        attendees.append({
            "emailAddress": {"address": booker_email, "name": booker_name},
            "type": "required",
        })
    attendees.append({
        "emailAddress": {"address": rep_email, "name": rep_name},
        "type": "required",
    })
    if cc_email:
        attendees.append({
            "emailAddress": {"address": cc_email, "name": cc_email},
            "type": "optional",
        })
    if cust_email:
        attendees.append({
            "emailAddress": {"address": cust_email, "name": customer},
            "type": "optional",
        })

    # Build full MS Graph event payload (for inspection — NOT sent to Graph yet)
    would_create = {
        "subject": subject,
        "categories": [rep_first] if rep_first else [],
        "start": {"dateTime": f"{date_iso}T{start_time}:00", "timeZone": "Europe/London"},
        "end":   {"dateTime": f"{date_iso}T{end_time}:00",   "timeZone": "Europe/London"},
        "attendees": attendees,
        "body": {"contentType": "Text", "content": notes},
        "showAs": "busy",
        "isOnlineMeeting": teams,
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 60,
    }
    if teams:
        would_create["onlineMeetingProvider"] = "teamsForBusiness"

    import json as _json
    app.logger.info("[DRY RUN] Would create Graph event:\n%s", _json.dumps(would_create, indent=2))

    booked_by = f" — booked by {booker_name}" if booker_email else ""
    message = (
        f"DRY RUN — would book {rep_name} on {date_iso} "
        f"{start_time}–{end_time} for {customer} ({postcode}){booked_by}"
    )
    return jsonify({
        "ok": True,
        "dry_run": True,
        "message": message,
        "would_create": would_create,
    })


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
    )


@app.route("/api/reps/diary")
@login_required
def api_rep_diary():
    days_back = min(int(request.args.get("days_back", 30)), 90)
    days_forward = 60  # fixed look-ahead
    key = f"diary:{days_back}"
    with _diary_lock:
        cached = _diary_cache.get(key)
        if cached and time.time() - cached["ts"] < _AVAIL_TTL:
            return jsonify(cached["data"])
    try:
        start = date.today() - timedelta(days=days_back)
        events = fetch_events(days=days_back + days_forward, start_date=start)
        data = build_rep_diary(events)
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
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/users")
@admin_required
def admin_users():
    users = [{"username": u["username"], "role": u["role"], "name": u["name"], "email": u.get("email", "")} for u in _load_users()]
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role", "user")
    name = (request.form.get("name") or username).strip()
    email = (request.form.get("email") or "").strip().lower()

    if not username or not password:
        abort(400)

    users = _load_users()
    if any(u["username"] == username for u in users):
        return redirect(url_for("admin_users"))

    users.append({
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "name": name,
        "email": email,
    })
    _USERS_FILE.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete/<username>", methods=["POST"])
@admin_required
def admin_delete_user(username: str):
    if username == session.get("username"):
        abort(400)  # can't delete yourself
    users = [u for u in _load_users() if u["username"] != username]
    _USERS_FILE.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Admin routes — reps
# ---------------------------------------------------------------------------

@app.route("/admin/reps")
@admin_required
def admin_reps():
    return render_template("admin_reps.html", reps=_load_reps_json(), all_regions=_KNOWN_REGIONS)


@app.route("/admin/reps/add", methods=["POST"])
@admin_required
def admin_add_rep():
    name     = (request.form.get("name") or "").strip()
    email    = (request.form.get("email") or "").strip().lower()
    regions  = request.form.getlist("regions")
    fallback = bool(request.form.get("fallback"))
    freelancer = bool(request.form.get("freelancer"))
    weekend_days = [int(d) for d in request.form.getlist("weekend_days")]
    aliases_raw  = (request.form.get("aliases") or "").strip()
    aliases = [a.strip().lower() for a in aliases_raw.split(",") if a.strip()]

    if not name or not email:
        abort(400)

    reps = _load_reps_json()
    if any(r["name"] == name for r in reps):
        return redirect(url_for("admin_reps"))

    reps.append({
        "name": name,
        "email": email,
        "regions": regions,
        "fallback": fallback,
        "freelancer": freelancer,
        "weekend_days": weekend_days,
        "aliases": aliases,
    })
    _save_reps_json(reps)
    return redirect(url_for("admin_reps"))


@app.route("/admin/reps/delete/<path:name>", methods=["POST"])
@admin_required
def admin_delete_rep(name: str):
    reps = [r for r in _load_reps_json() if r["name"] != name]
    _save_reps_json(reps)
    return redirect(url_for("admin_reps"))


# ---------------------------------------------------------------------------
# CLI: hash a password (for initial setup)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(_hash_password(sys.argv[2]))
    else:
        app.run(debug=True, port=5050)
