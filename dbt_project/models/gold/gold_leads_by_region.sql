with leads as (
    select
        DATE(created_at, 'Europe/London')   as created_date,
        lead_id,
        derived_region                       as region,
        platform,
        appointment_booked,
        is_sold,
        postcode
    from {{ ref('silver_sharpspring_leads') }}
    left join {{ ref('campaign_platform_mapping') }}
        using (campaign_id)
    where created_at is not null
),

final as (
    select
        created_date,
        coalesce(region, 'Unknown')                                         as region,
        platform,
        count(distinct lead_id)                                             as leads,
        count(distinct case when appointment_booked = 'Yes'
              then lead_id end)                                             as appointments,
        count(distinct case when is_sold = true
              then lead_id end)                                             as sales,
        count(distinct case when postcode is not null
              then lead_id end)                                             as leads_with_postcode,

        -- conversion rates
        round(
            count(distinct case when appointment_booked = 'Yes'
                  then lead_id end) * 1.0
            / nullif(count(distinct lead_id), 0),
            4
        )                                                                   as lead_to_appt_rate,

        round(
            count(distinct case when is_sold = true
                  then lead_id end) * 1.0
            / nullif(count(distinct case when appointment_booked = 'Yes'
                          then lead_id end), 0),
            4
        )                                                                   as appt_to_sale_rate

    from leads
    group by 1, 2, 3
)

select * from final
order by created_date desc, leads desc
