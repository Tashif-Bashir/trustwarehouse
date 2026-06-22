"""Entry point — run as: uv run python -m ingestion.sharpspring_notes

Separate, slow, daily pipeline for SharpSpring lead notes. Kept out of the main
30-minute sharpspring sync because it makes one API call per lead.
"""

from ingestion.sharpspring.notes_pipeline import run_notes_pipeline

run_notes_pipeline()
