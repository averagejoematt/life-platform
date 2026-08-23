"""PROBE (#3025 mutation proof — NEVER MERGE): a deliberately failing test that the
premerge marker deselects. The old lane must stay green; the new full-suite job
must red. Deleted with its branch once the evidence is recorded on #3025."""


def test_deliberately_failing_and_deselected_premerge():
    assert False, "#3025 probe: this red must be INVISIBLE to the premerge lane and VISIBLE to full-suite"
