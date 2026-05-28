with campaign_spend as (
    select
        segments_date                                   as date,
        campaign_budget_name,
        campaign_id,
        sum(metrics_cost_micros) / 1000000.0            as spend_gbp,
        sum(metrics_clicks)                             as clicks,
        sum(metrics_impressions)                        as impressions,
        sum(metrics_conversions)                        as conversions
    from {{ source('bronze', 'google_adscampaign_budget') }}
    where metrics_cost_micros > 0
    group by 1, 2, 3
),

with_region as (
    select
        date,
        campaign_budget_name,
        campaign_id,
        spend_gbp,
        clicks,
        impressions,
        conversions,

        case
            when lower(campaign_budget_name) like '%cornwall%'
              or lower(campaign_budget_name) like '%south west%'
            then 'South West'

            when lower(campaign_budget_name) like '%scotland%'
            then 'Scotland'

            when lower(campaign_budget_name) like '%wales%'
            then 'Wales'

            when lower(campaign_budget_name) like '%london%'
            then 'Greater London'

            when lower(campaign_budget_name) like '%north east%'
            then 'North East'

            when lower(campaign_budget_name) like '%yorkshire%'
            then 'Yorkshire'

            when lower(campaign_budget_name) like '%northern england%'
              or lower(campaign_budget_name) like '%north west%'
              or (lower(campaign_budget_name) like '%northern%'
                  and lower(campaign_budget_name) not like '%north east%')
            then 'Northern England'

            when lower(campaign_budget_name) like '%midlands%'
            then 'Midlands'

            when lower(campaign_budget_name) like '%east of england%'
              or lower(campaign_budget_name) like '%oxfordshire%'
              or lower(campaign_budget_name) like '%oxfordhsire%'
              or lower(campaign_budget_name) like '%eoe%'
            then 'East of England'

            else 'National'
        end                                             as region

    from campaign_spend
),

final as (
    select
        date,
        region,
        round(sum(spend_gbp), 2)                        as spend_gbp,
        sum(clicks)                                     as clicks,
        sum(impressions)                                 as impressions,
        sum(conversions)                                 as conversions,
        count(distinct campaign_id)                     as campaign_count
    from with_region
    group by 1, 2
)

select * from final
order by date desc, spend_gbp desc
