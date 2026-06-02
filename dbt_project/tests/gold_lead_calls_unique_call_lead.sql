-- Composite uniqueness on (call_id, lead_id) — equivalent to
-- dbt_utils.unique_combination_of_columns, written as a singular test so
-- we don't pull in the whole package just for one assertion.

select call_id, lead_id, count(*) as duplicate_rows
from {{ ref('gold_lead_calls') }}
group by call_id, lead_id
having count(*) > 1
