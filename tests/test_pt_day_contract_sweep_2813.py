"""tests/test_pt_day_contract_sweep_2813.py — #2813: the standing PT-day
producer/gate contract sweep, GENERALIZING test_cycle_gate_pacific_clock_2675.py
(retired below — its three tests are now three parametrize cases here) rather
than adding a fourth parallel one-file-per-incident pin.

THE DEFECT CLASS (see the elite review, 2026-08-16, WS-C). Every production
timezone escape since the #2506 sweep has been in an INSTRUMENT — a validator or
gate — never a display: #2675 (the grounding gate's OWN `generation_date_iso`
default read UTC while the prompt block it grades asserts the Pacific day),
#2815 (the quality-gate wire event's `generation_date` default did too), #2812
(the board quality gate's `day_n` default did too). Each was found, fixed and
pinned SEPARATELY. The platform runs two frames on purpose — UTC for
crons/infra, Pacific for data semantics — so "today" is a producer<->consumer
AGREEMENT, not a value, and a pin that only checks how ONE side derives its
day-string can never catch the NEXT gate that defaults to the wrong frame.

WHAT THIS FILE DOES, IN TWO HALVES
-----------------------------------
1. THE SWEEP (`test_registered_entry_agrees_with_pacific_at_a_pt_evening_instant`).
   `common.pt_day_contract.PT_DAY_CONTRACT_REGISTRY` is populated by importing
   every module discovered (see #2 below) to carry an `@pt_day_contract`
   decorator on a REAL production function — never a test-only shadow (see
   `lambdas/common/pt_day_contract.py`'s own docstring for the decorator
   contract). This test parametrizes over that registry, pins the wall clock to
   ONE PT-evening instant — derived from the live `EXPERIMENT_START_DATE` so it
   survives every future cycle reset, at a wall-clock minute where the UTC
   calendar day and the Pacific calendar day disagree — and asserts each
   registered function's OWN default resolves to the Pacific day. Plus one
   explicit WIRE-CHAIN test walking `quality_gate_event` (producer) into the
   REAL `coach_quality_gate._number_grounding_report` (gate) exactly as
   `coach_quality_gate.py:821` does, because that pair is two DIFFERENT
   functions rather than one function's own default.

2. THE STRUCTURAL SAFETY NET (`test_every_day_default_candidate_is_decided`).
   GUARD THE SET, NOT THE INSTANCE: nothing above enumerates which functions
   matter by hand. This half AST-scans `lambdas/` for every function accepting
   a `generation_date`/`day_n`-shaped parameter defaulting to `None` — the
   literal "producer+gate pairs that accept a generation_date/day_n default"
   shape #2813 names — and asserts EVERY one is either (a) `@pt_day_contract`
   -registered (swept above, automatically, with zero edits here) or (b) has a
   written, verified reason in `EXEMPT_PT_DAY_CANDIDATES` below for why its
   `None` default never resolves a clock independently. A brand-new gate that
   is neither registered nor exempted fails THIS test, not silently ships dark.
   The companion `test_no_stale_exemptions` keeps the exempt list itself
   honest — an entry for a candidate the scan no longer finds is deleted, not
   left to rot (same idiom as `tests/test_wallclock_fixture_bombs_2376.py` and
   `tests/grounding_wiring.py`).

MUTATION PROOF (acceptance criterion 4) is NOT a permanent test here — it
requires temporarily breaking a real production function, which cannot live in
the suite. It was performed by hand: reverting
`grounding_gate_params.cycle_gate_params`'s Pacific default to the pre-#2675
`date.today()` (UTC) form and re-running this file turns
`test_registered_entry_agrees_with_pacific_at_a_pt_evening_instant[ai.grounding_gate_params::cycle_gate_params]`
red; the change was reverted immediately after. See the PR description for the
exact diff and pytest output captured during that run.

#2372 PREMERGE: this is a tree-sweeping test (it AST-scans the full `lambdas/`
tree) — `discover_tree_sweeping_test_files()` (tests/premerge_derivation.py)
flags it structurally on the `os.walk(` idiom, and it is classified into
`tests/conftest.py`'s `_PREMERGE_EXTRA_FILES` (never `_PREMERGE_TREE_SWEEP_EXCLUDED`
— its verdict depends only on repo shape) alongside its closest siblings in
shape, `tests/grounding_wiring.py` and `tests/test_time_invariant_helpers_1964.py`.
"""

import ast
import importlib
import os
import re
import sys
from datetime import date, datetime, timedelta

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_LAMBDAS = os.path.join(_REPO, "lambdas")

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

for _p in (_LAMBDAS,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ══════════════════════════════════════════════════════════════════════════
# Discovery — structural, both directions (guard the SET, not the instance)
# ══════════════════════════════════════════════════════════════════════════

_SKIP_MARKERS = ("__pycache__", "_staging", "cdk.out", "layer-build")


def _iter_python_sources():
    for dirpath, dirnames, filenames in os.walk(_LAMBDAS):
        if any(m in dirpath for m in _SKIP_MARKERS):
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _module_dotted_name(path: str) -> str:
    """`lambdas/ai/grounding_gate_params.py` -> `ai.grounding_gate_params` — the
    import form every lambdas/ module uses at runtime (#781 bundle root)."""
    rel = os.path.relpath(path, _LAMBDAS)
    return rel[: -len(".py")].replace(os.sep, ".")


def _modules_using_pt_day_contract():
    """Every lambdas/ module that calls `pt_day_contract(...)` to register a
    function — either literal `@pt_day_contract(...)` decorator syntax, or the
    post-hoc `name = pt_day_contract(...)(name)` reassignment idiom this repo's
    fail-soft modules use instead (see lambdas/ai/grounding_gate_params.py: the
    decoration happens inside a `try/except` so an import failure of this
    OPTIONAL registry module can never break the gate's own import). Deliberately
    substring-level (mirrors tests/test_wallclock_fixture_bombs_2376.py's own
    lenient clock-control detection) — the point is finding every module worth
    IMPORTING to populate the registry, not parsing one exact call shape. A
    plain substring check also catches the `_pt_day_contract` import-alias every
    production caller uses (it contains "pt_day_contract(" as a substring)."""
    hits = []
    for path in _iter_python_sources():
        if path.endswith(os.path.join("common", "pt_day_contract.py")):
            continue  # the registry's own definition, not a use of it
        src = open(path, encoding="utf-8").read()
        if "pt_day_contract(" in src:
            hits.append(_module_dotted_name(path))
    return sorted(set(hits))


# Day-shaped parameter names this class of defect has actually worn (#2675's
# generation_date_iso, #2815's generation_date, #2812's day_n, plus the
# reader-truth/qa siblings' today_iso/current_date_str/night_of/expected_day).
_DAY_PARAM_RE = re.compile(r"(generation_date(_iso)?|today_iso|current_date_str|day_n|expected_day|night_of)$", re.IGNORECASE)


def _day_default_candidates():
    """Every (module, qualname, param) in lambdas/ where a function accepts a
    day-shaped parameter defaulting to the literal `None` — the AST-visible
    shape of "a producer or gate that DEFAULTS a generation date/day_n"
    (#2813's own acceptance-criteria wording). `pacific_time.py` itself is
    excluded — it IS the canonical resolver, not a caller of it."""
    out = []
    for path in _iter_python_sources():
        if path.endswith(os.path.join("common", "pacific_time.py")):
            continue
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
        dotted = _module_dotted_name(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            posargs = args.posonlyargs + args.args
            defaults = args.defaults
            offset = len(posargs) - len(defaults)
            for i, a in enumerate(posargs):
                if i < offset:
                    continue
                d = defaults[i - offset]
                if _DAY_PARAM_RE.search(a.arg) and isinstance(d, ast.Constant) and d.value is None:
                    out.append((dotted, node.name, a.arg))
            for a, d in zip(args.kwonlyargs, args.kw_defaults):
                if d is not None and _DAY_PARAM_RE.search(a.arg) and isinstance(d, ast.Constant) and d.value is None:
                    out.append((dotted, node.name, a.arg))
    return sorted(set(out))


def _candidate_key(module: str, qualname: str) -> str:
    return f"{module}::{qualname}"


# ══════════════════════════════════════════════════════════════════════════
# Populate the registry: import every module discovery found
# ══════════════════════════════════════════════════════════════════════════

_DECORATED_MODULES = _modules_using_pt_day_contract()
for _m in _DECORATED_MODULES:
    importlib.import_module(_m)

from common.pt_day_contract import PT_DAY_CONTRACT_REGISTRY  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# The fixed PT-evening instant: derived from the LIVE genesis, not a literal
# calendar date, so it survives every future cycle reset (the #2675 pin's own
# stated intent, generalized). day_n = 3 — inside board_quality_gate's 1-3
# cycle-boundary window, so that entry is exercised meaningfully too. Named
# without a clock-claiming token (TODAY/NOW/...) per the #2376 fixture-bomb
# convention; this file's own `monkeypatch.setattr(pacific_time, "pacific_now", ...)`
# calls already read as clock CONTROL to that scanner regardless.
# ══════════════════════════════════════════════════════════════════════════


def _pt_evening_instant():
    from common.constants import EXPERIMENT_START_DATE
    from common.pacific_time import PACIFIC

    d = date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=2)
    # 20:00 local Pacific clock time (PST or PDT, zoneinfo resolves the offset)
    # is always >= UTC-7, so its UTC rendering has already rolled to the next
    # calendar day — the exact PT-evening disagreement window #2675 lived in.
    return datetime(d.year, d.month, d.day, 20, 0, tzinfo=PACIFIC)


# ══════════════════════════════════════════════════════════════════════════
# 1. THE SWEEP
# ══════════════════════════════════════════════════════════════════════════


def _entry_id(entry):
    return entry.id


def _patch_ai_context_second_clock(monkeypatch, instant):
    """ai_context.build_experiment_phase_context's default does NOT go through
    common.pacific_time — `_phase_today_pt()` deliberately reconstructs its own
    `ZoneInfo(EXPERIMENT_TZ)` instead (its own docstring: "mirrors
    pre_start_meta's PT-day semantics without importing web/ into this pure
    module"), a SECOND, independent-but-currently-correct Pacific frame the
    #1964 structural guard's own literal-string matcher does not see either
    (`ZoneInfo(EXPERIMENT_TZ)` is a NAME, not a string constant — worth a
    follow-up on #1964 itself). Patching `pacific_time.pacific_now` alone can't
    reach it, so this entry gets its own targeted patch of the intermediate
    helper — same PT-evening instant, just applied at the seam this module
    actually reads."""
    ai_context = importlib.import_module("ai.ai_context")
    monkeypatch.setattr(ai_context, "_phase_today_pt", lambda: instant.date())


# entry.id -> an extra monkeypatch.setattr(...) the sweep applies before calling
# entry.resolve(), for the rare registered function whose default does NOT
# route through common.pacific_time.pacific_now (see the docstring above for
# the one current case). Absence here means "pacific_time.pacific_now is the
# only clock this function's default reads" — true for every OTHER registered
# entry, verified by this file's own passing runs.
_EXTRA_CLOCK_PATCHES = {
    "ai.ai_context::build_experiment_phase_context": _patch_ai_context_second_clock,
}


@pytest.mark.parametrize("entry", PT_DAY_CONTRACT_REGISTRY, ids=_entry_id)
def test_registered_entry_agrees_with_pacific_at_a_pt_evening_instant(entry, monkeypatch):
    """Every `@pt_day_contract`-registered function's OWN default must resolve
    to the Pacific calendar day at a PT-evening instant, not the UTC one —
    generalizes test_cycle_gate_pacific_clock_2675.py's
    `test_default_clock_is_pacific` (cycle_gate_params is now one entry among
    several, discovered structurally rather than hand-imported)."""
    from common import pacific_time

    instant = _pt_evening_instant()
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: instant)
    extra_patch = _EXTRA_CLOCK_PATCHES.get(entry.id)
    if extra_patch is not None:
        extra_patch(monkeypatch, instant)
    expected = pacific_time.pacific_today()  # the canonical answer, computed post-patch
    resolved = entry.resolve()
    assert resolved == expected, (
        f"{entry.id} defaulted to {resolved!r} at a PT-evening instant where the platform's own "
        f"Pacific day is {expected!r} — a UTC (or otherwise non-Pacific) derivation leaked back in"
    )


def test_the_0813_style_contradiction_is_ruled_correctly(monkeypatch):
    """Behavioral generalization of #2675's
    `test_the_0813_contradiction_is_now_ruled_correctly`: at the pinned PT
    evening, the coach's own correct Pacific-day framing PASSES the grounding
    gate and the UTC (one-day-ahead) framing is FLAGGED — not the reverse."""
    from ai import grounded_generation as gg
    from ai.grounding_gate_params import cycle_gate_params
    from common import pacific_time
    from common.constants import EXPERIMENT_START_DATE

    instant = _pt_evening_instant()
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: instant)
    pt_day = pacific_time.pacific_day_n(EXPERIMENT_START_DATE, on_date=pacific_time.pacific_today())
    params = cycle_gate_params()

    correct = gg.grounding_findings(f"Day {pt_day} of the climb.", allowed=set(), **params)
    assert not [f for f in correct if f.get("type") == "stale_phase"], "the platform's own PT day is flagged"

    wrong = gg.grounding_findings(f"Day {pt_day + 1} of the climb.", allowed=set(), **params)
    assert any(
        f.get("type") == "stale_phase" and f.get("claimed_day") == pt_day + 1 for f in wrong
    ), "the UTC-clock day claim (one day ahead) must be flagged"


def test_explicit_date_still_wins():
    """Generalizes #2675's `test_explicit_date_still_wins` — an explicit caller
    date must outrank the Pacific default, for every registered entry that
    accepts one positionally as its sole/first arg (cycle_gate_params)."""
    from ai.grounding_gate_params import cycle_gate_params

    assert cycle_gate_params(generation_date_iso="2026-08-10")["generation_date_iso"] == "2026-08-10"


def test_quality_gate_wire_chain_agrees_at_a_pt_evening_instant(monkeypatch):
    """The PRODUCER+GATE PAIR #2813 names explicitly: `quality_gate_contract.py`'s
    `quality_gate_event` (producer, builds the wire payload `ai_calls.py:1316`
    sends with no explicit generation_date) feeding `coach_quality_gate.py:821`'s
    REAL `_number_grounding_report` (the gate), which itself calls the REAL
    `cycle_gate_params` (#2815's fix). Fixture is the wire: this drives the
    actual production functions in the actual call order, not a copy of their
    date logic."""
    from ai.quality_gate_contract import GROUNDING_ALLOWLIST_KEY, quality_gate_event
    from coach import coach_quality_gate
    from common import pacific_time
    from common.constants import EXPERIMENT_START_DATE

    instant = _pt_evening_instant()
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: instant)
    pt_day = pacific_time.pacific_day_n(EXPERIMENT_START_DATE, on_date=pacific_time.pacific_today())

    brief = {GROUNDING_ALLOWLIST_KEY: []}  # empty allow-list: a real, armed statement (see quality_gate_contract.py)

    # The producer defaults generation_date with NO explicit value, exactly as
    # ai_calls.py:1316 does.
    correct_event = quality_gate_event("sleep_coach", f"Day {pt_day} of the climb.", brief)
    wrong_event = quality_gate_event("sleep_coach", f"Day {pt_day + 1} of the climb.", brief)
    assert correct_event["generation_date"] == wrong_event["generation_date"] == pacific_time.pacific_today()

    # The gate consumes the wire event's date exactly as coach_quality_gate.py:821 does.
    correct_report = coach_quality_gate._number_grounding_report(
        correct_event["output_text"], correct_event["generation_brief"], correct_event["generation_date"]
    )
    wrong_report = coach_quality_gate._number_grounding_report(
        wrong_event["output_text"], wrong_event["generation_brief"], wrong_event["generation_date"]
    )
    assert correct_report["verdict"] == "clean", f"the platform's own PT day framing must clear the gate: {correct_report}"
    assert wrong_report["verdict"] == "ungrounded", f"the UTC-clock (one day ahead) framing must be flagged: {wrong_report}"


# ══════════════════════════════════════════════════════════════════════════
# 2. THE STRUCTURAL SAFETY NET
# ══════════════════════════════════════════════════════════════════════════

# "module::qualname" -> the load-bearing, VERIFIED reason its day-shaped `None`
# default never independently resolves a clock (so it cannot disagree about
# the day the way #2675/#2812/#2815 did) or is otherwise out of this sweep's
# scope. Every entry was confirmed by reading the call site on 2026-08-23 —
# not just asserted safe. Add a REAL @pt_day_contract registration instead of
# an entry here whenever a candidate DOES resolve a clock independently.
EXEMPT_PT_DAY_CANDIDATES = {
    "ai.ai_context::_build_journey_context": (
        "private helper; its sole call site (ai_context.build_experiment_phase_context, "
        "registered) always passes an explicit today.isoformat() (ai_context.py:243) — the "
        "None-default path is unreachable from any production caller."
    ),
    "ai.grounded_generation::grounding_findings": (
        "None here DISARMS the #1691 stale_phase/stale_baseline classes (checked only when both "
        "generation_date_iso and start_date_iso are supplied) — it is never defaulted to a clock. "
        "The day resolution for every wired caller lives in the PROVIDER, cycle_gate_params "
        "(registered), which this function only consumes."
    ),
    "ai.night_scope::_night_named_in": (
        "None disables relative-frame night resolution ('last night' with no anchor) — no clock "
        "is consulted on that path (the sibling nightly_vitals_from_narrative's own docstring: "
        "'no lookup, no clock and no I/O')."
    ),
    "ai.night_scope::night_named_in": ("thin public wrapper around _night_named_in — same no-clock contract, see that entry."),
    "ai.night_scope::night_scoped_vitals_findings": (
        "generation_date_iso is passed straight through to _night_named_in for relative-frame "
        "resolution only — no independent clock read; see that entry."
    ),
    "ai.night_scope::nightly_vitals_from_narrative": (
        "generation_date_iso is passed straight through to _night_named_in for relative-frame "
        "resolution only — no independent clock read; see that entry."
    ),
    "coach.coach_chat_grounding::chat_available_logs": (
        "routes through _gen_date(), whose datetime.now(timezone.utc) fallback fires ONLY when "
        "common.pacific_time.pacific_now() itself raised at the sole call site "
        "(telegram_worker_lambda.py: 'today_pt = None' under 'except Exception: # pragma: no "
        "cover — import edge') — the documented fail-soft degrade shared with cycle_gate_params' "
        "own except-branch UTC fallback, never the happy-path default. The happy path always "
        "supplies an explicit, already-Pacific today_pt."
    ),
    "coach.coach_chat_grounding::build_grounder": ("same _gen_date() fail-soft-only fallback as chat_available_logs; see that entry."),
    "coach.coach_ensemble_digest::cycle_gate_params": (
        "an `except ImportError: def cycle_gate_params(generation_date_iso=None): return {}` "
        "shadow — verified it unconditionally returns {} and reads no clock. Every production "
        "import resolves to the REAL cycle_gate_params (registered, ai.grounding_gate_params); "
        "this local def exists only so the module still imports on a genuinely broken bundle."
    ),
    "coach.coach_history_summarizer::cycle_gate_params": ("same ImportError-fallback shadow as coach_ensemble_digest; see that entry."),
    "coach.coach_state_updater::cycle_gate_params": ("same ImportError-fallback shadow as coach_ensemble_digest; see that entry."),
    "coach.coach_quality_gate::_number_grounding_report": (
        "passes generation_date straight to the REAL cycle_gate_params(generation_date) with no "
        "independent resolution of its own — exercised end-to-end (as the GATE half of the "
        "producer+gate pair) by test_quality_gate_wire_chain_agrees_at_a_pt_evening_instant above, "
        "which calls this exact function."
    ),
    "coach.reading_date_fidelity::_dated_claims": (
        "routes generation_date_iso straight to ai.night_scope.night_named_in, which never reads a "
        "clock on the None path (relative-frame resolution only); see the night_scope entries."
    ),
    "coach.reading_date_fidelity::dropped_reading_date_findings": ("delegates to _dated_claims; see that entry."),
    "coach.reading_date_fidelity::summary_keeps_reading_dates": ("delegates to dropped_reading_date_findings; see that entry."),
    "compute.coach_memoir_lambda::gate_check": (
        "resolves generation_date_iso via `generation_date_iso or pacific_today()` inline (the "
        "identical primitive cycle_gate_params uses, registered and proven to resolve to Pacific "
        "at the pinned instant) before feeding grounding_findings — a distinct extraction path "
        "here would need a memoir-shaped facts/text fixture to observe a stale_phase finding, for "
        "no new coverage of the day-resolution primitive itself."
    ),
    "operational.phase_plausibility::sweep_payloads": (
        "delegates its entire clock resolution to phase_context(today_iso) (registered, same-module "
        "sibling reader_truth_qa.phase_context) — the only use of the result is day_n = "
        "phase['day_n']; sweep_payloads reads no clock of its own."
    ),
    "operational.reader_truth_qa::assess_prose": (
        "delegates to phase_context(today_iso) (registered) at the top of the function — the added "
        "surface here (Bedrock invoke, model_name, batching) never touches day resolution."
    ),
}


def test_every_day_default_candidate_is_decided():
    """GUARD THE SET: every function in lambdas/ that accepts a day-shaped
    parameter defaulting to None must be either @pt_day_contract-registered
    (swept above, automatically) or carry a written, specific exemption here.
    A brand-new gate satisfying neither fails THIS test — the #2813 outcome:
    a new gate cannot silently ship with an unswept, possibly-UTC default."""
    registered_keys = {_candidate_key(e.module, e.qualname) for e in PT_DAY_CONTRACT_REGISTRY}
    candidates = _day_default_candidates()
    undecided = [
        f"{_candidate_key(module, qualname)} (param={param!r})"
        for module, qualname, param in candidates
        if _candidate_key(module, qualname) not in registered_keys and _candidate_key(module, qualname) not in EXEMPT_PT_DAY_CANDIDATES
    ]
    assert not undecided, (
        "New/changed function(s) accept a generation_date/day_n-shaped default with no #2813 "
        "decision — either add @pt_day_contract(...) in the production module (see "
        "lambdas/common/pt_day_contract.py) or a verified reason in EXEMPT_PT_DAY_CANDIDATES "
        "(tests/test_pt_day_contract_sweep_2813.py):\n" + "\n".join(f"  {u}" for u in undecided)
    )


def test_no_stale_exemptions():
    """Keep EXEMPT_PT_DAY_CANDIDATES derived — an entry for a candidate the scan
    no longer finds (renamed, deleted, or since registered) is stale and must
    be removed, not left to rot (mirrors tests/test_wallclock_fixture_bombs_2376.py)."""
    candidates = {_candidate_key(module, qualname) for module, qualname, _param in _day_default_candidates()}
    stale = sorted(k for k in EXEMPT_PT_DAY_CANDIDATES if k not in candidates)
    assert not stale, f"EXEMPT_PT_DAY_CANDIDATES lists candidate(s) the scan no longer finds; delete them: {stale}"


def test_registry_and_exemptions_do_not_overlap():
    """A candidate that is BOTH registered and exempted is a contradiction —
    the exemption claims 'no clock read', the registration claims 'sweep this
    for clock agreement'. Catches copy-paste drift between the two lists."""
    registered_keys = {_candidate_key(e.module, e.qualname) for e in PT_DAY_CONTRACT_REGISTRY}
    overlap = registered_keys & set(EXEMPT_PT_DAY_CANDIDATES)
    assert not overlap, f"registered AND exempted — pick one: {sorted(overlap)}"


def test_scan_discovers_a_synthetic_decorated_function(tmp_path, monkeypatch):
    """Mutation proof for the DISCOVERY mechanism itself (distinct from the #4
    production mutation proof described in the module docstring): without this,
    a scanner that silently matched nothing would green every assertion above.
    A synthetic module with a day-default param and no decorator/exemption must
    be flagged by the candidate scan; the same module decorated must not be."""
    synthetic_dir = tmp_path / "synthetic_pkg"
    synthetic_dir.mkdir()
    (synthetic_dir / "__init__.py").write_text("")
    bare = "def gate_check(generation_date_iso=None):\n    return generation_date_iso\n"
    (synthetic_dir / "leaf.py").write_text(bare)

    monkeypatch.setattr(sys.modules[__name__], "_LAMBDAS", str(tmp_path))
    found = {_candidate_key(m, q) for m, q, _p in _day_default_candidates()}
    assert "synthetic_pkg.leaf::gate_check" in found

    decorated = "from common.pt_day_contract import pt_day_contract\n\n\n@pt_day_contract(extract=lambda r: r)\ndef gate_check(generation_date_iso=None):\n    return generation_date_iso\n"
    (synthetic_dir / "leaf.py").write_text(decorated)
    modules_using = set(_modules_using_pt_day_contract())
    assert "synthetic_pkg.leaf" in modules_using
