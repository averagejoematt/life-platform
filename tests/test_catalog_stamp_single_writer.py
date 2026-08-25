"""tests/test_catalog_stamp_single_writer.py — the generated MCP catalog has ONE
date, written by ONE writer, and its two writers cannot disagree.

The incident (2026-08-25 boot): Docs CI was RED on main's HEAD (fc1186ae5) because
`docs/MCP_TOOL_CATALOG.md` carried `Verified: 2026-08-24` on line 3 and
`Last updated: 2026-08-25` on line 5. The file is fully generated
(`scripts/generate_mcp_tool_catalog.py`, pure AST parse of `mcp/registry.py`) and its
generator COPIES the `Last updated` value straight into the `Verified:` header — so the
two lines are one fact with two spellings, and any state where they differ makes the
generator's own `--check` red.

How they came to differ: `deploy/sync_doc_metadata.py` stamps `{date}` from
`datetime.now(timezone.utc)`, and it stamped ONLY the `Last updated` line. The Session A
wrap synced at 00:57Z — the UTC date had already rolled over while the PT date had not —
so the sync moved one line forward and left the other behind. Nothing re-ran the
generator afterward, and main went red on a pure clock rollover. This recurs, by
construction, for any sync run in the 17:00–00:00 PT window.

The fix is the single-writer primitive (CHARTER): `sync_doc_metadata.py` now stamps BOTH
date-bearing lines, so the two writers agree in either order. These tests pin that.

Both tests are pure repo-state reads — no AWS, no network, no writes.
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CATALOG = os.path.join(_REPO, "docs", "MCP_TOOL_CATALOG.md")

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

sys.path.insert(0, os.path.join(_REPO, "deploy"))

import sync_doc_metadata as sync  # noqa: E402

_VERIFIED_RE = re.compile(r"\*\*Verified:\*\* (\d{4}-\d{2}-\d{2})")
_UPDATED_RE = re.compile(r"\*\*Last updated:\*\* (\d{4}-\d{2}-\d{2})")


def test_catalog_verified_and_last_updated_agree():
    """The live file's two date spellings are the same date.

    This is the exact assertion that would have caught the red before it landed:
    it fails on the committed state of fc1186ae5 and passes on the fix.
    """
    text = open(_CATALOG, encoding="utf-8").read()

    verified = _VERIFIED_RE.search(text)
    updated = _UPDATED_RE.search(text)
    assert verified, "docs/MCP_TOOL_CATALOG.md lost its '**Verified:** YYYY-MM-DD' header"
    assert updated, "docs/MCP_TOOL_CATALOG.md lost its '**Last updated:** YYYY-MM-DD' header"

    assert verified.group(1) == updated.group(1), (
        f"MCP_TOOL_CATALOG.md date drift: Verified={verified.group(1)} but "
        f"Last updated={updated.group(1)}. The generator copies 'Last updated' into "
        f"'Verified', so this state reds `generate_mcp_tool_catalog.py --check`. "
        f"Run: python3 deploy/sync_doc_metadata.py --apply"
    )


def test_sync_owns_both_catalog_date_lines():
    """sync_doc_metadata's rule table stamps BOTH date-bearing lines of the catalog.

    Guards the structural half: dropping the `Verified:` rule would silently restore
    the drift class (the file would only go inconsistent once the UTC date next rolled
    under a sync, which is why the class survived so long unnoticed).
    """
    catalog_rules = [r for r in sync.RULES if r[0] == "docs/MCP_TOOL_CATALOG.md"]
    assert catalog_rules, "sync_doc_metadata.RULES no longer stamps docs/MCP_TOOL_CATALOG.md at all"

    templates = " ".join(r[2] for r in catalog_rules)
    assert "**Verified:** {date}" in templates, (
        "sync_doc_metadata no longer stamps the catalog's '**Verified:**' line. "
        "The generator copies 'Last updated' into 'Verified', so a sync that moves only "
        "one of them leaves the file self-inconsistent and reds Docs CI on the next "
        "UTC date rollover (the 2026-08-25 incident)."
    )
    assert "**Last updated:** {date}" in templates, "sync_doc_metadata no longer stamps the catalog's '**Last updated:**' line"

    # Both lines must take the SAME substitution key, or they can still diverge.
    verified_rule = [r for r in catalog_rules if "**Verified:** {date}" in r[2]]
    updated_rule = [r for r in catalog_rules if "**Last updated:** {date}" in r[2]]
    assert verified_rule and updated_rule, "expected one rule per date-bearing catalog line"
