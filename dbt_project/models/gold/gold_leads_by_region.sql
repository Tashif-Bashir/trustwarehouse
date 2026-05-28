with leads as (
    select
        DATE(sl.created_at, 'Europe/London')    as created_date,
        sl.lead_id,
        sl.derived_region,
        sl.postcode,
        sl.marketing_url,
        m.platform,
        sl.appointment_booked,
        sl.is_sold,

        -- extract utm_campaign from URL, lowercase and strip whitespace
        lower(trim(regexp_extract(sl.marketing_url, r'utm_campaign=([^&]+)'))) as utm_campaign

    from {{ ref('silver_sharpspring_leads') }} sl
    left join {{ ref('campaign_platform_mapping') }} m using (campaign_id)
    where sl.created_at is not null
),

with_utm_region as (
    select
        *,

        -- derive region from utm_campaign (covers Google + Meta regional campaigns)
        case
            when utm_campaign like '%northern%' or utm_campaign = 'northern'
                then 'Northern England'
            when utm_campaign like '%yorkshire%'
                then 'Yorkshire'
            when utm_campaign like '%scotland%'
                then 'Scotland'
            when utm_campaign like '%cornwall%' or utm_campaign like '%south-west%'
              or utm_campaign like '%southwest%'
                then 'South West'
            when utm_campaign like '%midlands%'
                then 'Midlands'
            when utm_campaign like '%northeast%' or utm_campaign like '%north-east%'
                then 'North East'
            when utm_campaign like '%london%'
                then 'Greater London'
            when utm_campaign like '%wales%'
                then 'Wales'
            when utm_campaign like '%eastofengland%' or utm_campaign like '%oxfordshire%'
              or utm_campaign like '%oxford%'
                then 'East of England'
            when utm_campaign like '%southeast%' or utm_campaign like '%south-east%'
                then 'South East'
        end as utm_region

    from leads
),

final as (
    select
        created_date,
        -- priority: 1) UTM campaign region, 2) postcode-derived region, 3) Unknown
        coalesce(utm_region, derived_region, 'Unknown')     as region,
        platform,
        count(distinct lead_id)                             as leads,
        count(distinct case when appointment_booked = 'Yes'
              then lead_id end)                             as appointments,
        count(distinct case when is_sold = true
              then lead_id end)                             as sales,
        count(distinct case when postcode is not null
              then lead_id end)                             as leads_with_postcode,

        round(
            count(distinct case when appointment_booked = 'Yes'
                  then lead_id end) * 1.0
            / nullif(count(distinct lead_id), 0),
            4
        )                                                   as lead_to_appt_rate,

        round(
            count(distinct case when is_sold = true
                  then lead_id end) * 1.0
            / nullif(count(distinct case when appointment_booked = 'Yes'
                          then lead_id end), 0),
            4
        )                                                   as appt_to_sale_rate

    from with_utm_region
    group by 1, 2, 3
)

select * from final
order by created_date desc, leads desc
