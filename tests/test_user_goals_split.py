"""tests/test_user_goals_split.py — the plan root is split public/private (owner ruling 2026-11-11, item 2).

What is pinned:
  * THE TRACKED FILE: ``config/user_goals.json`` carries ONLY paths ``goals_field_privacy`` classifies public-safe —
    a private (or unreviewed) field added to it reds here before merge;
  * THE PARTITION: ``split`` puts every leaf where the classifier says, ``merge`` restores the document, a list mixing
    classes refuses to split, and on a clash the public value wins;
  * THE LOADER: the private part is read from the off-repo path, else S3 only in Lambda or with an explicit client;
    missing, it is ABSENT (no stand-in); the public part comes from the repo file, else the S3 twin;
  * NOT A TWIN: the private key has no repo file, so the config twin sync can never write or delete it.

Every private value here is SYNTHETIC — the repo is public.
"""

# premerge-gate: goals privacy split (owner 2026-11-11, item 2): reads the tracked config/user_goals.json — a private field committed to it must red before merge.
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import (
    goals_field_privacy as GFP,  # noqa: E402
    user_goals as U,  # noqa: E402
)

TRACKED = json.loads((ROOT / "config" / "user_goals.json").read_text())

SYNTHETIC = {
    "version": "x",
    "mission": "synthetic mission prose",
    "timeline": {"start_date": "2030-01-01", "start_weight_lbs": 200.0},
    "targets": {
        "weight": {"goal_lbs": 150, "interim_milestones": [{"lbs": 190, "label": "a"}, {"lbs": 180, "label": "b"}]},
        "biomarkers": {"resting_hr_target_bpm": 50, "ldl_target_mg_dl": 1, "note": "synthetic clinical note"},
        "nutrition": {"daily_protein_min_g": 100, "calorie_approach": "synthetic approach"},
    },
    "failure_mode": {"response_owner": "mind_coach", "pattern": "synthetic", "early_warning_signals": ["s1", "s2"]},
    "known_constraints": ["synthetic constraint"],
    "a_field_nobody_reviewed": {"x": 1},
}


class _Body:
    def __init__(self, raw):
        self._raw = raw

    def read(self):
        return self._raw


class FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.gets = []

    def get_object(self, Bucket=None, Key=None, **_kw):
        self.gets.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(json.dumps(self.objects[Key]).encode())}


def _leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{p}.{k}" if p else k)
    elif isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
        for i, v in enumerate(o):
            yield from _leaves(v, f"{p}[{i}]")
    else:
        yield p


# ── the tracked file ─────────────────────────────────────────────────────────


def test_the_tracked_plan_root_holds_only_public_safe_fields():
    private = [p for p in _leaves(TRACKED) if GFP.classify(p) != GFP.PUBLIC_SAFE]
    assert private == [], f"private goals fields belong in the private part (common.user_goals), not the public repo: {private}"
    assert U.private_paths_in(TRACKED) == []


def test_the_owner_ruled_sections_are_absent_from_the_tracked_file():
    for gone in ("mission", "philosophy", "mental_health_context", "known_constraints"):
        assert gone not in TRACKED
    assert "ldl_target_mg_dl" not in TRACKED["targets"]["biomarkers"] and "note" not in TRACKED["targets"]["biomarkers"]
    assert set(TRACKED["failure_mode"]) <= {"response_owner", "what_was_missing_last_time"}
    assert "binge_eating_pattern" not in TRACKED["athlete_profile"] and "weight_cycling_history" not in TRACKED["athlete_profile"]


def test_the_private_part_has_no_repo_twin():
    assert not (ROOT / "config" / "private").exists()
    assert U.PRIVATE_KEY.startswith("config/private/") and U.PRIVATE_KEY != U.PUBLIC_KEY
    sys.path.insert(0, str(ROOT / "deploy"))
    import config_twin_registry as CTR  # noqa: PLC0415

    keys = {t.key for t in CTR.derive(str(ROOT)).twins}
    assert U.PUBLIC_KEY in keys and U.PRIVATE_KEY not in keys


# ── the partition ────────────────────────────────────────────────────────────


def test_split_follows_the_classifier_and_merge_restores_the_document():
    pub, priv = U.split(SYNTHETIC)
    assert all(GFP.classify(p) == GFP.PUBLIC_SAFE for p in _leaves(pub))
    assert all(GFP.classify(p) == GFP.PRIVATE for p in _leaves(priv))
    assert priv["targets"]["biomarkers"] == {"ldl_target_mg_dl": 1, "note": "synthetic clinical note"}
    assert "a_field_nobody_reviewed" in priv, "an unreviewed field is private (fail closed)"
    assert U.merge(pub, priv) == SYNTHETIC
    assert sorted(U.private_paths_in(SYNTHETIC)) == sorted(
        [
            "mission",
            "targets.biomarkers.ldl_target_mg_dl",
            "targets.biomarkers.note",
            "targets.nutrition.calorie_approach",
            "failure_mode.pattern",
            "failure_mode.early_warning_signals",
            "known_constraints",
            "a_field_nobody_reviewed.x",
        ]
    )


def test_a_list_mixing_classes_refuses_to_split(monkeypatch):
    """A list of records cannot be partitioned without re-indexing it; a review that made one item field private
    must rule on the shape, so the split refuses rather than guessing."""
    monkeypatch.setattr(GFP, "_PRIVATE", GFP._PRIVATE + ("targets.weight.interim_milestones[*].label",))
    with pytest.raises(ValueError, match="mixes public-safe and private"):
        U.split({"targets": {"weight": {"interim_milestones": [{"lbs": 1, "label": "a"}]}}})


def test_merge_never_lets_the_private_part_restate_a_public_figure():
    assert U.merge({"timeline": {"start_weight_lbs": 200}}, {"timeline": {"start_weight_lbs": 1, "note2": "n"}}) == {
        "timeline": {"start_weight_lbs": 200, "note2": "n"}
    }


# ── the loader ───────────────────────────────────────────────────────────────


def test_the_local_private_part_is_read_from_the_off_repo_path(tmp_path, monkeypatch):
    f = tmp_path / "priv.json"
    f.write_text(json.dumps({"mission": "synthetic"}))
    monkeypatch.setenv(U.PRIVATE_PATH_ENV, str(f))
    s3 = FakeS3({})
    assert U.load_private(s3) == {"mission": "synthetic"} and s3.gets == [], "the local file wins; S3 is not touched"
    goals = U.load_goals()
    assert goals["mission"] == "synthetic" and goals["timeline"] == TRACKED["timeline"]


def test_a_missing_private_part_is_absent_and_never_reaches_s3_implicitly(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    def _boom(_client):
        raise AssertionError("a local run must not reach for the live private object")

    monkeypatch.setattr(U, "_s3", _boom)
    assert U.load_private() is None
    assert U.load_goals() == TRACKED, "no stand-in private field is invented"


def test_in_lambda_both_parts_come_from_s3(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "synthetic-fn")
    s3 = FakeS3({U.PUBLIC_KEY: {"timeline": {"start_date": "2030-01-01"}}, U.PRIVATE_KEY: {"mission": "synthetic"}})
    monkeypatch.setattr(U, "_s3", lambda _c: s3)
    assert U.load_goals(prefer_repo=False) == {"timeline": {"start_date": "2030-01-01"}, "mission": "synthetic"}
    assert s3.gets == [U.PUBLIC_KEY, U.PRIVATE_KEY]


def test_an_unreadable_private_object_degrades_to_the_public_plan(monkeypatch):
    s3 = FakeS3({U.PUBLIC_KEY: {"version": "p"}})
    assert U.load_goals(s3, prefer_repo=False) == {"version": "p"}
    assert U.load_goals(FakeS3({}), prefer_repo=False) is None, "no public part: the caller's own fail-soft takes over"
