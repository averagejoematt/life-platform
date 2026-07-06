"""#729/#730 — build-time static proof blocks (scripts/v4_proof.py).

Verifies the served HTML the scorecard/chronicle builders bake carries real,
crawlable content with an honest 'as of' stamp — and NEVER fabricates when data
is missing. Pure-logic: the live fetch is monkeypatched, so no network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import v4_proof  # noqa: E402


class TestScorecardBlock:
    def test_zero_graded_is_honest_empty_state(self):
        sc = {"total": 385, "decided": 0, "pending": 309, "evaluator_live_since": "2026-06-14", "as_of": "2026-07-06"}
        html = v4_proof.scorecard_block_html(sc)
        # #729 AC: the honest sentence is carried in no-JS HTML.
        assert "0 graded yet" in html
        assert "Evaluator live since 2026-06-14" in html
        assert "309 predictions pending" in html
        assert "as of 2026-07-06" in html
        # rich view is JS; the static block is inert once scripts run.
        assert html.startswith("<noscript>") and html.endswith("</noscript>")

    def test_flips_to_hit_rate_once_graded(self):
        sc = {"total": 400, "decided": 20, "pending": 300, "accuracy_pct": 65.0, "as_of": "2026-08-01"}
        html = v4_proof.scorecard_block_html(sc)
        assert "20 graded" in html
        assert "65% hit-rate" in html
        assert "0 graded yet" not in html

    def test_missing_data_omits_block_never_fabricates(self):
        assert v4_proof.scorecard_block_html({}) == ""
        assert v4_proof.scorecard_block_html(None) == ""

    def test_no_live_since_degrades_gracefully(self):
        html = v4_proof.scorecard_block_html({"decided": 0, "pending": 5, "as_of": "2026-07-06"})
        assert "Evaluator live." in html  # no bogus date
        assert "5 predictions pending" in html


class TestChronicleList:
    # As load_chronicle() feeds it: already newest-first.
    POSTS = [
        {"date": "2026-06-30", "title": "The Wall", "url": "/journal/posts/week-05/", "label": "Week 3"},
        {"date": "2026-06-07", "title": "The Body Votes First", "url": "/journal/posts/week-01/", "label": "Week 1"},
    ]

    def test_renders_dated_list_preserving_order(self):
        html = v4_proof.chronicle_list_html(self.POSTS)
        assert "<noscript>" in html
        assert '<time datetime="2026-06-30">2026-06-30</time> — The Wall' in html
        assert '<time datetime="2026-06-07">2026-06-07</time> — The Body Votes First' in html
        # render preserves loader order (newest first)
        assert html.index("The Wall") < html.index("The Body Votes First")

    def test_loader_sorts_newest_first(self, monkeypatch):
        # load_chronicle() is the sorter; give it out-of-order posts.
        monkeypatch.setattr(
            v4_proof,
            "_fetch_json",
            lambda path, timeout=8: {
                "posts": [
                    {"date": "2026-06-07", "title": "old"},
                    {"date": "2026-06-30", "title": "new"},
                ]
            },
        )
        out = v4_proof.load_chronicle()
        assert [p["title"] for p in out] == ["new", "old"]

    def test_empty_omits_block(self):
        assert v4_proof.chronicle_list_html([]) == ""

    def test_escapes_html_in_titles(self):
        html = v4_proof.chronicle_list_html([{"date": "2026-06-01", "title": "A <b>bold</b> & risky week", "url": "/x/"}])
        assert "&lt;b&gt;bold&lt;/b&gt;" in html
        assert "&amp;" in html
        assert "<b>bold</b>" not in html


class TestFallback:
    def test_scorecard_falls_back_to_snapshot_offline(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "_fetch_json", lambda path, timeout=8: None)
        monkeypatch.setattr(v4_proof, "_snapshot", lambda: {"scorecard": {"decided": 0, "pending": 42}})
        assert v4_proof.load_scorecard() == {"decided": 0, "pending": 42}

    def test_chronicle_falls_back_to_snapshot_offline(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "_fetch_json", lambda path, timeout=8: None)
        monkeypatch.setattr(v4_proof, "_snapshot", lambda: {"chronicle": [{"title": "x", "date": "2026-01-01"}]})
        assert v4_proof.load_chronicle() == [{"title": "x", "date": "2026-01-01"}]

    def test_committed_snapshot_is_valid_and_present(self):
        # the offline fallback must exist and parse (an offline CI build depends on it)
        import json

        snap = json.loads((Path(__file__).resolve().parent.parent / "scripts" / "proof_snapshot.json").read_text())
        assert "scorecard" in snap and "chronicle" in snap
        assert snap["scorecard"].get("evaluator_live_since")


class TestEscape:
    def test_esc(self):
        assert v4_proof._esc('<a href="x">&') == "&lt;a href=&quot;x&quot;&gt;&amp;"
