"""#6320 — the root smoke's page assertions are held to the BUILT pages, before the publish.

On 2026-11-27 a change removed the front page's portrait tiles while deploy/smoke_test_site.sh still asserted
`portrait-tiles`: every pre-merge gate was green, the root deploy published and rolled back. scripts/www_smoke_pins.py
reads the rows out of the smoke script and scripts/check_www_build.py holds the built pages to them.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import www_smoke_pins as sp  # noqa: E402

SMOKE = """
  check_body_contains "Home: v9 masthead"             "$HOME_FILE"  'header class="mast"'   "$BASE/"
  check_body_contains "Home: the figure" "$HOME_FILE" 'thedays-start' "$BASE/"
  check_body_contains "Home: self-canonical at /"     "$HOME_FILE"  'rel="canonical" href="https://averagejoematt.com/"' "$BASE/"
  check_body_not_contains "Home: not the preview build" "$HOME_FILE" 'name="robots" content="noindex' "$BASE/"
  check_body_contains "Data: the data room"           "$EVID_FILE"  'The data room'         "$BASE/data/"
  check_body_contains "Cockpit: data-bind targets"    "$NOW_FILE"   'data-bind'             "$BASE/cockpit/"
"""


def _tree(tmp_path, home: str, data: str = "<h1>The data room</h1>", base: str = ""):
    smoke = tmp_path / "smoke.sh"
    smoke.write_text(SMOKE, encoding="utf-8")
    dist = tmp_path / "dist"
    for route, html in (("", home), ("data", data)):
        d = dist / base / route
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(html, encoding="utf-8")
    return str(dist), str(smoke)


HOME_OK = '<header class="mast"></header><figure class="thedays thedays-start"></figure>'


def test_the_rows_are_read_from_the_smoke_script_and_a_base_bound_needle_is_left_out():
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        path = os.path.join(t, "smoke.sh")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(SMOKE)
        pins = sp.smoke_pins(path)
    assert ("Home: the figure", "/", "thedays-start") in pins
    assert all("averagejoematt.com" not in needle for _l, _r, needle in pins)
    assert not any(label.startswith("Home: not the preview") for label, _r, _n in pins)  # not_contains rows are not held


def test_a_build_that_carries_every_asserted_string_passes_at_the_root_and_under_the_preview_base(tmp_path):
    for base in ("", os.path.join("next", "v9")):
        root = tmp_path / (base or "root").replace(os.sep, "_")
        root.mkdir()
        dist, smoke = _tree(root, HOME_OK, base=base)
        issues, held = sp.smoke_pin_misses(dist, smoke)
        assert issues == [] and held == 3, (base, issues, held)  # two Home rows + one Data row; the cockpit is not this build's


def test_must_fail_control_a_page_that_lost_an_asserted_class_is_named(tmp_path):
    # the incident itself: the markup is gone, the smoke row still asserts it
    dist, smoke = _tree(tmp_path, '<header class="mast"></header><figure class="something-else"></figure>')
    issues, held = sp.smoke_pin_misses(dist, smoke)
    assert held == 3 and len(issues) == 1
    assert "thedays-start" in issues[0] and "deploy/smoke_test_site.sh" in issues[0]


def test_a_row_for_a_page_this_build_does_not_write_is_not_held(tmp_path):
    dist, smoke = _tree(tmp_path, HOME_OK)
    _issues, held = sp.smoke_pin_misses(dist, smoke)
    assert held == 3  # the /cockpit/ row belongs to a site/ page


def test_the_committed_smoke_script_still_has_rows_for_the_v9_front_page():
    # the reader must keep matching the real script: a reformatted row would turn the check blind
    pins = sp.smoke_pins()
    assert [p for p in pins if p[1] == "/"], "no check_body_contains row for $BASE/ was parsed from deploy/smoke_test_site.sh"
    assert any(route == "/data/" for _l, route, _n in pins) and any(route == "/story/" for _l, route, _n in pins)
