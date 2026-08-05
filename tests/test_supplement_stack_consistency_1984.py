"""tests/test_supplement_stack_consistency_1984.py — regression guard for #1984.

/protocols/discoveries and /protocols/supplements are two unreconciled sources of
truth for "what Matthew is currently taking": config/experiment_library.json holds
status=="active" pillar=="supplements" entries (rendered on the discoveries page as
standing protocols "under continuous measurement"), while config/supplement_registry.json
is the actual tracked stack served at /api/supplements. As of the #1984 filing, the
library held 4 such entries (tongkat-ali-recovery, nmn-nad-precursor, creatine-strength,
berberine-glucose) and the registry only confirmed one of them (creatine).

The fix (site_api_ledger._supplement_stack_match, #1984) is display-only: it does NOT
change the raw `status` field on any library entry (that would assert a false status
either way — the owner data decision of whether Matthew is still taking these is
explicitly NOT this repo's to make; see the PR body). Because the raw status stays
"active" with no stack match for three of the four entries, this guard uses the
allowlist-and-dated-exception pattern already established in
tests/test_heartbeat_completeness.py rather than requiring every entry to pass.

Non-vacuous: `test_unallowlisted_mismatch_is_caught` proves the check actually fires
against a synthetic entry that isn't on the allowlist.
"""

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from web.site_api_ledger import _supplement_stack_match  # noqa: E402

ROOT_LIBRARY = _REPO / "config" / "experiment_library.json"
ROOT_REGISTRY = _REPO / "config" / "supplement_registry.json"

# Dated, issue-referenced exemptions (pattern per tests/test_heartbeat_completeness.py's
# EXEMPT rows): a library entry that is pillar=="supplements", status=="active", and has
# no matching non-paused supplement_registry.json entry, but is a KNOWN, filed gap — not
# a silently-tolerated one. Each row is the open owner data decision: add the compound to
# the tracked stack, or relabel/close the library entry as no longer running. Until that
# decision lands, /protocols/discoveries labels these "unconfirmed_protocol" rather than
# "under continuous measurement" (site_api_ledger.discoveries, #1984) — the allowlist
# below is what keeps this regression guard honest about the SAME gap, not silent on it.
ALLOWLIST = {
    "tongkat-ali-recovery": ("2026-08-04", "#1984", "no supplement_registry.json entry for tongkat/Eurycoma longifolia"),
    "nmn-nad-precursor": ("2026-08-04", "#1984", "no supplement_registry.json entry for NMN"),
    "berberine-glucose": ("2026-08-04", "#1984", "no supplement_registry.json entry for berberine"),
}


def _load(path):
    return json.loads(path.read_text())


def unmatched_active_supplement_entries(library, registry):
    """Entries with pillar=='supplements', status=='active', and no matching
    non-paused registry entry — the raw set this guard checks, before allowlisting."""
    out = []
    for exp in library.get("experiments", []):
        if exp.get("pillar") != "supplements" or exp.get("status") != "active":
            continue
        if not _supplement_stack_match(exp.get("name", ""), registry):
            out.append(exp.get("id"))
    return out


def test_configs_exist_and_parse():
    assert json.loads(ROOT_LIBRARY.read_text())
    assert json.loads(ROOT_REGISTRY.read_text())


def test_every_unmatched_active_supplement_entry_is_allowlisted():
    library = _load(ROOT_LIBRARY)
    registry = _load(ROOT_REGISTRY)
    unmatched = unmatched_active_supplement_entries(library, registry)
    unlisted = [eid for eid in unmatched if eid not in ALLOWLIST]
    assert not unlisted, (
        f"experiment_library.json entries {unlisted} are pillar=='supplements', status=='active', and have no "
        f"matching non-paused config/supplement_registry.json entry — reconcile them (relabel or add to the stack, "
        f"#1984's acceptance criteria) or add a dated, issue-referenced ALLOWLIST row explaining why the gap is known."
    )


def test_allowlist_entries_are_still_actually_mismatched():
    """The allowlist should track REAL, current gaps — not accumulate stale rows for
    entries that got reconciled. If an allowlisted id now has a stack match (or no
    longer exists / isn't active supplements), its row is dead weight and should be
    removed."""
    library = _load(ROOT_LIBRARY)
    registry = _load(ROOT_REGISTRY)
    still_unmatched = set(unmatched_active_supplement_entries(library, registry))
    stale = sorted(set(ALLOWLIST) - still_unmatched)
    assert not stale, f"ALLOWLIST rows no longer reflect a real mismatch (reconciled or removed upstream): {stale}"


def test_allowlist_rows_are_dated_and_issue_referenced():
    for eid, (date, issue, reason) in ALLOWLIST.items():
        assert date.count("-") == 2 and len(date) == 10, f"{eid}: exemption date {date!r} is not YYYY-MM-DD"
        assert issue.startswith("#") and issue[1:].isdigit(), f"{eid}: exemption issue {issue!r} is not a #N reference"
        assert reason, f"{eid}: exemption has no reason"


def test_unallowlisted_mismatch_is_caught():
    """Non-vacuous proof: a synthetic active supplements-pillar entry with no stack
    match and NOT on the allowlist must be flagged by the same check the real-config
    test above runs."""
    library = {
        "experiments": [
            {"id": "fictitious-nootropic-9000", "name": "Fictitious Nootropic 9000", "pillar": "supplements", "status": "active"},
        ]
    }
    registry = {"groups": {"cognitive": {"items": [{"key": "lions_mane", "name": "Lion's Mane"}]}}}
    unmatched = unmatched_active_supplement_entries(library, registry)
    assert unmatched == ["fictitious-nootropic-9000"]
    assert "fictitious-nootropic-9000" not in ALLOWLIST


def test_matched_entry_is_not_flagged():
    library = {
        "experiments": [
            {"id": "creatine-strength", "name": "Creatine Monohydrate — Strength", "pillar": "supplements", "status": "active"},
        ]
    }
    registry = {"groups": {"muscle": {"items": [{"key": "creatine", "name": "Creatine Monohydrate"}]}}}
    assert unmatched_active_supplement_entries(library, registry) == []


def test_paused_registry_entry_does_not_count_as_a_match():
    library = {
        "experiments": [
            {"id": "x", "name": "Creatine Monohydrate — Strength", "pillar": "supplements", "status": "active"},
        ]
    }
    registry = {"groups": {"muscle": {"items": [{"key": "creatine", "name": "Creatine Monohydrate", "paused": True}]}}}
    assert unmatched_active_supplement_entries(library, registry) == ["x"]


def test_backlog_and_non_supplements_entries_are_never_checked():
    library = {
        "experiments": [
            {"id": "a", "name": "Ashwagandha", "pillar": "supplements", "status": "backlog"},
            {"id": "b", "name": "Sauna", "pillar": "recovery", "status": "active"},
        ]
    }
    registry = {"groups": {}}
    assert unmatched_active_supplement_entries(library, registry) == []
