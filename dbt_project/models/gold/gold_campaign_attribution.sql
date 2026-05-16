-- Platform-level daily attribution.
-- SharpSpring tags leads at platform level (Google Ads / Facebook / Bing Ads),
-- not individual campaign level, so this is the finest grain available.

with google_spend as (
    select
        date,
        'Google'                            as platform,
        round(sum(spend_gbp), 2)            as spend_gbp,
        sum(clicks)                         as clicks,
        sum(impressions)                    as impressions
    from {{ ref('silver_google_ads_spend') }}
    group by date
),

meta_spend as (
    select
        date,
        'Meta'                              as platform,
        round(sum(spend_gbp), 2)            as spend_gbp,
        sum(clicks)                         as clicks,
        sum(impressions)                    as impressions
    from {{ ref('silver_meta_spend') }}
    group by date
),

bing_spend as (
    select
        date,
        'Bing'                              as platform,
        round(sum(spend_gbp), 2)            as spend_gbp,
        sum(clicks)                         as clicks,
        sum(impressions)                    as impressions
    from {{ ref('silver_bing_spend') }}
    group by date
),

platform_spend as (
    select * from google_spend
    union all
    select * from meta_spend
    union all
    select * from bing_spend
),

-- Map SharpSpring campaign_id to the three paid platforms
lead_platform as (
    select
        lead_id,
        cast(created_at at time zone 'Europe/London' as date)   as created_date,
        case
            when campaign_id = '651768834'       then 'Google'
            when campaign_id = '672567298'       then 'Meta'
            when campaign_id = '200000012314626' then 'Bing'
        end                                                      as platform,
        appointment_booked,
        try_cast(appointment_booked_at as timestamp)             as appointment_booked_at
    from {{ ref('silver_sharpspring_leads') }}
    where campaign_id in ('651768834', '672567298', '200000012314626')
      and is_active = true
),

-- Leads created per day per platform
daily_leads as (
    select
        created_date                        as date,
        platform,
        count(*)                            as leads
    from lead_platform
    group by created_date, platform
),

-- Appointments booked per day per platform
-- date = when the appointment was booked, not when the lead came in
daily_appointments as (
    select
        cast(appointment_booked_at as date) as date,
        platform,
        count(*)                            as appointments_booked
    from lead_platform
    where appointment_booked = 'Yes'
      and appointment_booked_at is not null
    group by cast(appointment_booked_at as date), platform
),

final as (
    select
        s.date,
        s.platform,
        s.spend_gbp,
        s.clicks,
        s.impressions,
        coalesce(l.leads, 0)                                    as leads,
        coalesce(a.appointments_booked, 0)                      as appointments_booked,

        -- Cost per lead (spend on day X / leads acquired on day X)
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(s.spend_gbp / l.leads, 2)
        end                                                     as cost_per_lead,

        -- Cost per appointment (spend on day X / appointments booked on day X)
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(s.spend_gbp / a.appointments_booked, 2)
        end                                                     as cost_per_appointment,

        -- Click to lead conversion rate
        case
            when s.clicks = 0 then null
            else round(coalesce(l.leads, 0) * 1.0 / s.clicks, 4)
        end                                                     as click_to_lead_rate

    from platform_spend s
    left join daily_leads l
        on s.date = l.date and s.platform = l.platform
    left join daily_appointments a
        on s.date = a.date and s.platform = a.platform
)

select * from final
order by date desc, spend_gbp desc
