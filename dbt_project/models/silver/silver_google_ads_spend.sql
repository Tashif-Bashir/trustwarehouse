with source as (
    select * from {{ source('bronze', 'google_adscampaign') }}
),

-- Google Ads re-syncs historical rows on every Airbyte run (attribution window
-- updates). Keep only the most recently extracted row per unique hourly segment
-- so we never double-count when Airbyte syncs multiple times in one day.
deduped as (
    select *
    from source
    qualify row_number() over (
        partition by campaign_id, segments_date, segments_hour, segments_ad_network_type
        order by _airbyte_extracted_at desc
    ) = 1
),

-- Performance Max campaigns are reported by Google Ads API in one of two ways
-- depending on segmentation state at extraction time:
--   (a) a single `MIXED` rollup row containing the PMax daily total, OR
--   (b) multiple sub-network rows (DISCOVER, YOUTUBE, CONTENT, GMAIL, MAPS,
--       SEARCH_PARTNERS) that together sum to the PMax daily total.
-- Sometimes both representations end up in bronze for the same (campaign, date)
-- because Airbyte syncs at different times capture different states. Summing
-- them all double-counts. Search campaigns only ever emit SEARCH rows so they
-- are not affected.
--
-- Smart rule per (campaign, date):
--   - If a MIXED row exists, keep MIXED only (the rollup)
--   - Otherwise, keep the sub-network rows (which ARE the spend)
flagged as (
    select *,
        max(case when segments_ad_network_type = 'MIXED' then 1 else 0 end)
            over (partition by campaign_id, segments_date) as has_mixed
    from deduped
),

primary_network as (
    select * from flagged
    where (has_mixed = 1 and segments_ad_network_type = 'MIXED')
       or (has_mixed = 0 and segments_ad_network_type != 'MIXED')
),

daily as (
    select
        segments_date                                               as date,
        campaign_id,
        any_value(campaign_name)                                    as campaign_name,
        any_value(campaign_status)                                  as campaign_status,
        any_value(campaign_advertising_channel_type)                as channel_type,
        round(
            max(campaign_budget_amount_micros) / 1000000.0, 2
        )                                                           as daily_budget_gbp,

        sum(metrics_impressions)                                    as impressions,
        sum(metrics_clicks)                                         as clicks,
        round(sum(metrics_cost_micros) / 1000000.0, 4)             as spend_gbp,
        round(sum(metrics_conversions), 2)                          as conversions

    from primary_network
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
