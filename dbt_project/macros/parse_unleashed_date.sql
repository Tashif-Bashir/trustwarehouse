{#
    Unleashed's API returns dates as Microsoft JSON date strings, e.g.
    `/Date(1781654400000)/` (epoch milliseconds). A plain
    `SAFE_CAST(col AS DATE/TIMESTAMP)` silently returns NULL for every row,
    which previously left every Unleashed date column 100% NULL. These macros
    extract the epoch millis and convert correctly.
#}

{% macro parse_unleashed_timestamp(column) %}
    TIMESTAMP_MILLIS(
        SAFE_CAST(REGEXP_EXTRACT({{ column }}, r'/Date\((\d+)\)/') AS INT64)
    )
{% endmacro %}

{% macro parse_unleashed_date(column) %}
    DATE({{ parse_unleashed_timestamp(column) }})
{% endmacro %}
