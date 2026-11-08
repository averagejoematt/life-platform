"""tests/test_call_publication_privacy.py — private coach calls never show on a public surface (owner ruling 2026-11-05).

"Private journal-derived predictions must not expose journal activity through IDs, wording, metadata, counts,
evaluation results or related endpoints ... Recalculate public denominators and accuracy using only
publication-eligible calls. Show the revised methodology and effective date. Make sure differences between public and
private totals cannot be used to infer private journal counts."

Every call and id here is SYNTHETIC (``tests/call_publication_route_walk.py``).

THE INFERENCE TEST. Three tables that differ ONLY in the owner's private calls — none, one set, three sets: private
calls of every class the policy decides, every row that names one (learnings, grade corrections, calibration voids),
private asks with the commitments tally PRODUCED by the real grader from the varied corpus, and a private bet with its
two sides — walked over every public GET route the way ``lambda_handler`` serves them (both wire halves, so the
``_meta.withheld`` counts and the two count-bearing headers are in the comparison), plus the static pages' objects
built by the real snapshot builder (``scripts/publish_snapshot.py``: the ledger's per-call pages, the Day pages'
chips, the coaches). Everything must be byte-identical across the three, and so must the whole set taken together.

NEGATIVE CONTROL. ``--ungated`` — the same walk with the call policy publishing every call (the code before the
ruling) — must move the governed routes and put the private ids and words on the wire.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from common import prediction_publication as PP  # noqa: E402

NOW = "2026-11-07T20:00:00+00:00"
VARIANTS = ("none", "some", "many")
PRIVATE_MARKS = ("SYNTHETIC-PRIVATE-CALL", "synthetic_private", "private-bet")


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "call_publication_route_walk.py"), "--now", NOW, *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    return {v: _walk("--variant", v) for v in VARIANTS}


@pytest.fixture(scope="module")
def ungated() -> dict:
    return {v: _walk("--variant", v, "--ungated") for v in ("none", "some")}


def _body(out: dict, key: str) -> dict:
    return json.loads(out["bodies"][key])["body"]


def _moved(runs: dict, field: str = "bodies") -> list:
    base = runs["none"][field]
    return sorted(k for k in base if any(r[field].get(k) != base[k] for r in runs.values()))


# ── the inference test ────────────────────────────────────────────────────────────────────


def test_the_walk_reaches_every_route(walks):
    for v, out in walks.items():
        assert out["routes"] >= 140 and out["answered"] >= out["routes"] - 3, (v, out["routes"], out["answered"])
        assert out["raised"] == {}, (v, out["raised"])
        assert out["unparsed_queries"] == 0, "a query the fake table could not read is a blind spot"


def test_no_public_route_or_header_moves_with_private_calls(walks):
    assert _moved(walks) == [], "public routes whose body changes with private calls alone"
    assert _moved(walks, "headers") == [], "a wire header (a count) that moves with private calls"


def test_the_static_pages_do_not_move_with_private_calls(walks):
    for v, out in walks.items():
        assert '"error"' not in out["pages"][:40], (v, out["pages"][:300])
    assert len({walks[v]["pages"] for v in VARIANTS}) == 1


def test_the_whole_public_surface_is_one_value_across_variants(walks):
    """The cross-endpoint check: every body, header and page, taken together."""

    def digest(out):
        return hashlib.sha256(json.dumps([out["bodies"], out["headers"], out["pages"]], sort_keys=True).encode()).hexdigest()

    assert len({digest(walks[v]) for v in VARIANTS}) == 1
    assert set(walks["none"]["bodies"]) == set(walks["some"]["bodies"]) == set(walks["many"]["bodies"])


def test_no_private_id_or_word_reaches_any_route_or_page(walks):
    for v, out in walks.items():
        for key, body in out["bodies"].items():
            hits = [t for t in PRIVATE_MARKS if t in body]
            assert not hits, (v, key, hits)
        assert not [t for t in PRIVATE_MARKS if t in out["pages"]], v


# ── the public totals agree with each other ────────────────────────────────────────────────


def test_every_public_total_is_the_same_count_of_eligible_calls(walks):
    out = walks["many"]
    preds = _body(out, "/api/predictions")
    ledger = _body(out, "/api/ledger_export")
    calib = _body(out, "/api/calibration")
    overall = preds["overall"]
    assert overall["total"] == ledger["total"] > 0
    assert overall["total"] == sum(c["total"] for c in preds["by_coach"].values())
    assert overall["decided"] == overall["confirmed"] + overall["refuted"]
    assert overall["accuracy_pct"] == round(overall["confirmed"] / overall["decided"] * 100, 1)
    for c in calib["coaches"]:
        assert c["record"] == preds["by_coach"][c["coach_id"]]["record"], c["coach_id"]
    calls = _body(out, "/api/calls")
    assert calls["count"] <= overall["decided"] + len(calls.get("calls") or [])


def test_the_walk_is_not_vacuous(walks):
    """The public record is served: legacy reviewed calls, a structured call filed after the registry, a public bet,
    the commitments tally the grader produced."""
    out = walks["none"]
    ids = {i["prediction_id"] for i in _body(out, "/api/ledger_export")["items"]}
    assert "pred_20261020_synthetic_public_sleep_0" in ids and "pred_20261106_synthetic_public_new_sleep" in ids
    # Owner ruling 2026-11-06: a word the graded source explains does not take a call off the public record.
    assert {"pred_20261106_synthetic_public_fatigue", "pred_20261106_synthetic_public_rpe"} <= ids
    assert any("public-bet" in json.dumps(r) for r in _body(out, "/api/coach_docket")["resolved"])
    assert _body(out, "/api/predictions")["commitments"] is not None


def test_the_method_is_served_beside_every_count(walks):
    out = walks["none"]
    for key in ("/api/predictions", "/api/calibration", "/api/ledger_export", "/api/calls"):
        method = _body(out, key)["method"]
        assert method["version"] == PP.METHOD_VERSION == 2 and method["effective"] == PP.EFFECTIVE == "2026-11-05", key
        assert [h["version"] for h in method["history"]] == [1, 2], key
        assert "journal" in method["note"] and "not counted" in method["note"], key


# ── negative control ──────────────────────────────────────────────────────────────────────


def test_negative_control_the_ungated_policy_leaks(ungated):
    """The same walk with every call published (the code before the ruling) must red: the governed routes move with
    the private calls, and their ids and words reach the wire and the pages."""
    moved = set(_moved(ungated))
    for key in (
        "/api/predictions",
        "/api/ledger_export",
        "/api/calibration",
        "/api/calls",
        "/api/coach_docket",
        "/api/coaches",
        "/api/edition",
        "/api/coach/mind_coach",
    ):
        assert key in moved, (key, sorted(moved))
    some = ungated["some"]
    assert any(t in body for body in some["bodies"].values() for t in PRIVATE_MARKS)
    assert any(t in some["pages"] for t in PRIVATE_MARKS)
    assert _body(some, "/api/predictions")["overall"]["total"] > _body(ungated["none"], "/api/predictions")["overall"]["total"]
