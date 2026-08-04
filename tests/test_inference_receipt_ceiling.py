"""tests/test_inference_receipt_ceiling.py — #1230.

The public /api/inference_receipt is the platform's flagship cost-honesty surface.
It used to hardcode `"budget_ceiling_usd": 75` and a note "The $75 ceiling covers the
WHOLE platform" while the real ceiling is $85 base (ADR-133) / $100 in surge mode — the
receipt was off by $25 while surge was active. The fix derives the ceiling from the
governor's /life-platform/budget-breakdown param (#822) and drops every hardcoded figure
(here and in the bedrock_client tier-3 BudgetExceeded message).

Two guards, both offline:
  1. Truth test: with SSM mocked, the receipt's budget_ceiling_usd == the breakdown's
     ceiling (and falls back to the $85 base — never $75 — when the read fails).
  2. Source-scan non-vacuity: check_doc_facts._source_hits flags the exact defect shape
     planted in a scratch file, and does NOT flag the fixed or the legitimately-historical
     ($75 reference constant) shapes.
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from operational import cost_governor_lambda as cg  # noqa: E402  # #1997: drift guard needs the QUALIFIED import path
from web import site_api_intelligence as sad  # noqa: E402  # #1240: handle_inference_receipt moved to site_api_intelligence


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeCW:
    """No AI usage this period — keeps models/features empty so the test is about
    the ceiling, not token math."""

    def list_metrics(self, **kw):
        return {"Metrics": []}

    def get_metric_statistics(self, **kw):  # pragma: no cover — not reached with no metrics
        return {"Datapoints": []}


class _FakeSSM:
    def __init__(self, params, raises_for=()):
        self._params = params
        self._raises_for = set(raises_for)

    def get_parameter(self, Name):
        if Name in self._raises_for:
            raise RuntimeError("simulated SSM failure")
        return {"Parameter": {"Value": self._params[Name]}}


def _install(monkeypatch, ssm):
    def _client(service, **kw):
        if service == "cloudwatch":
            return _FakeCW()
        if service == "ssm":
            return ssm
        raise AssertionError(f"unexpected client: {service}")

    monkeypatch.setattr(sad.boto3, "client", _client)


def _payload(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── 1. truth test ─────────────────────────────────────────────────────────────
def test_receipt_ceiling_equals_breakdown_ceiling(monkeypatch):
    """The receipt's budget_ceiling_usd is the breakdown param's ceiling — not a literal."""
    breakdown = {
        "tier": 1,
        "mtd": 40.0,
        "projected": 82.22,
        "ceiling": 100.0,  # surge active → floated ceiling
        "surge_active": True,
        "recent_uniques": 972,
        "ai_daily": 1.5,
        "non_ai_daily": 1.0,
        "computed_at": "2026-07-17T00:00:00+00:00",
    }
    ssm = _FakeSSM(
        {
            "/life-platform/budget-tier": "1",
            "/life-platform/budget-breakdown": json.dumps(breakdown),
        }
    )
    _install(monkeypatch, ssm)

    body = _payload(sad.handle_inference_receipt())
    assert body["budget_ceiling_usd"] == breakdown["ceiling"]  # the core assertion
    assert body["budget_surge_active"] is True
    # the note must never state the retired $75; it names the base + the $-in-effect.
    assert "$75" not in body["note"]
    assert "$85" in body["note"] and "$100" in body["note"]


def test_receipt_ceiling_tracks_base_when_not_surging(monkeypatch):
    breakdown = {
        "tier": 0,
        "mtd": 20.0,
        "projected": 55.0,
        "ceiling": 85.0,
        "surge_active": False,
        "ai_daily": 0.8,
        "non_ai_daily": 0.9,
        "computed_at": "2026-07-17T00:00:00+00:00",
    }
    ssm = _FakeSSM(
        {
            "/life-platform/budget-tier": "0",
            "/life-platform/budget-breakdown": json.dumps(breakdown),
        }
    )
    _install(monkeypatch, ssm)

    body = _payload(sad.handle_inference_receipt())
    assert body["budget_ceiling_usd"] == 85.0
    assert body["budget_surge_active"] is False


def test_receipt_falls_back_to_85_never_75_on_ssm_failure(monkeypatch):
    """A breakdown-read blip degrades to the ADR-133 base $85 — never the retired $75."""
    ssm = _FakeSSM(
        {"/life-platform/budget-tier": "0"},
        raises_for=("/life-platform/budget-breakdown",),
    )
    _install(monkeypatch, ssm)

    body = _payload(sad.handle_inference_receipt())
    assert body["budget_ceiling_usd"] == 85.0
    assert body["budget_ceiling_usd"] != 75
    assert body["budget_surge_active"] is False


# ── 1b. #1997 — the receipt's price table CANNOT drift from the governor's ────
# Must use the QUALIFIED `from operational import cost_governor_lambda` path, matching
# how site_api_intelligence.py itself imports it — the unqualified `import
# cost_governor_lambda` some older tests use (test_receipts_endpoint.py,
# test_budget_guard_ladder.py, both of which add lambdas/operational to sys.path
# directly) creates a SEPARATE module object under a different sys.modules key, so a
# comparison against that copy would prove nothing (known repo trap: a re-export via
# the wrong import path is not the same object, silently).
def test_receipt_prices_are_the_governors_prices_not_a_copy():
    """The receipt's _BEDROCK_PRICES must be the governor's _PRICES object (imported,
    never hand-copied) — key-for-key equal, including cache_read/cache_write for every
    family, so the two tables cannot silently drift."""
    assert sad._BEDROCK_PRICES is cg._PRICES
    assert set(sad._BEDROCK_PRICES.keys()) == set(cg._PRICES.keys())
    for family, price in cg._PRICES.items():
        assert sad._BEDROCK_PRICES[family] == price
        assert set(price.keys()) >= {"in", "out", "cache_read", "cache_write"}


def test_receipt_safety_buffer_is_the_governors_safety_buffer():
    assert sad._AI_SAFETY_BUFFER == cg._AI_SAFETY_BUFFER


def test_price_for_model_never_guesses_for_an_unmatched_model():
    """#1997 acceptance bullet 2: an unmatched model (e.g. Titan/embeddings) must
    return None — never a fallback price (the old bug silently priced it at Sonnet)."""
    assert sad._price_for_model("amazon.titan-embed-text-v2:0") is None
    assert sad._price_for_model("some-future-unknown-model") is None
    assert sad._price_for_model("") is None
    # known families still resolve correctly.
    assert sad._price_for_model("us.anthropic.claude-sonnet-4-6-v1:0") == cg._PRICES["sonnet"]


# ── 2. bedrock_client message carries no literal figure ───────────────────────
def test_bedrock_budget_message_has_no_dollar_literal():
    src = (_REPO / "lambdas" / "ai" / "bedrock_client.py").read_text(encoding="utf-8")
    assert "BudgetExceeded(" in src
    # the tier-3 message line must not carry a hardcoded dollar ceiling.
    assert "$75" not in src.split("BudgetExceeded(", 1)[1].split(")", 1)[0]


# ── 3. check_doc_facts source scan is non-vacuous ─────────────────────────────
def _load_gate():
    spec = importlib.util.spec_from_file_location("_docfacts", _REPO / "scripts" / "check_doc_facts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_source_scan_flags_planted_defect_but_not_fixed_or_historical():
    gate = _load_gate()
    d = Path(tempfile.mkdtemp())

    # the EXACT #1230 defect shape — must be caught.
    bad = d / "defect.py"
    bad.write_text('def h():\n    return {"budget_ceiling_usd": 75, "note": "The $75 ceiling covers the platform"}\n')
    assert gate._source_hits([bad]), "source scan is VACUOUS — it did not flag the planted $75 ceiling literal"

    # the fixed shape (value read from the breakdown, figure interpolated) — must pass.
    good = d / "fixed.py"
    good.write_text('def h(c):\n    return {"budget_ceiling_usd": ceiling_usd, "note": f"the ${c:.0f} base ceiling"}\n')
    assert gate._source_hits([good]) == []

    # an ALLOWED value (the $85 base / $100 surge) — must pass.
    ok = d / "ok.py"
    ok.write_text('    return {"budget_ceiling_usd": 85}  # base\n')
    assert gate._source_hits([ok]) == []

    # the legitimate historical reference constant ($75 = the ORIGINAL calibration
    # anchor) — must NOT be flagged.
    hist = d / "hist.py"
    hist.write_text("    against the ORIGINAL $75 ceiling (_THRESHOLD_REFERENCE_CEILING); they scale\n")
    assert gate._source_hits([hist]) == []


def test_source_scan_clean_on_current_tree():
    """After the fix, no live source file hardcodes a stale ceiling."""
    gate = _load_gate()
    hits = gate._source_hits(gate._scan_source_files())
    assert hits == [], "stale hardcoded ceiling still in source:\n" + "\n".join(hits)
