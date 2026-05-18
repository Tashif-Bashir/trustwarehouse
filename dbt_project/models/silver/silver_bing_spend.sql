with source as (
    select * from {{ source('bronze', 'bing_adsaccount_performance_report_daily') }}
),

-- Account-level daily report. Each row is one network/device segment for the day.
-- A single Airbyte sync writes all rows with millisecond-apart extracted_at timestamps
-- (not truly separate syncs). Sum all segments per date — this matches the Bing Ads UI
-- account-level total.
daily as (
    select
        cast(timeperiod as date)            as date,
        any_value(accountname)              as account_name,
        any_value(currencycode)             as currency,

        round(sum(try_cast(spend as double)), 4)        as spend_gbp,
        sum(try_cast(clicks as bigint))                 as clicks,
        sum(try_cast(impressions as bigint))            as impressions,
        round(sum(try_cast(conversions as double)), 2)  as conversions

    from source
    group by cast(timeperiod as date)
),

final as (
    select
        date,
        account_name,
        currency,
        spend_gbp,
        clicks,
        impressions,
        conversions,

        case
            when impressions = 0 then null
            else round(clicks * 1.0 / impressions, 6)
        end                                 as ctr,

        case
            when clicks = 0 then null
            else round(spend_gbp / clicks, 4)
        end                                 as avg_cpc_gbp

    from daily
    where spend_gbp > 0
)

select * from final
order by date desc
