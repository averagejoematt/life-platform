"""tests/test_prior_cut_disclosure_3754.py — the ADR-104 sentence is defined ONCE (#3754 box 5).

WHY THIS EXISTS

#3754 box 5: "Any claim comparing to the prior cut states 'intake not comparable' (ADR-104)
exactly as the prescription view does." The prescription view (`lambdas/training/
plan_engine.py`) already carried the sentence verbatim; the risk this guard exists for is a
FUTURE hand-typed copy drifting from it — a second nutrition surface writing "not directly
comparable to the last cut" or dropping the MacroFactor date, which reads as a genuine
second claim rather than the one ADR-104 fact restated.

This is a repo-shape ratchet (its population can change size without anyone editing this
file — a new hardcoded copy anywhere under `lambdas/` or `mcp/` would grow it), so it runs
PRE-MERGE (registered in `tests/conftest.py`'s `_PREMERGE_EXTRA_FILES`) and carries its own
must-fail control rather than trusting the walk to be correct by inspection.
"""

from __future__ import annotations

import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]

SENTENCE = "intake is NOT comparable to the prior cut — MacroFactor begins 2025-11-24 (ADR-104)"

CANONICAL_DEFINITION_FILE = "lambdas/health/deficit_disclosures.py"

_SCAN_DIRS = ("lambdas", "mcp")


def _find_literal_occurrences(root: pathlib.Path, sentence: str, scan_dirs=_SCAN_DIRS) -> list[str]:
    """Every first-party `.py` file under `scan_dirs` whose source TEXT contains
    `sentence` as a literal substring, relative to `root`."""
    hits = []
    for scan_dir in scan_dirs:
        base = root / scan_dir
        if not base.is_dir():
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = pathlib.Path(dirpath) / fname
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if sentence in text:
                    hits.append(str(path.relative_to(root)))
    return sorted(hits)


def test_the_adr104_sentence_is_defined_in_exactly_one_file():
    hits = _find_literal_occurrences(REPO, SENTENCE)
    assert hits == [CANONICAL_DEFINITION_FILE], (
        "the ADR-104 'not comparable to the prior cut' sentence must live as a literal "
        f"string in exactly one file ({CANONICAL_DEFINITION_FILE}); found in: {hits}. "
        "Every other caller must import INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT, never "
        "re-type the sentence."
    )


def test_the_sweep_actually_catches_a_second_hardcoded_copy_mutation_control(tmp_path):
    """Must-fail control: plant a synthetic second copy in a throwaway tree and confirm
    the same walk used above reports BOTH files. A sweep that reports 1 no matter what
    is not a guard."""
    (tmp_path / "lambdas").mkdir()
    real = tmp_path / "lambdas" / "deficit_disclosures.py"
    real.write_text(f'INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT = "{SENTENCE}"\n', encoding="utf-8")
    drifted = tmp_path / "lambdas" / "some_new_surface.py"
    drifted.write_text(f'NOTE = "{SENTENCE}"  # hand-typed copy, not imported\n', encoding="utf-8")

    hits = _find_literal_occurrences(tmp_path, SENTENCE, scan_dirs=("lambdas",))
    assert sorted(hits) == sorted(["lambdas/deficit_disclosures.py", "lambdas/some_new_surface.py"])

    # And confirm a clean tree (no drift) reports exactly one — the walk isn't just
    # always returning >= 2.
    drifted.unlink()
    hits_clean = _find_literal_occurrences(tmp_path, SENTENCE, scan_dirs=("lambdas",))
    assert hits_clean == ["lambdas/deficit_disclosures.py"]


def test_deficit_sustainability_and_macros_view_reuse_the_constant_by_reference():
    """#3754 box 5: `tool_get_deficit_sustainability` and `get_nutrition(view='macros')`
    both invite a "vs last time" reading of intake/deficit figures — each must carry the
    disclaimer BY REFERENCE to the shared constant, never a re-typed copy (that case is
    covered by the sentence-uniqueness test above; this pins that the reference exists
    at all, so the field cannot be quietly deleted from either surface)."""
    src = (REPO / "mcp" / "tools_nutrition.py").read_text(encoding="utf-8")
    assert src.count("deficit_disclosures.INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT") >= 2, (
        "expected the shared constant referenced from BOTH tool_get_deficit_sustainability "
        "and _get_macro_targets in mcp/tools_nutrition.py"
    )
