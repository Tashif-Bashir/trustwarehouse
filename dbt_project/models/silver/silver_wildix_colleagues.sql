with source as (
    select * from {{ source('bronze', 'wildix_colleagues') }}
),

cleaned as (
    select
        -- identity
        id,
        nullif(trim(name), '')                  as name,
        nullif(trim(email), '')                 as email,
        nullif(trim(extension), '')             as extension,
        nullif(trim(login), '')                 as login,

        -- org / hierarchy
        nullif(trim(role), '')                  as role,
        nullif(trim(group_name), '')            as group_name,
        nullif(trim(department), '')            as department,
        nullif(trim(pbx), '')                   as pbx,

        -- contact / routing
        {{ normalise_phone('nullif(trim(office_phone), \'\')') }}   as office_phone,
        {{ normalise_phone('nullif(trim(mobile_phone), \'\')') }}   as mobile_phone,

        -- licensing
        nullif(trim(license_type), '')          as license_type

    from source
)

select * from cleaned
