"""Trust Sales — sales-logging internal webapp (Flask, session auth).

One row per sale event in BigQuery `app.sales`; the CRM lead's Sold Amount
fields are maintained as lifetime totals derived from those rows.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify,
)
from google.cloud import bigquery

app = Flask(__name__)
app.secret_key = os.environ.get("SALES_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=10)

# Internal tool: keep it out of search engines. noindex stops Google listing
# it; it does NOT make the app private - that is what the login is for.
@app.after_request
def _noindex(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


@app.route("/robots.txt")
def _robots():
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"}


# ---------------------------------------------------------------------------
# Config / BigQuery
# ---------------------------------------------------------------------------

BQ_PROJECT = (os.environ.get("BIGQUERY_PROJECT") or "trustwarehouse").strip().lstrip("\ufeff")
BQ_USERS = f"`{BQ_PROJECT}.app.sales_users`"   # the sales app's OWN logins
BQ_REPS = f"`{BQ_PROJECT}.app.reps`"
BQ_SALES = f"`{BQ_PROJECT}.app.sales`"
BQ_LEADS = f"`{BQ_PROJECT}.silver.silver_sharpspring_leads`"
BQ_TARGETS = f"`{BQ_PROJECT}.app.targets`"

# Who may set the monthly revenue target (owner decision 5 Aug 2026): the two
# internal sellers plus admins. Everyone else sees it read-only.
TARGET_EDITORS = ("dec", "josh")

_bq_client: bigquery.Client | None = None

# .env fallback for local dev (Vercel uses real env vars)
_DOTENV: dict[str, str] = {}
_dotenv_path = Path(__file__).parent.parent / ".env"
if _dotenv_path.exists():
    for _line in _dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _DOTENV[_k.strip()] = _v.strip().strip('"').strip("'")


def _cfg(key: str) -> str:
    # strip whitespace and any BOM — env values set via shell pipes can carry both
    return (os.environ.get(key) or _DOTENV.get(key, "")).strip().lstrip("\ufeff")


def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        creds = None
        raw = _cfg("GOOGLE_CREDENTIALS_JSON")
        if raw:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                json.loads(raw.lstrip("\ufeff")),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        _bq_client = bigquery.Client(project=BQ_PROJECT, credentials=creds)
    return _bq_client


def _bq_params(**kv) -> bigquery.QueryJobConfig:
    type_map = {str: "STRING", int: "INT64", float: "FLOAT64", bool: "BOOL"}
    params = []
    for name, val in kv.items():
        if name.endswith("_ts"):
            params.append(bigquery.ScalarQueryParameter(name, "TIMESTAMP", val))
        elif name.endswith("_date"):
            params.append(bigquery.ScalarQueryParameter(name, "DATE", val))
        else:
            params.append(bigquery.ScalarQueryParameter(name, type_map.get(type(val), "STRING"), val))
    return bigquery.QueryJobConfig(query_parameters=params)


# ---------------------------------------------------------------------------
# Auth (shared app.users, same hashing as the booking app)
# ---------------------------------------------------------------------------

def _get_user(username: str) -> dict | None:
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_USERS} WHERE username = @u LIMIT 1",
        job_config=_bq_params(u=username),
    ).result())
    return {k: rows[0][k] for k in rows[0].keys()} if rows else None


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"pbkdf2:sha256:{salt}:{h.hex()}"


def _check_password(stored_hash: str, provided: str) -> bool:
    parts = stored_hash.split(":", 3)
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False
    _, algo, salt, expected = parts
    actual = hashlib.pbkdf2_hmac(algo, provided.encode(), salt.encode(), 260000)
    return hmac.compare_digest(actual.hex(), expected)


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not logged in"}), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "admin only"}), 403
        return f(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = _get_user(username)
        if user and _check_password(user["password_hash"], password):
            session.permanent = True
            session["username"] = username
            session["name"] = user.get("name") or username
            session["role"] = user.get("role") or "user"
            return redirect(request.args.get("next") or url_for("index"))
        error = "Incorrect username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# SharpSpring write-back
# ---------------------------------------------------------------------------

_SS_BASE_URL = "https://api.sharpspring.com/pubapi/v1.2/"
F_SOLD_HEAT = "sold_amount_heating______6a60e957e3fe7"
F_SOLD_WATER = "sold_amount_water______6a60e96c2f317"
F_SOLD_CHC = "sold_amount_chc______6a6207ad9f645"
F_APPT_STATUS = "appointment_status_637f8d6fa1096"        # Appointment Status Heating
F_APPT_STATUS_WATER = "appointment_status__1__6a0f083987d2c"  # Appointment Status WATER
F_SOLD_BY = "product_bought__1__6969069edaaef"            # "Sold by" picklist (Dec/Josh)

OFFICE_SELLERS = ("Dec", "Josh")   # matches the CRM "Sold by" picklist values

# Sale types. 'on_site' and 'sold' are the SAME sale by the same field rep and
# count toward the same target — the only difference is when it closed: on the
# doorstep at the appointment, or on a callback afterwards. Both therefore
# reassign the lead to the rep. 'office' is Dec/Josh, 'chc' is an online
# purchase with no seller.
SALE_TYPES = ("on_site", "sold", "office", "chc")
REP_SALE_TYPES = ("on_site", "sold")          # closed by a field rep
STATUS_SALE_TYPES = ("on_site", "sold", "office")  # write an appointment status
CRM_STATUS_FOR_TYPE = {
    "on_site": "sold on site",
    "sold": "sold",
    "office": "sold in office",
}


def _ss_call(method: str, params: dict, retries: int = 3):
    for attempt in range(retries):
        r = requests.post(
            _SS_BASE_URL,
            params={"accountID": _cfg("SHARPSPRING_ACCOUNT_ID"),
                    "secretKey": _cfg("SHARPSPRING_SECRET_KEY")},
            json={"method": method, "params": params, "id": secrets.token_hex(8)},
            timeout=30,
        )
        try:
            j = r.json()
        except ValueError:
            time.sleep(1.5 ** attempt)
            continue
        if j.get("error"):
            raise RuntimeError(f"{method}: {j['error']}")
        return j["result"]
    raise RuntimeError(f"{method}: no JSON after retries")


_status_options_cache: dict = {"ts": 0.0, "options": []}


def _status_picklist_value(sale_type: str) -> str:
    """Return the EXACT picklist casing the CRM uses for this sale type."""
    want = CRM_STATUS_FOR_TYPE[sale_type]
    now = time.time()
    if not _status_options_cache["options"] or now - _status_options_cache["ts"] > 86400:
        try:
            fields = []
            offset = 0
            while True:
                res = _ss_call("getFields", {"where": {}, "limit": 500, "offset": offset})
                batch = res.get("field", [])
                fields.extend(batch)
                if len(batch) < 500:
                    break
                offset += 500
            for f in fields:
                if f.get("systemName") == F_APPT_STATUS:
                    opts = f.get("picklistOptions") or f.get("options") or []
                    vals = []
                    for o in opts:
                        if isinstance(o, dict):
                            vals.append(o.get("value") or o.get("label") or "")
                        else:
                            vals.append(str(o))
                    _status_options_cache.update(ts=now, options=[v for v in vals if v])
                    break
        except Exception:
            app.logger.exception("getFields for status options failed")
    for opt in _status_options_cache["options"]:
        if opt.strip().lower() == want:
            return opt
    # fall back to title-ish casing used in the CRM UI
    return {"on_site": "Sold on Site", "sold": "Sold",
            "office": "Sold in Office"}[sale_type]


def _lifetime_totals(lead_id: str) -> tuple[float, float, float]:
    rows = list(_bq().query(f"""
        SELECT ROUND(SUM(COALESCE(heating_amount, 0)), 2) AS h,
               ROUND(SUM(COALESCE(water_amount, 0)), 2) AS w,
               ROUND(SUM(COALESCE(chc_amount, 0)), 2) AS c
        FROM {BQ_SALES}
        WHERE lead_id = @lid AND status = 'active'
    """, job_config=_bq_params(lid=lead_id)).result())
    r = rows[0]
    return float(r["h"] or 0), float(r["w"] or 0), float(r["c"] or 0)


def _fmt_amount(x: float) -> str:
    return "" if not x else (str(int(x)) if x == int(x) else f"{x:.2f}")


def _crm_writeback(lead_id: str, sale_type: str, sold_by: str | None,
                   add_h: float = 0, add_w: float = 0, add_c: float = 0,
                   rep_owner: str = "") -> None:
    """Update the lead: lifetime sold amounts + statuses + attribution.

    On-site sales REASSIGN the lead to the selling rep (SOS ⇒ sale goes in the
    owner's name) and clear the Dec/Josh 'Sold by' field; office sales keep the
    owner and set 'Sold by'. add_* are amounts of a sale not yet inserted.
    """
    lead = _ss_call("getLeads", {"where": {"id": lead_id}})["lead"][0]
    owner = lead.get("ownerID")
    h, w, c = _lifetime_totals(lead_id)
    h, w, c = round(h + add_h, 2), round(w + add_w, 2), round(c + add_c, 2)
    obj: dict = {"id": lead_id}
    if sale_type in REP_SALE_TYPES and rep_owner:
        obj["ownerID"] = rep_owner            # reassign to the selling rep
    elif owner:
        obj["ownerID"] = owner                # echo (never omit — reassignment trap)
    if h:
        obj[F_SOLD_HEAT] = _fmt_amount(h)
    if w:
        obj[F_SOLD_WATER] = _fmt_amount(w)
    if c:
        obj[F_SOLD_CHC] = _fmt_amount(c)
    if sale_type in STATUS_SALE_TYPES:
        status_val = _status_picklist_value(sale_type)
        # statuses follow the sale's components: heating amount → heating status,
        # water amount → WATER status
        if add_h:
            obj[F_APPT_STATUS] = status_val
        if add_w:
            obj[F_APPT_STATUS_WATER] = status_val
    if sale_type == "office" and sold_by in OFFICE_SELLERS:
        obj[F_SOLD_BY] = sold_by
    if sale_type in REP_SALE_TYPES:
        obj[F_SOLD_BY] = ""                   # Dec/Josh field is office-only
    _ss_call("updateLeads", {"objects": [obj]})


def _rep_owner_id(name: str | None) -> str:
    """SharpSpring owner id for a rep name from app.reps ('' if unknown)."""
    if not name:
        return ""
    rows = list(_bq().query(
        f"SELECT sharpspring_owner_id FROM {BQ_REPS} WHERE name = @n LIMIT 1",
        job_config=_bq_params(n=name)).result())
    return (rows[0]["sharpspring_owner_id"] or "") if rows else ""


def _crm_note(lead_id: str, text: str, author_owner_id: str | None = None) -> None:
    """Drop a note in the lead's activity feed. SharpSpring REQUIRES authorID —
    fall back to the lead's owner when no rep author is known."""
    author = author_owner_id
    if not author:
        lead = _ss_call("getLeads", {"where": {"id": lead_id}})["lead"][0]
        author = lead.get("ownerID")
    if not author:
        raise RuntimeError("no authorID available for CRM note")
    _ss_call("createNotes", {"objects": [
        {"whoID": str(lead_id), "whoType": "lead", "note": text,
         "authorID": str(author)}]})


def _sale_note_text(sale_type: str, heating, water, chc, sold_by,
                    sale_date: str, user_note: str, entered_by: str) -> str:
    def gbp(x):
        return "£" + (f"{x:,.2f}".rstrip("0").rstrip(".") if x != int(x) else f"{int(x):,}")

    if sale_type == "chc":
        amounts = f"{gbp(chc)} CHC (online)"
    else:
        parts = []
        if heating:
            parts.append(f"{gbp(heating)} heating")
        if water:
            parts.append(f"{gbp(water)} water")
        amounts = " + ".join(parts)
    where = {"on_site": "Sold on Site", "sold": "Sold (callback after appointment)",
             "office": "Sold in Office", "chc": "CHC online purchase"}[sale_type]
    line = f"💰 Sale logged: {amounts} — {where}"
    if sold_by:
        line += f" by {sold_by}"
    line += f" — {sale_date}"
    if user_note:
        line += f'\n"{user_note}"'
    line += f"\n(entered by {entered_by} via Trust Sales)"
    return line


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return render_template(
        "sales.html",
        username=session.get("name", ""),
        login_username=session.get("username", ""),
        role=session.get("role", "user"),
        can_edit_target=_can_edit_target(),
    )


@app.route("/health")
def health():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Monthly revenue target (whole domestic: heating + water + CHC, all types).
# The wallboard reads app.targets directly; changing it here is live on the
# wall within its 15s cache.
# ---------------------------------------------------------------------------

def _can_edit_target() -> bool:
    return (session.get("role") == "admin"
            or session.get("username") in TARGET_EDITORS)


@app.route("/api/target", methods=["GET"])
@login_required
def api_target_get():
    """Current month's target plus recent months, newest first."""
    rows = list(_bq().query(f"""
        SELECT CAST(month AS STRING) AS month, target_gbp, set_by,
               CAST(updated_at AS STRING) AS updated_at
        FROM {BQ_TARGETS}
        ORDER BY month DESC
        LIMIT 12
    """).result())
    months = [{k: r[k] for k in r.keys()} for r in rows]
    this_month = date.today().replace(day=1).isoformat()
    current = next((m for m in months if m["month"] == this_month), None)
    return jsonify({
        "current": current,
        "months": months,
        "can_edit": _can_edit_target(),
    })


@app.route("/api/target", methods=["POST"])
@login_required
def api_target_set():
    """Set (or replace) one month's target. Editors only."""
    if not _can_edit_target():
        return jsonify({"error": "only Dec, Josh or an admin can set the target"}), 403
    d = request.get_json(silent=True) or {}
    month_raw = str(d.get("month") or "").strip()
    try:
        month = date.fromisoformat(month_raw).replace(day=1)
    except ValueError:
        return jsonify({"error": "month must be YYYY-MM-DD"}), 400
    try:
        target = float(d.get("target_gbp"))
    except (TypeError, ValueError):
        return jsonify({"error": "target_gbp must be a number"}), 400
    if not 0 < target < 10_000_000:
        return jsonify({"error": "target looks wrong — expected between £0 and £10m"}), 400

    # one row per month, latest write wins, with who/when kept for traceability
    _bq().query(f"""
        MERGE {BQ_TARGETS} t
        USING (SELECT @m_date AS month) s ON t.month = s.month
        WHEN MATCHED THEN UPDATE SET
          target_gbp = @amount, set_by = @who, updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (month, target_gbp, set_by, updated_at)
          VALUES (@m_date, @amount, @who, CURRENT_TIMESTAMP())
    """, job_config=_bq_params(
        m_date=month, amount=target, who=session.get("username", ""),
    )).result()
    return jsonify({"ok": True, "month": month.isoformat(), "target_gbp": target})


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/reps")
@login_required
def api_reps():
    """Field reps for the 'sold by' picker (from the booking app's reps table)."""
    rows = list(_bq().query(
        f"SELECT name, sharpspring_owner_id FROM {BQ_REPS} ORDER BY name"
    ).result())
    return jsonify({
        "reps": [{"name": r["name"], "owner_id": r["sharpspring_owner_id"] or ""}
                 for r in rows],
        "office": list(OFFICE_SELLERS),
    })


@app.route("/api/leads/search")
@login_required
def api_lead_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"results": []})
    digits = "".join(ch for ch in q if ch.isdigit())
    like = f"%{q.lower()}%"
    phone_like = f"%{digits[-9:]}%" if len(digits) >= 6 else ""
    rows = list(_bq().query(f"""
        SELECT lead_id, first_name, last_name, email, phone, mobile, postcode, city,
               SAFE_CAST(appointment_date AS DATE) AS appt_date,
               appointment_status, owner_id,
               DATE(SAFE_CAST(created_at AS TIMESTAMP)) AS created
        FROM {BQ_LEADS}
        WHERE LOWER(CONCAT(IFNULL(first_name, ''), ' ', IFNULL(last_name, ''))) LIKE @like
           OR LOWER(IFNULL(email, '')) LIKE @like
           OR (LOWER(IFNULL(postcode, '')) = LOWER(@q))
           OR (@phone_like != '' AND (IFNULL(phone, '') LIKE @phone_like
                                      OR IFNULL(mobile, '') LIKE @phone_like))
        ORDER BY created DESC
        LIMIT 8
    """, job_config=_bq_params(like=like, q=q, phone_like=phone_like)).result())
    return jsonify({"results": [{
        "lead_id": r["lead_id"],
        "name": f"{r['first_name'] or ''} {r['last_name'] or ''}".strip(),
        "email": r["email"] or "",
        "phone": r["phone"] or r["mobile"] or "",
        "postcode": r["postcode"] or "",
        "city": r["city"] or "",
        "appt_date": r["appt_date"].isoformat() if r["appt_date"] else "",
        "appt_status": r["appointment_status"] or "",
        "created": r["created"].isoformat() if r["created"] else "",
    } for r in rows]})


@app.route("/api/leads/<lead_id>/history")
@login_required
def api_lead_history(lead_id: str):
    rows = list(_bq().query(f"""
        SELECT sale_date, sale_type, heating_amount, water_amount, chc_amount,
               sold_by, status
        FROM {BQ_SALES}
        WHERE lead_id = @lid
        ORDER BY sale_date DESC
        LIMIT 20
    """, job_config=_bq_params(lid=lead_id)).result())
    sales = [{
        "sale_date": r["sale_date"].isoformat(),
        "sale_type": r["sale_type"],
        "heating": r["heating_amount"], "water": r["water_amount"],
        "chc": r["chc_amount"], "sold_by": r["sold_by"], "status": r["status"],
    } for r in rows]
    active = [s for s in sales if s["status"] == "active"]
    lifetime = round(sum((s["heating"] or 0) + (s["water"] or 0) + (s["chc"] or 0)
                         for s in active), 2)
    return jsonify({"sales": sales, "lifetime": lifetime, "count": len(active)})


@app.route("/api/sales", methods=["POST"])
@login_required
def api_create_sale():
    d = request.get_json(force=True, silent=True) or {}
    sale_type = d.get("sale_type") or ""
    if sale_type not in SALE_TYPES:
        return jsonify({"error": "bad sale_type"}), 400

    try:
        sale_date = date.fromisoformat(str(d.get("sale_date") or ""))
    except ValueError:
        return jsonify({"error": "bad sale_date"}), 400
    today = datetime.now(timezone.utc).date()
    if sale_date > today or sale_date < today - timedelta(days=90):
        return jsonify({"error": "sale_date out of range"}), 400

    def _num(x):
        try:
            v = round(float(x), 2)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    heating = _num(d.get("heating_amount"))
    water = _num(d.get("water_amount"))
    chc = _num(d.get("chc_amount"))
    if sale_type == "chc":
        heating = water = None
        if not chc:
            return jsonify({"error": "CHC sale needs an amount"}), 400
    else:
        chc = None
        if not heating and not water:
            return jsonify({"error": "enter a heating and/or water amount"}), 400

    sold_by = (d.get("sold_by") or "").strip() or None
    if sale_type == "office" and sold_by not in OFFICE_SELLERS:
        return jsonify({"error": "office sales must be sold by Dec or Josh"}), 400
    if sale_type in REP_SALE_TYPES and not sold_by:
        return jsonify({"error": "pick the rep who sold it"}), 400
    if sale_type == "chc":
        sold_by = None

    lead_id = (str(d.get("lead_id") or "").strip()) or None
    customer_name = (d.get("customer_name") or "").strip()
    if not customer_name:
        return jsonify({"error": "customer name required"}), 400

    # CRM first (with the new amounts as deltas), then a DML insert carrying the
    # final sync flag — DML rows are immediately updatable (voids work right away),
    # unlike streaming-buffer rows.
    rep_owner = _rep_owner_id(sold_by) if sale_type in REP_SALE_TYPES else ""

    crm_ok = False
    crm_error = ""
    if lead_id:
        try:
            _crm_writeback(lead_id, sale_type, sold_by,
                           add_h=heating or 0, add_w=water or 0, add_c=chc or 0,
                           rep_owner=rep_owner)
            crm_ok = True
        except Exception as exc:
            app.logger.exception("CRM writeback failed")
            crm_error = str(exc)[:200]
        try:
            _crm_note(
                lead_id,
                _sale_note_text(sale_type, heating, water, chc, sold_by,
                                sale_date.isoformat(), (d.get("note") or "").strip(),
                                session.get("name") or session.get("username") or "?"),
                author_owner_id=rep_owner or None,
            )
        except Exception:
            app.logger.exception("CRM note failed (non-fatal)")

    now = datetime.now(timezone.utc)
    sale_id = str(uuid.uuid4())
    try:
        _bq().query(f"""
            INSERT INTO {BQ_SALES}
            (sale_id, lead_id, customer_name, postcode, sale_date, sale_type,
             heating_amount, water_amount, chc_amount, sold_by, sold_by_owner_id,
             product_bought, note, source, status, crm_synced, entered_by, created_at)
            VALUES
            (@sid, @lid, @cname, @pcode, @s_date, @stype,
             @heat, @wat, @chc, @sold_by, @sb_oid,
             @product, @note, 'app', 'active', @synced, @entered, @now_ts)
        """, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sid", "STRING", sale_id),
            bigquery.ScalarQueryParameter("lid", "STRING", lead_id),
            bigquery.ScalarQueryParameter("cname", "STRING", customer_name),
            bigquery.ScalarQueryParameter("pcode", "STRING",
                                          (d.get("postcode") or "").strip() or None),
            bigquery.ScalarQueryParameter("s_date", "DATE", sale_date.isoformat()),
            bigquery.ScalarQueryParameter("stype", "STRING", sale_type),
            bigquery.ScalarQueryParameter("heat", "FLOAT64", heating),
            bigquery.ScalarQueryParameter("wat", "FLOAT64", water),
            bigquery.ScalarQueryParameter("chc", "FLOAT64", chc),
            bigquery.ScalarQueryParameter("sold_by", "STRING", sold_by),
            bigquery.ScalarQueryParameter("sb_oid", "STRING",
                                          rep_owner
                                          or (d.get("sold_by_owner_id") or "").strip()
                                          or None),
            bigquery.ScalarQueryParameter("product", "STRING",
                                          (d.get("product_bought") or "").strip() or None),
            bigquery.ScalarQueryParameter("note", "STRING",
                                          (d.get("note") or "").strip()
                                          or (None if lead_id else "review: no CRM lead matched")),
            bigquery.ScalarQueryParameter("synced", "BOOL", crm_ok),
            bigquery.ScalarQueryParameter("entered", "STRING", session.get("username")),
            bigquery.ScalarQueryParameter("now_ts", "TIMESTAMP", now.isoformat()),
        ])).result()
    except Exception:
        app.logger.exception("sales insert failed")
        return jsonify({"error": "could not save the sale"}), 500

    return jsonify({"ok": True, "sale_id": sale_id,
                    "crm_synced": crm_ok, "crm_error": crm_error})


@app.route("/api/sales")
@login_required
def api_list_sales():
    month = (request.args.get("month") or "").strip()   # YYYY-MM
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        start = date.today().replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)

    rows = list(_bq().query(f"""
        SELECT sale_id, lead_id, customer_name, postcode, sale_date, sale_type,
               heating_amount, water_amount, chc_amount, sold_by, sold_by_owner_id,
               entered_by, status, void_reason, cancel_reason, crm_synced, source, note
        FROM {BQ_SALES}
        WHERE sale_date >= @s_date AND sale_date < @e_date
        ORDER BY sale_date DESC, created_at DESC
    """, job_config=_bq_params(s_date=start.isoformat(),
                               e_date=end.isoformat())).result())
    sales = [{k: (v.isoformat() if isinstance(v, date) else v)
              for k, v in dict(r).items()} for r in rows]
    active = [s for s in sales if s["status"] == "active"]
    total = round(sum((s["heating_amount"] or 0) + (s["water_amount"] or 0)
                      + (s["chc_amount"] or 0) for s in active), 2)
    return jsonify({"month": start.strftime("%Y-%m"), "sales": sales,
                    "total": total, "count": len(active)})


def _get_sale(sale_id: str) -> dict | None:
    rows = list(_bq().query(
        f"SELECT * FROM {BQ_SALES} WHERE sale_id = @sid",
        job_config=_bq_params(sid=sale_id)).result())
    return {k: rows[0][k] for k in rows[0].keys()} if rows else None


def _refresh_crm_totals(lead_id: str, sale_type: str | None = None,
                        heating: float | None = None, water: float | None = None,
                        sold_by: str | None = None, rep_owner: str = "") -> None:
    """Recompute lifetime totals from active rows and push to the lead.

    When sale_type is given (edits): statuses mirror the edited sale's
    components, on-site reassigns the lead to the rep + clears 'Sold by',
    office sets 'Sold by'.
    """
    lead = _ss_call("getLeads", {"where": {"id": lead_id}})["lead"][0]
    owner = lead.get("ownerID")
    h, w, c = _lifetime_totals(lead_id)
    obj = {"id": lead_id, F_SOLD_HEAT: _fmt_amount(h),
           F_SOLD_WATER: _fmt_amount(w), F_SOLD_CHC: _fmt_amount(c)}
    if sale_type in REP_SALE_TYPES and rep_owner:
        obj["ownerID"] = rep_owner
    elif owner:
        obj["ownerID"] = owner

    # Statuses mirror the amounts: a component whose active total is zero loses
    # its sold status (only sold-ish values are cleared — a manually set
    # 'follow up' etc. is left alone).
    sold_vals = {"sold", "sold on site", "sold in office", "chc sold"}
    if h <= 0 and str(lead.get(F_APPT_STATUS) or "").strip().lower() in sold_vals:
        obj[F_APPT_STATUS] = ""
    if w <= 0 and str(lead.get(F_APPT_STATUS_WATER) or "").strip().lower() in sold_vals:
        obj[F_APPT_STATUS_WATER] = ""

    if sale_type in STATUS_SALE_TYPES:
        status_val = _status_picklist_value(sale_type)
        if heating:
            obj[F_APPT_STATUS] = status_val
        if water:
            obj[F_APPT_STATUS_WATER] = status_val
        if sale_type == "office" and sold_by in OFFICE_SELLERS:
            obj[F_SOLD_BY] = sold_by
        if sale_type in REP_SALE_TYPES:
            obj[F_SOLD_BY] = ""
    _ss_call("updateLeads", {"objects": [obj]})


def _audit(sale_id: str, action: str, before: dict, after: dict) -> None:
    def scrub(d):
        return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                for k, v in d.items()}
    _bq().query(f"""
        INSERT INTO `{BQ_PROJECT}.app.sales_audit`
        (audit_id, sale_id, action, changed_by, changed_at, before_json, after_json)
        VALUES (@aid, @sid, @action, @by, @now_ts, @before, @after)
    """, job_config=_bq_params(aid=str(uuid.uuid4()), sid=sale_id, action=action,
                               by=session.get("username") or "?",
                               now_ts=datetime.now(timezone.utc).isoformat(),
                               before=json.dumps(scrub(before)),
                               after=json.dumps(scrub(after)))).result()


@app.route("/api/sales/<sale_id>/cancel", methods=["POST"])
@login_required
def api_cancel_sale(sale_id: str):
    d = request.get_json(force=True, silent=True) or {}
    reason = (d.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "a reason is required"}), 400
    sale = _get_sale(sale_id)
    if not sale:
        return jsonify({"error": "not found"}), 404
    if sale["status"] != "active":
        return jsonify({"error": f"sale is already {sale['status']}"}), 400

    now = datetime.now(timezone.utc)
    _bq().query(f"""
        UPDATE {BQ_SALES}
        SET status = 'cancelled', cancel_reason = @reason, updated_at = @now_ts
        WHERE sale_id = @sid
    """, job_config=_bq_params(sid=sale_id,
                               reason=f"{reason} (by {session.get('username')})",
                               now_ts=now.isoformat())).result()
    _audit(sale_id, "cancel", {"status": "active"},
           {"status": "cancelled", "reason": reason})

    if sale["lead_id"]:
        amt = (sale["heating_amount"] or 0) + (sale["water_amount"] or 0) + (sale["chc_amount"] or 0)
        try:
            _refresh_crm_totals(sale["lead_id"])
            _crm_note(sale["lead_id"],
                      f"❌ Order cancelled — £{amt:,.2f} removed from sold amounts"
                      f'\n"{reason}"'
                      f"\n(by {session.get('name') or session.get('username')} via Trust Sales)",
                      author_owner_id=sale.get("sold_by_owner_id"))
        except Exception:
            app.logger.exception("CRM update after cancel failed")
    return jsonify({"ok": True})


@app.route("/api/sales/<sale_id>/edit", methods=["POST"])
@login_required
def api_edit_sale(sale_id: str):
    d = request.get_json(force=True, silent=True) or {}
    sale = _get_sale(sale_id)
    if not sale:
        return jsonify({"error": "not found"}), 404
    if sale["status"] != "active":
        return jsonify({"error": f"can't edit a {sale['status']} sale"}), 400

    sale_type = d.get("sale_type") or sale["sale_type"]
    if sale_type not in SALE_TYPES:
        return jsonify({"error": "bad sale_type"}), 400
    try:
        sale_date = date.fromisoformat(str(d.get("sale_date") or ""))
    except ValueError:
        return jsonify({"error": "bad sale_date"}), 400

    def _num(x):
        try:
            v = round(float(x), 2)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    heating = _num(d.get("heating_amount"))
    water = _num(d.get("water_amount"))
    chc = _num(d.get("chc_amount"))
    if sale_type == "chc":
        heating = water = None
        if not chc:
            return jsonify({"error": "CHC sale needs an amount"}), 400
    else:
        chc = None
        if not heating and not water:
            return jsonify({"error": "enter a heating and/or water amount"}), 400

    sold_by = (d.get("sold_by") or "").strip() or None
    if sale_type == "office" and sold_by not in OFFICE_SELLERS:
        return jsonify({"error": "office sales must be sold by Dec or Josh"}), 400
    if sale_type in REP_SALE_TYPES and not sold_by:
        return jsonify({"error": "pick the rep who sold it"}), 400
    if sale_type == "chc":
        sold_by = None

    rep_owner = _rep_owner_id(sold_by) if sale_type in REP_SALE_TYPES else ""

    before = {k: sale[k] for k in ("sale_date", "sale_type", "heating_amount",
                                   "water_amount", "chc_amount", "sold_by", "note")}
    after = {"sale_date": sale_date.isoformat(), "sale_type": sale_type,
             "heating_amount": heating, "water_amount": water, "chc_amount": chc,
             "sold_by": sold_by, "note": (d.get("note") or "").strip() or None}

    now = datetime.now(timezone.utc)
    _bq().query(f"""
        UPDATE {BQ_SALES}
        SET sale_date = @s_date, sale_type = @stype,
            heating_amount = @heat, water_amount = @wat, chc_amount = @chc,
            sold_by = @sold_by, sold_by_owner_id = @sb_oid, note = @note,
            updated_at = @now_ts
        WHERE sale_id = @sid
    """, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("sid", "STRING", sale_id),
        bigquery.ScalarQueryParameter("s_date", "DATE", sale_date.isoformat()),
        bigquery.ScalarQueryParameter("stype", "STRING", sale_type),
        bigquery.ScalarQueryParameter("heat", "FLOAT64", heating),
        bigquery.ScalarQueryParameter("wat", "FLOAT64", water),
        bigquery.ScalarQueryParameter("chc", "FLOAT64", chc),
        bigquery.ScalarQueryParameter("sold_by", "STRING", sold_by),
        bigquery.ScalarQueryParameter("sb_oid", "STRING",
                                      rep_owner
                                      or (d.get("sold_by_owner_id") or "").strip()
                                      or sale.get("sold_by_owner_id")),
        bigquery.ScalarQueryParameter("note", "STRING", after["note"]),
        bigquery.ScalarQueryParameter("now_ts", "TIMESTAMP", now.isoformat()),
    ])).result()
    _audit(sale_id, "edit", before, after)

    if sale["lead_id"]:
        old_amt = (sale["heating_amount"] or 0) + (sale["water_amount"] or 0) + (sale["chc_amount"] or 0)
        new_amt = (heating or 0) + (water or 0) + (chc or 0)
        try:
            _refresh_crm_totals(sale["lead_id"], sale_type=sale_type,
                                heating=heating, water=water, sold_by=sold_by,
                                rep_owner=rep_owner)
            changes = []
            if abs(old_amt - new_amt) > 0.004:
                changes.append(f"£{old_amt:,.2f} → £{new_amt:,.2f}")
            if before["sold_by"] != sold_by:
                changes.append(f"seller {before['sold_by'] or '—'} → {sold_by or '—'}")
            if str(before["sale_date"]) != sale_date.isoformat():
                changes.append(f"date {before['sale_date']} → {sale_date.isoformat()}")
            if changes:
                _crm_note(sale["lead_id"],
                          "✏️ Sale corrected: " + ", ".join(changes)
                          + f"\n(by {session.get('name') or session.get('username')} via Trust Sales)",
                          author_owner_id=rep_owner or sale.get("sold_by_owner_id"))
        except Exception:
            app.logger.exception("CRM update after edit failed")
    return jsonify({"ok": True})


@app.route("/api/sales/<sale_id>/void", methods=["POST"])
@login_required
@admin_required
def api_void_sale(sale_id: str):
    d = request.get_json(force=True, silent=True) or {}
    reason = (d.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "a reason is required"}), 400
    rows = list(_bq().query(
        f"SELECT lead_id, sale_type, sold_by, status FROM {BQ_SALES} WHERE sale_id = @sid",
        job_config=_bq_params(sid=sale_id)).result())
    if not rows:
        return jsonify({"error": "not found"}), 404
    if rows[0]["status"] == "void":
        return jsonify({"error": "already void"}), 400
    now = datetime.now(timezone.utc)
    _bq().query(f"""
        UPDATE {BQ_SALES}
        SET status = 'void', void_reason = @reason, updated_at = @now_ts
        WHERE sale_id = @sid
    """, job_config=_bq_params(sid=sale_id, reason=f"{reason} (by {session.get('username')})",
                               now_ts=now.isoformat())).result()
    lead_id = rows[0]["lead_id"]
    if lead_id:
        try:
            # totals recompute; sold statuses clear when a component's total hits zero
            _refresh_crm_totals(lead_id)
        except Exception:
            app.logger.exception("CRM total refresh after void failed")
        try:
            sale = _get_sale(sale_id) or {}
            amt = ((sale.get("heating_amount") or 0) + (sale.get("water_amount") or 0)
                   + (sale.get("chc_amount") or 0))
            _crm_note(lead_id,
                      f"🚫 Sale entry voided — £{amt:,.2f} removed from sold amounts"
                      f'\n"{reason}"'
                      f"\n(by {session.get('name') or session.get('username')} via Trust Sales)",
                      author_owner_id=sale.get("sold_by_owner_id"))
        except Exception:
            app.logger.exception("CRM note after void failed (non-fatal)")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — user management (admin only)
# ---------------------------------------------------------------------------

@app.route("/api/users")
@login_required
@admin_required
def api_list_users():
    rows = list(_bq().query(
        f"SELECT username, name, role, created_at FROM {BQ_USERS} ORDER BY username"
    ).result())
    return jsonify({"users": [{
        "username": r["username"], "name": r["name"] or "", "role": r["role"] or "user",
    } for r in rows]})


@app.route("/api/users", methods=["POST"])
@login_required
@admin_required
def api_create_user():
    d = request.get_json(force=True, silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    name = (d.get("name") or "").strip()
    role = d.get("role") if d.get("role") in ("admin", "user") else "user"
    password = d.get("password") or ""
    if not username.isalnum() or len(username) < 2:
        return jsonify({"error": "username must be letters/numbers only"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if _get_user(username):
        return jsonify({"error": "username already exists"}), 400
    try:
        _bq().query(f"""
            INSERT INTO {BQ_USERS} (username, name, role, password_hash, created_at)
            VALUES (@u, @n, @r, @h, @now_ts)
        """, job_config=_bq_params(u=username, n=name or username, r=role,
                                   h=_hash_password(password),
                                   now_ts=datetime.now(timezone.utc).isoformat())).result()
    except Exception:
        app.logger.exception("user insert failed")
        return jsonify({"error": "could not create the user"}), 500
    return jsonify({"ok": True})


@app.route("/api/users/<username>/password", methods=["POST"])
@login_required
@admin_required
def api_reset_password(username: str):
    d = request.get_json(force=True, silent=True) or {}
    password = d.get("password") or ""
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if not _get_user(username.lower()):
        return jsonify({"error": "no such user"}), 404
    job = _bq().query(f"""
        UPDATE {BQ_USERS}
        SET password_hash = @h, updated_at = @now_ts
        WHERE username = @u
    """, job_config=_bq_params(h=_hash_password(password), u=username.lower(),
                               now_ts=datetime.now(timezone.utc).isoformat()))
    job.result()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5061)
