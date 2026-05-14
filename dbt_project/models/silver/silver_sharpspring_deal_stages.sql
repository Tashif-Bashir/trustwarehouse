with source as (
    select * from {{ source('bronze', 'sharpspring_deal_stages') }}
),

cleaned as (
    select
        id                                          as deal_stage_id,
        nullif(trim(deal_stage_name), '')           as deal_stage_name,
        nullif(trim(description), '')               as description,
        try_cast(default_probability as integer)    as default_probability,
        try_cast(weight as integer)                 as weight
    from source
)

select * from cleaned
