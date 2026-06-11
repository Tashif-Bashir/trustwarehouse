with leads as (
    select
        DATE(sl.created_at, 'Europe/London')    as created_date,
        sl.lead_id,
        sl.derived_region,
        sl.sharpspring_region,
        sl.phone_region,
        sl.region,
        sl.postcode,
        sl.marketing_url,
        m.platform,
        sl.appointment_booked,
        sl.is_sold,

        -- extract utm_campaign from URL, lowercase and strip whitespace
        lower(trim(regexp_extract(sl.marketing_url, r'utm_campaign=([^&]+)'))) as utm_campaign

    from {{ ref('silver_sharpspring_leads') }} sl
    left join {{ ref('campaign_platform_mapping') }} m using (campaign_id)
    where sl.created_at is not null
),

with_utm_region as (
    select
        *,

        -- derive region from utm_campaign (covers Google + Meta regional campaigns)
        case
            when utm_campaign like '%northern%' or utm_campaign = 'northern'
                then 'Northern England'
            when utm_campaign like '%yorkshire%'
                then 'Yorkshire'
            when utm_campaign like '%scotland%'
                then 'Scotland'
            when utm_campaign like '%cornwall%' or utm_campaign like '%south-west%'
              or utm_campaign like '%southwest%'
                then 'South West'
            when utm_campaign like '%midlands%'
                then 'Midlands'
            when utm_campaign like '%northeast%' or utm_campaign like '%north-east%'
                then 'North East'
            when utm_campaign like '%london%'
                then 'Greater London'
            when utm_campaign like '%wales%'
                then 'Wales'
            when utm_campaign like '%eastofengland%' or utm_campaign like '%oxfordshire%'
              or utm_campaign like '%oxford%'
                then 'East of England'
            when utm_campaign like '%southeast%' or utm_campaign like '%south-east%'
                then 'South East'
        end as utm_region

    from leads
),

final as (
    select
        created_date,
        -- priority: 1) UTM campaign region, 2) postcode-derived region, 3) Unknown
        -- normalise postcode regions to match UTM naming (West/East Midlands → Midlands)
        coalesce(
            -- 1. postcode-derived region (actual address — most accurate)
            case derived_region
                when 'Yorkshire and The Humber'    then 'Yorkshire'
                when 'Yorkshire and the Humber'    then 'Yorkshire'
                when 'Yorkshire and Humber'        then 'Yorkshire'
                when 'West Midlands'               then 'Midlands'
                when 'East Midlands'               then 'Midlands'
                when 'Greater London'              then 'Greater London'
                when 'London'                      then 'Greater London'
                else derived_region
            end,
            -- 2. sharpspring region dropdown (~97% coverage since Aug 2025)
            sharpspring_region,
            -- 3. utm campaign name (campaign-level inference)
            utm_region,
            -- 4. phone area code → region (UK landlines are geographically coded)
            phone_region,
            -- 5. sharpspring state field — region names, county names, and city names
            --    (free-text; explicitly flag OOA entries; skip anything too ambiguous)
            case region
                -- official region names
                when 'North East'                  then 'North East'
                when 'North West'                  then 'North West'
                when 'Yorkshire and the Humber'    then 'Yorkshire'
                when 'Yorkshire and The Humber'    then 'Yorkshire'
                when 'Yorkshire'                   then 'Yorkshire'
                when 'East Midlands'               then 'Midlands'
                when 'West Midlands'               then 'Midlands'
                when 'Midlands'                    then 'Midlands'
                when 'East of England'             then 'East of England'
                when 'London'                      then 'Greater London'
                when 'Greater London'              then 'Greater London'
                when 'South East'                  then 'South East'
                when 'South West'                  then 'South West'
                when 'Wales'                       then 'Wales'
                when 'Scotland'                    then 'Scotland'
                when 'Northern Ireland'            then 'Northern Ireland'
                when 'Northern England'            then 'Northern England'
                -- typo fixes
                when 'Northen Ireland'             then 'Northern Ireland'
                when 'East of Englands'            then 'East of England'
                -- cities
                when 'Manchester'                  then 'North West'
                when 'Liverpool'                   then 'North West'
                when 'Rochdale'                    then 'North West'
                when 'Glasgow'                     then 'Scotland'
                when 'Birmingham'                  then 'Midlands'
                when 'Coventry'                    then 'Midlands'
                when 'Stoke-on-Trent'              then 'Midlands'
                when 'West Bromwich'               then 'Midlands'
                when 'Leeds'                       then 'Yorkshire'
                when 'Bradford'                    then 'Yorkshire'
                when 'Sheffield'                   then 'Yorkshire'
                when 'Wakefield'                   then 'Yorkshire'
                when 'Hull'                        then 'Yorkshire'
                when 'Stockton-on-Tees'            then 'North East'
                when 'Bristol'                     then 'South West'
                when 'Norwich'                     then 'East of England'
                when 'Luton'                       then 'East of England'
                when 'Swansea'                     then 'Wales'
                when 'North Wales'                 then 'Wales'
                when 'Tonbridge'                   then 'South East'
                when 'Croydon'                     then 'Greater London'
                when 'Hounslow'                    then 'Greater London'
                when 'Lambeth'                     then 'Greater London'
                when 'Brent'                       then 'Greater London'
                -- counties / historic counties
                when 'Devon'                       then 'South West'
                when 'Dorset'                      then 'South West'
                when 'Somerset'                    then 'South West'
                when 'Wiltshire'                   then 'South West'
                when 'Gloucestershire'             then 'South West'
                when 'Cornwall'                    then 'South West'
                when 'Kent'                        then 'South East'
                when 'Essex'                       then 'East of England'
                when 'Hertfordshire'               then 'East of England'
                when 'Bedfordshire'                then 'East of England'
                when 'Cambridgeshire'              then 'East of England'
                when 'Norfolk'                     then 'East of England'
                when 'Suffolk'                     then 'East of England'
                when 'Hampshire'                   then 'South East'
                when 'Surrey'                      then 'South East'
                when 'Berkshire'                   then 'South East'
                when 'Buckinghamshire'             then 'South East'
                when 'Oxfordshire'                 then 'South East'
                when 'East Sussex'                 then 'South East'
                when 'West Sussex'                 then 'South East'
                when 'Sussex'                      then 'South East'
                when 'Derbyshire'                  then 'Midlands'
                when 'Nottinghamshire'             then 'Midlands'
                when 'Lincolnshire'                then 'Midlands'
                when 'Leicestershire'              then 'Midlands'
                when 'Northamptonshire'            then 'Midlands'
                when 'Warwickshire'                then 'Midlands'
                when 'Worcestershire'              then 'Midlands'
                when 'Staffordshire'               then 'Midlands'
                when 'Shropshire'                  then 'Midlands'
                when 'Glossop'                     then 'Midlands'
                when 'West Yorkshire'              then 'Yorkshire'
                when 'South Yorkshire'             then 'Yorkshire'
                when 'North Yorkshire'             then 'Yorkshire'
                when 'East Yorkshire'              then 'Yorkshire'
                when 'Lancashire'                  then 'North West'
                when 'Cumbria'                     then 'North West'
                when 'Cheshire'                    then 'North West'
                when 'Greater Manchester'          then 'North West'
                when 'Merseyside'                  then 'North West'
                when 'Tyne and Wear'               then 'North East'
                when 'County Durham'               then 'North East'
                when 'Northumberland'              then 'North East'
                -- out of area — flag explicitly rather than treating as unknown
                when 'Ireland'                     then 'Outside UK'
                when 'Republic of Ireland'         then 'Outside UK'
                when 'ROI'                         then 'Outside UK'
                when 'Isle of Man'                 then 'Outside UK'
                when 'Isle of Mann'                then 'Outside UK'
            end,
            'Unknown'
        )                                                   as region,
        platform,
        count(distinct lead_id)                             as leads,
        count(distinct case when appointment_booked = 'Yes'
              then lead_id end)                             as appointments,
        count(distinct case when is_sold = true
              then lead_id end)                             as sales,
        count(distinct case when postcode is not null
              then lead_id end)                             as leads_with_postcode,
        count(distinct case when sharpspring_region is not null
              then lead_id end)                             as leads_with_ss_region,

        round(
            count(distinct case when appointment_booked = 'Yes'
                  then lead_id end) * 1.0
            / nullif(count(distinct lead_id), 0),
            4
        )                                                   as lead_to_appt_rate,

        round(
            count(distinct case when is_sold = true
                  then lead_id end) * 1.0
            / nullif(count(distinct case when appointment_booked = 'Yes'
                          then lead_id end), 0),
            4
        )                                                   as appt_to_sale_rate

    from with_utm_region
    group by 1, 2, 3
)

select * from final
order by created_date desc, leads desc
