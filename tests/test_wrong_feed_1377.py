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
        assert o["believed"] == "sleep would come in at or above 7.5 hours"
        assert "sleep measured 6.8 hours" in o["number"]
        assert "at or above 7.5 hours" in o["number"]
        # #4218: a templated sentence, never the evaluator's raw reason string.
        assert o["what_changed"] == "It came in at 6.8 hours, not at or above 7.5 hours."

    def test_number_formatting_strips_spurious_trailing_zero(self, monkeypatch):
        t = FakeTable({"COACH#sleep_coach": [_learning("sleep", "p1", "refuted", "steps", "gte", 8000, 6500.0, "short")]})
        o = _wrong(t, monkeypatch)["obituaries"][0]
        # #4218: thousands separators, as the site's formatter prints them.
        assert "8,000" in o["believed"] and "6,500" in o["number"]
        assert "8000" not in o["believed"] and ".0" not in o["number"]

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
        out, _ledger = og_moments._sweep_wrong(s3)
        assert out == {"abc123def456": "/moments/wrong/abc123def456/"}
        # The card + shell land at the paths the API already published (no drift).
        assert "generated/moments/assets/wrong-abc123def456.png" in s3.puts
        shell_key = "generated/moments/wrong/abc123def456/index.html"
        assert shell_key in s3.puts
        shell = s3.puts[shell_key]["Body"].decode()
        assert "sleep hours would come in at or above 7.5" in shell
        assert "/method/wrong/#obit-abc123def456" in shell  # deep-link back to the live feed

    # ── #4404: an obituary that left /api/wrong is RETIRED, not left serving 200 ──
    # The fixture is the wire: the /api/wrong obituary is the real row the feed served at
    # 2026-09-29 03:0xZ (3b404dd9e871, live), and the /moments/index.json shape is the one
    # the previous run wrote (generated_at + a ``wrong`` id→permalink map). aa98dbbed1dd
    # is one of the 20 #4216 docket obituaries whose record left the feed.
    _LIVE = {
        "id": "3b404dd9e871",
        "date": "2026-09-28",
        "coach": "nutrition",
        "believed": "total protein would trend down",
        "number": "measured rising: the smoothed average of total protein rose 3.6% across its last 7 readings — the call was falling",
        "what_changed": "The trend ran up, the opposite of the call, so it was graded refuted.",
        "verdict": "refuted",
        "permalink": "/moments/wrong/3b404dd9e871/",
        "og_image": "/moments/assets/wrong-3b404dd9e871.png",
    }
    _RETIRED = "aa98dbbed1dd"

    def _route(self, monkeypatch, feed, index):
        """urlopen by URL: /api/wrong → ``feed``, /moments/index.json → ``index``.
        ``None`` for either makes that fetch raise, the way a failed read does live."""
        from web import og_moments

        def _open(req, timeout=8):
            url = req.full_url
            body = feed if url.endswith("/api/wrong") else index if url.endswith("/moments/index.json") else None
            if body is None:
                raise OSError(f"unreachable: {url}")

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return json.dumps(body).encode()

            return _Resp()

        monkeypatch.setattr(og_moments.urllib.request, "urlopen", _open)
        return og_moments

    @staticmethod
    def _redirects(s3):
        return {k: v["WebsiteRedirectLocation"] for k, v in s3.puts.items() if "WebsiteRedirectLocation" in v}

    def test_a_retired_id_redirects_and_a_live_id_is_untouched(self, monkeypatch):
        index = {"generated_at": "2026-09-28T19:30:11+00:00", "wrong": {self._LIVE["id"]: self._LIVE["permalink"]}}
        om = self._route(monkeypatch, {"data": {"obituaries": [self._LIVE], "obituary_count": 1}}, index)
        s3 = FakeS3()
        out, ledger = om._sweep_wrong(s3)
        redirects = self._redirects(s3)
        assert redirects[f"generated/moments/wrong/{self._RETIRED}/index.html"] == "/method/wrong/"
        assert redirects[f"generated/moments/assets/wrong-{self._RETIRED}.png"] == "/assets/images/og-home.png"
        live_keys = {"generated/moments/wrong/3b404dd9e871/index.html", "generated/moments/assets/wrong-3b404dd9e871.png"}
        assert live_keys <= set(s3.puts) and not live_keys & set(redirects)  # never touches a live id
        assert out == {"3b404dd9e871": "/moments/wrong/3b404dd9e871/"}
        assert self._RETIRED in ledger["retired"] and "3b404dd9e871" not in ledger["retired"]
        assert {self._RETIRED, "3b404dd9e871"} <= set(ledger["published"])
        assert len(redirects) == 2 * len(ledger["retired"])  # a shell AND a card per retired id

    def test_the_sweep_is_idempotent(self, monkeypatch):
        om = self._route(monkeypatch, {"obituaries": [self._LIVE]}, {"wrong": {}})
        first, second = FakeS3(), FakeS3()
        ledger_1 = om._sweep_wrong(first)[1]
        ledger_2 = om._sweep_wrong(second)[1]
        assert ledger_1 == ledger_2 and self._redirects(first) == self._redirects(second)

    def test_an_id_that_leaves_later_is_retired_from_the_carried_ledger(self, monkeypatch):
        """The class, not the specimen: an id the seed never named, published by an
        earlier run (so it rides in the index's ``wrong_published``), is retired once it
        leaves the feed."""
        index = {"wrong": {}, "wrong_published": ["0123456789ab", self._LIVE["id"]]}
        om = self._route(monkeypatch, {"obituaries": [self._LIVE]}, index)
        s3 = FakeS3()
        _out, ledger = om._sweep_wrong(s3)
        assert "0123456789ab" in ledger["retired"]
        assert self._redirects(s3)["generated/moments/wrong/0123456789ab/index.html"] == "/method/wrong/"

    def test_a_failed_or_empty_feed_retires_nothing_and_keeps_the_ledger(self, monkeypatch):
        index = {"wrong": {}, "wrong_published": ["0123456789ab"]}
        for feed in (None, {"obituaries": []}):
            om = self._route(monkeypatch, feed, index)
            s3 = FakeS3()
            out, ledger = om._sweep_wrong(s3)
            assert out == {} and ledger["retired"] == [] and self._redirects(s3) == {}
            assert {"0123456789ab", self._RETIRED} <= set(ledger["published"])  # carried, not dropped

    def test_the_index_carries_the_ledger_forward(self):
        import inspect

        from web import og_moments

        src = inspect.getsource(og_moments.sweep_moments)
        assert '"wrong_published"' in src and '"wrong_retired"' in src

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
