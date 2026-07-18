"""#1237 — every daily OG share card the og-image sweep renders must be SERVED.

`lambdas/web/og_image_lambda.py` PAGES draws a fresh per-topic PNG share card daily
(og-sleep, og-glucose, …). The platform's best discovery asset is a fresh, per-topic
link preview — but a card is worthless if no page points its `og:image` at it. Before
#1237, 10 of the 12 data-driven cards were referenced by ZERO non-legacy page, so every
/data/ subpage and the chronicle fell back to the generic og-home.png; the sweep drew
cards nothing served.

This guard asserts every card name in PAGES is referenced by at least one NON-LEGACY
site/ page (its `og:image` meta), or is on the explicit, documented ORPHAN_ALLOWLIST.
It fails the moment a new card is added to the sweep without a page to serve it (or an
old page stops referencing its card) — the exact regression #1237 fixed.

Wiring lives in the two site generators, keyed so the committed HTML can't drift:
  - scripts/v4_build_evidence.py  OG_CARD_BY_SLUG    (/data/*, /protocols/experiments/)
  - scripts/v4_build_dispatches.py OG_CARD_BY_SECTION (/story/chronicle, /build, /timeline)
"""

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OG_LAMBDA_SRC = os.path.join(_REPO, "lambdas", "web", "og_image_lambda.py")


def _page_card_names() -> list[str]:
    """Card basenames from `og_image_lambda.PAGES`, read via AST — NOT by importing.

    The lambda module imports Pillow (PIL) at top level; Pillow is a runtime
    dependency LAYER, absent from the CI test runner, so importing it here reds the
    whole suite at collection. Parsing the source keeps this guard non-vacuous in CI
    without dragging PIL in. PAGES is a list of ("og-<topic>", builder) tuples.
    """
    tree = ast.parse(open(_OG_LAMBDA_SRC, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PAGES" for t in node.targets):
            names = []
            for elt in node.value.elts:  # each elt is a ("og-name", builder) tuple
                first = elt.elts[0]
                assert isinstance(first, ast.Constant) and isinstance(
                    first.value, str
                ), "PAGES tuple's first element is expected to be a string card name literal"
                names.append(first.value)
            assert names, "PAGES parsed to an empty list — parser out of sync with og_image_lambda.py"
            return names
    raise AssertionError("could not find PAGES assignment in og_image_lambda.py")


# Cards deliberately generated but NOT expected on any non-legacy public page. Keep this
# EMPTY unless a card genuinely has no honest public home — an entry here is a documented
# admission that the sweep draws a card nothing serves. Add a `# reason:` note per entry.
ORPHAN_ALLOWLIST: frozenset[str] = frozenset()

_SITE = os.path.join(_REPO, "site")


def _served_card_files() -> set[str]:
    """Every `<card>.png` filename referenced by any non-legacy site/ HTML page."""
    card_names = _page_card_names()
    served: set[str] = set()
    for root, _dirs, files in os.walk(_SITE):
        # site/legacy/** is the frozen old site — its references do not count (#1237).
        if os.path.sep + "legacy" in os.path.sep + os.path.relpath(root, _SITE):
            continue
        for name in files:
            if not name.endswith(".html"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                text = fh.read()
            for card_name in card_names:
                if f"{card_name}.png" in text:
                    served.add(card_name)
    return served


def test_every_og_card_is_served_by_a_nonlegacy_page():
    served = _served_card_files()
    card_names = _page_card_names()
    unserved = [c for c in card_names if c not in served and c not in ORPHAN_ALLOWLIST]
    assert not unserved, (
        "OG cards drawn daily by the og-image sweep but referenced by ZERO non-legacy page "
        f"(and not on ORPHAN_ALLOWLIST): {sorted(unserved)}. Point the matching page's "
        "og:image at each card via v4_build_evidence.py OG_CARD_BY_SLUG or "
        "v4_build_dispatches.py OG_CARD_BY_SECTION, or add it to ORPHAN_ALLOWLIST with a reason."
    )


def test_orphan_allowlist_entries_are_real_cards():
    """No stale allowlist entries — every allowlisted name must be a real sweep card."""
    card_names = set(_page_card_names())
    stale = ORPHAN_ALLOWLIST - card_names
    assert not stale, f"ORPHAN_ALLOWLIST names not in og_image_lambda.PAGES: {sorted(stale)}"
