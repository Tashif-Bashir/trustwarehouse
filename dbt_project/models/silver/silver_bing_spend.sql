with source as (
    select * from {{ source('bronze', 'bing_adscampaign_performance_report_daily') }}
),

-- Bing syncs intraday (partial spend) and end-of-day (full spend).
-- Only use rows from the latest sync batch per date — defined as within
-- 1 hour of the most recent extraction for that timeperiod.
latest_batch as (
    select s.*
    from source s
    inner join (
        select timeperiod, max(_airbyte_extracted_at) as latest
        from source
        group by timeperiod
    ) lb on s.timeperiod = lb.timeperiod
        and s._airbyte_extracted_at >= lb.latest - interval '1 hour'
),

-- Bing Performance Max campaigns emit multiple rows per segment combination
-- within a single sync (milliseconds apart), with only one row carrying the
-- actual spend — the others are zero. Taking max(spend) per segment handles this
-- without needing to identify which specific row is correct.
deduped as (
    select
        timeperiod,
        campaignid,
        network,
        devicetype,
        bidmatchtype,
        deliveredmatchtype,
        addistribution,
        topvsother,
        any_value(campaignname)     as campaignname,
        any_value(campaigntype)     as campaigntype,
        any_value(campaignstatus)   as campaignstatus,
        any_value(currencycode)     as currencycode,
        max(impressions)            as impressions,
        max(clicks)                 as clicks,
        max(spend)                  as spend,
        max(conversions)            as conversions
    from latest_batch
    group by
        timeperiod, campaignid, network, devicetype,
        bidmatchtype, deliveredmatchtype, addistribution, topvsother
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
