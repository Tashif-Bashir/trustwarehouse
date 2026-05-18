import duckdb, os
from dotenv import load_dotenv
load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")

leads = con.execute("""
    SELECT count(*) AS total_leads,
           count(*) FILTER (WHERE customer_type = 'domestic')   AS domestic,
           count(*) FILTER (WHERE customer_type = 'commercial') AS commercial,
           count(*) FILTER (WHERE customer_type IS NULL)        AS unknown_type,
           count(*) FILTER (WHERE appointment_booked = 'Yes')   AS appointments,
           count(*) FILTER (WHERE is_sold)                      AS sold
    FROM gold.gold_lead_activity
    WHERE created_date = '2026-05-17'
""").df()
print("=== LEADS  Sunday 17 May ===")
print(leads.to_string(index=False))

ads = con.execute("""
    SELECT platform, spend_gbp, leads, appointments_booked, cost_per_lead
    FROM gold.gold_campaign_attribution
    WHERE date = '2026-05-17'
    ORDER BY spend_gbp DESC
""").df()
print("\n=== AD SPEND  Sunday 17 May ===")
if ads.empty:
    print("No spend data for Sunday yet.")
else:
    print(ads.to_string(index=False))
    total_spend = ads['spend_gbp'].sum()
    total_leads = int(ads['leads'].sum())
    cpl = total_spend / total_leads if total_leads > 0 else None
    print(f"\nTotal spend:  £{total_spend:,.2f}")
    print(f"Paid leads:   {total_leads}")
    print(f"Blended CPL:  {'£'+f'{cpl:.2f}' if cpl else 'n/a'}")
