"""#2287 derived guard: every FIELD_COMPLETENESS_CHECKS entry vs. its writer.

`lambdas/emails/freshness_checker_lambda.py` spot-checks a fresh source's record
for a hand-listed set of "key fields" and reports `⚠️ PARTIAL` when any of them
is null. The list is used verbatim as a DynamoDB `ProjectionExpression`, so a
field name the writer never emits does not error — it comes back absent, and the
check reports PARTIAL forever. That reads as a *data* problem, which is why the
todoist entry (#2271) sat dark for ~147 days without anyone noticing: a dark
monitor and a degraded pipeline are indistinguishable from the email.

#2271 fixed one entry by hand. This file guards the SET: it derives the check map
by AST, derives each source's writer by AST, derives that writer's emitted field
names by AST, and asserts the subset. Entry number ten cannot be added dark, and
a writer-side rename reds a test instead of silently blinding the monitor.

Three derivations, no hand-typed field names anywhere:

1. `field_completeness_checks()` reads the map out of the checker's own source.
2. `writer_for()` locates each source's writer from the SIMP-2
   `IngestionConfig(source_name=...)` declaration or, for the two standalone
   writers, from the `USER#…#SOURCE#<key>` partition literal. A source with no
   writer — or with two — raises, so it can never be silently skipped
   (the acceptance criterion that stops a source dropping out of the guard).
3. `emitted_fields()` extracts field names from the writer via uniform emission
   shapes (see EMISSION SHAPES below) rather than one bespoke anchor per module.

Non-vacuity is proven in-file three ways: a bogus field name injected into a real
entry must be rejected, a writer whose emission is stubbed out must red every one
of its fields, and the derivations must each still be finding something.
"""

from __future__ import annotations

import ast
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
INGESTION = os.path.join(LAMBDAS, "ingestion")
FRESHNESS_CHECKER = os.path.join(LAMBDAS, "emails", "freshness_checker_lambda.py")
INGESTION_FRAMEWORK = os.path.join(INGESTION, "ingestion_framework.py")

# A DynamoDB attribute name as this platform writes them: lower snake_case.
# Deliberately excludes the vendors' camelCase API keys (`bodyBatteryValuesArray`)
# and prose, so a writer merely *mentioning* a name in a log line or a docstring
# does not count as emitting it.
_ATTR_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ── 1. The check map (derived from the checker, never hand-typed) ────────────


def field_completeness_checks() -> dict[str, list[str]]:
    """`FIELD_COMPLETENESS_CHECKS` as the checker actually declares it."""
    tree = ast.parse(_read(FRESHNESS_CHECKER))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        if not any(isinstance(t, ast.Name) and t.id == "FIELD_COMPLETENESS_CHECKS" for t in targets):
            continue
        assert isinstance(node.value, ast.Dict), "FIELD_COMPLETENESS_CHECKS is no longer a dict literal"
        out: dict[str, list[str]] = {}
        for k, v in zip(node.value.keys, node.value.values):
            assert isinstance(k, ast.Constant) and isinstance(v, ast.List), "unexpected FIELD_COMPLETENESS_CHECKS shape"
            out[k.value] = [e.value for e in v.elts if isinstance(e, ast.Constant)]
        return out
    raise AssertionError("FIELD_COMPLETENESS_CHECKS not found in freshness_checker_lambda — this guard has gone blind")


# ── 2. The writer, located per source (derived; missing writer = failure) ────

# Ingestion modules that name a source without being its writer. Each entry
# states why, so an unexamined module can never land here silently.
NOT_A_WRITER = {
    "ingestion_framework.py": "the SIMP-2 framework itself — its docstring shows a whoop config as the worked example",
    "ingestion_validator.py": "declares per-source validation schemas; writes no record",
    "source_registry.py": "the source facet registry; writes no record",
    "source_state.py": "auth/breaker state helpers, keyed by source name",
    "enrichment_lambda.py": "post-hoc enrichment pass over records other writers stored",
}


def _ingestion_modules():
    for f in sorted(os.listdir(INGESTION)):
        if f.endswith(".py") and f not in NOT_A_WRITER:
            yield f, os.path.join(INGESTION, f)


def _declares_source(src: str, source_key: str) -> bool:
    """True if this module is the writer of `source_key`'s DDB partition.

    Two shapes, both structural rather than textual — a mention inside a
    docstring or a log message parses as a plain string and matches neither:
      * SIMP-2 sources: `IngestionConfig(source_name="<key>", ...)`.
      * standalone writers: a `USER#…#SOURCE#<key>` partition-key literal
        assigned at module level (health_auto_export, measurements).
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "IngestionConfig":
            for kw in node.keywords:
                if kw.arg == "source_name" and isinstance(kw.value, ast.Constant) and kw.value.value == source_key:
                    return True
    # Partition-key literal — an f-string, so read the JoinedStr's constant tail.
    pk_literal = re.compile(r"SOURCE#" + re.escape(source_key) + r"(?![a-z0-9_])")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.JoinedStr):
            text = "".join(p.value for p in node.value.values if isinstance(p, ast.Constant) and isinstance(p.value, str))
            if pk_literal.search(text):
                return True
    return False


def writer_for(source_key: str) -> str:
    """Path of the module that writes `source_key`'s records. Raises if unclear."""
    hits = [path for name, path in _ingestion_modules() if _declares_source(_read(path), source_key)]
    assert hits, (
        f"no writer found for source '{source_key}', which FIELD_COMPLETENESS_CHECKS monitors. "
        "A source whose writer cannot be located must fail this guard, not be skipped — an "
        "unverifiable completeness check is exactly the #2271 failure mode. Either the writer was "
        "renamed/removed (drop the entry) or it declares its source in a new shape (teach _declares_source)."
    )
    assert len(hits) == 1, f"source '{source_key}' resolves to {len(hits)} writers {hits} — ambiguous; add the non-writer to NOT_A_WRITER"
    return hits[0]


# ── 3. The writer's emitted field names (uniform shapes, no per-file anchors) ─
#
# EMISSION SHAPES — the syntactic positions in which a writer names a DynamoDB
# attribute it stores. Applied identically to every writer:
#   (a) keys of a dict literal            `{"total_completed": n}`  (habitify, strava, eightsleep)
#   (b) values of a dict literal          `{1: "weight_kg"}` / `{"field": "steps"}`  (withings, HAE)
#   (c) elements of a list/tuple/set      `MEASUREMENT_FIELDS = [...]`  (measurements)
#   (d) constant subscript-assignment     `result["steps"] = ...`  (garmin, eightsleep derived)
#   (e) string args to a set*/field* call `_set_dec(fields, "hrv", ...)`  (whoop)
#   (f) `.replace(a, b)` expansion        `result[name.replace("_kg", "_lbs")]`  (withings)
#       — the transform's own constants, taken from the writer, applied to (a)–(e).
#
# Everything is then filtered to _ATTR_NAME, so prose and camelCase vendor keys
# drop out. This is looser than naming one anchor per writer and deliberately so:
# a loose derivation that covers all nine writers uniformly beats nine bespoke
# extractors that rot one at a time. It is still tight enough to have isolated
# the one real defect (garmin's `body_battery_highest`, a name that appears
# nowhere in garmin_lambda.py) out of the 15 monitored fields.

_SETTER_CALL = re.compile(r"set|field", re.I)


def emitted_fields(src: str) -> set[str]:
    tree = ast.parse(src)
    names: set[str] = set()
    replacements: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):  # (a) + (b)
            for elt in list(node.keys) + list(node.values):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):  # (c)
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
        elif isinstance(node, ast.Call):  # (e) + (f)
            fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if (
                fname == "replace"
                and len(node.args) == 2
                and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args)
            ):
                replacements.add((node.args[0].value, node.args[1].value))
            elif _SETTER_CALL.search(fname or ""):
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        names.add(a.value)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):  # (d)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                    names.add(t.slice.value)

    names = {n for n in names if _ATTR_NAME.match(n)}
    for old, new in replacements:
        names |= {n.replace(old, new) for n in names if old in n}
    return names


def framework_envelope_fields() -> set[str]:
    """Keys the SIMP-2 framework stamps on EVERY record before the write."""
    tree = ast.parse(_read(INGESTION_FRAMEWORK))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "floats_to_decimal"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            keys = {k.value for k in node.args[0].keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"pk", "sk"} <= keys:
                return keys
    raise AssertionError("ingestion_framework's floats_to_decimal envelope dict not found — derivation shape changed")


# ADR-077: stamped after the write by the phase tagger, not by the writer.
POST_WRITE_TAGS = {"phase", "cycle"}


def writer_fields(source_key: str) -> set[str]:
    return emitted_fields(_read(writer_for(source_key))) | framework_envelope_fields() | POST_WRITE_TAGS


def dark_fields(source_key: str, fields: list[str]) -> list[str]:
    """The entry's fields that its writer never emits — i.e. permanently absent."""
    emitted = writer_fields(source_key)
    return sorted(f for f in fields if f not in emitted)


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


def test_the_check_map_is_actually_derived():
    checks = field_completeness_checks()
    assert len(checks) >= 9, f"only {len(checks)} entries parsed out of FIELD_COMPLETENESS_CHECKS — the derivation has gone blind"
    assert all(v for v in checks.values()), "an entry with an empty field list checks nothing"
    # The #2271 correction must not regress.
    assert checks["todoist"] == ["completed_count"]


def test_every_monitored_source_has_a_locatable_writer():
    """Acceptance: a source whose writer cannot be found FAILS rather than being
    skipped. A skipped source is a check nobody is verifying — the #2271 shape."""
    for source_key in field_completeness_checks():
        assert os.path.exists(writer_for(source_key))


def test_the_writer_derivation_finds_real_fields():
    """Guards the derivation itself: if emitted_fields() ever stops finding
    anything, every subset assertion below passes vacuously."""
    for source_key in field_completeness_checks():
        fields = writer_fields(source_key)
        assert len(fields) >= 10, f"only {len(fields)} fields derived from {source_key}'s writer — the extraction has gone blind"
        assert {"pk", "sk"} <= fields


def test_every_completeness_check_field_is_one_its_writer_emits():
    """The guard. A field name here that no writer emits makes the check report
    PARTIAL forever — indistinguishable, from the freshness email, from a real
    data outage. #2271 (todoist `tasks_completed`) sat dark that way for ~147
    days; #2287 found the same defect in the garmin row (`body_battery_highest`,
    a name that has never existed in this repo — the writer emits
    `body_battery_high`)."""
    offenders = {}
    for source_key, fields in field_completeness_checks().items():
        dark = dark_fields(source_key, fields)
        if dark:
            offenders[source_key] = dark
    assert not offenders, (
        f"FIELD_COMPLETENESS_CHECKS names field(s) no writer emits: {offenders}. The "
        "ProjectionExpression will return them absent on every run, so the check reports "
        "⚠️ PARTIAL forever and never verifies anything. Fix the name to match the writer "
        "(check the writer module named by writer_for(<source>)), or drop the field."
    )


# ── Non-vacuity ───────────────────────────────────────────────────────────────


def test_the_guard_rejects_a_bogus_field_on_every_monitored_source():
    """Injecting a dead name into any one entry must red it — for every source,
    not just the one that happened to be broken."""
    for source_key in field_completeness_checks():
        assert dark_fields(source_key, ["tasks_completed"]) == ["tasks_completed"], f"{source_key} accepted a field no writer emits"


def test_the_guard_rejects_the_historical_garmin_defect_by_name():
    """The specific name #2287 found. `body_battery_highest` has never been
    written by any writer in this repo's history; the garmin writer emits
    `body_battery_high`. Pinned so the correction cannot silently revert."""
    assert dark_fields("garmin", ["body_battery_highest"]) == ["body_battery_highest"]
    assert dark_fields("garmin", ["body_battery_high"]) == []


_STUBBED_WRITER = '''
"""A writer that stores nothing — proves the subset assertion is load-bearing."""


def transform(raw, date_str):
    return []
'''


def test_the_guard_reds_when_a_writer_stops_emitting():
    """Feed the real extraction a writer whose emission has been gutted. If the
    machinery still says 'fine', the guard is decoration."""
    emitted = emitted_fields(_STUBBED_WRITER) | framework_envelope_fields() | POST_WRITE_TAGS
    for source_key, fields in field_completeness_checks().items():
        still_covered = [f for f in fields if f in emitted]
        assert not still_covered, f"{source_key}: {still_covered} 'survived' a writer that emits nothing"
