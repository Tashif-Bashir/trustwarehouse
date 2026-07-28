#!/usr/bin/env bash
# Usage: sync-and-build.sh <wildix|sharpspring|sharpspring_notes|google_ads|meta|ga4|unleashed|ascend|gold_calls|test_calls>
# Runs the ingestion module, dbt-builds the relevant downstream silver+gold,
# then busts the dashboard cache. Uses flock to serialize the dbt step.
# Sources with no dbt selector (e.g. sharpspring_notes) just land bronze data.
# gold_calls / test_calls are dbt-only pseudo-sources (no ingestion): BigQuery
# bills a 10MB minimum per query, so the 60s ascend cycle rebuilds ONLY the
# table the live metres read; the heavier call-chain models rebuild every 10min
# (gold_calls timer) and their tests run hourly (test_calls timer).
set -euo pipefail
SOURCE="$1"
cd "$HOME/trustwarehouse"
export PATH="$HOME/.local/bin:$PATH"

# Pull latest model changes from git before building.
git pull --ff-only origin main 2>&1 | tail -3 || echo "git pull failed (non-fatal)"

# 1. Sync the source data into bronze.
# Direct-API ingestions (google_ads, meta, ga4) need a --run flag; dlt-based
# ones (wildix, sharpspring) just default to running their pipeline.
INGEST_ARGS=""
case "$SOURCE" in
  google_ads|meta|ga4)
    INGEST_ARGS="--run --days 7"
    ;;
esac
if [[ "$SOURCE" != "gold_calls" && "$SOURCE" != "test_calls" ]]; then
  uv run python -m "ingestion.${SOURCE}" $INGEST_ARGS 2>&1 | grep -vE "(UserWarning|warnings.warn|google-cloud-bigquery-storage)" || true
fi

# 2. dbt build the downstream models for this source.
# GA4 has no dbt dependencies — the dashboard reads GA4 bronze tables directly
# via api/index.py — so we skip dbt entirely for that source.
SELECTOR=""
DBT_CMD="build"
case "$SOURCE" in
  wildix)
    SELECTOR="silver_wildix_calls silver_wildix_colleagues gold_lead_activity gold_lead_calls gold_agent_performance_daily"
    ;;
  sharpspring)
    SELECTOR="sales_rep_mapping silver_sharpspring_leads silver_sharpspring_campaigns silver_sharpspring_opportunities silver_sharpspring_deal_stages silver_sharpspring_notes silver_google_ads_spend silver_meta_spend silver_bing_spend gold_lead_activity gold_campaign_attribution gold_agent_performance_daily gold_pipeline_opportunities gold_sales_reconciled gold_sales_exceptions"
    ;;
  google_ads)
    SELECTOR="silver_google_ads_spend gold_google_ads_spend_by_region gold_campaign_attribution gold_leads_by_region"
    ;;
  meta)
    SELECTOR="silver_meta_spend silver_meta_geographic gold_campaign_attribution gold_leads_by_region"
    ;;
  ga4)
    SELECTOR=""  # no dbt step
    ;;
  ascend)
    # 60s cycle: models only, and only the table the live metres read
    SELECTOR="silver_ascend_calls"
    DBT_CMD="run"
    ;;
  gold_calls)
    # dashboard call-chain models — every 10 min is fresh enough for laptop views
    SELECTOR="silver_calls_unified gold_lead_activity gold_lead_calls gold_agent_performance_daily"
    DBT_CMD="run"
    ;;
  test_calls)
    # hourly data-quality tests over the whole call chain
    SELECTOR="silver_ascend_calls silver_calls_unified gold_lead_activity gold_lead_calls gold_agent_performance_daily"
    DBT_CMD="test"
    ;;
  unleashed)
    SELECTOR="silver_unleashed_customers silver_unleashed_products silver_unleashed_sales_orders silver_unleashed_stock_on_hand gold_sales_orders gold_sales_reconciled"
    ;;
esac

if [ -n "$SELECTOR" ]; then
  flock /tmp/dbt.lock uv run dbt "$DBT_CMD" --project-dir dbt_project --profiles-dir dbt_project --target prod --threads 4 --select $SELECTOR 2>&1 | tail -5
fi

# 3. Bust dashboard cache so the next page load shows fresh numbers
curl -sf -X POST https://trustwarehouse.vercel.app/api/refresh --max-time 5 -o /tmp/refresh.json && cat /tmp/refresh.json || echo "refresh endpoint not reachable (non-fatal)"
echo " sync-and-build [$SOURCE] complete"
