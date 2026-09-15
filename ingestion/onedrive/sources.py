"""Where the four operations workbooks live in Microsoft 365 (resolved 15 Sep 2026).

Graph item ids are stable across edits; they change only if a file is moved
to another drive or re-uploaded as a new file. If a download starts returning
404, re-resolve with a Graph search (scratchpad graph_find_files2.py did the
first resolution) and update here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workbook:
    key: str
    name: str
    drive_id: str
    item_id: str
    where: str  # human note


WORKBOOKS: tuple[Workbook, ...] = (
    Workbook(
        key="kpis",
        name="2026 KPI's.xlsx",
        drive_id="b!aXVeNLtTKkOj1sL6rJfEEAp9j2h14n9Nuav1LiLYgrwuxDuVUygDRpm3--knCV2c",
        item_id="015EKGVROCYDCFL3FEIFCLWQE5OZJV7IU2",
        where="Gia Rose's OneDrive",
    ),
    Workbook(
        key="install",
        name="Install plan 2026.xlsx",
        drive_id="b!KmwLFVWWdU6dmV0wJHlPyyjusOAOUYRMjRB1gBMeAI6iOOiRc-0CRqrnYUo5XARV",
        item_id="01VRRW5QG7PNOFHB37KNEJ4GTD75GI4HY3",
        where="Alice Hardegon's OneDrive (she has left - move this file)",
    ),
    Workbook(
        key="revenue",
        name="Daily Revenue Tracker Aug 25 -  .xlsx",
        drive_id="b!qk8iCLF4gUqTsh0wB4mfqKRSz6oaAcxNr3sxPc3gxVACebpHrvGuTZVRcR4XfCpY",
        item_id="01M7I3T5DBCCKECG36WRH3P6HRKFU34ADK",
        where="Finance SharePoint site / Shared Documents / Accounts",
    ),
    Workbook(
        key="dailies",
        name="Copy of Mar 26 Dailies.xlsx",
        drive_id="b!gz-dX8sOwkiLbTTbYjggSSjusOAOUYRMjRB1gBMeAI6iOOiRc-0CRqrnYUo5XARV",
        item_id="01FQ6RR2VWEMWYRY7SKBE3GCN3PCYWEZYH",
        where="Amelia Konczewska's OneDrive",
    ),
)

BY_KEY = {w.key: w for w in WORKBOOKS}
