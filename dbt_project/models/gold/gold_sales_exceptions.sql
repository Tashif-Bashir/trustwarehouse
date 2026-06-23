-- gold_sales_exceptions
-- QA review list for the sales ledger: rows where the reconciliation is uncertain
-- or where sources disagree. This is how the data stays honest — it surfaces the
-- edges (pending ERP entry, unattributed sales, attribution conflicts, sold leads
-- with no money evidence) for a human to confirm, rather than silently guessing.
-- Scoped to roughly the last 4 months so the list stays actionable.

{{ config(materialized='view') }}

with ledger as (
    select * from {{ ref('gold_sales_reconciled') }}
),

rep_map as (
    select * from {{ ref('sales_rep_mapping') }}
),

leads as (
    select
        lead_id,
        trim(concat(coalesce(first_name, ''), ' ', coalesce(last_name, '')))  as customer_name,
        owner_id,
        is_sold,
        appointment_date
    from {{ ref('silver_sharpspring_leads') }}
),

window_start as (
    select date_trunc(date_sub(current_date('Europe/London'), interval 120 day), month) as d
),

-- 1) Deposit logged in CRM, but no Unleashed order has confirmed the amount yet.
pending as (
    select
        'pending_no_unleashed'                                      as exception_type,
        lead_id,
        customer_name,
        rep,
        sale_month,
        amount_ex_vat,
        'deposit logged in CRM but no matching Unleashed order yet (amount provisional)' as detail
    from ledger
    where is_provisional
      and not is_unattributed
      and sale_month >= (select d from window_start)
),

-- 2) Real sale that could not be attributed to a tracked advisor (e.g. closer sale).
unattributed as (
    select
        'unattributed'                                             as exception_type,
        lead_id,
        customer_name,
        cast(null as string)                                       as rep,
        sale_month,
        amount_ex_vat,
        concat('sale not attributable to a tracked advisor; Unleashed salesperson = ',
               coalesce(unl_sales_person, '(none)'))               as detail
    from ledger
    where is_unattributed
      and sale_month >= (select d from window_start)
),

-- 3) CRM owner and Unleashed salesperson disagree on who sold it.
conflict as (
    select
        'attribution_conflict'                                     as exception_type,
        l.lead_id,
        l.customer_name,
        l.rep,
        l.sale_month,
        l.amount_ex_vat,
        concat('CRM owner -> ', l.rep, ', but Unleashed salesperson -> ', rm.canonical_name) as detail
    from ledger l
    join rep_map rm on l.unl_sales_person = rm.unleashed_sales_person_name
    where l.rep is not null
      and rm.canonical_name != l.rep
      and l.sale_month >= (select d from window_start)
),

-- 4) Lead marked sold with a recent appointment, owned by a tracked advisor, but
--    NOT in the ledger — no deposit note and no Unleashed order. Either a quote
--    wrongly flagged "sold" (Rhiannon) or a genuine sale whose deposit isn't logged
--    yet (Sarah). A human should confirm whether money actually changed hands.
sold_no_money as (
    select
        'sold_no_money'                                            as exception_type,
        s.lead_id,
        s.customer_name,
        rm.canonical_name                                          as rep,
        date_trunc(s.appointment_date, month)                      as sale_month,
        cast(null as float64)                                      as amount_ex_vat,
        'lead marked sold (recent appointment) but no deposit note and no Unleashed order' as detail
    from leads s
    join rep_map rm on safe_cast(s.owner_id as int64) = rm.sharpspring_owner_id
    left join ledger l on l.lead_id = s.lead_id
    where s.is_sold
      and s.appointment_date >= date_sub(current_date('Europe/London'), interval 120 day)
      and l.lead_id is null
)

select * from pending
union all select * from unattributed
union all select * from conflict
union all select * from sold_no_money
order by exception_type, sale_month desc, rep
