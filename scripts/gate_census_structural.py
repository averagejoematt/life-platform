"""scripts/gate_census_structural.py — Family 5, structural pytest gates (repo-shape
ratchets).

Split from `gate_census.py` alongside Family 6 (#3129) for extra headroom on the
module-size ratchet (#1665's 1200-line hard ceiling, #2610's extraction-not-baseline
policy — `gate_census.py` was never baselined, so any fix here has to be a split, not a
BASELINE entry or the top-of-file exemption). Kept in its own module rather than folded
into `gate_census_sentinel.py` — the two families are unrelated (this one delegates to
`tests/premerge_derivation.py`'s tree-sweeping-test discovery; #3129's family walks
deploy/drift_sentinel.py) and a shared file would blur which extraction paid for which
review incident.

Same NO CIRCULAR IMPORT shape as gate_census_sentinel.py: `gate_census.py`'s `Gate`,
`_read`, `_static_source_flags`, and `log` are passed in as parameters rather than
imported back from here, so this module has zero dependency on gate_census.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable


def discover_structural_test_gates(
    root: Path,
    gate_cls: Callable[..., Any],
    read_fn: Callable[[Path], str],
    static_flags_fn: Callable[[str], list[str]],
    log_fn: Callable[[str], None],
) -> tuple[list[Any], dict[str, int]]:
    sys.path.insert(0, str(root / "tests"))
    try:
        from premerge_derivation import discover_tree_sweeping_test_files  # type: ignore
    except ImportError:  # pragma: no cover
        log_fn("tests/premerge_derivation.py not importable — structural-test family SKIPPED (n unknown)")
        return [], {"importable": 0}
    names = sorted(discover_tree_sweeping_test_files(root / "tests"))
    gates: list[Any] = []
    for name in names:
        text = read_fn(root / "tests" / name)
        gates.append(
            gate_cls(
                id=f"structural::{name}",
                family="structural-test",
                name=name,
                source=f"tests/{name}",
                screened=True,
                risk_flags=sorted(set(static_flags_fn(text))),
            )
        )
    return gates, {"importable": 1, "found": len(names)}
