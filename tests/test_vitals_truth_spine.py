"""tests/test_vitals_truth_spine.py — the cross-surface vitals contract (#1369).

Replays the 2026-07-18 frontier finding: the public surface contradicted itself
on the same morning's numbers — /api/snapshot recovery 0.0% / "red" / sleep null
beside /api/pulse recovery 96% / 8.4h, steps 128 vs 525, and three different
hand-authored platform-count homes (121/26/62, 95/19/50, "19 data sources" hero
copy) against the guarded PLATFORM_STATS (64/20/94).

The fix: ONE canonical resolver (web/vitals_resolver.py) consumed by every
current-vitals surface, counts derived from the one guarded home, and the
/method/wrong header count derived from the parts it renders. These tests are
the contract gate — every class here FAILS on the pre-fix tree.
"""

import ast
import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import (
    site_api_intelligence as intel,  # noqa: E402
    site_api_vitals as vitals,  # noqa: E402
    vitals_resolver,  # noqa: E402
)


# ── Fake DDB table ───────────────────────────────────────────────────────────
class FakeTable:
    """Answers table.query() from a {source_pk_suffix: [items]} fixture.

    Matches on the pk inside the KeyConditionExpression (boto3 Key condition
    objects expose their operands via ._values); everything unknown returns
    empty Items — handlers treat that as honest absence.
    """

    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}

    @staticmethod
    def _find_pk(cond):
        # Walk the condition tree for the Key("pk").eq(...) operand.
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        if pk is None and isinstance(kwargs.get("ExpressionAttributeValues"), dict):
            pk = kwargs["ExpressionAttributeValues"].get(":pk")
        items = list(self.by_pk.get(pk, []))
        # Newest-first when the caller asks for it (the resolver always does).
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    def get_item(self, **kwargs):
        return {}


_WHOOP_PK = "USER#matthew#SOURCE#whoop"
_GARMIN_PK = "USER#matthew#SOURCE#garmin"
_AH_PK = "USER#matthew#SOURCE#apple_health"


def _resolver_fixture(now_date="2026-07-18"):
    """Whoop with an UNSCORED newest record (recovery finalizes late), garmin +
    apple_health disagreeing on steps — the exact live divergence shape."""
    return FakeTable(
        {
            _WHOOP_PK: [
                {"sk": f"DATE#{now_date}", "sleep_duration_hours": 8.4},  # unscored yet
                {"sk": "DATE#2026-07-17", "recovery_score": 96, "hrv": 61.2, "resting_heart_rate": 52, "sleep_duration_hours": 7.1},
                {"sk": f"DATE#{now_date}#WORKOUT#abc", "recovery_score": 12},  # workout sub-record: never a vital
            ],
            _GARMIN_PK: [{"sk": f"DATE#{now_date}", "steps": 525}],
            _AH_PK: [{"sk": f"DATE#{now_date}", "steps": 128, "water_intake_ml": 500}],
        }
    )


# ── 1. Resolver semantics ────────────────────────────────────────────────────
def test_resolver_finalized_recovery_separate_sleep_and_garmin_steps():
    out = vitals_resolver.resolve_vitals(_resolver_fixture(), "USER#matthew#SOURCE#")
    # recovery/hrv/rhr from the newest FINALIZED record (07-17), never the
    # unscored newest and never a workout sub-record
    assert out["recovery_pct"] == 96
    assert out["recovery_status"] == "green"
    assert out["hrv_ms"] == 61.2
    assert out["rhr_bpm"] == 52
    assert out["recovery_as_of"] == "2026-07-17"
    # sleep finalizes separately — newest record that carries it
    assert out["sleep_hours"] == 8.4
    assert out["sleep_as_of"] == "2026-07-18"
    # steps: garmin (watch of record) wins over apple_health
    assert out["steps"] == 525
    assert out["steps_source"] == "garmin"


def test_resolver_honest_null_on_empty():
    """ADR-104: no reading ⇒ None value AND None status. Never 0.0/red."""
    out = vitals_resolver.resolve_vitals(FakeTable(), "USER#matthew#SOURCE#")
    assert all(v is None for v in out.values()), out
    assert vitals_resolver.recovery_status(None) is None


# ── 2. Cross-surface parity: pulse and vitals serve the SAME numbers ─────────
def _stub_resolver(values):
    def _resolve(table, user_prefix, now=None):
        return dict(values)

    return _resolve


_CANON = {
    "recovery_pct": 96.0,
    "recovery_status": "green",
    "hrv_ms": 61.2,
    "rhr_bpm": 52.0,
    "recovery_as_of": "2026-07-17",
    "sleep_hours": 8.4,
    "sleep_as_of": "2026-07-18",
    "steps": 525.0,
    "steps_source": "garmin",
    "steps_as_of": "2026-07-18",
}


def test_pulse_and_vitals_agree_on_the_same_morning(monkeypatch):
    """The live contradiction (pulse 96%/8.4h vs snapshot 0.0%/red/null) is
    structurally impossible: both handlers consume the ONE resolver.

    On the pre-fix tree this fails at monkeypatch (neither module has the
    resolver symbol) — the wiring itself is the contract.
    """
    # /api/pulse — resolver stubbed, every other read honest-empty
    monkeypatch.setattr(intel, "resolve_vitals", _stub_resolver(_CANON), raising=True)
    monkeypatch.setattr(intel, "table", FakeTable(), raising=True)
    monkeypatch.setattr(intel, "_latest_item", lambda *a, **k: {}, raising=True)
    monkeypatch.setattr(intel, "_get_profile", lambda *a, **k: {}, raising=True)
    pulse = json.loads(intel.handle_pulse()["body"])

    # /api/vitals (the /api/snapshot vitals sub-object) — same stub
    monkeypatch.setattr(vitals.vitals_resolver, "resolve_vitals", _stub_resolver(_CANON), raising=True)
    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: [], raising=True)
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: {}, raising=True)
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]

    g = pulse["pulse"]["glyphs"]
    assert g["recovery"]["recovery_pct"] == round(_CANON["recovery_pct"]) == v["recovery_pct"]
    assert g["recovery"]["hrv_ms"] == v["hrv_ms"] == 61.2
    assert g["sleep"]["hours"] == v["sleep_hours"] == 8.4
    assert v["recovery_status"] == "green"
    assert g["movement"]["value"] == 525
    assert v["as_of_date"] == "2026-07-17"


def test_vitals_never_fabricates_zero_red_when_empty(monkeypatch):
    """The snapshot side of the finding: an empty window (e.g. the morning after
    a reset) must serve null/null — the pre-fix tree served 0.0 + "red"."""
    monkeypatch.setattr(vitals.vitals_resolver, "resolve_vitals", _stub_resolver({k: None for k in _CANON}), raising=True)
    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: [], raising=True)
    monkeypatch.setattr(vitals, "_latest_item", lambda *a, **k: {}, raising=True)
    v = json.loads(vitals.handle_vitals()["body"])["vitals"]
    assert v["recovery_pct"] is None
    assert v["recovery_status"] is None
    assert v["sleep_hours"] is None


# ── 3. Counts derive from the ONE guarded home ───────────────────────────────
def _dict_literal_int_values(path, keys):
    """All (key, value) pairs in dict literals where key ∈ keys and value is an
    int literal — the hand-authored-count smell."""
    tree = ast.parse(open(path).read())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in keys and isinstance(v, ast.Constant) and isinstance(v.value, int):
                    hits.append((k.value, v.value))
    return hits


def test_no_hand_authored_platform_counts_outside_the_one_home():
    """public_stats writers must not carry their own mcp_tools/data_sources/
    lambdas literals — PLATFORM_STATS (sync_doc_metadata-rewritten, pinned by
    test_platform_stats_truth) is the only home. Pre-fix: 121/26/62 + 95/19/50."""
    keys = {"mcp_tools", "data_sources", "lambdas"}
    for rel in ("lambdas/emails/daily_brief_lambda.py", "lambdas/site_writer.py"):
        hits = _dict_literal_int_values(os.path.join(_REPO, rel), keys)
        assert not hits, f"{rel} hand-authors platform counts: {hits} — derive from PLATFORM_STATS"


def test_hero_copy_source_count_is_derived():
    """The hero paragraph's "N data sources" must be an f-string off the guarded
    home, never a baked number (pre-fix: a literal "19 data sources")."""
    import re

    src = open(os.path.join(_REPO, "lambdas/site_writer.py")).read()
    tree = ast.parse(src)
    baked = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(r"\d+ data sources", n.value)
    ]
    assert not baked, f"hero copy bakes a source count: {baked!r}"


# ── 4. /method/wrong header derives from its parts ───────────────────────────
def test_wrong_header_count_is_sum_of_detailed_and_undetailed(monkeypatch):
    iq_pk = "USER#matthew"
    fake = FakeTable(
        {
            iq_pk: [
                {
                    "sk": "SOURCE#intelligence_quality#2026-07-10",
                    "date": "2026-07-10",
                    "coach_id": "sleep",
                    "checks_run": 10,
                    "errors": [{"detail": "claimed HRV 70, data says 55"}],
                    "flags": [{"detail": "cited a stale weigh-in"}],
                },
                # older record: count-only, no detail — the "4 caught, 2 rows" gap
                {"sk": "SOURCE#intelligence_quality#2026-06-01", "date": "2026-06-01", "checks_run": 5, "errors": 2},
            ]
        }
    )
    monkeypatch.setattr(intel, "table", fake, raising=True)
    body = json.loads(intel.handle_wrong()["body"])["validator"]
    assert body["caught_detailed"] == 2
    assert body["caught_undetailed"] == 2
    assert body["caught"] == body["caught_detailed"] + body["caught_undetailed"] == 4
    assert len(body["recent"]) == body["caught_detailed"]
