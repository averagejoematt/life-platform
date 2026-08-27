"""tests/test_gate_census_enforcement_3220.py — #3220: a filename is not a gate.

THE INCIDENT (2026-08-26, while landing #3202). A new module
`lambdas/ai/coach_gate_retention.py` — the extracted body of
`_retain_coach_brief_flag`, which persists a fired quality-gate verdict as eval
data — pushed the census 560 -> 561 and red `tests/test_gate_census_lane_3000.py`,
whose assertion instructs the author to bump `BASELINE_TOTAL_GATES`.

It is not a gate. It enforces nothing, blocks nothing, and is deliberately
fail-soft (`except Exception: pass`, documented "retention is never
load-bearing"). It matched `_GUARD_NAME`'s `.*_gate[a-z0-9_]*\\.py$` alternative on
the substring "gate" in its filename, then landed in the `no_nonzero_exit` bucket
whose own detail line already anticipated it: "no nonzero-exit path found — it may
be a library, or it may be unable to fail." The census could see the condition and
had no way to act on it.

That instance was resolved by RENAMING the module. Right fix for that PR, wrong fix
for the class — renaming makes the symptom go away while the matcher stays wrong,
and the next `*_gate*.py` library hits it again. Hence these tests.

WHY THE FIXTURES ARE SYNTHETIC. Every classification test below builds its own
tiny tree, so none of them drift when the real repo changes. The one test that
does touch the real tree asserts a PROPERTY (a well-known guard script is still
counted), not a number — numbers live in test_gate_census_lane_3000.py's ratchet,
which is the one place they belong.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate_census = pytest.importorskip("gate_census", reason="the census's CI-family walk needs PyYAML")
import gate_census_enforcement as gce  # noqa: E402

# The measured false positive, reproduced. This is the shape of the real
# `coach_gate_retention.py`: a fail-soft persistence helper, documented as never
# load-bearing, with "gate" in its filename and nothing that can fail.
FAIL_SOFT_LIBRARY = '''
"""Persist a fired quality-gate verdict as eval data. Retention is never
load-bearing — a write failure must not affect the brief."""


def _retain_coach_brief_flag(table, coach_id, verdict):
    try:
        table.put_item(Item={"pk": coach_id, "verdict": verdict})
    except Exception:
        pass
'''

GENUINE_GUARD = """
import sys


def main():
    if broken():
        print("FAIL")
        sys.exit(1)
    return 0
"""

RAISING_GUARD = """
def enforce(payload):
    if payload is None:
        raise ValueError("refusing an empty payload")
    return payload
"""

ASSERTING_GUARD = """
def sweep(tree):
    offenders = find(tree)
    assert not offenders, offenders
"""

BOOL_VERDICT_GUARD = """
def allow(feature: str) -> bool:
    return feature not in _paused()
"""

DECLARED_ENTRYPOINT = '''
# gate-entrypoint: the caller (ai_calls._enforce_quality_gate) blocks on this verdict.
"""Computes a verdict; the blocking lives at the call site."""


def report(text):
    return {"findings": scan(text)}
'''

# A raise that CANNOT escape — the fail-soft shape wearing a raise. This is the
# adversarial case: a naive `"raise" in text` check calls this a gate.
SWALLOWED_RAISE = """
def retain(x):
    try:
        raise ValueError("never seen by a caller")
    except Exception:
        pass
"""


def _tree(tmp_path: pathlib.Path, files: dict[str, str]) -> tuple[pathlib.Path, list[pathlib.Path]]:
    for rel, body in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return tmp_path, sorted(tmp_path.rglob("*.py"))


def _discover(tmp_path, files):
    root, paths = _tree(tmp_path, files)
    gates, counters = gate_census.discover_guard_scripts(root, paths)
    return {g.name for g in gates}, counters, list(gate_census.NAME_ONLY_CANDIDATES)


# ── The evidence kinds, one at a time (pure, no repo) ─────────────────────────


def test_fail_soft_library_has_no_enforcement_evidence():
    assert gce.enforcement_evidence(FAIL_SOFT_LIBRARY) == []


@pytest.mark.parametrize(
    "src,kind",
    [
        (GENUINE_GUARD, gce.EVIDENCE_NONZERO_EXIT),
        (RAISING_GUARD, gce.EVIDENCE_ESCAPING_RAISE),
        (ASSERTING_GUARD, gce.EVIDENCE_ASSERT),
        (BOOL_VERDICT_GUARD, gce.EVIDENCE_BOOL_VERDICT),
        (DECLARED_ENTRYPOINT, gce.EVIDENCE_DECLARED),
    ],
)
def test_each_evidence_kind_is_detected(src, kind):
    assert kind in gce.enforcement_evidence(src)


def test_a_raise_that_cannot_escape_is_not_evidence():
    """The adversarial case. `try: raise ... except Exception: pass` is the
    fail-soft library shape wearing a raise, and a substring check on "raise"
    would readmit exactly the false positive #3220 exists to remove."""
    assert gce.enforcement_evidence(SWALLOWED_RAISE) == []


def test_a_raise_inside_the_HANDLER_still_escapes():
    """The other direction — re-raising out of a broad handler IS enforcement, and
    treating the whole `try` as swallowing would drop a real guard."""
    src = "def f(x):\n    try:\n        g(x)\n    except Exception:\n        raise RuntimeError('nope')\n"
    assert gce.EVIDENCE_ESCAPING_RAISE in gce.enforcement_evidence(src)


def test_a_narrow_except_does_not_swallow():
    """`except ValueError` catches one class; a raise in the guarded body may still
    escape. Assuming otherwise would drop real gates — the posture is always to
    fail toward inclusion."""
    src = "def f(x):\n    try:\n        raise TypeError('boom')\n    except ValueError:\n        pass\n"
    assert gce.EVIDENCE_ESCAPING_RAISE in gce.enforcement_evidence(src)


def test_an_unparseable_file_stays_in_the_inventory():
    """Over-counting one library is a rounding error; silently dropping a real gate
    is the failure class this whole census is named after."""
    ev = gce.enforcement_evidence("def broken(:\n")
    assert ev == [gce.EVIDENCE_UNPARSEABLE]
    assert gce.classify_candidate("x_gate.py", "def broken(:\n")["enforces"] is True


# ── The census-level claim: the total, in both directions ────────────────────


def test_a_fail_soft_library_named_gate_does_not_enter_the_total(tmp_path):
    """PRE-FIX THIS FAILED: `discover_guard_scripts` returned this file as a Gate
    on the strength of the substring "gate" in its name, and it counted toward
    `BASELINE_TOTAL_GATES` and #2578's unproven column."""
    names, counters, name_only = _discover(tmp_path, {"lambdas/ai/coach_gate_retention.py": FAIL_SOFT_LIBRARY})
    assert names == set(), f"a fail-soft library entered the inventory: {names}"
    assert counters["name_only"] == 1
    assert [c["path"] for c in name_only] == ["lambdas/ai/coach_gate_retention.py"]


def test_a_genuine_guard_script_still_does(tmp_path):
    """The other half. A rule that excluded libraries by also excluding real guards
    would trade one census lie for a worse one."""
    names, counters, _ = _discover(tmp_path, {"scripts/check_thing.py": GENUINE_GUARD})
    assert "scripts/check_thing.py" in names
    assert counters["name_only"] == 0


def test_both_in_one_sweep_so_the_rule_is_discriminating_not_blanket(tmp_path):
    names, counters, name_only = _discover(
        tmp_path,
        {
            "scripts/check_thing.py": GENUINE_GUARD,
            "lambdas/ai/coach_gate_retention.py": FAIL_SOFT_LIBRARY,
            "lambdas/ai/budget_guard.py": BOOL_VERDICT_GUARD,
            "tests/pair_seam_guard_lib.py": ASSERTING_GUARD,
        },
    )
    assert names == {"scripts/check_thing.py", "lambdas/ai/budget_guard.py", "tests/pair_seam_guard_lib.py"}
    assert [c["path"] for c in name_only] == ["lambdas/ai/coach_gate_retention.py"]
    assert counters["candidates"] == 4 and counters["name_only"] == 1


def test_a_guard_that_LOSES_its_enforcement_path_is_reported_not_silently_dropped(tmp_path):
    """The acceptance's fourth clause, and the one that matters most for the epic.

    Someone deletes the `sys.exit(1)` and the gate goes dark. The census must not
    quietly shrink by one — that is the same silhouette as the six dark gates it
    exists to find, so making it invisible would be the census committing its own
    subject.
    """
    armed = {"scripts/check_thing.py": GENUINE_GUARD}
    names_before, _, _ = _discover(tmp_path, armed)
    assert "scripts/check_thing.py" in names_before

    disarmed = GENUINE_GUARD.replace("sys.exit(1)", "pass")
    names_after, counters, name_only = _discover(tmp_path, {"scripts/check_thing.py": disarmed})

    assert "scripts/check_thing.py" not in names_after, "it must leave the ratcheted total"
    paths = [c["path"] for c in name_only]
    assert "scripts/check_thing.py" in paths, "…but it must be REPORTED, by path, not vanish"
    entry = name_only[paths.index("scripts/check_thing.py")]
    assert entry["state"] == gce.NAME_ONLY_STATE
    assert entry["verdict"] == gce.VERDICT_UNPROVABLE


def test_a_declared_entrypoint_marker_readmits_a_computation_module(tmp_path):
    """The reviewable escape hatch: a real gate whose caller does the blocking says
    so in its own first 40 lines. Not inferrable — a marker someone had to type is
    evidence; a pattern that guesses at intent is not."""
    names, _, name_only = _discover(tmp_path, {"lambdas/coach/coach_quality_gate.py": DECLARED_ENTRYPOINT})
    assert "lambdas/coach/coach_quality_gate.py" in names
    assert name_only == []


# ── unproven vs unprovable must be explicit in the OUTPUT ────────────────────


def test_report_states_unproven_and_unprovable_as_different_things():
    """#2578's denominator has to mean what it claims: "proof not written yet" is
    real work; "nothing to fail" is not work at all."""
    census = {
        "gates": [
            {
                "id": "g::1",
                "family": "guard-script",
                "name": "a",
                "source": "a",
                "screened": True,
                "risk_flags": [],
                "verdict": "unproven",
                "detail": {},
            }
        ],
        "name_only_candidates": [
            {"path": "lambdas/ai/coach_gate_retention.py", "state": gce.NAME_ONLY_STATE, "verdict": gce.VERDICT_UNPROVABLE, "evidence": []}
        ],
        "shapes": {},
        "counters": {},
        "families_dropped": [],
        "attempted_unproven": {},
        "annassign_exposure": {},
        "orphan_proofs": [],
        "unattached_attempts": [],
    }
    report = gate_census.render_report(census)
    assert "UNPROVEN (can fail, proof not written)" in report
    assert "UNPROVABLE (nothing to fail, excluded)" in report
    assert "NAME-MATCHED, NO ENFORCEMENT PATH" in report
    assert "lambdas/ai/coach_gate_retention.py" in report, "an excluded candidate must still be named, by path"
    assert "gate-entrypoint:" in report, "the report must say how to re-admit a real gate"


def test_report_does_not_tell_the_reader_to_bump_the_ceiling_for_a_name_only_match():
    """The second kind of damage in the issue: bumping `BASELINE_TOTAL_GATES` to
    absorb a misfire trains the next author to bump on noise and quietly corrupts
    the ratchet."""
    census = {
        "gates": [],
        "name_only_candidates": [{"path": "x_gate.py", "state": gce.NAME_ONLY_STATE, "verdict": gce.VERDICT_UNPROVABLE, "evidence": []}],
        "shapes": {},
        "counters": {},
        "families_dropped": [],
        "attempted_unproven": {},
        "annassign_exposure": {},
        "orphan_proofs": [],
        "unattached_attempts": [],
    }
    report = gate_census.render_report(census)
    assert "Do NOT bump the census" in report


# ── One property assertion against the REAL tree (never a number) ────────────


def test_real_repo_still_counts_a_well_known_exiting_guard_script():
    """A guard the repo genuinely runs in CI must survive the new rule. The COUNT
    lives in test_gate_census_lane_3000.py's ratchet; this asserts the property, so
    it cannot drift into a second, competing baseline."""
    root = pathlib.Path(_REPO)
    text = (root / "scripts" / "check_main_green.py").read_text(encoding="utf-8")
    assert gce.classify_candidate("scripts/check_main_green.py", text)["enforces"] is True
