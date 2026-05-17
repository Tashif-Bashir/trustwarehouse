{% macro normalise_agent_name(column) %}
    case
        when lower({{ column }}) in ('lily', 'lily harpham')          then 'Lily'
        when lower({{ column }}) in ('sue', 'susan england')           then 'Sue'
        when lower({{ column }}) in ('dec', 'declan franks')           then 'Dec'
        when lower({{ column }}) in ('alice', 'alice hardegon')        then 'Alice Hardegon'
        when lower({{ column }}) in ('alicja', 'alicja aleksiuk')      then 'Alicja Aleksiuk'
        when lower({{ column }}) in ('reilly', 'reilly andrew')        then 'Reilly Andrew'
        when lower({{ column }}) in ('alisha', 'alisha moore')         then 'Alisha'
        when lower({{ column }}) in ('ashleigh', 'ashleigh nankervis') then 'Ashleigh Nankervis'
        when lower({{ column }}) in ('kim', 'kim ellis')               then 'Kim Ellis'
        when lower({{ column }}) in ('amelia', 'amelia konczewska')    then 'Amelia Konczewska'
        when lower({{ column }}) in ('josh', 'josh baron')             then 'Josh Baron'
        when lower({{ column }}) in ('victoria', 'victoria ramsden')   then 'Victoria'
        when lower({{ column }}) in ('gemma', 'gemma taylor')          then 'Gemma Taylor'
        when lower({{ column }}) = 'other'                             then null
        else {{ column }}
    end
{% endmacro %}
