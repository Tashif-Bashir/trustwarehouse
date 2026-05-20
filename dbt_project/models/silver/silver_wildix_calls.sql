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
        SAFE_CAST(start_time AS INT64)                      as start_time,
        SAFE_CAST(end_time AS INT64)                        as end_time,
        SAFE_CAST(connect_time AS INT64)                   as connect_time_seconds,
        SAFE_CAST(duration AS INT64)                       as duration_seconds,
        SAFE_CAST(talk_time AS INT64)                      as talk_time_seconds,
        SAFE_CAST(hold_time AS INT64)                      as hold_time_seconds,
        SAFE_CAST(wait_time AS INT64)                      as wait_time_seconds,
        SAFE_CAST(queue_time AS INT64)                     as queue_time_seconds,

        -- routing / identity
        nullif(trim(pbx), '')                               as pbx,
        nullif(trim(service), '')                           as service,
        nullif(trim(service_number), '')                    as service_number,
        nullif(trim(trunk_name), '')                        as trunk_name,
        nullif(trim(trunk_direction), '')                   as trunk_direction,
        nullif(trim(queue_id), '')                          as queue_id,
        nullif(trim(queue_name), '')                        as queue_name,
        SAFE_CAST(flow_index AS INT64)                     as flow_index,

        -- remote / customer side
        {{ normalise_phone('nullif(trim(remote_phone), \'\')') }}           as remote_phone,
        remote_phone_country_code,
        nullif(trim(remote_phone_country_code_str), '')     as remote_phone_country,
        nullif(trim(remote_phone_location), '')             as remote_phone_location,

        -- caller / callee (flat strings — nested fields serialised to JSON by pipeline)
        nullif(trim(caller), '')                            as caller,
        nullif(trim(callee), '')                            as callee,

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
