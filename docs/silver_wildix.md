# Wildix Silver Models

## Overview

Two silver models built from Wildix bronze data. Both clean and type the raw data but drop no rows — filtering happens in gold.

---

## silver_wildix_calls

**143,082 rows** — full call history since the pipeline started, every call for every agent.

Source: `bronze.wildix_calls` → synced every 30 minutes via GitHub Actions. Incremental merge — fetches last 2 hours per run, deduplicates by `(id, _wms_id)`.

### What we cleaned
- **Kept 46 columns out of 71** — dropped SIP/protocol internals (`sip_call_id`, `user_agent`, `user_device`), IP addresses (`private_address`, `public_address`), empty fields (`recordings`, `recordings_data`, `tags`), and redundant company fields
- **Time columns cast to integers** — `duration`, `talk_time`, `hold_time`, `wait_time`, `queue_time`, `connect_time` are now proper numbers you can `SUM()` and `AVG()`. Stored as text in bronze.
- **`start_time` and `end_time` cast to bigint** — Unix timestamps in milliseconds. Will be converted to proper datetimes in gold.
- **`remote_phone` normalised** via the `normalise_phone` macro — matches the same format as SharpSpring `phone`/`mobile` fields, making the lead-to-call join possible in gold
- Empty strings → NULL throughout
- Columns renamed for clarity — `caller__group_name` → `caller_group`, `remote_phone_country_code_str` → `remote_phone_country` etc.
- dlt internal columns dropped

### Key columns

| Column | Description |
|---|---|
| `call_id` + `wms_id` | Composite primary key — same call appears once per agent involved |
| `call_status` | COMPLETED, MISSED etc. |
| `direction` | INBOUND / OUTBOUND / INTERNAL |
| `duration_seconds` | Total call duration — headline metric |
| `talk_time_seconds` | Active talk time excluding hold/wait — true engagement metric |
| `remote_phone` | Normalised customer phone — **join key to SharpSpring leads in gold** |
| `start_time` | Unix ms timestamp — when the call started |
| `caller_extension` / `callee_extension` | Agent extension — joins to `silver_wildix_colleagues.extension` |
| `caller_email` / `callee_email` | Agent email — joins to `silver_wildix_colleagues.email` |
| `wms_id` | Which colleague's perspective this record is from |
| `colleague_name` | Denormalised agent name from the pipeline tag |
| `colleague_department` | Denormalised department from the pipeline tag |
| `split_reason` | Why a call was split — transfer analytics |
| `queue_name` | Which queue handled the call — team/dept SLA reporting |

### What this unlocks in gold
1. **Join to SharpSpring leads** via `remote_phone` ↔ `silver_sharpspring_leads.phone` — links calls to lead lifecycle
2. **Agent productivity** — calls per agent, talk time, missed-call rate by user/group
3. **Queue/service SLAs** — wait time and abandonment by service line
4. **Inbound vs outbound mix** — sales effort vs support load
5. **Conversion attribution** — did a call precede an appointment or order confirmation?

---

## silver_wildix_colleagues

**40 rows** — all agents and extensions on the Wildix PBX. A small but high-leverage dimension table.

Source: `bronze.wildix_colleagues` → synced every 30 minutes via GitHub Actions. Full replace each run.

### What we cleaned
- **Kept 12 columns out of 24** — dropped LDAP internals (`dn`, `jid`, `group_dn`, `pbx_dn`), empty fields (`fax_number`, `picture`), low-value fields (`language` always "en", `source_id` inconsistent, `dialplan`)
- **`office_phone` and `mobile_phone` normalised** via the `normalise_phone` macro — consistent format for any future cross-system matching
- Empty strings → NULL throughout
- dlt internal columns dropped

### Key columns

| Column | Description |
|---|---|
| `id` | Stable Wildix user ID — primary key |
| `name` | Display name e.g. Lily, Sue — dashboard labels |
| `email` | Strongest cross-system join key — links to SharpSpring owner email |
| `extension` | Internal extension — joins to `wildix_calls.caller_extension` / `callee_extension` |
| `department` | Installations, Accounts, Commercial etc. — key dimension for team-level reporting |
| `group_name` | Functional group — queue/permission analysis |
| `role` | admin / user — filter out non-human accounts |

### Why this table matters
This is the **agent dimension**. Every call in `silver_wildix_calls` can be enriched with department and group by joining on `extension` or `email`. Combined with SharpSpring's `owner_id`, it enables "calls per sales rep alongside leads per sales rep" in a single gold view — without bloating the calls fact table.
