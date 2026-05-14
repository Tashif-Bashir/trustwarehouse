# SharpSpring Silver Models

## Overview

Four silver models built from SharpSpring bronze data. All models clean and type the raw data but drop no rows — filtering happens in gold.

---

## silver_sharpspring_leads

**57,100 rows** — every enquiry ever submitted to Trust Electric Heating.

Source: `bronze.sharpspring_leads` → synced hourly via GitHub Actions.

### What we cleaned
- **Renamed 63 columns** — SharpSpring stores custom fields with internal IDs like `lead_warmth___1___69ea236712886`. All renamed to plain English (`enquiry_type`, `heating_type`, `form_page` etc.)
- **Empty strings → NULL** — SharpSpring returns `""` for missing values, converted to proper NULLs throughout
- **Phone numbers normalised** — `phone`, `mobile`, `phone_alt` standardised to E.164 format without `+` (e.g. `07700900123` → `447700900123`) using the `normalise_phone` macro. Required for matching leads to Wildix call records in gold.
- **Booleans cast** — `is_active`, `is_qualified`, `is_contact`, `is_customer`, `is_unsubscribed` converted from `'0'`/`'1'` strings to proper `true`/`false`
- **Numerics cast** — `lead_score` to integer, `lead_score_weighted` to double
- **dlt internal columns dropped** — `_dlt_load_id`, `_dlt_id` removed

### Key columns

| Column | Description |
|---|---|
| `lead_id` | Unique SharpSpring lead ID |
| `owner_id` | Agent who owns the lead |
| `campaign_id` | Lead source — join to `silver_sharpspring_campaigns` |
| `lead_status` | contact, qualified, contactWithOpp, customer, unqualified |
| `phone` | Normalised phone — used to match Wildix calls in gold |
| `enquiry_type` | Water / Heating / Heating and Water — populated from May 2026 |
| `created_at` | When the lead first enquired |
| `updated_at` | When the record was last touched |
| `appointment_status` | sold, follow up, not interested etc. |
| `order_confirmed` | Yes/No — sale made (original field, 3,060 records) |
| `order_confirmed_new` | 1/0 — same purpose, newer field (703 records) |
| `chc_lead_status` | CHC product pipeline status, separate from main heating pipeline |

### Column groups
Identity, Contact, Timestamps, Lifecycle, Scoring, Geography, Appointment, Sales, Pipeline, Installation, Attribution, Lead Metadata — 63 columns total.

---

## silver_sharpspring_campaigns

**66 rows** — the marketing campaigns that leads are attributed to.

Source: `bronze.sharpspring_campaigns` → synced hourly via GitHub Actions.

### What we cleaned
- Renamed `id` → `campaign_id` for clarity when joining to leads
- Empty strings → NULL on name, type, alias, origin
- `is_active` cast from `'0'`/`'1'` to boolean
- Dropped unused columns — `qty`, `price`, `goal`, `other_costs` all zero across the board
- dlt internal columns dropped

### Key columns

| Column | Description |
|---|---|
| `campaign_id` | Joins to `lead.campaign_id` in silver_sharpspring_leads |
| `campaign_name` | Human-readable name e.g. "Facebook", "CHC Letter 1", "Google Ads" |
| `campaign_type` | Organic, Google, General etc. |
| `campaign_origin` | System (auto-created) vs SharpSpring (manually created) |
| `is_active` | Whether the campaign is still running |

---

## silver_sharpspring_deal_stages

**9 rows** — the pipeline stages a deal moves through.

Source: `bronze.sharpspring_deal_stages` → synced hourly via GitHub Actions.

### What we cleaned
- `default_probability` and `weight` cast from text to integers
- Empty strings → NULL on name and description
- Dropped `is_editable` — not relevant for reporting
- dlt internal columns dropped

### Key columns

| Column | Description |
|---|---|
| `deal_stage_id` | Joins to `silver_sharpspring_opportunities.deal_stage_id` |
| `deal_stage_name` | Appointment Booked, Appointment Done, Follow Up Stage etc. |
| `default_probability` | Default win probability % for this stage |

---

## silver_sharpspring_opportunities

**5,884 rows** — deals linked to leads, tracking sale values and pipeline stages.

Source: `bronze.sharpspring_opportunities` → synced hourly via GitHub Actions.

### What we cleaned
- **`amount` cast to decimal(12,2)** — stored as text in bronze so maths was impossible. Now you can `SUM(amount)` and `AVG(amount)` directly.
- **`probability` cast to integer**
- **`is_closed`, `is_won`, `is_active` cast to booleans** from `'0'`/`'1'` strings
- **Ugly field names decoded** — `estimate_no_6384aad103ee2` → `estimate_number`, `competitor_6384aa400f388` → `competitor`, `sector_6384aa8470196` → `sector`
- Empty strings → NULL throughout
- Timestamps renamed to `created_at`/`updated_at`
- dlt internal columns dropped

### Key columns

| Column | Description |
|---|---|
| `opportunity_id` | Unique deal ID |
| `primary_lead_id` | Joins to `silver_sharpspring_leads.lead_id` |
| `deal_stage_id` | Joins to `silver_sharpspring_deal_stages.deal_stage_id` |
| `amount` | Deal value in £ — now a proper decimal |
| `is_won` | Whether the deal was won |
| `is_closed` | Whether the deal is closed (won or lost) |
| `probability` | Estimated win probability % |
| `close_date` | Expected or actual close date |
| `competitor` | Competitor named if deal was lost |
| `sector` | Residential, commercial etc. |
