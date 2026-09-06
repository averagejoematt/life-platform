"""tests/test_grounding_corpus_3614.py — the frozen adversarial grounding corpus (#3614 ROW1).

WHAT THIS IS
------------
`tests/grounding_corpus/*.json` holds ONE fixture per sentence the platform was caught
fabricating on a live surface, seeded with the 2026-09-05 `/review full` baseline's eight
(R4, NARR-3, AIQ-3/4/5/6/8). Each carries the sentence VERBATIM (or says plainly that it
is not), the gate class expected to fail it, a matched positive control that must PASS the
same gate with the same inputs, and FROZEN anchors (the plan block, the genesis, the
allow-list as they were on the day) — so the replay never depends on today's constants,
which is what "anchors move in-run" (the forensic RCA) makes necessary.

Every fixture is content-addressed: `corpus.sha256.json` is the seal and
`scripts/grounding_corpus_stamp.py` refuses to launder an edit or a delete. A specimen that
stops failing is fixed by fixing the GATE, or by flipping its `status` in the diff — never
by rewording the sentence (the #2959/#3003/#3199 phrase-match class, in reverse).

CANNOT-DISAGREE BEATS MUST-MENTION
----------------------------------
The assertion on a `caught` specimen is that the composite gate returns a finding of the
expected class; the assertion on its control is that the same gate returns NOTHING. An
`open` specimen is one the review captured that NO class yet catches — it is recorded with
the story that closes it, and the test pins that it is STILL uncaught: when the class
lands, the fixture must flip to `caught` in the same PR (the intake rule #3614 asks for),
and the caught count is a grow-only ratchet.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent
for _p in (str(_REPO / "lambdas"), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai import (
    grounded_generation as gg,  # noqa: E402
    plan_facts_gate,  # noqa: E402
)
from grounding_corpus_stamp import STAMP_NAME, fixture_paths, load_stamp, verify_corpus, write_stamp  # noqa: E402

CORPUS_DIR = _TESTS / "grounding_corpus"

# ── the ratchets (grow-only; bump in the SAME PR that adds a specimen) ────────
# Seeded 2026-09-05 (#3614): the review's eight — five caught (two by the #3614
# stale_reset_date class, one by the #3518 plan class, one by the #1242 date class, one by
# the ADR-104 number class), three open (#3516 x2, #3519's structured field).
MIN_SPECIMENS = 8
MIN_CAUGHT = 5

REQUIRED_KEYS = {
    "id",
    "issue",
    "review",
    "captured_at",
    "surface",
    "verbatim",
    "status",
    "gate",
    "expect_type",
    "specimen",
    "control",
    "inputs",
}
VALID_STATUS = {"caught", "open"}
VALID_GATE = {"composite", "plan", None}


def _fixtures() -> list[dict]:
    out = []
    for p in fixture_paths(CORPUS_DIR):
        f = json.loads(p.read_text(encoding="utf-8"))
        f["_file"] = p.name
        out.append(f)
    return out


FIXTURES = _fixtures()
CAUGHT = [f for f in FIXTURES if f["status"] == "caught"]
OPEN = [f for f in FIXTURES if f["status"] == "open"]


def replay(fixture: dict, text: str) -> list:
    """Run ONE fixture's gate over ``text`` with the fixture's FROZEN inputs."""
    inputs = fixture.get("inputs") or {}
    if fixture["gate"] == "plan":
        return plan_facts_gate.plan_figure_findings(text, inputs["plan_facts"], observed=inputs.get("observed"))
    if fixture["gate"] == "composite":
        kwargs = {}
        if "allowed" in inputs:
            kwargs["allowed"] = set(float(x) for x in inputs["allowed"])
        if "allowed_dates" in inputs:
            kwargs["allowed_dates"] = set(inputs["allowed_dates"])
        for k in ("generation_date_iso", "start_date_iso", "baseline_lbs"):
            if k in inputs:
                kwargs[k] = inputs[k]
        return gg.grounding_findings(text, facts=None, **kwargs)
    raise ValueError(f"{fixture['_file']}: gate {fixture['gate']!r} is not replayable")


# ── shape ─────────────────────────────────────────────────────────────────────
def test_corpus_is_non_vacuous_and_ratcheted():
    assert len(FIXTURES) >= MIN_SPECIMENS, f"the corpus shrank below its floor ({len(FIXTURES)} < {MIN_SPECIMENS}) — it is grow-only"
    assert len(CAUGHT) >= MIN_CAUGHT, f"caught specimens fell below the ratchet ({len(CAUGHT)} < {MIN_CAUGHT}) — a gate class went dark"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["_file"])
def test_every_fixture_carries_the_record(fixture):
    missing = REQUIRED_KEYS - set(fixture)
    assert not missing, f"{fixture['_file']}: missing {sorted(missing)}"
    assert fixture["_file"] == f"{fixture['id']}.json", "the file name is the id"
    assert fixture["status"] in VALID_STATUS and fixture["gate"] in VALID_GATE
    assert fixture["issue"].startswith("#") and fixture["review"], "every specimen names the story and the review that captured it"
    assert fixture["specimen"].strip() and fixture["control"].strip() and fixture["specimen"] != fixture["control"]
    if fixture["verbatim"] is False:
        assert fixture.get("verbatim_note"), "a non-verbatim specimen must say what was and was not captured"
    if fixture["status"] == "caught":
        assert fixture["gate"] is not None and fixture["expect_type"], "a caught specimen names the class that fails it"
    else:
        assert fixture.get("closes_with", "").startswith("#"), "an open specimen names the story that closes it"
        assert fixture.get("why_open"), "an open specimen says why no class catches it yet"


# ── the replay: caught specimens FAIL, their controls PASS ────────────────────
@pytest.mark.parametrize("fixture", CAUGHT, ids=lambda f: f["_file"])
def test_caught_specimen_fails_its_gate(fixture):
    findings = replay(fixture, fixture["specimen"])
    types = [f.get("type") for f in findings]
    assert (
        fixture["expect_type"] in types
    ), f"{fixture['_file']}: the gate no longer fails the specimen (got {types}) — fix the GATE, never the sentence"


@pytest.mark.parametrize("fixture", CAUGHT, ids=lambda f: f["_file"])
def test_matched_control_passes_the_same_gate(fixture):
    findings = replay(fixture, fixture["control"])
    assert findings == [], f"{fixture['_file']}: the positive control trips the gate — the class is over-firing: {findings}"


# ── open specimens are STILL open (flip them in the PR that closes the class) ─
@pytest.mark.parametrize("fixture", [f for f in OPEN if f["gate"]], ids=lambda f: f["_file"])
def test_open_specimen_is_still_uncaught(fixture):
    findings = replay(fixture, fixture["specimen"])
    assert findings == [], (
        f"{fixture['_file']}: a gate now catches this OPEN specimen ({[f.get('type') for f in findings]}) — flip its status to "
        f"'caught', set expect_type, re-seal (`stamp --amend`) and bump MIN_CAUGHT in the same PR ({fixture.get('closes_with')})"
    )


# ── the seal ──────────────────────────────────────────────────────────────────
def test_corpus_is_sealed_and_unedited():
    problems = verify_corpus(CORPUS_DIR)
    assert not problems, "the corpus seal is broken:\n  " + "\n  ".join(problems)
    stamp = load_stamp(CORPUS_DIR / STAMP_NAME)
    assert stamp["count"] == len(FIXTURES) and stamp["caught"] == len(CAUGHT)


def test_seal_refuses_a_laundered_edit_and_a_delete(tmp_path):
    """Positive control on the seal itself: an edited fixture and a deleted fixture are
    both refused by `stamp`, and both are named by `verify`."""
    corpus = tmp_path / "grounding_corpus"
    corpus.mkdir()
    for src in fixture_paths(CORPUS_DIR)[:2]:
        (corpus / src.name).write_bytes(src.read_bytes())
    write_stamp(corpus)
    assert verify_corpus(corpus) == []
    victim = fixture_paths(corpus)[0]
    victim.write_text(victim.read_text(encoding="utf-8").replace("\n", "\n", 1) + "\n", encoding="utf-8")  # a one-byte edit
    assert any("EDITED" in p for p in verify_corpus(corpus))
    with pytest.raises(SystemExit, match="laundering"):
        write_stamp(corpus)
    write_stamp(corpus, amend=(victim.stem,))  # the stated form is accepted
    assert verify_corpus(corpus) == []
    os.remove(victim)
    assert any("DELETED" in p for p in verify_corpus(corpus))
    with pytest.raises(SystemExit, match="grow-only"):
        write_stamp(corpus)


def test_a_specimen_that_stops_failing_is_visible():
    """Mutation proof for the replay: hand the #3518 specimen a plan whose range now
    includes 8,000 and the caught assertion must red — the corpus is only worth its
    seal if a weakened gate (or a widened plan) shows up here."""
    fx = next(f for f in CAUGHT if f["gate"] == "plan")
    widened = dict(fx["inputs"]["plan_facts"], daily_steps_range=[6000, 9000])
    assert plan_facts_gate.plan_figure_findings(fx["specimen"], widened) == []
    assert plan_facts_gate.plan_figure_findings(fx["specimen"], fx["inputs"]["plan_facts"])
