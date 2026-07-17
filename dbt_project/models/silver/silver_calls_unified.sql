-- Unified call history across the phone-system migration:
--   Wildix  : calls before 1 Jul 2026 (frozen source, transfer-leg rows kept
--             exactly as they always were so history doesn't shift)
--   Ascend  : calls from 1 Jul 2026 (one row per call)
-- Boundary rule established from the data in the Jul-2026 business analysis
-- (last full Wildix day 30 Jun, first Ascend day 1 Jul, no gap).

with wildix as (
    select
        call_id, wms_id, call_status, direction, call_type,
        start_time, end_time,
        connect_time_seconds, duration_seconds, talk_time_seconds,
        hold_time_seconds, wait_time_seconds,
        remote_phone, colleague_name, colleague_department, colleague_extension,
        'wildix' as phone_system
    from {{ ref('silver_wildix_calls') }}
    where start_time < UNIX_MILLIS(TIMESTAMP('2026-07-01'))
),

ascend as (
    select
        call_id, wms_id, call_status, direction, call_type,
        start_time, end_time,
        connect_time_seconds, duration_seconds, talk_time_seconds,
        hold_time_seconds, wait_time_seconds,
        remote_phone, colleague_name, colleague_department, colleague_extension,
        'ascend' as phone_system
    from {{ ref('silver_ascend_calls') }}
    where start_time >= UNIX_MILLIS(TIMESTAMP('2026-07-01'))
)

select * from wildix
union all
select * from ascend
