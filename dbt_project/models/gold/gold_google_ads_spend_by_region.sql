with campaign_spend as (
    select
        date,
        campaign_id,
        campaign_name,
        spend_gbp,
        clicks,
        impressions,
        conversions
    from {{ ref('silver_google_ads_spend') }}
    where spend_gbp > 0
),

with_region as (
    select
        date,
        campaign_id,
        campaign_name,
        spend_gbp,
        clicks,
        impressions,
        conversions,

        case
            when lower(campaign_name) like '%cornwall%'
              or lower(campaign_name) like '%south west%'
            then 'South West'

            when lower(campaign_name) like '%scotland%'
            then 'Scotland'

            when lower(campaign_name) like '%wales%'
            then 'Wales'

            when lower(campaign_name) like '%london%'
            then 'Greater London'

            when lower(campaign_name) like '%north east%'
            then 'North East'

            when lower(campaign_name) like '%yorkshire%'
            then 'Yorkshire'

            when lower(campaign_name) like '%northern england%'
              or lower(campaign_name) like '%north west%'
              or (lower(campaign_name) like '%northern%'
                  and lower(campaign_name) not like '%north east%')
            then 'Northern England'

            when lower(campaign_name) like '%midlands%'
            then 'Midlands'

            when lower(campaign_name) like '%east of england%'
              or lower(campaign_name) like '%oxfordshire%'
              or lower(campaign_name) like '%oxfordhsire%'
              or lower(campaign_name) like '%eoe%'
            then 'East of England'

            else 'National'
        end as region

    from campaign_spend
),

final as (
    select
        date,
        region,
        round(sum(spend_gbp), 2)        as spend_gbp,
        sum(clicks)                      as clicks,
        sum(impressions)                 as impressions,
        sum(conversions)                 as conversions,
        count(distinct campaign_id)      as campaign_count
    from with_region
    group by 1, 2
)

select * from final
order by date desc, spend_gbp desc
