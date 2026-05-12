{% macro normalise_phone(column) %}
    case
        when {{ column }} is null then null
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') = '' then null
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') like '00%'
            then substring(regexp_replace({{ column }}, '[^0-9]', '', 'g'), 3)
        when regexp_replace({{ column }}, '[^0-9]', '', 'g') like '0%'
            then '44' || substring(regexp_replace({{ column }}, '[^0-9]', '', 'g'), 2)
        else regexp_replace({{ column }}, '[^0-9]', '', 'g')
    end
{% endmacro %}
