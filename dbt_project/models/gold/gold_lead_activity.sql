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

        -- UK local date of creation
        cast(created_at at time zone 'Europe/London' as date) as created_date,

        -- classify lead
        case
            when lead_status = 'customer'                                   then 'sold'
            when lead_status = 'unqualified'                                then 'lost'
            when appointment_booked = 'Yes'                                 then 'appointed'
            when cast(created_at at time zone 'Europe/London' as date)
                 = current_date                                              then 'fresh'
            when cast(created_at at time zone 'Europe/London' as date)
                 >= current_date - interval 30 days                         then 'backlog'
            else                                                                 'aged_backlog'
        end as lead_type

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
lead_calls as (
    select
        l.lead_id,
        c.call_at,
        c.call_date,
        c.talk_time_seconds,
        c.agent_name
    from leads l
    inner join outbound_calls c
        on c.remote_phone = l.phone
        or c.remote_phone = l.mobile
        or c.remote_phone = l.phone_alt
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
        -- agent on the most recent call
        arg_max(agent_name, call_at)                          as last_call_agent,
        count(*) filter (where call_date = current_date)      as calls_today,
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
        l.appointment_made_by,
        l.appointment_type,
        l.appointment_status,
        l.lead_type,

        -- call activity
        coalesce(cm.total_call_attempts, 0)                   as total_call_attempts,
        cm.first_call_at,
        cm.last_call_at,
        cm.last_call_agent,
        coalesce(cm.calls_today, 0)                           as calls_today,
        coalesce(cm.qualified_conversations, 0)               as qualified_conversations,

        -- time from lead created to first outbound call (minutes)
        case
            when cm.first_call_at is null then null
            else round(
                date_diff('minute', l.created_at, cm.first_call_at),
                0
            )
        end                                                   as mins_to_first_call,

        -- flags
        cm.first_call_at is not null                          as has_been_called,
        coalesce(cm.calls_today, 0) > 0                       as called_today,
        coalesce(cm.qualified_conversations, 0) > 0           as has_qualified_conversation,

        -- backlog: was this aged lead worked today?
        case
            when l.lead_type = 'backlog' then coalesce(cm.calls_today, 0) > 0
            else null
        end                                                   as backlog_worked_today

    from leads l
    left join call_metrics cm on l.lead_id = cm.lead_id
)

select * from final
order by created_at desc
