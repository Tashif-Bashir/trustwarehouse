with source as (
    select * from {{ source('bronze', 'sharpspring_leads') }}
),

cleaned as (
    select
        -- identity
        id                                              as lead_id,
        account_id,
        owner_id,

        -- contact
        first_name,
        last_name,
        nullif(trim(email_address), '')                 as email,
        {{ normalise_phone('nullif(trim(phone_number), \'\')') }}          as phone,
        {{ normalise_phone('nullif(trim(mobile_phone_number), \'\')') }}   as mobile,
        {{ normalise_phone('nullif(trim(alternative_phone_number_5af46947e2fc1), \'\')') }} as phone_alt,
        nullif(trim(company_name), '')                  as company,
        nullif(trim(website), '')                       as website,

        -- timestamps
        create_timestamp                                as created_at,
        update_timestamp                                as updated_at,

        -- lifecycle
        active = '1'                                    as is_active,
        is_qualified = '1'                              as is_qualified,
        is_contact = '1'                                as is_contact,
        is_customer = '1'                               as is_customer,
        nullif(trim(status), '')                        as status_code,
        nullif(trim(lead_status), '')                   as lead_status,
        is_unsubscribed = '1'                           as is_unsubscribed,
        nullif(trim(persona), '')                       as persona,

        -- scoring
        SAFE_CAST(lead_score AS INT64)                 as lead_score,
        SAFE_CAST(lead_score_weighted AS FLOAT64)         as lead_score_weighted,

        -- geography
        nullif(trim(street), '')                        as street,
        nullif(trim(city), '')                          as city,
        nullif(trim(state), '')                         as region,
        nullif(trim(zipcode), '')                                           as postcode,
        nullif(trim(post_code_5af30a907e7c3), '')       as postcode_raw,
        nullif(trim(country), '')                       as country,

        -- appointment
        appointment_time___date_5ae8ca2f532bc                              as appointment_datetime,
        nullif(trim(appointment_time___date_5ae8ca2f532bc__v_text), '')    as appointment_datetime_text,
        nullif(trim(appointment_booked_5ae8cb01a35c6), '')                 as appointment_booked,
        nullif(trim(type_of_appointment_606ee2f254f4d), '')                as appointment_type,
        nullif(trim(appointment_status_637f8d6fa1096), '')                 as appointment_status,
        nullif(trim(date_time_appointment_booked_687fabb701341), '')       as appointment_booked_at,

        -- sales
        nullif(trim(order_confirmed_606ee9ff0c371), '')                    as order_confirmed,
        nullif(trim("order_confirmed___1___680b98aac02e0"), '')            as order_confirmed_new,
        nullif(trim(order_confirmed_timestamp_691b939cbd9dc), '')          as order_confirmed_at,
        nullif(trim(order_confirmed_sale_month_691b9de17d340), '')         as order_sale_month,
        nullif(trim(product_bought_5b75a2394323e), '')                     as product_bought,
        nullif(trim(sale_month_690b6f96accc2), '')                         as sale_month,
        nullif(trim(appt_amount_6911cfa5427cc), '')                        as appt_amount,
        nullif(trim(amount_688886934080a), '')                             as deal_amount,
        nullif(trim(finance_option_69f4ab5abb7ea), '')                     as finance_option,
        nullif(trim(in_out_hours_68c7d2ea31742), '')                       as in_out_hours,
        nullif(trim(conversion_with_691207769e23f), '')                    as converted_by,

        -- pipeline
        nullif(trim("domestic_lead_status___1___64256c8b9804a"), '')       as domestic_lead_status,
        nullif(trim("domestic_lead_status___1___69b1915ca5bb7"), '')       as lead_temperature,
        nullif(trim(chc_lead_status_65c4eb8949156), '')                    as chc_lead_status,
        nullif(trim("pipeline_category___688730404401e"), '')              as pipeline_category,
        nullif(trim("pipeline_category___1___6887308047284"), '')          as enquiry_month,
        nullif(trim(appointment_probability_69398791eec24), '')            as appointment_probability,
        nullif(trim(appointment_predicted_sale_month_69398a3faa258), '')   as predicted_sale_month,

        -- installation
        nullif(trim(installation_date_606eeaba66035), '')                  as installation_date,
        nullif(trim("installation_date_confirmed___606eeaa000f9b"), '')    as installation_confirmed,
        nullif(trim(electrician_needed_606ef17b0c8ea), '')                 as electrician_needed,
        nullif(trim(installed_by_66e44119364b0), '')                       as installed_by,

        -- geography (sharpspring region dropdown — high coverage since Aug 2025)
        case nullif(trim(location_6349396e4a08d), '')
            when 'North East'                  then 'North East'
            when 'North West'                  then 'North West'
            when 'Yorkshire and the Humber'    then 'Yorkshire'
            when 'East Midlands'               then 'Midlands'
            when 'West Midlands'               then 'Midlands'
            when 'East of England'             then 'East of England'
            when 'London'                      then 'Greater London'
            when 'South East'                  then 'South East'
            when 'South West'                  then 'South West'
            when 'Wales'                       then 'Wales'
            when 'Scotland'                    then 'Scotland'
            when 'Northern Ireland'            then 'Northern Ireland'
            -- 'England' and 'Ireland' are too broad — treat as null
        end                                                                as sharpspring_region,

        -- attribution
        nullif(trim(campaign_id), '')                                      as campaign_id,
        nullif(trim(tracking_id), '')                                      as tracking_id,
        nullif(trim(exact_marketing_campaign_64d0b4a09e91b), '')           as marketing_campaign,
        nullif(trim(exact_marketing_url_64d0bebced518), '')                as marketing_url,
        nullif(trim(gclid1_66dad68843cd4), '')                             as gclid,

        -- utm parameters parsed from landing page url
        regexp_extract(
            nullif(trim(exact_marketing_url_64d0bebced518), ''),
            r'[?&]utm_source=([^&#]+)'
        )                                                                  as utm_source,
        regexp_extract(
            nullif(trim(exact_marketing_url_64d0bebced518), ''),
            r'[?&]utm_medium=([^&#]+)'
        )                                                                  as utm_medium,
        regexp_extract(
            nullif(trim(exact_marketing_url_64d0bebced518), ''),
            r'[?&]utm_campaign=([^&#]+)'
        )                                                                  as utm_campaign,
        regexp_extract(
            nullif(trim(exact_marketing_url_64d0bebced518), ''),
            r'[?&]utm_content=([^&#]+)'
        )                                                                  as utm_content,
        regexp_extract(
            nullif(trim(exact_marketing_url_64d0bebced518), ''),
            r'[?&]utm_term=([^&#]+)'
        )                                                                  as utm_term,

        -- lead metadata
        nullif(trim(salutation_5af592e1e2374), '')                         as salutation,
        nullif(trim(job_role_5b10173f73ab9), '')                           as job_role,
        nullif(trim(what_describes_you_best___5af4635bf04dd), '')          as self_described_type,
        nullif(trim(message_5af30a9083007), '')                            as form_message,
        nullif(trim(enquiry_content_69fceffd80c27), '')                    as enquiry_content,
        nullif(trim(description), '')                                      as notes,
        nullif(trim(follow_up_date_66cefb6937225), '')                     as follow_up_date,
        nullif(trim(call_marker_notes_66d87ecd74673), '')                  as call_notes,
        nullif(trim(type_of_heating___6317101eeda5b), '')                  as heating_type,
        nullif(trim("lead_warmth___1___69ea236712886"), '')                as enquiry_type,
        nullif(trim(page_submitted_5af30a9090796), '')                     as form_page,
        nullif(trim(appointment_made_by_65e1a90253305), '')                as appointment_made_by,

        -- Service classification — the SharpSpring "what service do you need" field.
        -- Note: the column name `lead_warmth___1___69ea236712886` looks misleading
        -- but the actual values are: 'Heating' | 'Water' | 'Heating and Water' | NULL.
        -- The `enquiry_type` column above mis-quotes this identifier (BigQuery treats
        -- "..." as a string literal), so it always returns the literal name. We add
        -- correctly-quoted columns here without touching the legacy one.
        nullif(trim(`lead_warmth___1___69ea236712886`), '')                 as service_type,
        coalesce(`lead_warmth___1___69ea236712886` in ('Water', 'Heating and Water'), false)
                                                                            as is_water_lead,

        -- Tracking-artifact flag — ResponseIQ call tracking creates a SharpSpring
        -- lead for every inbound call. If the call came via a paid ad the record
        -- has a gclid (Google) or tracking_id (Bing/other) — those ARE real paid
        -- leads and must be counted. Only flag as artifact when there is no paid
        -- click ID, meaning the call was direct/organic and the lead is already
        -- captured in Wildix CDR.
        coalesce(
            REGEXP_CONTAINS(LOWER(COALESCE(description, '')), r'^responseiq:')
            AND (gclid1_66dad68843cd4 IS NULL OR TRIM(gclid1_66dad68843cd4) = '')
            AND (tracking_id IS NULL OR TRIM(tracking_id) = '')
            AND (campaign_id IS NULL OR TRIM(campaign_id) = ''),
            false
        )                                                                   as is_tracking_artifact

    from source
),

postcode_lookup as (
    select * from {{ ref('postcode_area_region') }}
),

-- derived classifications that depend on columns computed in cleaned
enriched as (
    select
        c.*,
        pc.uk_region as derived_region,

        -- phone area code → region (landlines only; mobiles 447xxx have no geographic coding)
        {{ phone_region('c.phone', 'c.mobile') }}                               as phone_region,

        -- UK-local date when the appointment is scheduled to sit. The
        -- previous version parsed `appointment_datetime_text` (the __v_text
        -- variant) which SharpSpring leaves empty — so this column was NULL
        -- for every lead lifetime. We now parse the actual timestamp column.
        DATE(SAFE_CAST(appointment_datetime AS TIMESTAMP), 'Europe/London')     as appointment_date,

        -- domestic vs commercial: map free-text self_described_type to a clean enum
        case
            when LOWER(self_described_type) like '%residential%'
              or LOWER(self_described_type) like '%home owner%'
              or LOWER(self_described_type) like '%sheltered%'
              or LOWER(self_described_type) like '%housing tenant%'
            then 'domestic'
            when self_described_type is not null
            then 'commercial'
        end                                                                     as customer_type,

        -- sale flag: all appointment_status values that mean a win
        -- coalesce handles NULL appointment_status → false, never NULL
        coalesce(appointment_status in (
            'sold', 'sold on site', 'sold in office', 'chc sold'
        ), false)                                                               as is_sold

    from cleaned c
    left join postcode_lookup pc
        on regexp_extract(upper(coalesce(c.postcode, c.postcode_raw)), r'^([A-Z]+)') = pc.postcode_area
)

select * from enriched
