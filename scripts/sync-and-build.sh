#!/usr/bin/env bash
# Usage: sync-and-build.sh <wildix|sharpspring>
# Runs the ingestion module, dbt-builds the relevant downstream silver+gold,
# then busts the dashboard cache. Uses flock to serialize the dbt step.
set -euo pipefail
SOURCE="$1"
cd "$HOME/trustwarehouse"
export PATH="$HOME/.local/bin:$PATH"

# 1. Sync the source data into bronze
uv run python -m "ingestion.${SOURCE}" 2>&1 | grep -vE "(UserWarning|warnings.warn|google-cloud-bigquery-storage)" || true

# 2. dbt build the downstream models for this source
SELECTOR=""
case "$SOURCE" in
  wildix)
    SELECTOR="silver_wildix_calls silver_wildix_colleagues gold_lead_activity gold_lead_calls gold_agent_performance_daily"
    ;;
  sharpspring)
    SELECTOR="silver_sharpspring_leads silver_sharpspring_campaigns silver_sharpspring_opportunities silver_sharpspring_deal_stages silver_google_ads_spend silver_meta_spend silver_bing_spend gold_lead_activity gold_campaign_attribution gold_agent_performance_daily gold_pipeline_opportunities"
    ;;
esac

flock /tmp/dbt.lock uv run dbt build --project-dir dbt_project --profiles-dir dbt_project --target prod --threads 4 --select $SELECTOR 2>&1 | tail -5

# 3. Bust dashboard cache so the next page load shows fresh numbers
curl -sf -X POST https://trustwarehouse.vercel.app/api/refresh --max-time 5 -o /tmp/refresh.json && cat /tmp/refresh.json || echo "refresh endpoint not reachable (non-fatal)"
echo " sync-and-build [$SOURCE] complete"
