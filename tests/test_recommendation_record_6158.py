"""tests/test_recommendation_record_6158.py — the ONE recommendation record and the coach-context pilot (#6158).

Part A (live on merge): `coach.recommendation_record` + the owner tool `manage_coach_recommendation`.
  * the admission rule admits material, actionable recommendations and refuses the rest, by name;
  * the response vocabulary is one set, absence reads `not_recorded`, only the owner's tool writes;
  * the publication boundary: no public-pipeline module can reach the record, and the source is owner-only.
Part B (dark): `coach.coach_context_pilot`, behind `LIVE = False`.
  * the switch ships off and, off, hands the worker its inputs back untouched;
  * on, the context runs in the owner's priority order, de-duplicates a dominant theme, raises ONE due
    follow-up for the lead only, once, and says what the coach can remember.
"""

# premerge-gate: sweeps the tracked tree (git ls-files) for writers of the recommendation record and for public-pipeline imports of it

from __future__ import annotations

import ast
import os
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
    coach_context_pilot as ccp,  # noqa: E402
    recommendation_record as rr,  # noqa: E402
)

import mcp.tools_coach_recommendations as tcr  # noqa: E402

PK = rr.pk("matthew")
TODAY = "2026-11-22"
GOOD = "Keep the session, but pull the compounds back to RPE 7 today and see how the warm-up feels."


# ── a small DynamoDB double that evaluates the real boto3 Key conditions ─────────────────────


class ConditionalCheckFailedException(Exception):
    pass


def _key_parts(cond) -> dict:
    out: dict = {}
    stack = [cond]
    while stack:
        expr = stack.pop().get_expression()
        op = expr["operator"]
        if op == "AND":
            stack.extend(expr["values"])
        elif op == "=":
            out["pk"] = expr["values"][1]
        elif op == "begins_with":
            out["prefix"] = expr["values"][1]
        elif op == "BETWEEN":
            out["between"] = (expr["values"][1], expr["values"][2])
    return out


class Table:
    def __init__(self, rows=()):
        self.store = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.puts: list = []

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.store:
            raise ConditionalCheckFailedException("exists")
        self.store[key] = dict(Item)
        self.puts.append(dict(Item))
        return {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        """Just enough of DynamoDB's update grammar for the correction close/reopen shapes."""
        key = (Key["pk"], Key["sk"])
        row = self.store.get(key)
        names, vals = ExpressionAttributeNames, ExpressionAttributeValues
        want = ConditionExpression.split("#s = ")[1].strip()
        if row is None or "attribute_exists(sk)" not in ConditionExpression or row.get("status") != vals[want]:
            raise ConditionalCheckFailedException("condition")
        set_part, _, remove_part = UpdateExpression.partition(" REMOVE ")
        for assign in [a.strip() for a in set_part.removeprefix("SET ").split(", ") if "=" in a]:
            field, expr = [x.strip() for x in assign.split("=", 1)]
            field = names.get(field, field)
            if expr.startswith("list_append"):
                row[field] = list(row.get(field) or []) + list(vals[":entry"])
            else:
                row[field] = vals[expr]
        for field in [f.strip() for f in remove_part.split(",") if f.strip()]:
            row.pop(field, None)
        self.puts.append({"update": dict(row)})
        return {}

    def query(self, **kw):
        parts = _key_parts(kw["KeyConditionExpression"])
        rows = [r for (p, s), r in self.store.items() if p == parts.get("pk")]
        if "prefix" in parts:
            rows = [r for r in rows if r["sk"].startswith(parts["prefix"])]
        if "between" in parts:
            lo, hi = parts["between"]
            rows = [r for r in rows if lo <= r["sk"] <= hi]
        rows.sort(key=lambda r: r["sk"], reverse=kw.get("ScanIndexForward") is False)
        if kw.get("Limit"):
            rows = rows[: kw["Limit"]]
        return {"Items": [dict(r) for r in rows]}


@pytest.fixture
def table(monkeypatch):
    t = Table(
        [
            {
                "pk": "USER#matthew#SOURCE#decisions",
                "sk": "DECISION#2026-11-08T18:00:00.000Z",
                "date": "2026-11-08",
                "decision": "Move training to mornings for the next 60 days",
            },
            {
                "pk": "USER#matthew#SOURCE#decisions",
                "sk": "DECISION#2026-11-21T18:00:00.000Z",
                "date": "2026-11-21",
                "decision": "Push the morning move to December",
                "note": "work travel first",
            },
            {"pk": "USER#matthew#SOURCE#coach_corrections", "sk": "CORRECTION#2026-11-20#abcd1234", "correction_text": "wrong anchor"},
        ]
    )
    monkeypatch.setattr(tcr, "_table_ref", t)
    monkeypatch.setattr(tcr, "_user_id_ref", "matthew")
    monkeypatch.setattr(tcr, "pacific_today", lambda: TODAY)
    return t


def _record(**kw):
    args = {"action": "record", "coach_id": "physical_coach", "channel": "telegram", "text": GOOD, "date": "2026-11-20"}
    args.update(kw)
    return tcr.tool_manage_coach_recommendation(args)


# ── Part A: the admission rule ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        GOOD,
        "Get to 170 g of protein a day this week — front-load it at breakfast.",
        "My call: walk 30 minutes after dinner each evening until Friday.",
        "I'd move the hard session to Thursday morning and keep Tuesday easy.",
    ],
)
def test_material_actionable_recommendations_are_admitted(text):
    verdict = rr.admit(text)
    assert verdict["admitted"], verdict["reasons"]


@pytest.mark.parametrize(
    "text, why",
    [
        ("Great job this week, keep it up!", "not actionable"),
        ("Nice work. You've got this, keep going.", "not actionable"),
        ("Protein. You're averaging 147 g against a 170 g floor.", "not actionable"),
        ("Try to be kind to yourself about the whole thing.", "not material"),
        ("Rest today.", "too short"),
    ],
)
def test_passing_suggestions_and_encouragement_are_refused_by_name(text, why):
    verdict = rr.admit(text)
    assert not verdict["admitted"] and any(why in r for r in verdict["reasons"]), verdict


def test_a_refused_recommendation_is_never_stored(table):
    res = _record(text="Great job this week, keep it up!")
    assert "not admitted" in str(res)
    assert not [p for p in table.puts if p["pk"] == PK]


# ── Part A: the record, the response, the follow-up, the outcome ────────────────────────────


def test_record_stores_the_exact_words_and_reads_not_recorded(table):
    res = _record(evidence=["recovery 56% on Nov 19"], context="he asked whether to train hard")
    assert res["status"] == "recorded" and res["response"] == "not recorded"
    head = table.store[(PK, rr.head_sk(res["rec_id"]))]
    assert head["text"] == GOOD and head["coach_id"] == "physical_coach" and head["channel"] == "telegram"
    assert head["window_start"] == "2026-11-20" and head["window_end"] == "2026-11-27"
    assert head["evidence"] == ["recovery 56% on Nov 19"] and head["recorded_by"] == "owner"
    assert _record()["status"] == "duplicate", "the same coach, day and words is one record"
    listed = tcr.tool_manage_coach_recommendation({"action": "list"})
    assert listed["count"] == 1 and listed["recommendations"][0]["response"] == rr.NOT_RECORDED


def test_record_refuses_an_unknown_coach_channel_or_decision(table):
    assert "error" in _record(coach_id="dr_who")
    assert "error" in _record(channel="carrier_pigeon")
    assert "error" in _record(decision_sk="DECISION#2020-01-01T00:00:00.000Z")


def test_respond_withdraw_and_replay(table):
    rid = _record()["rec_id"]
    res = tcr.tool_manage_coach_recommendation(
        {"action": "respond", "rec_id": rid, "response": "partially_followed", "words": "did the RPE 7 part"}
    )
    assert res["recommendation"]["response"] == "partially_followed"
    assert res["recommendation"]["response_words"] == "did the RPE 7 part"
    again = tcr.tool_manage_coach_recommendation(
        {"action": "respond", "rec_id": rid, "response": "partially_followed", "words": "did the RPE 7 part"}
    )
    assert again["status"] == "duplicate"
    back = tcr.tool_manage_coach_recommendation({"action": "respond", "rec_id": rid, "withdraw": True})
    assert back["recommendation"]["response"] == rr.NOT_RECORDED and back["recommendation"]["response_label"] == "not recorded"
    assert len(back["recommendation"]["history"]) == 2, "a withdrawal keeps the earlier answer in the history"
    assert "error" in tcr.tool_manage_coach_recommendation({"action": "respond", "rec_id": rid, "response": "acted_on"})


@pytest.mark.parametrize("answer", list(rr.RESPONSES))
def test_every_response_in_the_one_vocabulary_is_accepted(table, answer):
    rid = _record()["rec_id"]
    res = tcr.tool_manage_coach_recommendation({"action": "respond", "rec_id": rid, "response": answer})
    assert res["recommendation"]["response"] == answer


def test_follow_up_comes_due_and_an_outcome_closes_it(table):
    rid = _record()["rec_id"]
    assert "error" in tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-19"})
    tcr.tool_manage_coach_recommendation({"action": "respond", "rec_id": rid, "response": "accepted"})
    tcr.tool_manage_coach_recommendation({"action": "follow_up", "rec_id": rid, "follow_up_on": "2026-11-22"})
    due = tcr.tool_manage_coach_recommendation({"action": "list", "status": "due"})
    assert [v["rec_id"] for v in due["recommendations"]] == [rid]
    assert "error" in tcr.tool_manage_coach_recommendation({"action": "outcome", "rec_id": rid, "effectiveness": 4})
    tcr.tool_manage_coach_recommendation(
        {"action": "outcome", "rec_id": rid, "outcome_notes": "felt fine, top set moved", "effectiveness": 4}
    )
    closed = tcr.tool_manage_coach_recommendation({"action": "list", "status": "closed"})
    assert closed["recommendations"][0]["outcome"]["effectiveness"] == 4
    assert tcr.tool_manage_coach_recommendation({"action": "list", "status": "due"})["count"] == 0


def test_a_correction_link_must_name_a_real_ledger_row(table):
    rid = _record()["rec_id"]
    assert "error" in tcr.tool_manage_coach_recommendation({"action": "link_correction", "rec_id": rid, "correction_sk": "CORRECTION#nope"})
    res = tcr.tool_manage_coach_recommendation(
        {"action": "link_correction", "rec_id": rid, "correction_sk": "CORRECTION#2026-11-20#abcd1234"}
    )
    assert res["recommendation"]["corrections"] == ["CORRECTION#2026-11-20#abcd1234"]


def test_only_owner_events_count_and_a_bad_response_reads_not_recorded():
    head = rr.build_head(user_id="matthew", coach_id="eli_marsh", channel="claude_chat", text=GOOD, day="2026-11-20", recorded_at="t0")
    machine = dict(
        rr.build_event(user_id="matthew", rec=head, kind="response", recorded_at="t1", response="accepted"), recorded_by="daily_brief"
    )
    junk = dict(rr.build_event(user_id="matthew", rec=head, kind="response", recorded_at="t2", response="accepted"), response="followed")
    view = rr.fold([head, machine])[0]
    assert view["response"] == rr.NOT_RECORDED, "an event not recorded by the owner is not an answer"
    assert rr.fold([head, junk])[0]["response"] == rr.NOT_RECORDED


def test_the_tool_schema_enums_equal_the_registries():
    props = tcr.MANAGE_REC_INPUT["properties"]
    assert tuple(props["response"]["enum"]) == rr.RESPONSES
    assert tuple(props["channel"]["enum"]) == rr.CHANNELS
    assert tuple(props["action"]["enum"]) == tcr.ACTIONS
    assert tuple(props["status"]["enum"]) == tcr.LIST_STATUSES
    assert set(rr.RESPONSE_LABELS) == set(rr.RESPONSES) | {rr.NOT_RECORDED}


def test_the_seven_older_vocabularies_are_mapped_and_none_is_inferred():
    assert set(rr.VOCABULARY_MAP) == {"advice_link", "ask_response", "decision_followed", "commitment", "checkin", "insight", "correction"}
    for name in ("decision_followed", "commitment", "checkin", "insight", "correction"):
        assert set(rr.VOCABULARY_MAP[name]["terms"].values()) == {None}, f"{name} must never convert into an answer"
    for name in ("advice_link", "ask_response"):
        assert set(rr.VOCABULARY_MAP[name]["terms"].values()) <= set(rr.RESPONSES) | {rr.NOT_RECORDED}


def test_the_tool_is_registered_as_a_write_with_replay_semantics():
    from mcp_registry_ast import registered_tool_names

    from mcp import audit, idempotency

    assert "manage_coach_recommendation" in registered_tool_names((ROOT / "mcp" / "registry.py").read_text(encoding="utf-8"))
    assert audit.is_write_tool("manage_coach_recommendation")
    assert "manage_coach_recommendation" in idempotency.REPLAY_SEMANTICS


def test_the_source_is_owner_only_cross_phase_and_never_publishable():
    from experiment import phase_taxonomy
    from ingestion import source_registry
    from privacy import field_tiers

    assert field_tiers.SOURCE_TIERS[rr.SOURCE] == field_tiers.TIER_OWNER_ONLY
    assert not field_tiers.is_publishable(field_tiers.source_tier_of(rr.SOURCE))
    assert phase_taxonomy.SOURCE_CLASS[rr.SOURCE] == phase_taxonomy.CROSS_PHASE
    assert rr.SOURCE in source_registry.UNREGISTERED_PARTITIONS


# ── Part A: one writer, and the publication boundary (tree sweeps) ───────────────────────────


def _tracked_py() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out if not p.startswith("tests/") and (ROOT / p).exists()]


WRITER_MODULE = "mcp/tools_coach_recommendations.py"
#: Every module allowed to NAME the record (its source string or its module). A new reader is a decision made here.
ALLOWED_TO_NAME = frozenset(
    {
        "lambdas/coach/recommendation_record.py",  # the registry
        "lambdas/coach/coach_context_pilot.py",  # the pilot context (reads)
        WRITER_MODULE,  # the one writer
        "lambdas/coach/telegram_worker_lambda.py",  # imports the pilot seam (owner's private chat)
        "mcp/tools_coach_packet.py",  # imports the pilot seam (owner's MCP packet)
        "mcp/registry.py",  # registers the tool
        "lambdas/privacy/field_tiers.py",  # TIER_OWNER_ONLY
        "lambdas/experiment/phase_taxonomy.py",  # CROSS_PHASE
        "lambdas/ingestion/source_registry.py",  # UNREGISTERED_PARTITIONS
    }
)


#: Code that runs (the gate census's proof ledger in scripts/ names the test file, which is not a reader).
RUNTIME_TREES = ("lambdas/", "mcp/", "deploy/", "cdk/")


def _names_the_record(src: str) -> bool:
    return any(s in src for s in ("coach_recommendations", "recommendation_record", "coach_context_pilot"))


def test_only_the_owner_tool_constructs_or_writes_a_record():
    constructing, naming = set(), set()
    for rel in _tracked_py():
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if _names_the_record(src) and rel.startswith(RUNTIME_TREES):
            naming.add(rel)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            f = call.func
            if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)) in ("build_head", "build_event"):
                constructing.add(rel)
    assert constructing == {WRITER_MODULE}, f"record constructors outside the owner tool: {sorted(constructing)}"
    assert naming <= ALLOWED_TO_NAME, f"modules naming the recommendation record outside the allowlist: {sorted(naming - ALLOWED_TO_NAME)}"
    assert naming == ALLOWED_TO_NAME, f"an allowed module stopped naming the record (vacuous guard?): {sorted(ALLOWED_TO_NAME - naming)}"


def _import_graph(module_level_only: bool) -> dict[str, set[str]]:
    mods: dict[str, Path] = {}
    for p in (ROOT / "lambdas").rglob("*.py"):
        name = ".".join(p.relative_to(ROOT / "lambdas").with_suffix("").parts).removesuffix(".__init__")
        mods[name] = p
    for p in (ROOT / "mcp").rglob("*.py"):
        mods[".".join(p.relative_to(ROOT).with_suffix("").parts)] = p
    graph: dict[str, set[str]] = {}
    for name, p in mods.items():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        nodes = []
        if module_level_only:
            stack = list(tree.body)
            while stack:  # top level, including try/if blocks — never a function or class body
                n = stack.pop()
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                nodes.append(n)
                stack.extend(c for c in ast.iter_child_nodes(n) if isinstance(c, ast.stmt) or isinstance(c, ast.excepthandler))
        else:
            nodes = list(ast.walk(tree))
        deps = set()
        for n in nodes:
            if isinstance(n, ast.Import):
                deps |= {a.name for a in n.names if a.name in mods}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                deps |= {n.module} & set(mods) | {f"{n.module}.{a.name}" for a in n.names if f"{n.module}.{a.name}" in mods}
        graph[name] = deps
    return graph


def _closure(graph: dict[str, set[str]], roots: list[str], stop: frozenset = frozenset()) -> set[str]:
    seen, stack = set(roots), list(roots)
    while stack:
        for d in graph.get(stack.pop(), ()):
            if d not in seen and d not in stop:
                seen.add(d)
                stack.append(d)
    return seen


#: The public publishing pipeline: the site API, the content generators (chronicle, podcast, recap cards), and
#: the email lambdas (every reader-facing send lives there). The record must be unreachable from all of them.
PUBLIC_ROOT_PACKAGES = ("web.", "content.", "emails.")
RECORD_MODULES = frozenset({"coach.recommendation_record", "coach.coach_context_pilot", "mcp.tools_coach_recommendations"})
#: The Telegram worker is the owner's private chat lambda. `coach.telegram_group` imports it LAZILY, inside
#: `group_turn` only; `content.recap_deliver` imports telegram_group for `first_private_chat_id` and never calls the
#: group turn. That one lazy edge is cut here and the module-level closure below proves it is never loaded at import.
OWNER_CHAT_MODULE = "coach.telegram_worker_lambda"


def test_the_publication_boundary_cannot_reach_the_record():
    lazy = _import_graph(module_level_only=False)
    roots = [m for m in lazy if m.startswith(PUBLIC_ROOT_PACKAGES)]
    assert len(roots) > 50, "the public roots were not found — vacuous guard"
    reached = _closure(lazy, roots, stop=frozenset({OWNER_CHAT_MODULE}))
    assert not reached & RECORD_MODULES, f"a public-pipeline module can import the record: {sorted(reached & RECORD_MODULES)}"
    eager = _closure(_import_graph(module_level_only=True), roots)
    assert OWNER_CHAT_MODULE not in eager, "a public module loads the Telegram worker at import time"
    assert not eager & RECORD_MODULES


def test_the_boundary_sweep_can_fail(tmp_path, monkeypatch):
    """Mutation proof: a public module that imports the record is caught by the same closure."""
    graph = _import_graph(module_level_only=False)
    graph["web.site_api_fake"] = {"coach.recommendation_record"}
    assert _closure(graph, ["web.site_api_fake"]) & RECORD_MODULES


def test_the_writer_sweep_can_fail():
    tree = ast.parse("def f():\n    rr.build_event(user_id='u', rec={}, kind='response', recorded_at='t')\n")
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "build_event"]
    assert hits


# ── Part B: the switch ────────────────────────────────────────────────────────────────────


def test_the_switch_ships_off():
    assert ccp.LIVE is False


def test_off_the_worker_gets_its_inputs_back_untouched_and_no_table_is_built():
    thread = [{"role": "matthew", "text": "hi"}]

    def boom():
        raise AssertionError("no table may be built while the pilot is dark")

    memory, out_thread, extra = ccp.for_turn(boom, "eli_marsh", "MEM", thread)
    assert memory == "MEM" and out_thread is thread and extra == {}
    assert ccp.packet_context(boom, TODAY) is None


def test_on_a_failure_degrades_to_the_production_context():
    memory, thread, extra = ccp.for_turn(lambda: 1 / 0, "eli_marsh", "MEM", [], live=True)
    assert (memory, thread, extra) == ("MEM", [], {})


# ── Part B: the context ───────────────────────────────────────────────────────────────────


def _seed_rec(t: Table, *, coach="eli_marsh", follow_up_on=None, response=None, text=GOOD, day="2026-11-18"):
    head = rr.build_head(user_id="matthew", coach_id=coach, channel="claude_chat", text=text, day=day, recorded_at=f"{day}T10:00:00.000Z")
    t.put_item(Item=head)
    if response:
        t.put_item(Item=rr.build_event(user_id="matthew", rec=head, kind="response", recorded_at=f"{day}T11:00:00.000Z", response=response))
    if follow_up_on:
        t.put_item(
            Item=rr.build_event(
                user_id="matthew", rec=head, kind="follow_up", recorded_at=f"{day}T12:00:00.000Z", follow_up_on=follow_up_on
            )
        )
    return head["rec_id"]


@pytest.fixture
def pilot_table(table, monkeypatch):
    monkeypatch.setattr(ccp, "planned_session", lambda day: {"state": "measured", "label": "Lower — week 3 · session 1 of 3, block 1"})
    monkeypatch.setattr(
        "ai.platform_memory._query_conversation_records",
        lambda t: [
            {
                "sk": "MEMORY#life_context#2026-11-15#aa",
                "category": "life_context",
                "date": "2026-11-15",
                "channel": "conversation",
                "summary": "Travelling for work the first week of December",
            }
        ],
    )
    return table


def _memory_with_corrections(notes: str) -> str:
    from coach.coach_corrections import CHAT_CORRECTIONS_HEADER

    return f"{notes}\n\n{CHAT_CORRECTIONS_HEADER}\n- [2026-11-09] do not assume a diet-only cut"


def test_the_context_runs_in_the_owner_priority_order(pilot_table):
    _seed_rec(pilot_table, response="not_yet_decided")
    ctx = ccp.build_turn_context(
        pilot_table,
        "eli_marsh",
        TODAY,
        memory=_memory_with_corrections("RECENT CONVERSATIONS:\n- [2026-11-01] talked about sleep."),
        thread=[],
    )
    m = ctx["memory"]
    order = [
        m.index(h)
        for h in (
            ccp.PRIORITIES_HEADER[:20],
            ccp.SESSION_HEADER,
            ccp.RECS_HEADER[:20],
            ccp.NOTES_HEADER[:20],
            "THINGS MATTHEW HAS ALREADY CORRECTED",
            ccp.CAPABILITY[:20],
        )
    ]
    assert order == sorted(order), order
    assert m.index("Push the morning move to December") < m.index("Move training to mornings"), "newest decision first"
    assert "(shared in confidence)" in m, "platform memory keeps its confidence marker"
    assert "Lower — week 3" in m and "his answer: still deciding" in m
    assert "Never tell him you have no memory" in m and ccp.LEAD_LINE in m


def test_the_planned_session_is_for_the_lead_and_performance_seat_only(pilot_table, monkeypatch):
    assert ccp.SESSION_HEADER in ccp.build_turn_context(pilot_table, "physical_coach", TODAY)["memory"]
    assert ccp.SESSION_HEADER not in ccp.build_turn_context(pilot_table, "nutrition_coach", TODAY)["memory"]

    def broken(day):
        raise RuntimeError("hevy down")

    monkeypatch.setattr(ccp, "planned_session", broken)
    assert "not available" in ccp.build_turn_context(pilot_table, "eli_marsh", TODAY)["memory"]


def test_a_dominant_theme_is_carried_at_most_twice_and_his_words_are_kept():
    protein = "Protein is averaging 147 g over 26 logged days against the 170 g floor."
    thread = []
    for i in range(7):
        thread += [{"role": "matthew", "text": f"question {i} about my week"}, {"role": "coach", "text": protein}]
    notes = (
        "RECENT CONVERSATIONS (your own compressed notes from earlier days):\n- [2026-10-01] Protein at 147 g, floor 170 g. He travelled."
    )
    new_notes, new_thread, removed = ccp.dedupe(notes, thread)
    kept = [t for t in new_thread if t["role"] == "coach" and t["text"] == protein]
    assert len(kept) == 2 and new_thread[-1]["text"] == protein, "the newest two repeats survive"
    assert [t["text"] for t in new_thread if t["role"] == "matthew"] == [t["text"] for t in thread if t["role"] == "matthew"]
    assert len(new_thread) == len(thread), "a left-out reply keeps its place, so the turn order he saw is kept"
    assert "He travelled." in new_notes and "Protein at 147 g" not in new_notes
    assert removed == {"replies_left_out": 5, "note_segments_left_out": 1}


def test_a_thread_with_no_dominant_theme_is_untouched():
    thread = [
        {"role": "matthew", "text": "sleep?"},
        {"role": "coach", "text": "Slept 7.1 hours."},
        {"role": "matthew", "text": "lift?"},
        {"role": "coach", "text": "Squat day tomorrow."},
    ]
    notes, new_thread, removed = ccp.dedupe("", thread)
    assert new_thread == thread and removed["replies_left_out"] == 0


def test_a_due_follow_up_is_raised_by_the_lead_once(pilot_table):
    rid = _seed_rec(pilot_table, response="accepted", follow_up_on="2026-11-21")
    lead = ccp.build_turn_context(pilot_table, "eli_marsh", TODAY)
    assert lead["record_extra"] == {ccp.FOLLOW_UP_FIELD: rid} and "FOLLOW-UP DUE" in lead["memory"]
    spec = ccp.build_turn_context(pilot_table, "physical_coach", TODAY)
    assert spec["record_extra"] == {} and "FOLLOW-UP DUE" not in spec["memory"]
    pilot_table.put_item(
        Item={
            "pk": "COACH#eli_marsh",
            "sk": "CHAT#2026-11-22#abc12345",
            "role": "coach",
            "text": "how did it go?",
            ccp.FOLLOW_UP_FIELD: rid,
        }
    )
    again = ccp.build_turn_context(pilot_table, "eli_marsh", TODAY)
    assert again["record_extra"] == {} and "FOLLOW-UP DUE" not in again["memory"], "asked once"


def test_a_specialist_sees_its_own_open_recommendations_only(pilot_table):
    _seed_rec(pilot_table, coach="nutrition_coach", text="Front-load 40 g of protein at breakfast every day this week.")
    _seed_rec(pilot_table, coach="sleep_coach", text="Get lights out by 22:30 every weeknight until Friday.")
    m = ccp.build_turn_context(pilot_table, "nutrition_coach", TODAY)["memory"]
    assert "Front-load 40 g" in m and "lights out" not in m
    lead = ccp.build_turn_context(pilot_table, "eli_marsh", TODAY)["memory"]
    assert "Front-load 40 g" in lead and "lights out" in lead


def test_the_packet_context_carries_priorities_recommendations_and_the_due_follow_up(pilot_table):
    rid = _seed_rec(pilot_table, follow_up_on="2026-11-20")
    ctx = ccp.packet_context(pilot_table, TODAY, live=True)
    assert ctx["state"] == "measured" and ctx["priorities"][0]["decision"] == "Push the morning move to December"
    assert ctx["follow_up_due"]["rec_id"] == rid and ctx["recommendations"][0]["response"] == rr.NOT_RECORDED
    assert "(shared in confidence)" in ctx["told_in_chat"]


# ── Part B: the worker seam ───────────────────────────────────────────────────────────────


class TestWorkerSeam:
    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch):
        from coach import coach_chat, telegram_worker_lambda as worker

        self.worker, self.cc, self.stored = worker, coach_chat, []
        monkeypatch.setattr(worker, "_bot_token", lambda key: "tok")
        monkeypatch.setattr(worker, "_tg", lambda token, method, payload: True)
        monkeypatch.setattr(worker, "_thread_today", lambda cid, limit=40: [])
        monkeypatch.setattr(worker, "_memory_block", lambda cid: "PRODUCTION MEMORY")
        monkeypatch.setattr(worker, "_facts", dict)
        monkeypatch.setattr(worker, "_current_tier", lambda: 0)
        monkeypatch.setattr(worker, "_s3_client", lambda: None)
        monkeypatch.setattr(worker, "_emit_metric", lambda name, cid: None)
        monkeypatch.setattr(worker, "_cycle", lambda: None)

        class T:
            put_item = staticmethod(lambda Item: self.stored.append(Item))

        monkeypatch.setattr(worker, "_table", lambda: T())
        self.seen = {}

        def run_turn(**kw):
            self.seen.update(kw)
            return coach_chat.TurnResult("Fair. How did the RPE 7 session go?", "sent", [], 1)

        monkeypatch.setattr(worker.coach_chat, "run_turn", run_turn)

    def _turn(self):
        return self.worker.lambda_handler({"coach_id": "nutrition", "chat_id": 8675309, "text": "protein?"}, None)

    def test_dark_the_turn_is_production_exactly(self):
        self._turn()
        assert self.seen["memory_block"] == "PRODUCTION MEMORY"
        coach_row = [i for i in self.stored if i.get("role") == "coach"][0]
        assert ccp.FOLLOW_UP_FIELD not in coach_row

    def test_live_the_pilot_context_is_used_and_the_raised_follow_up_rides_the_reply_row(self, monkeypatch):
        monkeypatch.setattr(ccp, "LIVE", True)
        monkeypatch.setattr(
            ccp,
            "build_turn_context",
            lambda table, pid, day, memory="", thread=None: {
                "memory": "PILOT MEMORY",
                "thread": [],
                "record_extra": {ccp.FOLLOW_UP_FIELD: "rec_x"},
            },
        )
        self._turn()
        assert self.seen["memory_block"] == "PILOT MEMORY"
        coach_row = [i for i in self.stored if i.get("role") == "coach"][0]
        assert coach_row[ccp.FOLLOW_UP_FIELD] == "rec_x" and coach_row["text"].startswith("Fair.")
        assert ccp.FOLLOW_UP_FIELD not in [i for i in self.stored if i.get("role") == "matthew"][0]


# ── owner ruling §11: closing a correction (driver addition to #6158) ──────────────────────────


CSK = "CORRECTION#2026-11-20#abcd1234"


def _ledger_row(t: Table) -> dict:
    return t.store[("USER#matthew#SOURCE#coach_corrections", CSK)]


@pytest.fixture
def ledger(table, monkeypatch):
    import mcp.tools_coach_corrections as tcc

    row = _ledger_row(table)
    row.update(
        {"status": "open", "created_at": "2026-11-20T12:00:00+00:00", "error_class": "other", "item_ref": {"surface": "chat_coaching"}}
    )
    monkeypatch.setattr(tcc, "_table_ref", table)
    return tcc


def test_a_close_needs_a_disposition_and_checkable_evidence(ledger, table):
    from coach import coach_corrections as cc

    for bad in ({"disposition": "obsolete", "evidence": "#4408"}, {"disposition": "fixed", "evidence": ""}):
        res = ledger.tool_log_coach_correction({"action": "close", "sk": CSK, **bad})
        assert "error" in res
    assert _ledger_row(table)["status"] == "open"
    with pytest.raises(cc.CorrectionCloseError):
        cc.close_correction(table, CSK, disposition="fixed", evidence="#4408", closed_by="")


@pytest.mark.parametrize("age_only", ["older than 90 days", "stale, logged months ago", "no longer relevant because it is old"])
def test_age_alone_cannot_close_a_correction(ledger, table, age_only):
    res = ledger.tool_log_coach_correction({"action": "close", "sk": CSK, "disposition": "no_longer_applicable", "evidence": age_only})
    assert "error" in res and "never closed because it is old" in res["error"]
    assert _ledger_row(table)["status"] == "open"


def test_close_keeps_the_original_text_and_dates_and_appends_the_audit(ledger, table):
    before = dict(_ledger_row(table))
    res = ledger.tool_log_coach_correction({"action": "close", "sk": CSK, "disposition": "fixed", "evidence": "#4408, PR #4417"})
    assert res["status"] == "closed"
    row = _ledger_row(table)
    for field in ("correction_text", "created_at", "error_class", "item_ref", "sk"):
        assert row[field] == before[field], f"closing altered {field}"
    assert row["status"] == "closed" and row["disposition"] == "fixed" and row["disposition_evidence"] == "#4408, PR #4417"
    assert row["closed_at"] and row["closed_by"] and row["status_history"][0]["action"] == "close"
    again = ledger.tool_log_coach_correction({"action": "close", "sk": CSK, "disposition": "fixed", "evidence": "#4408"})
    assert "error" in again and len(_ledger_row(table)["status_history"]) == 1, "a replayed close writes nothing"


def test_a_closed_row_leaves_prompts_and_open_counts_but_stays_readable(ledger, table):
    from coach import coach_corrections as cc

    assert [r["sk"] for r in cc.list_corrections(table, status="open")] == [CSK]
    ledger.tool_log_coach_correction({"action": "close", "sk": CSK, "disposition": "superseded", "evidence": "superseded by #5069"})
    assert cc.list_corrections(table, status="open") == []
    assert cc.open_corrections_for(table, surface="chat_coaching", current_cycle=17) == []
    assert cc.never_injected(table, current_cycle=17) == []
    listed = ledger.tool_log_coach_correction({"action": "list", "status": "closed"})
    assert listed["count"] == 1 and listed["corrections"][0]["disposition"] == "superseded"
    rid = _record()["rec_id"]
    tcr.tool_manage_coach_recommendation({"action": "link_correction", "rec_id": rid, "correction_sk": CSK})
    hist = tcr.tool_manage_coach_recommendation({"action": "list", "rec_id": rid})["recommendations"][0]["correction_history"]
    assert hist == [
        {
            "sk": CSK,
            "status": "closed",
            "error_class": "other",
            "created_at": "2026-11-20T12:00:00+00:00",
            "disposition": "superseded",
            "disposition_evidence": "superseded by #5069",
            "closed_at": hist[0]["closed_at"],
        }
    ]


def test_reopen_needs_a_reason_and_keeps_the_closure_in_history(ledger, table):
    ledger.tool_log_coach_correction({"action": "close", "sk": CSK, "disposition": "fixed", "evidence": "#4408"})
    assert "error" in ledger.tool_log_coach_correction({"action": "reopen", "sk": CSK})
    res = ledger.tool_log_coach_correction({"action": "reopen", "sk": CSK, "reason": "it recurred on 2026-11-23"})
    assert res["status"] == "reopened"
    row = _ledger_row(table)
    assert row["status"] == "open" and "disposition" not in row and "closed_at" not in row
    assert [h["action"] for h in row["status_history"]] == ["close", "reopen"] and row["status_history"][0]["disposition"] == "fixed"
    assert "error" in ledger.tool_log_coach_correction({"action": "reopen", "sk": CSK, "reason": "again"}), "only a closed row reopens"


def test_nothing_closes_a_correction_but_the_owner_door():
    """No code path closes a correction by age or on a schedule: the close function has one caller."""
    callers = set()
    for rel in _tracked_py():
        src = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if "close_correction(" in src or "reopen_correction(" in src:
            callers.add(rel)
    assert callers == {"lambdas/coach/coach_corrections.py", "mcp/tools_coach_corrections.py"}, sorted(callers)
