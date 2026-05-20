-- Deal pipeline from SharpSpring Opportunities, joined back to leads.
-- One row per opportunity. Provides deal stages, amounts, and win/loss status
-- independent of the custom lead fields (which agents fill in inconsistently).

with opportunities as (
    select
        opportunity_id,
        owner_id,
        deal_stage_id,
        opportunity_name,
        probability,
        amount,
        is_closed,
        is_won,
        is_active,
        close_date,
        created_at,
        updated_at,
        originating_lead_id,
        primary_lead_id,
        campaign_id,
        appointment_status,
        sector,
        competitor,
        estimate_number
    from {{ ref('silver_sharpspring_opportunities') }}
    where is_active = true
),

deal_stages as (
    select
        deal_stage_id,
        deal_stage_name,
        default_probability,
        weight
    from {{ ref('silver_sharpspring_deal_stages') }}
),

leads as (
    select
        lead_id,
        first_name,
        last_name,
        email,
        phone,
        customer_type,
        DATE(SAFE_CAST(created_at AS TIMESTAMP), 'Europe/London') as lead_created_date,
        lead_status,
        campaign_id     as lead_campaign_id
    from {{ ref('silver_sharpspring_leads') }}
    where is_active = true
),

final as (
    select
        o.opportunity_id,
        o.opportunity_name,

        -- deal stage
        ds.deal_stage_name,
        ds.default_probability  as stage_default_probability,

        -- financials
        o.amount                                                        as deal_amount,
        o.probability,
        case
            when o.probability is not null and o.amount is not null
            then round(o.probability / 100.0 * o.amount, 2)
        end                                                             as weighted_amount,

        -- outcome
        o.is_won,
        o.is_closed,
        o.close_date,

        -- timeline
        DATE(SAFE_CAST(o.created_at AS TIMESTAMP), 'Europe/London')    as created_date,
        DATE(SAFE_CAST(o.updated_at AS TIMESTAMP), 'Europe/London')    as updated_date,

        -- linked lead attributes
        l.first_name,
        l.last_name,
        l.email,
        l.phone,
        l.customer_type,
        l.lead_created_date,
        l.lead_status,

        -- identifiers
        o.originating_lead_id                                           as lead_id,
        o.owner_id,
        o.appointment_status,
        o.sector,
        o.competitor,
        o.estimate_number

    from opportunities o
    left join deal_stages ds on o.deal_stage_id = ds.deal_stage_id
    left join leads l        on o.originating_lead_id = l.lead_id
)

select * from final
order by created_date desc, deal_amount desc
