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
