-- Daily Google Ads performance by actual user location (where the user physically was).
-- Joins criterion IDs to human-readable names via the geo_target_constants lookup table.
-- One row per (date, campaign, most_specific_location).
-- USER_LOCATION only — excludes LOCATION_OF_PRESENCE (search intent) rows.

with geo as (
    select * from {{ source('bronze', 'google_ads_api_geographic_daily') }}
),

targets as (
    select criterion_id, name, target_type, canonical_name
    from {{ source('bronze', 'google_ads_api_geo_target_constants') }}
),

joined as (
    select
        parse_date('%Y-%m-%d', g.date)                              as date,
        g.campaign_id,
        g.campaign_name,
        g.most_specific_criterion_id,
        coalesce(t_city.name, t_most.name)                          as location_name,
        coalesce(t_city.canonical_name, t_most.canonical_name)      as location_canonical,
        t_region.name                                               as region_name,
        t_region.canonical_name                                     as region_canonical,
        sum(g.impressions)                                          as impressions,
        sum(g.clicks)                                               as clicks,
        round(sum(g.spend_gbp), 4)                                  as spend_gbp,
        round(sum(g.conversions), 2)                                as conversions,
        round(sum(g.conversions_value), 2)                          as conversions_value
    from geo g
    left join targets t_city  on g.city_criterion_id             = t_city.criterion_id
    left join targets t_most  on g.most_specific_criterion_id    = t_most.criterion_id
    left join targets t_region on g.region_criterion_id          = t_region.criterion_id
    group by 1, 2, 3, 4, 5, 6, 7, 8
),

with_territory as (
    select
        *,
        case
            when lower(region_name) like '%yorkshire%'
                then 'Yorkshire'
            when lower(region_name) like '%tyne%'
              or lower(region_name) like '%wear%'
              or lower(region_name) like '%durham%'
              or lower(region_name) like '%northumberland%'
              or lower(region_name) like '%north east%'
              or lower(region_name) like '%cleveland%'
                then 'North East'
            when lower(region_name) like '%manchester%'
              or lower(region_name) like '%merseyside%'
              or lower(region_name) like '%lancashire%'
              or lower(region_name) like '%cheshire%'
              or lower(region_name) like '%cumbria%'
              or lower(region_name) like '%north west%'
                then 'North West'
            when lower(region_name) = 'scotland'
                then 'Scotland'
            when lower(region_name) = 'wales'
                then 'Wales'
            when lower(region_name) like '%london%'
                then 'London'
            when lower(region_name) like '%midlands%'
              or lower(region_name) in ('derbyshire', 'nottinghamshire', 'leicestershire',
                                       'lincolnshire', 'northamptonshire', 'staffordshire',
                                       'warwickshire', 'worcestershire', 'shropshire')
                then 'Midlands'
            when lower(region_name) like '%south west%'
              or lower(region_name) in ('devon', 'cornwall', 'somerset', 'dorset',
                                       'wiltshire', 'gloucestershire', 'bristol')
                then 'South West'
            when lower(region_name) like '%east%england%'
              or lower(region_name) like '%east anglia%'
              or lower(region_name) in ('essex', 'suffolk', 'norfolk', 'cambridgeshire',
                                       'bedfordshire', 'hertfordshire', 'buckinghamshire')
                then 'East of England'
            when lower(region_name) like '%south east%'
              or lower(region_name) in ('kent', 'surrey', 'east sussex', 'west sussex',
                                       'hampshire', 'berkshire', 'oxfordshire')
                then 'South East'
            else 'National'
        end as rep_territory
    from joined
)

select * from with_territory
order by date desc, spend_gbp desc
