"""#2669 — the chronicle generation cache + the distinct timeout signal.

The 2026-08-05 issue was generated THREE times: the full model pipeline finished
inside the 120s timeout each run, the function died in the persist/render tail,
and each retry started from zero — three paid generations, zero shipped content.
Measured (21-day CloudWatch sweep): a representative full generation runs ~102s
against the 120s wall; three runs timed out.

Pinned here:
  1. the cache helpers' contract (write carries the text + a real TTL; read
     returns the text on a hit, None on miss, None — never a raise — on error);
  2. the watchdog's contract (armed at remaining-8s, fires a DISTINCT [ERROR] +
     ChronicleTimeoutImminent metric, cancelled on normal return);
  3. the reuse seam in the handler source: the cache is consulted BEFORE the
     Sonnet call and written before the render tail (structural pin — the full
     handler integration is proven by the live-run acceptance box, where the
     '[#2669] generation cache HIT' log line is the observable).

NB unit suite over two modules — no `tests/conftest.py` registration needed.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import logging  # noqa: E402
import time  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import chronicle_store as store  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402

_LOG = logging.getLogger("test-2669")


class _FakeTable:
    def __init__(self, items=None, raise_on=None):
        self.items = items or {}
        self.puts = []
        self.raise_on = raise_on

    def get_item(self, Key):
        if self.raise_on == "get":
            raise RuntimeError("ddb down")
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        if self.raise_on == "put":
            raise RuntimeError("ddb down")
        self.puts.append(Item)


def _g(table):
    return {"table": table, "logger": _LOG, "USER_ID": "matthew"}


# ── 1. cache helper contract ──────────────────────────────────────────────────


def test_write_then_read_roundtrip_with_ttl():
    t = _FakeTable()
    store.write_raw_cache("2026-08-19", 2, "the final gated text", _g=_g(t))
    (item,) = t.puts
    assert item["sk"] == "RAWCACHE#2026-08-19"
    assert item["raw_text"] == "the final gated text"
    # TTL is a real expiry ~7 days out, not a placeholder
    assert abs(item["ttl"] - (time.time() + store.RAW_CACHE_TTL_DAYS * 86400)) < 300

    t2 = _FakeTable(items={(item["pk"], item["sk"]): item})
    assert store.read_raw_cache("2026-08-19", _g=_g(t2)) == "the final gated text"


def test_read_miss_and_error_both_return_none_never_raise():
    assert store.read_raw_cache("2026-08-19", _g=_g(_FakeTable())) is None
    assert store.read_raw_cache("2026-08-19", _g=_g(_FakeTable(raise_on="get"))) is None


def test_write_failure_is_loud_but_nonfatal(caplog):
    with caplog.at_level(logging.ERROR, logger="test-2669"):
        store.write_raw_cache("2026-08-19", 2, "text", _g=_g(_FakeTable(raise_on="put")))
    assert any("cache write FAILED" in r.message for r in caplog.records)


# ── 2. the watchdog contract ──────────────────────────────────────────────────


class _FakeContext:
    def __init__(self, remaining_ms):
        self._ms = remaining_ms

    def get_remaining_time_in_millis(self):
        return self._ms


class _FakeTimer:
    instances = []

    def __init__(self, delay, fn):
        self.delay, self.fn, self.cancelled, self.daemon = delay, fn, False, False
        _FakeTimer.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


def test_watchdog_armed_at_remaining_minus_8_and_cancelled_on_return(monkeypatch):
    import threading

    _FakeTimer.instances = []
    monkeypatch.setattr(threading, "Timer", _FakeTimer)
    monkeypatch.setattr(chron, "_handler_core", lambda e, c: {"statusCode": 200, "body": "ok"})
    out = chron.lambda_handler({}, _FakeContext(120_000))
    assert out["statusCode"] == 200
    (timer,) = _FakeTimer.instances
    assert timer.delay == 112.0  # 120s remaining - 8s
    assert timer.cancelled, "a normal return must disarm the watchdog"


def test_watchdog_cancelled_even_when_core_raises(monkeypatch):
    import threading

    import pytest

    _FakeTimer.instances = []
    monkeypatch.setattr(threading, "Timer", _FakeTimer)

    def _boom(e, c):
        raise RuntimeError("mid-tail death")

    monkeypatch.setattr(chron, "_handler_core", _boom)
    with pytest.raises(RuntimeError):
        chron.lambda_handler({}, _FakeContext(60_000))
    (timer,) = _FakeTimer.instances
    assert timer.cancelled


def test_watchdog_fire_emits_distinct_error_and_metric(monkeypatch, capsys):
    import threading

    _FakeTimer.instances = []
    monkeypatch.setattr(threading, "Timer", _FakeTimer)
    monkeypatch.setattr(chron, "_handler_core", lambda e, c: {"statusCode": 200})

    metric_calls = []

    class _FakeCW:
        def put_metric_data(self, **kw):
            metric_calls.append(kw)

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeCW())
    chron.lambda_handler({}, _FakeContext(120_000))
    (timer,) = _FakeTimer.instances
    timer.fn()  # simulate the deadline arriving
    out = capsys.readouterr().out
    assert "[ERROR] [#2669] timeout imminent" in out and "retry is free" in out
    (mc,) = metric_calls
    assert mc["MetricData"][0]["MetricName"] == "ChronicleTimeoutImminent"


def test_no_watchdog_without_headroom(monkeypatch):
    import threading

    _FakeTimer.instances = []
    monkeypatch.setattr(threading, "Timer", _FakeTimer)
    monkeypatch.setattr(chron, "_handler_core", lambda e, c: {"statusCode": 200})
    chron.lambda_handler({}, _FakeContext(5_000))  # <10s — arming would fire instantly
    assert _FakeTimer.instances == []


# ── 3. the reuse seam, pinned structurally ────────────────────────────────────


def test_cache_read_sits_before_the_sonnet_call_and_write_before_render():
    src = open(os.path.join(_REPO, "lambdas", "emails", "wednesday_chronicle_lambda.py")).read()
    read_at = src.index("read_raw_cache")
    call_at = src.index("raw_installment = call_anthropic(elena_prompt, user_message")
    write_at = src.index("write_raw_cache")
    ai3_at = src.index("# AI-3: Validate output before rendering")
    assert read_at < call_at, "the cache must be consulted before paying for a generation"
    assert call_at < write_at < ai3_at, "the text must be persisted the moment the model pipeline completes"
    # the rehearsal contract (#2221): a dry run neither reads nor writes the cache
    assert 'not _dry and not event.get("force") and _target_date' in src
    assert "not _dry and not _skip_model_passes and _target_date" in src
