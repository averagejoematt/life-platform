"""tests/test_labs_producer_import_graph_3792.py — #3792 box 1: the DASHBOARD producer.

`tests/test_labs_coach_domain_facts_3792.py` covers `coach.coach_domain_facts._labs_pack`
and it is correct — run live it emits *"Most recent draw: 2026-04-03 — it is COMPLETE …
Do not narrate it as upcoming, scheduled, or awaited."*

**The producer of the surface in the issue's title never read it.** `_PACKS` feeds
`coach_team_texture` / `telegram_worker_lambda` / `coach_chat_grounding` — the Telegram and
chat grounding path. The `/api/coaching-dashboard` labs row is written by
`coach_state_updater` from text `ai_calls._run_coach_v2_pipeline` generated, and
`ai_calls` does not import `coach_domain_facts` at all. Measured live on 2026-09-16T17:07:26Z:
the coach regenerated, `day_n` 10 -> 11, and the stored record still said *"schedule the
April 3rd draw"* and *"holding the escalation until April's CMP returns"* about a draw 166
days past.

So this file asserts two different things, and the second is the one the previous attempt
was missing:

1. **The words.** `ai_context._build_labs_data` — the dict JSON-dumped into the prompt's
   `LABS DATA:` block — states the draw is done and how old it is.
2. **The path.** `intelligence.labs_facts` is REACHABLE by import from the brief entry point
   that produces this surface. A fix present in the deployed bundle but absent from the
   consuming module's import closure is inert, and a zip grep cannot tell the two apart
   (#3713's shape, repeated on this very issue).
"""

from __future__ import annotations

import ast
import collections
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"

if str(LAMBDAS) not in sys.path:
    sys.path.insert(0, str(LAMBDAS))

from ai import ai_context  # noqa: E402
from common.pacific_time import pacific_now  # noqa: E402

# The April panel exactly as DynamoDB holds it (verified against
# `USER#matthew#SOURCE#labs / DATE#2026-04-03`, 2026-09-16): a nested `biomarkers`
# map plus `out_of_range` / `out_of_range_count` / `total_biomarkers`. There is no
# top-level `flagged_markers`, no `flagged_count` and no `total_draws` — the schema
# the old `_build_labs_data` read has never existed on any record (#1993).
_REAL_DRAW = {
    "sk": "DATE#2026-04-03",
    "draw_date": "2026-04-03",
    "biomarkers": {"ige_total": {"value": 339, "unit": "kU/L", "flag": "high", "ref_text": "0-114"}},
    "out_of_range": ["ige_total"],
    "out_of_range_count": 1,
    "total_biomarkers": 153,
}
_OLDER_DRAW = {
    "sk": "DATE#2025-04-17",
    "draw_date": "2025-04-17",
    "biomarkers": {},
    "out_of_range": [],
    "out_of_range_count": 0,
    "total_biomarkers": 100,
}


def _brief_data(**over):
    d = {"labs": [_OLDER_DRAW, _REAL_DRAW]}
    d.update(over)
    return d


# ── 1. The words ──────────────────────────────────────────────────────────────


def test_MUST_FAIL_the_draw_is_stated_as_ALREADY_DRAWN_with_its_age():
    """The defect in one assertion.

    Pre-fix this returned `{"draw_date": "2026-04-03", ...}` — a bare date with no age and
    no assertion that the draw is done. Revert `_build_labs_data` to that dict and this
    goes red on the first assert.
    """
    out = ai_context._build_labs_data(_brief_data())
    blob = " ".join(str(v) for v in out.values())
    assert "ALREADY DRAWN AND RESULTED" in blob, "the completed draw is not stated as complete — the coach can narrate it as upcoming"
    # #3222: the producer stamps the age off `pacific_now()` (labs_facts), so the
    # expectation must read the SAME clock — a naive UTC `date.today()` disagrees with it
    # for the seven hours after 17:00 PT.
    age = (pacific_now().date() - datetime.strptime("2026-04-03", "%Y-%m-%d").date()).days
    assert f"{age} days ago" in blob, f"the draw's age ({age}d) must be stated, not left for the model to infer"
    assert "scheduled, upcoming, or still to be booked" in blob, "the instruction forbidding the live wording is absent"


def test_the_PHANTOM_schema_read_is_gone():
    """The second half of the defect, and it was silent.

    `flagged_markers` / `flagged_count` / `total_draws` were read off top-level keys no
    record carries, so all three were structurally constant — `flagged_count: 0` beside a
    panel with a real out-of-range marker is the ADR-104 breach #1993 fixed in the
    analyzer and left standing here.
    """
    out = ai_context._build_labs_data(_brief_data())
    assert out["flagged_count"] == 1, "a real out-of-range marker still reports 0 — the phantom-schema read survives"
    assert out["flagged_markers"], "flagged markers are empty against a draw that has one"
    assert out["total_draws"] == 2, "total_draws is not derived from the draw list"
    assert out["store_empty"] is False


def test_an_EMPTY_store_is_still_narrated_honestly():
    """The control in the opposite direction: the fix must not assert a draw that is not there."""
    out = ai_context._build_labs_data({"labs": []})
    assert out["store_empty"] is True
    blob = " ".join(str(v) for v in out.values())
    assert "zero draw records" in blob.lower()
    assert "ALREADY DRAWN AND RESULTED" not in blob, "an empty store must not claim a completed draw"


def test_a_caller_handing_ONE_record_DEGRADES_rather_than_asserting_a_wrong_total():
    """Any caller predating the list shape still gets the framing, but `total_draws` is
    DROPPED rather than published as 1 — one record is honest about the panel and says
    nothing about the history. A bare "0 total blood draws" beside a real date is the
    contradiction #3728 traced the defect to, so silence is the only honest option."""
    out = ai_context._build_labs_data({"labs": _REAL_DRAW})
    assert "total_draws" not in out, "a single-record fallback must not claim it has seen the whole history"
    assert "ALREADY DRAWN AND RESULTED" in " ".join(str(v) for v in out.values())


def test_the_framing_comes_from_the_SHARED_builder_not_a_second_derivation():
    """Box 2: ONE home for the window framing. Re-typing the sentence into a second place
    is how #3737's analyzer fix and this producer drifted apart.

    Asserted as a DELEGATION, not as the presence of a call: `_build_labs_data` must hand
    the whole question to `labs_facts` and derive nothing of its own. A producer that
    calls the shared builder and then adds a sentence beside it is the same drift with an
    import in front of it."""
    src = (LAMBDAS / "ai" / "ai_context.py").read_text(encoding="utf-8")
    body = src[src.index("def _build_labs_data(data):") : src.index("def _build_explorer_data(data):")]
    assert "labs_facts.coach_domain_block" in body, "the producer does not read the shared builder"
    for derived in ("flagged_count", "flagged_markers", "draw_date", "total_draws", "ALREADY DRAWN"):
        assert derived not in body.split('"""')[-1], f"{derived!r} is re-derived in the producer instead of read from labs_facts"


# ── 2. The path (the load-bearing half) ───────────────────────────────────────


def _module_file(dotted: str):
    p = LAMBDAS / (dotted.replace(".", "/") + ".py")
    if p.exists():
        return p
    p = LAMBDAS / dotted.replace(".", "/") / "__init__.py"
    return p if p.exists() else None


def _imports_of(path: Path):
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            # `from intelligence import labs_facts` binds a SUBMODULE, not a package
            # attribute. Resolving only `node.module` makes the edge invisible — which
            # is exactly how a walker reports a live import as unreachable.
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def _import_closure(start: str):
    """Modules reachable from `start` as the bundle's FLAT zip root resolves them."""
    seen, queue, edges = set(), collections.deque([start]), collections.defaultdict(list)
    while queue:
        cur = queue.popleft()
        if cur in seen:
            continue
        seen.add(cur)
        path = _module_file(cur)
        if path is None:
            continue
        for imp in _imports_of(path):
            if _module_file(imp) is not None:
                edges[cur].append(imp)
                if imp not in seen:
                    queue.append(imp)
    return seen, edges


def _shortest_path(start: str, target: str, edges):
    prev, queue = {start: None}, collections.deque([start])
    while queue:
        cur = queue.popleft()
        if cur == target:
            break
        for nxt in edges.get(cur, ()):
            if nxt not in prev:
                prev[nxt] = cur
                queue.append(nxt)
    if target not in prev:
        return []
    out, cur = [], target
    while cur is not None:
        out.append(cur)
        cur = prev[cur]
    return list(reversed(out))


def test_THE_LOAD_BEARING_ASSERTION_the_dashboard_producer_can_actually_reach_the_fix():
    """In the bundle is not on the path.

    #3792's first fix shipped in `coach-narrative-orchestrator`'s live zip and was inert,
    because the module that builds THIS surface's prompt never imports it. A zip grep
    proves shipping; only the import closure proves reachability.
    """
    seen, edges = _import_closure("emails.daily_brief_lambda")
    assert "intelligence.labs_facts" in seen, (
        "the daily-brief entry point cannot reach intelligence.labs_facts — the labs framing is "
        "inert on /api/coaching-dashboard no matter what ships in the zip (#3792)"
    )
    # Name the route, so a regression says WHICH edge broke rather than just "unreachable".
    path = _shortest_path("emails.daily_brief_lambda", "intelligence.labs_facts", edges)
    assert path[:3] == ["emails.daily_brief_lambda", "ai.ai_calls", "ai.ai_context"], f"unexpected route to labs_facts: {path}"


def test_the_walker_itself_can_report_UNREACHABLE():
    """A reachability assertion that cannot fail is not a check. A module that genuinely is
    not in the brief's closure must come back False."""
    seen, _ = _import_closure("emails.daily_brief_lambda")
    assert "intelligence.labs_facts" in seen
    assert "no.such.module.anywhere" not in seen
    # And a real, existing lambdas module the brief does not import.
    assert _module_file("operational.qa_smoke_lambda") is not None
    assert "operational.qa_smoke_lambda" not in seen, "the closure walker is over-reporting — it would pass on anything"
