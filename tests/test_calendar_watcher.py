"""Unit tests for the calendar-watcher attribution upgrade.

Pure-logic tests only — no BigQuery client, no Graph/SharpSpring network calls.
Covers: the owner->booker map (incl. the Peter/Alisha/unknown invalid cases),
the self-heal decision function, the (name+postcode) match-ladder rung's
selection/normalisation helpers, and the parenthetical-subject stripper.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.calendar_watcher import (  # noqa: E402
    MADE_BY_TO_BOOKER,
    VALID_BOOKER_OWNERS,
    _norm_postcode,
    _pick_unique,
    _strip_parens,
    event_stamp,
    known_skip,
    load_skip_cache,
    resolve_booker,
    save_skip_cache,
    self_heal_decision,
)

# ---------------------------------------------------------------------------
# resolve_booker — owner ID -> booker map
# ---------------------------------------------------------------------------

def test_resolve_booker_sue():
    assert resolve_booker("349724672") == ("Sue England", "349724672", "Susan England")


def test_resolve_booker_amanda():
    assert resolve_booker("377646080") == ("Amanda Romans", "377646080", "Amanda Romans")


def test_resolve_booker_alicja():
    assert resolve_booker("368143360") == ("Alicja Aleksiuk", "368143360", "Alicja Aleksiuk")


def test_resolve_booker_peter_heaton_invalid():
    """Peter Heaton moved to field sales — no longer a valid telesales booker."""
    assert resolve_booker("PETER_HEATON_OWNER_ID") is None


def test_resolve_booker_alisha_invalid():
    """Alisha Moore is out — never a valid booker per the owner ruling."""
    assert resolve_booker("ALISHA_OWNER_ID") is None


def test_resolve_booker_unknown_id_invalid():
    assert resolve_booker("999999999") is None


def test_resolve_booker_blank_invalid():
    assert resolve_booker("") is None
    assert resolve_booker(None) is None


def test_resolve_booker_strips_whitespace():
    assert resolve_booker(" 349724672 ") == ("Sue England", "349724672", "Susan England")


def test_valid_booker_owners_exactly_three():
    """Owner ruling: exactly these three IDs, no more, no fewer."""
    assert set(VALID_BOOKER_OWNERS.keys()) == {
        "349724672", "368143360", "377646080", "377645056",
    }


# ---------------------------------------------------------------------------
# self_heal_decision — CRM stamp always wins
# ---------------------------------------------------------------------------

def test_self_heal_maps_crm_stamp_to_booker():
    assert self_heal_decision("Manual (calendar)", "Susan England") == ("Sue England", "349724672")


def test_self_heal_overrides_wrong_owner_guess():
    """A human CRM correction (Alicja) beats a stale owner-derived guess (Sue)."""
    assert self_heal_decision("Sue England", "Alicja Aleksiuk") == ("Alicja Aleksiuk", "368143360")


def test_self_heal_noop_when_already_matching():
    assert self_heal_decision("Alicja Aleksiuk", "Alicja Aleksiuk") is None


def test_self_heal_noop_for_unmapped_crm_value():
    """Someone else's picklist value (e.g. a rep, not telesales) never heals a row."""
    assert self_heal_decision("Manual (calendar)", "Gemma Taylor") is None


def test_self_heal_noop_for_blank_crm_value():
    assert self_heal_decision("Manual (calendar)", "") is None


def test_made_by_to_booker_reverse_map_consistent():
    for owner_id, (booker_name, made_by) in VALID_BOOKER_OWNERS.items():
        assert MADE_BY_TO_BOOKER[made_by] == (booker_name, owner_id)


# ---------------------------------------------------------------------------
# _strip_parens — the "(ring first)" parsing nicety
# ---------------------------------------------------------------------------

def test_strip_parens_removes_trailing_aside():
    assert _strip_parens("John Smith (ring first)") == "John Smith"


def test_strip_parens_removes_multiple_asides():
    assert _strip_parens("John Smith (ring first) - AB1 2CD (urgent)") == "John Smith - AB1 2CD"


def test_strip_parens_no_parens_unchanged():
    assert _strip_parens("John Smith - AB1 2CD") == "John Smith - AB1 2CD"


def test_strip_parens_blank_input():
    assert _strip_parens("") == ""
    assert _strip_parens(None) == ""


# ---------------------------------------------------------------------------
# name+postcode rung — normalisation + uniqueness selection
# ---------------------------------------------------------------------------

def test_norm_postcode_strips_space_and_uppercases():
    assert _norm_postcode("ab1 2cd") == "AB12CD"


def test_norm_postcode_blank():
    assert _norm_postcode("") == ""
    assert _norm_postcode(None) == ""


def test_pick_unique_single_candidate():
    cands = {"1": {"id": "1", "name": "John Smith"}}
    assert _pick_unique(cands) == {"id": "1", "name": "John Smith"}


def test_pick_unique_no_candidates():
    assert _pick_unique({}) is None


def test_pick_unique_ambiguous_candidates():
    """Two leads share a name+postcode match — never guess, leave for /links."""
    cands = {
        "1": {"id": "1", "name": "John Smith"},
        "2": {"id": "2", "name": "John Smith"},
    }
    assert _pick_unique(cands) is None


# ---------------------------------------------------------------------------
# skip cache — the 12 Sep 2026 cost fix: a skipped event is not re-searched
# every run; an edited event is.


def _ev(eid: str, modified: str, created: str = "2026-09-01T08:00:00.0000000Z") -> dict:
    return {"id": eid, "subject": "Internal sales meeting",
            "createdDateTime": created, "lastModifiedDateTime": modified}


def test_known_skip_matches_only_the_same_version():
    cache = {"ev1": "2026-09-01T09:00:00"}
    assert known_skip(_ev("ev1", "2026-09-01T09:00:00.0000000Z"), cache)
    assert not known_skip(_ev("ev1", "2026-09-05T10:30:00.0000000Z"), cache)  # edited since
    assert not known_skip(_ev("ev2", "2026-09-01T09:00:00.0000000Z"), cache)  # never seen


def test_event_stamp_falls_back_to_created():
    assert event_stamp({"createdDateTime": "2026-09-01T08:00:00.0000000Z"}) == "2026-09-01T08:00:00"
    assert event_stamp({}) == ""


def test_skip_cache_round_trip_prunes_ids_outside_the_window(tmp_path):
    path = tmp_path / "skipped.json"
    save_skip_cache({"keep": "a", "gone": "b"}, keep_ids={"keep"}, path=path)
    assert load_skip_cache(path) == {"keep": "a"}


def test_skip_cache_missing_or_corrupt_file_is_empty(tmp_path):
    assert load_skip_cache(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_skip_cache(bad) == {}
