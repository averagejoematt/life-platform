#!/usr/bin/env python3
"""
deploy/sync_deploy_doc_map.py — regenerate the /deploy skill's function→source table
from ci/lambda_map.json (#2005, devex-1).

The table in .claude/commands/deploy.md was hand-maintained and drifted from ground
truth (a dead function, a wrong source path, 43 live functions missing). Per the
repo's own meta-rule ("run the command, never quote a number"), the table is now
GENERATOR OUTPUT between markers — derived from ci/lambda_map.json, the same map CI
and deploy_lambda.sh already resolve regions/paths from.

Usage:
    python3 deploy/sync_deploy_doc_map.py            # rewrite the block in deploy.md
    python3 deploy/sync_deploy_doc_map.py --check    # exit 2 if the doc block differs
    # --doc / --map override the default paths (used by tests/test_deploy_doc_map.py)

Drift gate: tests/test_deploy_doc_map.py asserts block==render (guards the SET —
any function added to / removed from the map reds the test until this is re-run).
"""

import argparse
import json
import sys
from pathlib import Path


def _skill_registry():
    """The ONE registry for Claude Code skills + agents (scripts/skill_registry.py)."""
    import importlib.util
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    _cands = [_os.path.join(_here, "skill_registry.py"), _os.path.join(_here, "..", "scripts", "skill_registry.py")]
    for _p in _cands:
        if _os.path.isfile(_p):
            spec = importlib.util.spec_from_file_location("_skill_registry", _p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("scripts/skill_registry.py not found")


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = REPO_ROOT / "ci" / "lambda_map.json"
DEFAULT_DOC = _skill_registry().require_skill("deploy")

BEGIN_MARKER = "<!-- BEGIN GENERATED: deploy-doc-map -->"
END_MARKER = "<!-- END GENERATED: deploy-doc-map -->"

# Preferred domain ordering (lambdas/<domain>/). Unknown domains still render —
# they fall back to alphabetical after these (guard the set, not the instance).
DOMAIN_ORDER = ["ingestion", "compute", "coach", "emails", "intelligence", "operational", "reading", "web"]

# Functions whose deploy path is special-cased in the prose above the table.
SPECIAL_NOTES = {
    "life-platform-site-api": "SPECIAL BUILD — `bash deploy/deploy_site_api.sh` (see Special case above)",
}


def _domain(source_path: str) -> str:
    parts = source_path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "lambdas" else "other"


def render_block(lambda_map: dict) -> str:
    """Render the generated deploy.md block (markers included) from the parsed map."""
    by_domain: dict[str, list[str]] = {}
    for source, entry in sorted(lambda_map.get("lambdas", {}).items()):
        if source.startswith("_") or not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not function:
            continue
        flags = []
        region = entry.get("region")
        if region and region != "us-west-2":
            flags.append(f"region: {region}")
        if entry.get("cdk_only"):
            flags.append("cdk_only†")
        suffix = f" ({', '.join(flags)})" if flags else ""
        if function in SPECIAL_NOTES:
            row = f"- {function} → {SPECIAL_NOTES[function]}"
        else:
            row = f"- {function} → `{source}`{suffix}"
        by_domain.setdefault(_domain(source), []).append(row)

    ordered = [d for d in DOMAIN_ORDER if d in by_domain]
    ordered += sorted(d for d in by_domain if d not in DOMAIN_ORDER)

    lines = [
        BEGIN_MARKER,
        "<!-- Regenerate: python3 deploy/sync_deploy_doc_map.py   (never hand-edit this block)",
        "     Source of truth: ci/lambda_map.json — drift gate: tests/test_deploy_doc_map.py -->",
        "",
    ]
    for domain in ordered:
        lines.append(f"**{domain.capitalize()}** (`lambdas/{domain}/`):" if domain != "other" else "**Other:**")
        lines.extend(sorted(by_domain[domain]))
        lines.append("")

    mcp = lambda_map.get("mcp", {})
    if mcp.get("function"):
        lines.append("**Special:**")
        lines.append(
            f"- {mcp['function']} → `{mcp.get('source', 'mcp_server.py')}` + `{mcp.get('package_dir', 'mcp/')}` — SPECIAL BUILD (see above)"
        )
        lines.append("")

    edge_fns = lambda_map.get("lambda_edge", {}).get("functions", {})
    edge_rows = []
    for source, entry in sorted(edge_fns.items()):
        if source.startswith("_") or not isinstance(entry, dict) or not entry.get("function"):
            continue
        edge_rows.append(f"- {entry['function']} → `{source}` (region: {entry.get('region', 'us-east-1')})")
    if edge_rows:
        lines.append("**Lambda@Edge (manually deployed, NOT CI/CD — see the map's notes):**")
        lines.extend(edge_rows)
        lines.append("")

    lines.append("† `cdk_only` is a historical annotation in the map: since #781 every sanctioned deploy path")
    lines.append("ships the same full-tree bundle, so these deploy fine via `deploy_and_verify.sh` too.")
    lines.append(END_MARKER)
    return "\n".join(lines)


def extract_block(doc_text: str) -> str | None:
    """Return the current generated block (markers included), or None if markers absent."""
    start = doc_text.find(BEGIN_MARKER)
    end = doc_text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        return None
    return doc_text[start : end + len(END_MARKER)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the doc block matches the map; exit 2 on drift")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args(argv)

    lambda_map = json.loads(args.map.read_text())
    expected = render_block(lambda_map)
    doc_text = args.doc.read_text()
    current = extract_block(doc_text)

    if args.check:
        if current is None:
            print(f"DRIFT: {args.doc} has no generated deploy-doc-map block (markers missing).")
            return 2
        if current != expected:
            cur_rows = {line for line in current.splitlines() if line.startswith("- ")}
            exp_rows = {line for line in expected.splitlines() if line.startswith("- ")}
            for row in sorted(exp_rows - cur_rows):
                print(f"DRIFT: missing/stale in doc: {row}")
            for row in sorted(cur_rows - exp_rows):
                print(f"DRIFT: doc row not derived from map: {row}")
            print("DRIFT: regenerate with: python3 deploy/sync_deploy_doc_map.py")
            return 2
        print(f"OK: {args.doc} deploy-doc-map block matches {args.map}")
        return 0

    if current is None:
        print(f"ERROR: {args.doc} has no {BEGIN_MARKER} / {END_MARKER} markers to fill.", file=sys.stderr)
        return 1
    if current == expected:
        print(f"unchanged: {args.doc}")
        return 0
    args.doc.write_text(doc_text.replace(current, expected))
    print(f"rewrote deploy-doc-map block in {args.doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
