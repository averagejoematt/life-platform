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

import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import og_image_lambda  # noqa: E402

# Cards deliberately generated but NOT expected on any non-legacy public page. Keep this
# EMPTY unless a card genuinely has no honest public home — an entry here is a documented
# admission that the sweep draws a card nothing serves. Add a `# reason:` note per entry.
ORPHAN_ALLOWLIST: frozenset[str] = frozenset()

_SITE = os.path.join(_REPO, "site")


def _served_card_files() -> set[str]:
    """Every `<card>.png` filename referenced by any non-legacy site/ HTML page."""
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
            for card_name, _builder in og_image_lambda.PAGES:
                if f"{card_name}.png" in text:
                    served.add(card_name)
    return served


def test_every_og_card_is_served_by_a_nonlegacy_page():
    served = _served_card_files()
    card_names = [c for c, _ in og_image_lambda.PAGES]
    unserved = [c for c in card_names if c not in served and c not in ORPHAN_ALLOWLIST]
    assert not unserved, (
        "OG cards drawn daily by the og-image sweep but referenced by ZERO non-legacy page "
        f"(and not on ORPHAN_ALLOWLIST): {sorted(unserved)}. Point the matching page's "
        "og:image at each card via v4_build_evidence.py OG_CARD_BY_SLUG or "
        "v4_build_dispatches.py OG_CARD_BY_SECTION, or add it to ORPHAN_ALLOWLIST with a reason."
    )


def test_orphan_allowlist_entries_are_real_cards():
    """No stale allowlist entries — every allowlisted name must be a real sweep card."""
    card_names = {c for c, _ in og_image_lambda.PAGES}
    stale = ORPHAN_ALLOWLIST - card_names
    assert not stale, f"ORPHAN_ALLOWLIST names not in og_image_lambda.PAGES: {sorted(stale)}"
