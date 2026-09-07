def test_payload_is_empty_discriminates_affirmative_absence():
    """#2500 rollback loop (2026-08-10): the genesis dark-state downgrade fires
    ONLY on an affirmatively empty payload — unrecognized shapes stay gating."""
    from visual_qa import _payload_is_empty

    assert _payload_is_empty([]) is True
    assert _payload_is_empty({"_meta": {}, "items": [], "total_count": 0}) is True
    assert _payload_is_empty({"_meta": {}, "active_hypotheses": [{"a": 1}], "ai_findings": []}) is False
    assert _payload_is_empty([{"x": 1}]) is False
    assert _payload_is_empty({"_meta": {}}) is False  # no lists, no counts — unknown, stays gating
    assert _payload_is_empty("nonsense") is False


def test_payload_is_empty_recognizes_declared_absence():
    """2026-08-22 (run 32547631137): /api/autonomic_balance's engine-declared
    absence — `available: false` + a non-empty `reason`, the exact shape the
    front-end renderers branch on — was unrecognized (no lists, no count keys),
    so the genesis discrimination refused it and a healthy site deploy
    auto-rolled-back on cycle Day 5 of a 7-day minimum. The declared-absence
    arm is scoped: available must be literal False and reason a non-empty
    string; everything else keeps the fail-closed default."""
    from visual_qa import _payload_is_empty

    # the live 2026-08-22 payload shape
    assert (
        _payload_is_empty(
            {"_meta": {}, "available": False, "reason": "Need at least 7 days — 5 so far.", "days_with_data": 5, "min_days": 7}
        )
        is True
    )
    # scoping: truthy available, missing/blank reason, or non-bool shapes stay gating
    assert _payload_is_empty({"available": True, "reason": "x"}) is False
    assert _payload_is_empty({"available": False}) is False
    assert _payload_is_empty({"available": False, "reason": ""}) is False
    assert _payload_is_empty({"available": False, "reason": "  "}) is False
    assert _payload_is_empty({"available": 0, "reason": "x"}) is False  # falsy-but-not-False stays gating
    # declared absence wins even when count-shaped keys ride along non-zero
    assert _payload_is_empty({"available": False, "reason": "warming up", "days_with_data": 5, "min_days": 7, "total_count": 5}) is True


def test_visual_pages_carry_api_deps():
    """The sweep can only probe honest emptiness if the manifest rides the deps."""
    from qa_manifest import visual_pages

    disc = [p for p in visual_pages() if p["path"] == "/protocols/discoveries/"]
    assert disc and disc[0]["api_deps"] == ["/api/discoveries"]


def test_html_text_floor_pages_are_in_the_sweep_manifest():
    """#2674: the HTML-text floor gate fires only for paths in TEXT_FLOOR_PAGES —
    a gating page missing from the sweep manifest would make the gate a no-op
    (the 'gate that cannot fail' class). Pin the set AND its presence in the sweep."""
    from qa_manifest import visual_pages
    from visual_qa import TEXT_FLOOR_PAGES

    assert TEXT_FLOOR_PAGES == {"/", "/cockpit/", "/data/"}
    swept = {p["path"] for p in visual_pages()}
    missing = TEXT_FLOOR_PAGES - swept
    assert not missing, f"TEXT_FLOOR_PAGES not in the visual sweep manifest: {missing}"


def test_html_text_floor_audit_excludes_svg_and_shares_the_1210_floor():
    """#2674 rides the SAME 11px constant as the #1210 svg audit (one floor, §10.5),
    and its JS must skip svg <text> — that surface is #1210's, with CTM scaling the
    computed-size-only walk here would misread."""
    from visual_qa import _HTML_TEXT_AUDIT_JS, SVG_TEXT_FLOOR_PX

    assert SVG_TEXT_FLOOR_PX == 11.0
    assert "closest('svg')" in _HTML_TEXT_AUDIT_JS


def test_html_text_floor_findings_dedupes_and_sorts():
    """The findings helper aggregates identical (selector, size) pairs with a count
    and sorts smallest-first, so one repeated label class reads as one finding."""
    from visual_qa import _html_text_floor_findings

    class FakePage:
        def set_viewport_size(self, _):
            pass

        def wait_for_timeout(self, _):
            pass

        def evaluate(self, _js, _floor):
            return [
                {"sel": "span.vr-l.label", "txt": "recovery", "eff": 9.28},
                {"sel": "span.vr-l.label", "txt": "sleep", "eff": 9.28},
                {"sel": "span.vr-sub.label", "txt": "h", "eff": 8.8},
            ]

    out = _html_text_floor_findings(FakePage(), 390)
    assert [(f["sel"], f["eff"], f["n"]) for f in out] == [
        ("span.vr-sub.label", 8.8, 1),
        ("span.vr-l.label", 9.28, 2),
    ]


def test_html_text_floor_findings_swallow_evaluate_failure():
    """A page that cannot be evaluated yields NO findings (the sweep's other audits
    share this shape) — but never a crash mid-sweep."""
    from visual_qa import _html_text_floor_findings

    class BrokenPage:
        def set_viewport_size(self, _):
            pass

        def wait_for_timeout(self, _):
            pass

        def evaluate(self, _js, _floor):
            raise RuntimeError("detached")

    assert _html_text_floor_findings(BrokenPage(), 390) == []


# ── #3542 — the mobile FIRST-LOAD contract (DES-1 auto-scroll, DES-3 see-through bar) ──
# These drive visual_qa.mobile_first_load_findings with the EXACT live observations the
# 2026-09-05 /review full recorded, so the gate is proven to fail on the pre-fix world
# rather than merely proven to pass on the post-fix one.

_CLEAN_PROBE = {
    "hero_present": True,
    "hero_doc_top": 96.0,
    "hero_doc_bottom": 501.0,
    "viewport_h": 844,
    "top_bars": [{"sel": "ev-top", "position": "sticky", "backdrop_filter": "none", "background_color": "oklch(0.15 0.008 75)"}],
}


def test_mobile_first_load_passes_a_page_that_does_not_move():
    from visual_qa import mobile_first_load_findings

    samples = [(250, 0), (800, 0), (1600, 0), (2600, 0)]
    assert mobile_first_load_findings("/data/physical/", samples, _CLEAN_PROBE) == []


def test_mobile_first_load_catches_the_des1_self_scroll():
    """The live /data/physical/ measurement at 390x844, fresh context, NO input:
    scrollY = [0, 1297, 1297, 1297] at 200/800/1500/3000ms (hero at y = -1218).
    Before #3542 no gate could see this — every mobile assertion ran on a page the
    harness had already loaded at desktop and scrolled itself."""
    from visual_qa import mobile_first_load_findings

    samples = [(250, 0), (800, 1297), (1600, 1297), (2600, 1297)]
    probe = dict(_CLEAN_PROBE, hero_doc_top=79.0, hero_doc_bottom=484.0)
    findings = mobile_first_load_findings("/data/physical/", samples, probe)
    assert len(findings) == 1
    assert "scrolled itself on FIRST LOAD" in findings[0]
    assert "800ms=1297" in findings[0]


def test_mobile_first_load_catches_a_hero_outside_the_first_screen():
    """Second half of the DES-1 acceptance: the .page-hero must intersect the first
    viewport. Measured in DOCUMENT coordinates, so a page that never scrolls but
    lays its hero below the fold still fails."""
    from visual_qa import mobile_first_load_findings

    samples = [(250, 0), (800, 0)]
    probe = dict(_CLEAN_PROBE, hero_doc_top=1300.0, hero_doc_bottom=1705.0)
    findings = mobile_first_load_findings("/data/physical/", samples, probe)
    assert len(findings) == 1
    assert ".page-hero does not intersect the first viewport" in findings[0]
    # A page with no hero at all is not a violation — the check is "where present".
    assert mobile_first_load_findings("/404.html", samples, dict(_CLEAN_PROBE, hero_present=False, hero_doc_top=None)) == []


def test_mobile_first_load_catches_the_des3_see_through_top_bar():
    """The live computed value at 390px before the fix: background
    `oklch(0.15 0.008 75 / 0.82)` with backdropFilter `none` — the @media (max-width:
    600px) block stripped the blur (#1007) and left the alpha, so tile prose read
    straight through the sticky bar."""
    from visual_qa import mobile_first_load_findings

    samples = [(250, 0), (800, 0)]
    probe = dict(
        _CLEAN_PROBE,
        top_bars=[{"sel": "ev-top", "position": "sticky", "backdrop_filter": "none", "background_color": "oklch(0.15 0.008 75 / 0.82)"}],
    )
    findings = mobile_first_load_findings("/data/physical/", samples, probe)
    assert len(findings) == 1
    assert "0.82-alpha with backdrop-filter: none" in findings[0]
    # A translucent bar that KEEPS its blur is the designed treatment, not a finding.
    kept_blur = dict(
        _CLEAN_PROBE,
        top_bars=[
            {"sel": "story-top", "position": "sticky", "backdrop_filter": "blur(10px)", "background_color": "oklch(0.15 0.008 75 / 0.82)"}
        ],
    )
    assert mobile_first_load_findings("/story/", samples, kept_blur) == []


def test_css_alpha_reads_every_computed_syntax_and_fails_open():
    """#3542 — the alpha parser is the DES-3 verdict's only sensor. The live bar
    computed as oklch(… / 0.82), not rgba(…), because the declaration is a
    color-mix(in oklch, …); a parser that only knew rgba() would have reported the
    bar opaque and the gate would have been vacuous."""
    from visual_qa import _css_alpha

    assert _css_alpha("oklch(0.15 0.008 75 / 0.82)") == 0.82
    assert _css_alpha("rgba(14, 12, 8, 0.82)") == 0.82
    assert _css_alpha("rgb(14 12 8 / 82%)") == 0.82
    assert _css_alpha("oklch(0.15 0.008 75)") == 1.0
    assert _css_alpha("rgb(14, 12, 8)") == 1.0
    assert _css_alpha("#0E0C08") == 1.0
    assert _css_alpha("transparent") == 0.0
    assert _css_alpha("rgba(0, 0, 0, 0)") == 0.0
    # Unknown syntax must read as OPAQUE — a gate may never invent a violation.
    assert _css_alpha("color(display-p3 0.05 0.05 0.03)") == 1.0
    assert _css_alpha("") == 1.0


def test_mobile_first_load_is_on_by_default_in_capture_page():
    """Both harnesses must inherit the probe: pr_render_gate.py drives capture_page
    with no mobile_first_load argument, so a default of False would silently leave
    the PR-time gate blind (the #3200 class — a check that cannot fail)."""
    import inspect

    import visual_qa

    sig = inspect.signature(visual_qa.capture_page)
    assert sig.parameters["mobile_first_load"].default is True
