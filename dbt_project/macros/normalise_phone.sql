{% macro normalise_phone(column) %}
    case
        when {{ column }} is null then null
        when REGEXP_REPLACE({{ column }}, r'[^0-9]', '') = '' then null
        when REGEXP_REPLACE({{ column }}, r'[^0-9]', '') like '00%'
            then SUBSTR(REGEXP_REPLACE({{ column }}, r'[^0-9]', ''), 3)
        when REGEXP_REPLACE({{ column }}, r'[^0-9]', '') like '0%'
            then '44' || SUBSTR(REGEXP_REPLACE({{ column }}, r'[^0-9]', ''), 2)
        else REGEXP_REPLACE({{ column }}, r'[^0-9]', '')
    end
{% endmacro %}
