"""program_seam.py — the ONE place that decides where the week grid comes from (#3755).

WHY A SEPARATE MODULE, AND WHY ONE FUNCTION

Two readers consume the week grid today and they found it independently:

  * `training.routine_generator.generate_routines` — `_load_json("training_week.json")`,
    which reads the repo copy locally and the S3 copy at runtime (`config/*.json` is not
    staged into the bundle, #3675).
  * `mcp.tools_hevy_routine` — the same call, for the `session_set_ceiling` warning on a
    hand-authored session.

Two independent readers of one artifact is two places to flip when the program moves from
JSON to module, and the flip that lands in only one of them is the defect this seam
exists to make impossible: the generator would build a PPL week while the ceiling warning
graded it against the old upper/lower grid, with nothing red anywhere.

WHAT THE SEAM PROMISES

  1. ONE decision. `program_structure.ACTIVE` decides, here, once.
  2. IT NAMES ITS SOURCE. The result carries `source` = "module" | "json", so a caller can
     print which grid it planned against instead of assuming. A substitution nobody can
     see is the class of defect that cost #3675 ten days.
  3. NO I/O OF ITS OWN. The JSON loader is INJECTED — `resolve_week_grid(_load_json)` —
     so this module is pure and testable without S3 or a config directory, and so the
     existing local-then-S3 fallback keeps its single implementation in
     `routine_generator._load_json`.
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

from training import program_structure

WEEK_CONFIG_FILENAME = "training_week.json"
"""The bare filename `routine_generator._load_json` resolves (local CONFIG_DIR, then
s3://${S3_BUCKET}/config/). Named here because this is now the only call site that
passes it — `deploy/config_twin_registry` harvests exactly this literal to keep the
twin's consumer edge visible."""


class ResolvedWeek(NamedTuple):
    """The week grid plus WHERE it came from. The source travels with the data."""

    week: dict[str, Any]
    source: str  # "module" | "json"
    detail: str


def resolve_week_grid(json_loader: Callable[[str], dict[str, Any]], *, filename: str = WEEK_CONFIG_FILENAME) -> ResolvedWeek:
    """The week grid every consumer reads: `program_structure.week_grid()` when the
    program is ACTIVE, otherwise the live JSON the engine has always used.

    `json_loader` is `routine_generator._load_json` in both production callers. Injected
    so this decision can be tested (and mutation-controlled: flipping ACTIVE must change
    `source`) with no S3 and no config directory.
    """
    if program_structure.ACTIVE:
        return ResolvedWeek(
            week=program_structure.week_grid(),
            source="module",
            detail=(
                f"TRAINING_PROGRAM v{program_structure.PROGRAM_VERSION} "
                f"({program_structure.SPLIT}) from lambdas/training/program_structure.py — "
                f"owner-approved {program_structure.LAST_REVIEWED_BY_OWNER}"
            ),
        )
    return ResolvedWeek(
        week=json_loader(filename),
        source="json",
        detail=(
            f"config/{filename} (S3 at runtime) — program_structure is PROPOSED, not active "
            f"(#3755, gate:owner), so the grid the engine has always run on is unchanged"
        ),
    )
