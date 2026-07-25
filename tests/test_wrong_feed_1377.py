"""tests/test_wrong_feed_1377.py — The Wrong Feed: graded failures as first-class content.

Contract (#1377, epic #1364):
  * /api/wrong emits an OBITUARY per graded failure — what we believed / the number
    that killed it / what changed — sourced ONLY from deterministic refuted verdicts
    (the LEARNING# records the evaluator grades), NEVER AI-asserted wrongness (ADR-104).
  * the headline count DERIVES from the obituary list (obituary_count == len(obituaries)),
    killing the header-drift class (AC4);
  * each card gets a stable permalink + data-driven OG card (og_moments._sweep_wrong)
    + an RSS entry (v4_build_rss.build_wrong_feed) — all keyed off the SAME id, so the
    permalink, the card, and the feed agree by construction.

Guard classes marked "RED pre-#1377" fail on the pre-feature tree.
"""

import json
import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_intelligence as intel  # noqa: E402


# ── A FakeTable that routes queries by their pk (USER# validator, COACH# ledger) ──
class FakeTable:
    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            if isinstance(v, str) and (v.startswith("USER#") or v.startswith("COACH#")):
                return v
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else None
            if got:
                return got
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        return {"Items": list(self.by_pk.get(pk, []))}

    def get_item(self, **kwargs):
        return {}


def _learning(coach, pid, status, metric, condition, threshold, actual, reason, date="2026-07-20"):
    return {
        "pk": f"COACH#{coach}_coach",
        "sk": f"LEARNING#{date}#{pid}",
        "coach_id": coach,
        "date": date,
        "prediction_id": pid,
        "status": status,
        "metric": metric,
        "condition": condition,
        "threshold": Decimal(str(threshold)),
        "actual_value": Decimal(str(actual)) if actual is not None else None,
        "reason": reason,
    }


def _wrong(table, monkeypatch):
    monkeypatch.setattr(intel, "table", table, raising=True)
    return json.loads(intel.handle_wrong()["body"])


# ═════════════════════════════════════════════════════════════════════════════
# 1. Obituaries — one per graded failure, templated from the verdict fields
# ═════════════════════════════════════════════════════════════════════════════
class TestObituaries:
    def test_one_obituary_per_refuted_verdict(self, monkeypatch):
        """RED pre-#1377: /api/wrong served no obituaries stream at all."""
        t = FakeTable(
            {
                "COACH#sleep_coach": [
                    _learning("sleep", "p1", "refuted", "sleep_hours", "gte", 7.5, 6.8, "sleep_hours trend=down, predicted=up"),
                    _learning("sleep", "p2", "confirmed", "sleep_hours", "gte", 7.0, 7.4, "held"),
                ],
                "COACH#training_coach": [
                    _learning("training", "p3", "refuted", "recovery_pct", "gt", 60, 48, "recovery flat", date="2026-07-18"),
                    _learning("training", "p4", "inconclusive", "recovery_pct", "gt", 60, None, "no signal"),
                ],
            }
        )
        body = _wrong(t, monkeypatch)
        obits = body["obituaries"]
        # ONLY the two refuted verdicts become obituaries — confirmed/inconclusive never do.
        assert len(obits) == 2, "only graded FAILURES (refuted) are obituaries"
        assert {o["coach"] for o in obits} == {"sleep", "training"}
        assert all(o["verdict"] == "refuted" for o in obits)

    def test_count_derives_from_the_list(self, monkeypatch):
        """AC4: obituary_count == len(obituaries), by construction."""
        t = FakeTable({"COACH#sleep_coach": [_learning("sleep", f"p{i}", "refuted", "hrv", "gte", 60, 50, "hrv fell") for i in range(4)]})
        body = _wrong(t, monkeypatch)
        assert body["obituary_count"] == len(body["obituaries"]) == 4

    def test_believed_and_number_are_templated_from_verdict_fields(self, monkeypatch):
        """The obituary text is PURE projection of the deterministic verdict — never AI.
        RED pre-#1377: refuted rows exposed only the bare condition operator ('gte')."""
        t = FakeTable(
            {
                "COACH#sleep_coach": [
                    _learning("sleep", "p1", "refuted", "sleep_hours", "gte", 7.5, 6.8, "sleep_hours trend=down, predicted=up")
                ]
            }
        )
        o = _wrong(t, monkeypatch)["obituaries"][0]
        assert o["believed"] == "sleep hours would come in at or above 7.5"
        assert "sleep hours measured 6.8" in o["number"]
        assert "at or above 7.5" in o["number"]
        assert o["what_changed"] == "sleep_hours trend=down, predicted=up"  # the evaluator's own reason string

    def test_number_formatting_strips_spurious_trailing_zero(self, monkeypatch):
        t = FakeTable({"COACH#sleep_coach": [_learning("sleep", "p1", "refuted", "steps", "gte", 8000, 6500.0, "short")]})
        o = _wrong(t, monkeypatch)["obituaries"][0]
        assert "8000" in o["believed"] and "6500" in o["number"]
        assert "8000.0" not in o["believed"] and "6500.0" not in o["number"]

    def test_id_is_stable_and_permalink_og_derive_from_it(self, monkeypatch):
        t = FakeTable({"COACH#sleep_coach": [_learning("sleep", "p1", "refuted", "hrv", "gte", 60, 50, "hrv fell")]})
        o = _wrong(t, monkeypatch)["obituaries"][0]
        import hashlib

        expect = hashlib.sha256(b"sleep|p1|refuted").hexdigest()[:12]
        assert o["id"] == expect
        assert o["permalink"] == f"/moments/wrong/{expect}/"
        assert o["og_image"] == f"/moments/assets/wrong-{expect}.png"

    def test_empty_slate_is_honest_not_broken(self, monkeypatch):
        body = _wrong(FakeTable({}), monkeypatch)
        assert body["obituaries"] == [] and body["obituary_count"] == 0

    def test_no_llm_in_the_path(self):
        """Grounding (ADR-104): the obituary helper templates deterministically — it must
        never route through the Bedrock chokepoint."""
        import inspect

        src = inspect.getsource(intel._wrong_obituary)
        assert "bedrock" not in src.lower() and "invoke" not in src.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 2. Per-card OG + permalink (og_moments._sweep_wrong) — keyed off the API id
# ═════════════════════════════════════════════════════════════════════════════
class FakeS3:
    def __init__(self):
        self.puts = {}

    def put_object(self, **kwargs):
        self.puts[kwargs["Key"]] = kwargs

    def get_object(self, **kwargs):
        raise RuntimeError("no object")


class TestOgSweep:
    def test_sweep_writes_permalink_shell_and_card_per_obituary(self, monkeypatch):
        from web import og_moments

        payload = {
            "obituaries": [
                {
                    "id": "abc123def456",
                    "date": "2026-07-20",
                    "coach": "sleep",
                    "believed": "sleep hours would come in at or above 7.5",
                    "number": "sleep hours measured 6.8 — the call was at or above 7.5",
                    "what_changed": "sleep_hours trend=down",
                    "permalink": "/moments/wrong/abc123def456/",
                    "og_image": "/moments/assets/wrong-abc123def456.png",
                }
            ]
        }

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode()

        monkeypatch.setattr(og_moments.urllib.request, "urlopen", lambda *a, **k: _Resp())
        s3 = FakeS3()
        out = og_moments._sweep_wrong(s3)
        assert out == {"abc123def456": "/moments/wrong/abc123def456/"}
        # The card + shell land at the paths the API already published (no drift).
        assert "generated/moments/assets/wrong-abc123def456.png" in s3.puts
        shell_key = "generated/moments/wrong/abc123def456/index.html"
        assert shell_key in s3.puts
        shell = s3.puts[shell_key]["Body"].decode()
        assert "sleep hours would come in at or above 7.5" in shell
        assert "/method/wrong/#obit-abc123def456" in shell  # deep-link back to the live feed

    def test_sweep_is_registered_in_the_index(self):
        import inspect

        from web import og_moments

        assert "wrong" in inspect.getsource(og_moments.sweep_moments)


# ═════════════════════════════════════════════════════════════════════════════
# 3. RSS entry per card (v4_build_rss.build_wrong_feed)
# ═════════════════════════════════════════════════════════════════════════════
class TestRssFeed:
    def test_build_wrong_feed_emits_an_item_per_obituary(self, monkeypatch, tmp_path):
        sys.path.insert(0, os.path.join(_REPO, "scripts"))
        import v4_build_rss as rss

        payload = {
            "obituaries": [
                {
                    "id": "abc123def456",
                    "date": "2026-07-20",
                    "coach": "sleep",
                    "believed": "sleep hours would come in at or above 7.5",
                    "number": "sleep hours measured 6.8",
                    "what_changed": "trend=down",
                    "permalink": "/moments/wrong/abc123def456/",
                },
            ]
        }

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode()

        monkeypatch.setattr(rss, "urlopen", lambda *a, **k: _Resp())
        monkeypatch.setattr(rss, "OUT", tmp_path / "rss.xml")
        n = rss.build_wrong_feed()
        assert n == 1
        feed = (tmp_path / "method" / "wrong" / "rss.xml").read_text()
        assert "The AI was wrong: sleep hours would come in at or above 7.5" in feed
        assert "https://averagejoematt.com/moments/wrong/abc123def456/" in feed
        assert '<rss version="2.0"' in feed

    def test_build_wrong_feed_is_fail_soft(self, monkeypatch, tmp_path):
        sys.path.insert(0, os.path.join(_REPO, "scripts"))
        import v4_build_rss as rss

        def _boom(*a, **k):
            raise OSError("endpoint down")

        monkeypatch.setattr(rss, "urlopen", _boom)
        monkeypatch.setattr(rss, "OUT", tmp_path / "rss.xml")
        # A dead endpoint yields a valid EMPTY feed, never an exception.
        assert rss.build_wrong_feed() == 0
        assert (tmp_path / "method" / "wrong" / "rss.xml").exists()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
