with orders as (
    select * from {{ ref('silver_unleashed_sales_orders') }}
),

leads as (
    select * from {{ ref('silver_sharpspring_leads') }}
),

-- primary match: delivery email → lead email
email_matches as (
    select
        o.order_guid,
        l.lead_id,
        'email'     as match_type
    from orders o
    inner join leads l
        on LOWER(o.delivery_email) = LOWER(l.email)
        and o.delivery_email is not null
        and l.email is not null
),

-- fallback: full name match for orders not already email-matched
name_matches as (
    select
        o.order_guid,
        l.lead_id,
        'name'      as match_type
    from orders o
    inner join leads l
        on LOWER(CONCAT(COALESCE(o.delivery_first_name, ''), ' ', COALESCE(o.delivery_last_name, '')))
           = LOWER(CONCAT(COALESCE(l.first_name, ''), ' ', COALESCE(l.last_name, '')))
        and o.delivery_first_name is not null
        and l.first_name is not null
    where o.order_guid not in (select order_guid from email_matches)
),

all_matches as (
    select * from email_matches
    union all
    select * from name_matches
),

-- if one order matched multiple leads, keep the most recently created lead
deduped_matches as (
    select
        m.order_guid,
        m.lead_id,
        m.match_type,
        row_number() over (
            partition by m.order_guid
            order by l.created_at desc
        ) as rn
    from all_matches m
    inner join leads l on m.lead_id = l.lead_id
),

final as (
    select
        -- order fields
        o.order_number,
        o.order_guid,
        o.order_date,
        o.completed_date,
        o.order_status,
        o.customer_name,
        o.delivery_email,
        o.delivery_first_name,
        o.delivery_last_name,
        o.delivery_city,
        o.delivery_postcode,
        o.total                                                         as order_total,
        o.currency_code,
        o.sales_person_name                                             as unleashed_sales_person,

        -- lead attribution
        dm.match_type,
        l.lead_id,
        l.lead_status,
        l.campaign_id,
        l.marketing_campaign,
        l.customer_type,
        l.created_at                                                    as lead_created_at,
        SAFE_CAST(l.appointment_booked_at AS TIMESTAMP)                 as appointment_booked_at,
        l.appointment_made_by,
        l.converted_by,
        l.is_sold                                                       as crm_is_sold,

        -- derived
        case when dm.lead_id is not null then true else false end        as is_crm_matched,
        DATE_DIFF(o.order_date, DATE(l.created_at), DAY)                as days_lead_to_order

    from orders o
    left join deduped_matches dm
        on o.order_guid = dm.order_guid
        and dm.rn = 1
    left join leads l on dm.lead_id = l.lead_id
)

select * from final
order by order_date desc
