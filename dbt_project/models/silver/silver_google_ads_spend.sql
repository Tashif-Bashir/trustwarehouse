with source as (
    select * from {{ source('bronze', 'google_adscampaign') }}
),

-- Google Ads syncs intraday (partial spend) and end-of-day (final spend).
-- Summing across all syncs double-counts. Only use the latest sync batch
-- per date — defined as within 1 hour of the most recent extraction for that date.
latest_batch as (
    select s.*
    from source s
    inner join (
        select segments_date, max(_airbyte_extracted_at) as latest
        from source
        group by segments_date
    ) lb on s.segments_date = lb.segments_date
        and s._airbyte_extracted_at >= lb.latest - interval '1 hour'
),

daily as (
    select
        segments_date                                               as date,
        campaign_id,
        -- use any_value for stable campaign attributes (same per campaign per day)
        any_value(campaign_name)                                    as campaign_name,
        any_value(campaign_status)                                  as campaign_status,
        any_value(campaign_advertising_channel_type)                as channel_type,
        round(
            max(campaign_budget_amount_micros) / 1000000.0, 2
        )                                                           as daily_budget_gbp,

        -- aggregate hourly rows to daily totals
        sum(metrics_impressions)                                    as impressions,
        sum(metrics_clicks)                                         as clicks,
        round(sum(metrics_cost_micros) / 1000000.0, 4)             as spend_gbp,
        round(sum(metrics_conversions), 2)                          as conversions

    from latest_batch
    group by segments_date, campaign_id
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

        -- derived metrics (null-safe to avoid divide-by-zero)
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
