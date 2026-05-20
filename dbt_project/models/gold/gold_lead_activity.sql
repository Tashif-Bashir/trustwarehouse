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

        -- UK local date of creation
        DATE(SAFE_CAST(created_at AS TIMESTAMP), 'Europe/London') as created_date

    from {{ ref('silver_sharpspring_leads') }}
    where is_active = true
),

-- outbound completed calls only
outbound_calls as (
    select
        remote_phone,
        TIMESTAMP_MILLIS(start_time)                                        as call_at,
        DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London')                 as call_date,
        talk_time_seconds,
        colleague_name as agent_name
    from {{ ref('silver_wildix_calls') }}
    where direction = 'OUTBOUND'
    and call_status = 'COMPLETED'
    and remote_phone is not null
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
    left join call_metrics cm on l.lead_id = cm.lead_id
)

select * from final
order by created_at desc
