"""Weekly refresh of the owner's `Pipeline_quotes_from_Unleashed_*.xlsx` workbook, IN PLACE.

The file (owner's OneDrive root, shared with Fiona, Gia, Paula and Declan) is
the 30/60/90-day unsold pipeline per field rep with each lead's Unleashed
quote. The team added their own sheet, "OVER ALL ": quoted £ per rep in the
0-30 / 31-60 / 61-90-day bands, leads with no quote ("Missing Paperwork")
per band, and totals. This job rebuilds Summary, Leads and OVER ALL from the
warehouse every Monday and writes them into the SAME OneDrive item, so the
link and sharing survive and OneDrive keeps version history. Any other sheet
anyone adds is preserved untouched.

Usage:
  python -m scripts.pipeline_quotes_weekly --dry-run   # writes ./out/<name>.xlsx only
  python -m scripts.pipeline_quotes_weekly             # rebuilds the OneDrive file
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from google.cloud import bigquery
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingestion.onedrive.auth import get_token  # noqa: E402
from scripts.rep_pipelines_weekly import best_quote, sql_list, unleashed_quotes  # noqa: E402

load_dotenv()
UK = ZoneInfo("Europe/London")
PROJECT = "trustwarehouse"
GRAPH = "https://graph.microsoft.com/v1.0"
FILE_NAME = os.environ.get("PIPELINE_QUOTES_FILE", "Pipeline_quotes_from_Unleashed_15Sep2026.xlsx")
WINDOW_DAYS = 90
DEAD = ["Appointment Cancelled", "Not Interested", "Too Expensive", "Not a Lead", "Bought Elsewhere"]
CHASE = ["appointment sat", "follow up", "follow up text", "no contact", "not ready yet"]
STATUS_RANK = {"Accepted": 0, "Pending": 1, "Draft": 2, "Cancelled": 3}
# The team's own row labels on the OVER ALL sheet (15 Sep 2026). Anyone not
# listed gets first name + surname initial; Unattributed is their "Other".
SHORT = {
    "Chris Krammer": "Chris K", "Chris Mannix": "Chris M", "Chris Southworth": "Chris S", "Chris Cash": "Chris C",
    "Kelly Miller": "Kelly", "Kris Noorouzi": "Kris", "Luke Mudd": "Luke", "Niall Devanish": "Niall",
    "Paul Slade": "Paul", "Sam Chapman": "Sam C", "Samuel Hamilton": "Sammy", "Stephen Bishop": "Steve B",
    "Steven Morley Jordan": "Steve M", "Unattributed": "Other",
}
HDR_FONT = Font(bold=True, color="FFFFFF")
HDR_FILL = PatternFill("solid", fgColor="D71F26")


def log(msg: str) -> None:
    print(f"{datetime.now(UK):%H:%M:%S} {msg}", flush=True)


def short_name(rep: str) -> str:
    if rep in SHORT:
        return SHORT[rep]
    parts = rep.split()
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def query_pipeline(bq: bigquery.Client) -> list[dict]:
    sql = f"""
    SELECT CAST(id AS STRING) AS lead_id,
           TRIM(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))) AS customer,
           COALESCE(zipcode,'') AS postcode,
           COALESCE(mobile_phone_number, phone_number, '') AS phone,
           CAST(DATE(appointment_time___date_5ae8ca2f532bc, 'Europe/London') AS STRING) AS appt_date,
           CAST(owner_id AS STRING) AS owner_id,
           LOWER(TRIM(appointment_status_637f8d6fa1096)) AS chase_status,
           COALESCE(status_633ae6f6ac6fe,'') AS lead_status
    FROM `{PROJECT}.bronze.sharpspring_leads`
    WHERE LOWER(TRIM(appointment_status_637f8d6fa1096)) IN ({sql_list(CHASE)})
      AND status_633ae6f6ac6fe NOT IN ({sql_list(DEAD)})
      AND appointment_time___date_5ae8ca2f532bc IS NOT NULL
      AND appointment_time___date_5ae8ca2f532bc <= CURRENT_TIMESTAMP()
      AND DATE(appointment_time___date_5ae8ca2f532bc, 'Europe/London') >= DATE_SUB(CURRENT_DATE('Europe/London'), INTERVAL {WINDOW_DAYS} DAY)
      AND first_name NOT LIKE 'Zzz%'
      AND TRIM(CONCAT(first_name, ' ', COALESCE(last_name, ''))) NOT LIKE 'Test %'
      AND LOWER(COALESCE(first_name, '')) != 'test'
      AND CAST(id AS STRING) NOT IN (SELECT id FROM `{PROJECT}.bronze.sharpspring_leads_deleted`)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY update_timestamp DESC) = 1
    """
    return [dict(r) for r in bq.query(sql, location="europe-west2").result()]


def query_reps(bq: bigquery.Client, lead_ids: list[str]) -> tuple[dict, dict]:
    sql = f"""
    SELECT 'booking' AS kind, lead_id AS k, ARRAY_AGG(rep_name ORDER BY booked_at DESC LIMIT 1)[OFFSET(0)] AS v
    FROM `{PROJECT}.app.bookings`
    WHERE status = 'active' AND rep_name IS NOT NULL AND rep_name != '' AND lead_id IN UNNEST(@ids) GROUP BY lead_id
    UNION ALL SELECT 'rep', name, CAST(sharpspring_owner_id AS STRING) FROM `{PROJECT}.app.reps`
    """
    job = bq.query(sql, location="US", job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", lead_ids or [""])]))
    booking_rep, rep_by_owner = {}, {}
    for r in job.result():
        if r.kind == "booking" and r.v:
            booking_rep[r.k] = r.v
        elif r.kind == "rep" and r.v:
            rep_by_owner[r.v] = r.k
    return booking_rep, rep_by_owner


def all_quotes_for(lead: dict, quotes: list[dict]) -> list[dict]:
    from scripts.rep_pipelines_weekly import _norm_name, _norm_pc
    ln, lp = _norm_name(lead["customer"]), _norm_pc(lead["postcode"])
    surname = ln.split()[-1] if ln else ""
    hits = [q for q in quotes if (ln and q["name"] == ln) or (lp and q["pc"] == lp and surname and surname in q["name"])]
    hits.sort(key=lambda q: (q["rank"], q["date"]))
    return hits


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def _header(ws, cols: list[str], widths: list[int]) -> None:
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = HDR_FONT, HDR_FILL
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def write_summary(ws, rows: list[dict], today: date) -> None:
    _header(ws, ["Field rep", "Pipeline leads", "With a quote", "No quote found", "Quoted £ (ex VAT)", "Avg quote £"],
            [22, 15, 14, 15, 18, 14])
    reps = sorted({o["rep"] for o in rows}, key=lambda n: (n == "Unattributed", n))
    T = defaultdict(float)
    for rep in reps:
        mine = [o for o in rows if o["rep"] == rep]; mq = [o for o in mine if o["best"]]
        q = sum(o["best"]["subtotal"] for o in mq)
        ws.append([rep, len(mine), len(mq), len(mine) - len(mq), round(q, 2), round(q / len(mq), 2) if mq else None])
        T["n"] += len(mine); T["q"] += len(mq); T["£"] += q
    ws.append(["Total", int(T["n"]), int(T["q"]), int(T["n"] - T["q"]), round(T["£"], 2), round(T["£"] / T["q"], 2) if T["q"] else None])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=6):
        for c in row:
            c.number_format = "£#,##0"
    ws.append([]); ws.append(["How the match was made",
        "CRM lead (name, postcode) against Unleashed sales quotes modified in the last 130 days. A lead counts as quoted when "
        "the full name matches, or the postcode plus surname match. Where a lead has several quotes the best is Accepted > "
        "Pending > Draft, latest first. Quoted £ is the Unleashed SubTotal (ex VAT). Pipeline = attended in the last 90 days, "
        f"still winnable, not sold, not dead (the live metre's definition). Rebuilt automatically every Monday; this copy {today:%d/%m/%Y}."])


def write_leads(ws, rows: list[dict]) -> None:
    _header(ws, ["Field rep", "Customer", "Postcode", "Appointment", "Days since", "Chase status", "Quote no.", "Quote status",
                 "Quote date", "Quote £ (ex VAT)", "Matched on", "Other quotes", "Lead ID"],
            [22, 28, 10, 13, 10, 18, 14, 13, 12, 15, 20, 30, 20])
    for o in sorted(rows, key=lambda o: (o["rep"], -bool(o["best"]), o["age"])):
        b = o["best"]
        others = "; ".join(f"{q['number']} {q['status']} £{q['subtotal']}" for q in o["quotes"] if not b or q["number"] != b["number"])
        ws.append([o["rep"], o["customer"], o["postcode"], date.fromisoformat(o["appt_date"]).strftime("%d/%m/%Y"), o["age"], o["chase_status"],
                   b["number"] if b else "", b["status"] if b else "no quote found",
                   datetime.strptime(b["date"], "%Y-%m-%d").strftime("%d/%m/%Y") if b and b["date"] else "",
                   b["subtotal"] if b else None, b["how"] if b else "", others, o["lead_id"]])
    for row in ws.iter_rows(min_row=2, min_col=10, max_col=10):
        for c in row:
            c.number_format = "£#,##0"
    ws.auto_filter.ref = ws.dimensions


def write_overall(ws, rows: list[dict]) -> None:
    """The team's sheet, rebuilt with the same layout and the same SUM formulas."""
    ws.append(["Reps ", 30, 60, 90, "Missing Paperwork 30 days ", "Missing Paperwork 60 days ", "Missing Paperwork 90 days ", "Total £", "Total PW"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, w in enumerate([12, 11, 11, 11, 26, 26, 26, 12, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    band = lambda age: 0 if age <= 30 else 1 if age <= 60 else 2  # noqa: E731
    per: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0, 0])
    for o in rows:
        k = short_name(o["rep"]); b = band(o["age"])
        if o["best"]:
            per[k][b] += o["best"]["subtotal"]
        else:
            per[k][3 + b] += 1
    r = 2
    for k in sorted(per, key=lambda n: (n == "Other", n.lower())):
        v = per[k]
        ws.append([k, round(v[0]), round(v[1]), round(v[2]), v[3], v[4], v[5], f"=SUM(B{r}:D{r})", f"=SUM(E{r}:G{r})"]); r += 1
    last = r - 1
    ws.append(["Total"] + [f"=SUM({col}2:{col}{last})" for col in "BCDEFG"] + [f"=SUM(B{r}:D{r})", f"=SUM(E{r}:G{r})"])
    for c in ws[r]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, max_row=r, min_col=2, max_col=4):
        for c in row:
            c.number_format = "#,##0"
    ws.cell(r, 8).number_format = "#,##0"
    ws.freeze_panes = "B2"


REBUILT = ("Summary", "Leads", "OVER ALL ")


def rebuild_into(existing: bytes | None, rows: list[dict], today: date) -> bytes:
    """Replace the three generated sheets inside the existing workbook; keep everything else."""
    wb = load_workbook(io.BytesIO(existing)) if existing else Workbook()
    if existing is None:
        wb.remove(wb.active)
    for name in REBUILT:
        if name in wb.sheetnames:
            idx = wb.sheetnames.index(name); wb.remove(wb[name]); ws = wb.create_sheet(name, idx)
        else:
            ws = wb.create_sheet(name)
        {"Summary": lambda w: write_summary(w, rows, today), "Leads": lambda w: write_leads(w, rows),
         "OVER ALL ": lambda w: write_overall(w, rows)}[name](ws)
    wb.active = 0
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


# ---------------------------------------------------------------------------
# OneDrive
# ---------------------------------------------------------------------------

def graph_headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}"}


def get_item() -> dict:
    r = requests.get(f"{GRAPH}/me/drive/root:/{FILE_NAME}", headers=graph_headers(), params={"$select": "id,name,size,lastModifiedDateTime"}, timeout=60)
    r.raise_for_status(); return r.json()


def download(item_id: str) -> bytes:
    r = requests.get(f"{GRAPH}/me/drive/items/{item_id}/content", headers=graph_headers(), timeout=120)
    r.raise_for_status(); return r.content


def upload(item_id: str, data: bytes, attempts: int = 6) -> None:
    """Overwrite in place; a 423 means someone has it open in Excel - wait and retry."""
    for i in range(attempts):
        r = requests.put(f"{GRAPH}/me/drive/items/{item_id}/content",
                         headers={**graph_headers(), "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                         data=data, timeout=180)
        if r.status_code == 423 and i < attempts - 1:
            log(f"file is open in Excel (locked) - retry {i + 1}/{attempts - 1} in 5 min"); time.sleep(300); continue
        r.raise_for_status(); return


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = datetime.now(UK).date()
    bq = bigquery.Client(project=PROJECT)
    leads = query_pipeline(bq)
    booking_rep, rep_by_owner = query_reps(bq, [l["lead_id"] for l in leads])
    quotes = unleashed_quotes()
    log(f"pipeline leads: {len(leads)} | unleashed quotes: {len(quotes)}")
    rows = []
    for l in leads:
        hits = all_quotes_for(l, quotes)
        for q in hits:
            from scripts.rep_pipelines_weekly import _norm_name
            q["how"] = "name" if q["name"] == _norm_name(l["customer"]) else "postcode+surname"
        best = None
        if hits:
            top = hits[0]["rank"]; best = max((q for q in hits if q["rank"] == top), key=lambda q: q["date"])
        rows.append({**l, "rep": booking_rep.get(l["lead_id"]) or rep_by_owner.get(l["owner_id"] or "") or "Unattributed",
                     "age": (today - date.fromisoformat(l["appt_date"])).days, "quotes": hits, "best": best})
    with_q = sum(1 for o in rows if o["best"]); quoted = sum(o["best"]["subtotal"] for o in rows if o["best"])
    log(f"with a quote: {with_q}/{len(rows)} | quoted £{quoted:,.0f}")
    if args.dry_run:
        out = Path(__file__).resolve().parents[1] / "out"; out.mkdir(exist_ok=True)
        src = out / "pipeline_quotes_current.xlsx"
        existing = src.read_bytes() if src.exists() else None
        (out / FILE_NAME).write_bytes(rebuild_into(existing, rows, today)); log(f"dry run -> {out / FILE_NAME}")
        return
    item = get_item()
    existing = download(item["id"])
    log(f"OneDrive file: {item['name']} ({round(item['size'] / 1024)} KB, modified {item['lastModifiedDateTime']}) - rebuilding {', '.join(REBUILT)} in place")
    upload(item["id"], rebuild_into(existing, rows, today))
    log("done - same file, same link; previous copy in OneDrive version history")


if __name__ == "__main__":
    main()
