with source as (
    select * from {{ source('bronze', 'unleashed_stock_on_hand') }}
),

cleaned as (
    select
        -- primary key
        guid                                                            as stock_guid,
        nullif(trim(product_code), '')                                  as product_code,
        nullif(trim(product_description), '')                           as product_description,
        nullif(trim(product_guid), '')                                  as product_guid,
        nullif(trim(product_group_name), '')                            as product_group,

        -- warehouse
        nullif(trim(warehouse), '')                                     as warehouse_name,
        nullif(trim(warehouse_code), '')                                as warehouse_code,

        -- quantities
        SAFE_CAST(qty_on_hand AS NUMERIC)                               as qty_on_hand,
        SAFE_CAST(available_qty AS NUMERIC)                             as available_qty,
        SAFE_CAST(allocated_qty AS NUMERIC)                             as allocated_qty,
        SAFE_CAST(on_purchase AS NUMERIC)                               as on_purchase,

        -- cost
        SAFE_CAST(avg_cost AS NUMERIC)                                  as avg_cost,
        SAFE_CAST(total_cost AS NUMERIC)                                as total_cost,

        -- velocity
        days_since_last_sale,

        -- audit
        {{ parse_unleashed_timestamp('last_modified_on') }}             as last_modified_at

    from source
)

select * from cleaned
