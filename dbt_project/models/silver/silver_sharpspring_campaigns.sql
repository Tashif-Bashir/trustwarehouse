with source as (
    select * from {{ source('bronze', 'sharpspring_campaigns') }}
),

cleaned as (
    select
        id              as campaign_id,
        nullif(trim(campaign_name), '')     as campaign_name,
        nullif(trim(campaign_type), '')     as campaign_type,
        nullif(trim(campaign_alias), '')    as campaign_alias,
        nullif(trim(campaign_origin), '')   as campaign_origin,
        is_active = '1'                     as is_active,
        start_date,
        end_date
    from source
)

select * from cleaned
