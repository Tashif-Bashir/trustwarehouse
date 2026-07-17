with calls as (
    select
        -- convert unix ms to UK local date
        DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London')             as call_date,
        wms_id,
        colleague_name,
        colleague_department,
        direction,
        call_status,
        talk_time_seconds,
        duration_seconds,
        remote_phone
    from {{ ref('silver_calls_unified') }}
    where direction in ('OUTBOUND', 'INBOUND')
    and call_status = 'COMPLETED'
),

-- Appointments BOOKED on this day — counts the booking EVENT permanently
-- (owner decision 18 Jul 2026): a cancellation must not retroactively erase
-- the booking from the day it was made. A booking counts while the flag is
-- 'Yes' (live) AND stays counted once the status moves to 'Appointment
-- Cancelled', provided the booked-at timestamp survives — the booking app
-- preserves it on cancel as of 18 Jul 2026 (it used to clear it; a handful
-- of app cancellations from 7-17 Jul are unrecoverable and undercounted).
-- Europe/London so the date axis matches call_date (late-evening UK bookings
-- would otherwise drift a day under UTC).
appointments as (
    select
        {{ normalise_agent_name('appointment_made_by') }}                           as agent_name,
        DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London')        as appt_booked_date,
        count(*)                                                                    as appointments_booked
    from {{ ref('silver_sharpspring_leads') }}
    where appointment_made_by is not null
      and appointment_booked_at is not null
      and (appointment_booked = 'Yes'
           or lower(coalesce(domestic_appointment_status, '')) = 'appointment cancelled')
    group by agent_name, DATE(SAFE_CAST(appointment_booked_at AS TIMESTAMP), 'Europe/London')
),

-- Appointments SCHEDULED to sit on this day (the date the customer is in the
-- diary for). Attributed to whoever booked it in CRM. This is what the
-- telesales manager actually compares against — "how many appointments are
-- in Lily's diary for this week" — vs the booked-at metric above which
-- tracks dialling activity.
--
-- Three columns to give the team a clean read on the funnel:
--   - appointments_scheduled = anything in the diary for this date
--   - appointments_sat       = subset that actually happened (any outcome)
--   - appointments_sold      = subset that closed
appointments_scheduled as (
    select
        {{ normalise_agent_name('appointment_made_by') }}                           as agent_name,
        appointment_date                                                            as appt_sit_date,
        count(*)                                                                    as appointments_scheduled,
        countif(lower(appointment_status) in (
            'appointment sat', 'sold', 'sold on site', 'sold in office',
            'follow up', 'too expensive', 'not interested', 'bought elsewhere',
            'not ready yet', 'chc sold'
        ))                                                                          as appointments_sat,
        countif(lower(appointment_status) in (
            'sold', 'sold on site', 'sold in office', 'chc sold'
        ))                                                                          as appointments_sold
    from {{ ref('silver_sharpspring_leads') }}
    where appointment_booked = 'Yes'
      and appointment_made_by is not null
      and appointment_date is not null
      -- The telesales manager's xlsx excludes cancelled appointments from
      -- the monthly count (only the "Appointment" outcome is counted, not
      -- "Appointment Cancelled"). Mirror that here.
      and lower(coalesce(appointment_status, '')) not in (
        'appointment cancelled', 'cancelled', 'cancel', 'appointment cancel'
      )
    group by agent_name, appointment_date
),

-- Sales credited to each agent per day.
--
-- The CRM team does not populate `converted_by` (NULL on every recent sale
-- and historically too — it's effectively a dead field). We attribute the
-- sale to whoever booked the appointment (`appointment_made_by`) which is
-- populated 100% on sold leads. For value we fall back to `appt_amount`
-- (the quote) when `deal_amount` is missing, because `deal_amount` is also
-- routinely left empty in CRM despite the sale being marked as sold.
sales as (
    select
        {{ normalise_agent_name('appointment_made_by') }}                                       as agent_name,
        DATE(SAFE_CAST(order_confirmed_at AS TIMESTAMP), 'Europe/London')                       as sale_date,
        count(*)                                                                                as sales_confirmed,
        round(sum(
            coalesce(
                SAFE_CAST(REGEXP_REPLACE(deal_amount, r',', '') AS NUMERIC),
                SAFE_CAST(REGEXP_REPLACE(appt_amount,  r',', '') AS NUMERIC),
                0
            )
        ), 2)                                                                                   as total_deal_value
    from {{ ref('silver_sharpspring_leads') }}
    where is_sold = true
      and appointment_made_by is not null
      and order_confirmed_at is not null
    group by agent_name, DATE(SAFE_CAST(order_confirmed_at AS TIMESTAMP), 'Europe/London')
),

-- per agent per day call metrics
call_metrics as (
    select
        call_date,
        colleague_name                                                              as agent_name,
        colleague_department                                                        as department,
        count(*)                                                                    as total_calls,
        COUNTIF(direction = 'OUTBOUND')                                             as outbound_calls,
        COUNTIF(direction = 'INBOUND')                                              as inbound_calls,
        count(distinct remote_phone)                                                as unique_leads_contacted,
        sum(talk_time_seconds)                                                      as total_talk_time_seconds,
        round(avg(talk_time_seconds), 0)                                            as avg_talk_time_seconds,
        COUNTIF(talk_time_seconds >= 120)                                           as qualified_conversations,
        COUNTIF(talk_time_seconds >= 120 and direction = 'OUTBOUND')                as qualified_outbound_conversations
    from calls
    group by call_date, colleague_name, colleague_department
),

-- missed calls per agent per day
missed as (
    select
        DATE(TIMESTAMP_MILLIS(start_time), 'Europe/London')                        as call_date,
        colleague_name                                                              as agent_name,
        count(*)                                                                    as missed_calls
    from {{ ref('silver_calls_unified') }}
    where call_status = 'MISSED'
    group by call_date, colleague_name
),

-- Build the spine: every (date, agent) where ANYTHING happened. The previous
-- version started FROM call_metrics, which silently dropped agents/dates that
-- had appointments-but-no-calls. Most commonly: appointments scheduled to sit
-- in the future, on a day no calls happen, were invisible.
date_agent_spine as (
    select * from (
        select call_date as date, agent_name from call_metrics
        union distinct
        select appt_booked_date as date, agent_name from appointments
        union distinct
        select appt_sit_date as date, agent_name from appointments_scheduled
        union distinct
        select sale_date as date, agent_name from sales
        union distinct
        select call_date as date, agent_name from missed
    )
    -- normalise_agent_name returns NULL for 'Other' values from CRM;
    -- drop those rows so the not_null test on agent_name passes.
    where agent_name is not null
),

final as (
    select
        sp.date,
        sp.agent_name,
        cm.department,
        coalesce(cm.total_calls, 0)                                                        as total_calls,
        coalesce(cm.outbound_calls, 0)                                                     as outbound_calls,
        coalesce(cm.inbound_calls, 0)                                                      as inbound_calls,
        coalesce(m.missed_calls, 0)                                                        as missed_calls,
        coalesce(cm.unique_leads_contacted, 0)                                             as unique_leads_contacted,
        coalesce(cm.total_talk_time_seconds, 0)                                            as total_talk_time_seconds,
        coalesce(cm.avg_talk_time_seconds, 0)                                              as avg_talk_time_seconds,
        coalesce(cm.qualified_conversations, 0)                                            as qualified_conversations,
        coalesce(cm.qualified_outbound_conversations, 0)                                   as qualified_outbound_conversations,
        coalesce(a.appointments_booked, 0)                                                 as appointments_booked,
        coalesce(asch.appointments_scheduled, 0)                                           as appointments_scheduled,
        coalesce(asch.appointments_sat, 0)                                                 as appointments_sat,
        coalesce(asch.appointments_sold, 0)                                                as appointments_sold,
        coalesce(s.sales_confirmed, 0)                                                     as sales_confirmed,
        s.total_deal_value

        -- Per-day ratios used to live here (calls_per_appointment,
        -- qual_convos_per_appointment, appointment_to_sale_rate, on_target).
        -- They were structurally misleading: dividing today's calls by today's
        -- appointments mixes two unrelated streams — the call activity is
        -- spread across many leads not yet converted, while today's booked
        -- appointments often came from leads called yesterday or last week.
        -- The dashboard now computes these ratios at period-aggregate level
        -- (sum first, then divide) in api/index.py, which is honest because
        -- the lead-to-booking lag washes out over a 7-30 day window.

    from date_agent_spine sp
    left join call_metrics cm
        on sp.date = cm.call_date and sp.agent_name = cm.agent_name
    left join missed m
        on sp.date = m.call_date and sp.agent_name = m.agent_name
    left join appointments a
        on sp.date = a.appt_booked_date and sp.agent_name = a.agent_name
    left join appointments_scheduled asch
        on sp.date = asch.appt_sit_date and sp.agent_name = asch.agent_name
    left join sales s
        on sp.date = s.sale_date and sp.agent_name = s.agent_name
)

select * from final
order by date desc, appointments_booked desc
