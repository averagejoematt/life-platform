"""tests/test_coach_memoir_lambda.py — #553 quarterly coach memoir guardrails (offline).

No moto, no real AWS, no real Bedrock (repo convention). A small in-memory
FakeTable EVALUATES the real boto3 Key condition objects (eq / begins_with /
between) so the quarter-window queries are genuinely exercised, not stubbed.

Covers:
  * budget-tier-1 self-pause (never touches Bedrock/S3/DDB when paused)
  * the quarterly regen-once gate: won't regenerate mid-quarter, will
    generate again once a new calendar quarter starts
  * honest-empty: a coach with no graded LEARNING# this quarter is skipped
  * the ADR-104 gate: fabricated numbers rejected, a real miss must be cited
  * the narration call: only real track-record facts reach the Bedrock prompt
"""

import os
import sys
from datetime import datetime

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import budget_guard  # noqa: E402
import persona_registry  # noqa: E402
from boto3.dynamodb.conditions import AttributeBase  # noqa: E402
from compute import coach_memoir_lambda as writer  # noqa: E402

# ── A real (small) DynamoDB query evaluator, not a stub — the quarter-window
# math is exactly what this feature depends on, so it needs to be exercised. ──


def _resolve(v, item):
    return item.get(v.name) if isinstance(v, AttributeBase) else v


def _eval_cond(cond, item) -> bool:
    op = cond.expression_operator
    vals = cond._values
    if op == "AND":
        return all(_eval_cond(c, item) for c in vals)
    attr = vals[0]
    name = attr.name if isinstance(attr, AttributeBase) else attr
    actual = item.get(name)
    if op == "=":
        return actual == _resolve(vals[1], item)
    if op == "BETWEEN":
        lo, hi = _resolve(vals[1], item), _resolve(vals[2], item)
        return actual is not None and lo <= actual <= hi
    if op == "begins_with":
        return isinstance(actual, str) and actual.startswith(_resolve(vals[1], item))
    raise NotImplementedError(f"unsupported operator {op!r}")


class FakeTable:
    def __init__(self):
        self.store = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        forward = kw.get("ScanIndexForward", True)
        matched = [dict(v) for v in self.store.values() if _eval_cond(cond, v)]
        matched.sort(key=lambda it: it.get("sk", ""), reverse=not forward)
        limit = kw.get("Limit")
        return {"Items": matched[:limit] if limit else matched}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


class _FakeDynamoResource:
    def __init__(self, table):
        self._table = table

    def Table(self, name):
        return self._table


class _FixedDatetime(datetime):
    """Freezes datetime.now(tz) inside the lambda module for the quarter-
    rollover test; .date() etc. still work since this subclasses datetime."""

    _fixed = datetime(2026, 10, 1)

    @classmethod
    def now(cls, tz=None):
        d = cls._fixed
        return cls(d.year, d.month, d.day, tzinfo=tz)


def _install_fakes(monkeypatch, table, s3):
    monkeypatch.setattr(writer.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(writer.boto3, "resource", lambda *a, **k: _FakeDynamoResource(table))
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)  # tier 0 — AI runs normally


def _learning(coach_id, dt, status, subdomain="sleep_quality", metric="deep_sleep_pct", reason="held up"):
    return {
        "pk": f"COACH#{coach_id}",
        "sk": f"LEARNING#{dt}#slug",
        "date": dt,
        "status": status,
        "subdomain": subdomain,
        "metric": metric,
        "reason": reason,
    }


def _stance(coach_id, dt, headline, changed=""):
    return {"pk": f"COACH#{coach_id}", "sk": f"STANCE#{dt}", "as_of": dt, "headline_read": headline, "how_my_read_changed": changed}


# ── budget-tier self-pause ──────────────────────────────────────────────────


def test_self_skips_when_budget_tier_pauses_coach_narrative(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)  # coach_narrative cutoff is 2 (ADR-125 reader-narrative band)
    out = writer.lambda_handler({}, None)
    assert out == {"skipped": True, "reason": "budget_tier"}


def test_runs_normally_below_the_pause_tier(monkeypatch):
    table, s3 = FakeTable(), FakeS3()
    _install_fakes(monkeypatch, table, s3)
    monkeypatch.setattr(writer, "datetime", _FixedDatetime)
    out = writer.lambda_handler({}, None)
    # No LEARNING# data anywhere -> every coach is an honest-empty skip, not a "budget" skip.
    assert out["quarter"] == "2026-Q3"
    assert set(out["skipped"]) == set(persona_registry.OPERATIONAL_COACH_IDS)
    assert out["written"] == []


# ── the quarterly regen-once gate (already_generated) ───────────────────────


def test_already_generated_false_when_no_sentinel():
    table = FakeTable()
    assert writer.already_generated(table, "sleep_coach", "2026-Q3") is False


def test_already_generated_true_after_a_sentinel_is_written():
    table = FakeTable()
    table.put_item(Item={"pk": "COACH#sleep_coach", "sk": "MEMOIR#2026-Q3", "text": "..."})
    assert writer.already_generated(table, "sleep_coach", "2026-Q3") is True
    # A DIFFERENT quarter's sentinel must not satisfy the gate.
    assert writer.already_generated(table, "sleep_coach", "2026-Q4") is False


# ── honest empty ─────────────────────────────────────────────────────────────


def test_gather_facts_is_none_with_no_learnings_this_quarter():
    table = FakeTable()
    assert writer._gather_facts(table, "sleep_coach", "2026-Q3") is None


def test_gather_facts_only_counts_records_inside_the_quarter_window():
    table = FakeTable()
    # In-window (Q3 2026 = Jul 1 - Sep 30)
    table.put_item(Item=_learning("sleep_coach", "2026-08-01", "confirmed"))
    table.put_item(Item=_learning("sleep_coach", "2026-08-10", "refuted", subdomain="recovery", metric="hrv_ms", reason="reversed"))
    # Out-of-window (Q2 2026) — must NOT be counted in the Q3 memoir.
    table.put_item(Item=_learning("sleep_coach", "2026-06-15", "confirmed"))
    facts = writer._gather_facts(table, "sleep_coach", "2026-Q3")
    assert facts is not None
    assert facts["total_evaluations"] == 2
    assert facts["by_outcome"] == {"confirmed": 1, "refuted": 1}
    assert facts["hit_rate_pct"] == 50.0
    assert len(facts["misses"]) == 1
    assert facts["misses"][0]["metric"] == "hrv_ms"


# ── the ADR-104 gate ─────────────────────────────────────────────────────────


def _facts_with_a_miss():
    return {
        "quarter": "2026-Q3",
        "total_evaluations": 2,
        "by_outcome": {"confirmed": 1, "refuted": 1},
        "decided_count": 2,
        "hit_rate_pct": 50.0,
        "calibration": {"brier": 0.18, "calibration": "well-calibrated", "scored_n": 6},
        "misses": [{"date": "2026-08-10", "subdomain": "recovery", "metric": "hrv_ms", "reason": "reversed"}],
        "hits": [{"date": "2026-08-01", "subdomain": "sleep_quality", "metric": "deep_sleep_pct", "reason": "held up"}],
        "stance_start": None,
        "stance_end": None,
        "learnings_raw": [
            {"status": "confirmed", "subdomain": "sleep_quality", "metric": "deep_sleep_pct"},
            {"status": "refuted", "subdomain": "recovery", "metric": "hrv_ms"},
        ],
    }


def test_gate_rejects_a_fabricated_number():
    facts = _facts_with_a_miss()
    text = "This quarter my hit rate quietly climbed to 97%, a number nowhere in my real record."
    ok, reasons = writer.gate_check(text, facts)
    assert ok is False
    assert any("fabricated" in r for r in reasons)


def test_gate_rejects_a_highlight_reel_when_a_miss_exists():
    facts = _facts_with_a_miss()
    text = "This quarter my hit rate held at 50%, and I'm proud of the calls I got right."
    ok, reasons = writer.gate_check(text, facts)
    assert ok is False
    assert "no_miss_cited_despite_refuted_learnings" in reasons


def test_gate_passes_grounded_text_that_cites_the_real_miss():
    facts = _facts_with_a_miss()
    text = "My hit rate held at 50% this quarter. My hrv_ms call on recovery didn't hold up, and I have to reckon with that."
    ok, reasons = writer.gate_check(text, facts)
    assert ok is True
    assert reasons == []


# ── narration: only real facts reach the prompt ─────────────────────────────


class _RecordingBedrock:
    """Captures every request body; scripted to return one text per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, body, model_name=None):
        self.calls.append(body)
        text = self._responses.pop(0) if self._responses else ""
        return {"content": [{"type": "text", "text": text}]}


def test_generate_prompt_carries_only_real_facts_no_invented_numbers(monkeypatch):
    facts = _facts_with_a_miss()
    fake_bedrock = _RecordingBedrock(
        ["My hit rate held at 50% this quarter. My hrv_ms call on recovery didn't hold up, and I have to own that."]
    )
    monkeypatch.setitem(sys.modules, "bedrock_client", fake_bedrock)

    persona = {"name": "Dr. Lisa Park", "board_role": "Sleep Science"}
    text, reasons = writer._generate_memoir(persona, "{}", "", facts, "2026-Q3")

    assert reasons == []
    assert text is not None
    # Exactly one call — the draft passed the gate on the first try.
    assert len(fake_bedrock.calls) == 1
    prompt = fake_bedrock.calls[0]["messages"][0]["content"]
    # The coach's real quarter, hit rate, and the specific miss are in the prompt...
    assert "2026-Q3" in prompt
    assert "50.0" in prompt
    assert "hrv_ms" in prompt
    # ...but nothing that looks like a career total the coach never saw.
    assert "9999" not in prompt


def test_generate_retries_once_then_drops_on_persistent_gate_failure(monkeypatch):
    facts = _facts_with_a_miss()
    # Both attempts dodge the real miss and invent a number -> gate fails twice.
    fake_bedrock = _RecordingBedrock(
        [
            "This quarter my hit rate quietly climbed to 97%, a triumph across the board.",
            "Another strong quarter — 97% again, no complaints from me.",
        ]
    )
    monkeypatch.setitem(sys.modules, "bedrock_client", fake_bedrock)

    persona = {"name": "Dr. Lisa Park", "board_role": "Sleep Science"}
    text, reasons = writer._generate_memoir(persona, "{}", "", facts, "2026-Q3")

    assert text is None  # fail-closed: never publish a memoir that dodges its own record
    assert len(fake_bedrock.calls) == 2  # exactly one generation + one corrective retry, never more
    assert reasons  # the caller gets to see why it was dropped


# ── end-to-end: won't regenerate mid-quarter, will on a new quarter ─────────


def test_end_to_end_quarterly_gate_regenerates_only_on_a_new_quarter(monkeypatch):
    table, s3 = FakeTable(), FakeS3()
    _install_fakes(monkeypatch, table, s3)
    monkeypatch.setattr(writer, "datetime", _FixedDatetime)  # "today" = 2026-10-01 -> target Q3

    table.put_item(Item=_learning("sleep_coach", "2026-08-01", "confirmed"))
    table.put_item(Item=_learning("sleep_coach", "2026-08-10", "refuted", subdomain="recovery", metric="hrv_ms", reason="reversed"))

    good_memoir = "My hit rate held at 50% this quarter. My hrv_ms call on recovery didn't hold up, and I have to own that."
    fake_bedrock = _RecordingBedrock([good_memoir])
    monkeypatch.setitem(sys.modules, "bedrock_client", fake_bedrock)

    out1 = writer.lambda_handler({}, None)
    assert out1["quarter"] == "2026-Q3"
    assert "sleep_coach" in out1["written"]
    assert len(fake_bedrock.calls) == 1
    assert writer.already_generated(table, "sleep_coach", "2026-Q3") is True

    # Re-run for the SAME quarter (e.g. a retried/rescheduled invocation) —
    # must NOT touch Bedrock again for a coach that already has this quarter's memoir.
    out2 = writer.lambda_handler({}, None)
    assert "sleep_coach" in out2["already"]
    assert "sleep_coach" not in out2["written"]
    assert len(fake_bedrock.calls) == 1  # unchanged — no second inference call

    # A new quarter starts: advance "today" to 2027-01-01 -> target 2026-Q4,
    # with fresh Q4 data. The gate must allow generation again.
    _FixedDatetime._fixed = datetime(2027, 1, 1)
    table.put_item(Item=_learning("sleep_coach", "2026-11-01", "confirmed"))
    fake_bedrock._responses.append("A steadier quarter this time, and I'm glad of it.")

    out3 = writer.lambda_handler({}, None)
    assert out3["quarter"] == "2026-Q4"
    assert "sleep_coach" in out3["written"]
    assert len(fake_bedrock.calls) == 2  # the new quarter earned exactly one new call
