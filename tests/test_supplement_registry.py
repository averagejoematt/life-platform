"""tests/test_supplement_registry.py — honesty guards for the public supplement registry.

Two regression guards, both provably non-vacuous (each has a synthetic pre-fix case
that MUST be flagged):

* #1216 — supplement "challenge" citations must be real articles, not PubMed
  SEARCH-QUERY URLs (`?term=...`) dressed up as studies. A skeptic who clicks the
  dissent must land on a citation that exists.

* #1217 — supplement "science" bullets must not state marketing overstatements as
  flat facts. Any quantitative population claim ("X% of Americans/people") must be
  hedged AND backed by an adjacent supporting source, or it is a violation.

The registry is served verbatim to averagejoematt.com via
`lambdas/web/site_api_data.py::handle_supplements` and rendered by
`site/assets/js/evidence_body.js`, so these run in the offline suite as the gate.
"""

import json
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REGISTRY_PATH = os.path.join(_REPO, "config", "supplement_registry.json")

# A citation URL must resolve to a specific article, not a search results page.
# Accepted: PubMed article (pubmed.ncbi.nlm.nih.gov/<digits>), PMC article, or a DOI.
_ARTICLE_URL_RE = re.compile(
    r"^https?://(" r"pubmed\.ncbi\.nlm\.nih\.gov/\d+/?" r"|(www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/PMC\d+/?" r"|(dx\.)?doi\.org/\S+" r")",
    re.IGNORECASE,
)

# "X% of Americans / people / adults / (the) (US) population" — a population-prevalence claim.
_POP_PERCENT_RE = re.compile(
    r"\b\d{1,3}\s*%\s+of\s+(the\s+)?(us\s+)?(americans|people|adults|population)\b",
    re.IGNORECASE,
)

# Tokens that signal an honest hedge on a population figure (approximation / framing).
_HEDGE_TOKENS = (
    "~",
    "about",
    "around",
    "nearly",
    "roughly",
    "approximately",
    "up to",
    "estimated",
    "estimate",
    "less than",
    "inadequate",
    "insufficient",
    "may ",
)


def _load_registry():
    with open(_REGISTRY_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _iter_items(registry):
    """Yield (group_key, item) for every supplement item across all groups."""
    for gkey, group in (registry.get("groups") or {}).items():
        for item in group.get("items") or []:
            yield gkey, item


def find_bad_source_urls(registry):
    """#1216 guard: return a list of (item_name, url) for any source URL that is a
    search query (`?term=`) or does not match a specific-article pattern."""
    bad = []
    for _gkey, item in _iter_items(registry):
        for src in item.get("sources") or []:
            url = (src or {}).get("url")
            if not url:
                # Source-less entries (e.g. an honest "open question — no direct
                # study found" stance) are allowed; they carry no dead citation.
                continue
            if "?term=" in url or not _ARTICLE_URL_RE.match(url):
                bad.append((item.get("name"), url))
    return bad


def find_unhedged_population_claims(registry):
    """#1217 guard: return a list of (item_name, bullet) for any 'X% of Americans/people'
    science bullet that is unhedged OR lacks an adjacent supporting article source."""
    bad = []
    for _gkey, item in _iter_items(registry):
        # Does the item carry at least one real (article-URL) source to lean on?
        has_article_source = any(
            (src or {}).get("url") and _ARTICLE_URL_RE.match(src["url"]) and "?term=" not in src["url"] for src in item.get("sources") or []
        )
        for bullet in item.get("science") or []:
            if not _POP_PERCENT_RE.search(bullet or ""):
                continue
            lowered = (bullet or "").lower()
            hedged = any(tok in lowered for tok in _HEDGE_TOKENS)
            if not hedged or not has_article_source:
                bad.append((item.get("name"), bullet))
    return bad


# ── Live-data guards (fail if the real registry regresses) ──────────────────────


def test_registry_parses():
    reg = _load_registry()
    assert reg.get("groups"), "registry has no groups"


def test_no_search_query_or_nonarticle_citation_urls():
    """#1216: every source URL in the live registry resolves to a real article."""
    bad = find_bad_source_urls(_load_registry())
    assert not bad, "search-query / non-article citation URLs found:\n" + "\n".join(f"  {n}: {u}" for n, u in bad)


def test_no_unhedged_population_claims():
    """#1217: every 'X% of Americans/people' bullet is hedged and sourced."""
    bad = find_unhedged_population_claims(_load_registry())
    assert not bad, "unhedged/unsourced population claims found:\n" + "\n".join(f"  {n}: {b}" for n, b in bad)


# ── Non-vacuity proofs (the guards MUST flag the pre-fix data) ───────────────────


def test_guard_flags_pubmed_search_url():
    """Proves the #1216 guard is non-vacuous: it catches a `?term=` search URL."""
    prefix = {
        "groups": {
            "sleep": {
                "items": [
                    {
                        "name": "Magnesium L-Threonate",
                        "sources": [
                            {
                                "title": "cost-effectiveness analysis",
                                "url": "https://pubmed.ncbi.nlm.nih.gov/?term=magnesium+L-threonate+bioavailability+comparison",
                                "stance": "challenges",
                            }
                        ],
                    }
                ]
            }
        }
    }
    bad = find_bad_source_urls(prefix)
    assert bad == [("Magnesium L-Threonate", "https://pubmed.ncbi.nlm.nih.gov/?term=magnesium+L-threonate+bioavailability+comparison")]


def test_guard_flags_unhedged_population_claim():
    """Proves the #1217 guard is non-vacuous: it catches '80% of Americans are magnesium deficient'."""
    prefix = {
        "groups": {
            "sleep": {
                "items": [
                    {
                        "name": "Magnesium L-Threonate",
                        "science": ["80% of Americans are magnesium deficient"],
                        "sources": [{"title": "real", "url": "https://pubmed.ncbi.nlm.nih.gov/20152124/", "stance": "supports"}],
                    }
                ]
            }
        }
    }
    bad = find_unhedged_population_claims(prefix)
    assert bad == [("Magnesium L-Threonate", "80% of Americans are magnesium deficient")]


def test_guard_passes_hedged_sourced_population_claim():
    """The corrected framing (hedged + sourced) is accepted."""
    fixed = {
        "groups": {
            "sleep": {
                "items": [
                    {
                        "name": "Magnesium L-Threonate",
                        "science": [
                            "~48% of Americans consume less magnesium than the estimated average requirement"
                            " (NHANES); clinical deficiency is far less common"
                        ],
                        "sources": [{"title": "NHANES", "url": "https://pubmed.ncbi.nlm.nih.gov/22364157/", "stance": "supports"}],
                    }
                ]
            }
        }
    }
    assert find_unhedged_population_claims(fixed) == []
