"""tests/test_edition_verify_live_shape_6193.py — two defects Week 10's publication exposed (#6193).

1. ``scripts/chronicle_edition_verify.py`` crashed on the LIVE ``/api/chapters`` shape: retired, skipped and pending weeks
   are served with ``"url": null`` and ``"title": null`` (a present key whose value is None), so ``w.get("url", "")``
   returned None and ``.rstrip`` raised — the CLI printed UNREADABLE for every chapter. The fixture below is that shape
   (taken from a read-only fetch of the live route; synthetic values). The rehearsal now runs the verifier itself over
   the live response shape, so the same crash is a BLOCKED row there, not a surprise after publication.
2. The site deploy's route sweep expected 200 from ``/api/brief_response``, a token-only owner door that answers 404
   without a token by design. A door the API-schema census declares auth-gated is swept for its REFUSAL status.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from content import chapter_editions as CE  # noqa: E402
from test_chapter_editions_6193 import TEXT, _edition, _original, _sha, _view  # noqa: E402

BASE = "https://s"


def _week(n, status, **kw):
    """One week as /api/chapters serves it (keys and null-ness from the live route; values synthetic)."""
    w = {"week": n, "start": "2026-09-06", "end": "2026-09-12", "status": status, "date": None, "title": None, "url": None}
    w.update({"label": None, "drafted_at": None, "reason": None})
    w.update(kw)
    return w


def _live_shape(editions):
    return {
        "genesis": "2026-09-06",
        "as_of": "2026-11-23",
        "week_length_days": 7,
        "held": None,
        "counts": {},
        "corrections": [],
        # the null rows come BEFORE the chapter's own week, as they do live (a skipped or retired week precedes a later
        # published one), so a lookup that walks the list meets a null url first
        "weeks": [
            _week(1, "skipped", reason="a synthetic reason"),
            _week(2, "retired", drafted_at="2026-09-22T12:00:00+00:00"),
            _week(
                3,
                "published",
                date="2026-09-22",
                title="A Sample Chapter",
                url="/journal/posts/week-04/",
                label="Week 3",
                published_at="2026-09-25T18:00:00+00:00",
            ),
            _week(4, "pending"),
        ],
        "editions": editions,
    }


def _page(e):
    body = CE.render_html(CE.presentation(TEXT)["body"])
    return (
        f'<h1>A Sample Chapter</h1><p class="dek">{e["summary"]}</p>'
        f'<p data-edition-line><b>{e["edition_line"]}</b></p><article><div data-published-body>{body}</div></article>'
    )


def test_the_verifier_reads_the_live_shape_with_null_urls():
    import chronicle_edition_verify as V

    (e,) = _view([_original(), _edition(2)])
    site = {
        f"{BASE}/api/chapters": json.dumps(_live_shape([e])),
        f"{BASE}/story/week-04/": _page(e),
        f"{BASE}/rss.xml": f'<guid isPermaLink="true">{BASE}/journal/posts/week-04/</guid>',
    }
    assert V.verify(site.__getitem__, "week-04", _sha(TEXT), base=BASE) == []  # crashed with AttributeError before
    site[f"{BASE}/rss.xml"] = ""  # and the feed check still runs past the null rows
    assert any("0 time(s)" in p for p in V.verify(site.__getitem__, "week-04", _sha(TEXT), base=BASE))


def test_the_rehearsal_runs_the_verifier_over_the_live_shape_and_reports_a_crash_as_blocked(tmp_path, monkeypatch):
    import chronicle_edition_rehearsal as R
    import chronicle_edition_verify as V

    (e,) = _view([_original(), _edition(2)])
    dist = tmp_path / "dist"
    (dist / "story" / "week-04").mkdir(parents=True)
    (dist / "story" / "week-04" / "index.html").write_text(_page(e), encoding="utf-8")
    (tmp_path / "rss.xml").write_text(f'<guid isPermaLink="true">{BASE}/journal/posts/week-04/</guid>', encoding="utf-8")
    monkeypatch.setattr(R, "DIST", str(dist))
    live = json.dumps(_live_shape([]))
    results = {"week-04": {"verify": None}}
    R.live_verify(results, {"week-04": e}, str(tmp_path), BASE, fetch=lambda url: live)
    assert results["week-04"]["verify"] is None  # the live shape, the rehearsal's edition placed in it: verified

    def crashing(get, cid, sha, **kw):
        raise AttributeError("'NoneType' object has no attribute 'rstrip'")

    monkeypatch.setattr(V, "verify", crashing)
    R.live_verify(results, {"week-04": e}, str(tmp_path), BASE, fetch=lambda url: live)
    assert "crashed on the live response shape" in results["week-04"]["verify"]


def test_a_token_only_door_is_swept_for_its_refusal():
    import api_sweep_check as S

    from qa import qa_manifest

    exemptions = json.load(open(os.path.join(_REPO, "tests", "api_schemas", "_exemptions.json"), encoding="utf-8"))
    auth_gated = {k for k, v in exemptions.items() if isinstance(v, dict) and v.get("category") == "auth-gated"}
    rows = {r["route"]: r for r in qa_manifest.api_sweep_records()}
    swept = auth_gated & set(rows)
    assert "/api/brief_response" in swept
    for route in swept:  # every declared auth-gated door the sweep reaches expects its refusal, never a 200
        assert rows[route]["expect"] != "200", route
    rec = rows["/api/brief_response"]
    assert rec["expect"] == "404"
    assert S.verdict(rec, 404, b"", set())[0] == "PASS"
    assert S.verdict(rec, 200, b"<html>open</html>", set())[0] == "FAIL"  # a door that opened without a token fails
