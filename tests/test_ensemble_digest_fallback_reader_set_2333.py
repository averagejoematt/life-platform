"""tests/test_ensemble_digest_fallback_reader_set_2333.py — #2333: the ensemble
digest's `_fallback` mark had no reader.

`coach_ensemble_digest` stamps `"_fallback": True` on a digest produced without
the LLM (budget-paused at tier >= 1, ADR-125 — the common case per #1927, not
the rare one, per the module's own comment at `coach_ensemble_digest.py:497`).
The issue named TWO readers (`site_api_coach_stance.py`, `coach_observatory_
renderer.py`) — deriving the set instead of hand-enumerating it finds **five**
modules in `lambdas/` that touch an `ENSEMBLE#digest / CYCLE#{date}` record:

  1. web/site_api_coach_stance.py       — DEFINER: issues the DDB read
                                           (`_latest_cycle_digest`), returns the
                                           record verbatim (the `_fallback` key
                                           survives naturally — this is the
                                           source of truth every other member
                                           reads through).
  2. web/site_api_coach.py              — DELEGATOR: the routed-facade
                                           re-export. A bare one-line passthrough
                                           of #1's return value — never
                                           reconstructs a payload of its own.
  3. web/site_api_coach_narrative.py    — PROPAGATOR: `handle_coach_analysis`
                                           (GET /api/coach_analysis) reads the
                                           digest via #1 and RECONSTRUCTS a new
                                           response dict — the exact shape that
                                           silently dropped `_fallback` before
                                           this PR. Fixed to carry
                                           `ensemble_fallback`.
  4. coach/coach_observatory_renderer.py — PROPAGATOR: `_render_coach_card`
                                           issues its OWN DDB read and also
                                           reconstructs a new response dict —
                                           same defect class as #3, same fix.
  5. coach/coach_narrative_orchestrator.py — PASSTHROUGH: `_gather_all_state`
                                           issues its own DDB read, but the
                                           record is serialized WHOLESALE
                                           (`json.dumps(state["ensemble_digest"],
                                           ...)`) straight into the ensemble
                                           LLM's own prompt — no field is ever
                                           selected out, so `_fallback` was
                                           never dropped here. Confirmed by a
                                           structural regression guard below,
                                           not "fixed" (there is nothing to fix).

Structure:
  AC-derive   `_derive_readers()` walks `lambdas/` with two mechanical rules (a
              literal `"ENSEMBLE#digest"` PK argument to a DDB-read call, OR a
              call site of the shared `_latest_cycle_digest()` accessor) and
              is asserted non-vacuous AND exactly equal to the five members
              above — so a sixth reader added later fails this test until it
              is classified into the registry, never silently.
  AC-nonvacuous  the derivation is proven live (not a disguised hardcoded list)
              by running it against a synthetic scratch tree that plants one
              matching file and one near-miss — only the matching one is found.
  AC-behavior    the two PROPAGATOR members are exercised end-to-end with a
              real `_fallback: True` digest and asserted to surface it
              (`ensemble_fallback is True`) on their served payload — this is
              the mutation proof: comment out either `ensemble_fallback =
              bool(digest.get("_fallback"))` assignment (or the corresponding
              dict-literal key) in `site_api_coach_narrative.py` or
              `coach_observatory_renderer.py` and one of these two tests reds
              (verified manually while writing this PR — see the PR body).
  AC-passthrough the PASSTHROUGH member is guarded structurally: the exact
              wholesale-serialization call site is pinned by source text, so a
              future change to a hand-picked subset (which WOULD silently drop
              `_fallback`) breaks this test rather than shipping quietly.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tests/ — reuse sibling test helpers

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

LAMBDAS_ROOT = Path(_REPO) / "lambdas"

# ══════════════════════════════════════════════════════════════════════════════
# DERIVATION — mechanical, not hand-typed
# ══════════════════════════════════════════════════════════════════════════════

_DIRECT_READ_PATTERNS = [
    re.compile(r'\.eq\(\s*"ENSEMBLE#digest"\s*\)', re.DOTALL),
    re.compile(r'_get_item\(\s*"ENSEMBLE#digest"', re.DOTALL),
    re.compile(r'_query_latest\(\s*"ENSEMBLE#digest"', re.DOTALL),
    re.compile(r'_query_begins_with\(\s*"ENSEMBLE#digest"', re.DOTALL),
]
_ACCESSOR_CALL = re.compile(r"_latest_cycle_digest\(")


def _derive_readers(root: Path) -> set:
    """Every `.py` file under `root` that either (a) issues a DDB read whose PK
    argument is the literal `"ENSEMBLE#digest"`, or (b) calls the shared
    `_latest_cycle_digest()` accessor (excluding its own `def` line). Returns
    paths relative to `root`, POSIX-style, sorted-set for stable comparison."""
    found = set()
    for path in root.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        hit = any(pat.search(src) for pat in _DIRECT_READ_PATTERNS)
        if not hit:
            for m in _ACCESSOR_CALL.finditer(src):
                line_start = src.rfind("\n", 0, m.start()) + 1
                line_end = src.find("\n", m.start())
                line = src[line_start : line_end if line_end != -1 else None]
                if line.strip().startswith("def "):
                    continue
                hit = True
                break
        if hit:
            found.add(path.relative_to(root).as_posix())
    return found


EXPECTED_READERS = {
    "web/site_api_coach_stance.py",
    "web/site_api_coach.py",
    "web/site_api_coach_narrative.py",
    "coach/coach_observatory_renderer.py",
    "coach/coach_narrative_orchestrator.py",
}


def test_derivation_is_non_vacuous_and_finds_exactly_the_known_readers():
    derived = _derive_readers(LAMBDAS_ROOT)
    assert derived, "derivation found NO readers — the regex has drifted from the real call idioms"
    assert derived == EXPECTED_READERS, (
        f"the derived ENSEMBLE#digest reader set changed — classify the new/missing member(s) "
        f"in this file's registry before updating the expectation. missing={EXPECTED_READERS - derived} "
        f"new={derived - EXPECTED_READERS}"
    )


def test_derivation_is_a_live_regex_not_a_disguised_hardcoded_list():
    """AC1b-style non-vacuity proof (the class of bug this repo has shipped
    before: a 'derived' set that is secretly just the hardcoded expectation in
    different clothing). A synthetic scratch tree plants one file that matches
    a direct-read pattern and one near-miss (same PK string, but as a plain
    dict value — not a read call) that must NOT match."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "real_reader.py").write_text(
            'item = table.get_item(Key={"pk": pk}).get("Item")\n_get_item("ENSEMBLE#digest", "CYCLE#2026-08-08")\n'
        )
        (root / "not_a_reader.py").write_text('note = "the pk is ENSEMBLE#digest for reference"\n')
        derived = _derive_readers(root)
        assert derived == {"real_reader.py"}, derived


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURAL CHECKS — DELEGATOR + PASSTHROUGH members
# ══════════════════════════════════════════════════════════════════════════════


def test_delegator_facade_is_a_bare_passthrough():
    """web/site_api_coach.py's `_latest_cycle_digest` must stay a one-line
    re-export of the stance module's function — the moment it starts building
    its own dict, it joins the PROPAGATOR class and needs its own fix +
    membership here, not silent trust.

    Plain string slicing (not a backtracking regex over the whole file) — the
    function body runs from its `def` line to the next top-level `def `."""
    src = (LAMBDAS_ROOT / "web" / "site_api_coach.py").read_text(encoding="utf-8")
    marker = "def _latest_cycle_digest():"
    start = src.index(marker)
    rest = src[start + len(marker) :]
    next_def = rest.find("\ndef ")
    body = rest if next_def == -1 else rest[:next_def]
    body_lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith('"""') and '"""' not in ln]
    # Exactly one statement: `return _stance._latest_cycle_digest(_g=globals())`
    assert body_lines == ["return _stance._latest_cycle_digest(_g=globals())"], body_lines


def test_orchestrator_serializes_the_digest_wholesale_not_a_reconstructed_subset():
    """coach_narrative_orchestrator.py dumps `state["ensemble_digest"]` verbatim
    into the ensemble LLM's prompt (`json.dumps(state["ensemble_digest"], ...)`)
    — every key, including `_fallback`, reaches the model unfiltered. If this
    ever changes to a hand-picked subset (`json.dumps({"coach_summaries": ...})`
    style), `_fallback` could silently stop reaching the LLM the same way it
    silently stopped reaching the two HTTP readers — this pins the wholesale
    call site so that regression breaks loudly instead."""
    src = (LAMBDAS_ROOT / "coach" / "coach_narrative_orchestrator.py").read_text(encoding="utf-8")
    assert 'json.dumps(state["ensemble_digest"]' in src, (
        "coach_narrative_orchestrator no longer serializes the whole ensemble_digest record — "
        "verify _fallback still reaches the LLM prompt, then update this pin"
    )


# ══════════════════════════════════════════════════════════════════════════════
# BEHAVIORAL PROOF — the two PROPAGATOR members, mutation-provable
# ══════════════════════════════════════════════════════════════════════════════

import coach_observatory_renderer as cobs  # noqa: E402  (tests/ dir on sys.path — see test_coach_observatory_renderer.py)
from ai import budget_guard  # noqa: E402
from web import site_api_coach as coach_api  # noqa: E402

_FALLBACK_DIGEST = {
    "pk": "ENSEMBLE#digest",
    "sk": "CYCLE#2026-08-08",
    "_fallback": True,
    "active_disagreements": [],
    "coach_summaries": [],
}


def test_coach_analysis_propagator_surfaces_the_fallback_mark(monkeypatch):
    """GET /api/coach_analysis — the exact route the issue named."""
    out_item = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-08-08",
        "content": "the analysis text",
        "generated_at": "2026-08-08T14:00:00Z",
    }

    def _pk_of(condition):
        expr = condition.get_expression()
        if expr["operator"] == "AND":
            for v in expr["values"]:
                found = _pk_of(v)
                if found is not None:
                    return found
            return None
        key = expr["values"][0]
        return expr["values"][1] if getattr(key, "name", None) == "pk" else None

    def _query(**kwargs):
        pk = _pk_of(kwargs["KeyConditionExpression"])
        routes = {"COACH#sleep_coach": [out_item], "ENSEMBLE#digest": [_FALLBACK_DIGEST]}
        return {"Items": routes.get(pk, [])}

    monkeypatch.setattr(coach_api.table, "query", _query)
    monkeypatch.setattr(coach_api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

    import json as _json

    resp = coach_api.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}})
    assert resp["statusCode"] == 200
    data = _json.loads(resp["body"])
    assert data["ensemble_fallback"] is True, "the propagator dropped the fallback mark — the #2333 defect is back"


def test_observatory_propagator_surfaces_the_fallback_mark(monkeypatch):
    """The observatory card renderer — the second route the issue named."""
    from test_coach_observatory_renderer import FakeTable, FrozenDatetime, _output  # noqa: E402

    rows = [_output(content="analysis"), dict(_FALLBACK_DIGEST)]
    table = FakeTable(rows=rows)
    monkeypatch.setattr(cobs, "table", table)
    monkeypatch.setattr(cobs, "datetime", FrozenDatetime)

    card = cobs._render_coach_card("sleep")
    assert card["ensemble_fallback"] is True, "the propagator dropped the fallback mark — the #2333 defect is back"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
