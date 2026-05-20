with source as (
    select * from {{ source('bronze', 'unleashed_products') }}
),

cleaned as (
    select
        -- primary key
        guid                                                            as product_guid,
        nullif(trim(product_code), '')                                  as product_code,
        nullif(trim(product_description), '')                           as product_description,

        -- classification
        nullif(trim(product_group__group_name), '')                     as product_group,
        nullif(trim(supplier__supplier_name), '')                       as supplier_name,
        nullif(trim(supplier__supplier_code), '')                       as supplier_code,

        -- pricing
        SAFE_CAST(default_sell_price AS NUMERIC)                        as default_sell_price,
        SAFE_CAST(default_purchase_price AS NUMERIC)                    as default_purchase_price,
        SAFE_CAST(last_cost AS NUMERIC)                                 as last_cost,
        SAFE_CAST(nominal_cost AS NUMERIC)                              as nominal_cost,
        SAFE_CAST(average_land_price AS NUMERIC)                        as average_land_price,
        SAFE_CAST(minimum_sell_price AS NUMERIC)                        as minimum_sell_price,

        -- stock control
        SAFE_CAST(min_stock_alert_level AS NUMERIC)                     as min_stock_alert_level,
        SAFE_CAST(max_stock_alert_level AS NUMERIC)                     as max_stock_alert_level,
        SAFE_CAST(minimum_order_quantity AS NUMERIC)                    as minimum_order_quantity,
        never_diminishing,

        -- flags
        is_sellable,
        is_purchasable,
        is_component,
        is_assembled_product,
        is_serialized,
        is_batch_tracked,
        obsolete,

        -- tax
        nullif(trim(xero_tax_code), '')                                 as tax_code,
        SAFE_CAST(xero_tax_rate AS NUMERIC)                             as tax_rate,

        -- audit
        SAFE_CAST(created_on AS TIMESTAMP)                              as created_at,
        SAFE_CAST(last_modified_on AS TIMESTAMP)                        as last_modified_at,
        nullif(trim(created_by), '')                                    as created_by,
        nullif(trim(last_modified_by), '')                              as last_modified_by

    from source
    where obsolete = false or obsolete is null
)

select * from cleaned
