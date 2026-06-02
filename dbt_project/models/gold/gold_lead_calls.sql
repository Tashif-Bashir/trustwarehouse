-- One row per (call, lead) match.
-- A "call" here is a single logical conversation (collapsed across all
-- participant rows in silver_wildix_calls so transfers don't double-count).
-- A "lead" is the SharpSpring lead whose phone matched the call's remote number.
-- One logical call may match multiple leads if the same phone is reused
-- across lead records (repeat customer, family); each match = a separate row.
--
-- Powers: hour×day heatmap, speed-to-call cliff, call-duration vs conversion,
-- cost-per-appointment by lead source. See gold_lead_calls section of the
-- analytics handbook for sample queries.

with calls_filtered as (
    select
        call_id,
        wms_id,
        direction,
        call_status,
        call_type,
        start_time,
        end_time,
        duration_seconds,
        talk_time_seconds,
        connect_time_seconds,
        wait_time_seconds,
        remote_phone,
        colleague_name,
        colleague_department,
        colleague_extension
    from {{ ref('silver_wildix_calls') }}
    -- only customer-facing legs of a call; INTERNAL = agent-to-agent transfer leg
    where direction in ('OUTBOUND', 'INBOUND')
      -- COMPLETED = answered, MISSED = dial attempt where customer didn't pick up.
      -- Keeping MISSED so "how many times did we try" metrics work.
      and call_status in ('COMPLETED', 'MISSED')
      and remote_phone is not null
),

-- Collapse multi-participant rows (transfers / parallel pickups) into one row per call_id.
-- talk_time_seconds is summed (total conversation length across all agents involved).
-- duration_seconds takes the max (full call lifecycle).
-- primary agent = whoever spoke the longest.
calls_dedup as (
    select
        call_id,
        any_value(direction)              as direction,
        any_value(call_status)            as call_status,
        any_value(call_type)              as call_type,
        min(start_time)                   as start_time,
        max(end_time)                     as end_time,
        max(duration_seconds)             as duration_seconds,
        sum(talk_time_seconds)            as talk_time_seconds,
        max(connect_time_seconds)         as connect_time_seconds,
        max(wait_time_seconds)            as wait_time_seconds,
        any_value(remote_phone)           as remote_phone,
        array_agg(colleague_name        order by talk_time_seconds desc limit 1)[offset(0)] as agent_name,
        array_agg(colleague_department  order by talk_time_seconds desc limit 1)[offset(0)] as agent_department,
        array_agg(colleague_extension   order by talk_time_seconds desc limit 1)[offset(0)] as agent_extension,
        count(*)                          as participant_count
    from calls_filtered
    group by call_id
),

leads as (
    select
        lead_id,
        first_name,
        last_name,
        created_at as lead_created_at,
        phone,
        mobile,
        phone_alt
    from {{ ref('silver_sharpspring_leads') }}
    where is_active = true
),

-- Lead's attribution + outcome (reuses the hybrid CRM/UTM platform already in gold_lead_activity).
-- appointment_booked_at arrives as a string from SharpSpring with no timezone — treat as UK local.
lead_outcomes as (
    select
        lead_id,
        platform        as lead_platform,
        crm_platform    as lead_crm_platform,
        utm_platform    as lead_utm_platform,
        qc_flag         as lead_qc_flag,
        campaign_id     as lead_campaign_id,
        customer_type   as lead_customer_type,
        appointment_booked  as lead_appointment_booked,
        appointment_date    as lead_appointment_date,
        case
            when appointment_booked_at is null or appointment_booked_at = '' then null
            else safe.timestamp(appointment_booked_at, 'Europe/London')
        end                 as lead_appointment_booked_at,
        is_sold             as lead_is_sold,
        deal_amount         as lead_deal_amount,
        quote_amount        as lead_quote_amount
    from {{ ref('gold_lead_activity') }}
),

-- Match each call to leads it could belong to (any of the 3 normalised phone fields)
-- and only count calls that happened AFTER the lead was created.
matched as (
    select
        c.call_id,
        l.lead_id,
        c.direction, c.call_status, c.call_type,
        c.start_time, c.end_time,
        c.duration_seconds, c.talk_time_seconds, c.connect_time_seconds, c.wait_time_seconds,
        c.remote_phone,
        c.agent_name, c.agent_department, c.agent_extension, c.participant_count,
        l.first_name as lead_first_name,
        l.last_name  as lead_last_name,
        l.lead_created_at
    from calls_dedup c
    inner join leads l
        on (c.remote_phone = l.phone
         or c.remote_phone = l.mobile
         or c.remote_phone = l.phone_alt)
        and TIMESTAMP_MILLIS(c.start_time) >= SAFE_CAST(l.lead_created_at as TIMESTAMP)
),

-- Per-lead call ordering (1 = first call to this lead, 2 = second, ...).
sequenced as (
    select *,
        row_number() over (partition by lead_id order by start_time) as call_seq
    from matched
)

select
    -- identity
    s.call_id,
    s.lead_id,

    -- call timing (UK local for analytics)
    TIMESTAMP_MILLIS(s.start_time)                                                              as call_at,
    DATE(TIMESTAMP_MILLIS(s.start_time), 'Europe/London')                                       as call_date,
    EXTRACT(HOUR    FROM TIMESTAMP_MILLIS(s.start_time) AT TIME ZONE 'Europe/London')           as call_hour,
    EXTRACT(DAYOFWEEK FROM TIMESTAMP_MILLIS(s.start_time) AT TIME ZONE 'Europe/London')         as call_dow_num,
    FORMAT_TIMESTAMP('%A', TIMESTAMP_MILLIS(s.start_time), 'Europe/London')                     as call_dow_name,

    -- call attributes
    s.direction,
    s.call_status,
    s.call_type,
    s.duration_seconds,
    s.talk_time_seconds,
    s.connect_time_seconds,
    s.wait_time_seconds,
    s.remote_phone,

    -- agent
    s.agent_name,
    s.agent_department,
    s.agent_extension,
    s.participant_count,

    -- lead context
    s.lead_first_name,
    s.lead_last_name,
    s.lead_created_at,
    o.lead_platform,
    o.lead_crm_platform,
    o.lead_utm_platform,
    o.lead_qc_flag,
    o.lead_campaign_id,
    o.lead_customer_type,

    -- lead-level outcomes (same on every call row for a lead — denormalised for query speed)
    o.lead_appointment_booked,
    o.lead_appointment_date,
    o.lead_appointment_booked_at,
    o.lead_is_sold,
    o.lead_deal_amount,
    o.lead_quote_amount,

    -- Per-call outcome attribution.
    -- The lead-level appt flag credits every call to a lead with an eventual appt — even
    -- calls that happened *after* the appt was already booked. These columns fix that by
    -- crediting a call only if the appt was booked in a window *after* this call.
    -- Used for honest heatmap / sweet-spot / speed-to-call rates.
    case
        when o.lead_appointment_booked_at is null then false
        when o.lead_appointment_booked_at <  TIMESTAMP_MILLIS(s.start_time) then false
        when o.lead_appointment_booked_at <= TIMESTAMP_ADD(TIMESTAMP_MILLIS(s.start_time), interval 1 hour) then true
        else false
    end                                                                                         as appt_within_1h,
    case
        when o.lead_appointment_booked_at is null then false
        when o.lead_appointment_booked_at <  TIMESTAMP_MILLIS(s.start_time) then false
        when o.lead_appointment_booked_at <= TIMESTAMP_ADD(TIMESTAMP_MILLIS(s.start_time), interval 24 hour) then true
        else false
    end                                                                                         as appt_within_24h,
    case
        when o.lead_appointment_booked_at is null then false
        when o.lead_appointment_booked_at <  TIMESTAMP_MILLIS(s.start_time) then false
        when o.lead_appointment_booked_at <= TIMESTAMP_ADD(TIMESTAMP_MILLIS(s.start_time), interval 48 hour) then true
        else false
    end                                                                                         as appt_within_48h,
    -- Minutes from this call to the appointment booking. NULL if no appt or appt was before the call.
    case
        when o.lead_appointment_booked_at is null then null
        when o.lead_appointment_booked_at <  TIMESTAMP_MILLIS(s.start_time) then null
        else round(TIMESTAMP_DIFF(o.lead_appointment_booked_at, TIMESTAMP_MILLIS(s.start_time), SECOND) / 60.0, 2)
    end                                                                                         as mins_to_appt_after_call,

    -- speed-to-call (per-call)
    TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) as lead_age_at_call_seconds,
    ROUND(TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) / 60.0, 2) as lead_age_at_call_minutes,
    case
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 5*60       then '<5m'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 15*60      then '5-15m'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 60*60      then '15-60m'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 4*60*60    then '1-4h'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 24*60*60   then '4-24h'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 3*24*60*60 then '1-3d'
        when TIMESTAMP_DIFF(TIMESTAMP_MILLIS(s.start_time), SAFE_CAST(s.lead_created_at as TIMESTAMP), SECOND) < 7*24*60*60 then '3-7d'
        else '>7d'
    end as lead_age_bucket,

    -- call ordering
    s.call_seq,
    s.call_seq = 1                              as is_first_call,

    -- call-level outcome derivation
    s.talk_time_seconds >= 120                  as is_qualified_call

from sequenced s
left join lead_outcomes o using (lead_id)
order by s.start_time desc
