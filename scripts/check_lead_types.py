import duckdb, os
from dotenv import load_dotenv
load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")

DATE = "2026-05-17"

# Bronze — raw from SharpSpring, create_timestamp is the raw field
bronze = con.execute(f"""
    SELECT count(*) AS total
    FROM bronze.sharpspring_leads
    WHERE cast(create_timestamp as date) = '{DATE}'
""").fetchone()[0]

# Silver — after cleaning, is_active filter not applied
silver_all = con.execute(f"""
    SELECT count(*) AS total
    FROM silver.silver_sharpspring_leads
    WHERE cast(created_at as date) = '{DATE}'
""").fetchone()[0]

# Silver — active only (same filter as gold)
silver_active = con.execute(f"""
    SELECT count(*) AS total
    FROM silver.silver_sharpspring_leads
    WHERE cast(created_at at time zone 'Europe/London' as date) = '{DATE}'
      AND is_active = true
""").fetchone()[0]

# Gold
gold = con.execute(f"""
    SELECT count(*) AS total
    FROM gold.gold_lead_activity
    WHERE created_date = '{DATE}'
""").fetchone()[0]

print(f"Sunday {DATE} — lead count at each layer:")
print(f"  Bronze (sharpspring_leads):            {bronze}")
print(f"  Silver (all, no filter):               {silver_all}")
print(f"  Silver (is_active=true, UK tz):        {silver_active}")
print(f"  Gold   (gold_lead_activity):           {gold}")

if bronze == silver_all == silver_active == gold:
    print("\n  ALL LAYERS MATCH")
else:
    print("\n  MISMATCH — checking why...")
    # Check timezone difference
    tz_check = con.execute(f"""
        SELECT
            count(*) FILTER (WHERE cast(created_at as date) = '{DATE}')                               AS utc_date,
            count(*) FILTER (WHERE cast(created_at at time zone 'Europe/London' as date) = '{DATE}')  AS uk_date
        FROM silver.silver_sharpspring_leads
    """).df()
    print(f"\n  UTC vs UK timezone split for silver:")
    print(tz_check.to_string(index=False))

    inactive = con.execute(f"""
        SELECT count(*) FROM silver.silver_sharpspring_leads
        WHERE cast(created_at at time zone 'Europe/London' as date) = '{DATE}'
          AND is_active = false
    """).fetchone()[0]
    print(f"\n  Inactive leads on this date: {inactive}")
