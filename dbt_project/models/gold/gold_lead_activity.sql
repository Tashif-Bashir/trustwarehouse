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
        appointment_booked_at,

        -- derived columns from silver enriched CTE
        appointment_date,
        customer_type,
        is_sold,

        -- UK local date of creation — use this to classify leads at query time
        cast(created_at at time zone 'Europe/London' as date) as created_date

    from {{ ref('silver_sharpspring_leads') }}
    where is_active = true
),

-- outbound completed calls only
outbound_calls as (
    select
        remote_phone,
        cast(to_timestamp(start_time / 1000) at time zone 'Europe/London' as timestamp) as call_at,
        cast(to_timestamp(start_time / 1000) at time zone 'Europe/London' as date)      as call_date,
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
        and c.call_at >= l.created_at
    where l.phone is not null
        or l.mobile is not null
        or l.phone_alt is not null
),

-- per-lead call aggregates
call_metrics as (
    select
        lead_id,
        count(*)                                              as total_call_attempts,
        min(call_at)                                          as first_call_at,
        max(call_at)                                          as last_call_at,
        cast(max(call_at) as date)                            as last_call_date,
        arg_max(agent_name, call_at)                          as last_call_agent,
        count(*) filter (where talk_time_seconds >= 120)      as qualified_conversations
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

        -- call activity
        coalesce(cm.total_call_attempts, 0)                   as total_call_attempts,
        cm.first_call_at,
        cm.last_call_at,
        cm.last_call_date,
        cm.last_call_agent,
        coalesce(cm.qualified_conversations, 0)               as qualified_conversations,

        -- time from lead created to first outbound call (minutes)
        -- null when the first call was on a different calendar day: overnight gaps
        -- would skew the same-day response metric (e.g. evening lead called next morning)
        case
            when cm.first_call_at is null then null
            when cast(cm.first_call_at as date) != l.created_date then null
            else round(
                date_diff('minute', l.created_at, cm.first_call_at),
                0
            )
        end                                                   as mins_to_first_call,

        -- flags
        cm.first_call_at is not null                          as has_been_called,
        coalesce(cm.qualified_conversations, 0) > 0           as has_qualified_conversation,

        -- quote amount: strip junk placeholder values (≤1) and non-castable strings
        case
            when try_cast(l.appt_amount as decimal(10,2)) > 1
            then round(try_cast(l.appt_amount as decimal(10,2)), 2)
        end                                                   as quote_amount,

        -- deal amount: agents sometimes enter commas (e.g. "2,990.50") — strip before cast
        case
            when try_cast(regexp_replace(l.deal_amount, ',', '', 'g') as decimal(10,2)) > 1
            then round(try_cast(regexp_replace(l.deal_amount, ',', '', 'g') as decimal(10,2)), 2)
        end                                                   as deal_amount,

        -- order confirmed as boolean (null = unknown, not the same as No)
        case
            when l.order_confirmed = 'Yes' then true
            when l.order_confirmed = 'No'  then false
        end                                                   as order_confirmed,

        try_cast(l.order_confirmed_at as timestamp)           as order_confirmed_at,

        l.is_sold

    from leads l
    left join call_metrics cm on l.lead_id = cm.lead_id
)

select * from final
order by created_at desc
