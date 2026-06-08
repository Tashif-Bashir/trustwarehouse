-- Daily Meta spend, one row per (date, campaign).
--
-- Reads from `bronze.meta_api_campaign_daily`, populated by our direct-API
-- ingestion (ingestion.meta). The previous Airbyte-based version needed
-- dedup because Airbyte's connector re-pulled rows on every sync as Meta's
-- attribution windows updated. The direct API uses replace disposition per
-- run, so there is only ever one row per (date, campaign) — no dedup needed.

with source as (
    select * from {{ source('bronze', 'meta_api_campaign_daily') }}
),

final as (
    select
        parse_date('%Y-%m-%d', date)                                as date,
        cast(campaign_id as string)                                 as campaign_id,
        campaign_name,
        objective,
        account_currency                                            as currency,

        impressions,
        clicks,
        unique_clicks,
        round(spend_gbp, 4)                                         as spend_gbp,
        reach,

        case
            when impressions = 0 or impressions is null then null
            else round(clicks * 1.0 / impressions, 6)
        end                                                         as ctr,

        case
            when clicks = 0 or clicks is null then null
            else round(spend_gbp / clicks, 4)
        end                                                         as avg_cpc_gbp,

        case
            when reach = 0 or reach is null then null
            else round(spend_gbp / reach * 1000, 4)
        end                                                         as cpm_gbp

    from source
)

select * from final
order by date desc, spend_gbp desc
