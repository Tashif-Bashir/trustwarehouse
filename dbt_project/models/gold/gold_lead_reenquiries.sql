-- Returning leads (owner design, 21 Aug 2026): an existing lead (>14 days
-- old) whose form-submission signals changed at a sync — captured by
-- ingestion/sharpspring/reenquiries.py into bronze.sharpspring_lead_reenquiries.
-- One row per lead per Europe/London day. The RETURN visit is attributed from
-- the NEW url it arrived with (same inference as gold_lead_activity), not the
-- lead's original acquisition. Counter starts at zero on switch-on day —
-- history before that is unrecoverable (bronze keeps latest state only).

with events as (

    select
        r.lead_id,
        r.event_date,
        r.detected_at,
        r.changed_fields,
        lower(coalesce(nullif(r.new_marketing_url, ''), r.new_page_submitted, '')) as return_url

    from {{ source('bronze', 'sharpspring_lead_reenquiries') }} r

    -- Only count events where a FORM signal changed. Description-only changes
    -- are excluded: ResponseIQ call-tracking appends to description on phone
    -- calls ("responseIQ: ... Calltracking/Widget"), and CRM merges append
    -- "Merged Description" blocks — neither is a form re-submission (owner
    -- definition: forms only; evidenced 24 Aug 2026 when 8 of 13 events were
    -- call/merge noise). Bronze keeps every event, so this stays reversible.
    where regexp_contains(r.changed_fields, r'page_submitted|marketing_url')

),

leads as (

    select
        lead_id,
        first_name,
        last_name,
        domestic_appointment_status
    from {{ ref('silver_sharpspring_leads') }}
    qualify row_number() over (partition by lead_id order by updated_at desc) = 1

)

select
    e.lead_id,
    e.event_date,
    e.detected_at,
    e.changed_fields,

    -- same paid-platform inference as gold_lead_activity, applied to the
    -- RETURN visit's url
    case
        when regexp_contains(e.return_url, r'gclid=')                       then 'Google'
        when regexp_contains(e.return_url, r'utm_source=google')
         and regexp_contains(e.return_url, r'utm_medium=(cpc|ppc|paid)')    then 'Google'
        when regexp_contains(e.return_url, r'gad_source=1')                 then 'Google'
        when regexp_contains(e.return_url, r'fbclid=')                      then 'Meta'
        when regexp_contains(e.return_url, r'utm_source=(facebook|instagram|meta|fb)')
         and regexp_contains(e.return_url, r'utm_medium=(cpc|paid|paidsocial)') then 'Meta'
        when regexp_contains(e.return_url, r'utm_source=bing')
         and regexp_contains(e.return_url, r'utm_medium=(cpc|ppc|paid)')    then 'Bing'
    end                                                                     as platform,

    -- in-hours = Mon-Fri 08:30-17:29 Europe/London at detection time (the
    -- sync runs ~every 35 min, so detection lags the actual visit slightly)
    (
        extract(dayofweek from datetime(e.detected_at, 'Europe/London')) between 2 and 6
        and (extract(hour from datetime(e.detected_at, 'Europe/London')) * 60
             + extract(minute from datetime(e.detected_at, 'Europe/London'))) between 510 and 1049
    )                                                                       as in_hours,

    l.first_name,
    l.last_name,
    l.domestic_appointment_status

from events e
left join leads l using (lead_id)
