"""tests/test_chat_behavioral_gate_2564.py — the behavioral class on the CHAT surface.

#2564: `tests/grounding_wiring.py` declares `coach_chat_grounding.build_grounder` armed
for all five classes with NO exemption — the registry's only such entry, because in a
chat Matthew chooses the subject. But `ungrounded_behavioral_findings` returns [] the
instant `available_logs` is None, and the sole production chat call site
(`telegram_worker_lambda._grounder_for`) never passed one. The class read as coverage
and could not fire: a gate that cannot fail.

WHY THESE TESTS RUN THROUGH `_grounder_for` AND NOT `build_grounder`

The defect WAS the wiring, not the gate — `build_grounder` was always capable of arming
the class, and a test that calls it directly with a hand-built kwarg set passes with the
bug fully in place. That is the same harness failure this repo has paid for repeatedly
(a harness must track its real call site). So every behavioural assertion below goes
through the PRODUCTION assembly (`_assemble`) and the PRODUCTION closure builder
(`_grounder_for`), with only the I/O seams faked. Drop `available_logs=` from
`_grounder_for` and `test_the_chat_gate_catches_an_unlogged_same_day_claim` goes red.

COVERAGE IS PARTIAL AND DECLARED (ADR-104). The presence derivation answers for
nutrition / workout / journal — the three channels `PRESENCE_CHANNEL_CATEGORIES` maps.
An eating-window claim stays UNKNOWN and is deliberately NOT flagged: the signal cannot
speak to it, and a guessed map is worse than none.

Wall-clock discipline: every date here is injected. Nothing reads the real clock.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_chat_grounding as ccg  # noqa: E402

TODAY = "2026-08-11"
YESTERDAY = "2026-08-10"

PRESENCE_PK = "USER#matthew#SOURCE#engagement_state"


def _presence(date=TODAY, **last_log_dates):
    """An engagement_state STATE#current record in its stored shape."""
    return {
        "pk": PRESENCE_PK,
        "sk": "STATE#current",
        "date": date,
        "experiment_window_start": "2026-08-01",
        "channel_detail": {channel: {"last_log_date": d} for channel, d in last_log_dates.items()},
    }


class _FakeTable:
    """The two calls `_assemble` + `chat_available_logs` make of the table."""

    def __init__(self, item=None):
        self._item = item
        self.get_item_keys = []

    def get_item(self, Key=None, **_):  # noqa: N803 — boto3's own kwarg spelling
        self.get_item_keys.append(Key)
        if self._item is not None and Key == {"pk": PRESENCE_PK, "sk": "STATE#current"}:
            return {"Item": self._item}
        return {}

    def query(self, **_):
        return {"Items": []}


@pytest.fixture
def worker(monkeypatch):
    """The real worker module with only its I/O seams faked.

    `_facts`, `_memory_block` and `_thread_today` are the reads `_assemble` makes that
    have nothing to do with this gate; `_pacific_now` is the clock. Everything the fix
    touches — `_assemble`'s wiring of `today_pt`, `_grounder_for`'s kwargs,
    `chat_available_logs`'s read and derivation — stays production code.
    """
    import datetime as _dt

    from coach import telegram_worker_lambda as w

    monkeypatch.setattr(w, "_facts", lambda: {})
    monkeypatch.setattr(w, "_memory_block", lambda cid: "")
    monkeypatch.setattr(w, "_thread_today", lambda cid: [])
    monkeypatch.setattr(w, "_s3_client", lambda: None)
    monkeypatch.setattr(w, "_pacific_now", lambda: _dt.datetime(2026, 8, 11, 9, 30))
    monkeypatch.setattr(w, "_current_moment_line", lambda: f"CURRENT MOMENT: Tuesday, {TODAY}, 9:30 AM Pacific.")
    return w


def _chat_grounder(worker, monkeypatch, table):
    """Build the grounder EXACTLY as the live inbound turn does.

    `lambda_handler` runs `a = _assemble(...)` then `run_turn(..., grounder=_grounder_for(a, text))`
    — reproduced here call-for-call rather than approximated.
    """
    monkeypatch.setattr(worker, "_table", lambda: table)
    a = worker._assemble("nutrition_coach", "nutrition_coach")
    assert a["today_pt"] == TODAY, "the fixture clock must drive the generation date, not the wall clock"
    return worker._grounder_for(a, "how did I do today?")


# ── The class fires through the live path ────────────────────────────────────


def test_the_chat_gate_catches_an_unlogged_same_day_claim(worker, monkeypatch):
    """The whole point of #2564. MacroFactor's last log is YESTERDAY, so "no nutrition
    log today" is a KNOWN absence — and "you logged your meals today" is a fabricated
    completed-action claim about Matthew's own behaviour.

    MUTATION CONTRACT: delete `available_logs=` from `_grounder_for` and this assertion
    fails. It is the one that proves the class is wired, not merely declared.
    """
    table = _FakeTable(_presence(macrofactor=YESTERDAY))
    grounder = _chat_grounder(worker, monkeypatch, table)

    findings = grounder("You logged your meals today.")
    kinds = {f["type"] for f in findings}
    assert "ungrounded_behavioral" in kinds, f"the behavioral class did not fire on an unlogged same-day claim: {findings}"
    assert {f.get("category") for f in findings if f["type"] == "ungrounded_behavioral"} == {"nutrition"}
    # And the read that armed it went to the presence singleton, not somewhere else.
    assert {"pk": PRESENCE_PK, "sk": "STATE#current"} in table.get_item_keys


def test_the_chat_gate_catches_an_unlogged_journal_claim(worker, monkeypatch):
    """A second category through the same path — the class is armed for the presence
    record's whole mapped set, not incidentally for one regex."""
    table = _FakeTable(_presence(notion=YESTERDAY))
    grounder = _chat_grounder(worker, monkeypatch, table)

    findings = [f for f in grounder("You journaled today, which is the streak holding.") if f["type"] == "ungrounded_behavioral"]
    assert [f["category"] for f in findings] == ["journal"]


# ── The opposite direction: a supported claim must NOT fire ──────────────────


def test_a_logged_behavior_is_not_flagged(worker, monkeypatch):
    """A gate that flags everything is the same defect wearing a different hat.

    MacroFactor's last log IS today, so the claim is substantiated and must pass — with
    the identical reply text that fires in the test above.
    """
    table = _FakeTable(_presence(macrofactor=TODAY))
    grounder = _chat_grounder(worker, monkeypatch, table)

    assert [f for f in grounder("You logged your meals today.") if f["type"] == "ungrounded_behavioral"] == []


def test_an_uncovered_category_stays_unknown_never_a_finding(worker, monkeypatch):
    """ADR-104 behavioral-absence semantics. The presence record maps three channels;
    the eating window is not one of them, so it is UNKNOWN — and unknown is never
    reported as absence. This is why the derivation returns a LogAvailability and not a
    bare set: a set would call every unmapped category absent."""
    table = _FakeTable(_presence(macrofactor=TODAY, hevy=TODAY, notion=TODAY))
    grounder = _chat_grounder(worker, monkeypatch, table)

    assert [f for f in grounder("You maintained your eating window today.") if f["type"] == "ungrounded_behavioral"] == []


# ── The honest-dark cases: None, never an empty set ──────────────────────────


@pytest.mark.parametrize(
    "item,why",
    [
        (None, "no engagement_state record at all"),
        ({**_presence(), "tombstone": True}, "a restart tombstoned the singleton (#1969)"),
        (_presence(date=YESTERDAY, macrofactor=YESTERDAY), "the signal predates the day being asked about"),
    ],
)
def test_an_unusable_signal_leaves_the_class_dark_rather_than_lying(item, why):
    """`None` (or an availability that covers nothing) is the honest value when the
    presence signal cannot answer. Substituting an empty set to make the gate look armed
    would flip every TRUE same-day claim into a false finding — the opposite failure, and
    the worse one, because it corrects a coach into denying what actually happened."""
    logs = ccg.chat_available_logs(_FakeTable(item), TODAY)
    covered = getattr(logs, "covered", frozenset()) if logs is not None else frozenset()
    assert not covered, f"expected no coverage when {why}"

    from ai.behavior_logs import ungrounded_behavioral_findings

    assert ungrounded_behavioral_findings("You logged your meals today.", available_logs=logs) == []


def test_an_unreadable_table_fails_soft_not_loud():
    """The summarizer's posture, kept: storage trouble costs the class, never the turn."""

    class _Boom:
        def get_item(self, **_):
            raise RuntimeError("ddb down")

    assert ccg.chat_available_logs(_Boom(), TODAY) is None


def test_the_map_is_built_for_the_same_day_the_grounder_adjudicates(worker, monkeypatch):
    """One generation date, two consumers. A map built for UTC-today against a gate
    adjudicating Pacific-today would grade the claim against the wrong day's logs — the
    #2343 failure shape in #1699's clothes. `_gen_date` is the single definition and
    `_grounder_for` hands it the SAME `today_pt` it hands `generation_date_iso`."""
    seen = {}
    real = ccg.chat_available_logs

    def _recording(table, generation_date_iso=None):
        seen["date"] = generation_date_iso
        return real(table, generation_date_iso)

    monkeypatch.setattr(worker, "chat_available_logs", _recording)
    _chat_grounder(worker, monkeypatch, _FakeTable(_presence(macrofactor=TODAY)))
    assert seen["date"] == TODAY


# ── The registry's other side: every production caller passes the kwarg ──────


def test_every_production_build_grounder_call_supplies_available_logs():
    """The acceptance item "does any other caller have the same gap?", as a gate.

    Measured answer at the time of the fix: `build_grounder` has exactly ONE production
    caller — `telegram_worker_lambda._grounder_for`. (`scripts/coach_chat_sim.py` reaches
    the gate through `_grounder_for` and so inherits it; the remaining callers are test
    helpers.) This keeps that true: a second chat transport that forgets the kwarg
    re-opens #2564 silently, because the registry would still declare the class armed.
    """
    import ast

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    checked = 0
    for base, _dirs, files in os.walk(os.path.join(root, "lambdas")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                func = getattr(node, "func", None)
                called = getattr(func, "id", None) or getattr(func, "attr", None)
                if not (isinstance(node, ast.Call) and called == "build_grounder"):
                    continue
                checked += 1
                kwargs = {k.arg for k in node.keywords}
                assert "available_logs" in kwargs, (
                    f"{os.path.relpath(path, root)}: build_grounder called without available_logs — "
                    f"tests/grounding_wiring.py declares the behavioral class armed with NO exemption "
                    f"for this surface, and without the kwarg it cannot fire (#2564)"
                )
    assert checked == 1, f"expected exactly one production build_grounder call site, found {checked}"
