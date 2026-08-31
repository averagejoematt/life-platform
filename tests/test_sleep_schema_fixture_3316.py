"""
tests/test_sleep_schema_fixture_3316.py — the /api/sleep_detail contract and the
/data/sleep/ render fixture are held to the SAME post-#3023 shape (#3316, #2921's
residual).

#2921 (PR #3023) namespaced /api/sleep_detail by device: `sleep_detail.eightsleep`
and `sleep_detail.whoop` (plus the same pair on every `sleep_trend` row), each
carrying only its own device's numbers. Its closure named two residuals verbatim —
the schema baseline `tests/api_schemas/api_sleep_detail.json` still described the
PRE-#3023 flat shape (a gate green against a shape the API no longer served), and
no local render fixture drove /data/sleep/ with populated whoop data (the page's
main body was skipped by the empty-mock pass).

This file keeps both fixed:

  1. the committed baseline carries the per-device blocks (it cannot silently be
     re-captured back to the pre-#3023 shape without this going red);
  2. the render-gate fixture matches the baseline's shape (fixture-shape drift
     fails HERE, offline, before the browser pass would re-render the empty state);
  3. the fixture is wired into tests/pr_render_gate.py's populated pass with a
     whoop-block marker check — the acceptance the issue asked for;
  4. a negative control: the drift gate's own diff (`diff_shape`, the function
     `--check-drift` calls — never a re-implementation) reports a BREAKING finding
     when the per-device block is removed or retyped, with the fixture standing in
     for the live response. A gate that cannot fail is the class this issue named.

Offline: reads only committed files. The live comparison stays
`python3 deploy/capture_api_schemas.py --only /api/sleep_detail --check-drift`.
"""

import copy
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capture_api_schemas as cas  # noqa: E402
import pr_render_gate as prg  # noqa: E402

BASELINE_PATH = os.path.join(_ROOT, "tests", "api_schemas", "api_sleep_detail.json")
FIXTURE_PATH = os.path.join(_ROOT, "tests", "fixtures", "render_gate", "sleep_detail.json")

# The per-device block fields #3023 introduced — each device's OWN numbers only.
DEVICE_BLOCK_KEYS = {
    "as_of_date",
    "night_of",
    "total_sleep_hours",
    "deep_hours",
    "rem_hours",
    "light_hours",
    "deep_pct",
    "rem_pct",
    "light_pct",
}


def _baseline():
    with open(BASELINE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _breaking(diffs):
    """The same filter --check-drift applies: 'key added (informational)' is not drift."""
    return [d for d in diffs if "informational" not in d]


def _nullable_tolerant(diffs):
    """Drop the one drift class a fixture legitimately differs from a live capture on:
    a scalar that was null on the capture night (Whoop absent, 30d window not yet
    full) and populated in the fixture, or vice versa. Everything else — a key
    missing, an object turned scalar, an array item shape gone — is real."""
    return [d for d in diffs if "'null' ->" not in d and "-> 'null'" not in d]


# ── 1. the baseline is the post-#3023 shape ──────────────────────────────────


def test_baseline_carries_the_per_device_blocks_on_sleep_detail_and_every_trend_row():
    shape = _baseline()["shape"]
    sd = shape["keys"]["sleep_detail"]["keys"]
    for device in ("eightsleep", "whoop"):
        assert device in sd, f"baseline predates #3023 — sleep_detail.{device} missing (recapture with --only /api/sleep_detail)"
        assert sd[device]["type"] == "object", f"sleep_detail.{device} baselined as {sd[device]['type']!r}, expected an object block"
        assert DEVICE_BLOCK_KEYS <= set(
            sd[device]["keys"]
        ), f"sleep_detail.{device} block is missing {DEVICE_BLOCK_KEYS - set(sd[device]['keys'])}"
    trend_items = shape["keys"]["sleep_trend"]["items"]
    trend_shapes = trend_items if isinstance(trend_items, list) else [trend_items]
    assert trend_shapes, "baseline captured an empty sleep_trend — recapture on a night with trend rows"
    for item in trend_shapes:
        for device in ("eightsleep", "whoop"):
            assert device in item["keys"], f"a sleep_trend row shape lacks the {device} block"
            assert item["keys"][device]["type"] == "object"


def test_baseline_was_captured_after_the_3023_deploy():
    # #3023 merged 2026-08-23; a baseline dated before it cannot describe the served shape.
    captured_at = _baseline()["captured_at"]
    assert captured_at >= "2026-08-23", f"baseline captured_at {captured_at} predates the #3023 deploy"


# ── 2. the render fixture matches the baseline's shape ───────────────────────


def test_fixture_matches_the_committed_baseline_shape():
    diffs = _nullable_tolerant(_breaking(cas.diff_shape(_baseline()["shape"], cas.json_shape(_fixture()))))
    assert not diffs, "render-gate sleep fixture drifted from tests/api_schemas/api_sleep_detail.json:\n  " + "\n  ".join(diffs)


def test_fixture_is_populated_whoop_not_the_empty_state():
    fx = _fixture()
    sd = fx["sleep_detail"]
    for device in ("eightsleep", "whoop"):
        block = sd.get(device)
        assert isinstance(block, dict) and block, f"fixture sleep_detail.{device} is empty — the page would render its empty state"
        assert all(
            block.get(k) is not None for k in ("deep_hours", "rem_hours", "light_hours", "total_sleep_hours")
        ), f"fixture sleep_detail.{device} has a null stage hour — 'Last night's stages' would not draw"
    # the dumbbell (two devices, one night) needs the flat whoop_hours + the ES pcts
    assert sd.get("whoop_hours") and sd.get("deep_pct") is not None and sd.get("rem_pct") is not None
    rows = fx["sleep_trend"]
    assert len(rows) >= 4, "stage-composition columns need 4+ nights (stackedDayColumns minPoints)"
    for row in rows:
        assert (
            isinstance(row.get("whoop"), dict) and row["whoop"].get("deep_hours") is not None
        ), f"trend row {row.get('date')} lacks a populated whoop block"
        assert row.get("deep_sleep_hours") is not None and row.get("rem_sleep_hours") is not None


def test_fixture_meta_is_fixture_stamped_not_a_live_request():
    meta = _fixture()["_meta"]
    assert meta["request_id"].startswith("fixture-"), "a live request_id in a committed fixture means it was pasted, not curated"
    assert "#3316" in meta.get("fixture_provenance", "")


# ── 3. wired into the render gate's populated pass ───────────────────────────


def test_render_gate_registers_the_fixture_and_the_populated_sleep_page():
    assert prg.POPULATED_API_MOCKS.get("**/api/sleep_detail") == "sleep_detail.json"
    assert os.path.isfile(os.path.join(prg.FIXTURES_DIR, "sleep_detail.json"))
    pages = [p for p in prg.POPULATED_GATE_PAGES if p["path"] == "/data/sleep/"]
    assert len(pages) == 1, "/data/sleep/ must be in the populated pass exactly once"
    checks = pages[0]["checks"]
    assert any("Whoop" in c["selector"] for c in checks), "the populated sleep page needs a marker check on the whoop stage bar"
    assert all(c["min_count"] >= 1 for c in checks)


def test_every_populated_mock_names_a_committed_fixture():
    for pattern, fname in prg.POPULATED_API_MOCKS.items():
        assert os.path.isfile(os.path.join(prg.FIXTURES_DIR, fname)), f"{pattern} -> {fname} is not a committed fixture"


# ── 4. negative control: the gate can fail against the new baseline ──────────


@pytest.mark.parametrize(
    "mutate, expect_fragment",
    [
        (lambda sd: sd.pop("whoop"), "$.sleep_detail.whoop: key removed"),
        (lambda sd: sd.pop("eightsleep"), "$.sleep_detail.eightsleep: key removed"),
        (lambda sd: sd["whoop"].pop("light_hours"), "$.sleep_detail.whoop.light_hours: key removed"),
    ],
)
def test_drift_gate_reports_breaking_drift_when_a_device_block_regresses(mutate, expect_fragment):
    """The response regresses (block dropped / nulled / a stage hour gone) while the
    baseline stands: --check-drift's diff must report it as BREAKING. Uses the
    fixture as the response stand-in and the real diff_shape — the gate's own code."""
    response = _fixture()
    mutate(response["sleep_detail"])
    diffs = _breaking(cas.diff_shape(_baseline()["shape"], cas.json_shape(response)))
    assert any(expect_fragment in d for d in diffs), f"expected {expect_fragment!r} in {diffs}"


def test_a_device_block_going_null_is_a_nullable_flip_not_breaking_drift():
    """#3324 (2026-08-31): a device block that is an object one night and null the next is
    the ABSENCE shape, not a shape change — the drift gate treats `null | <type>` as one
    shape in both directions and reports the flip as informational. Device-dark is the
    freshness checker's signal, not the schema gate's. (Until #3324 this case was pinned
    as BREAKING here, which is why the gate read red on every night Whoop was absent.)"""
    response = _fixture()
    response["sleep_detail"]["whoop"] = None
    diffs = cas.diff_shape(_baseline()["shape"], cas.json_shape(response))
    assert any("$.sleep_detail.whoop: nullable type flip 'object' <-> 'null' (informational)" in d for d in diffs), diffs
    assert not any("$.sleep_detail.whoop" in d for d in _breaking(diffs)), _breaking(diffs)


def test_drift_gate_reports_breaking_drift_when_a_trend_row_loses_its_whoop_block():
    response = _fixture()
    for row in response["sleep_trend"]:
        row.pop("whoop")
    diffs = _breaking(cas.diff_shape(_baseline()["shape"], cas.json_shape(response)))
    assert any(d.startswith("$.sleep_trend[].whoop: key removed") for d in diffs), diffs


def test_the_pre_3023_baseline_shape_would_now_read_as_breaking_drift():
    """The class the issue named: the OLD baseline (no device blocks) was green
    against the new response only because 'key added' is informational. Turned
    around — the new baseline against a pre-#3023-shaped response — it is red."""
    old_style = copy.deepcopy(_fixture())
    for k in ("eightsleep", "whoop"):
        old_style["sleep_detail"].pop(k)
        for row in old_style["sleep_trend"]:
            row.pop(k)
    diffs = _breaking(cas.diff_shape(_baseline()["shape"], cas.json_shape(old_style)))
    assert {"$.sleep_detail.eightsleep: key removed", "$.sleep_detail.whoop: key removed"} <= set(diffs), diffs


# ── the --only scope flag (#3316) ────────────────────────────────────────────


def test_filter_plan_scopes_to_the_named_paths_and_tolerates_slash_variants():
    plan = [
        {"path": "/api/a", "action": "capture"},
        {"path": "/api/sleep_detail", "action": "capture"},
        {"path": "/api/z", "action": "exempt"},
    ]
    assert cas.filter_plan(plan, None) == plan
    assert [p["path"] for p in cas.filter_plan(plan, ["api/sleep_detail/"])] == ["/api/sleep_detail"]
    assert [p["path"] for p in cas.filter_plan(plan, ["/api/z", "/api/a", "/api/a"])] == ["/api/a", "/api/z"]


def test_filter_plan_rejects_an_unknown_path_loudly():
    with pytest.raises(ValueError, match="/api/typo"):
        cas.filter_plan([{"path": "/api/a", "action": "capture"}], ["/api/typo"])


def test_merge_exemptions_preserves_out_of_scope_entries_and_replaces_in_scope_ones():
    existing = {
        "/api/board_ask": {"category": "write-path", "reason": "POST-only"},
        "/api/sleep_detail": {"category": "capture-failed", "reason": "capture-failed-502: stale entry"},
    }
    # a clean scoped capture of /api/sleep_detail: no fresh entry for it
    merged = cas.merge_exemptions(existing, {}, ["/api/sleep_detail"])
    assert merged == {"/api/board_ask": existing["/api/board_ask"]}
    # a scoped capture that failed: the fresh entry replaces the stale one, others untouched
    fresh = {"/api/sleep_detail": {"category": "capture-failed", "reason": "capture-failed-503: dict body"}}
    merged = cas.merge_exemptions(existing, fresh, ["/api/sleep_detail"])
    assert merged == {"/api/board_ask": existing["/api/board_ask"], "/api/sleep_detail": fresh["/api/sleep_detail"]}
    # unscoped: wholesale, exactly the pre-#3316 behaviour
    assert cas.merge_exemptions(existing, fresh, None) == fresh


def test_run_capture_scoped_to_an_unknown_path_exits_nonzero_without_network(monkeypatch):
    monkeypatch.setattr(cas, "build_plan", lambda: [{"path": "/api/a", "action": "capture", "fetch_path": "/api/a", "is_prefix": False}])
    monkeypatch.setattr(cas, "_fetch", lambda *_a, **_k: pytest.fail("no HTTP may happen for an unknown --only path"))
    assert cas.run_capture(dry_run=False, check_drift=True, fail_on_leak=False, only=["/api/nope"]) == 2
