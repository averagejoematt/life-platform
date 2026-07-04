"""#404 — permalinked shareable moments: shells, cards, index, honesty guards.

Pins: three moment classes exist (weekly recap · board answer · graded
prediction), each gets a stable permalink shell with its own OG card, shells
bake only computed/already-published values, empty moments produce nothing,
and the front-end share key matches the sweep's index key exactly.
"""

import json
import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import og_moments as om  # noqa: E402


class _FakeImg:
    """Stands in for the Pillow card so CI needs no PIL — the sweep contract
    under test is shells/index/honesty, not pixels."""

    def save(self, buf, **kw):
        buf.write(b"\x89PNG-fake")


om.build_moment_card = lambda *a, **k: _FakeImg()


class _FakeS3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.puts = {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)

        class _B:
            def __init__(self, data):
                self._d = data

            def read(self):
                return self._d

        return {"Body": _B(json.dumps(self.objects[Key]).encode())}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl=None):
        self.puts[Key] = {"body": Body, "type": ContentType}


def test_week_recap_moment_written_with_iso_week_permalink():
    s3 = _FakeS3()
    out = om._sweep_week_recap(
        s3, {"journey": {"lost_lbs": 13.4}, "vitals": {"hrv_ms": 52}, "platform": {"days_in": 21, "tier0_streak": 3}}
    )
    assert out and out["current"].startswith("/moments/week/") and "-W" in out["id"]
    shell_key = f"generated/moments/week/{out['id']}/index.html"
    assert shell_key in s3.puts
    html = s3.puts[shell_key]["body"].decode()
    assert "13.4 lbs down" in html and "HRV 52 ms" in html
    assert f'og:image" content="https://averagejoematt.com/moments/assets/week-{out["id"]}.png' in html
    assert f"generated/moments/assets/week-{out['id']}.png" in s3.puts  # its own card


def test_empty_stats_mean_no_recap_moment():
    s3 = _FakeS3()
    assert om._sweep_week_recap(s3, {}) is None
    assert s3.puts == {}  # no card, no shell — empty moments travel nowhere


def test_board_answer_moment_bakes_published_content_only():
    s3 = _FakeS3(
        objects={
            "generated/board_answers/answers.json": {
                "answers": [
                    {
                        "id": "abc123def456",
                        "question": "Is the glucose spike the supplement, or a bad night's sleep?",
                        "asked_at": "2026-07-01",
                        "answered_at": "2026-07-04",
                        "responses": [{"name": "Dr. Lisa Park", "text": "The short night explains most of it."}],
                    },
                    {"id": "unanswered1", "question": "Pending question?", "responses": []},
                ]
            }
        }
    )
    out = om._sweep_board_answers(s3)
    assert out == {"abc123def456": "/moments/qa/abc123def456/"}
    html = s3.puts["generated/moments/qa/abc123def456/index.html"]["body"].decode()
    assert "Is the glucose spike" in html and "Dr. Lisa Park" in html
    assert "/coaching/qa/#abc123def456" in html  # links back to the live surface
    assert "unanswered1" not in json.dumps(list(s3.puts))  # no answer → no moment


def test_prediction_moment_key_matches_frontend_composite():
    """The sweep's index key must be exactly what coaching.js rebuilds:
    coach_id|date|text[:60] — no hashing on the client side."""
    p = {"coach_id": "training", "date": "2026-06-20", "text": "x" * 100}
    assert om._prediction_key(p) == "training|2026-06-20|" + "x" * 60
    coaching = open(os.path.join(_REPO, "site/assets/js/coaching.js")).read()
    assert 'map[`${p.coach_id}|${p.date}|${String(p.text || "").slice(0, 60)}`]' in coaching


def test_prediction_sweep_only_mints_decided_calls(monkeypatch):
    payload = {
        "predictions": [
            {
                "coach_id": "training",
                "coach_name": "Marcus Chen",
                "date": "2026-06-20",
                "text": "Recovery holds above 60",
                "status": "confirmed",
                "outcome_notes": "held at 64",
            },
            {"coach_id": "sleep", "coach_name": "Dr. Lisa Park", "date": "2026-06-25", "text": "Sleep debt clears", "status": "pending"},
        ]
    }

    class _Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(om.urllib.request, "urlopen", lambda req, timeout=8: _Resp())
    s3 = _FakeS3()
    out = om._sweep_predictions(s3)
    assert len(out) == 1 and out[0]["status"] == "confirmed"
    shell = next(v["body"].decode() for k, v in s3.puts.items() if k.endswith("index.html"))
    assert "CALLED IT" in shell and "held at 64" in shell
    assert "Sleep debt clears" not in json.dumps(
        {k: v["body"].decode("utf-8", "ignore") for k, v in s3.puts.items() if k.endswith(".html")}
    )


def test_cloudfront_routes_moments_to_generated_origin():
    src = open(os.path.join(_REPO, "cdk/stacks/web_stack.py")).read()
    idx = src.find('path_pattern="/moments/*"')
    assert idx != -1 and 'target_origin_id="S3GeneratedOrigin"' in src[idx : idx + 400]


def test_share_affordance_exists_on_the_three_surfaces():
    coaching = open(os.path.join(_REPO, "site/assets/js/coaching.js")).read()
    cockpit = open(os.path.join(_REPO, "site/assets/js/cockpit.js")).read()
    share = open(os.path.join(_REPO, "site/assets/js/share.js")).read()
    assert "navigator.share" in share and "clipboard.writeText" in share
    assert "shareMount" in coaching and "qa-share" in coaching  # board answers
    assert "momentUrl(p)" in coaching  # graded predictions
    assert "shareMount(wk.current" in cockpit  # the weekly recap
