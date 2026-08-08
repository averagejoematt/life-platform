"""tests/test_raw_key_registry_guard.py — #2286: no module may hand-build a ``raw/`` S3 key.

The raw/ zone is **three-generation fractured** (X-9 / #1256): the prefix varies (user-
segmented vs legacy-unsegmented vs flat UUID), and so does the leaf filename
(``YYYY-MM-DD.json`` vs ``DD.json``, differing per source and per era on the SAME source).
A key assembled from string parts is therefore a coin flip, and it fails in the worst
possible way — #2278's blood-pressure reader omitted the user segment, addressed a prefix
nothing has ever written, and the caller's bare ``except`` turned that into a cheerful
"no readings on file" instead of an error. Silence, not a stack trace.

``ingestion.source_registry`` owns the facts: ``raw_layout_for`` (the layout),
``raw_date_key`` (one day's key), ``raw_year_prefix`` (one year's listing prefix, #2286).

This guard is **derived**: it walks the real source tree and flags any literal that
starts a ``raw/`` path outside the registry module itself. It does not know the list of
offenders and cannot go stale as new modules are added — which is the whole point,
because the three sites #2286 fixed were found by hand *after* #2278 fired, and a
hand-list would have missed the fourth.
"""

import ast
import os
import re
import subprocess

import pytest
from ingestion.source_registry import raw_date_key, raw_year_prefix

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# Where the registry legitimately owns raw/ literals — the single source of truth, plus
# the ingestion writers that CREATE the objects (a writer must name the path it writes;
# the registry documents it, and tests/test_source_registry.py cross-checks the two).
# Everything else is a READER and must resolve.
_OWNS_RAW_LITERALS = {
    "lambdas/ingestion/source_registry.py",
}

# Readers under these roots must resolve from the registry. Scoped to mcp/ for now:
# #2286's acceptance is the mcp/ surface, and widening it to every lambdas/ reader in the
# same PR would mix a conversion with a survey. Widening the tuple is the intended next
# step and needs no change to the logic below.
_READER_ROOTS = ("mcp",)

# A string literal that begins a raw/ S3 path. Matches both a plain literal and the
# leading text of an f-string ("raw/{USER_ID}/..." lexes as a JoinedStr whose first
# constant part is "raw/").
_RAW_LITERAL_RE = re.compile(r"^raw/")


def _tracked_py(roots):
    out = subprocess.run(["git", "ls-files", "-z", *roots], cwd=_REPO, capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\0") if p.endswith(".py"))


def _raw_literals(rel):
    """Every string constant in `rel` whose text starts a ``raw/`` path.

    AST-based, not grep: a grep for ``raw/`` also hits comments and docstrings, and this
    guard must fire on *code* only — the fix for a stale comment is to correct the
    comment, not to red the build.
    """
    with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=rel)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _RAW_LITERAL_RE.match(node.value):
            hits.append((node.lineno, node.value))
    return hits


def test_no_reader_hand_builds_a_raw_key():
    """A reader that assembles ``raw/…`` from parts is one layout change from silence."""
    offenders = []
    for rel in _tracked_py(_READER_ROOTS):
        if rel in _OWNS_RAW_LITERALS:
            continue
        for lineno, text in _raw_literals(rel):
            offenders.append(f"  {rel}:{lineno}  {text!r}")
    assert not offenders, (
        "Module(s) construct a raw/ S3 path from a string literal instead of resolving it "
        "from ingestion.source_registry (#2286, X-9/#1256):\n"
        + "\n".join(offenders)
        + "\n\nUse raw_date_key(source, date, sub=…) for one day's key, or "
        "raw_year_prefix(source, year, sub=…) for a listing prefix. The raw/ zone's prefix "
        "AND leaf filename both vary per source; a hand-built key fails by returning "
        "nothing, which readers swallow (#2278)."
    )


def test_the_guard_scans_something():
    """Non-vacuity: a sweep over an empty file set passes for the wrong reason."""
    scanned = [r for r in _tracked_py(_READER_ROOTS) if r not in _OWNS_RAW_LITERALS]
    assert len(scanned) > 20, f"the raw/-literal sweep only saw {len(scanned)} modules — it is not running over the reader surface"


# ── The conversion is behaviour-preserving: the SAME keys, resolved not assembled ──────
# #2286's acceptance requires proving zero behaviour change. These pin the exact strings
# the three converted call sites used to build by hand.


def test_registry_reproduces_the_previously_hand_built_cgm_key():
    assert raw_date_key("apple_health", "2024-10-01", sub="cgm_readings") == "raw/matthew/cgm_readings/2024/10/01.json"


def test_registry_reproduces_the_previously_hand_built_state_of_mind_key():
    assert raw_date_key("apple_health", "2026-07-05", sub="state_of_mind") == "raw/matthew/state_of_mind/2026/07/05.json"


def test_registry_reproduces_the_previously_hand_built_cgm_year_prefix():
    assert raw_year_prefix("apple_health", 2024, sub="cgm_readings") == "raw/matthew/cgm_readings/2024/"


def test_year_prefix_refuses_a_source_with_no_date_tree():
    """hevy is flat UUID-keyed — there is no per-year prefix, and inventing one would
    hand back a plausible string that lists nothing. Raise instead."""
    with pytest.raises(ValueError, match="not a date tree"):
        raw_year_prefix("hevy", 2026)


def test_year_prefix_refuses_an_unknown_source():
    with pytest.raises(KeyError):
        raw_year_prefix("not_a_source", 2026)
