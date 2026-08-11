"""#2271 derived guard: the reader/writer field-name contract for the todoist partition.

This is the tenth-plus instance of the *guard the SET* class. `#480`/A-7 documented
the todoist record field names as `completed_count`/`active_count`/`overdue_count`
(`lambdas/ingestion/ingestion_validator.py`), and four separate readers were still
asking the record for `tasks_completed` — a name `todoist_lambda` has never written
in this repo's entire history. Every one of them got its `.get` default, silently,
forever: no exception, no log line, no alarm.

Fixing four call sites by hand leaves the fifth. So this file does two things that
a hand-written list cannot:

1. **Derives the writer's emitted field set** from `todoist_lambda`'s record dict
   literal plus the SIMP-2 framework's envelope dict — both by AST, never hand-typed.
   A rename on the writer side is picked up automatically, so this cannot decay into
   "both sides agree on a new wrong name" the way a hardcoded expectation would.
2. **Derives the reader set** by scanning every module under `lambdas/` and `mcp/`
   for a read of the todoist partition, and asserts each reader's todoist-scoped
   field reads are a subset of the writer's fields. A NEW module that starts reading
   todoist fails `test_the_reader_set_is_derived_not_hand_listed` until it is
   reviewed and added to the inventory — the fifth reader cannot arrive unnoticed.

Non-vacuity is proven in-file: `test_the_guard_catches_an_injected_violating_reader`
feeds the same extraction+assertion machinery a synthetic reader that asks for a
dead field and asserts the guard rejects it. If the derivation ever silently stops
finding anything, that test fails too.
"""

from __future__ import annotations

import ast
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
MCP = os.path.join(ROOT, "mcp")

TODOIST_WRITER = os.path.join(LAMBDAS, "ingestion", "todoist_lambda.py")
INGESTION_FRAMEWORK = os.path.join(LAMBDAS, "ingestion", "ingestion_framework.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ── 1. The writer's emitted field set (derived, never hand-typed) ─────────────


def _transform_fn_name(src: str) -> str:
    """Name of the transform callable todoist_lambda hands to `run_ingestion`.

    Derived from the call site — `run_ingestion(_config, authenticate, fetch_day,
    transform, ...)`, 4th positional arg — so renaming the function here does not
    silently blind this guard.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_ingestion" and len(node.args) >= 4:
            arg = node.args[3]
            if isinstance(arg, ast.Name):
                return arg.id
    raise AssertionError("todoist_lambda's run_ingestion(...) call site not found — the SIMP-2 wiring shape changed")


def _dict_keys_of_returned_record(src: str, func_name: str) -> set[str]:
    """String keys of the dict literal(s) `func_name` returns.

    todoist_lambda's transform ends in `return [ {...} ]` — the single
    normalized daily record handed to the SIMP-2 framework.
    """
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert fn is not None, f"{func_name} not found — has the todoist writer been renamed or restructured?"
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                if isinstance(elt, ast.Dict):
                    keys |= {k.value for k in elt.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert keys, f"no returned record dict found in {func_name} — the AST shape this guard derives from has changed"
    return keys


def _framework_envelope_fields() -> set[str]:
    """Keys the SIMP-2 framework stamps onto EVERY record before the write,
    derived from the `floats_to_decimal({...})` envelope in `_run_ingestion`."""
    tree = ast.parse(_read(INGESTION_FRAMEWORK))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "floats_to_decimal"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            d = node.args[0]
            keys = {k.value for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"pk", "sk"} <= keys:
                return keys
    raise AssertionError("ingestion_framework's floats_to_decimal envelope dict not found — derivation shape changed")


# Attributes stamped on a record AFTER the write, by machinery outside the
# ingestion path. Not part of the writer's dict, but legitimately readable.
# ADR-077: the phase tagger writes `phase`; archived records also carry `cycle`.
POST_WRITE_TAGS = {"phase", "cycle"}


def writer_fields() -> set[str]:
    src = _read(TODOIST_WRITER)
    return _dict_keys_of_returned_record(src, _transform_fn_name(src)) | _framework_envelope_fields() | POST_WRITE_TAGS


# ── 2. The reader set (derived by scan, not hand-listed) ─────────────────────

# A module reads the todoist partition if it names the partition key or uses
# "todoist" as a source key into a records map / query helper.
TODOIST_PARTITION = re.compile(
    r"""SOURCE\#(?:\{[^}]*\})?todoist"""  # the partition key itself
    r"""|\}todoist["']"""  # f"{USER_PREFIX}todoist"
    r"""|["']todoist["']\s*[,:)\]]"""  # query_source("todoist", ...) / {"todoist": [...]}
    r"""|\[\s*["']todoist["']\s*\]"""  # raw["todoist"]
    r"""|\(\s*["']todoist["']"""  # _window("todoist")
    r"""|\btodoist(?:_week)?_rows?\b"""  # helpers taking the rows directly (indirect readers)
    r"""|\btodoist_by_date\b""",
    re.X,
)

# Modules that mention todoist but do NOT read a todoist RECORD's fields.
# Each entry states why, so an unexamined module can never land here silently.
NON_READERS = {
    "ingestion/todoist_lambda.py": "the writer itself",
    "ingestion/source_registry.py": "source facet registry — declares todoist, reads no record",
    "ingestion/ingestion_validator.py": "validates the writer's own output against the declared schema",
    "common/request_validator.py": "allow-list of valid source NAMES for API params",
    "emails/monday_compass_lambda.py": "talks to the Todoist REST API directly; never reads the DDB partition",
    "operational/pipeline_health_check_lambda.py": "names the ingestion Lambda + secret, not a record",
    "web/site_api_status.py": "source catalogue copy (labels/descriptions) for the status page",
    "mcp/config.py": "MCP tool-name -> source-name map",
    "experiment/phase_taxonomy.py": "ADR-077 partition classification registry — names todoist, reads no field",
}

# Reads inside a todoist window that are provably NOT todoist-record reads.
# Keyed by repo-relative module path; each name carries its reason.
# DynamoDB / boto response-envelope keys, never record attributes.
GLOBAL_NON_RECORD_KEYS = {"Item", "Items", "Count", "Attributes", "Responses"}

NON_RECORD_KEYS = {
    "health/pillar_absence.py": {
        # #2438: the pillar→evidence-source MAP names ingestion sources
        # ("todoist", "habitify") as VALUES; the module queries per-source
        # partitions via the registry, it never reads todoist record fields.
        "habitify": "a source name in PILLAR_EVIDENCE_SOURCES, not a record field",
    },
    "emails/weekly_digest_lambda.py": {
        # ex_todoist's RETURN dict is this module's own contract with the
        # renderer and the AI prompt — not a DynamoDB attribute name.
        "tasks_completed": "output key of ex_todoist, not a record field",
        "mcp_mutations_line": "unrelated digest payload key inside the window",
        "avg_per_day": "output key of ex_todoist",
        "days": "output key of ex_todoist",
    },
    "emails/monthly_digest_lambda.py": {
        "tasks_completed": "output key of the monthly todoist rollup, not a record field",
        "days": "output key of the monthly todoist rollup",
        "todoist": "sub-dict key of the digest payload",
    },
    "web/site_api_sleep.py": {
        "sleep_quality_score": "the whoop side of the B1 correlation card",
    },
    "compute/character_sheet_lambda.py": {
        "nutrition": "sibling source key in the same payload dict, not a todoist field",
        "raw_score_modifiers": "character-sheet payload key",
    },
    "emails/daily_brief_lambda.py": {
        "labels": "read off a task inside completed_tasks, not off the day record",
        "recovery_score": "the whoop record read on an adjacent line inside the window",
    },
    "health/fulfillment_index.py": {
        "labels": "read off a task inside completed_tasks, not off the day record",
    },
    "health/character_engine.py": {
        "hevy": "sibling source key in the same payload dict",
        "reading": "sibling source key in the same payload dict",
    },
    "web/site_api_fulfillment.py": {
        "values_todoist": "fulfillment-index channel name, not a record field",
    },
    "compute/hypothesis_engine_lambda.py": {
        "score": "hypothesis payload key",
    },
    "operational/continuity_watch.py": {
        # #1400: AMBIENT_REASONS is keyed by SOURCE NAME ("todoist", "weather",
        # "whoop", ...) and its values are prose. The two flagged tokens are
        # REGISTRY facets read off lambdas/ingestion/source_registry.py entries,
        # not attributes of a todoist DATE# record — the module's only record
        # read is `sk`, which it uses to date the row and nothing else.
        "behavioral": "a source_registry facet, not a todoist record field",
        "paused": "a source_registry facet, not a todoist record field",
    },
}

# Every module the scan classes as a todoist-record reader. Reviewed once, then
# held: a module joining this set is a code change that must be looked at.
READER_INVENTORY = {
    # #2438: queries the todoist partition (Limit-1 last-write probe via the
    # registry) for pillar-absence evidence; reads NO record fields (its one
    # flagged token is a source name — see NON_RECORD_KEYS).
    "health/pillar_absence.py",
    "emails/weekly_digest_lambda.py",
    "emails/monthly_digest_lambda.py",
    "emails/anomaly_detector_lambda.py",
    "emails/freshness_checker_lambda.py",
    "emails/daily_brief_lambda.py",
    "intelligence/intelligence_common.py",
    "compute/character_sheet_lambda.py",
    "compute/hypothesis_engine_lambda.py",
    "health/character_engine.py",
    "health/fulfillment_index.py",
    "health/time_affluence.py",
    "web/site_api_sleep.py",
    "web/site_api_fulfillment.py",
    "content/html_builder.py",
    "mcp/tools_todoist.py",
    # #1400: the continuity clock queries every behavioural source's partition
    # (todoist among the names it classifies) for the newest DATE# sort key. It
    # reads no record fields at all — see NON_RECORD_KEYS above.
    "operational/continuity_watch.py",
}


def _iter_modules():
    for base, prefix in ((LAMBDAS, ""), (MCP, "mcp/")):
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".py"):
                    full = os.path.join(dirpath, f)
                    yield prefix + os.path.relpath(full, base).replace(os.sep, "/"), full


def discover_readers() -> set[str]:
    found = set()
    for rel, full in _iter_modules():
        if rel in NON_READERS:
            continue
        if TODOIST_PARTITION.search(_read(full)):
            found.add(rel)
    return found


# ── 3. Field-read extraction (uniform, mechanical, no per-file anchors) ──────

WINDOW = 16  # lines after a todoist mention that still count as todoist-scoped

_READ_PATTERNS = (
    re.compile(r'\.get\(\s*["\'](\w+)["\']'),  # item.get("field")
    re.compile(r'safe_float\(\s*\w+\s*,\s*["\'](\w+)["\']'),  # safe_float(item, "field")
)


def todoist_scoped_reads(src: str) -> set[str]:
    """Field names read out of a record within WINDOW lines of a todoist mention."""
    lines = src.splitlines()
    hot: set[int] = set()
    for i, line in enumerate(lines):
        if TODOIST_PARTITION.search(line):
            hot |= set(range(i, min(i + WINDOW, len(lines))))
    keys: set[str] = set()
    for i in sorted(hot):
        for pat in _READ_PATTERNS:
            keys |= set(pat.findall(lines[i]))
    # "todoist" itself is a SOURCE name used as a key into per-source payload
    # dicts everywhere; it is never a field ON the record.
    return {k for k in keys if "todoist" not in k}


def declared_todoist_fields(src: str) -> set[str]:
    """Fields a *declarative* source->fields table names for todoist.

    Covers the two tables where the defect hid without any `.get` to find:
    freshness_checker's FIELD_COMPLETENESS_CHECKS (dict) and anomaly_detector's
    METRICS (list of (source, field, label, low_is_bad) tuples).
    """
    fields: set[str] = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # {"todoist": ["field", ...]}
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "todoist" and isinstance(v, (ast.List, ast.Tuple)):
                    fields |= {e.value for e in v.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        # ("todoist", "field", ...)
        if isinstance(node, ast.Tuple) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value == "todoist" and len(node.elts) >= 2:
                second = node.elts[1]
                if isinstance(second, ast.Constant) and isinstance(second.value, str):
                    fields.add(second.value)
    return fields


def violations_for(rel: str, src: str) -> set[str]:
    allowed = writer_fields() | GLOBAL_NON_RECORD_KEYS | set(NON_RECORD_KEYS.get(rel, {}))
    return (todoist_scoped_reads(src) | declared_todoist_fields(src)) - allowed


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


def test_the_writer_field_set_is_actually_derived():
    fields = writer_fields()
    # The three names #480/A-7 declared, plus the framework envelope.
    assert {"completed_count", "active_count", "overdue_count"} <= fields
    assert {"pk", "sk", "source", "ingested_at"} <= fields
    # And the dead name is NOT in it — the whole point of the derivation.
    assert "tasks_completed" not in fields


def test_the_reader_set_is_derived_not_hand_listed():
    """A new module that starts reading the todoist partition fails here until it
    is reviewed. This is the 'guard the SET' half: it is what stops a fifth
    reader from arriving with the same defect and nobody noticing."""
    discovered = discover_readers()
    new = discovered - READER_INVENTORY
    gone = READER_INVENTORY - discovered
    assert not new, (
        f"new todoist reader(s) {sorted(new)} are not in READER_INVENTORY. Check each one reads "
        "the field names the writer actually emits (see writer_fields()), then add it here."
    )
    assert not gone, f"READER_INVENTORY names {sorted(gone)}, which no longer read todoist — remove them."
    assert len(discovered) >= 6, f"the reader scan found only {len(discovered)} modules — the derivation has gone blind"


def test_every_derived_reader_reads_only_fields_the_writer_emits():
    offenders = {}
    for rel in sorted(discover_readers()):
        full = os.path.join(MCP, rel[4:]) if rel.startswith("mcp/") else os.path.join(LAMBDAS, rel)
        bad = violations_for(rel, _read(full))
        if bad:
            offenders[rel] = sorted(bad)
    assert not offenders, (
        f"todoist reader/writer contract broken: {offenders}. These modules read a field name "
        "that lambdas/ingestion/todoist_lambda.py never writes, so the read silently returns its "
        "default forever (the #2271 bug class — four readers were dark this way). Either fix the "
        "name, or, if it is genuinely not a record read, add it to NON_RECORD_KEYS with a reason."
    )


def test_anomaly_detector_dow_normalized_set_names_real_metric_fields():
    """DOW_NORMALIZED_METRICS is keyed on METRICS' field names, so it silently
    stops applying if the two drift. Same shape as the #2179 SLEEP_DEDUP_FIELDS
    fix; #2271 is the recurrence on the todoist row."""
    src = _read(os.path.join(LAMBDAS, "emails", "anomaly_detector_lambda.py"))
    tree = ast.parse(src)
    metric_fields = set()
    dow = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "METRICS" for t in node.targets):
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2 and isinstance(elt.elts[1], ast.Constant):
                    metric_fields.add(elt.elts[1].value)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DOW_NORMALIZED_METRICS" for t in node.targets):
            dow = {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
    assert metric_fields and dow, "METRICS / DOW_NORMALIZED_METRICS not found by AST — shape changed"
    assert dow <= metric_fields, (
        f"DOW_NORMALIZED_METRICS names {sorted(dow - metric_fields)}, which METRICS never emits — "
        "the day-of-week normalisation those entries exist to apply can never fire."
    )


# ── Non-vacuity: the guard must reject a reader that violates the contract ───


_FAKE_VIOLATING_READER = '''
"""A synthetic todoist reader used only to prove this guard is not vacuous."""


def summarize(table):
    rows = query_source("todoist", start, end)
    total = 0
    for item in rows:
        total += int(item.get("tasks_completed", 0) or 0)
    return total
'''

_FAKE_VIOLATING_DECLARATIVE = """
FIELD_COMPLETENESS_CHECKS = {
    "whoop": ["hrv"],
    "todoist": ["tasks_completed"],
}
"""


def test_the_guard_catches_an_injected_violating_reader():
    """Feed the real extraction + assertion machinery a reader with the exact
    defect #2271 fixed. If this passes silently, every other test in this file
    is decoration."""
    assert violations_for("fake/injected_reader.py", _FAKE_VIOLATING_READER) == {"tasks_completed"}


def test_the_guard_catches_the_defect_in_a_declarative_table_too():
    """The freshness-checker instance had no `.get` to find — it was a source->fields
    map. The declarative extractor must catch that shape independently."""
    assert violations_for("fake/injected_table.py", _FAKE_VIOLATING_DECLARATIVE) == {"tasks_completed"}


def test_the_injected_reader_is_discoverable_by_the_reader_scan():
    """The subset assertion is only worth anything if the scan would actually
    have picked this module up as a reader in the first place."""
    assert TODOIST_PARTITION.search(_FAKE_VIOLATING_READER)
    assert "tasks_completed" in todoist_scoped_reads(_FAKE_VIOLATING_READER)
