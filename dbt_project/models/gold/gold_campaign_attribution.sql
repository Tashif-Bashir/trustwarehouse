-- Platform-level daily attribution.
-- SharpSpring tags leads at platform level (Google Ads / Facebook / Bing Ads),
-- not individual campaign level, so this is the finest grain available.
-- Appointments and sales live in gold_lead_activity / gold_agent_performance_daily.

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

-- Read the canonical paid-platform attribution from gold_lead_activity, which
-- already applies the hybrid CRM-first + UTM-fallback rule and excludes
-- tracking artifacts. This keeps the dashboard's CPL formula in sync with
-- the Leads Breakdown donut (both now use identical lead-counting logic).
--
-- Previously this CTE did its own CRM-only join against campaign_platform_mapping,
-- which under-counted paid leads when SharpSpring assigned a paid click to an
-- organic campaign_id (a common CRM data-quality issue). The UTM fallback in
-- gold_lead_activity catches those cases.
lead_platform as (
    select
        la.lead_id,
        la.created_date,
        la.platform
    from {{ ref('gold_lead_activity') }} la
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

final as (
    select
        s.date,
        s.platform,
        s.spend_gbp,
        s.clicks,
        s.impressions,
        coalesce(l.leads, 0)                                                as leads,

        -- Cost per lead
        case
            when coalesce(l.leads, 0) = 0 then null
            else round(s.spend_gbp / l.leads, 2)
        end                                                                 as cost_per_lead,

        -- Click to lead conversion rate
        case
            when s.clicks = 0 then null
            else round(coalesce(l.leads, 0) * 1.0 / s.clicks, 4)
        end                                                                 as click_to_lead_rate

    from platform_spend s
    left join daily_leads l
        on s.date = l.date and s.platform = l.platform
)

select * from final
order by date desc, spend_gbp desc
