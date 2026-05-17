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

-- Map SharpSpring campaign_id to the three paid platforms via seed file
lead_platform as (
    select
        l.lead_id,
        cast(l.created_at at time zone 'Europe/London' as date) as created_date,
        m.platform,
        l.appointment_booked,
        try_cast(l.appointment_booked_at as timestamp)          as appointment_booked_at,
        l.is_sold,
        try_cast(l.order_confirmed_at as timestamp)             as order_confirmed_at
    from {{ ref('silver_sharpspring_leads') }} l
    inner join {{ ref('campaign_platform_mapping') }} m
        on l.campaign_id = m.campaign_id
    where l.is_active = true
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

-- Sales confirmed per day per platform (date = order_confirmed_at, falling back to created_date)
daily_sales as (
    select
        coalesce(cast(order_confirmed_at as date), created_date) as date,
        platform,
        count(*)                                                  as sales
    from lead_platform
    where is_sold = true
    group by coalesce(cast(order_confirmed_at as date), created_date), platform
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
        coalesce(sv.sales, 0)                                   as sales,

        -- Cost per lead
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(s.spend_gbp / l.leads, 2)
        end                                                     as cost_per_lead,

        -- Cost per appointment
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(s.spend_gbp / a.appointments_booked, 2)
        end                                                     as cost_per_appointment,

        -- Cost per sale
        case
            when coalesce(sv.sales, 0) = 0 then null
            else round(s.spend_gbp / sv.sales, 2)
        end                                                     as cost_per_sale,

        -- Click to lead conversion rate
        case
            when s.clicks = 0 then null
            else round(coalesce(l.leads, 0) * 1.0 / s.clicks, 4)
        end                                                     as click_to_lead_rate,

        -- Lead to appointment rate
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(coalesce(a.appointments_booked, 0) * 1.0 / l.leads, 4)
        end                                                     as lead_to_appointment_rate,

        -- Appointment to sale rate
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(coalesce(sv.sales, 0) * 1.0 / a.appointments_booked, 4)
        end                                                     as appointment_to_sale_rate

    from platform_spend s
    left join daily_leads l
        on s.date = l.date and s.platform = l.platform
    left join daily_appointments a
        on s.date = a.date and s.platform = a.platform
    left join daily_sales sv
        on s.date = sv.date and s.platform = sv.platform
)

select * from final
order by date desc, spend_gbp desc
