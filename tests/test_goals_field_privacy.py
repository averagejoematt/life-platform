"""tests/test_goals_field_privacy.py — config/user_goals.json is private by default, field by field (owner 2026-11-10, 6).

What is pinned:
  * COVERAGE: every field in config/user_goals.json is named by the review; a new field reds here until it is
    reviewed (and until then ``classify`` already says private);
  * the sections the review found private classify private; an unnamed path is private (fail closed);
  * THE SEALED CALLS: each of the 14 approved day-one calls read exactly the plan digest, every field of which is
    public-safe — and if any of those fields were private, every one of them would be withheld (negative control);
  * a sealed call withheld by an earlier ruling stays withheld (negative control), and lead reads read no goals field.
"""

# premerge-gate: goals-file field privacy (owner 2026-11-10, 6): reads config/user_goals.json and the frozen pre-registration artifact — a new goals field or a regenerated artifact must red before merge.
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "tests"))

import sealed_prereg  # noqa: E402
from common import (
    goals_field_privacy as GFP,  # noqa: E402
    narrative_allowlist as NA,  # noqa: E402
)
from web import narrative_publication as G  # noqa: E402

GOALS = json.loads((ROOT / "config" / "user_goals.json").read_text())
# The sealed file is private since 2026-11-11 (owner ruling item 3): tests/sealed_prereg.py serves the approved calls'
# words from a labelled test copy, and every sealed call's words only from the private original when present.
SEALED = sealed_prereg.sealed_call_texts()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{p}.{k}" if p else k)
    elif isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
        for i, v in enumerate(o):
            yield from _leaves(v, f"{p}[{i}]")
    else:
        yield p


def _calls():
    return [e for e in NA.APPROVED if e.sk.startswith("PREDICTION#")]


def _sealed_row(entry) -> dict:
    claim = next(c for c in SEALED if _sha(c) == entry.text_sha256)
    return {"pk": entry.pk, "sk": entry.sk, "claim_natural": claim, "status": "refuted", "prediction_id": entry.sk[len("PREDICTION#") :]}


@pytest.fixture
def cr2_on(monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)


def test_every_goals_field_is_named_by_the_review():
    unnamed = [p for p in _leaves(GOALS) if not GFP.is_named(p)]
    assert unnamed == [], f"review these goals fields (private until named): {unnamed}"


@pytest.mark.parametrize(
    "path",
    [
        "mental_health_context.drivers",
        "mental_health_context.coach_guidance",
        "athlete_profile.binge_eating_pattern",
        "athlete_profile.weight_cycling_history",
        "failure_mode.last_trigger",
        "failure_mode.early_warning_signals",
        "targets.biomarkers.note",
        "targets.behavioral.journal_entries_per_week",
        "known_constraints",
        "a_field_nobody_reviewed",
        "targets.biomarkers.a_new_marker_target",
    ],
)
def test_private_and_unnamed_paths_are_private(path):
    assert GFP.classify(path) == GFP.PRIVATE


def test_the_sealed_call_digest_reads_only_public_safe_fields():
    assert len(GFP.SEALED_CALL_DIGEST_FIELDS) == 20
    assert {p: GFP.classify(p) for p in GFP.SEALED_CALL_DIGEST_FIELDS} == {p: GFP.PUBLIC_SAFE for p in GFP.SEALED_CALL_DIGEST_FIELDS}
    for e in _calls():
        assert GFP.goals_inputs_for(e.pk, e.sk) == GFP.SEALED_CALL_DIGEST_FIELDS, e.sk
    for e in NA.APPROVED:
        if e.sk.startswith("LEAD_DAILY#"):
            assert GFP.goals_inputs_for(e.pk, e.sk) == (), "a lead read reads the profile row, never the goals file"


def test_the_approved_sealed_calls_are_served_in_scope(cr2_on):
    with NA.serving(NA.SCOPE_CR2):
        for e in _calls():
            assert NA.record_for(_sealed_row(e)) is not None, e.sk


def test_negative_control_a_private_digest_field_withholds_every_sealed_call(cr2_on, monkeypatch):
    """If the review had found ONE digest field private, no sealed call could be published: each prompt read it."""
    monkeypatch.setattr(GFP, "_PUBLIC_SAFE", tuple(p for p in GFP._PUBLIC_SAFE if p != "targets.biomarkers.ldl_target_mg_dl"))
    assert GFP.classify("targets.biomarkers.ldl_target_mg_dl") == GFP.PRIVATE
    with NA.serving(NA.SCOPE_CR2):
        for e in _calls():
            row = _sealed_row(e)
            assert NA.record_for(row) is None, e.sk
            G.begin_request()
            assert G.gate_item(dict(row), strict=True)["claim_natural"] == ""
            assert G.withheld_count() == 1


def test_negative_control_a_withheld_sealed_call_stays_withheld(cr2_on):
    """The sealed calls not on the list (the two the 2026-11-09 ruling keeps private) stay withheld in the CR2 scope,
    whatever key they are read under."""
    sealed_prereg.require_sealed_path()  # the two withheld calls exist only in the private original
    listed = {e.text_sha256 for e in _calls()}
    withheld = [c for c in SEALED if _sha(c) not in listed]
    assert len(withheld) == 2
    with NA.serving(NA.SCOPE_CR2):
        for claim in withheld:
            for sk in [e.sk for e in _calls()] + ["PREDICTION#pred_20260906_" + _sha(claim)[:20]]:
                row = {"pk": "COACH#mind_coach", "sk": sk, "claim_natural": claim}
                assert NA.record_for(row) is None
                G.begin_request()
                assert G.gate_item(dict(row), strict=True)["claim_natural"] == ""


def test_the_module_carries_no_goal_values():
    src = (ROOT / "lambdas" / "common" / "goals_field_privacy.py").read_text()
    for path in _leaves(GOALS):
        if GFP.classify(path) != GFP.PRIVATE:
            continue
        node = GOALS
        for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
            node = node[int(part[1:-1])] if part.startswith("[") else node[part]
        for value in node if isinstance(node, list) else [node]:
            words = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split()
            for i in range(max(0, len(words) - 5)):
                assert " ".join(words[i : i + 6]) not in re.sub(r"[^a-z0-9]+", " ", src.lower()), path
