"""tests/test_site_api_routes.py — Phase 4.5 scoped: validate the router table.

The new _SIMPLE_ROUTES dict in site_api_lambda.py needs to stay in sync:
  - Every entry's handler must exist as a function
  - Every entry's path must look like an API path
  - Allowed methods must be a set of valid HTTP verbs or None
  - No duplicate entries

Doesn't import site_api_lambda directly (requires AWS env). Greps the source.
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "lambdas", "site_api_lambda.py")


def _src():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


def _parse_routes():
    src = _src()
    start = src.find("_SIMPLE_ROUTES = {")
    assert start > 0, "_SIMPLE_ROUTES dict not found"
    end = src.find("\n}\n", start)
    block = src[start:end]
    # Match: "path": ({"METHOD", "METHOD"}, handler) OR (None, handler)
    pattern = re.compile(
        r'"(/api/[a-z0-9_]+)"\s*:\s*\(([^,]+),\s*(_handle_[a-z_]+)\)',
        re.MULTILINE,
    )
    return [(m.group(1), m.group(2).strip(), m.group(3)) for m in pattern.finditer(block)]


def test_routes_dict_parses():
    routes = _parse_routes()
    # 2026-05-25 (P1.1): was ≥10; /api/board_ask removed when dead AI code was purged from
    # site_api_lambda.py — that endpoint lives in life-platform-site-api-ai (ADR-036).
    assert len(routes) >= 9, f"Expected ≥9 routes, found {len(routes)}"


def test_no_duplicate_paths():
    routes = _parse_routes()
    paths = [p for p, _, _ in routes]
    assert len(paths) == len(set(paths)), "Duplicate path(s) in _SIMPLE_ROUTES"


def test_no_duplicate_handlers():
    routes = _parse_routes()
    handlers = [h for _, _, h in routes]
    assert len(handlers) == len(set(handlers)), (
        f"Duplicate handler(s) in _SIMPLE_ROUTES — same handler can't serve two paths in this table"
    )


def test_all_handlers_defined():
    src = _src()
    routes = _parse_routes()
    for path, _, handler in routes:
        pattern = rf"^def {handler}\("
        assert re.search(pattern, src, re.MULTILINE), (
            f"Route {path} references {handler} but no `def {handler}(` found in site_api_lambda.py"
        )


def test_paths_well_formed():
    routes = _parse_routes()
    for path, _, _ in routes:
        assert path.startswith("/api/"), f"Path {path!r} should start with /api/"
        assert " " not in path, f"Path {path!r} has whitespace"


def test_allowed_methods_use_valid_verbs():
    routes = _parse_routes()
    valid = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "None"}
    for path, methods_str, _ in routes:
        # methods_str is either "None" or "{\"GET\", \"OPTIONS\"}"
        if methods_str == "None":
            continue
        # Extract verbs from set literal
        verbs = re.findall(r'"([A-Z]+)"', methods_str)
        assert verbs, f"Route {path} has no recognizable methods in {methods_str!r}"
        for v in verbs:
            assert v in valid, f"Route {path} uses invalid method {v!r}"


def test_dispatch_call_exists_in_handler():
    """Verify lambda_handler actually uses _SIMPLE_ROUTES.get(path)."""
    src = _src()
    assert "_SIMPLE_ROUTES.get(path)" in src, (
        "Dispatch lookup not found in lambda_handler — did the inline branches "
        "get re-added without removing the table?"
    )
