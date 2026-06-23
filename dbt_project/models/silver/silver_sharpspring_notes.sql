with source as (
    select * from {{ source('bronze', 'sharpspring_notes') }}
),

cleaned as (
    select
        -- identity
        id                                              as note_id,
        who_id                                          as lead_id,
        author_id,

        -- author (the team member who wrote the note)
        nullif(trim(display_name), '')                  as author_name,
        nullif(trim(email_address), '')                 as author_email,

        -- content
        nullif(trim(note), '')                          as note_text,

        -- timing
        create_timestamp                                as created_at,
        date(create_timestamp, 'Europe/London')         as note_date,

        -- Payment-event signals. The deposit note is the team's canonical
        -- "sale happened" event (written by office/finance staff). A genuine
        -- opening deposit names a £ amount with a deposit/payment action, and
        -- is NOT a later balance/installment payment.
        (
            regexp_contains(note, r'£')
            and regexp_contains(lower(note),
                r'deposit|sold on site|s\.o\.s|\bsos\b|paid in full|payment received|money taken|card payment|via tyl|via ipg|via stripe')
            and not regexp_contains(lower(note),
                r'final balance|final payment|final instal|balance paid|paid.*balance|outstanding balance|2nd 33|second 33|final 33')
        )                                               as is_payment_event,

        regexp_contains(lower(note),
            r'final balance|final payment|final instal|balance paid|paid.*balance|outstanding balance|2nd 33|second 33|final 33')
                                                        as is_balance_payment,

        -- first £ amount mentioned (the deposit value)
        safe_cast(
            replace(regexp_extract(note, r'£\s*([0-9][0-9,]*\.?[0-9]*)'), ',', '')
            as float64
        )                                               as amount_mentioned,

        -- deposit percentage if stated (e.g. "50% deposit" -> 50)
        safe_cast(regexp_extract(note, r'([0-9]{2})\s*%') as int64)  as pct_mentioned

    from source
)

select * from cleaned
