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


def test_visual_pages_carry_api_deps():
    """The sweep can only probe honest emptiness if the manifest rides the deps."""
    from qa_manifest import visual_pages

    disc = [p for p in visual_pages() if p["path"] == "/protocols/discoveries/"]
    assert disc and disc[0]["api_deps"] == ["/api/discoveries"]
