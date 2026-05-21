with source as (
    select * from {{ source('bronze', 'bing_adsaccount_performance_report_daily') }}
),

-- Bing Ads syncs run twice per day: once mid-day (partial) and once the next morning
-- (final). Both syncs write rows for the same TimePeriod date but with different
-- _airbyte_extracted_at values. We must use only the latest sync to avoid double-counting.
latest_sync_per_date as (
    select
        cast(timeperiod as date)            as report_date,
        max(date(_airbyte_extracted_at))    as latest_sync_date
    from source
    group by cast(timeperiod as date)
),

-- Account-level daily report. Each row is one network/device segment for the day.
-- Filter to latest sync only, then sum all segments per date.
daily as (
    select
        cast(s.timeperiod as date)          as date,
        any_value(s.accountname)            as account_name,
        any_value(s.currencycode)           as currency,

        round(sum(SAFE_CAST(s.spend AS FLOAT64)), 4)       as spend_gbp,
        sum(SAFE_CAST(s.clicks AS INT64))                  as clicks,
        sum(SAFE_CAST(s.impressions AS INT64))             as impressions,
        round(sum(SAFE_CAST(s.conversions AS FLOAT64)), 2) as conversions

    from source s
    inner join latest_sync_per_date l
        on cast(s.timeperiod as date) = l.report_date
        and date(s._airbyte_extracted_at) = l.latest_sync_date
    group by cast(s.timeperiod as date)
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
