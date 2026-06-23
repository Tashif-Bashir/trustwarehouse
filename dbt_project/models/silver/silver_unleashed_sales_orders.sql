with source as (
    select * from {{ source('bronze', 'unleashed_sales_orders') }}
),

-- Water vs heating at the order level: an order is a water sale if any of its
-- product lines belong to the Unleashed "Water Heating" group (Ocean Stream /
-- Flow / Endless cylinders). Heating orders are "Neos" radiators. This is the
-- authoritative water signal that drives the £1,334-per-water-sale deduction.
order_water as (
    select
        b.guid                                                          as order_guid,
        max(case when p.product_group__group_name = 'Water Heating'
                 then true else false end)                             as is_water_order
    from {{ source('bronze', 'unleashed_sales_orders') }} b
    join {{ source('bronze', 'unleashed_sales_orders__sales_order_lines') }} l
        on l._dlt_parent_id = b._dlt_id
    left join {{ source('bronze', 'unleashed_products') }} p
        on p.guid = l.product__guid
    group by 1
),

cleaned as (
    select
        -- primary key
        guid                                                            as order_guid,
        order_number,

        -- dates
        {{ parse_unleashed_date('order_date') }}                        as order_date,
        {{ parse_unleashed_date('required_date') }}                     as required_date,
        {{ parse_unleashed_date('completed_date') }}                    as completed_date,
        {{ parse_unleashed_date('payment_due_date') }}                  as payment_due_date,
        {{ parse_unleashed_timestamp('created_on') }}                   as created_at,
        {{ parse_unleashed_timestamp('last_modified_on') }}             as last_modified_at,

        -- status
        nullif(trim(order_status), '')                                  as order_status,
        nullif(trim(custom_order_status), '')                           as custom_order_status,

        -- customer
        nullif(trim(customer__guid), '')                                as customer_guid,
        nullif(trim(customer__customer_code), '')                       as customer_code,
        nullif(trim(customer__customer_name), '')                       as customer_name,

        -- delivery contact (key for SharpSpring lead matching)
        nullif(trim(delivery_contact__first_name), '')                  as delivery_first_name,
        nullif(trim(delivery_contact__last_name), '')                   as delivery_last_name,
        nullif(trim(delivery_contact__email_address), '')               as delivery_email,
        nullif(trim(delivery_contact__phone_number), '')                as delivery_phone,
        nullif(trim(delivery_contact__mobile_phone), '')                as delivery_mobile,

        -- delivery address
        nullif(trim(delivery_name), '')                                 as delivery_name,
        nullif(trim(delivery_street_address), '')                       as delivery_street,
        nullif(trim(delivery_city), '')                                 as delivery_city,
        nullif(trim(delivery_region), '')                               as delivery_region,
        nullif(trim(delivery_post_code), '')                            as delivery_postcode,
        nullif(trim(delivery_country), '')                              as delivery_country,

        -- financials
        SAFE_CAST(sub_total AS NUMERIC)                                 as sub_total,
        SAFE_CAST(tax_total AS NUMERIC)                                 as tax_total,
        SAFE_CAST(total AS NUMERIC)                                     as total,
        SAFE_CAST(discount_rate AS NUMERIC)                             as discount_rate,
        SAFE_CAST(tax_rate AS NUMERIC)                                  as tax_rate,
        nullif(trim(currency__currency_code), '')                       as currency_code,

        -- fulfilment
        nullif(trim(delivery_method), '')                               as delivery_method,
        nullif(trim(warehouse__warehouse_name), '')                     as warehouse_name,
        nullif(trim(sales_order_group), '')                             as sales_order_group,

        -- sales person
        nullif(trim(sales_person__full_name), '')                       as sales_person_name,
        nullif(trim(sales_person__email), '')                           as sales_person_email,

        -- audit
        nullif(trim(created_by), '')                                    as created_by,
        nullif(trim(last_modified_by), '')                              as last_modified_by,
        nullif(trim(comments), '')                                      as comments

    from source
)

select
    cleaned.*,
    coalesce(ow.is_water_order, false)                                  as is_water_order
from cleaned
left join order_water ow on ow.order_guid = cleaned.order_guid
