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

-- Map SharpSpring campaign_id to the three paid platforms via seed file.
-- Falls back to UTM/gclid inference for leads the CRM misattributed to organic.
lead_platform as (
    select
        l.lead_id,
        DATE(SAFE_CAST(l.created_at AS TIMESTAMP), 'Europe/London')         as created_date,
        coalesce(
            m.platform,
            case
                when (l.gclid is not null and l.gclid != '')                then 'Google'
                when regexp_contains(lower(l.marketing_url), r'utm_source=google')
                 and regexp_contains(lower(l.marketing_url), r'utm_medium=(cpc|ppc|paid)')
                                                                            then 'Google'
                when regexp_contains(lower(l.marketing_url), r'gad_source=1')
                                                                            then 'Google'
                when regexp_contains(lower(l.marketing_url), r'utm_source=(facebook|instagram|meta)')
                 and regexp_contains(lower(l.marketing_url), r'utm_medium=(cpc|paid|paidsocial)')
                                                                            then 'Meta'
                when regexp_contains(lower(l.marketing_url), r'utm_source=bing')
                 and regexp_contains(lower(l.marketing_url), r'utm_medium=(cpc|ppc|paid)')
                                                                            then 'Bing'
            end
        )                                                                   as platform,
        l.appointment_booked,
        l.is_sold
    from {{ ref('silver_sharpspring_leads') }} l
    left join {{ ref('campaign_platform_mapping') }} m
        on l.campaign_id = m.campaign_id
    where l.is_active = true
),

-- Leads created per day per platform (organic leads have NULL platform — excluded here)
daily_leads as (
    select
        created_date                        as date,
        platform,
        count(distinct lead_id)             as leads
    from lead_platform
    where platform is not null
    group by created_date, platform
),

-- Appointments booked, cohorted by lead created_date (not appointment_booked_at —
-- 73% of appointments have no timestamp so the old filter silently dropped them).
daily_appointments as (
    select
        created_date                        as date,
        platform,
        count(distinct lead_id)             as appointments_booked
    from lead_platform
    where appointment_booked = 'Yes'
      and platform is not null
    group by created_date, platform
),

-- Sales cohorted by lead created_date.
daily_sales as (
    select
        created_date                        as date,
        platform,
        count(distinct lead_id)             as sales
    from lead_platform
    where is_sold = true
      and platform is not null
    group by created_date, platform
),

final as (
    select
        s.date,
        s.platform,
        s.spend_gbp,
        s.clicks,
        s.impressions,
        coalesce(l.leads, 0)                                                as leads,
        coalesce(a.appointments_booked, 0)                                  as appointments_booked,
        coalesce(sv.sales, 0)                                               as sales,

        -- Cost per lead
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(s.spend_gbp / l.leads, 2)
        end                                                                 as cost_per_lead,

        -- Cost per appointment
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(s.spend_gbp / a.appointments_booked, 2)
        end                                                                 as cost_per_appointment,

        -- Cost per sale
        case
            when coalesce(sv.sales, 0) = 0 then null
            else round(s.spend_gbp / sv.sales, 2)
        end                                                                 as cost_per_sale,

        -- Click to lead conversion rate
        case
            when s.clicks = 0 then null
            else round(coalesce(l.leads, 0) * 1.0 / s.clicks, 4)
        end                                                                 as click_to_lead_rate,

        -- Lead to appointment rate
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(coalesce(a.appointments_booked, 0) * 1.0 / l.leads, 4)
        end                                                                 as lead_to_appointment_rate,

        -- Appointment to sale rate
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(coalesce(sv.sales, 0) * 1.0 / a.appointments_booked, 4)
        end                                                                 as appointment_to_sale_rate

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
