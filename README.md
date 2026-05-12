# Heating Company Data Warehouse

Medallion-architecture cloud data warehouse pulling from SharpSpring (CRM), Wildix (phone), Google Ads / Meta / Bing (ad spend), and manual CSV uploads into Motherduck (cloud DuckDB).

## Architecture

See [Architecture.md](Architecture.md) for the full system design. In brief:

```
Sources → Bronze (raw) → Silver (clean) → Gold (joined, queryable)
```

All scheduling is handled by **GitHub Actions**. Ad platform syncs use **Airbyte Cloud**, triggered via Airbyte API key from GitHub Actions. CRM and phone data use **Python + dlt**.

## Local setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- A Motherduck account and token ([motherduck.com](https://motherduck.com))

### Install

```bash
uv sync
```

### Configure environment

```bash
cp .env.example .env
# Fill in MOTHERDUCK_TOKEN and other credentials
```

### Test connection

```bash
uv run python -c "from shared.motherduck import get_connection; print(get_connection().sql('SELECT 1').fetchone())"
```

## Project structure

| Directory | Purpose |
|---|---|
| `ingestion/` | Python ingestion scripts (SharpSpring, Wildix, manual CSVs) |
| `scrapers/` | Playwright scraper (Wildix fallback — not active) |
| `dbt_project/` | dbt transformations (silver + gold layers) |
| `shared/` | Shared utilities (phone normalisation, Motherduck connection) |
| `tests/` | Python unit tests |
| `docs/` | Data dictionary, runbooks, example queries |
| `scripts/` | One-off utility scripts |
| `.github/workflows/` | GitHub Actions (syncs, CI, pipeline build) |

## Running syncs manually

```bash
# SharpSpring
uv run python -m ingestion.sharpspring

# Wildix
uv run python -m ingestion.wildix

# Manual CSV
uv run python -m ingestion.manual --file path/to/file.csv --table manual_secured_leads --key lead_id
```

## Running tests

```bash
uv run pytest
uv run pytest tests/test_phone.py -v   # phone normalisation tests
```

## Adding a new data source

See [docs/adding_a_new_source.md](docs/adding_a_new_source.md).
