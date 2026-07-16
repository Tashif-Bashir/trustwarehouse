"""Phase 4 — revenue trends, order economics, product/margin, CAC, geo revenue,
inventory signals. Revenue source-of-truth per Phase 0: sheets (Aug-Dec 2024),
Unleashed ex-VAT (Jan 2025+)."""
import json
import google.auth
from google.cloud import bigquery
import pandas as pd

creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/bigquery'])
client = bigquery.Client(project='trustwarehouse', credentials=creds)
def q(sql):
    return client.query(sql).to_dataframe()
pd.set_option('display.width', 260)
OUT = r'C:\Users\bashi\trustwarehouse\business_plan\analysis_output\data'

ORDERS = """
  orders AS (
    SELECT s._dlt_id AS okey, s.order_number, s.customer__guid,
      DATE(TIMESTAMP_MILLIS(SAFE_CAST(REGEXP_EXTRACT(s.order_date, r'([0-9]+)') AS INT64))) AS od,
      SAFE_CAST(s.sub_total AS FLOAT64) AS sub_total, s.delivery_post_code
    FROM `trustwarehouse.bronze.unleashed_sales_orders` s
    WHERE s.order_status NOT IN ('Deleted','Parked') AND SAFE_CAST(s.sub_total AS FLOAT64) > 0)
"""

print("=== monthly revenue & order economics (Unleashed, Jan 2025+) ===")
rev = q(f"""
  WITH {ORDERS}
  SELECT FORMAT_DATE('%Y-%m', od) AS month, COUNT(*) AS orders,
         ROUND(SUM(sub_total),0) AS revenue_exvat,
         ROUND(AVG(sub_total),0) AS aov
  FROM orders WHERE od >= '2025-01-01' GROUP BY 1 ORDER BY 1
""")
print(rev.to_string(index=False))
rev.to_csv(OUT + r'\phase4_revenue_monthly.csv', index=False)

print("\n=== product groups: revenue, units, gross margin by half-year ===")
pg = q(f"""
  WITH {ORDERS},
  lines AS (
    SELECT o.od, l.product__product_code AS code,
      SAFE_CAST(l.line_total AS FLOAT64) AS line_total,
      SAFE_CAST(l.order_quantity AS FLOAT64) AS qty,
      SAFE_CAST(l.average_landed_price_at_time_of_sale AS FLOAT64) AS landed
    FROM `trustwarehouse.bronze.unleashed_sales_orders__sales_order_lines` l
    JOIN orders o ON l._dlt_parent_id = o.okey
    WHERE o.od >= '2025-01-01' AND SAFE_CAST(l.line_total AS FLOAT64) > 0),
  grp AS (
    SELECT DISTINCT product_code, product_group_name
    FROM `trustwarehouse.bronze.unleashed_stock_on_hand`)
  SELECT
    CONCAT(CAST(EXTRACT(YEAR FROM od) AS STRING), '-H',
           CAST(IF(EXTRACT(MONTH FROM od) <= 6, 1, 2) AS STRING)) AS half,
    COALESCE(g.product_group_name, '(ungrouped)') AS product_group,
    ROUND(SUM(line_total),0) AS revenue, ROUND(SUM(qty),0) AS units,
    ROUND(SUM(line_total - IFNULL(landed,0)*qty) / NULLIF(SUM(line_total),0) * 100, 1) AS gross_margin_pct
  FROM lines LEFT JOIN grp g ON lines.code = g.product_code
  GROUP BY 1,2 HAVING revenue > 20000
  ORDER BY half, revenue DESC
""")
print(pg.to_string(index=False))
pg.to_csv(OUT + r'\phase4_product_groups.csv', index=False)

print("\n=== CAC & marketing %% of revenue, monthly (Jan 2025+) ===")
cac = q(f"""
  WITH {ORDERS},
  firsts AS (
    SELECT customer__guid, MIN(od) AS first_od FROM orders GROUP BY 1),
  newcust AS (
    SELECT FORMAT_DATE('%Y-%m', first_od) AS month, COUNT(*) AS new_customers
    FROM firsts WHERE first_od >= '2025-01-01' GROUP BY 1),
  spend AS (
    SELECT FORMAT_DATE('%Y-%m', d) AS month, ROUND(SUM(s),0) AS paid_spend FROM (
      SELECT DATE(date) AS d, spend_gbp AS s FROM `trustwarehouse.bronze.google_ads_api_campaign_daily`
      UNION ALL SELECT DATE(date), spend_gbp FROM `trustwarehouse.bronze.meta_api_campaign_daily`
      UNION ALL SELECT SAFE_CAST(TimePeriod AS DATE), SAFE_CAST(Spend AS FLOAT64)
      FROM `trustwarehouse.bronze.bing_adsaccount_performance_report_daily`)
    WHERE d >= '2025-01-01' GROUP BY 1),
  mrev AS (
    SELECT FORMAT_DATE('%Y-%m', od) AS month, SUM(sub_total) AS revenue
    FROM orders WHERE od >= '2025-01-01' GROUP BY 1)
  SELECT s.month, s.paid_spend, n.new_customers,
         ROUND(s.paid_spend / NULLIF(n.new_customers,0), 0) AS blended_cac,
         ROUND(mrev.revenue, 0) AS revenue,
         ROUND(s.paid_spend / NULLIF(mrev.revenue,0) * 100, 1) AS mkt_pct_of_revenue
  FROM spend s JOIN newcust n USING (month) JOIN mrev USING (month)
  ORDER BY s.month
""")
print(cac.to_string(index=False))
cac.to_csv(OUT + r'\phase4_cac_monthly.csv', index=False)

print("\n=== revenue by region (delivery postcode), last 12 months ===")
geo = q(f"""
  WITH {ORDERS}
  SELECT UPPER(REGEXP_EXTRACT(TRIM(delivery_post_code), r'^[A-Za-z]+')) AS pc_area,
         COUNT(*) AS orders, ROUND(SUM(sub_total),0) AS revenue
  FROM orders
  WHERE od BETWEEN '2025-07-01' AND '2026-06-30'
  GROUP BY 1 ORDER BY revenue DESC
""")
geo.to_csv(OUT + r'\phase4_revenue_by_pcarea.csv', index=False)
pc_cov = geo[geo.pc_area.notna()].revenue.sum() / geo.revenue.sum() * 100
print("postcode coverage of revenue: %.1f%% | top areas:" % pc_cov)
print(geo.head(12).to_string(index=False))

print("\n=== inventory signals ===")
inv = q("""
  SELECT product_group_name, COUNT(*) AS skus,
         ROUND(SUM(SAFE_CAST(total_cost AS FLOAT64)),0) AS stock_value,
         SUM(SAFE_CAST(qty_on_hand AS FLOAT64)) AS units_on_hand,
         COUNTIF(SAFE_CAST(days_since_last_sale AS INT64) > 180
                 AND SAFE_CAST(qty_on_hand AS FLOAT64) > 0) AS skus_stale_180d,
         ROUND(SUM(IF(SAFE_CAST(days_since_last_sale AS INT64) > 180,
                      SAFE_CAST(total_cost AS FLOAT64), 0)),0) AS stale_value
  FROM `trustwarehouse.bronze.unleashed_stock_on_hand`
  GROUP BY 1 ORDER BY stock_value DESC LIMIT 10
""")
print(inv.to_string(index=False))
inv.to_csv(OUT + r'\phase4_inventory.csv', index=False)
