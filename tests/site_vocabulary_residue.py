"""tests/site_vocabulary_residue.py — the dated, shrink-only ledger behind the vocabulary guard (#4182).

Per registered term in site/data/glossary.json: the number of reader pages whose STATIC
main content still carried it when the guard landed. Measured 2026-09-26 at main 44c77f11c
by tests/test_site_vocabulary_registry.py's own census (word-bounded, case-insensitive,
"as of" also matching as_of; a keep-with-gloss term counts only pages with no <dfn>/<abbr title>). Ratchet semantics, the same as tests/test_module_size_guard.py:

  * a term's page count may only go DOWN — a new reader page using a cut/renamed term, or an
    old page gaining it, reds the guard with the pages named;
  * shrinking never auto-tightens (that would make every copy edit touch this file);
    tightening a number after a real pass is welcome and always allowed;
  * removing a term from the registry is a decision made on the PR that makes it.

Terms ruled keep-with-gloss are ratcheted too: the count is of pages that use the term
WITHOUT a gloss (<dfn>/<abbr title>) anywhere on the page — the gloss is what lets the count
move down without the word leaving.
"""

MEASURED_AT = "2026-09-26 · main 44c77f11c"

BASELINE = {
    "reset": 33,
    "correlation": 2,
    "cockpit": 20,
    "chronicle": 14,
    "model": 13,
    "as of": 12,
    "cycle": 8,
    "Third Wall": 9,
    "pillar": 5,
    "protocol": 2,
    "gate": 5,
    "HRV": 3,
    "glucose": 2,
    "Whoop": 3,
    "character level": 5,
}

# The static-reach ratchet (ruling vi): reader pages reachable from "/" by <a href> links in
# the static HTML. 39 at landing (of 91 pages). The owner's cap (24 proposed) is set by
# lowering this number; until then the count may only fall.
NAV_REACH_CEILING = 39
