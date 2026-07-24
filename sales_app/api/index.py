"""Vercel entry point for the Trust Sales webapp."""
from __future__ import annotations

import sys
from pathlib import Path

# Add sales_app root to sys.path so `from app import app` works
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app  # noqa: E402
