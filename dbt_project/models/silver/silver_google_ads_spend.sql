-- Daily Google Ads spend, one row per (date, campaign).
--
-- Reads from `bronze.google_ads_api_campaign_daily`, which our direct-API
-- ingestion (ingestion.google_ads) produces. The previous Airbyte-based
-- version of this model needed heavy dedup and PMax MIXED/sub-network
-- handling because Airbyte's connector returned both rollup and component
-- rows for PMax campaigns. The direct API only returns sub-network rows for
-- PMax, summing to the same daily total — no dedup needed.

with source as (
    select * from {{ source('bronze', 'google_ads_api_campaign_daily') }}
),

daily as (
    select
        parse_date('%Y-%m-%d', date)                                as date,
        cast(campaign_id as string)                                 as campaign_id,
        any_value(campaign_name)                                    as campaign_name,
        any_value(campaign_status)                                  as campaign_status,
        any_value(channel_type)                                     as channel_type,
        round(max(budget_micros) / 1000000.0, 2)                    as daily_budget_gbp,

        sum(impressions)                                            as impressions,
        sum(clicks)                                                 as clicks,
        round(sum(spend_gbp), 4)                                    as spend_gbp,
        round(sum(conversions), 2)                                  as conversions

    from source
    group by 1, 2
),

final as (
    select
        date,
        campaign_id,
        campaign_name,
        campaign_status,
        channel_type,
        daily_budget_gbp,
        impressions,
        clicks,
        spend_gbp,
        conversions,

        case
            when impressions = 0 then null
            else round(clicks * 1.0 / impressions, 6)
        end                                                         as ctr,

        case
            when clicks = 0 then null
            else round(spend_gbp / clicks, 4)
        end                                                         as avg_cpc_gbp

    from daily
)

select * from final
order by date desc, spend_gbp desc
