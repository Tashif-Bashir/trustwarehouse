-- gold_sales_reconciled
-- One row per genuine sale, normalised across CRM (SharpSpring), ERP (Unleashed)
-- and the deposit notes. Reproduces the team's manual sales sheet.
--
-- Model (validated against the June 2026 sheet):
--   * A sale = the first DEPOSIT payment for a lead (from the notes), dated to the
--     deposit month. Later "final balance" payments are ignored, so each sale lands
--     in the month the money first came in (not the appointment date — which can be
--     stale/re-dated, e.g. Michael Gillespie).
--   * Amount = the matched Unleashed order's ex-VAT sub_total when available
--     (name-matched, any salesperson); otherwise a provisional figure from the CRM
--     amount field or the deposit grossed up by its %.
--   * Attribution = the CRM lead owner -> canonical rep (sales_rep_mapping). Unleashed
--     sales_person is NOT trusted for attribution (back-office enterers like Rob/Sam
--     Chapman are often recorded there) — it is only used to attribute Unleashed-only
--     sales that have no CRM deposit (e.g. Karen Wellings).
--   * Water vs heating from the Unleashed product group; £1,334 flat deduction/water sale.

with notes as (
    select * from {{ ref('silver_sharpspring_notes') }}
),

leads as (
    select
        lead_id,
        trim(concat(coalesce(first_name, ''), ' ', coalesce(last_name, '')))  as customer_name,
        {{ norm_name("concat(coalesce(first_name, ''), ' ', coalesce(last_name, ''))") }} as name_key,
        owner_id,
        email,
        appt_amount,
        appt_amount_water,
        is_sold
    from {{ ref('silver_sharpspring_leads') }}
),

orders as (
    select
        order_guid,
        order_date,
        customer_name,
        {{ norm_name('customer_name') }}                            as name_key,
        delivery_email,
        sub_total,
        sales_person_name,
        is_water_order
    from {{ ref('silver_unleashed_sales_orders') }}
    where order_status not in ('Cancelled', 'Deleted', 'Parked')
      and order_date is not null
),

rep_map as (
    select * from {{ ref('sales_rep_mapping') }}
),

-- 1) opening deposit per lead: a payment event with no prior payment within 60 days
pay as (
    select
        lead_id,
        note_date,
        amount_mentioned,
        pct_mentioned,
        lag(note_date) over (partition by lead_id order by note_date) as prev_date
    from notes
    where is_payment_event
      and not is_balance_payment
      and note_date is not null
),

opening as (
    select lead_id, note_date as sale_date, amount_mentioned, pct_mentioned
    from pay
    where prev_date is null or date_diff(note_date, prev_date, day) > 60
),

-- 2) CRM-driven sales: opening deposit on a sold-variant lead, attributed by owner
crm_sales as (
    select
        o.lead_id,
        o.sale_date,
        date_trunc(o.sale_date, month)                              as sale_month,
        l.customer_name,
        l.name_key,
        l.owner_id,
        rm.canonical_name                                           as canonical_rep,
        rm.team,
        coalesce(
            safe_cast(l.appt_amount_water as float64) / 1.2,
            safe_cast(l.appt_amount as float64),
            case when o.pct_mentioned > 0 then o.amount_mentioned / (o.pct_mentioned / 100.0)
                 else o.amount_mentioned * 2 end
        )                                                           as crm_amount,
        l.appt_amount_water is not null                             as crm_is_water
    from opening o
    join leads l on l.lead_id = o.lead_id
    left join rep_map rm on safe_cast(l.owner_id as int64) = rm.sharpspring_owner_id
    where l.is_sold
),

-- 3) name-match each CRM sale to its Unleashed order (any salesperson) for exact ex-VAT
crm_with_unl as (
    select
        c.lead_id,
        c.sale_date,
        c.sale_month,
        c.customer_name,
        c.name_key,
        c.owner_id,
        c.canonical_rep,
        c.team,
        c.crm_amount,
        c.crm_is_water,
        u.sub_total                                                 as unl_ex_vat,
        u.is_water_order                                            as unl_is_water,
        u.sales_person_name                                         as unl_sales_person
    from crm_sales c
    left join orders u
        on u.name_key = c.name_key
        and u.name_key != ''
        and abs(date_diff(u.order_date, c.sale_date, day)) <= 45
    qualify row_number() over (
        partition by c.lead_id, c.sale_date
        order by abs(date_diff(u.order_date, c.sale_date, day)) nulls last, u.sub_total desc
    ) = 1
),

claimed_names as (
    select distinct name_key from crm_sales where name_key != ''
),

-- 4) Unleashed-only sales (no CRM deposit claimed them) attributed via salesperson
unl_only as (
    select
        cast(null as string)                                        as lead_id,
        u.order_date                                                as sale_date,
        date_trunc(u.order_date, month)                             as sale_month,
        u.customer_name,
        u.name_key,
        cast(null as string)                                        as owner_id,
        rm.canonical_name                                           as canonical_rep,
        rm.team,
        u.sub_total                                                 as crm_amount,
        u.is_water_order                                            as crm_is_water,
        u.sub_total                                                 as unl_ex_vat,
        u.is_water_order                                            as unl_is_water,
        u.sales_person_name                                         as unl_sales_person
    from orders u
    join rep_map rm on u.sales_person_name = rm.unleashed_sales_person_name
    where u.name_key != ''
      and u.name_key not in (select name_key from claimed_names)
    qualify row_number() over (
        partition by u.name_key, date_trunc(u.order_date, month)
        order by u.sub_total desc
    ) = 1
),

unioned as (
    select * from crm_with_unl
    union all
    select * from unl_only
),

final as (
    select
        lead_id,
        customer_name,
        canonical_rep                                               as rep,
        team,
        sale_date,
        sale_month,
        round(coalesce(unl_ex_vat, crm_amount), 2)                  as amount_ex_vat,
        coalesce(unl_is_water, crm_is_water, false)                 as is_water,
        round(coalesce(unl_ex_vat, crm_amount), 2)
            - case when coalesce(unl_is_water, crm_is_water, false) then 1334 else 0 end
                                                                    as amount_to_target,
        case
            when unl_ex_vat is not null and lead_id is not null then 'crm+unleashed'
            when lead_id is not null then 'crm_only'
            else 'unleashed_only'
        end                                                         as source,
        unl_ex_vat is null                                          as is_provisional,
        canonical_rep is null                                       as is_unattributed,
        unl_sales_person
    from unioned
)

select * from final
-- drop sales we cannot value at all (no Unleashed match, no CRM amount, no parseable
-- deposit figure) — they are unquantifiable and would distort totals
where amount_ex_vat is not null
order by sale_month desc, rep, sale_date
