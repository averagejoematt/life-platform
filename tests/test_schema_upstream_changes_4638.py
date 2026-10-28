"""#4638 (owner ruling B, 2026-10-28): docs/SCHEMA.md states each source's upstream edit/delete behaviour.

The registry's `upstream_changes` facet is the authority and `tests/test_upstream_changes_4638.py` holds it
to the code; this holds the SCHEMA.md table to the facet, so the document cannot drift from what the
registry says. One test, every offender reported.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from ingestion import source_registry as sr  # noqa: E402

HEADING = "## Upstream Edits and Deletes — What Reaches the Store (#4638)"


def _section() -> str:
    text = (ROOT / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1, "docs/SCHEMA.md must carry exactly one upstream edits/deletes section"
    return re.split(r"\n## ", text.split(HEADING, 1)[1], maxsplit=1)[0]


def _rows(section: str) -> dict:
    out = {}
    for line in section.splitlines():
        m = re.match(r"\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|\s*`(\w+)`\s*\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|\s*$", line)
        if m:
            out[m.group(1)] = m.groups()[1:]
    return out


def test_schema_table_matches_the_registry_facet_for_every_required_source():
    rows, offenders = _rows(_section()), []
    for key in sr.UPSTREAM_CHANGES_REQUIRED:
        facet = sr.SOURCE_REGISTRY[key]["upstream_changes"]
        if key not in rows:
            offenders.append(f"{key}: no row in the SCHEMA.md upstream table")
            continue
        edits, deletes, window, standing = rows[key]
        want_window = f"{facet['window_days']} day" if facet.get("window_days") else "none"
        if (edits, deletes, standing) != (facet["edits"], facet["deletes"], facet["standing"]):
            offenders.append(
                f"{key}: SCHEMA.md says {edits}/{deletes}/{standing}, registry says {facet['edits']}/{facet['deletes']}/{facet['standing']}"
            )
        if not window.startswith(want_window):
            offenders.append(f"{key}: SCHEMA.md window {window!r}, registry window_days {facet.get('window_days')!r}")
    extra = set(rows) - set(sr.UPSTREAM_CHANGES_REQUIRED)
    if extra:
        offenders.append(f"rows for sources outside UPSTREAM_CHANGES_REQUIRED: {sorted(extra)}")
    assert not offenders, "SCHEMA.md upstream table drifted from the registry:\n  " + "\n  ".join(offenders)


def test_every_other_registry_source_is_accounted_for_in_the_section():
    """The `Set` of #4638 is every registry source: each is a row of the required table or named in the second one."""
    section = _section()
    missing = [k for k in sr.SOURCE_REGISTRY if k not in sr.UPSTREAM_CHANGES_REQUIRED and f"`{k}`" not in section]
    assert not missing, f"registry sources with no stated upstream behaviour in docs/SCHEMA.md: {missing}"
