"""tests/test_ensemble_digest_deadman_3829.py — #3829 boxes 1 and 3.

THE GAP THESE CLOSE. `tests/test_ensemble_digest_timeout_3829.py` (#3836) holds the
SOURCE SHAPE: no line may claim persistence before `_put_item` returns, and the ceiling
may not be walked back. Neither of those can see a cycle that produced no row — a
static assertion over source is silent about the store. Two of the four cycles
2026-09-12..09-15 had no `ENSEMBLE#digest / CYCLE#` row and nothing reported it for
eight days; the only instrument that fired was a DLQ depth alarm a human read at wrap.

So there are two new behaviours here and one correction:

  * `operational/ensemble_digest_qa.check_ensemble_digest_liveness` — the dead-man.
    Fixtures below are the REAL partition contents, read live 2026-09-18T03:01Z:
    ... 09-11, 09-12, [09-13 ABSENT], 09-14, [09-15 ABSENT], 09-16, 09-17.

  * `coach_ensemble_digest._apply_grounding_gate(..., remaining_seconds=)` — the
    deadline guard. The gate's corrective regen is a SECOND Bedrock call, measured at
    55.3s (09-16) and 56.6s (09-17). Started with less time than that left, it cannot
    finish, and the cycle ends with nothing instead of with a fallback row.

  * `_finish_digest`'s terminal line. #3836 fixed the "produced" line and left the
    LAST line of the invocation — "Ensemble digest complete for cycle X" — emitted
    unconditionally, including when `_write_digest` had just returned False.

WHY THE NEWEST-ROW CHECK IS THE WRONG CHECK, pinned as a test rather than as prose:
`test_a_hole_behind_a_fresh_head_is_the_founding_incident` replays 2026-09-14, when
the newest sk was CYCLE#2026-09-14 — perfectly fresh — with 09-13 a hole one day
behind it. Holes heal at the head and stay in the body.
"""

import contextlib
import datetime as dt
import logging
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("SITE_BASE_URL", "https://averagejoematt.com")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "qa@example.invalid")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from operational import ensemble_digest_qa as edq  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

# The live partition, 2026-09-18T03:01Z. 09-13 and 09-15 are the incident's own holes.
LIVE_CYCLES = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-14", "2026-09-16", "2026-09-17"]

UTC = dt.timezone.utc
PT = dt.timezone(dt.timedelta(hours=-7))


class _LogSpy(logging.Handler):
    """Attach to the module's OWN logger.

    `platform_logger` emits structured JSON through a handler bound at import time and
    does not propagate, so `caplog`/`capsys`/`capfd` all read empty here — a test that
    trusted any of them would assert over a silent string and pass for the wrong reason.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def text(self):
        return "\n".join(r.getMessage() for r in self.records)


@contextlib.contextmanager
def _spy(mod):
    spy = _LogSpy()
    mod.logger.addHandler(spy)
    old = mod.logger.level
    mod.logger.setLevel(logging.DEBUG)
    try:
        yield spy
    finally:
        mod.logger.removeHandler(spy)
        mod.logger.setLevel(old)


def _pt_now(iso_utc):
    """A `pt_now` stub returning a PT-aware instant, exactly as qa_smoke injects."""
    moment = dt.datetime.fromisoformat(iso_utc).replace(tzinfo=UTC).astimezone(PT)
    return lambda: moment


def _between_bounds(cond):
    """Pull the BETWEEN bounds out of a real boto3 condition tree.

    Deliberately reads the condition the check actually built rather than accepting
    any query: a fake table that ignores the key condition would let a check with a
    broken range read green (the fixture-must-be-the-wire rule).
    """
    found = []

    def walk(node):
        expr = getattr(node, "get_expression", None)
        if expr is None:
            return
        e = expr()
        if e.get("operator") == "BETWEEN":
            found.append((e["values"][1], e["values"][2]))
        for v in e["values"]:
            walk(v)

    walk(cond)
    assert len(found) == 1, f"expected exactly one BETWEEN on the sk, got {len(found)}"
    return found[0]


class FakeTable:
    """Paginated, and it honours the range — two pages so the LEK loop is exercised."""

    def __init__(self, cycles, raises=None, page=2):
        self.cycles = list(cycles)
        self.raises = raises
        self.page = page
        self.queries = 0

    def query(self, **kw):
        self.queries += 1
        if self.raises:
            raise self.raises
        lo, hi = _between_bounds(kw["KeyConditionExpression"])
        rows = [{"sk": "CYCLE#" + c} for c in sorted(self.cycles) if lo <= "CYCLE#" + c <= hi]
        start = int(kw.get("ExclusiveStartKey", {}).get("n", 0))
        chunk = rows[start : start + self.page]
        out = {"Items": chunk}
        if start + self.page < len(rows):
            out["LastEvaluatedKey"] = {"n": start + self.page}
        return out


def _run(cycles, iso_utc, raises=None):
    table = FakeTable(cycles, raises=raises)
    results = edq.check_ensemble_digest_liveness(table, Check, CONTENT_TRUTH, _pt_now(iso_utc))
    assert len(results) == 1
    return results[0], table


# ══════════════════════════════════════════════════════════════════════════════
# The dead-man
# ══════════════════════════════════════════════════════════════════════════════


def test_negative_control_every_due_cycle_present_is_green():
    """The control that has to hold, or every red below is meaningless."""
    c, _ = _run(["2026-09-16", "2026-09-17", "2026-09-18"], "2026-09-18T18:30:00")
    assert c.passed is True, c.message
    assert "2026-09-16" in c.message and "2026-09-18" in c.message


def test_a_hole_behind_a_fresh_head_is_the_founding_incident():
    """2026-09-14, replayed from the real partition: newest row fresh, 09-13 a hole.

    This is the case a "is the newest row recent?" check cannot see, and it is the
    case that actually happened first.
    """
    c, _ = _run(LIVE_CYCLES, "2026-09-14T18:30:00")
    assert c.passed is None, f"a hole must be reported, got passed={c.passed}: {c.message}"
    assert "2026-09-13" in c.message
    # And the naive rule this design rejects: the newest row IS today's.
    assert max(d for d in LIVE_CYCLES if d <= "2026-09-14") == "2026-09-14"


def test_the_second_incident_the_newest_due_cycle_missing_is_a_fail():
    """2026-09-15: the run that filled the DLQ. Today's row is absent — FAIL, today."""
    c, _ = _run(LIVE_CYCLES, "2026-09-15T18:30:00")
    assert c.passed is False, f"expected FAIL, got passed={c.passed}: {c.message}"
    assert "CYCLE#2026-09-15" in c.message
    assert "timeout" in c.message.lower(), "the remediation must tell the operator where to look"


def test_both_holes_in_one_window_still_fails_on_the_newest():
    c, _ = _run(LIVE_CYCLES, "2026-09-15T23:00:00")
    assert c.passed is False
    assert "2026-09-13" in c.message and "2026-09-15" in c.message


def test_the_remediation_never_tells_an_operator_to_backfill():
    """A hole is permanent: a re-invoke with a past cycle_date would read TODAY's coach
    records and stamp them onto that cycle. Attest, never backfill."""
    for iso in ("2026-09-14T18:30:00", "2026-09-15T18:30:00"):
        c, _ = _run(LIVE_CYCLES, iso)
        low = c.message.lower()
        assert "backfill" in low, "the message must say so explicitly — silence invites the repair"


def test_todays_row_is_not_expected_before_the_grace_window_closes():
    """17:30Z is 30 minutes after the cron and inside the retry chain. Expecting the
    row here would fire a red every single day on a healthy platform."""
    c, _ = _run(["2026-09-15", "2026-09-16", "2026-09-17"], "2026-09-18T17:30:00")
    assert c.passed is True, c.message
    assert "2026-09-18" not in c.message

    # ...and 60 minutes later it IS due.
    late, _ = _run(["2026-09-15", "2026-09-16", "2026-09-17"], "2026-09-18T18:30:00")
    assert late.passed is False
    assert "CYCLE#2026-09-18" in late.message


def test_a_read_failure_is_unknown_and_never_fresh():
    """#2662's rule: a query that did not complete may not certify what it did not read."""
    c, table = _run(LIVE_CYCLES, "2026-09-17T18:30:00", raises=RuntimeError("ProvisionedThroughputExceeded"))
    assert c.passed is not True, "a failed read reported as fresh is the worst outcome available"
    assert c.passed is None
    assert "no verdict" in c.message.lower()
    assert table.queries == 1


def test_the_window_never_reaches_behind_genesis():
    """A reset tombstones the previous cycle's rows; expecting them would red every
    nightly for WINDOW_DAYS after every reset."""
    genesis = dt.date.fromisoformat(edq.EXPERIMENT_START_DATE)
    day1 = genesis.isoformat()
    c, _ = _run([day1], f"{day1}T18:30:00")
    assert c.passed is True, c.message
    for d in (genesis - dt.timedelta(days=1), genesis - dt.timedelta(days=2)):
        assert d.isoformat() not in c.message


def test_a_pre_genesis_instant_expects_no_cycle_at_all():
    before = (dt.date.fromisoformat(edq.EXPERIMENT_START_DATE) - dt.timedelta(days=5)).isoformat()
    c, _ = _run([], f"{before}T18:30:00")
    assert c.passed is True
    assert "pre-genesis" in c.message


def test_the_query_is_paginated_not_truncated():
    """One page is 2 rows in the fake; the window is 3. A single-page read would
    report the third day as a hole."""
    c, table = _run(["2026-09-16", "2026-09-17", "2026-09-18"], "2026-09-18T18:30:00")
    assert table.queries == 2, "the LastEvaluatedKey loop did not run — a truncated read invents holes"
    assert c.passed is True


def test_the_dead_man_is_wired_into_the_nightly_sweep():
    """Derived from check_steps, never enumerated (#1917) — an unwired check is a
    file, not an instrument. This is the #3860 lesson one issue later."""
    from operational import qa_smoke_lambda

    labels = [label for label, _fn in qa_smoke_lambda.check_steps()]
    assert "ensemble_digest_liveness" in labels, f"the dead-man is not in the nightly run list: {labels}"


# ══════════════════════════════════════════════════════════════════════════════
# The deadline guard — the row lands even when the gate cannot
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def digest_mod(monkeypatch):
    from coach import coach_ensemble_digest as ced

    calls = {"regen": 0}

    def fake_findings(text, **kw):
        return [{"type": "fabricated_number", "value": "326.3"}]

    def fake_regen_once(text, findings_fn, regen_fn, surface="unknown"):
        calls["regen"] += 1
        regen_fn("fix it")
        return text, findings_fn(text), False

    def fake_haiku(**kw):
        calls["haiku"] = calls.get("haiku", 0) + 1
        return {"coach_summaries": [], "active_disagreements": [], "unanimous_flags": []}

    monkeypatch.setattr(ced, "grounding_findings", fake_findings)
    monkeypatch.setattr(ced, "regen_once", fake_regen_once)
    monkeypatch.setattr(ced, "allowed_numbers", lambda m: set())
    monkeypatch.setattr(ced, "allowed_dates", lambda m: set())
    monkeypatch.setattr(ced, "cycle_gate_params", dict)
    monkeypatch.setattr(ced, "_call_haiku", fake_haiku)
    return ced, calls


DIGEST = {
    "coach_summaries": [{"coach": "sleep_coach", "summary": "Sleep held near 88%."}],
    "active_disagreements": [],
    "unanimous_flags": [],
}


def test_the_regen_is_skipped_when_the_deadline_cannot_hold_it(digest_mod):
    ced, calls = digest_mod
    with _spy(ced) as spy:
        out, findings = ced._apply_grounding_gate(DIGEST, "inputs", remaining_seconds=lambda: 20.0)
    assert calls["regen"] == 0, "a regen was started with 20s left — it cannot finish, and the row is lost with it"
    assert calls.get("haiku", 0) == 0, "a Bedrock call escaped the deadline guard"
    assert findings, "skipping the regen must still HOLD on the findings — the caller writes the fallback"
    assert out == DIGEST
    assert "SKIPPED" in spy.text and "#3829" in spy.text
    assert any(r.levelno >= logging.ERROR for r in spy.records), "a skipped gate must be loud — it degrades the cycle's stored artifact"


def test_the_regen_runs_with_the_full_ceiling_available(digest_mod):
    """The guard is a backstop, not a behaviour change: at the real 300s ceiling the
    gate is reached with ~240s left and must behave exactly as before."""
    ced, calls = digest_mod
    ced._apply_grounding_gate(DIGEST, "inputs", remaining_seconds=lambda: 240.0)
    assert calls["regen"] == 1
    assert calls.get("haiku", 0) == 1, "the corrective regen must still reach Bedrock when there is time for it"


def test_an_unknowable_deadline_does_not_skip(digest_mod):
    """None disables the guard; an exception reads as infinity. Neither invents a
    deadline — a guard that guesses its own budget is worse than no guard."""
    ced, calls = digest_mod
    ced._apply_grounding_gate(DIGEST, "inputs", remaining_seconds=None)
    assert calls["regen"] == 1

    assert ced._remaining_seconds(None) is None
    assert ced._remaining_seconds(object()) is None

    class Boom:
        def get_remaining_time_in_millis(self):
            raise RuntimeError("no deadline available")

    assert ced._remaining_seconds(Boom())() == float("inf")

    class Ctx:
        def get_remaining_time_in_millis(self):
            return 240_000

    assert ced._remaining_seconds(Ctx())() == pytest.approx(240.0)


def test_the_budget_is_above_every_measured_regen():
    """Sized from the two uncensored observations, not from a round number."""
    from coach import coach_ensemble_digest as ced

    for measured in (55.3, 56.6):
        assert (
            ced._REGEN_DEADLINE_BUDGET_S > measured
        ), "the budget is below a regen that really happened — the guard would fire on a healthy run"


# ══════════════════════════════════════════════════════════════════════════════
# The terminal line — #3836 fixed the first success line and left the last one
# ══════════════════════════════════════════════════════════════════════════════


def _finish_with(monkeypatch, stored):
    from coach import coach_ensemble_digest as ced

    monkeypatch.setattr(ced, "_put_item", lambda item: stored)
    monkeypatch.setattr(ced, "_update_coach_compressed_states", lambda *a, **k: 0)
    return ced


def test_the_terminal_line_says_not_stored_when_the_put_fails(monkeypatch):
    ced = _finish_with(monkeypatch, False)
    with _spy(ced) as spy:
        ced._finish_digest(dict(DIGEST), {}, "2026-09-15")
    terminal = [r for r in spy.records if "complete for cycle" in r.getMessage()]
    assert terminal, "the invocation's terminal line vanished"
    assert "NOT-STORED" in terminal[-1].getMessage(), "the last line of a cycle that stored nothing still read as success"
    assert terminal[-1].levelno >= logging.ERROR, "a not-stored cycle must log at ERROR — an INFO line is not reachable by a metric filter"


def test_the_terminal_line_names_the_row_it_stored(monkeypatch):
    ced = _finish_with(monkeypatch, True)
    with _spy(ced) as spy:
        ced._finish_digest(dict(DIGEST), {}, "2026-09-17")
    assert "stored ENSEMBLE#digest/CYCLE#2026-09-17" in spy.text
    assert "NOT-STORED" not in spy.text
