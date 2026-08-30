"""tests/test_permalink_blackhole_3284.py — #3284: a published permalink must never be a redirect source.

The live cycle's Week 1 chronicle installment shipped unreachable: redirects.map
still carried the #1805-era `/journal/posts/week-04/ -> /story/journal/` 301,
registered when week-04 was a tombstoned orphan of the PREVIOUS cycle. Root
cause was a one-way ratchet — `register_permalink_redirect()` had no removal
path, and `untombstone_and_redate()` resurrected records without un-registering
— plus a gate gap: nothing cross-checked live posts.json URLs against
redirects.map (the one redirect test that existed *confirmed* the blackhole as
correct behaviour).

Pins, per the issue's acceptance boxes:
  1. register adds / unregister removes (the paired removal path), both
     idempotent, both dry-run no-ops — BOTH directions of the ratchet.
  2. untombstone_and_redate() un-registers the journal permalink 301s — a
     resurrected record cannot leave a live 301 behind.
  3. The cross-check itself (lambdas/operational/qa_check_permalink_blackhole):
     map-leg overlap fails, live-leg 301 fails, clean state passes, packaging
     gap warns (never a vacuous green, never a spurious red), and the check is
     actually WIRED into the nightly run list (#2307's lesson: a Check nobody
     runs is not a gate).

Offline by construction: the handler writes to a tmp redirects.map via a
monkeypatched module path; HTTP legs use scripted fake openers (the
test_redirect_spotcheck.py idiom — the empirically-verified HTTPError shape a
real 301 raises through the no-redirect opener).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import urllib.error
from pathlib import Path

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from operational import qa_check_permalink_blackhole as pb  # noqa: E402


def _load(name):
    """Load a deploy/ script as a module (they self-manage sys.path at import)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # registered first so cross-imports share the instance
    spec.loader.exec_module(mod)
    return mod


handler = _load("restart_chronicle_handler")

BASE_MAP = "/chronicle/\t/story/chronicle/\n/journal/\t/story/journal/\n"


def _map(tmp_path, monkeypatch, text=BASE_MAP):
    path = tmp_path / "redirects.map"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(handler, "REDIRECTS_MAP_PATH", path)
    return path


# ---------------------------------------------------------------------------
# 1. The paired ratchet: register adds, unregister removes
# ---------------------------------------------------------------------------


def test_register_appends_and_is_idempotent(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch)
    assert handler.register_permalink_redirect("/journal/posts/week-04/", "/story/journal/", apply=True) is True
    assert "/journal/posts/week-04/\t/story/journal/\n" in path.read_text(encoding="utf-8")
    # Second registration is a no-op — no duplicate line.
    assert handler.register_permalink_redirect("/journal/posts/week-04/", "/story/journal/", apply=True) is False
    assert path.read_text(encoding="utf-8").count("/journal/posts/week-04/") == 1


def test_register_dry_run_writes_nothing(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch)
    assert handler.register_permalink_redirect("/journal/posts/week-04/", "/story/journal/", apply=False) is False
    assert path.read_text(encoding="utf-8") == BASE_MAP


def test_unregister_removes_exactly_the_target_line(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch, BASE_MAP + "/journal/posts/week-04/\t/story/journal/\n")
    assert handler.unregister_permalink_redirect("/journal/posts/week-04/", apply=True) is True
    assert path.read_text(encoding="utf-8") == BASE_MAP  # other lines untouched, trailing newline kept


def test_unregister_is_idempotent_and_honest_about_absence(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch)
    assert handler.unregister_permalink_redirect("/journal/posts/week-04/", apply=True) is False
    assert path.read_text(encoding="utf-8") == BASE_MAP


def test_unregister_dry_run_and_missing_map_are_no_ops(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch, BASE_MAP + "/journal/posts/week-04/\t/story/journal/\n")
    assert handler.unregister_permalink_redirect("/journal/posts/week-04/", apply=False) is False
    assert "/journal/posts/week-04/" in path.read_text(encoding="utf-8")
    monkeypatch.setattr(handler, "REDIRECTS_MAP_PATH", tmp_path / "no-such" / "redirects.map")
    assert handler.unregister_permalink_redirect("/journal/posts/week-04/", apply=True) is False


def test_register_then_unregister_round_trips_the_file(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch)
    handler.register_permalink_redirect("/journal/posts/week-07/", "/story/journal/", apply=True)
    handler.unregister_permalink_redirect("/journal/posts/week-07/", apply=True)
    assert path.read_text(encoding="utf-8") == BASE_MAP


def test_unregister_journal_sweep_removes_the_set_and_only_the_set(tmp_path, monkeypatch):
    path = _map(
        tmp_path,
        monkeypatch,
        BASE_MAP
        + "/journal/posts/week-04/\t/story/journal/\n/journal/posts/week-05/\t/story/journal/\n/journal/posts/week-06/\t/story/journal/\n",
    )
    removed = handler.unregister_journal_permalink_redirects(apply=True)
    assert removed == ["/journal/posts/week-04/", "/journal/posts/week-05/", "/journal/posts/week-06/"]
    assert path.read_text(encoding="utf-8") == BASE_MAP  # /journal/ and /chronicle/ hub 301s survive
    # Dry-run reports nothing and touches nothing.
    path.write_text(BASE_MAP + "/journal/posts/week-04/\t/story/journal/\n", encoding="utf-8")
    assert handler.unregister_journal_permalink_redirects(apply=False) == []
    assert "/journal/posts/week-04/" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. untombstone_and_redate un-registers — a resurrection leaves no 301 behind
# ---------------------------------------------------------------------------


class _FakeTable:
    def __init__(self):
        self.calls = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)


def test_untombstone_unregisters_the_journal_permalinks(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch, BASE_MAP + "/journal/posts/week-04/\t/story/journal/\n/journal/posts/week-05/\t/story/journal/\n")
    table = _FakeTable()
    handler.untombstone_and_redate(table, "DATE#2026-02-28", "2026-08-11", apply=True, cycle=14)
    # The record was resurrected…
    assert len(table.calls) == 1
    assert table.calls[0]["Key"] == {"pk": "USER#matthew#SOURCE#chronicle", "sk": "DATE#2026-02-28"}
    # …and the journal permalink 301s are gone with it (the #3284 acceptance box).
    assert path.read_text(encoding="utf-8") == BASE_MAP


def test_untombstone_dry_run_touches_neither_ddb_nor_the_map(tmp_path, monkeypatch):
    path = _map(tmp_path, monkeypatch, BASE_MAP + "/journal/posts/week-04/\t/story/journal/\n")
    table = _FakeTable()
    handler.untombstone_and_redate(table, "DATE#2026-02-28", "2026-08-11", apply=False, cycle=14)
    assert table.calls == []
    assert "/journal/posts/week-04/" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. The cross-check: live posts.json urls vs redirects.map + the live edge
# ---------------------------------------------------------------------------


def test_published_post_urls_parses_the_manifest_shape():
    payload = {"posts": [{"url": "/journal/posts/week-04/", "title": "Day One"}, {"title": "no url — skipped"}]}
    assert pb.published_post_urls(payload) == ["/journal/posts/week-04/"]
    assert pb.published_post_urls({"tombstone": True}) == []
    assert pb.published_post_urls(None) == []


def test_assess_flags_exactly_the_overlap():
    entries = [("/journal/posts/week-04/", "/story/journal/"), ("/chronicle/", "/story/chronicle/")]
    findings = pb.assess_permalink_blackhole(["/journal/posts/week-04/", "/journal/posts/week-07/"], entries)
    assert len(findings) == 1 and "/journal/posts/week-04/" in findings[0] and "/story/journal/" in findings[0]
    assert pb.assess_permalink_blackhole(["/journal/posts/week-07/"], entries) == []


class _FakeOpener:
    """Scripted per-URL responses (the test_redirect_spotcheck.py idiom)."""

    def __init__(self, script):
        self.script = script  # url -> ("http_error", code, location) | ("ok", status) | ("raise", exc)

    def open(self, url, timeout=10):
        kind, *rest = self.script[url]
        if kind == "http_error":
            code, location = rest
            headers = {"Location": location} if location else {}

            class _H(dict):
                def get(self, k, default=None):
                    return headers.get(k, default)

            raise urllib.error.HTTPError(url, code, "err", _H(), None)
        if kind == "raise":
            raise rest[0]

        class _Resp:
            status = rest[0]

        return _Resp()


def test_probe_fails_on_a_live_301_and_only_on_a_redirect():
    base = "https://example.com"
    opener = _FakeOpener(
        {
            f"{base}/journal/posts/week-04/": ("http_error", 301, "/story/journal/"),  # today's live state — the blackhole
            f"{base}/journal/posts/week-03/": ("ok", 200),
            f"{base}/journal/posts/week-02/": ("http_error", 404, None),  # dead page ≠ this check's charge (page sweeps own it)
            f"{base}/journal/posts/week-01/": ("raise", TimeoutError("timed out")),  # transport ≠ a verdict
        }
    )
    urls = ["/journal/posts/week-04/", "/journal/posts/week-03/", "/journal/posts/week-02/", "/journal/posts/week-01/"]
    failures, errors = pb.probe_live_permalinks(urls, opener=opener, base_url=base)
    assert len(failures) == 1 and "/journal/posts/week-04/" in failures[0] and "301" in failures[0]
    assert len(errors) == 1 and "/journal/posts/week-01/" in errors[0]


def _wire_check(monkeypatch, posts_payload, map_entries, opener_script):
    """Point the live check at scripted stand-ins for its three inputs."""

    class _Body:
        def __init__(self, data):
            self._fh = io.BytesIO(json.dumps(data).encode())

        def read(self):
            return self._fh.read()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pb.urllib.request, "urlopen", lambda req, timeout=15: _Body(posts_payload))
    if isinstance(map_entries, Exception):

        def _raise(path=None):
            raise map_entries

        monkeypatch.setattr(pb, "load_redirects_map", _raise)
    else:
        monkeypatch.setattr(pb, "load_redirects_map", lambda path=None: map_entries)
    monkeypatch.setattr(pb, "build_no_redirect_opener", lambda: _FakeOpener(opener_script))


def test_check_fails_on_todays_live_state(monkeypatch):
    """The proof the gate works: week-04 published AND redirected → red.
    (On the merged tree the map leg is clean; the LIVE leg stays red until the
    driver publishes the regenerated CloudFront function — expected-red.)"""
    base = pb.SITE_BASE_URL.rstrip("/")
    _wire_check(
        monkeypatch,
        {"posts": [{"url": "/journal/posts/week-04/", "title": "Day One Actually Happened"}]},
        [("/journal/posts/week-04/", "/story/journal/")],
        {f"{base}/journal/posts/week-04/": ("http_error", 301, "/story/journal/")},
    )
    checks = pb.check_published_permalink_reachable()
    fails = [c for c in checks if c.passed is False]
    assert len(fails) == 1
    assert "week-04" in fails[0].message and "blackhole" in fails[0].message


def test_check_live_leg_alone_still_fails_when_the_map_is_clean(monkeypatch):
    """The merged-but-not-published window: repo map clean, edge still 301s."""
    base = pb.SITE_BASE_URL.rstrip("/")
    _wire_check(
        monkeypatch,
        {"posts": [{"url": "/journal/posts/week-04/", "title": "Day One Actually Happened"}]},
        [("/chronicle/", "/story/chronicle/")],
        {f"{base}/journal/posts/week-04/": ("http_error", 301, "/story/journal/")},
    )
    fails = [c for c in pb.check_published_permalink_reachable() if c.passed is False]
    assert len(fails) == 1 and "301" in fails[0].message


def test_check_goes_green_once_map_and_edge_are_both_clean(monkeypatch):
    base = pb.SITE_BASE_URL.rstrip("/")
    _wire_check(
        monkeypatch,
        {"posts": [{"url": "/journal/posts/week-04/", "title": "Day One Actually Happened"}]},
        [("/chronicle/", "/story/chronicle/")],
        {f"{base}/journal/posts/week-04/": ("ok", 200)},
    )
    checks = pb.check_published_permalink_reachable()
    assert all(c.passed is not False for c in checks)
    assert any(c.passed is True for c in checks)


def test_check_missing_map_is_warn_not_fail_and_the_live_leg_still_runs(monkeypatch):
    """A packaging gap warns (the #1430 posture) — but it must NOT blind the
    live leg: a live 301 still reds the check even with no map to read."""
    base = pb.SITE_BASE_URL.rstrip("/")
    _wire_check(
        monkeypatch,
        {"posts": [{"url": "/journal/posts/week-04/", "title": "Day One Actually Happened"}]},
        FileNotFoundError("redirects.map not found"),
        {f"{base}/journal/posts/week-04/": ("http_error", 301, "/story/journal/")},
    )
    checks = pb.check_published_permalink_reachable()
    assert any(c.passed is None and "redirects.map not found" in c.message for c in checks)
    assert any(c.passed is False and "301" in c.message for c in checks)


def test_check_fetch_failure_is_fail_soft(monkeypatch):
    def _boom(req, timeout=15):
        raise TimeoutError("timed out")

    monkeypatch.setattr(pb.urllib.request, "urlopen", _boom)
    checks = pb.check_published_permalink_reachable()
    assert all(c.passed is not False for c in checks), "a transient posts.json fetch must never red the nightly"


def test_check_empty_manifest_is_an_honest_green(monkeypatch):
    _wire_check(monkeypatch, {"posts": []}, [("/chronicle/", "/story/chronicle/")], {})
    checks = pb.check_published_permalink_reachable()
    assert len(checks) == 1 and checks[0].passed is True and "nothing to cross-check" in checks[0].message


# ---------------------------------------------------------------------------
# 4. Wiring — the check is actually in the nightly run list
# ---------------------------------------------------------------------------

import qa_smoke_lambda as qa  # noqa: E402


def test_check_wired_into_the_nightly_run_list():
    assert (
        "published_permalink_reachable",
        qa.check_published_permalink_reachable,
    ) in qa.check_steps(), "check_published_permalink_reachable is not in the nightly run list (#3284)"


# ---------------------------------------------------------------------------
# 5. The repo's own map — the three #3284 lines stay gone
# ---------------------------------------------------------------------------


def test_repo_redirects_map_carries_no_journal_permalink_sources():
    """The committed map itself: no /journal/posts/week-NN/ source may be
    tracked while the journal namespace is publishing (this is the repo-side
    half; the nightly check owns the live half)."""
    text = (REPO_ROOT / "redirects.map").read_text(encoding="utf-8")
    offenders = [ln.split("\t", 1)[0] for ln in text.splitlines() if handler._JOURNAL_PERMALINK_RE.match(ln.split("\t", 1)[0])]
    assert offenders == [], f"journal permalink redirect source(s) re-armed in redirects.map: {offenders} (#3284)"
