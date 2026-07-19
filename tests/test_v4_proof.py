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


class TestCockpitBlock:
    """#788 — the cockpit's static proof: level + tier + pillar scores + as-of."""

    CH = {
        "level": 12,
        "tier": "Foundation",
        "as_of": "2026-07-06",
        "pillars": {
            "sleep": {"raw_score": 82.9, "tier": "Momentum"},
            "movement": {"raw_score": 25.8, "tier": "Foundation"},
            "nutrition": {"raw_score": 1.6, "tier": "Foundation"},
            "metabolic": {"raw_score": 59.4, "tier": "Foundation"},
            "mind": {"raw_score": 15.9, "tier": "Foundation"},
            "relationships": {"raw_score": 50.0, "tier": "Foundation"},
            "consistency": {"raw_score": 32.5, "tier": "Foundation"},
        },
    }

    def test_bakes_level_pillars_and_as_of(self):
        html = v4_proof.cockpit_block_html(self.CH)
        # #788 AC: real numbers + the honest stamp in the served no-JS HTML.
        assert "Character level 12 · Foundation" in html
        assert "as of 2026-07-06" in html
        assert "Sleep 83" in html and "Momentum" in html
        assert "Movement 26" in html and "Nutrition 2" in html
        assert "Consistency 33" in html  # rounded, same as cockpit.js
        assert html.startswith("<noscript>") and html.endswith("</noscript>")

    def test_rollups_match_cockpit_js_semantics(self):
        # Body = mean(movement, nutrition, sleep, metabolic); Mind = mean(mind, relationships).
        html = v4_proof.cockpit_block_html(self.CH)
        assert "Body 42" in html  # (25.8+1.6+82.9+59.4)/4 = 42.4 → 42
        assert "Mind 33" in html  # (15.9+50.0)/2 = 32.95 → 33

    def test_missing_pillar_is_omitted_never_zeroed(self):
        ch = {"level": 8, "tier": "Foundation", "as_of": "2026-07-06", "pillars": {"sleep": {"raw_score": 70.0, "tier": ""}}}
        html = v4_proof.cockpit_block_html(ch)
        assert "Sleep 70" in html
        # ADR-104: absent pillars never render as fabricated zeros.
        assert "Nutrition" not in html and "Movement" not in html
        assert "Mind 0" not in html and "Consistency" not in html

    def test_missing_data_omits_block_never_fabricates(self):
        assert v4_proof.cockpit_block_html({}) == ""
        assert v4_proof.cockpit_block_html(None) == ""
        assert v4_proof.cockpit_block_html({"tier": "Foundation"}) == ""  # no level → no block

    def test_loader_parses_live_api_shape(self, monkeypatch):
        monkeypatch.setattr(
            v4_proof,
            "_fetch_json",
            lambda path, timeout=8: {
                "character": {"level": 12.0, "tier": "Foundation", "as_of_date": "2026-07-06"},
                "pillars": [
                    {"name": "sleep", "raw_score": 82.9, "tier": "Momentum"},
                    {"name": "movement", "raw_score": None, "tier": "Foundation"},  # absent value → dropped
                ],
            },
        )
        out = v4_proof.load_character()
        assert out["level"] == 12 and out["tier"] == "Foundation" and out["as_of"] == "2026-07-06"
        assert out["pillars"] == {"sleep": {"raw_score": 82.9, "tier": "Momentum"}}
        assert out["source"] == "live"

    def test_loader_falls_back_to_snapshot_offline(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "_fetch_json", lambda path, timeout=8: None)
        monkeypatch.setattr(v4_proof, "_snapshot", lambda: {"cockpit": {"level": 9, "as_of": "2026-07-01", "pillars": {}}})
        assert v4_proof.load_character() == {"level": 9, "as_of": "2026-07-01", "pillars": {}}


class TestCockpitInjection:
    """#788 — v4_build_cockpit_proof.inject(): sentinel-delimited, idempotent."""

    SHELL = (
        '<main id="cockpit">\n'
        '    <article class="panel" aria-busy="true">\n'
        '      <span data-bind="level">··</span>\n'
        "    </article>\n"
        "</main>"
    )

    def _mod(self):
        import v4_build_cockpit_proof

        return v4_build_cockpit_proof

    def test_first_injection_lands_before_the_panel(self):
        mod = self._mod()
        block = v4_proof.cockpit_block_html(TestCockpitBlock.CH)
        out = mod.inject(self.SHELL, block)
        assert out is not None
        assert mod._START in out and mod._END in out
        assert "Character level 12" in out
        # baked block precedes the JS app shell
        assert out.index(mod._START) < out.index('<article class="panel"')

    def test_reinjection_replaces_in_place(self):
        mod = self._mod()
        once = mod.inject(self.SHELL, v4_proof.cockpit_block_html(TestCockpitBlock.CH))
        newer = dict(TestCockpitBlock.CH, level=13, as_of="2026-07-07")
        twice = mod.inject(once, v4_proof.cockpit_block_html(newer))
        assert twice.count(mod._START) == 1 and twice.count(mod._END) == 1
        assert "Character level 13" in twice and "Character level 12" not in twice
        assert "as of 2026-07-07" in twice

    def test_no_anchor_returns_none(self):
        assert self._mod().inject("<html><body>nope</body></html>", "<noscript>x</noscript>") is None

    def test_committed_now_page_carries_the_baked_block(self):
        # The #788 acceptance test: the DELIVERED /cockpit/ HTML carries real static
        # content — curl-visible, no JS required.
        html = (Path(__file__).resolve().parent.parent / "site" / "cockpit" / "index.html").read_text(encoding="utf-8")
        assert "cockpit-proof:start" in html
        assert "<noscript>" in html
        assert "Character level" in html
        assert "as of 20" in html  # a dated honesty stamp

    def test_committed_now_page_carries_the_first_visit_hint(self):
        # #807: the inline explainer markup ships in the HTML (hidden; JS unhides
        # it for first-time visitors only).
        html = (Path(__file__).resolve().parent.parent / "site" / "cockpit" / "index.html").read_text(encoding="utf-8")
        assert "data-hub-hint" in html
        assert "1&ndash;100 score" in html
        assert "hub-hint-x" in html


class TestCoachingReadBlock:
    """#804 (R22-UX-02) — the coaching page's static proof: the board's read baked
    into /coaching/ so a no-JS visitor / crawler / LLM sees the coach voices, not a
    shell."""

    READ = {
        "weekly_priority": {"text": "Restart your logging this week — the system runs blind without it.", "coach_name": "Dr. Kai Nakamura"},
        "coaches": [
            {
                "name": "Dr. Nathan Reeves",
                "title": "Psychiatrist — Behavioral Patterns",
                "coach_id": "mind",
                "position_summary": "Food logging ceased on June 24th — twelve days of silence.",
            },
            {
                "name": "Dr. Victor Reyes",
                "title": "Longevity & Body Composition",
                "coach_id": "physical",
                "position_summary": "Twelve days without logged meals created a blind spot.",
            },
        ],
        "as_of": "2026-07-07",
    }

    def test_bakes_priority_and_each_coach_read(self):
        html = v4_proof.coaching_read_block_html(self.READ)
        # the AC: actual coach voices are carried in the served no-JS HTML.
        assert "Restart your logging this week" in html
        assert "Dr. Kai Nakamura" in html
        # #1115: the integrator's priority is labeled at its true (week) altitude,
        # never presented as today's line.
        assert "The week's call" in html
        assert "Dr. Nathan Reeves" in html and "Psychiatrist" in html
        assert "twelve days of silence" in html
        assert "Dr. Victor Reyes" in html
        assert "as of 2026-07-07" in html
        assert html.startswith("<noscript>") and html.endswith("</noscript>")

    def test_priority_only_still_renders(self):
        html = v4_proof.coaching_read_block_html(
            {"weekly_priority": {"text": "One clear call.", "coach_name": ""}, "coaches": [], "as_of": "2026-07-07"}
        )
        assert "One clear call." in html
        assert "Each coach" not in html  # no roster section when no coach has a read

    def test_coaches_only_still_renders(self):
        html = v4_proof.coaching_read_block_html(
            {"weekly_priority": {}, "coaches": [{"name": "Dr. X", "title": "", "position_summary": "A read."}], "as_of": "2026-07-07"}
        )
        assert "A read." in html and "Dr. X" in html
        # #1115: the priority block is labeled at week altitude now
        assert "The week's call" not in html and "The one priority" not in html  # no priority block when text is absent

    def test_missing_data_omits_block_never_fabricates(self):
        # ADR-104: no content -> no block; the JS view still renders.
        assert v4_proof.coaching_read_block_html({}) == ""
        assert v4_proof.coaching_read_block_html(None) == ""
        assert v4_proof.coaching_read_block_html({"weekly_priority": {}, "coaches": []}) == ""

    def test_escapes_html_in_coach_content(self):
        html = v4_proof.coaching_read_block_html(
            {"weekly_priority": {"text": "<b>hi</b> & bye", "coach_name": "A & B"}, "coaches": [], "as_of": "2026-07-07"}
        )
        assert "&lt;b&gt;hi&lt;/b&gt;" in html and "&amp;" in html
        assert "<b>hi</b>" not in html

    def test_loader_parses_live_api_shape(self, monkeypatch):
        # #949: disarm the pre-start short-circuit — this test pins the POST-start
        # loader, and must not flip red whenever a reset stages a future genesis.
        monkeypatch.setattr(v4_proof, "pre_start_date", lambda: "")
        monkeypatch.setattr(
            v4_proof,
            "_fetch_json",
            lambda path, timeout=8: {
                "_meta": {"generated_at": "2026-07-08T01:31:08+00:00"},
                "weekly_priority": {"text": " the call ", "coach_name": "Dr. Kai Nakamura", "generated_at": "2026-07-07T14:03:02+00:00"},
                "coaches": [
                    {"coach_id": "mind", "name": "Dr. Nathan Reeves", "title": "Psychiatrist", "position_summary": " a read "},
                    {"coach_id": "sleep", "name": "Dr. Lisa Park", "title": "Sleep", "position_summary": ""},  # empty -> dropped
                ],
            },
        )
        out = v4_proof.load_coaching_read()
        assert out["weekly_priority"] == {"text": "the call", "coach_name": "Dr. Kai Nakamura"}
        # honest absence — the coach with an empty read is omitted, never fabricated.
        assert [c["coach_id"] for c in out["coaches"]] == ["mind"]
        assert out["coaches"][0]["position_summary"] == "a read"
        # honest stamp prefers the priority's own generation date.
        assert out["as_of"] == "2026-07-07"
        assert out["source"] == "live"

    def test_loader_falls_back_to_snapshot_offline(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "pre_start_date", lambda: "")  # #949 — pin the post-start path
        monkeypatch.setattr(v4_proof, "_fetch_json", lambda path, timeout=8: None)
        monkeypatch.setattr(v4_proof, "_snapshot", lambda: {"coaching_read": self.READ})
        assert v4_proof.load_coaching_read() == self.READ


class TestCoachingReadCommitted:
    """#804 — the DELIVERED /coaching/ HTML carries the board's read: curl-visible, no JS.

    Reset-aware (ADR-104): right after an experiment reset the board legitimately
    has no reads yet — coaching_read_block_html() bakes nothing rather than
    fabricating (a coach with no live read is omitted, never invented), so the
    committed HTML can honestly ship WITHOUT the proof block (or with the priority
    but no per-coach roster) until Day-1 content exists. The invariant pinned here
    is therefore conditional: IF a baked read ships it must be well-formed (dated
    stamp + real content; a roster header only ever with actual coach rows); if
    none ships, the page must be the clean JS shell with no half-baked artifacts.
    """

    def _html(self, rel):
        return (Path(__file__).resolve().parent.parent / "site" / "coaching" / rel).read_text(encoding="utf-8")

    def _assert_baked_read_or_honest_placeholder(self, html):
        if "The board's read on the data" in html:
            # a baked read ships → it must be the full #804 treatment, well-formed:
            assert "<noscript>" in html
            assert "as of 20" in html  # a dated honesty stamp
            # real content: the integrator's priority and/or the per-coach roster —
            # never a bare header with nothing under it.
            assert "<blockquote>" in html or "Each coach" in html
            if "Each coach" in html:
                assert "<ul><li>" in html, "roster header present but no coach rows baked"
        else:
            # honest pre-start/post-reset placeholder: no fabricated or partial proof
            assert "Each coach's read" not in html
            assert "<blockquote>" not in html
            # the live board still boots via JS once content exists
            assert "coaching.js" in html

    def test_index_carries_the_baked_read(self):
        self._assert_baked_read_or_honest_placeholder(self._html("index.html"))

    def test_read_section_carries_the_baked_read(self):
        # the "read" landing (the default section URL) ships the same proof-or-honest state.
        self._assert_baked_read_or_honest_placeholder(self._html("read/index.html"))


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
        # pre-genesis the evaluator hasn't run, so the honest snapshot value is "" —
        # require the key, not a value (#941 reset-aware pattern; render copes with "")
        assert "evaluator_live_since" in snap["scorecard"]
        # #788: the cockpit fallback must carry a level + as-of (honest stamp)
        assert snap["cockpit"].get("level") is not None
        assert snap["cockpit"].get("as_of")


class TestEscape:
    def test_esc(self):
        assert v4_proof._esc('<a href="x">&') == "&lt;a href=&quot;x&quot;&gt;&amp;"


class TestPreStartProof:
    """#949 — with a staged FUTURE genesis, the coaching proof bakes the countdown
    truth: never the wiped prior cycle's board read (the live dashboard AND the
    committed snapshot both carried it at T−1), and never a fetch that could
    resurrect it. Post-start, the pre-start path goes inert."""

    def test_pre_start_date_future_genesis(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "_experiment_start", lambda: "2099-01-01")
        assert v4_proof.pre_start_date() == "2099-01-01"

    def test_pre_start_date_inert_once_started(self, monkeypatch):
        monkeypatch.setattr(v4_proof, "_experiment_start", lambda: "2001-01-01")
        assert v4_proof.pre_start_date() == ""
        monkeypatch.setattr(v4_proof, "_experiment_start", lambda: "")
        assert v4_proof.pre_start_date() == ""

    def test_loader_short_circuits_pre_start_never_fetches(self, monkeypatch):
        def _boom(path, timeout=8):
            raise AssertionError("pre-start build must not fetch the (possibly stale) dashboard")

        monkeypatch.setattr(v4_proof, "_fetch_json", _boom)
        monkeypatch.setattr(v4_proof, "pre_start_date", lambda: "2099-01-09")
        out = v4_proof.load_coaching_read()
        assert out["pre_start"] is True
        assert out["start_date"] == "2099-01-09"

    def test_pre_start_block_is_countdown_not_board_read(self):
        html = v4_proof.coaching_read_block_html({"pre_start": True, "start_date": "2026-07-12", "as_of": "2026-07-11"})
        assert html.startswith("<noscript>") and html.endswith("</noscript>")
        assert "The experiment begins" in html and "Sunday, July 12" in html
        assert "as of 2026-07-11" in html
        # the committed-HTML contract (TestCoachingReadCommitted else-branch):
        # no prior-cycle board-read markup may ship pre-start.
        assert "The board's read on the data" not in html
        assert "Each coach's read" not in html
        assert "<blockquote>" not in html

    def test_snapshot_coaching_read_is_neutralized(self):
        # #949: the committed fallback must not carry a prior cycle's board read —
        # an offline build bakes honest nothing instead (block omitted).
        import json

        snap = json.loads((Path(__file__).resolve().parent.parent / "scripts" / "proof_snapshot.json").read_text())
        assert snap.get("coaching_read") == {}
        assert v4_proof.coaching_read_block_html(snap["coaching_read"]) == ""


class TestGrowthSurface1395:
    """#1395 — static core + data-driven OG on Home + the doors (the crawler view)."""

    PRE_START = {
        "start_weight": 315.6,
        "goal_weight": 185.0,
        "pre_start": True,
        "start_date": "2026-07-19",
        "day_n": 0,
        "as_of": "2026-07-19",
    }
    CHAR = {"level": 1, "tier": "Foundation", "as_of": "2026-07-18"}

    def test_home_block_is_real_content_with_provenance(self):
        html = v4_proof.home_block_html(self.PRE_START, self.CHAR)
        assert html.startswith("<noscript>") and html.endswith("</noscript>")
        assert 'class="proof-static' in html
        assert "as of 2026-07-19" in html  # ADR-104 honest-provenance stamp
        assert "316 lb" in html and "185 lb" in html  # real, rounded numbers
        assert "131 lb climb" in html
        assert "Character level 1 · Foundation" in html

    def test_home_block_post_start_uses_day_and_progress(self):
        j = {
            "start_weight": 315.6,
            "goal_weight": 185.0,
            "pre_start": False,
            "day_n": 12,
            "current_weight": 308.0,
            "lost_lbs": 7.6,
            "as_of": "2026-08-01",
        }
        html = v4_proof.home_block_html(j, self.CHAR)
        assert "Day 12." in html
        assert "308 lb now, 8 lb down" in html

    def test_home_block_omits_when_no_numbers(self):
        assert v4_proof.home_block_html({}, {}) == ""
        assert v4_proof.home_block_html(None, None) == ""

    def test_home_og_carries_falsifiable_number(self):
        og = v4_proof.home_og(self.PRE_START, self.CHAR)
        title = og[("property", "og:title")]
        desc = og[("property", "og:description")]
        assert "316 lb → 185 lb" in title  # a number in the unfurl title
        assert "Sunday, July 19" in desc and "as of 2026-07-19".lower() in desc.lower()
        assert og[("property", "og:image")].endswith("/og-home.png")

    def test_data_block_and_og_from_source_freshness(self):
        summary = {"total": 13, "fresh": 7, "labels": ["Whoop", "Withings", "Strava"], "as_of": "2026-07-19"}
        html = v4_proof.data_block_html(summary)
        assert "13 sources on the board, 7 fresh" in html
        assert "<li>Whoop</li>" in html  # the real roster is crawlable
        assert "as of 2026-07-19" in html
        og = v4_proof.data_og(summary)
        assert "13 sources, 7 fresh" in og[("property", "og:title")]

    def test_data_block_omits_when_empty(self):
        assert v4_proof.data_block_html({}) == ""
        assert v4_proof.data_block_html({"total": 0}) == ""

    def test_protocols_block_and_og_from_experiments(self):
        summary = {"total": 67, "available": 4, "as_of": "2026-07-19"}
        html = v4_proof.protocols_block_html(summary)
        assert "67 experiments in the library, 4 ready to run now" in html
        assert "as of 2026-07-19" in html
        og = v4_proof.protocols_og(summary)
        assert "67 experiments in the library" in og[("property", "og:title")]
        assert og[("property", "og:image")].endswith("/og-experiments.png")

    def test_cockpit_og_carries_level(self):
        og = v4_proof.cockpit_og(self.CHAR)
        assert "character level 1 · Foundation" in og[("property", "og:title")]
        assert og[("property", "og:image")].endswith("/og-character.png")

    def test_story_og_counts_dispatches(self):
        posts = [{"title": "A"}, {"title": "B"}, {"title": ""}]
        og = v4_proof.story_og(posts)
        assert "2 dispatches published" in og[("property", "og:title")]
        assert og[("property", "og:image")].endswith("/og-chronicle.png")

    def test_apply_og_replaces_existing_and_inserts_missing(self):
        html = '<head>\n  <meta name="description" content="d">\n  <meta property="og:title" content="OLD">\n</head>'
        og = {("property", "og:title"): "NEW", ("name", "twitter:title"): "TW"}
        out = v4_proof.apply_og(html, og)
        assert 'content="OLD"' not in out
        assert '<meta property="og:title" content="NEW">' in out
        assert '<meta name="twitter:title" content="TW">' in out
        # idempotent: a second pass yields identical output
        assert v4_proof.apply_og(out, og) == out

    def test_apply_og_escapes_ampersand(self):
        html = '<head>\n  <meta name="description" content="d">\n</head>'
        out = v4_proof.apply_og(html, {("property", "og:title"): "A & B"})
        assert "A &amp; B" in out
