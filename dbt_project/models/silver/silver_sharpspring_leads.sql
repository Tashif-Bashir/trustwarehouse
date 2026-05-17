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
        try_cast(lead_score as integer)                 as lead_score,
        try_cast(lead_score_weighted as double)         as lead_score_weighted,

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

        -- attribution
        nullif(trim(campaign_id), '')                                      as campaign_id,
        nullif(trim(tracking_id), '')                                      as tracking_id,
        nullif(trim(exact_marketing_campaign_64d0b4a09e91b), '')           as marketing_campaign,
        nullif(trim(exact_marketing_url_64d0bebced518), '')                as marketing_url,
        nullif(trim(gclid1_66dad68843cd4), '')                             as gclid,

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
        nullif(trim(appointment_made_by_65e1a90253305), '')               as appointment_made_by

    from source
),

-- derived classifications that depend on columns computed in cleaned
enriched as (
    select
        *,

        -- clean date of the scheduled appointment (text field has empty strings — TRY_CAST handles them)
        try_cast(appointment_datetime_text as date)                             as appointment_date,

        -- domestic vs commercial: map free-text self_described_type to a clean enum
        case
            when self_described_type ilike '%residential%'
              or self_described_type ilike '%home owner%'
              or self_described_type ilike '%sheltered%'
              or self_described_type ilike '%housing tenant%'
            then 'domestic'
            when self_described_type is not null
            then 'commercial'
        end                                                                     as customer_type,

        -- sale flag: all appointment_status values that mean a win
        -- coalesce handles NULL appointment_status → false, never NULL
        coalesce(appointment_status in (
            'sold', 'sold on site', 'sold in office', 'chc sold'
        ), false)                                                               as is_sold

    from cleaned
)

select * from enriched
