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
    fetch_events, build_grid, region_from_postcode,
    region_from_city, all_regions, reps_for_region,
)

app = Flask(__name__)
app.secret_key = os.environ.get("AVAILABILITY_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=8)

# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

_USERS_FILE = Path(__file__).parent / "users.json"


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


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/users")
@admin_required
def admin_users():
    users = [{"username": u["username"], "role": u["role"], "name": u["name"]} for u in _load_users()]
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role", "user")
    name = (request.form.get("name") or username).strip()

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
# CLI: hash a password (for initial setup)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(_hash_password(sys.argv[2]))
    else:
        app.run(debug=True, port=5050)
