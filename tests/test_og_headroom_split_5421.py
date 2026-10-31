"""#5421 — og-image-generator ran at ~93% of its 60 s timeout (one timeout 2026-10-26).

The time was not the page cards (~15 s, flat) but the moments sweep, which re-rendered and
re-PUT ~225 objects a day that were byte-identical to yesterday's. Pinned here:

  * the two halves are separately invocable (``event["mode"]`` = render | sweep | all);
    the EventBridge event carries no mode and runs ``all``, render FIRST;
  * the sweep is incremental — an unchanged moment is not re-rendered or re-PUT, a changed
    one is, a code change (the salt) or ``force`` re-renders everything, and with no readable
    previous index it does exactly what it did before;
  * the sweep is time-boxed — inside ``SWEEP_RESERVE_MS`` of the timeout it starts no new
    moment, still writes the fingerprint and the index, and retries the rest next run;
  * an already-retired obituary is not re-redirected every day.

The handler is exercised by AST-extracting it (CI lanes run without Pillow, and importing
``og_image_lambda`` imports PIL — the same reason tests/test_og_card_coverage.py parses it).
"""

import ast
import json
import os
import sys
import time

os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import og_moments as om  # noqa: E402

_OG = os.path.join(_REPO, "lambdas", "web", "og_image_lambda.py")


# ── the handler: render / sweep / all ────────────────────────────────────────


def _handler_ns(calls):
    """lambda_handler + resolve_mode + MODE_* lifted out of og_image_lambda.py by AST, bound to
    recording stubs for the three heavy steps."""
    tree = ast.parse(open(_OG).read())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("resolve_mode", "lambda_handler"):
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "").startswith("MODE") for t in node.targets):
            keep.append(node)
    ns = {
        "time": time,
        "PAGES": [],
        "read_stats": lambda: calls.append("read_stats") or {},
        "render_cards": lambda stats: calls.append("render") or ["og-home"],
        "sweep": lambda stats, time_left=None, force=False: calls.append(("sweep", force, time_left)) or (3, 1),
        # #5421: recorded apart from `calls` (with how many steps ran before it), so the order tests above stay exact
        "invalidated": [],
    }
    ns["invalidate_og_images"] = lambda n: ns["invalidated"].append((n, len(calls)))
    exec(compile(ast.Module(body=keep, type_ignores=[]), _OG, "exec"), ns)  # noqa: S102 — our own module's handler lines, test-only
    return ns


class _Ctx:
    def get_remaining_time_in_millis(self):
        return 42_000


def test_mode_defaults_to_all_for_the_scheduled_event_and_for_garbage():
    ns = _handler_ns([])
    resolve = ns["resolve_mode"]
    eventbridge = {"version": "0", "source": "aws.events", "detail-type": "Scheduled Event", "detail": {}}
    for event in (eventbridge, {}, None, {"mode": ""}, {"mode": "bogus"}, {"mode": None}):
        assert resolve(event) == "all", event
    assert resolve({"mode": "render"}) == "render" and resolve({"mode": " SWEEP "}) == "sweep"


def test_render_only_runs_the_cards_and_never_the_sweep():
    calls = []
    out = _handler_ns(calls)["lambda_handler"]({"mode": "render"}, _Ctx())
    assert "render" in calls and not [c for c in calls if isinstance(c, tuple)]
    assert out["statusCode"] == 200 and out["body"].startswith("[render] Generated 1/0")


def test_sweep_only_runs_the_sweep_and_never_the_cards():
    calls = []
    ctx = _Ctx()
    out = _handler_ns(calls)["lambda_handler"]({"mode": "sweep", "force": True}, ctx)
    assert "render" not in calls
    (sweep_call,) = [c for c in calls if isinstance(c, tuple)]
    assert sweep_call[1] is True  # force travels through
    assert sweep_call[2]() == 42_000  # the invocation's remaining-time clock reaches the sweep
    assert out["body"].startswith("[sweep]")


def test_the_scheduled_event_renders_first_then_sweeps():
    calls = []
    out = _handler_ns(calls)["lambda_handler"]({"source": "aws.events"}, _Ctx())
    order = [c if isinstance(c, str) else "sweep" for c in calls]
    assert order == ["read_stats", "render", "sweep"], order  # the cards can never be starved by the sweep
    assert out["body"].startswith("[all]")


def test_handler_survives_a_non_dict_event():
    calls = []
    _handler_ns(calls)["lambda_handler"]("not-a-dict", None)
    assert "render" in calls  # None context -> unbounded sweep, never a crash


# ── the sweep: incremental + time-boxed ──────────────────────────────────────


class _FakeImg:
    def save(self, buf, **kw):
        buf.write(b"\x89PNG-fake")


class _Body:
    def __init__(self, d):
        self._d = d

    def read(self):
        return self._d


class _S3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.puts = {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(json.dumps(self.objects[Key]).encode())}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl=None, **kw):
        self.puts[Key] = {"body": Body, "type": ContentType, **kw}

    def cards(self):
        """Rendered bulk-class cards (obituary / prediction / chronicle / qa PNGs) — not the daily
        week + fingerprint cards, not a retirement redirect that merely shares the .png key."""
        return sorted(
            k
            for k, v in self.puts.items()
            if k.endswith(".png") and "WebsiteRedirectLocation" not in v and "/week-" not in k and "/fingerprint-" not in k
        )


def _obit(i, believed=None):
    return {
        "id": f"{i:012x}",
        "date": "2026-09-01",
        "coach": "nutrition",
        "believed": believed or f"total protein would trend down {i}",
        "number": "measured rising",
        "what_changed": "graded refuted",
    }


def _pred(i):
    return {"coach_id": "training", "coach_name": "M", "date": f"2026-06-{i + 1:02d}", "text": f"Recovery holds {i}", "status": "confirmed"}


_POSTS = {
    "posts": [
        {"url": f"/journal/posts/week-{i:02d}/", "title": f"Week {i}", "label": "W", "stats_line": "57", "date": "2026-09-01"}
        for i in range(3)
    ]
}
_STATS = {"journey": {"lost_lbs": 13.4}, "vitals": {"hrv_ms": 52}, "platform": {"days_in": 50, "tier0_streak": 3}}


class _World:
    """The wire: /api/wrong, /api/predictions and the previous /moments/index.json."""

    def __init__(self, monkeypatch, obits, preds):
        self.obits, self.preds, self.index = obits, preds, None
        monkeypatch.setattr(om, "build_moment_card", lambda *a, **k: _FakeImg())
        monkeypatch.setattr(om, "_fingerprint_card", lambda stats: _FakeImg())
        monkeypatch.setattr(om, "_fingerprint_metrics", lambda stats: {})
        monkeypatch.setattr(om.urllib.request, "urlopen", self._open)
        # chronicles draw through card_engine (Pillow); stand it in
        import types

        fake = types.ModuleType("web.card_engine")
        fake.render = lambda kind, payload: _FakeImg()
        monkeypatch.setitem(sys.modules, "web.card_engine", fake)
        import web

        monkeypatch.setattr(web, "card_engine", fake, raising=False)

    def _open(self, req, timeout=8):
        url = req.full_url
        body = (
            {"obituaries": self.obits}
            if url.endswith("/api/wrong")
            else (
                {"predictions": self.preds}
                if url.endswith("/api/predictions")
                else self.index if url.endswith("/moments/index.json") else None
            )
        )
        if body is None:
            raise OSError(f"unreachable: {url}")

        class _R:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def read(s):
                return json.dumps(body).encode()

        return _R()

    def run(self, **kw):
        s3 = _S3({"generated/journal/posts.json": _POSTS})
        idx = om.sweep_moments(s3, _STATS, **kw)
        self.index = json.loads(json.dumps(idx, default=str))  # what the NEXT run reads back over HTTP
        return s3, idx


def _world(monkeypatch, n_obits=6, n_preds=4):
    return _World(monkeypatch, [_obit(i) for i in range(n_obits)], [_pred(i) for i in range(n_preds)])


def test_first_run_with_no_previous_index_renders_every_moment(monkeypatch):
    w = _world(monkeypatch)
    s3, idx = w.run()
    assert len(s3.cards()) == 6 + 4 + 3  # obituaries + predictions + chronicles: the pre-#5421 behaviour
    assert len(idx["digests"]) == 13 and len(idx["wrong"]) == 6 and len(idx["predictions"]) == 4 and len(idx["chronicles"]) == 3


def test_an_unchanged_second_run_rewrites_no_card_and_keeps_the_index_whole(monkeypatch):
    w = _world(monkeypatch)
    _, first = w.run()
    s3, second = w.run()
    assert s3.cards() == [], "an unchanged moment must not be re-rendered and re-PUT"
    for k in ("wrong", "predictions", "chronicles", "digests", "wrong_published", "wrong_retired"):
        assert second[k] == first[k], k  # the index still lists every permalink the share buttons read
    assert "generated/moments/index.json" in s3.puts  # the index itself is rewritten daily
    assert any("/week-" in k for k in s3.puts) and any("/fingerprint/" in k for k in s3.puts)  # the daily classes stay daily


def test_a_changed_moment_is_rerendered_alone(monkeypatch):
    w = _world(monkeypatch)
    w.run()
    w.obits[2] = _obit(2, believed="a different belief entirely")
    s3, _ = w.run()
    assert s3.cards() == [f"generated/moments/assets/wrong-{2:012x}.png"]


def test_a_new_moment_is_rendered_alone(monkeypatch):
    w = _world(monkeypatch)
    w.run()
    w.preds.append(_pred(9))
    s3, idx = w.run()
    assert len(s3.cards()) == 1 and len(idx["predictions"]) == 5


def test_control_force_and_an_unreadable_index_and_a_code_change_each_rerender_everything(monkeypatch):
    """The measurement control: the 'no card rewritten' assertion above CAN fail."""
    w = _world(monkeypatch)
    w.run()
    assert len(w.run(force=True)[0].cards()) == 13
    keep, w.index = w.index, None  # previous index unreadable
    assert len(w.run()[0].cards()) == 13
    w.index = keep
    w.run()  # settle: current again
    monkeypatch.setattr(om, "_source_salt", lambda: "a-different-drawing-code-digest")
    assert len(w.run()[0].cards()) == 13  # the salt: new drawing code -> nothing is "current"


def test_a_salt_that_cannot_be_computed_never_claims_a_moment_is_current(monkeypatch):
    w = _world(monkeypatch)
    w.run()
    monkeypatch.setattr(om, "_source_salt", lambda: None)
    assert len(w.run()[0].cards()) == 13


def test_the_salt_covers_the_code_that_draws_and_guards_a_moment():
    salt = om._source_salt()
    assert salt and len(salt) == 16
    src = open(om.__file__).read()
    for needed in ("card_engine.py", "og_image_lambda.py", "journal_silence"):
        assert needed in src[src.index("def _source_salt") : src.index("class SweepPlan")]


def test_time_boxed_sweep_defers_the_bulk_but_still_writes_the_fingerprint_and_the_index(monkeypatch):
    w = _world(monkeypatch)
    s3, idx = w.run(time_left=lambda: 1_000)  # inside the 8 s reserve from the first moment
    assert s3.cards() == [], "no new bulk moment may start inside the reserve"
    assert idx["digests"] == {} and idx["wrong"] == {} and idx["predictions"] == []  # nothing claimed that was not written
    assert idx["fingerprint"] and "generated/moments/index.json" in s3.puts
    assert any("/week-" in k for k in s3.puts)
    # the next, unhurried run picks the deferred moments up
    s3b, idxb = w.run(time_left=lambda: 55_000)
    assert len(s3b.cards()) == 13 and len(idxb["digests"]) == 13


def test_a_deferred_but_already_published_moment_stays_in_the_index(monkeypatch):
    w = _world(monkeypatch)
    w.run()
    key = f"wrong/{0:012x}"
    old_digest = w.index["digests"][key]
    w.obits[0] = _obit(0, believed="changed while the clock ran out")
    s3, idx = w.run(time_left=lambda: 500)
    assert s3.cards() == []
    assert f"{0:012x}" in idx["wrong"]  # the older render still serves; it is not dropped from the index
    assert idx["digests"][key] == old_digest  # ...but it is not claimed current, so the next run retries it
    s3b, _ = w.run(time_left=lambda: 55_000)
    assert s3b.cards() == [f"generated/moments/assets/wrong-{0:012x}.png"]  # retried, and only it


def test_an_already_retired_obituary_is_not_redirected_again(monkeypatch):
    w = _world(monkeypatch)
    s3, idx = w.run()
    redirects = {k for k, v in s3.puts.items() if "WebsiteRedirectLocation" in v}
    assert redirects and idx["wrong_retired"]  # the seed ledger: ids published before the ledger existed
    s3b, idxb = w.run()
    assert not {k for k, v in s3b.puts.items() if "WebsiteRedirectLocation" in v}, "retired ids keep the redirect they were given"
    assert idxb["wrong_retired"] == idx["wrong_retired"]  # but the ledger still carries them
    # force re-writes them (the escape hatch if a redirect object was ever lost)
    s3c, _ = w.run(force=True)
    assert {k for k, v in s3c.puts.items() if "WebsiteRedirectLocation" in v} == redirects


def test_sweep_moments_hands_the_plan_to_every_bulk_class():
    tree = ast.parse(open(om.__file__).read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "sweep_moments")
    src = ast.unparse(fn)
    for call in ("_sweep_wrong(s3, plan)", "_sweep_board_answers(s3, plan)", "_sweep_predictions(s3, plan)", "_sweep_chronicles(s3, plan)"):
        assert call in src, call
    assert "'digests': plan.digests" in src


def test_the_edge_is_invalidated_once_after_the_sweep_writes_the_coach_cards():
    """2026-10-30: the invalidation ran inside the render step, before the sweep rewrote the coach
    cards, so the edge re-cached yesterday's card for a full max-age (qa-smoke og:coach-cards)."""
    calls = []
    ns = _handler_ns(calls)
    ns["lambda_handler"]({"mode": "all"}, _Ctx())
    assert ns["invalidated"] == [(2, len(calls))], (ns["invalidated"], calls)  # 1 page + 1 coach card, once, after every step


def test_the_invalidation_path_covers_the_coach_cards_in_both_formats():
    import ast as _ast

    tree = _ast.parse(open(_OG).read())
    path = next(
        n.value.value for n in tree.body if isinstance(n, _ast.Assign) and getattr(n.targets[0], "id", "") == "OG_INVALIDATION_PATH"
    )
    assert path.endswith("og-*"), path  # og-coach-*.png and .webp, and the page cards, under one wildcard
    render = next(n for n in tree.body if isinstance(n, _ast.FunctionDef) and n.name == "render_cards")
    assert "create_invalidation" not in _ast.unparse(render)  # never again before the sweep's writes


# ── #5421, 2026-10-30: why `unchanged=0` — the log must say, and a cold run must leave room ──────────


def _plan_for(w):
    """The SweepPlan a run would build now, from the index the previous run left."""
    return om.SweepPlan(w.index)


def test_second_pass_reports_every_moment_unchanged_and_none_rendered(monkeypatch, capsys):
    w = _world(monkeypatch)
    w.run()
    capsys.readouterr()
    s3, idx = w.run()
    out = capsys.readouterr().out
    assert "incremental sweep: rendered=0 unchanged=13 deferred=0" in out, out
    assert s3.cards() == [] and "why[" not in out  # nothing re-rendered -> nothing to explain


def test_a_code_change_rerender_names_the_cause_in_the_log(monkeypatch, capsys):
    w = _world(monkeypatch)
    w.run()
    monkeypatch.setattr(om, "_source_salt", lambda: "a-different-drawing-code-digest")
    capsys.readouterr()
    w.run()
    out = capsys.readouterr().out
    assert "rendered=13 unchanged=0" in out and "code-changed=13(first:" in out and "prior_salt=" in out, out


def test_a_cold_or_changed_run_names_its_reason(monkeypatch, capsys):
    w = _world(monkeypatch)
    capsys.readouterr()
    w.run()
    assert "no-index=13(first:" in capsys.readouterr().out
    w.obits[1] = _obit(1, believed="changed belief")
    w.preds.append(_pred(9))
    w.run()
    out = capsys.readouterr().out
    assert "payload-changed=1(first:wrong/" in out and "new-moment=1(first:" in out, out


def test_the_index_records_the_salt_it_was_drawn_under(monkeypatch):
    w = _world(monkeypatch)
    _, idx = w.run()
    assert idx["salt"] == om._source_salt()
    assert _plan_for(w).prior_salt == idx["salt"]


def test_the_reserve_covers_the_coach_cards_a_cold_run_ends_with():
    """2026-10-30: an 8 s reserve left a cold run 9 s for the coach cards + index put; it timed out
    twice in a row and the index never landed. Do not shrink this back."""
    assert om.SWEEP_RESERVE_MS >= 20000


def test_a_cold_run_that_hits_the_reserve_still_writes_the_index_so_the_retry_is_not_cold(monkeypatch):
    w = _world(monkeypatch)
    clock = {"left": 40_000}
    s3 = None

    def left():
        clock["left"] -= 3_000  # each moment costs ~3 s
        return clock["left"]

    s3, idx = w.run(time_left=left)
    assert 0 < len(idx["digests"]) < 13  # partial progress is recorded ...
    assert "generated/moments/index.json" in s3.puts  # ... and published
    s3b, idxb = w.run(time_left=lambda: 55_000)
    assert len(s3b.cards()) == 13 - len(idx["digests"]) and len(idxb["digests"]) == 13  # the next run finishes only the rest
