#!/usr/bin/env python3
"""tests/test_generator_chrome_contract_3721.py — the generator must be unable to
strip chrome (#3721).

`scripts/v4_apply_chrome.py` has said since #1009 that it is the authoritative
post-build chrome pass and that it should be run "after any `v4_build_*` build so
generator-local chrome can't re-drift." Not one generator did. Every chrome sweep
since then updated the COMMITTED pages; the generators that produce those pages kept
their own copy-pasted head/footer literals and fell behind in silence.

Found by regenerating `/gear/` for one unrelated field in #3720 — a registry `method`
string. The regen was correct in the field it was asked for and silently dropped five
other things: the light/dark theme-color pair, the SVG favicon, the manifest, the
apple-touch-icon and the `.loop-forward` aside. Net 2 insertions, 7 deletions against
a page readers were being served.

It was NOT one stale generator. Measured 2026-09-13 by running each `v4_build_*.py`
against a clean tree and re-running `tests/test_site_chrome.py` after each:

    coaching · dispatches · evidence · eyeball · gear · grade_your_coach ·
    methods · mirror · theme_river · tone          -> 4 failed, 6 passed

Ten of them. `v4_build_agent_review.py` was the only page generator that survived —
and only because its own literals happened to be current, not because anything held
them there.

`tests/test_site_chrome.py` was not the broken thing; it caught this. The gap is that
the contract could only fire AFTER someone ran a generator, and the natural reading of
a red chrome test is "I broke the page," not "the generator is stale." So the fix
makes the normalizer the WRITER — `v4_apply_chrome.write_page()` — and this file is
the guard that keeps it that way: a generator that writes an HTML page under `site/`
by any other route fails here, at import-time AST, before it can ever run.

MUTATION PROOF: change any generator's `_apply_chrome.write_page(p, html)` back to
`p.write_text(html, encoding="utf-8")` and `test_no_generator_writes_a_page_directly`
names that file and line.

Offline, stdlib-only, repo-only: no generator is executed here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
NORMALIZER = "write_page"

# Generators are page builders by default. These write something that is not a chrome-
# bearing HTML page and so have nothing to normalize; each is listed with what it emits,
# so "it has no pages" stays a checked claim rather than an exemption.
NON_PAGE_GENERATORS = {
    "v4_build_rss.py": "rss.xml (+ its alias) — XML feeds, no chrome",
    "v4_build_data_sources.py": "site/data/*.json",
    "v4_build_stack_manifest.py": "site/data/stack.json",
    "v4_build_portraits.py": "site/assets/js/portrait_data.js",
    "v4_build_permanence_terms.py": "a JSON artifact",
}

# WHY THIS LIST IS SHORTER THAN ITS FIRST DRAFT (#3721, same session).
# My first version of this guard matched `.html` in the WRITE CALL's own source text,
# and my first version of the list above carried five more names written from what each
# generator's docstring claimed. Both were wrong, in the same direction:
#
#     v4_build_cockpit_proof.py   NOW.write_text(out, ...)            site/cockpit/index.html
#     v4_build_home_proof.py      HOME.write_text(out, ...)           site/index.html
#     v4_build_horizons.py        OUT.write_text(render(), ...)       site/data/horizons/index.html
#     v4_build_sitemap.py         CHRONICLE_HUB.write_text(html, ...) site/story/chronicle/index.html
#     v4_build_game_explained.py  OUT_PATH.write_text(page, ...)      site/method/game/index.html
#
# Every one of those writes a real reader page through a MODULE-LEVEL CONSTANT, so the
# string ".html" never appears at the call site and the matcher saw nothing. A guard
# satisfied by a token is not a guard, and an exemption written from a docstring is a
# guess. `_html_writes` now resolves module-level names bound to an .html path, and each
# of the five is routed through the normalizer like the rest.


def _generators():
    return sorted(SCRIPTS.glob("v4_build_*.py"))


def _html_page_names(src: str, tree: ast.AST) -> set:
    """Module-level names bound to a value whose source mentions an `.html` path.

    `OUT_PATH = ROOT / "site" / "method" / "game" / "index.html"` binds one. Without
    this the write through it is invisible — see the comment above the registry.
    """
    names = set()
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if ".html" not in (ast.get_source_segment(src, node) or ""):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _html_writes(path: Path):
    """(lineno, source) for every `.write_text(...)` / `.write(...)` that targets an
    HTML page — either literally at the call site, or through a module-level constant
    bound to one. This is the shape that bypasses the normalizer."""
    src = path.read_text()
    tree = ast.parse(src)
    page_names = _html_page_names(src, tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"write_text", "write"}:
            continue
        seg = ast.get_source_segment(src, node) or ""
        receiver = node.func.value
        via_const = isinstance(receiver, ast.Name) and receiver.id in page_names
        if ".html" in seg or via_const:
            out.append((node.lineno, " ".join(seg.split())[:120]))
    return out


def test_no_generator_writes_a_page_directly():
    """THE GUARD. Ten generators drifted because writing a page directly was possible;
    it no longer is."""
    offenders = []
    for path in _generators():
        for lineno, seg in _html_writes(path):
            offenders.append(f"{path.name}:{lineno}  {seg}")
    assert not offenders, (
        "these generators write an HTML page without going through "
        f"v4_apply_chrome.{NORMALIZER}() — the #3721 stale-chrome shape:\n  " + "\n  ".join(offenders)
    )


def test_every_page_generator_routes_through_the_normalizer():
    """The other direction: a generator that is not on the declared non-page list must
    actually call the normalizer. Without this, deleting a generator's only write and
    replacing it with a helper of its own would pass the guard above in silence."""
    missing = []
    for path in _generators():
        if path.name in NON_PAGE_GENERATORS:
            continue
        if f"_apply_chrome.{NORMALIZER}(" not in path.read_text():
            missing.append(path.name)
    assert not missing, (
        f"these generators are not declared non-page and never call v4_apply_chrome.{NORMALIZER}():\n  "
        + "\n  ".join(missing)
        + "\n(if one of them genuinely emits no chrome-bearing page, add it to NON_PAGE_GENERATORS with what it emits)"
    )


def test_the_non_page_list_names_only_real_generators():
    """A stale exemption is a permanently unguarded generator. Every name on the list
    must still exist."""
    present = {p.name for p in _generators()}
    stale = sorted(set(NON_PAGE_GENERATORS) - present)
    assert not stale, "NON_PAGE_GENERATORS names generators that no longer exist: " + ", ".join(stale)


def test_the_normalizer_actually_exposes_the_writer():
    """Reader/writer name match against the real source, not against a memory of it."""
    src = (SCRIPTS / "v4_apply_chrome.py").read_text()
    assert f"def {NORMALIZER}(" in src, f"v4_apply_chrome.py no longer defines {NORMALIZER}()"


def test_the_writer_normalizes_before_writing_not_after():
    """Order is the contract: normalize, then write. A write-then-normalize helper
    leaves a window where the un-normalized bytes are on disk, and a generator whose
    run is interrupted leaves them there."""
    src = (SCRIPTS / "v4_apply_chrome.py").read_text()
    body = src[src.index(f"def {NORMALIZER}(") :]
    body = body[: body.index("\ndef ", 1)]
    assert body.index("rewrite(") < body.index("fh.write("), "write_page writes before it normalizes"


@pytest.mark.parametrize("name", sorted(NON_PAGE_GENERATORS))
def test_a_declared_non_page_generator_really_writes_no_page(name):
    """Each exemption is CHECKED, not asserted: the file must contain no HTML write of
    its own either. An exemption that is wrong is the same defect wearing a label."""
    path = SCRIPTS / name
    assert not _html_writes(path), f"{name} is on NON_PAGE_GENERATORS but writes an HTML page: {_html_writes(path)}"


def test_the_detector_sees_a_write_through_a_module_constant():
    """MUTATION PROOF FOR THE DETECTOR ITSELF. The first version of `_html_writes`
    matched `.html` in the call source only, so five generators writing real reader
    pages through `OUT_PATH = ... / "index.html"` were invisible to it — and my first
    exemption list, written from their docstrings, called two of them "a JSON artifact".

    A guard that cannot see the shape it exists to catch is worth nothing, so the shape
    is planted here rather than trusted."""
    planted = "import pathlib\nOUT_PATH = pathlib.Path('site/method/game/index.html')\n\n\ndef main():\n    OUT_PATH.write_text('<html></html>')\n"
    tree = ast.parse(planted)
    assert _html_page_names(planted, tree) == {"OUT_PATH"}
    hits = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "write_text"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id in _html_page_names(planted, tree)
    ]
    assert hits, "the module-constant write shape is invisible to the detector again"
