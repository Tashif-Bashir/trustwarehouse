with leads as (
    select
        lead_id,
        first_name,
        last_name,
        email,
        phone,
        mobile,
        phone_alt,
        created_at,
        updated_at,
        lead_status,
        domestic_lead_status,
        appointment_booked,
        appointment_booked_at,
        appointment_made_by,
        appointment_type,
        appointment_status,
        pipeline_category,

        -- raw strings cleaned in final
        appt_amount,
        deal_amount,
        order_confirmed,
        order_confirmed_at,

        -- derived columns from silver enriched CTE
        appointment_date,
        customer_type,
        is_sold,

        -- attribution
        campaign_id,
        gclid,
        marketing_url,

        -- UK local date of creation
        DATE(SAFE_CAST(created_at AS TIMESTAMP), 'Europe/London') as created_date,

        -- infer paid platform from UTM params / gclid when SharpSpring campaign_id is missing
        case
            when (gclid is not null and gclid != '')                                             then 'Google'
            when regexp_contains(lower(marketing_url), r'utm_source=google')
             and regexp_contains(lower(marketing_url), r'utm_medium=(cpc|ppc|paid)')            then 'Google'
            when regexp_contains(lower(marketing_url), r'gad_source=1')                         then 'Google'
            when regexp_contains(lower(marketing_url), r'fbclid=')                              then 'Meta'
            when regexp_contains(lower(marketing_url), r'utm_source=(facebook|instagram|meta|fb)')
             and regexp_contains(lower(marketing_url), r'utm_medium=(cpc|paid|paidsocial)')     then 'Meta'
            when regexp_contains(lower(marketing_url), r'utm_source=bing')
             and regexp_contains(lower(marketing_url), r'utm_medium=(cpc|ppc|paid)')            then 'Bing'
        end                                                                                      as inferred_platform

    from {{ ref('silver_sharpspring_leads') }}
    where is_active = true
      -- Exclude responseIQ click-to-call widget events. These are not lead
      -- acquisitions — they're tracking metadata that fires when someone
      -- interacts with the call-button widget on the website. The real lead
      -- (if a call happened) is in Wildix CDR. See is_tracking_artifact in
      -- silver_sharpspring_leads for the full definition.
      and is_tracking_artifact = false
    qualify row_number() over (partition by lead_id order by updated_at desc) = 1
),

-- outbound completed calls — one row per call_id.
-- silver_wildix_calls stores one row per *participant* in a call (transfer
-- chains create 2-3 rows per logical call), so we aggregate first to avoid
-- inflating total_call_attempts and qualified_conversations downstream.
--   talk_time = sum across participants (full conversation length)
--   agent_name = whoever spoke the longest
outbound_calls as (
    select
        any_value(remote_phone)                                              as remote_phone,
        TIMESTAMP_MILLIS(min(start_time))                                    as call_at,
        DATE(TIMESTAMP_MILLIS(min(start_time)), 'Europe/London')             as call_date,
        sum(talk_time_seconds)                                               as talk_time_seconds,
        array_agg(colleague_name order by talk_time_seconds desc limit 1)[offset(0)] as agent_name
    from {{ ref('silver_calls_unified') }}
    where direction = 'OUTBOUND'
      and call_status = 'COMPLETED'
      and remote_phone is not null
    group by call_id
),

-- match calls to leads via any normalised phone field
-- only count calls that happened after the lead was created
lead_calls as (
    select
        l.lead_id,
        c.call_at,
        c.call_date,
        c.talk_time_seconds,
        c.agent_name
    from leads l
    inner join outbound_calls c
        on (c.remote_phone = l.phone
            or c.remote_phone = l.mobile
            or c.remote_phone = l.phone_alt)
        and c.call_at >= SAFE_CAST(l.created_at AS TIMESTAMP)
    where l.phone is not null
        or l.mobile is not null
        or l.phone_alt is not null
),

-- per-lead call aggregates
call_metrics as (
    select
        lead_id,
        count(*)                                                                    as total_call_attempts,
        min(call_at)                                                                as first_call_at,
        max(call_at)                                                                as last_call_at,
        DATE(max(call_at))                                                          as last_call_date,
        ARRAY_AGG(agent_name IGNORE NULLS ORDER BY call_at DESC LIMIT 1)[SAFE_OFFSET(0)] as last_call_agent,
        COUNTIF(talk_time_seconds >= 120)                                           as qualified_conversations
    from lead_calls
    group by lead_id
),

final as (
    select
        l.lead_id,
        l.first_name,
        l.last_name,
        l.email,
        l.phone,
        l.created_at,
        l.created_date,
        l.lead_status,
        l.domestic_lead_status,
        l.appointment_booked,
        l.appointment_booked_at,
        l.appointment_date,
        l.appointment_made_by,
        l.appointment_type,
        l.appointment_status,
        l.customer_type,
        l.pipeline_category,
        l.campaign_id,

        -- Attribution: CRM mapping first, UTM/gclid fallback when campaign is unmapped.
        -- CRM mapping wins because the sales team trusts SharpSpring's manual assignment;
        -- UTM is the safety net that catches leads SharpSpring auto-bucketed by default.
        m.platform                                                                               as crm_platform,
        l.inferred_platform                                                                      as utm_platform,
        coalesce(m.platform, l.inferred_platform)                                                as platform,

        -- Data-quality flag — surface attribution conflicts for the team to review.
        case
            when m.platform is null and l.inferred_platform is null                                then 'clean'
            when m.platform is not null and l.inferred_platform is null                            then 'crm_no_utm'        -- CRM tagged paid, no UTM trail
            when m.platform is null and l.inferred_platform is not null                            then 'utm_only'         -- Unmapped CRM, UTM identified paid
            when m.platform = l.inferred_platform                                                  then 'agree'
            else 'disagree'                                                                                                 -- Both paid, different platforms
        end                                                                                       as qc_flag,


        -- call activity
        coalesce(cm.total_call_attempts, 0)                                         as total_call_attempts,
        cm.first_call_at,
        cm.last_call_at,
        cm.last_call_date,
        cm.last_call_agent,
        coalesce(cm.qualified_conversations, 0)                                     as qualified_conversations,

        -- time from lead created to first outbound call (minutes)
        -- null when the first call was on a different calendar day
        case
            when cm.first_call_at is null then null
            when DATE(cm.first_call_at) != l.created_date then null
            else CAST(TIMESTAMP_DIFF(cm.first_call_at, SAFE_CAST(l.created_at AS TIMESTAMP), MINUTE) AS FLOAT64)
        end                                                                         as mins_to_first_call,

        -- flags
        cm.first_call_at is not null                                                as has_been_called,
        coalesce(cm.qualified_conversations, 0) > 0                                 as has_qualified_conversation,

        -- quote amount: strip junk placeholder values (≤1) and non-castable strings
        case
            when SAFE_CAST(l.appt_amount AS NUMERIC) > 1
            then round(SAFE_CAST(l.appt_amount AS NUMERIC), 2)
        end                                                                         as quote_amount,

        -- deal amount: strip commas before cast
        case
            when SAFE_CAST(REGEXP_REPLACE(l.deal_amount, r',', '') AS NUMERIC) > 1
            then round(SAFE_CAST(REGEXP_REPLACE(l.deal_amount, r',', '') AS NUMERIC), 2)
        end                                                                         as deal_amount,

        -- order confirmed as boolean
        case
            when l.order_confirmed = 'Yes' then true
            when l.order_confirmed = 'No'  then false
        end                                                                         as order_confirmed,

        SAFE_CAST(l.order_confirmed_at AS TIMESTAMP)                                as order_confirmed_at,

        l.is_sold

    from leads l
    left join {{ ref('campaign_platform_mapping') }} m on l.campaign_id = m.campaign_id
    left join call_metrics cm on l.lead_id = cm.lead_id
)

select * from final
order by created_at desc
