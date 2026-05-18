import duckdb, os
from dotenv import load_dotenv
load_dotenv()
con = duckdb.connect(f"md:trust-pipeline?motherduck_token={os.environ['MOTHERDUCK_TOKEN']}")
print(con.execute("SELECT direction, count(*) as n FROM silver.silver_wildix_calls GROUP BY direction ORDER BY 2 DESC").df().to_string())
