"""tests/test_challenge_evidence_provenance_3521.py — #3521: no undated number on the challenges door.

THE DEFECT (live, Day 0 of cycle 16). `/api/challenges` (82 entries, source
"catalog+live") and `/api/challenge_catalog` passed `evidence_summary` through verbatim.
26 of the catalog's 82 entries carry a digit, and five of those are Matthew's OWN
measurements — written into the catalog on 2026-03-28 (git blame 1c44301ef7,
seeds/challenges_catalog.json):

    nsdr-reset               "HRV 29.56 — this is indicated now."
    10-day-walk-streak       "Walk 5k was missed 14 of 20 tracked days"
    no-drift-weekends        "Calorie goal was missed 13 of 20 tracked days"
    zone-2-foundation-block  "CTL 4.45 … ACWR 0.26 …"
    minimum-viable-day       "After a 10-day complete zero period …"

`config/challenges_catalog.json` is CONFIG. The shared wipe manifest lists challenges as
EXPERIMENT_SCOPED, but no reset reaches a config file — so those numbers survived every
re-anchor and kept saying "now" cycles later. The reader-truth judge raised three
reproduced highs on /protocols/challenges/ for exactly these.

THE DISTINCTION THIS ENCODES (docs/PHASE_TAXONOMY.md). A published finding ("10,000
steps/day associated with 40-50% reduction in all-cause mortality") is CROSS-PHASE: it is
not about Matthew, no reset invalidates it, and it serves unchanged. A measurement OF
Matthew is EXPERIMENT-SCOPED and needs its date. The catalog stamps which it is; the API
derives the rest.

FAIL CLOSED is the load-bearing property: a digit-bearing summary with NO stamp is
DROPPED, so the guard cannot be defeated by forgetting to stamp a new entry — the failure
mode is a missing sentence, never an undated number.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(_REPO, "config", "challenges_catalog.json")

from web.site_api_social_challenges import challenge_evidence_view  # noqa: E402

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _entries():
    with open(CATALOG, encoding="utf-8") as f:
        return json.load(f)["challenges"]


def _has_digit(text):
    return any(c.isdigit() for c in str(text or ""))


# ── the catalog contract, over the WHOLE corpus ──────────────────────────────


def test_every_digit_bearing_evidence_summary_declares_its_scope():
    """THE SET GUARD: every entry, not a sample. A new digit-bearing entry fails here
    until someone decides whether its number is literature or a measurement."""
    unstamped = [
        c["id"] for c in _entries() if _has_digit(c.get("evidence_summary")) and c.get("evidence_scope") not in ("literature", "personal")
    ]
    assert not unstamped, (
        "evidence_summary carries a number with no evidence_scope — add "
        '"evidence_scope": "literature" (a published finding) or "personal" + '
        f'"evidence_as_of": "YYYY-MM-DD" (a measurement of Matthew): {unstamped}'
    )


def test_every_personal_evidence_entry_carries_an_iso_as_of_date():
    bad = []
    for c in _entries():
        if c.get("evidence_scope") != "personal":
            continue
        as_of = c.get("evidence_as_of")
        if not (isinstance(as_of, str) and _ISO.match(as_of)):
            bad.append((c["id"], as_of))
    assert not bad, f"personal evidence must carry an ISO evidence_as_of: {bad}"


def test_the_corpus_still_contains_both_classes_the_guard_is_not_vacuous():
    scopes = [c.get("evidence_scope") for c in _entries() if _has_digit(c.get("evidence_summary"))]
    assert scopes.count("literature") >= 15, "literature evidence vanished — the guard would be measuring nothing"
    assert scopes.count("personal") >= 5, "the five prior-cycle measurements must still be classified"


def test_the_five_named_prior_cycle_entries_are_stamped_personal():
    by_id = {c["id"]: c for c in _entries()}
    for cid in ("nsdr-reset", "10-day-walk-streak", "no-drift-weekends", "zone-2-foundation-block", "minimum-viable-day"):
        assert by_id[cid].get("evidence_scope") == "personal", f"{cid} is one of the reproduced reader-truth highs"
        assert by_id[cid].get("evidence_as_of") == "2026-03-28"


def test_a_literature_entry_is_not_mislabelled_personal():
    by_id = {c["id"]: c for c in _entries()}
    # A published mortality association is not about Matthew and takes no cycle stamp.
    assert by_id["10k-steps-daily"]["evidence_scope"] == "literature"
    assert "evidence_as_of" not in by_id["10k-steps-daily"]


# ── the API derivation ───────────────────────────────────────────────────────


def _live_entry(cid):
    return {c["id"]: c for c in _entries()}[cid]


def test_pre_genesis_a_personal_number_is_dropped_entirely():
    view = challenge_evidence_view(_live_entry("10-day-walk-streak"), today_iso="2026-09-05")
    assert view["evidence_summary"] == "", "a prior-cycle measurement has no 'now' to be true of before Day 1"
    assert view["evidence_scope"] == "personal"
    assert view["evidence_as_of"] == "2026-03-28"
    assert view["evidence_prior_cycle"] is True


def test_in_cycle_a_personal_number_serves_STAMPED_not_stripped():
    view = challenge_evidence_view(_live_entry("nsdr-reset"), today_iso="2026-09-20")
    assert "HRV 29.56" in view["evidence_summary"], "in-cycle the claim serves — dated, not deleted"
    assert view["evidence_as_of"] == "2026-03-28"
    assert view["evidence_prior_cycle"] is True, "measured before the live genesis"


def test_literature_evidence_is_untouched_in_every_phase():
    entry = _live_entry("10k-steps-daily")
    for today in ("2026-09-05", "2026-09-20"):
        view = challenge_evidence_view(entry, today_iso=today)
        assert view["evidence_summary"] == entry["evidence_summary"]
        assert view["evidence_prior_cycle"] is False
        assert view["evidence_as_of"] is None


def test_an_UNSTAMPED_number_fails_closed_and_is_dropped():
    """The property that makes the catalog guard enforceable rather than advisory: a new
    digit-bearing entry that nobody classified never reaches a reader."""
    view = challenge_evidence_view({"id": "x", "evidence_summary": "HRV 42.0 right now"}, today_iso="2026-09-20")
    assert view["evidence_summary"] == ""
    assert view["evidence_scope"] is None


def test_a_number_free_summary_needs_no_stamp():
    entry = {"id": "y", "evidence_summary": "Loaded carries improve bone density and grip strength"}
    view = challenge_evidence_view(entry, today_iso="2026-09-20")
    assert view["evidence_summary"] == entry["evidence_summary"]


def test_a_personal_entry_measured_INSIDE_the_live_cycle_is_not_flagged_prior():
    from common.constants import EXPERIMENT_START_DATE

    entry = {"id": "z", "evidence_summary": "HRV 51.2 over 10 days", "evidence_scope": "personal", "evidence_as_of": EXPERIMENT_START_DATE}
    view = challenge_evidence_view(entry, today_iso="2026-12-01")
    assert view["evidence_prior_cycle"] is False
    assert "HRV 51.2" in view["evidence_summary"]


def test_the_view_always_returns_all_five_keys():
    """An absent stamp must never be readable as 'current' by a consumer that uses
    `.get()` — every path returns the full shape, including the PACIFIC day the
    pre-genesis decision was made on (#2813)."""
    for entry in ({}, {"evidence_summary": ""}, _live_entry("nsdr-reset"), _live_entry("10k-steps-daily")):
        view = challenge_evidence_view(entry, today_iso="2026-09-20")
        assert set(view) == {"evidence_summary", "evidence_scope", "evidence_as_of", "evidence_prior_cycle", "evidence_evaluated_on"}


def test_both_handlers_route_evidence_through_the_derivation():
    """A source guard: neither handler may pass the raw catalog string again. The catalog
    handler deep-copies the whole entry, so a future edit that drops the `update()` call
    silently restores the defect."""
    src = open(os.path.join(_REPO, "lambdas", "web", "site_api_social_challenges.py"), encoding="utf-8").read()
    assert src.count("challenge_evidence_view(") >= 3, "both handlers plus the definition"
    assert 'c.get("evidence_summary", "")' not in src, "the raw catalog string must not be served verbatim any more"
