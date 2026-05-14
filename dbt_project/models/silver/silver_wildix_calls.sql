with source as (
    select * from {{ source('bronze', 'wildix_calls') }}
),

cleaned as (
    select
        -- primary key
        id                                                  as call_id,
        _wms_id                                             as wms_id,

        -- core call record
        nullif(trim(call_status), '')                       as call_status,
        nullif(trim(direction), '')                         as direction,
        nullif(trim(type), '')                              as call_type,
        try_cast(start_time as bigint)                      as start_time,
        try_cast(end_time as bigint)                        as end_time,
        try_cast(connect_time as integer)                   as connect_time_seconds,
        try_cast(duration as integer)                       as duration_seconds,
        try_cast(talk_time as integer)                      as talk_time_seconds,
        try_cast(hold_time as integer)                      as hold_time_seconds,
        try_cast(wait_time as integer)                      as wait_time_seconds,
        try_cast(queue_time as integer)                     as queue_time_seconds,

        -- routing / identity
        nullif(trim(pbx), '')                               as pbx,
        nullif(trim(service), '')                           as service,
        nullif(trim(service_number), '')                    as service_number,
        nullif(trim(trunk_name), '')                        as trunk_name,
        nullif(trim(trunk_direction), '')                   as trunk_direction,
        nullif(trim(queue_id), '')                          as queue_id,
        nullif(trim(queue_name), '')                        as queue_name,
        try_cast(flow_index as integer)                     as flow_index,

        -- remote / customer side
        {{ normalise_phone('nullif(trim(remote_phone), \'\')') }}           as remote_phone,
        remote_phone_country_code,
        nullif(trim(remote_phone_country_code_str), '')     as remote_phone_country,
        nullif(trim(remote_phone_location), '')             as remote_phone_location,

        -- caller (internal agent side)
        nullif(trim(caller), '')                            as caller,
        nullif(trim(caller__name), '')                      as caller_name,
        nullif(trim(caller__user_id), '')                   as caller_user_id,
        nullif(trim(caller__user_extension), '')            as caller_extension,
        nullif(trim(caller__email), '')                     as caller_email,
        nullif(trim(caller__role), '')                      as caller_role,
        nullif(trim(caller__type), '')                      as caller_type,
        nullif(trim(caller__group_name), '')                as caller_group,
        nullif(trim(caller__phone), '')                     as caller_phone,
        nullif(trim(caller__user_department), '')           as caller_department,

        -- callee (internal agent side)
        nullif(trim(callee), '')                            as callee,
        nullif(trim(callee__name), '')                      as callee_name,
        nullif(trim(callee__user_id), '')                   as callee_user_id,
        nullif(trim(callee__user_extension), '')            as callee_extension,
        nullif(trim(callee__email), '')                     as callee_email,
        nullif(trim(callee__role), '')                      as callee_role,
        nullif(trim(callee__type), '')                      as callee_type,
        nullif(trim(callee__group_name), '')                as callee_group,
        nullif(trim(callee__phone), '')                     as callee_phone,

        -- call flow
        nullif(trim(merge_with), '')                        as merge_with,
        nullif(trim(split_reason), '')                      as split_reason,
        nullif(trim(split_transfer_type), '')               as split_transfer_type,

        -- pipeline metadata
        nullif(trim(_extension), '')                        as colleague_extension,
        nullif(trim(_colleague_name), '')                   as colleague_name,
        nullif(trim(_department), '')                       as colleague_department

    from source
)

select * from cleaned
