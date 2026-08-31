"""
tests/test_api_schema_completeness.py — the #1436 completeness gate.

This is the structural core the issue asked for: every `/api/*` endpoint the AST
enumerator (deploy/endpoint_registry.py, shared with deploy/sync_doc_metadata.py's
doc-sync endpoint count — one walk, two consumers, #1436/#1437) discovers in
lambdas/web/site_api_lambda.py must land in EXACTLY ONE of two buckets:

  1. a committed shape snapshot at tests/api_schemas/<slug>.json
     (deploy/capture_api_schemas.py — a live GET, reduced to types/keys only, #1436
     AC3: shape not values), OR
  2. an entry in tests/api_schemas/_exemptions.json with a reason (write-path /
     requires-path-param / deprecated / auth-gated / capture-failed).

A NEW route added later with neither reds THIS test — that is the whole point: API
surface can no longer grow silently past the contract baseline. All of this is
OFFLINE (no network) — it only reads the committed AST source + the committed
snapshot/exemption files, so it runs in every CI pass, not just a scheduled live
check. The network-dependent live-drift comparison lives in
deploy/capture_api_schemas.py --check-drift (run manually / on a schedule — see that
module's docstring for why a live-diff gate isn't wired into this offline suite).
"""

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capture_api_schemas as cas  # noqa: E402
import endpoint_registry as er  # noqa: E402

SNAPSHOT_DIR = os.path.join(_ROOT, "tests", "api_schemas")
EXEMPTIONS_PATH = os.path.join(SNAPSHOT_DIR, "_exemptions.json")

KNOWN_EXEMPTION_CATEGORIES = {"write-path", "requires-path-param", "deprecated", "auth-gated", "capture-failed"}


def _load_exemptions(path=EXEMPTIONS_PATH):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _snapshot_paths(snapshot_dir=SNAPSHOT_DIR):
    """The set of `/api/...` paths that have a committed snapshot file — read back
    OUT of each file's own `"path"` field (not guessed from the filename), so a
    rename/slug collision can't silently under- or over-count."""
    paths = set()
    # #3324: `.rglob(` (not the non-recursive `glob.glob`) so this walk matches
    # tests/premerge_derivation.py's `_SWEEP_PATTERN` and the file is correctly
    # classified as a tree-sweeping structural gate (#2578 family 5) — it enumerates
    # every committed snapshot to decide coverage, the same shape as the other
    # sweep gates, and a nested subdirectory under tests/api_schemas/ would silently
    # escape the non-recursive form.
    for fpath in sorted(str(p) for p in Path(snapshot_dir).rglob("*.json")):
        if os.path.basename(fpath) == "_exemptions.json":
            continue
        try:
            with open(fpath) as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        p = data.get("path")
        if p:
            paths.add(p)
    return paths


def missing_paths(records: dict, snapshot_dir=SNAPSHOT_DIR, exemptions_path=EXEMPTIONS_PATH) -> list:
    """The completeness check itself: every discovered path must be covered by a
    snapshot OR an exemption. Returns the sorted list of paths that are neither —
    empty means the gate passes. Pulled out as its own function (not inlined in the
    test body) so both the real gate test and the synthetic "a new route reds this"
    proof test exercise the identical code path."""
    covered = _snapshot_paths(snapshot_dir) | set(_load_exemptions(exemptions_path).keys())
    return sorted(set(records.keys()) - covered)


# ── AC: the completeness gate itself ─────────────────────────────────────────────


def test_every_discovered_endpoint_has_a_snapshot_or_exemption():
    """The #1436 structural core. Enumerates the REAL router table (ROUTES +
    _SIMPLE_ROUTES + inline dispatcher checks, via the shared AST enumerator) and
    asserts every single one is covered. A route added to site_api_lambda.py without
    either a captured snapshot (`python3 deploy/capture_api_schemas.py`) or an
    exemption entry in tests/api_schemas/_exemptions.json fails HERE, with the exact
    list of uncovered paths in the assertion message."""
    records = er.discover_endpoint_records()
    assert len(records) >= er.SANITY_FLOOR, f"endpoint enumerator returned suspiciously few routes ({len(records)})"

    missing = missing_paths(records)
    assert not missing, (
        f"{len(missing)} endpoint(s) missing a schema snapshot AND an exemption entry: {missing}\n"
        f"Fix: run `python3 deploy/capture_api_schemas.py` to capture a live snapshot, "
        f"or add a reasoned entry to {EXEMPTIONS_PATH} "
        f"(category one of {sorted(KNOWN_EXEMPTION_CATEGORIES)})."
    )


def test_no_orphan_snapshot_or_exemption_for_a_retired_route():
    """The reverse direction: a snapshot or exemption for a path the router no
    longer serves is stale evidence, not a bug — but it should be visible, not
    silently accumulate forever. Soft assertion (a warning-shaped message) is
    deliberately a hard fail here: an orphan is cheap to fix (delete the file) and
    letting them pile up would let this exact test slowly stop meaning anything."""
    records = er.discover_endpoint_records()
    live_paths = set(records.keys())
    orphans = sorted((_snapshot_paths() | set(_load_exemptions().keys())) - live_paths)
    assert not orphans, (
        f"{len(orphans)} snapshot/exemption entry(ies) reference a path no longer in "
        f"the router table: {orphans}\nFix: delete the stale tests/api_schemas/<slug>.json "
        f"file(s) and/or its _exemptions.json entry."
    )


def test_completeness_gate_catches_a_route_with_neither_snapshot_nor_exemption(tmp_path):
    """Synthetic proof (not the real repo state): a fake endpoint set containing one
    path with a snapshot, one with an exemption, and one with NEITHER must report
    exactly the third one as missing — exercising the same `missing_paths()` the real
    gate test calls, so this is a direct proof the mechanism works, not a
    reimplementation that could drift from it."""
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    (snap_dir / "api_covered.json").write_text(json.dumps({"path": "/api/covered", "shape": {"type": "object", "keys": {}}}))
    exemptions_path = tmp_path / "_exemptions.json"
    exemptions_path.write_text(json.dumps({"/api/exempted": {"category": "write-path", "reason": "test fixture"}}))

    fake_records = {"/api/covered": None, "/api/exempted": None, "/api/uncovered_new_route": None}
    missing = missing_paths(fake_records, snapshot_dir=str(snap_dir), exemptions_path=str(exemptions_path))
    assert missing == ["/api/uncovered_new_route"]


# ── AC: snapshot files are structurally valid shape JSON (offline integrity) ────


def test_all_snapshot_files_parse_and_match_the_shape_schema():
    snapshot_files = [str(p) for p in Path(SNAPSHOT_DIR).rglob("*.json") if os.path.basename(str(p)) != "_exemptions.json"]
    assert len(snapshot_files) >= 50, f"suspiciously few committed snapshot files ({len(snapshot_files)})"
    for fpath in snapshot_files:
        with open(fpath) as f:
            data = json.load(f)  # a parse failure here is itself the test failure
        for required in ("path", "captured_at", "shape"):
            assert required in data, f"{fpath} missing required top-level field {required!r}"
        assert cas.is_valid_shape_node(data["shape"]), f"{fpath}: 'shape' is not a structurally valid shape node"


def test_snapshot_files_never_carry_raw_values_only_shape_metadata():
    """#1436 AC3 (privacy/staleness): a snapshot node's leaf is a "type" tag, never a
    raw value. This guards against a future capture-script change that accidentally
    starts persisting real numbers/strings — e.g. someone "helpfully" adding a
    `"sample": <value>` field to json_shape()'s output."""

    def _walk(node):
        assert isinstance(node, dict) and "type" in node
        allowed_keys = {"type", "keys", "items", "length_sample", "optional"}
        assert set(node.keys()) <= allowed_keys, f"unexpected key(s) in shape node: {set(node.keys()) - allowed_keys}"
        if node["type"] == "object":
            for v in (node.get("keys") or {}).values():
                _walk(v)
            optional = node.get("optional")
            if optional is not None:
                # #3354: a list of key NAMES (strings), not shape nodes — the array-
                # union per-key optionality marker, never a raw payload value.
                assert isinstance(optional, list) and all(isinstance(k, str) for k in optional)
        elif node["type"] == "array":
            items = node.get("items")
            if isinstance(items, list):
                for i in items:
                    _walk(i)
            elif items is not None:
                _walk(items)

    for fpath in Path(SNAPSHOT_DIR).rglob("*.json"):
        if fpath.name == "_exemptions.json":
            continue
        with open(fpath) as f:
            data = json.load(f)
        _walk(data["shape"])


# ── AC: exemption registry structural integrity ──────────────────────────────────


def test_exemptions_use_known_categories_and_nonempty_reasons():
    exemptions = _load_exemptions()
    assert exemptions, "expected at least one exemption (write-path endpoints exist)"
    for path, entry in exemptions.items():
        assert path.startswith("/api/"), f"exemption key {path!r} doesn't look like an endpoint path"
        category = entry.get("category")
        assert category in KNOWN_EXEMPTION_CATEGORIES, f"{path}: unknown exemption category {category!r}"
        assert entry.get("reason") and len(entry["reason"]) > 10, f"{path}: exemption reason missing or too short"


def test_write_path_exemptions_cover_every_post_only_simple_route():
    """Cross-check against the router's OWN method declarations (not a re-typed
    list): every `_SIMPLE_ROUTES` entry whose allowed methods are exactly {"POST"}
    must be exempted as a write-path — this is the "write endpoints must be handled
    explicitly" acceptance criterion, verified structurally rather than by review."""
    records = er.discover_endpoint_records()
    exemptions = _load_exemptions()
    post_only = {p: r for p, r in records.items() if r.methods == {"POST"}}
    assert post_only, "expected at least one POST-only _SIMPLE_ROUTES entry in the live router"
    for path in post_only:
        assert path in exemptions, f"{path} is POST-only but has no exemption entry"
        assert exemptions[path]["category"] == "write-path", f"{path} is POST-only but exempted as {exemptions[path]['category']!r}"


# ── shape/diff utility unit tests (deploy/capture_api_schemas.py) ───────────────


class TestJsonShape:
    def test_scalars(self):
        assert cas.json_shape(None) == {"type": "null"}
        assert cas.json_shape(True) == {"type": "boolean"}
        assert cas.json_shape(3) == {"type": "integer"}
        assert cas.json_shape(3.5) == {"type": "number"}
        assert cas.json_shape("x") == {"type": "string"}

    def test_bool_precedes_int_check(self):
        # bool is an int subclass in Python — must not be misreported as "integer".
        assert cas.json_shape(False)["type"] == "boolean"

    def test_object_recurses_into_keys(self):
        shape = cas.json_shape({"a": 1, "b": "x", "c": {"d": None}})
        assert shape == {"type": "object", "keys": {"a": {"type": "integer"}, "b": {"type": "string"}, "c": shape["keys"]["c"]}}
        assert shape["keys"]["c"] == {"type": "object", "keys": {"d": {"type": "null"}}}

    def test_homogeneous_array_collapses_to_one_item_shape(self):
        shape = cas.json_shape([1, 2, 3])
        assert shape["type"] == "array"
        assert shape["items"] == {"type": "integer"}
        assert shape["length_sample"] == 3

    def test_heterogeneous_array_keeps_a_list_of_distinct_shapes(self):
        shape = cas.json_shape([1, "x", None])
        assert isinstance(shape["items"], list)
        assert {"type": "integer"} in shape["items"]
        assert {"type": "string"} in shape["items"]
        assert {"type": "null"} in shape["items"]

    def test_empty_array(self):
        assert cas.json_shape([]) == {"type": "array", "items": None, "length_sample": 0}

    def test_never_retains_a_raw_value(self):
        shape = cas.json_shape({"email": "matthew@example.com", "weight_lbs": 181.4})
        blob = json.dumps(shape)
        assert "example.com" not in blob
        assert "181.4" not in blob


class TestDiffShape:
    def test_identical_shapes_have_no_diff(self):
        s = cas.json_shape({"a": 1, "b": [1, 2]})
        assert cas.diff_shape(s, s) == []

    def test_type_change_is_reported(self):
        old = cas.json_shape({"a": 1})
        new = cas.json_shape({"a": "one"})
        diffs = cas.diff_shape(old, new)
        assert any("a" in d and "type changed" in d for d in diffs)

    def test_key_removed_is_reported(self):
        old = cas.json_shape({"a": 1, "b": 2})
        new = cas.json_shape({"a": 1})
        diffs = cas.diff_shape(old, new)
        assert any("b" in d and "removed" in d for d in diffs)

    def test_key_added_is_informational_only(self):
        old = cas.json_shape({"a": 1})
        new = cas.json_shape({"a": 1, "b": 2})
        diffs = cas.diff_shape(old, new)
        assert any("added" in d for d in diffs)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking == []

    def test_nested_object_type_change_is_reported_at_its_path(self):
        old = cas.json_shape({"vitals": {"hrv_ms": 55.0}})
        new = cas.json_shape({"vitals": {"hrv_ms": "fifty-five"}})
        diffs = cas.diff_shape(old, new)
        assert any("vitals.hrv_ms" in d and "type changed" in d for d in diffs)

    # ── #3324: nullable-aware shape rule ──────────────────────────────────────

    def test_null_to_number_is_not_breaking(self):
        """A source absent on the OLD capture (e.g. Whoop dark that night) reads
        `null`; present now it's a real number. Not a type change — absence, not
        a regression."""
        old = cas.json_shape({"whoop_hrv": None})
        new = cas.json_shape({"whoop_hrv": 55.0})
        diffs = cas.diff_shape(old, new)
        assert any("nullable type flip" in d and "informational" in d for d in diffs)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking == []

    def test_number_to_null_is_not_breaking(self):
        """The reverse direction: present on the OLD capture, absent now — same
        nullable class, still not breaking."""
        old = cas.json_shape({"whoop_hrv": 55.0})
        new = cas.json_shape({"whoop_hrv": None})
        diffs = cas.diff_shape(old, new)
        assert any("nullable type flip" in d and "informational" in d for d in diffs)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking == []

    def test_null_to_object_and_object_to_null_are_not_breaking(self):
        """Nullable-awareness isn't scalar-only: a whole object/array can be
        rendered null when its source is absent (e.g. `/api/glucose`'s
        `best_day`), the same absence semantics one level up."""
        old = cas.json_shape({"best_day": None})
        new = cas.json_shape({"best_day": {"date": "2026-08-30", "avg": 95}})
        diffs = cas.diff_shape(old, new)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking == []
        # and the reverse
        diffs2 = cas.diff_shape(new, old)
        breaking2 = [d for d in diffs2 if "informational" not in d]
        assert breaking2 == []

    def test_genuine_string_to_number_still_fails(self):
        """The nullable absorption must not swallow a REAL cross-type flip that
        has nothing to do with null — a string field that started returning a
        number is exactly the #3324 Outcome's "the only thing the gate reports"."""
        old = cas.json_shape({"weight_lbs": "181.4"})
        new = cas.json_shape({"weight_lbs": 181.4})
        diffs = cas.diff_shape(old, new)
        assert any("type changed" in d and "nullable" not in d for d in diffs)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking, "a genuine string -> number flip must still be reported as breaking"

    def test_genuine_boolean_to_integer_still_fails(self):
        """A second non-null cross-type case, to make sure the nullable carve-out
        is scoped to `null`, not to "any type mismatch involving a falsy value"."""
        old = cas.json_shape({"paused": True})
        new = cas.json_shape({"paused": 1})
        diffs = cas.diff_shape(old, new)
        breaking = [d for d in diffs if "informational" not in d]
        assert breaking, "boolean -> integer is a real type change, not a nullable flip"


# ── #3354: array-of-objects union shape + per-key optionality ────────────────
#
# Reproduction (#3354, found by the #3324 lane on /api/source_freshness):
# `sources` is an array of per-source dicts where OPTIONAL keys (e.g. `manual`)
# vary element-to-element. json_shape() must summarize the array as the UNION
# of every element's keys (with per-key optionality), and diff_shape() must
# report a key "removed" only when it is gone from EVERY element — never
# merely because one sampled element happens to omit a key another carries.


class TestArrayUnionShape:
    def test_array_of_objects_merges_into_one_union_shape_with_optional_keys(self):
        shape = cas.json_shape(
            [
                {"id": "apple_health", "age_hours": 1.0, "manual": True},
                {"id": "whoop", "age_hours": 2.0},
            ]
        )
        assert shape["type"] == "array"
        items = shape["items"]
        assert isinstance(items, dict) and items["type"] == "object", "array-of-objects items must be ONE merged union node"
        assert set(items["keys"]) == {"id", "age_hours", "manual"}
        assert items.get("optional") == ["manual"], "a key present on only SOME elements must be named optional"

    def test_a_key_present_on_every_element_is_not_marked_optional(self):
        shape = cas.json_shape([{"id": "a", "age_hours": 1.0}, {"id": "b", "age_hours": 2.0}])
        items = shape["items"]
        assert "optional" not in items, "a key present on ALL elements must not be listed as optional"

    def test_source_freshness_reproduction_varying_optional_key_is_not_breaking(self):
        """The literal #3354 reproduction: /api/source_freshness's `sources[]`
        elements differ in whether `manual` is present. Depending on which
        element a capture happens to sample FIRST, the old exact-shape-match
        diff read this as a removal in one direction and not the other — under
        the union rule it must never read as breaking, in EITHER capture
        order."""
        with_manual = {"id": "apple_health", "age_hours": 1.0, "category": "wearable", "manual": False}
        without_manual = {"id": "whoop", "age_hours": 2.0, "category": "wearable"}

        old = cas.json_shape([with_manual, without_manual])
        new = cas.json_shape([without_manual, with_manual])  # same elements, opposite sample order
        breaking = [d for d in cas.diff_shape(old, new) if "informational" not in d]
        assert breaking == [], f"varying optional keys across array elements must never read as breaking: {breaking}"

        # and the reverse order pairing
        old2 = cas.json_shape([without_manual, with_manual])
        new2 = cas.json_shape([with_manual, without_manual])
        breaking2 = [d for d in cas.diff_shape(old2, new2) if "informational" not in d]
        assert breaking2 == [], f"varying optional keys across array elements must never read as breaking: {breaking2}"

    def test_a_key_removed_from_every_element_still_reads_as_breaking(self):
        """The positive control the issue names explicitly: a key genuinely gone
        from EVERY element (not just one sampled element) must still fail."""
        old = cas.json_shape(
            [
                {"id": "apple_health", "age_hours": 1.0, "manual": True},
                {"id": "whoop", "age_hours": 2.0, "manual": False},
            ]
        )
        new = cas.json_shape(
            [
                {"id": "apple_health", "age_hours": 1.0},
                {"id": "whoop", "age_hours": 2.0},
            ]
        )
        diffs = cas.diff_shape(old, new)
        breaking = [d for d in diffs if "informational" not in d]
        assert any("manual" in d and "removed" in d for d in breaking), f"a key gone from EVERY element must still be reported: {diffs}"

    def test_a_key_removed_from_only_some_elements_is_still_not_breaking(self):
        """A key that regresses from "present on all elements" to "present on
        SOME elements" (still present on at least one) is optional-key
        variance, not a removal — the union still names the key."""
        old = cas.json_shape([{"id": "a", "manual": True}, {"id": "b", "manual": False}])
        new = cas.json_shape([{"id": "a", "manual": True}, {"id": "b"}])
        breaking = [d for d in cas.diff_shape(old, new) if "informational" not in d]
        assert breaking == [], f"a key still present on at least one element must not read as a removal: {breaking}"

    def test_nested_array_of_objects_inside_array_elements_also_unions(self):
        """The reproduction's real shape is two levels deep — `sources[].
        dark_datatypes[]` is itself an array of objects whose elements can vary
        in optional keys the same way. The union rule must apply recursively."""
        old = cas.json_shape(
            [
                {"id": "apple_health", "dark_datatypes": [{"label": "steps", "manual": True}, {"label": "sleep"}]},
                {"id": "whoop", "dark_datatypes": []},
            ]
        )
        new = cas.json_shape(
            [
                {"id": "whoop", "dark_datatypes": []},
                {"id": "apple_health", "dark_datatypes": [{"label": "sleep"}, {"label": "steps", "manual": True}]},
            ]
        )
        breaking = [d for d in cas.diff_shape(old, new) if "informational" not in d]
        assert breaking == [], f"a nested array-of-objects must union the same way: {breaking}"

    def test_is_valid_shape_node_accepts_the_optional_field(self):
        shape = cas.json_shape([{"id": "a", "manual": True}, {"id": "b"}])
        assert cas.is_valid_shape_node(shape)

    def test_is_valid_shape_node_rejects_an_optional_key_not_in_keys(self):
        bad = {"type": "object", "keys": {"a": {"type": "string"}}, "optional": ["nonexistent"]}
        assert not cas.is_valid_shape_node(bad)


# ── shared sentinel scan reuse (tests/accuracy_audit.py::scan_json_value_leaks) ──


def test_capture_script_reuses_the_shared_sentinel_scan_not_a_copy():
    """#1436's sentinel-scan-extension AC: deploy/capture_api_schemas.py must call
    the SAME leak-scan tests/accuracy_audit.py::sanity_scan() already uses for its
    curated page-binding subset — not a parallel reimplementation that could drift
    out of sync with it."""
    import accuracy_audit as aa

    assert cas.accuracy_audit is aa
    assert cas.accuracy_audit.scan_json_value_leaks is aa.scan_json_value_leaks


def test_sentinel_scan_flags_a_leaked_undefined_in_a_live_style_payload():
    import accuracy_audit as aa

    findings = aa.scan_json_value_leaks({"vitals": {"note": "value is undefined right now"}}, "test:/api/vitals")
    assert findings
    assert findings[0]["where"] == ".vitals.note"


# ── #3324: the sentinel scan is anchored to whole string values for None/null ────


def test_sentinel_scan_still_fires_on_a_whole_value_none_leak():
    """`"value": "None"` — the entire string IS the leaked Python repr, no
    surrounding sentence. This is the exact leak class #1436 exists to catch."""
    import accuracy_audit as aa

    findings = aa.scan_json_value_leaks({"labs": {"flag": "None"}}, "test:/api/labs")
    assert findings
    assert findings[0]["where"] == ".labs.flag"


def test_sentinel_scan_still_fires_on_a_whole_value_null_leak():
    import accuracy_audit as aa

    findings = aa.scan_json_value_leaks({"labs": {"flag": "null"}}, "test:/api/labs")
    assert findings
    assert findings[0]["where"] == ".labs.flag"


def test_sentinel_scan_does_not_fire_on_a_sentence_containing_none():
    """#3324's false-positive: `/api/methods`' `limitations` prose reads "None
    when |r| >= 1 or n <= 3. ..." — real English describing the ADR-104 absence
    contract, not a leaked value. The whole string is not just the token "None",
    so it must not fire."""
    import accuracy_audit as aa

    findings = aa.scan_json_value_leaks(
        {"stats": [{"limitations": "None when |r| >= 1 or n <= 3. Supports exactly four confidence levels."}]},
        "test:/api/methods",
    )
    assert findings == []


def test_sentinel_scan_does_not_fire_on_null_hypothesis_prose():
    """#3324's other false-positive source: statistics prose legitimately uses
    the word "null" ("null hypothesis") inside a longer sentence."""
    import accuracy_audit as aa

    findings = aa.scan_json_value_leaks(
        {"supplements": {"measured_by": "The weight-trend rate read against the deficit math; a clear null here retires it."}},
        "test:/api/supplements",
    )
    assert findings == []


def test_sentinel_scan_still_fires_on_js_runtime_leaks_mid_sentence():
    """The JS-runtime-only tokens (undefined/NaN/[object Object]) are NOT common
    English — a mid-string match still counts, unlike None/null. Re-asserted here
    (alongside the existing undefined test) for NaN and [object Object]."""
    import accuracy_audit as aa

    assert aa.scan_json_value_leaks({"a": "score is NaN this week"}, "src")
    assert aa.scan_json_value_leaks({"a": "rendered [object Object] on the card"}, "src")


# ── #2578/#3324: can-it-fail proof for the nullable-aware shape rule ─────────────

_DRIFT_PROBE_PATH = os.path.join(_ROOT, "tests", "fixtures", "_census_probe_2999_api_schema_drift.json")


def test_hand_mutated_baseline_reds_on_a_removed_key():
    """#2578's mutation harness (scripts/gate_census_mutations.py) plants a probe
    HERE: `reference_shape` is a real committed snapshot's shape (tests/api_schemas/
    api_vitals.json, copied fresh at plant time, never hand-typed) standing in for
    "the committed baseline"; `mutated_shape` is the SAME shape with one key hand-
    removed, standing in for "what a fresh capture just returned" — a captured
    FIXTURE, not the live site (this suite is offline by design, see the module
    docstring). The assertion below is the exact offline proxy for what
    `deploy/capture_api_schemas.py --check-drift` does against the live site:
    breaking drift between baseline and current capture must fail the run.

    Normally no probe file exists and this test is a no-op PASS — the gate is silent
    until something is planted. When the probe IS present, this must go RED: the
    #3324 nullable-flip absorption must not also swallow a genuine key removal."""
    if not os.path.exists(_DRIFT_PROBE_PATH):
        return
    with open(_DRIFT_PROBE_PATH) as f:
        probe = json.load(f)
    diffs = cas.diff_shape(probe["reference_shape"], probe["mutated_shape"])
    breaking = [d for d in diffs if "informational" not in d]
    assert not breaking, f"check-drift-equivalent: current capture disagrees with the committed baseline: {breaking}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
