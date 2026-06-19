with source as (
    select * from {{ source('bronze', 'unleashed_customers') }}
),

cleaned as (
    select
        -- primary key
        guid                                                            as customer_guid,
        nullif(trim(customer_code), '')                                 as customer_code,
        nullif(trim(customer_name), '')                                 as customer_name,

        -- contact
        nullif(trim(email), '')                                         as email,
        nullif(trim(phone_number), '')                                  as phone_number,
        nullif(trim(mobile_number), '')                                 as mobile_number,
        nullif(trim(contact_first_name), '')                            as contact_first_name,
        nullif(trim(contact_last_name), '')                             as contact_last_name,

        -- classification
        nullif(trim(customer_type), '')                                 as customer_type,
        nullif(trim(sell_price_tier), '')                               as sell_price_tier,
        nullif(trim(payment_term), '')                                  as payment_term,
        nullif(trim(delivery_method), '')                               as delivery_method,
        nullif(trim(sales_order_group), '')                             as sales_order_group,

        -- financials
        SAFE_CAST(discount_rate AS NUMERIC)                             as discount_rate,
        SAFE_CAST(credit_limit AS NUMERIC)                              as credit_limit,
        has_credit_limit,
        stop_credit,
        taxable,
        obsolete,

        -- currency and warehouse
        nullif(trim(currency__currency_code), '')                       as currency_code,
        nullif(trim(default_warehouse__warehouse_name), '')             as default_warehouse,

        -- sales person
        nullif(trim(sales_person__full_name), '')                       as sales_person_name,
        nullif(trim(sales_person__email), '')                           as sales_person_email,

        -- audit
        {{ parse_unleashed_timestamp('created_on') }}                   as created_at,
        {{ parse_unleashed_timestamp('last_modified_on') }}             as last_modified_at,
        nullif(trim(created_by), '')                                    as created_by,
        nullif(trim(last_modified_by), '')                              as last_modified_by

    from source
    where obsolete = false or obsolete is null
)

select * from cleaned
