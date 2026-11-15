"""tests/test_advice_links_5612.py — the advice link: evidence-only, owner-only, no backfill (#5612, ruling F).

Owner ruling F (2026-11-02, epic #5607): a structured relationship between coach
recommendations and Matthew's recorded decisions; "do not infer that I followed advice simply
because my subsequent behavior happened to align with it"; acted_on / declined /
partially_followed / unknown "only when supported by evidence"; historical records stay unknown,
never backfilled.

What each leg holds (the charter primitives for this record family):
  REGISTRY            `lambdas/coach/advice_links.py` — STATES, REF_KINDS, the validator.
  DERIVATION GUARD    the tool's literal inputSchema enums EQUAL the registry (both directions);
                      coach ids derive from the persona registry.
  CONTRACT            every evidence-requiring state is refused without evidence at write, on the
                      tool's real args → record → table path; the row the tool writes is the row
                      `get_decisions` reads (same fake table, the stored shape is the wire); a bad
                      stored row reads unknown.
  ONE-WRITER GUARD    an AST sweep of the tracked tree: only the owner MCP tool constructs a link,
                      only three modules may name the family at all, and no module outside the
                      registry spells a non-unknown state — so no compute path can derive one.
  NO BACKFILL         no script/deploy file touches the family; every unlinked decision reads unknown.
  PARTITION ISOLATION every DECISION# reader of the shared partition narrows on its own prefix, so
                      the new family never leaks into a decision count.

# premerge-gate: sweeps the tracked tree (git ls-files) for writers of the ADVICELINK# family and for state literals
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coach import (
    advice_links as al,  # noqa: E402
    persona_registry as pr,  # noqa: E402
)
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_advice_links as tal  # noqa: E402
import mcp.tools_decisions as td  # noqa: E402

PK = "USER#matthew#SOURCE#decisions"
DEC_A = "DECISION#2026-10-30T22:41:18.075Z"
DEC_B = "DECISION#2026-10-31T08:00:00.000Z"
PRED = "pred_20261029_protein_first_meal_lifts_hrv"
OUTPUT = "2026-10-30#daily_brief_sleep"
ACTION = "2026-10-30-sleep"
ASK = "commit_20261030_lights_out_by_22_30_on_weeknights"

# The three modules allowed to name the family at all, and the one allowed to construct a row.
REGISTRY_MODULE = "lambdas/coach/advice_links.py"
WRITER_MODULE = "mcp/tools_advice_links.py"
READER_MODULE = "mcp/tools_decisions.py"
#: The ONE reader of the ask-response family (owner 2026-11-12): the public projection and the owner's current answers.
ASK_READER_MODULE = "lambdas/coach/ask_outcomes.py"
#: mcp/idempotency.py names the sk shape in the tool's replay-semantics declaration (a string, no access).
ALLOWED_TO_NAME = frozenset({REGISTRY_MODULE, WRITER_MODULE, READER_MODULE, ASK_READER_MODULE, "mcp/idempotency.py"})
#: Each record constructor and the one function allowed to call it.
WRITER_FUNCTIONS = frozenset(
    {(WRITER_MODULE, "tool_log_advice_link", "build_link_record"), (WRITER_MODULE, "_log_ask_response", "build_ask_response")}
)


# ── the fake table: a query hook that evaluates the real boto3 Key condition ──────────────


def _key_parts(cond) -> tuple[str | None, str | None]:
    pk = prefix = None
    stack = [cond]
    while stack:
        c = stack.pop()
        expr = c.get_expression()
        op = expr["operator"]
        if op == "AND":
            stack.extend(expr["values"])
        elif op == "=":
            pk = expr["values"][1]
        elif op == "begins_with":
            prefix = expr["values"][1]
    return pk, prefix


def _query_hook(table, **kwargs):
    pk, prefix = _key_parts(kwargs["KeyConditionExpression"])
    rows = [r for (p, s), r in table.store.items() if p == pk and (prefix is None or s.startswith(prefix))]
    if "#phase" in (kwargs.get("FilterExpression") or ""):
        rows = [r for r in rows if r.get("phase") in (None, "experiment")]
    rows.sort(key=lambda r: r["sk"], reverse=kwargs.get("ScanIndexForward") is False)
    return {"Items": rows}


def _table(*extra):
    rows = [
        {"pk": PK, "sk": DEC_A, "date": "2026-10-30", "decision": "Front-load protein", "followed": True, "source": "mcp"},
        {"pk": PK, "sk": DEC_B, "date": "2026-10-31", "decision": "Rest day", "source": "mcp"},
        {"pk": "COACH#nutrition_coach", "sk": f"PREDICTION#{PRED}", "prediction_id": PRED, "coach_id": "nutrition_coach"},
        {"pk": "COACH#sleep_coach", "sk": f"OUTPUT#{OUTPUT}", "text": "Lights out by 22:30."},
        {"pk": "USER#matthew", "sk": f"SOURCE#coach_actions#{ACTION}", "action_id": ACTION, "coach_id": "sleep"},
        {
            "pk": "COACH#sleep_coach",
            "sk": f"COMMITMENT#{ASK}",
            "commitment_id": ASK,
            "coach_id": "sleep_coach",
            "commitment_natural": "Lights out by 22:30 on weeknights.",
            "status": "kept",
        },
        *extra,
    ]
    return FakeDdbTable(rows=rows, query_hook=_query_hook)


@pytest.fixture
def table(monkeypatch):
    t = _table()
    monkeypatch.setattr(tal, "_table_ref", t)
    monkeypatch.setattr(td, "_table_ref", t)
    return t


def _link(**over):
    args = {"decision_sk": DEC_A, "coach_id": "nutrition_coach", "ref_kind": "prediction", "ref_id": PRED, "state": "acted_on"}
    args.update(over)
    return args


def _links_in(t):
    return [r for (p, s), r in t.store.items() if s.startswith(al.SK_PREFIX)]


# ── REGISTRY + CONTRACT: the write-time rule ─────────────────────────────────────────────


def test_every_evidence_requiring_state_is_refused_without_evidence(table):
    """The ruling's core: every state but unknown is refused, at the tool, with nothing stored."""
    assert al.EVIDENCE_REQUIRED_STATES == set(al.STATES) - {"unknown"}
    refused = set()
    for state in al.STATES:
        for empty in ({}, {"evidence_text": "   "}, {"evidence_text": "", "evidence_ref": ""}):
            res = tal.tool_log_advice_link(_link(state=state, **empty))
            if res.get("written") is False and "error" in res:
                refused.add(state)
    assert refused == al.EVIDENCE_REQUIRED_STATES, refused
    assert {r["state"] for r in _links_in(table)} == {"unknown"}, "only the unknown attempts may have landed"


def test_unknown_needs_no_evidence_and_evidence_is_stored_verbatim(table):
    res = tal.tool_log_advice_link(_link(state="unknown"))
    assert res["written"] is True and "evidence" not in table.store[(PK, res["sk"])]
    words = "I moved the protein to breakfast on Thursday because the coach asked."
    res = tal.tool_log_advice_link(_link(state="acted_on", evidence_text=words))
    row = table.store[(PK, res["sk"])]
    assert row["state"] == "acted_on" and row["evidence"]["text"] == words
    assert row["evidence"]["asserted_by"] == "owner" and row["recorded_by"] == "owner"
    assert row["evidence"]["asserted_at"] == row["recorded_at"]
    # a reference alone is evidence too
    res = tal.tool_log_advice_link(_link(state="declined", evidence_ref="journal 2026-10-31"))
    assert table.store[(PK, res["sk"])]["evidence"] == {
        "asserted_by": "owner",
        "asserted_at": table.store[(PK, res["sk"])]["recorded_at"],
        "reference": "journal 2026-10-31",
    }


_REFUSALS = [
    ({"recorded_by": "nutrition_coach", "evidence_text": "x"}, "recorded_by"),
    ({"state": "followed", "evidence_text": "x"}, "state must be"),
    ({"ref_kind": "insight", "evidence_text": "x"}, "ref_kind"),
    ({"coach_id": "dr_nobody", "evidence_text": "x"}, "coach_id"),
    ({"ref_id": "not a prediction id", "evidence_text": "x"}, "ref_id"),
    ({"decision_sk": "INSIGHT#2026", "evidence_text": "x"}, "DECISION#"),
    ({"decision_sk": "DECISION#2020-01-01T00:00:00.000Z", "evidence_text": "x"}, "no current-cycle decision"),
    ({"ref_id": "pred_20261001_never_made", "evidence_text": "x"}, "no current-cycle prediction"),
    ({"coach_id": "sleep_coach", "evidence_text": "x"}, "no current-cycle prediction"),  # wrong coach for the prediction
    ({"ref_kind": "coach_action", "ref_id": ACTION, "coach_id": "mind_coach", "evidence_text": "x"}, "issued by sleep"),
]


def test_the_write_refuses_what_the_ruling_or_the_record_forbids(table):
    """One test over every refusal (reports every offender, not the first)."""
    misses = []
    for over, fragment in _REFUSALS:
        res = tal.tool_log_advice_link(_link(**over))
        if res.get("written") is not False or fragment not in res.get("error", ""):
            misses.append((over, res))
    assert misses == []
    assert _links_in(table) == []


def test_a_coach_action_must_have_been_issued_by_the_named_coach(monkeypatch):
    t = _table({"pk": "USER#matthew", "sk": "SOURCE#coach_actions#2026-10-30-mind", "action_id": "2026-10-30-mind", "coach_id": "sleep"})
    monkeypatch.setattr(tal, "_table_ref", t)
    res = tal.tool_log_advice_link(_link(ref_kind="coach_action", ref_id="2026-10-30-mind", coach_id="mind_coach", evidence_text="x"))
    assert res["written"] is False and "issued by sleep" in res["error"]
    ok = tal.tool_log_advice_link(_link(ref_kind="coach_action", ref_id=ACTION, coach_id="sleep_coach", evidence_text="did it"))
    assert ok["written"] is True


def test_a_tombstoned_decision_or_recommendation_cannot_be_linked(monkeypatch):
    t = _table({"pk": "COACH#sleep_coach", "sk": "OUTPUT#2026-09-01#daily_brief_sleep", "tombstone": True, "phase": "pilot"})
    monkeypatch.setattr(tal, "_table_ref", t)
    res = tal.tool_log_advice_link(
        _link(coach_id="sleep_coach", ref_kind="coach_output", ref_id="2026-09-01#daily_brief_sleep", evidence_text="x")
    )
    assert res["written"] is False and "no current-cycle coach_output" in res["error"]


def test_replay_writes_nothing_and_a_changed_answer_keeps_the_first(table):
    first = tal.tool_log_advice_link(_link(evidence_text="did it"))
    assert first["written"] is True
    assert tal.tool_log_advice_link(_link(evidence_text="did it")) == {
        "status": "unchanged",
        "sk": first["sk"],
        "state": "acted_on",
        "written": False,
    }
    assert len(table.puts) == 1
    second = tal.tool_log_advice_link(_link(state="partially_followed", evidence_text="only on two of the five days"))
    row = table.store[(PK, second["sk"])]
    assert second["sk"] == first["sk"] and row["state"] == "partially_followed"
    assert [p["state"] for p in row["previous"]] == ["acted_on"] and row["previous"][0]["evidence"]["text"] == "did it"


def test_the_sk_is_deterministic_and_scoped_to_its_decision():
    sk = al.link_sk(DEC_A, "coach_output", "sleep_coach", OUTPUT)
    assert sk == f"ADVICELINK#2026-10-30T22:41:18.075Z#coach_output#sleep_coach#{OUTPUT}"
    prefix = lambda dec: f"{al.SK_PREFIX}{dec[len(al.DECISION_SK_PREFIX):]}#"  # noqa: E731 — one decision's link prefix
    assert sk.startswith(prefix(DEC_A)) and not sk.startswith(prefix(DEC_B))


# ── DERIVATION GUARD: the copies equal the registry ─────────────────────────────────────


def test_the_tool_schema_enums_equal_the_registry_both_ways():
    props = tal.LOG_ADVICE_LINK_INPUT["properties"]
    assert props["state"]["enum"] == list(al.TOOL_STATES)
    assert set(al.TOOL_STATES) == set(al.STATES) | set(al.ASK_RESPONSE_STATES)
    assert set(props["ref_kind"]["enum"]) == set(al.REF_KINDS)
    assert "enum" not in props["coach_id"], "coach ids derive from the persona registry at write — never a copy here"
    # decision_sk and state are required in code for a decision link; an ask needs neither (withdraw takes no state)
    assert set(tal.LOG_ADVICE_LINK_INPUT["required"]) == {"coach_id", "ref_kind", "ref_id"}
    assert props["withdraw"]["type"] == "boolean"


def test_coach_ids_derive_from_the_persona_registry():
    assert al.KNOWN_COACH_IDS == set(pr.OPERATIONAL_COACH_IDS) | set(pr.CHAT_COACH_IDS) | set(pr.RETIRED_COACH_IDS)
    src = (ROOT / REGISTRY_MODULE).read_text(encoding="utf-8")
    for cid in pr.OPERATIONAL_COACH_IDS:
        assert f'"{cid}"' not in src, f"{cid} hand-listed in the registry module"


def test_the_tool_is_registered_and_classified_as_a_write():
    from mcp import audit, idempotency
    from mcp.registry import TOOLS

    assert TOOLS["log_advice_link"]["fn"] is tal.tool_log_advice_link
    assert audit.is_write_tool("log_advice_link")
    assert idempotency.REPLAY_SEMANTICS["log_advice_link"][0] == idempotency.DETERMINISTIC_KEY


# ── the READ path: absence is unknown; the stored row is the wire ───────────────────────


def test_get_decisions_reads_every_unlinked_decision_as_unknown(table):
    res = td.tool_get_decisions({"days": 3650})
    assert res["total_decisions"] == 2
    assert res["advice_links"] == {"acted_on": 0, "declined": 0, "partially_followed": 0, "unknown": 2}
    assert all(d["advice_links"] == [] for d in res["decisions"])
    # the existing `followed: true` on DEC_A is NOT evidence and is never converted
    assert next(d for d in res["decisions"] if d["sk"] == DEC_A)["followed"] is True


def test_get_decisions_reads_back_exactly_what_the_tool_wrote(table):
    words = "Yes — I did the protein breakfast all week."
    w = tal.tool_log_advice_link(_link(evidence_text=words))
    res = td.tool_get_decisions({"days": 3650})
    assert res["total_decisions"] == 2, "a link row must never count as a decision"
    a = next(d for d in res["decisions"] if d["sk"] == DEC_A)
    assert a["advice_links"] == [al.owner_view(table.store[(PK, w["sk"])])]
    assert a["advice_links"][0]["state"] == "acted_on" and a["advice_links"][0]["evidence"]["text"] == words
    assert res["advice_links"] == {"acted_on": 1, "declined": 0, "partially_followed": 0, "unknown": 1}


def test_a_stored_row_that_breaks_the_rule_reads_unknown(monkeypatch):
    bad = {
        "pk": PK,
        "sk": al.link_sk(DEC_B, "prediction", "nutrition_coach", PRED),
        "decision_sk": DEC_B,
        "state": "acted_on",
        "recorded_by": "owner",
    }
    pilot = {
        **bad,
        "sk": al.link_sk(DEC_A, "prediction", "nutrition_coach", PRED),
        "decision_sk": DEC_A,
        "phase": "pilot",
        "evidence": {"text": "x"},
    }
    t = _table(bad, pilot)
    monkeypatch.setattr(td, "_table_ref", t)
    res = td.tool_get_decisions({"days": 3650})
    b = next(d for d in res["decisions"] if d["sk"] == DEC_B)
    assert b["advice_links"][0]["state"] == "unknown"
    assert next(d for d in res["decisions"] if d["sk"] == DEC_A)["advice_links"] == [], "a wiped cycle's link must not read"


# ── ONE-WRITER GUARD + NO BACKFILL + PARTITION ISOLATION (tree sweeps) ──────────────────


def _tracked_py() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out if not p.startswith("tests/") and (ROOT / p).exists()]


def _names_the_family(src: str, tree: ast.AST) -> bool:
    if "ADVICELINK" in src or "ASKRESPONSE" in src:
        return True
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "coach.advice_links" or (node.module == "coach" and any(a.name == "advice_links" for a in node.names)))
        ):
            return True
        if isinstance(node, ast.Import) and any(a.name == "coach.advice_links" for a in node.names):
            return True
    return False


#: STRICT ON THE VERB: what counts is ASSIGNING an asserting state — a `state`/`advice_state` key or
#: keyword set to one, or a collection that copies the vocabulary. A bare `"acted_on"` elsewhere is a
#: different vocabulary (remediation/signal_identity.py's alarm observations use `acted_on` as a dict
#: key) and is deliberately not flagged.
_ASSERTING = set(al.EVIDENCE_REQUIRED_STATES)
#: A single assignment of any answer Matthew gives (not_yet_decided is his answer too, owner 2026-11-12) is flagged;
#: the collection rule stays on the three asserting states so a three-state copy is still caught.
_ASSIGNED = _ASSERTING | {al.NOT_YET_DECIDED}
_STATE_NAMES = {"state", "advice_state"}
#: The registry, and the writer's literal inputSchema enum (held equal to the registry above).
_MAY_SPELL = {REGISTRY_MODULE, WRITER_MODULE}


def _lit(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _assigns_an_asserting_state(tree: ast.AST) -> list[int]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is not None and _lit(k) in _STATE_NAMES and _lit(v) in _ASSIGNED:
                    hits.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg in _STATE_NAMES and _lit(node.value) in _ASSIGNED:
            hits.append(node.value.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _lit(node.value) in _ASSIGNED:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                name = (
                    _lit(t.slice) if isinstance(t, ast.Subscript) else (t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", None))
                )
                if name in _STATE_NAMES:
                    hits.append(node.lineno)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            if _ASSERTING <= {_lit(e) for e in node.elts}:
                hits.append(node.lineno)
    return hits


def test_only_the_owner_tool_writes_and_only_the_allowed_modules_name_the_family():
    naming, spelling, constructing = set(), set(), set()
    for rel in _tracked_py():
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if _names_the_family(src, tree):
            naming.add(rel)
        if rel not in _MAY_SPELL and _assigns_an_asserting_state(tree):
            spelling.add((rel, tuple(_assigns_an_asserting_state(tree))))
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                f = call.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name in ("build_link_record", "build_ask_response"):
                    constructing.add((rel, fn.name, name))
    assert naming <= ALLOWED_TO_NAME, f"modules naming the ADVICELINK# family outside the allowlist: {sorted(naming - ALLOWED_TO_NAME)}"
    assert naming == ALLOWED_TO_NAME, f"an allowed module stopped naming the family (vacuous guard?): {sorted(ALLOWED_TO_NAME - naming)}"
    assert (
        spelling == set()
    ), f"an asserting advice state is assigned outside the owner tool (derivation from behaviour?): {sorted(spelling)}"
    assert constructing == WRITER_FUNCTIONS, f"link constructors: {sorted(constructing)}"


def test_the_reader_never_writes_a_link():
    tree = ast.parse((ROOT / READER_MODULE).read_text(encoding="utf-8"))
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_advice_links_by_decision"):
        calls = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert not calls & {"put_item", "update_item", "batch_writer", "delete_item"}, calls
        return
    pytest.fail("the reader function moved — re-point this guard")


def test_no_backfill_or_migration_of_advice_states_exists():
    """Ruling F: 'historical records without such evidence should remain unknown, not be backfilled'."""
    offenders = [p for p in _tracked_py() if p.startswith(("scripts/", "deploy/")) and re.search(r"advice|5612", p, re.I)]
    assert offenders == [], offenders
    ops = [p for p in _tracked_py() if p.startswith(("scripts/", "deploy/", "lambdas/"))]
    touching = set()
    for p in ops:
        src = (ROOT / p).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if _names_the_family(src, tree):  # the ADVICELINK key family, or an import of the registry
            touching.add(p)
    assert touching == {REGISTRY_MODULE, ASK_READER_MODULE}, f"an ops/compute module touches the advice-link family: {sorted(touching)}"


_DECISIONS_PK_RE = re.compile(r"SOURCE#decisions|\}decisions\"|_decisions_pk\(")


def test_every_decision_reader_of_the_shared_partition_narrows_on_its_prefix():
    """The family shares the decisions pk, so a reader that queried the bare partition would
    count a link as a decision. Every module that builds the pk and queries must narrow."""
    exempt = {
        "deploy/restart_intelligence_wipe.py": "tombstones the WHOLE partition at a reset — links follow their decision, by design",
        "mcp/idempotency.py": "names the pk in a comment only (its ledger lives elsewhere)",
    }
    readers = []
    for rel in _tracked_py():
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if _DECISIONS_PK_RE.search(src) and rel not in exempt:
            readers.append(rel)
            if ".query(" in src or "sk_prefix" in src:
                assert (
                    'begins_with("DECISION#")' in src or '"sk_prefix": "DECISION#"' in src
                ), f"{rel} reads the decisions partition without the DECISION# prefix"
    assert {"mcp/tools_decisions.py", "lambdas/web/site_api_thirdwall.py"} <= set(readers), readers


def test_the_state_sweep_can_fail():
    """Mutation proof, in-file: each assignment shape the sweep claims to catch is caught, and the
    remediation-style dict key is not."""
    caught = [
        'row = {"state": "acted_on"}',
        "put(state='declined')",
        'rec["state"] = "partially_followed"',
        "self.advice_state = 'acted_on'",
        'STATES = ("acted_on", "declined", "partially_followed")',
        'row = {"state": "not_yet_decided"}',
    ]
    missed = [src for src in caught if not _assigns_an_asserting_state(ast.parse(src))]
    assert missed == []
    for clean in ('ob = {"acted_on": True}', 'x.get("acted_on")', 'state = "unknown"'):
        assert _assigns_an_asserting_state(ast.parse(clean)) == [], clean


#: The read-only ask queue (`get_advice_link_queue`) sits beside the owner tool: it must never write, never name the
#: family and never call the writer, so the one-writer guard above still has exactly one writer to name.
QUEUE_MODULE = "mcp/tools_advice_queue.py"
_DDB_WRITES = {"put_item", "update_item", "delete_item", "batch_writer", "batch_write_item", "transact_write_items"}


def test_the_advice_queue_is_read_only_and_outside_the_family():
    src = (ROOT / QUEUE_MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert QUEUE_MODULE not in ALLOWED_TO_NAME and not _names_the_family(src, tree)
    calls = {
        c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None) for c in ast.walk(tree) if isinstance(c, ast.Call)
    }
    assert not calls & (_DDB_WRITES | {"build_link_record", "tool_log_advice_link"}), calls
    assert not _assigns_an_asserting_state(tree)


# ── a coach ASK (COMMITMENT#) is answered by an ask response, never a decision link (owner 2026-11-12) ─
# The ask-response behaviour itself (states, revisions, withdrawal, the public projection) is tests/test_ask_responses.py.


def test_an_ask_cannot_be_a_decision_link():
    with pytest.raises(al.AdviceLinkError, match="ask response"):
        al.build_link_record(
            user_id="matthew",
            decision_sk=DEC_A,
            coach_id="sleep_coach",
            ref_kind="commitment",
            ref_id=ASK,
            state="acted_on",
            evidence={"text": "I did it"},
            recorded_at="2026-10-31T00:00:00.000Z",
        )
    stray = {"pk": PK, "sk": al.link_sk(DEC_A, "commitment", "sleep_coach", ASK), "ref_kind": "commitment", "state": "acted_on"}
    assert al.effective_state({**stray, "recorded_by": "owner", "evidence": {"text": "I did it"}}) == "unknown"


def test_the_queue_points_at_the_ask_kind_the_registry_accepts():
    """get_advice_link_queue's instructions name the ask kind; it must be a real REF_KINDS key answered by an ask response."""
    from mcp import tools_advice_queue as taq

    assert "log_advice_link" in taq.HOW_TO_RECORD and "ref_kind='commitment'" in taq.HOW_TO_RECORD
    assert "commitment" in al.REF_KINDS and al.answered_by_ask_response("commitment")
    assert not any(al.answered_by_ask_response(k) for k in ("prediction", "coach_output", "coach_action"))
    for state in al.ASK_RESPONSE_STATES:
        assert state in taq.HOW_TO_RECORD, state
    assert "withdraw=true" in taq.HOW_TO_RECORD and "never 'declined'" in taq.HOW_TO_RECORD
