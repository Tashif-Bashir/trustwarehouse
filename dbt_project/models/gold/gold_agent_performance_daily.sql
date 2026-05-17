with calls as (
    select
        -- cast unix ms to UK local date (avoids UTC midnight mismatch)
        cast(to_timestamp(start_time / 1000) at time zone 'Europe/London' as date) as call_date,
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
-- target: match colleague_name values from silver_wildix_calls exactly
appointments as (
    select
        {{ normalise_agent_name('appointment_made_by') }} as agent_name,
        date_trunc('day', try_cast(appointment_booked_at as timestamp)) as appt_booked_date,
        count(*) as appointments_booked
    from {{ ref('silver_sharpspring_leads') }}
    where appointment_booked = 'Yes'
    and appointment_made_by is not null
    and appointment_booked_at is not null
    group by agent_name, date_trunc('day', try_cast(appointment_booked_at as timestamp))
),

-- sales credited to each agent per day (via converted_by field)
sales as (
    select
        {{ normalise_agent_name('converted_by') }}                            as agent_name,
        cast(try_cast(order_confirmed_at as timestamp) as date)               as sale_date,
        count(*)                                                               as sales_confirmed,
        round(sum(try_cast(regexp_replace(deal_amount, ',', '', 'g') as decimal(10,2))), 2) as total_deal_value
    from {{ ref('silver_sharpspring_leads') }}
    where is_sold = true
      and converted_by is not null
      and converted_by != 'Other'
    group by agent_name, sale_date
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
        cast(to_timestamp(start_time / 1000) at time zone 'Europe/London' as date) as call_date,
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
        coalesce(s.sales_confirmed, 0)                                                 as sales_confirmed,
        s.total_deal_value,

        -- qualified conversations per appointment (lower = better)
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(
                (cm.qualified_conversations + cm.qualified_outbound_conversations) * 1.0
                / coalesce(a.appointments_booked, 0),
                1
            )
        end                                                                             as qual_convos_per_appointment,

        -- calls per appointment (your 1-in-3 target)
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(cm.outbound_calls * 1.0 / a.appointments_booked, 1)
        end                                                                             as calls_per_appointment,

        -- appointment to sale conversion rate per agent per day
        case
            when coalesce(a.appointments_booked, 0) = 0 then null
            else round(coalesce(s.sales_confirmed, 0) * 1.0 / a.appointments_booked, 2)
        end                                                                             as appointment_to_sale_rate,

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
        on cm.call_date = a.appt_booked_date
        and cm.agent_name = a.agent_name
    left join sales s
        on cm.call_date = s.sale_date
        and cm.agent_name = s.agent_name
)

select * from final
order by date desc, appointments_booked desc
