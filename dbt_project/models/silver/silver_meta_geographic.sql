-- Daily Meta (Facebook/Instagram) performance broken down by UK region.
-- Uses the region breakdown from the Meta Marketing API insights endpoint.
-- One row per (date, campaign, region).

with source as (
    select * from {{ source('bronze', 'meta_api_geographic_daily') }}
),

cleaned as (
    select
        parse_date('%Y-%m-%d', date)                as date,
        campaign_id,
        campaign_name,
        nullif(trim(region), '')                    as region,
        round(spend_gbp, 4)                         as spend_gbp,
        impressions,
        clicks,
        reach,
        case
            when lower(region) like '%yorkshire%'
                then 'Yorkshire'
            when lower(region) like '%tyne%'
              or lower(region) like '%wear%'
              or lower(region) like '%durham%'
              or lower(region) like '%northumberland%'
              or lower(region) like '%north east%'
              or lower(region) like '%cleveland%'
                then 'North East'
            when lower(region) like '%manchester%'
              or lower(region) like '%merseyside%'
              or lower(region) like '%lancashire%'
              or lower(region) like '%cheshire%'
              or lower(region) like '%cumbria%'
              or lower(region) like '%north west%'
                then 'North West'
            when lower(region) = 'scotland'
                then 'Scotland'
            when lower(region) = 'wales'
                then 'Wales'
            when lower(region) like '%london%'
                then 'London'
            when lower(region) like '%midlands%'
                then 'Midlands'
            when lower(region) like '%south west%'
              or lower(region) like '%cornwall%'
              or lower(region) like '%devon%'
              or lower(region) like '%somerset%'
              or lower(region) like '%dorset%'
                then 'South West'
            when lower(region) like '%east%england%'
              or lower(region) like '%east anglia%'
              or lower(region) like '%essex%'
              or lower(region) like '%suffolk%'
              or lower(region) like '%norfolk%'
              or lower(region) like '%hertfordshire%'
                then 'East of England'
            when lower(region) like '%south east%'
              or lower(region) like '%kent%'
              or lower(region) like '%surrey%'
              or lower(region) like '%sussex%'
              or lower(region) like '%hampshire%'
              or lower(region) like '%berkshire%'
              or lower(region) like '%oxfordshire%'
                then 'South East'
            else 'National'
        end                                         as rep_territory
    from source
    where spend_gbp > 0
      and region is not null
)

select * from cleaned
order by date desc, spend_gbp desc
