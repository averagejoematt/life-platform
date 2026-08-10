"""#1905 — /legacy may not attribute coach voices to real people, and it can't return.

Decision of record (issue #1905, recorded here so the next sweep does not
re-litigate it):

  * `/legacy/**` STAYS publicly reachable (HTTP 200, noindex, never linked from
    the UI) — `deploy/smoke_test_site.sh` pins that reachability.
  * In exchange, the tree is inside EVERY static privacy gate: the `legacy`
    exclusions were deleted from `deploy/pii_surface_guard.py::_SKIP_DIRS` and
    `scripts/content_policy_scan.py::SKIP_SUBDIRS` (they had silently created a
    ~170-file zone of the public surface no privacy gate inspected), and this
    test adds the arm neither scanner had: real-person name attributions.
  * Rollback-fidelity of the verbatim archive was deliberately traded for
    scrubbing the real-clinician coach-voice attributions (option 3 of the
    issue) — the archive is no longer byte-identical to the retired v3 site.

The banned-name vocabulary is DERIVED from `privacy_guard` (the platform's one
definition of "real figures the AI tends to name as coaches") — never a copied
list, so a widened guard vocabulary automatically widens this scan.

Genuine citations are allowed and count-pinned below: a PubMed-linked
literature citation, a podcast title in an information-diet list, and the
subject's own quoted speech are references, not coach-voice attributions —
the exact line `privacy_guard`'s docstring draws.
"""

import os
import re
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from privacy import privacy_guard  # noqa: E402

LEGACY_ROOT = os.path.join(_REPO, "site", "legacy")

# Text artifacts that ship to the public surface (superset of what the two
# repo scanners look at for /legacy).
_TEXT_EXT = {".html", ".js", ".css", ".json", ".txt", ".xml", ".svg", ".md", ".webmanifest"}

# (relpath-under-site/legacy, banned term) -> exact expected count.
# Every entry is a CITATION, not an attribution — justification inline. A
# count drift in either direction fails: new mentions can't hide behind an
# existing entry, and a stale entry can't outlive its citation.
ALLOWED_CITATIONS = {
    # Literature citations with PubMed provenance on the protocols page
    # ("Published literature (Walker, 2017; Huberman, 2021)" + the linked
    # "Huberman (2021) — Temperature & light timing…" reference row).
    ("protocols/index.html", "huberman"): 2,
    # Podcast titles in the information-diet chip list ("Huberman Lab",
    # "The Drive (Attia)") — names of media properties the subject consumes,
    # not voices the platform claims.
    ("experiments/index.html", "huberman"): 1,
    ("experiments/index.html", "attia"): 1,
    # The subject's own quoted speech in an archived interview ("Not a
    # Goggins cycle, he said") — a cultural reference in first-person
    # narrative, not a coach attribution.
    ("chronicle/posts/interview/index.html", "goggins"): 1,
    # Research citation: "Dr. Vivek Murthy's research on loneliness convinced
    # me that social connection is a health metric" — cites the former Surgeon
    # General's published work as motivation; no voice or staff claim.
    ("community/index.html", "vivek murthy"): 1,
}


def _iter_text_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in _TEXT_EXT:
                yield os.path.join(dirpath, fn)


def _count_hits(text):
    """Mirror privacy_guard.find_violations' two name arms, with counts."""
    lowered = text.lower()
    hits = {}
    for nm in privacy_guard.BANNED_FULL_NAMES:
        c = lowered.count(nm)
        if c:
            hits[nm] = hits.get(nm, 0) + c
    for sn in privacy_guard.BANNED_SURNAMES:
        c = len(re.findall(r"\b" + re.escape(sn) + r"\b", text, re.IGNORECASE))
        if c:
            hits[sn] = hits.get(sn, 0) + c
    return hits


def scan_legacy_tree(root):
    """Return {(relpath, term): count} for every banned-name hit under root."""
    found = {}
    for path in _iter_text_files(root):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for term, count in _count_hits(text).items():
            found[(rel, term)] = count
    return found


# ── The gate ─────────────────────────────────────────────────────────────────


def test_legacy_tree_exists_and_is_nonempty():
    assert os.path.isdir(LEGACY_ROOT), "site/legacy missing — scan target gone"
    assert sum(1 for _ in _iter_text_files(LEGACY_ROOT)) > 50, "suspiciously few files — scan would be vacuous"


def test_no_real_person_attributions_in_legacy():
    found = scan_legacy_tree(LEGACY_ROOT)
    violations = {k: v for k, v in found.items() if ALLOWED_CITATIONS.get(k) != v}
    assert not violations, (
        "Real-person name(s) on the publicly served /legacy tree outside the "
        "count-pinned citation allowlist (#1905 — scrub or, for a genuine "
        f"citation, pin it with a justification): {sorted(violations.items())}"
    )


def test_allowlist_entries_are_still_live():
    """A stale allowlist entry (file gone / citation removed) must fail, not rot."""
    found = scan_legacy_tree(LEGACY_ROOT)
    stale = {k: v for k, v in ALLOWED_CITATIONS.items() if k not in found}
    assert not stale, f"stale ALLOWED_CITATIONS entries — remove them: {sorted(stale)}"


def test_banned_vocabulary_is_derived_not_copied():
    """Guard the SET: the scan must consume privacy_guard's live tuples."""
    assert len(privacy_guard.BANNED_FULL_NAMES) >= 10
    assert len(privacy_guard.BANNED_SURNAMES) >= 3
    # A term present in the guard vocabulary is a term this scan searches for.
    assert "peter attia" in privacy_guard.BANNED_FULL_NAMES
    assert "attia" in privacy_guard.BANNED_SURNAMES


# ── Mutation proof: the scan actually fires ──────────────────────────────────


@pytest.mark.parametrize(
    "planted",
    [
        "Voice shaped by Peter Attia's exercise-as-medicine framework",  # full name (the #1905 class verbatim)
        "as Huberman recommends",  # standalone surname
    ],
)
def test_scan_fires_on_a_planted_attribution(tmp_path, planted):
    site = tmp_path / "legacy" / "somepage"
    site.mkdir(parents=True)
    (site / "index.html").write_text(f"<html><body><p>{planted}</p></body></html>", encoding="utf-8")
    found = scan_legacy_tree(str(tmp_path / "legacy"))
    assert found, f"scan did not fire on planted text: {planted!r}"
    assert all(rel == "somepage/index.html" for rel, _ in found)


def test_scan_counts_so_growth_next_to_an_allowlisted_citation_is_caught(tmp_path):
    """The allowlist pins counts: a SECOND mention in an allowlisted file must trip."""
    root = tmp_path / "legacy"
    (root / "protocols").mkdir(parents=True)
    # Simulate the allowlisted file gaining one extra mention beyond its pin.
    (root / "protocols" / "index.html").write_text("Huberman (2021) citation. Huberman again. A third Huberman.", encoding="utf-8")
    found = scan_legacy_tree(str(root))
    key = ("protocols/index.html", "huberman")
    assert found[key] == 3
    assert ALLOWED_CITATIONS[key] != found[key], "count pin failed to distinguish growth"
