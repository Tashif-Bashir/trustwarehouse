import duckdb
import os

con = duckdb.connect("md:trust-pipeline?motherduck_token=" + os.environ["MOTHERDUCK_TOKEN"])

print("=== Yesterday's agent performance (2026-05-14) ===")
rows = con.execute("""
    SELECT
        agent_name,
        department,
        total_calls,
        outbound_calls,
        inbound_calls,
        missed_calls,
        qualified_conversations,
        qualified_outbound_conversations,
        appointments_booked,
        qual_convos_per_appointment,
        calls_per_appointment,
        on_target
    FROM gold.gold_agent_performance_daily
    WHERE date = CURRENT_DATE - INTERVAL 1 DAY
    ORDER BY appointments_booked DESC
""").fetchall()

print(f"{'agent':<22} {'dept':<14} {'total':>5} {'out':>5} {'in':>4} {'missed':>6} {'qual':>5} {'qual_out':>8} {'appts':>5} {'conv':>6} {'c/appt':>7} {'target':>7}")
print("-" * 110)
for row in rows:
    print(f"{str(row[0]):<22} {str(row[1] or ''):<14} {row[2]:>5} {row[3]:>5} {row[4]:>4} {row[5]:>6} {row[6]:>5} {row[7]:>8} {row[8]:>5} {str(row[9] or ''):>6} {str(row[10] or ''):>7} {str(row[11]):>7}")
