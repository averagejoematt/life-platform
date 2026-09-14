"""tests/test_bundle_boot_pil_baseline_3784.py — the PIL baseline is DERIVED, not curated.

THE DEFECT THIS CLOSES, WHICH HAS NOW HAPPENED TWICE IN TWO DAYS

`deploy/bundle_boot_baseline.json` suppresses the modules that cannot import in an
environment without Pillow, because Pillow reaches the Lambda from a LAYER and is
deliberately never in the code bundle. It was a hand-maintained list of four.

#3780 added three more PIL-importing modules — `recap_canvas`, `recap_charts`,
`recap_layouts` — and did not add them, because nothing asked it to. Nothing failed
either: that PR was deployed with `cdk_deploy.sh`, which does not run the bundle probe.
The next CI fleet deploy did run it, and the Deploy job failed with three NEW import
failures on a PR (#3737) that had touched none of those files. A merged-but-undeployed
main is itself drift, so the cost landed on an unrelated change.

It is the same shape as #3784 one layer over. There, `test_deploy_critical_lane_imports_2758`
allowed every repo-local name unconditionally, so it checked only the FIRST hop and could
not see PIL arriving transitively through a first-party module. Here, a list of names was
kept by hand and could not see a new member arriving at all. Both are "the guard knows
the instances, not the set".

WHAT THIS ASSERTS

The baseline must equal the module-scope PIL closure over `lambdas/`, exactly — no
missing member (which fails a deploy) and no extra one (which would suppress a real
bundle-shape failure, the thing the file's own `_note` forbids).

WHY MODULE SCOPE IS THE WHOLE DISTINCTION

`import x` runs x's module-scope statements and nothing else. A module that imports PIL
inside a function body imports fine with no Pillow — `reading.cover_placeholder` does
exactly that and correctly is NOT in the baseline. So the closure walks only imports
reachable at import time: the module body, plus module-level `if`/`try` bodies, which do
execute. That distinction is the difference between a derivation that matches the probe
and one that quietly disagrees with it.
"""

from __future__ import annotations

import ast
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LAMBDAS = REPO / "lambdas"
BASELINE_FILE = REPO / "deploy" / "bundle_boot_baseline.json"


def _module_map() -> dict:
    """{bundle module name: path} — the bundle stages lambdas/ at the zip root."""
    out = {}
    for path in LAMBDAS.rglob("*.py"):
        rel = path.relative_to(LAMBDAS).with_suffix("")
        out[".".join(rel.parts)] = path
    return out


def _import_time_nodes(tree: ast.Module):
    """Every import that RUNS on `import <module>` — body, plus module-level if/try."""
    out, stack = [], list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(node)
        elif isinstance(node, (ast.If, ast.Try)):
            stack.extend(node.body)
            stack.extend(getattr(node, "orelse", []) or [])
            stack.extend(getattr(node, "finalbody", []) or [])
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
    return out


def pil_closure() -> set:
    """Every module whose IMPORT would raise without Pillow installed."""
    mods = _module_map()
    direct, first_party = set(), {}
    for name, path in mods.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — the syntax gate owns this
            continue
        deps = set()
        for node in _import_time_nodes(tree):
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif node.level:  # a relative import; the tree has none, and guessing is worse
                continue
            else:
                base = node.module or ""
                targets = [f"{base}.{a.name}" for a in node.names] + [base]
            for target in targets:
                if target.split(".")[0] == "PIL":
                    direct.add(name)
                elif target in mods:
                    deps.add(target)
        first_party[name] = deps

    reached = set(direct)
    changed = True
    while changed:
        changed = False
        for name, deps in first_party.items():
            if name not in reached and deps & reached:
                reached.add(name)
                changed = True
    return reached


def baseline_modules() -> set:
    data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    return {k for k in data if not k.startswith("_")}


# ── the negative controls, first: a derivation that finds nothing proves nothing ──
def test_the_closure_finds_the_known_direct_importers():
    found = pil_closure()
    for known in ("web.card_engine", "web.portrait_raster"):
        assert known in found, f"{known} imports PIL at module scope and the closure missed it"


def test_the_closure_follows_a_first_party_hop():
    """The #3784 property. `recap_layouts` never says PIL; it says `from web import card_engine`."""
    assert "web.recap_layouts" in pil_closure(), "the closure checks only the first hop"


def test_a_function_local_pil_import_is_NOT_in_the_closure():
    """`import x` does not run function bodies, so such a module imports fine."""
    found = pil_closure()
    assert "reading.cover_placeholder" not in found, (
        "cover_placeholder imports PIL inside a function — treating it as a module-scope "
        "importer would baseline a module that imports cleanly, hiding a real failure later"
    )


# ── the rule ──────────────────────────────────────────────────────────────────
def test_the_baseline_is_exactly_the_pil_closure():
    derived, recorded = pil_closure(), baseline_modules()

    missing = sorted(derived - recorded)
    extra = sorted(recorded - derived)
    assert not missing, (
        f"module(s) import PIL at module scope but are not in {BASELINE_FILE.name}: {missing}\n"
        "The bundle probe will report them as NEW import failures and FAIL THE DEPLOY — on whatever "
        "PR happens to trigger the next fleet deploy, which is unlikely to be the one that added them "
        "(that is exactly how #3780's three modules broke #3737's deploy). Add them with the "
        "ModuleNotFoundError string, or stop importing PIL at module scope."
    )
    assert not extra, (
        f"{BASELINE_FILE.name} suppresses module(s) that import cleanly without Pillow: {extra}\n"
        "The file's own note is explicit that ONLY probe-environment gaps belong here. A stale entry "
        "suppresses a real bundle-shape failure — the #2632 outage class this gate exists to prevent."
    )


def test_every_baseline_entry_states_the_pil_reason():
    data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    for name, reason in data.items():
        if name.startswith("_"):
            continue
        assert "No module named 'PIL'" in reason, (
            f"{name} is baselined with reason {reason!r}. This file is for the Pillow LAYER gap only; "
            "a real bundle-shape failure parked here is the thing the gate was built to catch."
        )


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
