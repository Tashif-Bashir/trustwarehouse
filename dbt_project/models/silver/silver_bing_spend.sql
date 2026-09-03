with source as (
    -- Direct Bing Ads API sync (scripts/bing_ads_sync.py, VM timer 8x/day)
    -- replaced the Airbyte connection on 3 Sep 2026 after a 9-day parallel
    -- run matched it to the penny. Loads are delete-then-insert per date
    -- window, so unlike the Airbyte feed there are no duplicate syncs to
    -- dedupe — every row is current state.
    select * from {{ source('bronze', 'bing_direct_account_performance_report_daily') }}
),

-- Account-level daily report. Each row is one network/device/match-type
-- segment for the day; sum all segments per date.
daily as (
    select
        cast(timeperiod as date)            as date,
        any_value(accountname)              as account_name,
        any_value(currencycode)             as currency,

        round(sum(safe_cast(spend as FLOAT64)), 4)       as spend_gbp,
        sum(safe_cast(clicks as INT64))                  as clicks,
        sum(safe_cast(impressions as INT64))             as impressions,
        round(sum(safe_cast(conversions as FLOAT64)), 2) as conversions

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
