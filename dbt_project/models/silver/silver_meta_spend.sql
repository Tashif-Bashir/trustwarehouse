with source as (
    select * from {{ source('bronze', 'facebook_adsads_insights') }}
),

-- Airbyte re-pulls historical rows on each sync (Facebook attribution window updates).
-- Keep only the most recently extracted row per date+ad to avoid double-counting spend.
deduped as (
    select *
    from source
    qualify row_number() over (
        partition by date_start, ad_id
        order by _airbyte_extracted_at desc
    ) = 1
),

-- Aggregate ad-level rows up to campaign level daily
campaign_daily as (
    select
        date_start                          as date,
        campaign_id,
        any_value(campaign_name)            as campaign_name,
        any_value(objective)                as objective,
        any_value(account_currency)         as currency,

        sum(impressions)                    as impressions,
        sum(clicks)                         as clicks,
        sum(unique_clicks)                  as unique_clicks,
        round(sum(spend), 4)                as spend_gbp,
        sum(reach)                          as reach

    from deduped
    group by date_start, campaign_id
),

final as (
    select
        date,
        campaign_id,
        campaign_name,
        objective,
        currency,
        impressions,
        clicks,
        unique_clicks,
        spend_gbp,
        reach,

        case
            when impressions = 0 then null
            else round(clicks * 1.0 / impressions, 6)
        end                                 as ctr,

        case
            when clicks = 0 then null
            else round(spend_gbp / clicks, 4)
        end                                 as avg_cpc_gbp,

        case
            when reach = 0 then null
            else round(spend_gbp / reach * 1000, 4)
        end                                 as cpm_gbp

    from campaign_daily
)

select * from final
order by date desc, spend_gbp desc
