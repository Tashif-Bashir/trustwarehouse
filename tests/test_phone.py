"""Tests for shared/phone.py — normalise_phone() against 23 UK number formats."""

import pytest

from shared.phone import normalise_phone


@pytest.mark.parametrize(
    "raw, expected",
    [
        # --- Standard UK mobile (07xxx) ---
        ("07700900123", "447700900123"),
        ("07700 900123", "447700900123"),       # one space
        ("07700 900 123", "447700900123"),      # two spaces
        ("07700-900-123", "447700900123"),      # dashes
        ("07700.900.123", "447700900123"),      # dots
        ("  07700 900 123  ", "447700900123"),  # leading/trailing whitespace

        # --- International +44 format ---
        ("+44 7700 900123", "447700900123"),    # +44 with space
        ("+447700900123", "447700900123"),      # +44 compact
        ("+44 (0) 7700 900-123", "4407700900123"),  # +44 (0) — (0) becomes literal digit, returned as-is

        # --- 00-prefix (international dialling) ---
        ("00447700900123", "447700900123"),     # 00 compact
        ("0044 7700 900123", "447700900123"),   # 00 with space

        # --- London landline (020) ---
        ("020 7946 0958", "442079460958"),
        ("+44 20 7946 0958", "442079460958"),   # London international

        # --- Regional landline ---
        ("01132 123456", "441132123456"),       # Leeds

        # --- Already normalised (no leading 0 or 00) ---
        ("447700900123", "447700900123"),
        ("442079460958", "442079460958"),

        # --- No leading zero — returned digits-only, no prefix added ---
        ("7700900123", "7700900123"),

        # --- Null / empty / non-numeric ---
        ("", None),
        (None, None),
        ("   ", None),
        ("not a number", None),
        ("N/A", None),

        # --- Mixed edge cases ---
        ("(0) 7700 900123", "447700900123"),    # brackets around leading 0
    ],
)
def test_normalise_phone(raw, expected):
    assert normalise_phone(raw) == expected
