"""
config_anchor_registry.py — the config-file counterpart to phase_taxonomy.py (#3671).

phase_taxonomy.py is ADR-077's registry for what a reset does to a DynamoDB
partition, with a coverage assertion (`classify()` raises `KeyError` on an
unknown SOURCE#) so a new top-level pk family can never silently survive a
reset unclassified. That registry has **no jurisdiction over files under
`config/`** — and `config/training_phases.json`'s `reset_epoch_date` sat stale
at `2026-06-16` through ELEVEN resets in exactly that blind spot (#3671):
`deploy/restart_pipeline.py` contained no reference to the file, so nothing
ever asked whether it needed re-anchoring. Fixing only that one field (#3680)
left the next config file with the same hole — this module is the fix to the
*class*, not just the specimen.

The universe (audited 2026-09-14 by walking every leaf of every
`config/**/*.json` for a value that is `None` or ISO-date-shaped, under a key
name matching `_KEY_PATTERN` below — `scan_config_tree()` reproduces this
scan): **20 (file, key) hits across 14 files.** Four files carry a genuine
experiment anchor:

  * `character_sheet.json` / `start_date` — a genuine experiment anchor, RESET.
  * `user_goals.json` / `start_date`, `end_date`, `baseline_measurement_utc` —
    genuine experiment anchors, RESET.
  * `training_phases.json` / `current_started` — anchor-SHAPED, but a training
    phase may legitimately span cycles, so this is a DELIBERATE non-reset
    (owner ruling 2026-09-06). `training_phases.json`'s other anchor,
    `reset_epoch_date`, was DELETED entirely by #3680/#3701 — the Y counter
    now derives straight from `EXPERIMENT_START_DATE` and carries no config
    copy at all (`tests/test_routine_title_y_anchor_3671.py` fails if it is
    reintroduced), so it does not appear in this registry as a live field.
  * `vacation_fund.json` / `start_date` — the committed value is `None`, and
    `vacation_fund.compute_vacation_fund()` already falls through
    `None -> EXPERIMENT_START_DATE` at READ time
    (`lambdas/content/vacation_fund.py`) — the same derive-don't-duplicate
    pattern #3671 chose for the Y counter. Nothing to write; ruled below.

The remaining 14 hits across 10 files (`board_of_directors.json`/`retired_date`,
`personas.json`/`retired_date`, `experiment_library.json`/`promoted_date`,
`config/coaches/tuning_log.json`/`date`, ten `config/portraits/*.json`/`date`
files) are historical facts unrelated to the experiment's own calendar — a
board member's retirement, a hypothesis's promotion into the catalog, an
editorial changelog entry, a portrait's revision date. They are registered
`NOT_ANCHORED` explicitly, with a written reason each, rather than left
un-mentioned — the whole point of this registry is that a reviewer can tell
"considered and ruled out" from "never looked at".

Coverage is enforced by `assert_full_coverage()`: any anchor-shaped field
found by `scan_config_tree()` with no matching `ConfigAnchor` raises
`KeyError`, mirroring `phase_taxonomy.classify()`'s refuse-to-default posture.
A planted anchor field (e.g. reintroducing `reset_epoch_date`, or a brand-new
config file with its own hand-maintained `start_date`) reds this guard instead
of drifting silently for another eleven resets.

`deploy/restart_pipeline.py` runs `assert_full_coverage()` as a preflight
(sibling to the #1234 census preflight) and prints `report_lines()` — every
registered anchor's treatment plus its before/after value — so a reset that
forgets to touch a `RESET_TO_GENESIS` field is visible in the run's own
output, not discoverable 82 days later.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")

# ── Treatments ──────────────────────────────────────────────────────────────
RESET_TO_GENESIS = "reset_to_genesis"  # restart_pipeline re-anchors this field to the new genesis on every reset
DELIBERATE_CARRY = "deliberate_carry"  # anchor-shaped, but an owner ruling says a reset must NOT touch it
DERIVES_LIVE = "derives_live"  # a null/absent value defers to EXPERIMENT_START_DATE at READ time — nothing to write
NOT_ANCHORED = "not_anchored"  # anchor-shaped key name, but the value has nothing to do with the experiment's calendar

VALID_TREATMENTS = frozenset({RESET_TO_GENESIS, DELIBERATE_CARRY, DERIVES_LIVE, NOT_ANCHORED})


@dataclass(frozen=True)
class ConfigAnchor:
    config_file: str  # path relative to config/, e.g. "character_sheet.json"; may be an
    # fnmatch glob (e.g. "portraits/*.json") when the same ruling covers a whole family.
    key: str  # the leaf key name (not a full JSON path — scan_config_tree() matches by
    # key name so one entry covers every occurrence, incl. inside list items).
    treatment: str
    reason: str
    path: tuple[str, ...] | None = field(default=None)  # the exact JSON path, ONLY for entries where
    # report_lines() needs a single before/after value (reset_to_genesis / deliberate_carry /
    # derives_live on a concrete, non-glob file). None for not_anchored / glob entries.

    def __post_init__(self):
        if self.treatment not in VALID_TREATMENTS:
            raise ValueError(f"config_anchor_registry: {self.config_file}:{self.key} has an unknown treatment {self.treatment!r}")


CONFIG_ANCHOR_REGISTRY: tuple[ConfigAnchor, ...] = (
    ConfigAnchor(
        "character_sheet.json",
        "start_date",
        RESET_TO_GENESIS,
        "restart_pipeline.update_configs() re-anchors baseline.start_date to the new cycle's genesis on every reset.",
        path=("baseline", "start_date"),
    ),
    ConfigAnchor(
        "user_goals.json",
        "start_date",
        RESET_TO_GENESIS,
        "restart_pipeline.update_configs() re-anchors timeline.start_date to the new cycle's genesis on every reset.",
        path=("timeline", "start_date"),
    ),
    ConfigAnchor(
        "user_goals.json",
        "end_date",
        RESET_TO_GENESIS,
        "restart_pipeline.update_configs() recomputes timeline.end_date as start_date plus the plan's fixed span.",
        path=("timeline", "end_date"),
    ),
    ConfigAnchor(
        "user_goals.json",
        "baseline_measurement_utc",
        RESET_TO_GENESIS,
        "restart_pipeline.update_configs() re-anchors timeline.baseline_measurement_utc to the new baseline weigh-in "
        "(always assigned, never conditional — a None clears a stale prior-cycle timestamp, #1092).",
        path=("timeline", "baseline_measurement_utc"),
    ),
    ConfigAnchor(
        "training_phases.json",
        "current_started",
        DELIBERATE_CARRY,
        "Owner ruling 2026-09-06 (#3671): a training phase (Foundation/Build/Forge/Sustain) may legitimately span "
        "multiple experiment cycles. current_started only advances when Matthew hand-advances the phase, never on a "
        "reset — Y (workouts since genesis) resets automatically because it is DERIVED from EXPERIMENT_START_DATE "
        "(#3680/#3701); N (workouts within the current phase) deliberately does not.",
        path=("current_started",),
    ),
    ConfigAnchor(
        "vacation_fund.json",
        "start_date",
        DERIVES_LIVE,
        "Ruled 2026-09-14 (#3671): the committed value is null, and vacation_fund.compute_vacation_fund() falls "
        "through null -> EXPERIMENT_START_DATE at READ time (lambdas/content/vacation_fund.py) — the same "
        "derive-don't-duplicate pattern #3671 chose for the Hevy Y counter, so every reset re-anchors it for free. "
        "This ruling covers the COMMITTED default only: if start_date is ever hand-set to a literal date (e.g. to "
        "exclude mileage from before fund-tracking began), that literal becomes a real anchor and must be "
        "re-classified RESET_TO_GENESIS here — and wired into restart_pipeline.update_configs() — before it can go "
        "stale the way reset_epoch_date did.",
        path=("start_date",),
    ),
    ConfigAnchor(
        "board_of_directors.json",
        "retired_date",
        NOT_ANCHORED,
        "A board member's own retirement date — an org-roster fact, not the experiment's calendar.",
    ),
    ConfigAnchor(
        "personas.json",
        "retired_date",
        NOT_ANCHORED,
        "Same as board_of_directors.json's retired_date: when a coaching persona was retired, not an experiment anchor.",
    ),
    ConfigAnchor(
        "experiment_library.json",
        "promoted_date",
        NOT_ANCHORED,
        "When a catalog HYPOTHESIS was promoted to active — the library's own 'experiment' (an owner protocol trial), "
        "unrelated to the platform's reset/genesis cycle.",
    ),
    ConfigAnchor(
        "coaches/tuning_log.json",
        "date",
        NOT_ANCHORED,
        "CC-03 changelog date of a coach prompt/voice edit — an editorial-history fact, not an experiment anchor.",
    ),
    ConfigAnchor(
        "portraits/*.json",
        "date",
        NOT_ANCHORED,
        "ADR-106 portrait revision date (when a coach's SVG portrait was drawn/approved) — art history, not the " "experiment's calendar.",
    ),
)

# ── The scan: reproduces the audit above so drift is caught, not just documented ──

# Matches start_date/end_date/retired_date/promoted_date/current_started/reset_epoch/
# baseline_measurement_utc/bare "date" — deliberately NOT "anchor"-as-substring (that
# false-matched food_vocabulary.json's `roles.anchor`, an unrelated meal-role label) and
# NOT "_dates" plural (that false-matched user_goals.json's prose `approximate_dates`).
_KEY_PATTERN = re.compile(r"(^|_)(date|started|epoch|measurement_utc)$", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _is_anchor_shaped(key: str, value: object) -> bool:
    if not _KEY_PATTERN.search(str(key)):
        return False
    return value is None or (isinstance(value, str) and bool(_ISO_DATE_RE.match(value)))


def _walk_leaves(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk_leaves(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_leaves(item)


def scan_config_tree(config_dir: str = CONFIG_DIR) -> set[tuple[str, str]]:
    """Every (file-relative-to-config_dir, leaf-key-name) pair anywhere under
    config/**/*.json whose key name looks like an experiment anchor (see
    `_KEY_PATTERN`) and whose value is either `None` or an ISO-date-shaped
    string. This is the raw candidate set `CONFIG_ANCHOR_REGISTRY` must fully
    account for — see `assert_full_coverage()`. A file that fails to parse as
    JSON is skipped (not this registry's job to validate JSON syntax)."""
    hits: set[tuple[str, str]] = set()
    for path in glob.glob(os.path.join(config_dir, "**", "*.json"), recursive=True):
        rel = os.path.relpath(path, config_dir)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        for k, v in _walk_leaves(doc):
            if _is_anchor_shaped(k, v):
                hits.add((rel, str(k)))
    return hits


def _registered(rel_file: str, key: str) -> ConfigAnchor | None:
    for anchor in CONFIG_ANCHOR_REGISTRY:
        if anchor.key == key and (anchor.config_file == rel_file or fnmatch.fnmatch(rel_file, anchor.config_file)):
            return anchor
    return None


def assert_full_coverage(config_dir: str = CONFIG_DIR) -> int:
    """Raise `KeyError` naming every anchor-shaped config field with no
    registry entry. Mirrors `phase_taxonomy.classify()`'s unknown-source
    KeyError: a config file/field can never silently default to unowned.
    Returns the number of hits scanned (all covered) on success."""
    hits = scan_config_tree(config_dir)
    uncovered = sorted((rel, key) for rel, key in hits if _registered(rel, key) is None)
    if uncovered:
        raise KeyError(
            "config_anchor_registry: found experiment-anchor-shaped config field(s) with no registry entry: "
            f"{uncovered}. Add a ConfigAnchor to CONFIG_ANCHOR_REGISTRY (lambdas/experiment/config_anchor_registry.py) "
            "classifying each one — reset_to_genesis / deliberate_carry / derives_live / not_anchored — with a "
            "written reason. This is what stops the next training_phases.json (#3671)."
        )
    return len(hits)


def _get_at_path(doc: dict[str, object], path: tuple[str, ...]) -> object:
    cur = doc
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def report_lines(
    before_docs: dict[str, dict[str, object]] | None = None,
    after_docs: dict[str, dict[str, object]] | None = None,
    config_dir: str = CONFIG_DIR,
) -> list[str]:
    """One printable line per path-bearing registry entry: treatment, file,
    field, before -> after. `before_docs`/`after_docs` map config_file -> the
    in-memory dict a caller (restart_pipeline.update_configs) already mutated
    this run; any registered file absent from both is read once from disk
    (before == after, since this run left it untouched) so a DELIBERATE_CARRY
    or DERIVES_LIVE field still shows up — the point of acceptance criterion 3:
    a missed re-anchor is visible in the run's own output, not discoverable
    82 days later."""
    before_docs = before_docs or {}
    after_docs = after_docs or {}
    lines: list[str] = []
    for a in CONFIG_ANCHOR_REGISTRY:
        if a.path is None:
            continue  # not_anchored / glob entries carry no single value to report
        before = before_docs.get(a.config_file)
        after = after_docs.get(a.config_file)
        if before is None and after is None:
            fp = os.path.join(config_dir, a.config_file)
            try:
                with open(fp, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except Exception:
                doc = {}
            before = after = doc
        before_val = _get_at_path(before or {}, a.path)
        after_val = _get_at_path(after or {}, a.path)
        field_label = ".".join(a.path)
        arrow = "->" if before_val != after_val else "== (unchanged)"
        lines.append(f"    [{a.treatment}] {a.config_file}:{field_label}  {before_val!r} {arrow} {after_val!r}")
    return lines


def anchors_for_treatment(treatment: str) -> tuple[ConfigAnchor, ...]:
    return tuple(a for a in CONFIG_ANCHOR_REGISTRY if a.treatment == treatment)
