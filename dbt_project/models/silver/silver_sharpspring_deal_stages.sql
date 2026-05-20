with source as (
    select * from {{ source('bronze', 'sharpspring_deal_stages') }}
),

cleaned as (
    select
        id                                          as deal_stage_id,
        nullif(trim(deal_stage_name), '')           as deal_stage_name,
        nullif(trim(description), '')               as description,
        SAFE_CAST(default_probability AS INT64)    as default_probability,
        SAFE_CAST(weight AS INT64)                 as weight
    from source
)

select * from cleaned
