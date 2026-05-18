import duckdb, os
from dotenv import load_dotenv
load_dotenv()

con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")

# All leads Sat 16 – Mon 18 May
leads = con.execute("""
    SELECT
        created_date,
        count(*)                                                    AS total_leads,
        count(*) FILTER (WHERE customer_type = 'domestic')         AS domestic,
        count(*) FILTER (WHERE customer_type = 'commercial')       AS commercial,
        count(*) FILTER (WHERE customer_type IS NULL)              AS unknown_type,
        count(*) FILTER (WHERE appointment_booked = 'Yes')         AS appointments,
        count(*) FILTER (WHERE is_sold)                            AS sold
    FROM gold.gold_lead_activity
    WHERE created_date BETWEEN '2026-05-16' AND '2026-05-18'
    GROUP BY created_date
    ORDER BY created_date
""").df()

print("=== LEADS  Sat 16 – Mon 18 May ===")
print(leads.to_string(index=False))
print(f"\nTOTAL  leads={leads['total_leads'].sum()}  appts={leads['appointments'].sum()}  sold={leads['sold'].sum()}")

# Ad spend + paid leads
ads = con.execute("""
    SELECT
        date,
        platform,
        spend_gbp,
        leads,
        appointments_booked,
        cost_per_lead,
        cost_per_appointment
    FROM gold.gold_campaign_attribution
    WHERE date BETWEEN '2026-05-16' AND '2026-05-18'
    ORDER BY date, platform
""").df()

print("\n=== AD SPEND  Sat 16 – Mon 18 May ===")
if ads.empty:
    print("No spend data for this period.")
else:
    print(ads.to_string(index=False))
    total_spend   = ads['spend_gbp'].sum()
    total_leads   = ads['leads'].sum()
    total_appts   = ads['appointments_booked'].sum()
    blended_cpl   = total_spend / total_leads   if total_leads  > 0 else None
    blended_cpa   = total_spend / total_appts   if total_appts  > 0 else None
    print(f"\nTotal spend:      £{total_spend:,.2f}")
    print(f"Total paid leads: {total_leads:.0f}")
    print(f"Blended CPL:      {'£'+f'{blended_cpl:.2f}' if blended_cpl else 'n/a'}")
    print(f"Total appts:      {total_appts:.0f}")
    print(f"Blended CPA:      {'£'+f'{blended_cpa:.2f}' if blended_cpa else 'n/a'}")
