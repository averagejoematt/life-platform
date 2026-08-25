"""deploy/sync_cdk_fact.py — the cdk_stacks auto-discoverer (#3143), extracted from
`sync_doc_metadata.py` when the train-2 integration stacked #3151's splice and #3183's
essay rules into the same file and pushed it past its 1253-line baseline (#1665; the
#2610 rule: pay by extraction, never raise). Same sibling shape as `sync_census_fact.py`.
"""

from pathlib import Path


def discover_cdk_stack_count(root: Path) -> int | None:
    """Count deployed CDK stack modules: cdk/stacks/*_stack.py (#3143).

    Every real stack follows the suffix (core_stack.py, ingestion_stack.py, ...);
    helper modules sharing the directory (role_policies*, constants.py, csp.py,
    monitoring_dashboards.py, ...) don't match it, so the glob doesn't need an
    app.py cross-check to stay accurate. Matches cdk/app.py's stack count (10).
    """
    stacks_dir = root / "cdk" / "stacks"
    if not stacks_dir.exists():
        return None
    try:
        count = len(list(stacks_dir.glob("*_stack.py")))
        return count if count >= 5 else None
    except Exception:
        return None
