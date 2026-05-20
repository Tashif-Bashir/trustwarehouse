with source as (
    select * from {{ source('bronze', 'sharpspring_opportunities') }}
),

cleaned as (
    select
        id                                                      as opportunity_id,
        owner_id,
        deal_stage_id,
        account_id,
        nullif(trim(opportunity_name), '')                      as opportunity_name,
        SAFE_CAST(probability AS INT64)                        as probability,
        SAFE_CAST(amount AS NUMERIC)                      as amount,
        is_closed = '1'                                         as is_closed,
        is_won = '1'                                            as is_won,
        is_active = '1'                                         as is_active,
        close_date,
        create_timestamp                                        as created_at,
        update_timestamp                                        as updated_at,
        nullif(trim(originating_lead_id), '')                   as originating_lead_id,
        nullif(trim(primary_lead_id), '')                       as primary_lead_id,
        nullif(trim(campaign_id), '')                           as campaign_id,
        nullif(trim(campaign_attribution_override), '')         as campaign_attribution_override,
        nullif(trim(estimate_no_6384aad103ee2), '')             as estimate_number,
        nullif(trim(appointment_status_637f8fff22164), '')      as appointment_status,
        nullif(trim(competitor_6384aa400f388), '')              as competitor,
        nullif(trim(sector_6384aa8470196), '')                  as sector
    from source
)

select * from cleaned
