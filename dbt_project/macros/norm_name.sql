{% macro norm_name(col) %}
    -- Order-insensitive normalised customer-name key for matching across sources.
    -- Strips parenthetical postcodes, keeps alpha tokens >2 chars, sorts them.
    -- e.g. "Karen Wellings" and "Wellings Karen (YO26 4ZF)" both -> "karen wellings".
    array_to_string(
        array(
            select tok
            from unnest(split(
                regexp_replace(
                    regexp_replace(lower({{ col }}), r'\(.*?\)', ' '),
                    r'[^a-z ]', ' '
                ), ' '
            )) as tok
            where length(tok) > 2
            order by tok
        ), ' '
    )
{% endmacro %}
