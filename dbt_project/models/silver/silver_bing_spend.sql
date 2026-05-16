with source as (
    select * from {{ source('bronze', 'bing_adscampaign_performance_report_daily') }}
),

-- Bing reports segment each campaign row by network, device, matchtype, and placement.
-- Deduplicate the 3 known Airbyte micro-duplicates, then sum across all segments
-- to get one row per campaign per day.
deduped as (
    select *
    from source
    qualify row_number() over (
        partition by timeperiod, campaignid, network, devicetype,
                     bidmatchtype, deliveredmatchtype, addistribution, topvsother
        order by _airbyte_extracted_at desc
    ) = 1
),

campaign_daily as (
    select
        timeperiod                          as date,
        campaignid                          as campaign_id,
        any_value(campaignname)             as campaign_name,
        any_value(campaigntype)             as campaign_type,
        any_value(campaignstatus)           as campaign_status,
        any_value(currencycode)             as currency,

        sum(impressions)                    as impressions,
        sum(clicks)                         as clicks,
        round(sum(spend), 4)                as spend_gbp,
        round(sum(conversions), 2)          as conversions

    from deduped
    group by timeperiod, campaignid
),

final as (
    select
        date,
        campaign_id,
        campaign_name,
        campaign_type,
        campaign_status,
        currency,
        impressions,
        clicks,
        spend_gbp,
        conversions,

        case
            when impressions = 0 then null
            else round(clicks * 1.0 / impressions, 6)
        end                                 as ctr,

        case
            when clicks = 0 then null
            else round(spend_gbp / clicks, 4)
        end                                 as avg_cpc_gbp

    from campaign_daily
)

select * from final
order by date desc, spend_gbp desc
