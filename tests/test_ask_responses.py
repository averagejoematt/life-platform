"""tests/test_ask_responses.py — Matthew's structured answers to coach asks, and the privacy boundary (owner 2026-11-12).

The owner's rules, each held below on the real path (tool args -> revision rows -> public reader -> /api/coach/<id>
dossier rows -> the CR2 snapshot data file):
  * private states: acted on / declined / partly followed / not yet decided; an optional private note;
  * edits and withdrawals are NEW revision rows (conditional put, never an overwrite) with a private history;
  * the public page gets ONLY {ask_id, state, responded_on, self_reported: true} for an answered ask — never the note,
    the decision pointer or the history; `not_yet_decided` reads "not recorded" publicly (the conservative choice);
  * a missing answer is NEVER "declined"; a withdrawal returns the ask to "not recorded";
  * no behaviour-data inference path: the reader reads the revisions and nothing else.
The free-text boundary is proven with a planted SENTINEL and a must-fail control (the same detector fires on a leaky
projection). The one-writer AST sweep for the family is tests/test_advice_links_5612.py.
"""

from __future__ import annotations

import ast
import json
import os
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
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import publish_snapshot_coach_room as P  # noqa: E402
from coach import advice_links as al, ask_outcomes  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach_profile as profile  # noqa: E402

import mcp.tools_advice_links as tal  # noqa: E402
import mcp.tools_advice_queue as taq  # noqa: E402

PK = "USER#matthew#SOURCE#decisions"
DEC = "DECISION#2026-11-10T18:00:00.000Z"
ASK = "commit_20261102_lights_out_by_22_30_on_weeknights"
ASK2 = "commit_20261104_ten_minute_walk_after_dinner"
COACH = "sleep_coach"
#: A planted string in every private field. It must reach no public payload; the controls prove the detector sees it.
SENTINEL = "SENTINEL-PRIVATE-7f3a9c"
PUBLIC_KEYS = {"ask_id", "state", "responded_on", "self_reported"}


def _key_parts(cond):
    pk = prefix = None
    stack = [cond]
    while stack:
        expr = stack.pop().get_expression()
        if expr["operator"] == "AND":
            stack.extend(expr["values"])
        elif expr["operator"] == "=":
            pk = expr["values"][1]
        elif expr["operator"] == "begins_with":
            prefix = expr["values"][1]
    return pk, prefix


def _query_hook(table, **kwargs):
    pk, prefix = _key_parts(kwargs["KeyConditionExpression"])
    rows = [r for (p, s), r in table.store.items() if p == pk and (prefix is None or s.startswith(prefix))]
    return {"Items": sorted(rows, key=lambda r: r["sk"])}


def _put_hook(table, item, **kwargs):
    """Emulate the conditional put: a revision may never land on an existing key."""
    if kwargs.get("ConditionExpression") == "attribute_not_exists(sk)" and (item["pk"], item["sk"]) in table.store:
        raise AssertionError("ConditionalCheckFailed: a revision would have overwritten a row")
    table.store[(item["pk"], item["sk"])] = item


def _table(*extra):
    rows = [
        {"pk": PK, "sk": DEC, "date": "2026-11-10", "decision": "Lights out early", "source": "mcp"},
        {"pk": f"COACH#{COACH}", "sk": f"COMMITMENT#{ASK}", "commitment_id": ASK, "status": "kept", "commitment_natural": "x"},
        {"pk": f"COACH#{COACH}", "sk": f"COMMITMENT#{ASK2}", "commitment_id": ASK2, "status": "kept", "commitment_natural": "y"},
        *extra,
    ]
    return FakeDdbTable(rows=rows, query_hook=_query_hook, put_item_hook=_put_hook)


class _Clock:
    """Strictly increasing instants, so every revision has its own key (as real wall-clock calls do)."""

    def __init__(self, start="2026-11-14T18:00:00.000Z"):
        self.n = 0
        self.base = start[:-7]

    def __call__(self):
        self.n += 1
        return f"{self.base}{self.n:02d}.000Z"


@pytest.fixture
def table(monkeypatch):
    t = _table()
    monkeypatch.setattr(tal, "_table_ref", t)
    monkeypatch.setattr(tal, "_now_iso", _Clock())
    return t


def _answer(**over):
    args = {"ref_kind": "commitment", "ref_id": ASK, "coach_id": COACH, "state": "acted_on"}
    args.update(over)
    return {k: v for k, v in args.items() if v is not None}


def _revisions(t):
    return sorted((r for (p, s), r in t.store.items() if s.startswith(al.ASK_RESPONSE_SK_PREFIX)), key=lambda r: r["sk"])


def _public(t, coach=COACH):
    return ask_outcomes.public_outcomes(t, "matthew", coach)


# ── private input: states, note, edit, withdraw, owner-only ──────────────────────────────────────────


def test_every_private_state_is_accepted_with_or_without_a_note(table):
    for i, state in enumerate(al.ASK_RESPONSE_STATES):
        res = tal.tool_log_advice_link(_answer(state=state, evidence_text=None if i % 2 else f"{SENTINEL} because"))
        assert res["written"] is True and res["state"] == state, res
    assert [r["state"] for r in _revisions(table)] == list(al.ASK_RESPONSE_STATES)
    assert all(r["recorded_by"] == "owner" and r["kind"] == "ask_response" for r in _revisions(table))


def test_an_edit_and_a_withdrawal_append_revisions_and_never_overwrite(table):
    first = tal.tool_log_advice_link(_answer(state="declined", evidence_text=f"{SENTINEL} not this week", decision_sk=DEC))
    edit = tal.tool_log_advice_link(_answer(state="partially_followed", evidence_text="two nights of five"))
    gone = tal.tool_log_advice_link(_answer(state=None, withdraw=True))
    assert (first["status"], edit["status"], gone["status"]) == ("answered", "edited", "withdrawn")
    revs = _revisions(table)
    assert [r["state"] for r in revs] == ["declined", "partially_followed", "withdrawn"]
    assert [r["revision"] for r in revs] == [1, 2, 3]
    assert revs[1]["supersedes"] == revs[0]["sk"] and revs[2]["supersedes"] == revs[1]["sk"]
    # the first answer is still there, untouched — history is rows, not a rewritten field
    assert revs[0]["note"] == f"{SENTINEL} not this week" and revs[0]["decision_sk"] == DEC
    assert all(p.get("pk") == PK for p in table.puts) and len(table.puts) == 3
    # the owner sees the whole history on the call (private, MCP only)
    assert [h["state"] for h in gone["history"]] == ["declined", "partially_followed", "withdrawn"]
    assert gone["history"][0]["note"] == f"{SENTINEL} not this week"
    # and a re-answer after a withdrawal is a fourth revision
    again = tal.tool_log_advice_link(_answer(state="acted_on"))
    assert again["status"] == "answered" and again["revision"] == 4


def test_the_put_is_conditional_so_a_collision_cannot_overwrite(table, monkeypatch):
    monkeypatch.setattr(tal, "_now_iso", lambda: "2026-11-14T18:00:00.000Z")
    tal.tool_log_advice_link(_answer(state="acted_on"))
    with pytest.raises(AssertionError, match="ConditionalCheckFailed"):
        tal.tool_log_advice_link(_answer(state="declined"))  # same instant, same key: refused, not overwritten
    assert [r["state"] for r in _revisions(table)] == ["acted_on"]


def test_a_replay_and_an_empty_withdrawal_write_nothing(table):
    tal.tool_log_advice_link(_answer(state="acted_on", evidence_text="did it"))
    assert tal.tool_log_advice_link(_answer(state="acted_on", evidence_text="did it"))["status"] == "unchanged"
    assert tal.tool_log_advice_link(_answer(ref_id=ASK2, state=None, withdraw=True))["status"] == "nothing_to_withdraw"
    assert len(table.puts) == 1


_REFUSALS = [
    ({"state": "unknown"}, "not an answer"),
    ({"state": "followed"}, "state must be one of"),
    ({"state": None}, "state must be one of"),
    ({"withdraw": True}, "withdraw takes no state"),
    ({"recorded_by": "sleep_coach"}, "owner only"),
    ({"evidence_ref": "hevy workout 2026-11-03"}, "evidence_ref is for decision links"),
    ({"coach_id": "dr_nobody"}, "coach_id"),
    ({"ref_id": "pred_20261102_x"}, "ref_id"),
    ({"ref_id": "commit_20261102_never_asked"}, "no current-cycle commitment"),
    ({"coach_id": "nutrition_coach"}, "no current-cycle commitment"),  # the ask is the sleep coach's
    ({"decision_sk": "DECISION#2020-01-01T00:00:00.000Z"}, "no current-cycle decision"),
    ({"decision_sk": "INSIGHT#2026"}, "DECISION#"),
]


def test_the_write_refuses_what_the_rules_forbid(table):
    misses = []
    for over, fragment in _REFUSALS:
        res = tal.tool_log_advice_link(_answer(**over))
        if res.get("written") is not False or fragment not in res.get("error", ""):
            misses.append((over, res))
    assert misses == []
    assert _revisions(table) == []


def test_a_wiped_cycles_ask_cannot_be_answered(monkeypatch):
    t = _table({"pk": f"COACH#{COACH}", "sk": "COMMITMENT#commit_20260901_old", "tombstone": True, "phase": "pilot"})
    monkeypatch.setattr(tal, "_table_ref", t)
    res = tal.tool_log_advice_link(_answer(ref_id="commit_20260901_old"))
    assert res["written"] is False and "no current-cycle commitment" in res["error"]


# ── the public projection ────────────────────────────────────────────────────────────────────────────


def test_the_public_shape_is_exactly_four_keys_and_the_day_is_pacific(table):
    tal.tool_log_advice_link(_answer(state="acted_on", evidence_text=SENTINEL, decision_sk=DEC))
    out = _public(table)
    # 18:00Z on 14 Nov is 10:00 PT on 14 Nov; the day a reader sees is the Pacific day of the newest revision
    assert out == {ASK: {"ask_id": ASK, "state": "acted_on", "responded_on": "2026-11-14", "self_reported": True}}
    late = _table(
        {
            **al.build_ask_response(
                user_id="matthew",
                coach_id=COACH,
                ask_id=ASK,
                state="declined",
                withdraw=False,
                note=None,
                decision_sk=None,
                recorded_at="2026-11-15T05:30:00.000Z",
                revision=1,
                supersedes=None,
            )
        }
    )
    assert _public(late)[ASK]["responded_on"] == "2026-11-14", "05:30Z is the evening before in Pacific time"


def test_a_missing_answer_is_never_declined(table):
    """No revision -> no public outcome at all: absent, so the page reads 'not recorded' (never 'declined')."""
    assert _public(table) == {}
    tal.tool_log_advice_link(_answer(state="acted_on"))
    out = _public(table)
    assert set(out) == {ASK} and ASK2 not in out, "the unanswered ask stays absent"
    assert all(v["state"] != "declined" for v in out.values())


def test_not_yet_decided_is_private_and_reads_not_recorded(table):
    tal.tool_log_advice_link(_answer(state="not_yet_decided", evidence_text=SENTINEL))
    assert _public(table) == {}
    assert "not_yet_decided" not in al.PUBLIC_ASK_STATES
    assert (
        taq.rank_asks(
            [{"coach_id": COACH, "ask_id": ASK, "asked_on": "", "due": "2026-11-09"}],
            [],
            [],
            [],
            ask_outcomes.owner_answers(table, "matthew", [COACH]),
        )[0]["your_answer"]["state"]
        == "not_yet_decided"
    )


def test_a_withdrawal_reverts_to_not_recorded_and_an_edit_publishes_only_the_newest(table):
    tal.tool_log_advice_link(_answer(state="declined"))
    assert _public(table)[ASK]["state"] == "declined"
    tal.tool_log_advice_link(_answer(state="acted_on"))
    assert _public(table)[ASK]["state"] == "acted_on", "an edit publishes the newest answer, never the history"
    tal.tool_log_advice_link(_answer(state=None, withdraw=True))
    assert _public(table) == {}, "a withdrawal returns the ask to 'not recorded'"
    assert [r["state"] for r in _revisions(table)] == ["declined", "acted_on", "withdrawn"], "the history is kept, privately"


def test_a_bad_or_wiped_newest_revision_publishes_nothing():
    good = al.build_ask_response(
        user_id="matthew",
        coach_id=COACH,
        ask_id=ASK,
        state="acted_on",
        withdraw=False,
        note=None,
        decision_sk=None,
        recorded_at="2026-11-14T18:00:00.000Z",
        revision=1,
        supersedes=None,
    )
    assert _public(_table(good))[ASK]["state"] == "acted_on"
    forged = {
        **good,
        "sk": al.ask_response_sk(COACH, ASK, "2026-11-14T19:00:00.000Z"),
        "recorded_at": "2026-11-14T19:00:00.000Z",
        "recorded_by": "sleep_coach",
    }
    assert _public(_table(good, forged)) == {}, "a newest row that breaks a rule publishes nothing (never falls back)"
    wiped = {**good, "phase": "pilot"}
    assert _public(_table(wiped)) == {}, "a wiped cycle's answer is not an answer"


def test_a_failed_read_publishes_nothing():
    class Boom:
        def query(self, **_k):
            raise RuntimeError("throttled")

    assert ask_outcomes.public_outcomes(Boom(), "matthew", COACH) == {}


# ── the privacy boundary: free text never reaches a public payload (SENTINEL + must-fail control) ─────


def _api_rows(t):
    """The /api/coach/<id> dossier's ask rows, as `_dossier_block` finishes them."""
    commitments = [
        {"kind": "commitment", "record_id": f"COMMITMENT#{a}", "date": "2026-11-02", "text": "", "status": "kept", "due_date": "2026-11-09"}
        for a in (ASK, ASK2)
    ]
    return profile._with_what_matt_did(commitments, COACH, t)


def _data_file(rows):
    payload = {"persona_id": COACH, "dossier": {"commitments": rows, "commitment_counts": {"held": 2, "kept": 2}}}
    entry = P.shape_coach(payload)
    room = {"state": "ok", "coaches": {COACH: entry}}
    return P.resolve_and_validate(room, {"coach": [{"id": COACH}]}, cr3=False)


def test_the_sentinel_never_reaches_the_api_rows_or_the_data_file(table):
    tal.tool_log_advice_link(_answer(state="declined", evidence_text=f"{SENTINEL} first", decision_sk=DEC))
    tal.tool_log_advice_link(_answer(state="acted_on", evidence_text=f"{SENTINEL} edited"))
    tal.tool_log_advice_link(_answer(ref_id=ASK2, state="not_yet_decided", evidence_text=f"{SENTINEL} unsure"))
    assert any(SENTINEL in json.dumps(r) for r in _revisions(table)), "the sentinel is planted in the private rows"

    rows = _api_rows(table)
    api = json.dumps(rows)
    assert SENTINEL not in api and DEC not in api and "supersedes" not in api and "history" not in api
    assert rows[0]["what_matt_did"] == {"ask_id": ASK, "state": "acted_on", "responded_on": "2026-11-14", "self_reported": True}
    assert "what_matt_did" not in rows[1], "not yet decided: nothing public"

    data = _data_file(rows)
    text = json.dumps(data)
    assert SENTINEL not in text and ASK not in text, "neither the note nor the id-slug is carried"
    did = [r["did"] for r in data["coaches"][COACH]["asks"]["rows"]]
    assert did == [{"state": "acted_on", "responded_on": "2026-11-14", "self_reported": True}, None]


def test_control_the_detector_fires_on_a_leaky_projection(table, monkeypatch):
    """MUST-FAIL: a projection that hands over the raw revision carries the sentinel into the API rows — so the
    clean result above is the projection working, not a detector that cannot see — and the publisher's strict
    `did` voids the leak before the data file (its own belt), and refuses a hand-built file that carries one."""
    tal.tool_log_advice_link(_answer(state="acted_on", evidence_text=SENTINEL))
    raw = {r["ask_id"]: r for r in _revisions(table)}
    monkeypatch.setattr(profile.ask_outcomes, "public_outcomes", lambda *_a: raw)
    rows = _api_rows(table)
    assert SENTINEL in json.dumps(rows), "the detector sees a leak when there is one"
    data = _data_file(rows)
    assert SENTINEL not in json.dumps(data) and data["coaches"][COACH]["asks"]["rows"][0]["did"] is None
    leaky = {"state": "ok", "coaches": {COACH: {**data["coaches"][COACH]}}}
    leaky["coaches"][COACH]["asks"] = {
        **data["coaches"][COACH]["asks"],
        "rows": [{"did": {"state": "acted_on", "responded_on": "2026-11-14", "self_reported": True, "note": SENTINEL}}],
    }
    with pytest.raises(ValueError, match="did must be exactly"):
        P.resolve_and_validate(leaky, {"coach": [{"id": COACH}]}, cr3=False)


def test_the_publisher_voids_every_malformed_answer():
    ok = {"ask_id": ASK, "state": "acted_on", "responded_on": "2026-11-14", "self_reported": True}
    assert P._did(ok) == {"state": "acted_on", "responded_on": "2026-11-14", "self_reported": True}
    for bad in (
        {**ok, "note": SENTINEL},
        {**ok, "self_reported": False},
        {**ok, "self_reported": "true"},
        {**ok, "responded_on": "2026-11-14T18:00:00Z"},
        {**ok, "responded_on": None},
        {**ok, "state": f"acted on {SENTINEL}"},
        {**ok, "state": None},
        "acted_on",
        None,
    ):
        assert P._did(bad) is None, bad


# ── no behaviour-data inference path ────────────────────────────────────────────────────────────────


_BEHAVIOUR = (
    "hevy",
    "macrofactor",
    "withings",
    "habitify",
    "whoop",
    "strava",
    "garmin",
    "apple_health",
    "computed_metrics",
    "grader",
    '"outcome"',  # the grader's verdict field on an ask row
    '"status"',
    "COMMITMENT#",  # the ask row itself (its grader status) is never read here
    "query_source",
    "DATE#",
)


def test_the_reader_reads_only_the_revisions():
    src = (ROOT / "lambdas/coach/ask_outcomes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    code = "\n".join(
        ast.get_source_segment(src, n) or "" for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    )
    assert [w for w in _BEHAVIOUR if w in code] == [], "the reader names a behaviour source"
    calls = {c.func.attr for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert not calls & {"put_item", "update_item", "delete_item", "batch_writer", "get_item", "scan"}, calls
    queries = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "query"]
    assert len(queries) == 1, "one query: the ask-response revisions"
    assert "ask_response_pk(user_id)" in code and ".begins_with(prefix)" in code
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert imports <= {"annotations", "pacific_date_of", "singleton_visible", "advice_links", "Key"}, imports


def test_a_kept_ask_and_matching_behaviour_publish_nothing(monkeypatch):
    """The grader says kept, the data moved the way the ask wanted, and Matthew said nothing: not recorded."""
    t = _table(
        {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-11-05#WORKOUT#1", "title": "Evening walk"},
        {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-11-05", "sleep_duration_hours": 8.4},
    )
    assert _public(t) == {}
    rows = _api_rows(t)
    assert all("what_matt_did" not in r for r in rows)
    data = _data_file(rows)
    assert [r["did"] for r in data["coaches"][COACH]["asks"]["rows"]] == [None, None]
    assert t.query_calls and {_key_parts(q["KeyConditionExpression"]) for q in t.query_calls} == {(PK, "ASKRESPONSE#sleep_coach#")}


def test_the_api_attaches_only_to_full_dossiers_and_the_page_reads_did_only():
    src = (ROOT / "lambdas/web/site_api_coach_profile.py").read_text(encoding="utf-8")
    assert "if not commitments_only and commitments:\n        commitments = _with_what_matt_did(" in src
    page = (ROOT / "www/src/lib/coach_room.js").read_text(encoding="utf-8")
    assert "did: didWords(a.did)" in page and "a.outcome" not in page.split("export function didWords")[1].split("}")[0]
