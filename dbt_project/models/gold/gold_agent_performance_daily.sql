with calls as (
    select
        -- convert unix ms to date
        date_trunc('day', to_timestamp(start_time / 1000)) as call_date,
        wms_id,
        colleague_name,
        colleague_department,
        caller_extension,
        caller_email,
        direction,
        call_status,
        talk_time_seconds,
        duration_seconds,
        remote_phone
    from {{ ref('silver_wildix_calls') }}
    where direction in ('OUTBOUND', 'INBOUND')
    and call_status = 'COMPLETED'
),

-- normalise agent names from SharpSpring appointment_made_by field
appointments as (
    select
        case
            when lower(appointment_made_by) in ('lily', 'lily harpham')         then 'Lily Harpham'
            when lower(appointment_made_by) in ('sue', 'susan england')          then 'Susan England'
            when lower(appointment_made_by) in ('dec', 'declan franks')          then 'Declan Franks'
            when lower(appointment_made_by) in ('alice', 'alice hardegon')       then 'Alice Hardegon'
            when lower(appointment_made_by) in ('alicja', 'alicja aleksiuk')     then 'Alicja Aleksiuk'
            when lower(appointment_made_by) in ('reilly', 'reilly andrew')       then 'Reilly Andrew'
            when lower(appointment_made_by) in ('alisha', 'alisha moore')        then 'Alisha Moore'
            when lower(appointment_made_by) in ('ashleigh', 'ashleigh nankervis') then 'Ashleigh Nankervis'
            when lower(appointment_made_by) in ('kim', 'kim ellis')              then 'Kim Ellis'
            when lower(appointment_made_by) in ('amelia', 'amelia konczewska')   then 'Amelia Konczewska'
            when lower(appointment_made_by) in ('josh', 'josh baron')            then 'Josh Baron'
            when lower(appointment_made_by) = 'other'                            then null
            else appointment_made_by
        end as agent_name,
        date_trunc('day', updated_at) as appointment_date,
        count(*) as appointments_booked
    from {{ ref('silver_sharpspring_leads') }}
    where appointment_booked = 'Yes'
    and appointment_made_by is not null
    group by agent_name, appointment_date
),

-- per agent per day call metrics
call_metrics as (
    select
        call_date,
        colleague_name                                              as agent_name,
        colleague_department                                        as department,
        count(*)                                                    as total_calls,
        count(*) filter (where direction = 'OUTBOUND')             as outbound_calls,
        count(*) filter (where direction = 'INBOUND')              as inbound_calls,
        count(distinct remote_phone)                               as unique_leads_contacted,
        sum(talk_time_seconds)                                     as total_talk_time_seconds,
        round(avg(talk_time_seconds), 0)                           as avg_talk_time_seconds,
        count(*) filter (where talk_time_seconds >= 120)           as qualified_conversations,
        count(*) filter (where talk_time_seconds >= 120
                         and direction = 'OUTBOUND')               as qualified_outbound_conversations
    from calls
    group by call_date, colleague_name, colleague_department
),

-- missed calls per agent per day
missed as (
    select
        date_trunc('day', to_timestamp(start_time / 1000))         as call_date,
        colleague_name                                              as agent_name,
        count(*)                                                    as missed_calls
    from {{ ref('silver_wildix_calls') }}
    where call_status = 'MISSED'
    group by call_date, colleague_name
),

final as (
    select
        cm.call_date                                                                    as date,
        cm.agent_name,
        cm.department,
        cm.total_calls,
        cm.outbound_calls,
        cm.inbound_calls,
        coalesce(m.missed_calls, 0)                                                    as missed_calls,
        cm.unique_leads_contacted,
        cm.total_talk_time_seconds,
        cm.avg_talk_time_seconds,
        cm.qualified_conversations,
        cm.qualified_outbound_conversations,
        coalesce(a.appointments_booked, 0)                                             as appointments_booked,

        -- conversion rate: appointments / qualified conversations
        case
            when cm.qualified_conversations = 0 then null
            else round(coalesce(a.appointments_booked, 0) * 100.0 / cm.qualified_conversations, 1)
        end                                                                             as conversion_rate_pct,

        -- calls per appointment (your 1-in-3 target)
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(cm.outbound_calls * 1.0 / a.appointments_booked, 1)
        end                                                                             as calls_per_appointment,

        -- on target flag (1 appointment per 3 calls)
        case
            when coalesce(a.appointments_booked, 0) = 0 then false
            when cm.outbound_calls * 1.0 / a.appointments_booked <= 3 then true
            else false
        end                                                                             as on_target

    from call_metrics cm
    left join missed m
        on cm.call_date = m.call_date
        and cm.agent_name = m.agent_name
    left join appointments a
        on cm.call_date = a.appointment_date
        and cm.agent_name = a.agent_name
)

select * from final
order by date desc, appointments_booked desc
