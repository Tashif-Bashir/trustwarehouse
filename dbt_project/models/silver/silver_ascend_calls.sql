-- Ascend (Focus Group phone system) calls mapped to the SAME column contract as
-- silver_wildix_calls, so downstream call models work identically across the
-- 1 Jul 2026 Wildix -> Ascend cutover (see silver_calls_unified).
--
-- Semantic mapping (validated in the Jul-2026 business analysis):
--   * Ascend `duration` is pure TALK time (Wildix `duration` included ring) ->
--     maps to talk_time_seconds; duration_seconds = ring + talk for parity.
--   * Ascend `answered` is a real flag -> COMPLETED / MISSED.
--   * One row per call (no transfer legs, unlike Wildix).
--   * Agent = `from` on outbound, `to` on inbound/internal. IVR / voicemail
--     endpoints are NOT agents -> colleague_name NULL (drops from per-agent
--     stats, still counts in call totals).

with source as (
    select * from {{ source('bronze', 'ascend_calls') }}
),

cleaned as (
    select
        id                                                          as call_id,
        global_call_id                                              as wms_id,

        case when answered then 'COMPLETED' else 'MISSED' end       as call_status,
        upper(direction)                                            as direction,
        'call'                                                      as call_type,
        UNIX_MILLIS(start)                                          as start_time,
        UNIX_MILLIS(start)
            + (coalesce(ring_duration, 0) + coalesce(duration, 0)) * 1000
                                                                    as end_time,
        coalesce(ring_duration, 0)                                  as connect_time_seconds,
        coalesce(ring_duration, 0) + coalesce(duration, 0)          as duration_seconds,
        coalesce(duration, 0)                                       as talk_time_seconds,
        0                                                           as hold_time_seconds,
        0                                                           as wait_time_seconds,

        -- remote / customer side (NULL for internal calls)
        case when direction = 'internal' then null
             else {{ normalise_phone("""
                 case when direction = 'outbound' then JSON_VALUE(`to`, '$.number')
                      else JSON_VALUE(`from`, '$.number') end
             """) }} end                                            as remote_phone,

        -- agent side; IVR / voicemail endpoints are not people
        case
            when direction = 'outbound' then JSON_VALUE(`from`, '$.name')
            when JSON_VALUE(`to`, '$.device.deviceType') in ('IVR', 'Voicemail', 'VoiceMail')
                then null
            else nullif(trim(JSON_VALUE(`to`, '$.name')), '')
        end                                                         as colleague_name,
        nullif(trim(`group`), '')                                   as colleague_department,
        cast(null as string)                                        as colleague_extension

    from source
)

select * from cleaned
