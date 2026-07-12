"""tests/test_experiment_justification_1117.py — the justification contract (#1117).

Experiment records carry why_now / priority / hoped_outcome / measurement /
evidence_links, and why_now is WIRED to the hypothesis→experiment promotion
trigger: an explicit value wins; else a confirmed hypothesis record or the
promoted experiment-library entry supplies it automatically, stamped with its
provenance (why_now_source). ADR-104 honest-empty: no trigger → no field, no
placeholder prose, and lookups fail soft (a missing trigger never blocks the
creation).
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

import experiment_design as ed  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

import mcp.tools_lifestyle as tl  # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────

LIB_ENTRY = {
    "id": "tongkat-ali-recovery",
    "name": "Tongkat Ali",
    "status": "active",
    "rationale": "Small but consistent human trial data on cortisol/testosterone.",
    "promoted_date": "2026-02-09",
    "votes": 3,
    "evidence_for": [
        {"title": "Tongkat Ali RCT", "url": "https://pubmed.ncbi.nlm.nih.gov/23615780/", "summary": "Reduced cortisol 16%."},
    ],
    "evidence_against": [
        {"title": "Industry funding bias", "url": None, "summary": "Mostly manufacturer-funded."},
        {"title": "Small samples", "url": "https://example.org/small-samples", "summary": "Largest trial n=76."},
    ],
}

CONFIRMED_HYP = {
    "pk": "USER#matthew#SOURCE#hypotheses",
    "sk": "HYPOTHESIS#2026-07-01T19:00:00+00:00",
    "hypothesis_id": "hyp-early-dinner-deep",
    "hypothesis": "Dinner before 7pm raises deep sleep %",
    "status": "confirmed",
    "last_checked": "2026-07-08T19:00:00+00:00",
    "effect_size": 2.4,
    "ci95_low": 0.8,
    "ci95_high": 4.1,
    "n_condition": 12,
    "n_comparison": 15,
}


class _FakeS3:
    """put_object recorder + get_object serving the experiment library (or failing)."""

    def __init__(self, library=None, get_fails=False):
        self.puts = []
        self.library = library
        self.get_fails = get_fails

    def put_object(self, **kw):
        self.puts.append(kw)

    def get_object(self, **kw):
        if self.get_fails or self.library is None:
            raise RuntimeError("S3 down")

        class _Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": _Body(json.dumps({"experiments": [self.library]}).encode())}


def _pk_query_hook(table, **kw):
    """Dispatch FakeDdbTable.query on the boto3 Key('pk').eq(...) partition value,
    so the iteration query (experiments pk) and the hypothesis lookup (hypotheses
    pk) each see only their own rows."""
    cond = kw.get("KeyConditionExpression")
    pk = None
    for sub in getattr(cond, "_values", ()) or ():
        vals = getattr(sub, "_values", ())
        if len(vals) == 2 and getattr(vals[0], "name", None) == "pk":
            pk = vals[1]
    return {"Items": [r for r in table.rows if r.get("pk") == pk]}


def _create(monkeypatch, args, rows=(), s3=None):
    table = FakeDdbTable(rows=list(rows), query_hook=_pk_query_hook)
    s3 = s3 or _FakeS3()
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "s3_client", s3)
    base = {"name": "Justification Test", "hypothesis": "deep sleep rises", "start_date": "2026-07-13"}
    base.update(args)
    return tl.tool_create_experiment(base), table, s3


# ── pure core: derive_why_now ─────────────────────────────────────────────────


class TestDeriveWhyNow:
    def test_explicit_wins_over_everything(self):
        text, source = ed.derive_why_now("  CGM arrived this week.  ", hypothesis=CONFIRMED_HYP, library_entry=LIB_ENTRY)
        assert text == "CGM arrived this week."
        assert source == "explicit"

    def test_confirmed_hypothesis_carries_measured_effect(self):
        text, source = ed.derive_why_now(None, hypothesis=CONFIRMED_HYP)
        assert source == "hypothesis"
        assert "Dinner before 7pm raises deep sleep %" in text
        assert "confirmed 2026-07-08" in text
        assert "measured effect +2.4" in text
        assert "95% CI [0.8, 4.1]" in text
        assert "n=12/15 days" in text

    def test_unconfirmed_hypothesis_is_not_a_trigger(self):
        hyp = dict(CONFIRMED_HYP, status="pending")
        text, source = ed.derive_why_now(None, hypothesis=hyp)
        assert text is None and source is None

    def test_hypothesis_beats_library(self):
        text, source = ed.derive_why_now(None, hypothesis=CONFIRMED_HYP, library_entry=LIB_ENTRY)
        assert source == "hypothesis"

    def test_promoted_library_entry(self):
        text, source = ed.derive_why_now(None, library_entry=LIB_ENTRY)
        assert source == "library"
        assert "Promoted from the experiment library on 2026-02-09" in text
        assert "cortisol/testosterone" in text
        assert "(3 reader votes)" in text

    def test_backlog_library_entry_is_not_a_trigger(self):
        entry = {"id": "x", "status": "backlog", "promoted_date": None, "votes": 0}
        text, source = ed.derive_why_now(None, library_entry=entry)
        assert text is None and source is None

    def test_no_trigger_is_honest_empty(self):
        text, source = ed.derive_why_now(None)
        assert text is None and source is None


# ── pure core: derive_evidence_links + validate_justification ────────────────


class TestDeriveEvidenceLinks:
    def test_explicit_wins(self):
        mine = [{"url": "https://example.org/mine", "title": "Mine"}]
        assert ed.derive_evidence_links(mine, library_entry=LIB_ENTRY) == mine

    def test_library_links_keep_dissent_and_drop_urlless(self):
        links = ed.derive_evidence_links(None, library_entry=LIB_ENTRY)
        # 1 for-link + 1 against-link; the url-less against citation is dropped (links need URLs).
        assert [(x["stance"], x["url"]) for x in links] == [
            ("for", "https://pubmed.ncbi.nlm.nih.gov/23615780/"),
            ("against", "https://example.org/small-samples"),
        ]
        assert links[0]["title"] == "Tongkat Ali RCT"

    def test_no_source_is_empty(self):
        assert ed.derive_evidence_links(None) == []
        assert ed.derive_evidence_links(None, library_entry={"id": "x"}) == []


class TestValidateJustification:
    def test_all_absent_is_valid(self):
        ok, issues = ed.validate_justification({})
        assert ok and issues == []

    def test_full_valid_set(self):
        ok, issues = ed.validate_justification(
            {
                "why_now": "CGM arrived",
                "priority": "high",
                "hoped_outcome": "lower glucose spikes",
                "measurement": "CGM mean glucose vs 14d baseline",
                "evidence_links": [{"url": "https://example.org", "title": "t", "stance": "for"}],
            }
        )
        assert ok and issues == []

    def test_bad_priority_rejected(self):
        ok, issues = ed.validate_justification({"priority": "urgent"})
        assert not ok and any("priority" in i for i in issues)

    def test_bad_links_rejected(self):
        for bad in ([{"title": "no url"}], [{"url": "ftp://x"}], [{"url": "https://x", "stance": "meh"}]):
            ok, issues = ed.validate_justification({"evidence_links": bad})
            assert not ok and any("evidence_links" in i for i in issues)

    def test_overlong_field_rejected(self):
        ok, issues = ed.validate_justification({"why_now": "x" * 601})
        assert not ok and any("why_now" in i for i in issues)

    def test_unknown_field_rejected(self):
        ok, issues = ed.validate_justification({"vibes": "good"})
        assert not ok and any("unknown" in i for i in issues)


# ── wiring: tool_create_experiment ────────────────────────────────────────────


class TestCreateExperimentWiring:
    def test_explicit_fields_stored_and_echoed(self, monkeypatch):
        resp, table, _ = _create(
            monkeypatch,
            {
                "why_now": "CGM arrived this week",
                "priority": "high",
                "hoped_outcome": "lower glucose spikes",
                "measurement": "CGM mean glucose vs 14d baseline",
                "evidence_links": [{"url": "https://example.org/rct", "title": "RCT"}],
            },
        )
        item = table.puts[0]
        assert item["why_now"] == "CGM arrived this week"
        assert item["why_now_source"] == "explicit"
        assert item["priority"] == "high"
        assert item["hoped_outcome"] == "lower glucose spikes"
        assert item["measurement"] == "CGM mean glucose vs 14d baseline"
        assert item["evidence_links"] == [{"url": "https://example.org/rct", "title": "RCT"}]
        assert resp["why_now_source"] == "explicit"

    def test_why_now_auto_populates_from_confirmed_hypothesis(self, monkeypatch):
        resp, table, _ = _create(monkeypatch, {"source_hypothesis_id": "hyp-early-dinner-deep"}, rows=[CONFIRMED_HYP])
        item = table.puts[0]
        assert item["why_now_source"] == "hypothesis"
        assert "Dinner before 7pm raises deep sleep %" in item["why_now"]
        assert "measured effect +2.4" in item["why_now"]
        assert item["source_hypothesis_id"] == "hyp-early-dinner-deep"
        assert resp["why_now_source"] == "hypothesis"

    def test_why_now_auto_populates_from_promoted_library_entry(self, monkeypatch):
        resp, table, _ = _create(monkeypatch, {"library_id": "tongkat-ali-recovery"}, s3=_FakeS3(library=LIB_ENTRY))
        item = table.puts[0]
        assert item["why_now_source"] == "library"
        assert "Promoted from the experiment library on 2026-02-09" in item["why_now"]
        # evidence links carried from the library entry, dissent tagged.
        assert [x["stance"] for x in item["evidence_links"]] == ["for", "against"]
        assert resp["evidence_links"] == item["evidence_links"]

    def test_unannotated_record_is_honest_empty(self, monkeypatch):
        resp, table, _ = _create(monkeypatch, {})
        item = table.puts[0]
        for field in ("why_now", "why_now_source", "priority", "hoped_outcome", "measurement", "evidence_links", "source_hypothesis_id"):
            assert field not in item  # clean_item strips Nones — nothing stored, nothing rendered
        assert resp["why_now"] is None and resp["why_now_source"] is None

    def test_missing_triggers_fail_soft(self, monkeypatch):
        # Unknown hypothesis id + library fetch failure: creation succeeds, honest-empty.
        resp, table, _ = _create(
            monkeypatch,
            {"source_hypothesis_id": "no-such-hyp", "library_id": "tongkat-ali-recovery"},
            s3=_FakeS3(get_fails=True),
        )
        assert resp["created"] is True
        assert "why_now" not in table.puts[0]

    def test_invalid_justification_rejected(self, monkeypatch):
        try:
            _create(monkeypatch, {"priority": "urgent"})
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "priority" in str(e)

    def test_justification_frozen_into_prereg_artifact(self, monkeypatch):
        design = {
            "baseline_days": 14,
            "washout_days": 3,
            "stopping_rule": "run the full 21 days regardless of interim trend; abort only if recovery < 40% for 3 days",
            "criterion": {"metric": "deep_pct", "direction": "higher", "min_effect": 2},
        }
        resp, table, s3 = _create(
            monkeypatch,
            {"design": design, "why_now": "CGM arrived", "priority": "high"},
        )
        body = json.loads(s3.puts[0]["Body"])
        assert body["why_now"] == "CGM arrived"
        assert body["why_now_source"] == "explicit"
        assert body["priority"] == "high"
        assert "hoped_outcome" not in body  # absent stays absent, even in the artifact
