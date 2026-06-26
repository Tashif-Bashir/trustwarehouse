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

sys.path.insert(0, str(Path(__file__).parent.parent))

from calendar_analysis.availability import (
    fetch_events, build_grid, build_rep_diary, region_from_postcode,
    region_from_city, all_regions, reps_for_region, REP_EMAIL,
    reload_reps, get_graph_token, CALENDAR_MAILBOX,
)

app = Flask(__name__)
app.secret_key = os.environ.get("AVAILABILITY_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=8)

# ---------------------------------------------------------------------------
# BigQuery / GCS
# ---------------------------------------------------------------------------

from google.cloud import bigquery, storage

BQ_PROJECT = os.environ.get("BIGQUERY_PROJECT", "trustwarehouse")
BQ_USERS   = f"`{BQ_PROJECT}.app.users`"
BQ_REPS    = f"`{BQ_PROJECT}.app.reps`"
GCS_BUCKET = os.environ.get("GCS_AVATAR_BUCKET", "trustwarehouse-avatars")

_bq_client: bigquery.Client | None = None
_gcs_client: storage.Client | None = None


def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


def _gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=BQ_PROJECT)
    return _gcs_client


# ---------------------------------------------------------------------------
# Reps store (BigQuery-backed)
# ---------------------------------------------------------------------------

_KNOWN_REGIONS = [
    "North East", "Yorkshire & Humber", "North West",
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
    }


def _get_all_reps() -> list[dict]:
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_REPS} ORDER BY created_at"
    ).result())
    return [_row_to_rep(r) for r in rows]


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
        f"SELECT username, name, email, role, photo_url FROM {BQ_USERS} ORDER BY created_at"
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

    if not all([rep_name, date_iso, start_time, end_time, customer, postcode]):
        return jsonify({"ok": False, "message": "Missing required fields"}), 400

    rep_email = REP_EMAIL.get(rep_name)
    if not rep_email:
        return jsonify({"ok": False, "message": f"No email found for rep: {rep_name}"}), 400

    subject  = f"{postcode} - {customer}"
    rep_first = rep_name.split()[0] if rep_name else ""

    booker_email = session.get("email", "").strip()
    booker_name  = session.get("name", "Telesales")

    _TELESALES = "telesales@trustelectricheating.co.uk"

    attendees = []
    if booker_email and booker_email.lower() != _TELESALES:
        attendees.append({
            "emailAddress": {"address": booker_email, "name": booker_name},
            "type": "required",
        })
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
    if cust_email:
        attendees.append({
            "emailAddress": {"address": cust_email, "name": customer},
            "type": "optional",
        })

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

        with _avail_lock:
            _avail_cache.clear()
        with _diary_lock:
            _diary_cache.clear()

        booked_by = f" — booked by {booker_name}" if booker_email else ""
        message = (
            f"Booked: {rep_name} · {date_iso} · {start_time}–{end_time} "
            f"· {customer} ({postcode}){booked_by}"
        )
        return jsonify({"ok": True, "dry_run": False, "message": message})

    except Exception as ex:
        app.logger.exception("Booking request failed")
        return jsonify({"ok": False, "message": f"Booking failed: {ex}"}), 500


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
    days_back = min(int(request.args.get("days_back", 30)), 90)
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
    return render_template("admin_users.html", users=users)


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
