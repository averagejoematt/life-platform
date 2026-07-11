#!/usr/bin/env python3
"""
generate_mcp_tool_catalog.py — regenerate docs/MCP_TOOL_CATALOG.md from mcp/registry.py.

THE PROBLEM THIS SOLVES (#891):
  The catalog was hand-maintained and rotted every time the registry changed —
  after the #395 ER-04 prune (143 → 60) the body listed 83 tools that no longer
  exist and needed a stale-content banner as a stopgap.

HOW IT WORKS:
  Pure AST parse of mcp/registry.py (the same discipline as
  deploy/sync_doc_metadata.py::_auto_discover_tool_count) — the mcp package is
  NEVER imported, so no AWS clients, no env vars, no side effects. For each
  top-level key of the TOOLS dict it extracts the tool name, description, and
  inputSchema params, resolves the implementing module from the registry's own
  imports, and emits one table per module. The nightly-warmer table is derived
  the same way from mcp/warmer.py's steps list.

  f-string fragments in schema text (e.g. {RAW_DAY_LIMIT}) are resolved from
  mcp/config.py module-level constants where they are simple literals; dynamic
  ones (e.g. {SOURCES}) are left as named placeholders.

IDEMPOTENT + ZERO-ARGUMENT:
  Running it twice produces byte-identical output. The Version/Last-updated
  header line is preserved from the existing file (deploy/sync_doc_metadata.py
  owns stamping it — run `python3 deploy/sync_doc_metadata.py --apply` after
  regenerating; only the "Total tools" count is refreshed here so the header
  never contradicts the body).

USAGE:
  python3 scripts/generate_mcp_tool_catalog.py            # write the catalog
  python3 scripts/generate_mcp_tool_catalog.py --check    # exit 1 if it would change
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "mcp" / "registry.py"
CONFIG = ROOT / "mcp" / "config.py"
WARMER = ROOT / "mcp" / "warmer.py"
CATALOG = ROOT / "docs" / "MCP_TOOL_CATALOG.md"

# Human section titles per implementing module. Fallback is the bare module
# name, so a brand-new tools_*.py never breaks generation — it just gets a
# plain heading until a title is added here.
MODULE_TITLES = {
    "mcp.tools_data": "Core Data Access",
    "mcp.tools_health": "Health & Readiness",
    "mcp.tools_training": "Training Intelligence",
    "mcp.tools_training_notes": "Training Notes",
    "mcp.tools_strength": "Strength Training",
    "mcp.tools_hevy": "Workouts (Unified — Hevy + MacroFactor, ADR-060)",
    "mcp.tools_hevy_routine": "Hevy Routine Write-Loop (ADR-066/067/068/088)",
    "mcp.tools_correlation": "Correlation & Fitness",
    "mcp.tools_nutrition": "Nutrition",
    "mcp.tools_benchmark": "Cut Benchmarking (PRIVATE — BENCH-1, ADR-089)",
    "mcp.tools_cgm": "Blood Glucose / CGM",
    "mcp.tools_labs": "Labs & Freshness",
    "mcp.tools_journal": "Journal & Mood",
    "mcp.tools_lifestyle": "Insights, Experiments & Field Notes",
    "mcp.tools_coach_intelligence": "Coach Intelligence",
    "mcp.tools_decisions": "Decision Journal",
    "mcp.tools_social": "Social & Behavioral",
    "mcp.tools_sick_days": "Sick Days",
    "mcp.tools_todoist": "Todoist",
    "mcp.tools_memory": "Platform Memory",
    "mcp.tools_reading": "Reading / Mind Pillar (ADR-097)",
    "mcp.registry": "Meta",
}


def _config_constants() -> dict:
    """Module-level simple literal assignments in mcp/config.py (e.g. RAW_DAY_LIMIT = 90)."""
    consts = {}
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    return consts


def _render_str(node: ast.AST, consts: dict) -> str:
    """Render a string-valued AST node: plain constants, implicit concatenation,
    and f-strings (JoinedStr) with known config constants substituted."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                name = value.value.id
                parts.append(str(consts[name]) if name in consts else "{" + name + "}")
            else:
                parts.append("{…}")
        return "".join(parts)
    raise ValueError(f"unrenderable schema string node: {ast.dump(node)[:120]}")


def _eval_schema(node: ast.AST, consts: dict):
    """ast.literal_eval that also tolerates f-strings referencing config constants."""
    if isinstance(node, ast.Dict):
        return {_eval_schema(k, consts): _eval_schema(v, consts) for k, v in zip(node.keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_schema(e, consts) for e in node.elts]
    if isinstance(node, (ast.JoinedStr,)) or (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return _render_str(node, consts)
    return ast.literal_eval(node)


def _parse_registry(consts: dict):
    """Return (tools, import_map): tools = ordered [(name, schema, module)], from the
    TOOLS dict in mcp/registry.py. Never imports mcp."""
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"))

    import_map = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mcp."):
            for alias in node.names:
                import_map[alias.asname or alias.name] = node.module

    tools_dict = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "TOOLS" and isinstance(node.value, ast.Dict):
                tools_dict = node.value
                break
    if tools_dict is None:
        raise SystemExit("TOOLS dict not found in mcp/registry.py")

    tools = []
    fn_to_tool = {}
    for key_node, val_node in zip(tools_dict.keys, tools_dict.values):
        name = key_node.value
        schema = None
        fn_module = "mcp.registry"  # inline defs / placeholder-rebound fns live here
        for k, v in zip(val_node.keys, val_node.values):
            if k.value == "schema":
                schema = _eval_schema(v, consts)
            elif k.value == "fn" and isinstance(v, ast.Name):
                fn_module = import_map.get(v.id, "mcp.registry")
                fn_to_tool[v.id] = name
        if schema is None:
            raise SystemExit(f"tool {name!r} has no schema")
        if schema.get("name") != name:
            raise SystemExit(f"tool key {name!r} != schema name {schema.get('name')!r}")
        tools.append((name, schema, fn_module))
    return tools, fn_to_tool


def _parse_warmer(fn_to_tool: dict):
    """Derive the nightly-warmer table rows [(cache_key, call)] from mcp/warmer.py."""
    tree = ast.parse(WARMER.read_text(encoding="utf-8"))
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id != "steps" or not isinstance(node.value, ast.List):
                continue
            for elt in node.value.elts:
                if not (isinstance(elt, ast.Tuple) and len(elt.elts) == 4):
                    continue
                _, cache_key, fn, args = elt.elts
                fn_name = fn.id if isinstance(fn, ast.Name) else "?"
                tool = fn_to_tool.get(fn_name, fn_name)
                arg_str = ", ".join(f"{k}={v}" for k, v in ast.literal_eval(args).items())
                rows.append((cache_key.value, f"{tool}({arg_str})"))
    return rows


def _md_escape(text: str) -> str:
    """Collapse whitespace and escape pipes so a description survives a table cell."""
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _params_cell(schema: dict) -> str:
    props = schema.get("inputSchema", {}).get("properties", {})
    required = set(schema.get("inputSchema", {}).get("required", []))
    if not props:
        return "—"
    parts = []
    for pname, pdef in props.items():
        suffix = "" if pname in required else "="
        if isinstance(pdef, dict) and pdef.get("type") == "array":
            suffix += "[]"
        parts.append(pname + suffix)
    return _md_escape(", ".join(parts))


def _existing_header() -> tuple[str, str]:
    """(version, date) from the current catalog header, so regeneration never
    fights deploy/sync_doc_metadata.py's stamp (it owns those two fields)."""
    if CATALOG.exists():
        m = re.search(
            r"\*\*Version:\*\* ([^|]+) \| \*\*Last updated:\*\* ([^|]+) \| \*\*Total tools:\*\* \d+",
            CATALOG.read_text(encoding="utf-8"),
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "vX.Y.Z", "1970-01-01"  # placeholders; sync_doc_metadata --apply stamps the real values


def build_catalog() -> str:
    consts = _config_constants()
    tools, fn_to_tool = _parse_registry(consts)
    version, date = _existing_header()
    count = len(tools)

    # Group by implementing module, preserving registry insertion order.
    groups: dict[str, list] = {}
    for name, schema, module in tools:
        groups.setdefault(module, []).append((name, schema))

    lines = [
        "# Life Platform — MCP Tool Catalog",
        "",
        f"> **Status:** generated · **Owner:** Matthew · **Verified:** {date}",
        "",
        f"**Version:** {version} | **Last updated:** {date} | **Total tools:** {count}",
        "",
        "> **GENERATED FILE — do not hand-edit the tables.** Regenerate via",
        "> `python3 scripts/generate_mcp_tool_catalog.py` (pure AST parse of `mcp/registry.py`;",
        "> never imports `mcp`), then run `python3 deploy/sync_doc_metadata.py --apply` to stamp",
        "> the header. Source of truth: the top-level `TOOLS` dict keys in `mcp/registry.py` —",
        "> never count with `grep '\"name\":'`, it over-counts nested schema fields (CLAUDE.md).",
        ">",
        "> Registry removals go through the AUDITED_AT ratchet in `docs/MCP_TOOL_AUDIT.md`",
        "> (#395 ER-04 pruned 143 → 60 on 2026-07-08 against 30-day usage telemetry).",
        "> For architecture and schema details, see ARCHITECTURE.md and SCHEMA.md.",
        "",
        "---",
        "",
        f"## All {count} Tools — by module",
        "",
    ]

    # Module summary table.
    lines += ["| Module | Tools |", "|---|---|"]
    for module in groups:
        short = module.replace("mcp.", "mcp/") + ".py"
        lines.append(f"| `{short}` | {len(groups[module])} |")
    lines.append("")

    for module, entries in groups.items():
        title = MODULE_TITLES.get(module, module)
        short = module.replace("mcp.", "mcp/") + ".py"
        lines += [
            f"### {title} (`{short}`)",
            "",
            "| Tool | Key Params | Description |",
            "|------|-----------|-------------|",
        ]
        for name, schema in entries:
            lines.append(f"| `{name}` | {_params_cell(schema)} | {_md_escape(schema.get('description', ''))} |")
        lines.append("")

    # Warmer coverage — derived from mcp/warmer.py.
    warmer_rows = _parse_warmer(fn_to_tool)
    lines += [
        "---",
        "",
        "## Warmer Coverage (nightly pre-compute)",
        "",
        f"{len(warmer_rows)} warm steps run nightly (derived from `mcp/warmer.py`), dispatching",
        "through the registered tool and caching to `CACHE#matthew` (26h TTL):",
        "",
        "| Cache Key | Warm Call |",
        "|-----------|-----------|",
    ]
    for cache_key, call in warmer_rows:
        lines.append(f"| {cache_key} | {_md_escape(call)} |")

    # Phase-filter epilogue (ADR-058) — behavioral doc, stable across regenerations.
    lines += [
        "",
        "---",
        "",
        "## Phase-filter behavior (ADR-058)",
        "",
        "Tools that read day-level source data default to `phase=experiment`-only results",
        "and hide `phase=pilot` records: `get_date_range`, `find_days`, and",
        "`search_activities` route through `mcp.core.query_source`, which applies the",
        "filter; the `get_daily_snapshot` dispatcher applies the same filter via",
        "`mcp.core._apply_phase_filter`. To access pre-genesis data, pass",
        "`include_pilot=True` (most tools accept this keyword via the args dict). See",
        "`lambdas/phase_filter.py::with_phase_filter()`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    new = build_catalog()
    old = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    if "--check" in sys.argv:
        if new != old:
            print("docs/MCP_TOOL_CATALOG.md is stale — run: python3 scripts/generate_mcp_tool_catalog.py")
            return 1
        print("docs/MCP_TOOL_CATALOG.md is up to date")
        return 0
    if new == old:
        print("docs/MCP_TOOL_CATALOG.md unchanged")
        return 0
    CATALOG.write_text(new, encoding="utf-8")
    tool_count = new.count("\n| `", new.find("## All"))  # rough, for the log line only
    print(f"wrote docs/MCP_TOOL_CATALOG.md ({tool_count} table rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
