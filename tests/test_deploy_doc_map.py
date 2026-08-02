"""
tests/test_deploy_doc_map.py — the /deploy skill's function→source table must be
generator output from ci/lambda_map.json (#2005, devex-1).

History: the table in .claude/commands/deploy.md was hand-typed and drifted — a dead
function (apple-health-ingestion), a wrong source path (weather_handler.py), and 43
live functions missing entirely. This gate asserts the doc block is byte-identical to
what deploy/sync_deploy_doc_map.py renders from the map, so ANY map change (function
added, removed, path moved, region flagged) reds CI until the block is regenerated.

Guard-the-set discipline: the comparison is derived from the whole map, never an
enumerated list; the planted-violation tests prove the guard actually fires (#1189).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "sync_deploy_doc_map.py"
DOC = REPO_ROOT / ".claude" / "commands" / "deploy.md"
MAP = REPO_ROOT / "ci" / "lambda_map.json"

spec = importlib.util.spec_from_file_location("sync_deploy_doc_map", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _map():
    return json.loads(MAP.read_text())


def test_doc_block_matches_map():
    """The generated block in deploy.md is byte-identical to render_block(map)."""
    current = mod.extract_block(DOC.read_text())
    assert current is not None, "deploy.md is missing the generated deploy-doc-map markers — run deploy/sync_deploy_doc_map.py"
    expected = mod.render_block(_map())
    assert (
        current == expected
    ), "deploy.md's function→source table has drifted from ci/lambda_map.json — regenerate: python3 deploy/sync_deploy_doc_map.py"


def test_every_map_function_appears_in_doc():
    """Set-level: every live function in the map is resolvable from the doc (clearer failure than byte-diff)."""
    doc_text = DOC.read_text()
    lambda_map = _map()
    functions = [e["function"] for k, e in lambda_map.get("lambdas", {}).items() if isinstance(e, dict) and e.get("function")]
    functions.append(lambda_map["mcp"]["function"])
    missing = [f for f in functions if f not in doc_text]
    assert not missing, f"live functions absent from the /deploy doc table: {missing}"


def test_no_doc_row_outside_the_map():
    """Set-level: no table row names a function the map doesn't know (the dead-row class, e.g. apple-health-ingestion)."""
    block = mod.extract_block(DOC.read_text())
    assert block is not None
    lambda_map = _map()
    known = {e["function"] for e in lambda_map.get("lambdas", {}).values() if isinstance(e, dict) and e.get("function")}
    known.add(lambda_map["mcp"]["function"])
    known |= {
        e["function"] for e in lambda_map.get("lambda_edge", {}).get("functions", {}).values() if isinstance(e, dict) and e.get("function")
    }
    rows = [line for line in block.splitlines() if line.startswith("- ")]
    dead = [row for row in rows if row[2:].split(" → ")[0] not in known]
    assert not dead, f"doc rows not backed by ci/lambda_map.json: {dead}"


def _check(doc_path: Path) -> int:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--doc", str(doc_path), "--map", str(MAP)],
        capture_output=True,
        text=True,
    ).returncode


def test_check_cli_green_on_real_tree():
    assert _check(DOC) == 0


def test_guard_fires_on_removed_row(tmp_path):
    """Planted violation (#1189): delete one function row → the checker MUST red."""
    block = mod.extract_block(DOC.read_text())
    rows = [line for line in block.splitlines() if line.startswith("- ")]
    planted = DOC.read_text().replace(rows[0] + "\n", "", 1)
    doc = tmp_path / "deploy.md"
    doc.write_text(planted)
    assert _check(doc) != 0, "checker stayed green after a function row was deleted — the guard does not fire"


def test_guard_fires_on_wrong_source_path(tmp_path):
    """Planted violation: corrupt a source path (the weather_handler.py class) → the checker MUST red."""
    doc = tmp_path / "deploy.md"
    doc.write_text(DOC.read_text().replace("lambdas/ingestion/weather_lambda.py", "lambdas/ingestion/weather_handler.py", 1))
    assert _check(doc) != 0, "checker stayed green with a wrong source path — the guard does not fire"


def test_guard_fires_on_dead_row(tmp_path):
    """Planted violation: add a row for a function the map doesn't have (the apple-health class) → red."""
    block = mod.extract_block(DOC.read_text())
    planted_block = block.replace(
        mod.BEGIN_MARKER, mod.BEGIN_MARKER + "\n- apple-health-ingestion → `lambdas/ingestion/apple_health_lambda.py`", 1
    )
    doc = tmp_path / "deploy.md"
    doc.write_text(DOC.read_text().replace(block, planted_block))
    assert _check(doc) != 0, "checker stayed green with a dead function row — the guard does not fire"


def test_guard_fires_on_missing_markers(tmp_path):
    """Planted violation: strip the markers entirely (today's pre-fix state) → red."""
    text = DOC.read_text().replace(mod.BEGIN_MARKER, "").replace(mod.END_MARKER, "")
    doc = tmp_path / "deploy.md"
    doc.write_text(text)
    assert _check(doc) != 0
