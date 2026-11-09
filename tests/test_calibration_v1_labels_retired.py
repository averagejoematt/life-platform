"""tests/test_calibration_v1_labels_retired.py — no reader surface shows a calibration-v1 label (owner ruling 2026-11-09).

The owner adopted calibration-v2 on 2026-11-09: three separate questions, each with its own test and interval, and
words that never praise a forecaster for passing a test. The v1 labels (``calibration_core``: one word per forecaster
from a fixed ±0.15 gap trip and a skill gate) stay in the API only as deprecated fields. This guard holds the reader
side of that:

  * ``test_no_v1_label_in_served_pages_or_scripts`` — every file the site serves from ``site/`` (HTML, JS, JSON; the
    never-linked ``/legacy`` and ``/next`` archives excepted) and every source file of the v9 build (``www/src``) is
    free of the v1-only vocabulary. Two exemptions, each with its reason, and the exemption list is itself checked to
    still match a real file that still needs it (so it cannot rot into a hole).
  * ``test_the_scanner_catches_a_planted_v1_label`` — MUTATION CONTROL: the same scanner over planted strings in every
    spelling a v1 surface used ("Well Calibrated", "not_yet_skillful", "Not Yet Skillful", "not measurable") hits.
  * ``test_grade_your_coach_never_reads_the_v1_fields`` — the one page that still imports the vendored v1 scorer
    (for its Brier score and reliability curve) never reads that scorer's ``calibration`` / ``label`` / ``score``.
  * ``test_the_api_keeps_v1_fields_only_as_deprecated`` — ``calibration_method`` names the v1 fields as deprecated and
    calibration-v2 as the adopted authority, with a dated method history.
  * ``test_v2_words_never_praise`` — over a grid of synthetic ledgers, no calibration-v2 sentence says a forecaster is
    well calibrated, good, reliable or skilled; a non-rejection always reads "(not established)" or "insufficient
    evidence".
"""

# premerge-gate: calibration-v2 adoption (owner 2026-11-09): an rglob sweep of site/ and www/src for the retired v1 calibration labels — it fails on the diff that re-introduces one on a reader surface, so it belongs before merge.
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

#: The v1-only vocabulary, in every spelling a v1 surface rendered it.
V1_LABEL = re.compile(r"well[\s_-]?calibrated|not[\s_-]?yet[\s_-]?skillful|not[\s_-]measurable", re.IGNORECASE)

SERVED_SUFFIXES = {".html", ".js", ".mjs", ".json", ".astro", ".ts"}
SKIP_PREFIXES = ("site/legacy/", "site/next/")  # never-linked archives of earlier site versions (CLAUDE.md: never link /legacy)

#: path → why it may still contain the vocabulary. Each must exist and still contain it (checked below).
EXEMPT = {
    "site/assets/js/calibration-core.js": (
        "the vendored, byte-identical copy of oss/calibration-core (pinned by tests/test_calibration_core_parity.py); it "
        "still COMPUTES the deprecated v1 field, and no page renders it (test_grade_your_coach_never_reads_the_v1_fields)"
    ),
    "site/story/build/beats.json": "a dated build-history narrative quoting a badge the site once showed; history, not a verdict",
}


def _served_files():
    for top in ("site", "www/src"):
        for p in sorted((ROOT / top).rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and p.suffix in SERVED_SUFFIXES and not rel.startswith(SKIP_PREFIXES):
                yield rel, p


def scan(text: str) -> list[str]:
    return [m.group(0) for m in V1_LABEL.finditer(text)]


def test_no_v1_label_in_served_pages_or_scripts():
    hits = {}
    for rel, p in _served_files():
        if rel in EXEMPT:
            continue
        found = scan(p.read_text(encoding="utf-8", errors="replace"))
        if found:
            hits[rel] = sorted(set(found))[:5]
    assert not hits, f"calibration-v1 labels on a reader surface (owner ruling 2026-11-09 retired them): {hits}"


def test_the_exemptions_are_real_and_still_needed():
    for rel, why in EXEMPT.items():
        p = ROOT / rel
        assert p.is_file(), f"stale exemption, file gone: {rel}"
        assert scan(p.read_text(encoding="utf-8")), f"stale exemption, {rel} no longer needs it ({why})"


def test_the_scanner_catches_a_planted_v1_label():
    for planted in (
        '<td class="cal">Well Calibrated</td>',
        "fig('Not Yet Skillful', 'n=12')",
        '{"calibration": "not_yet_skillful"}',
        "one stated confidence — not measurable",
        "reads well-calibrated",
        '"calibration": "not_measurable"',
    ):
        assert scan(planted), planted
    # …and the words calibration-v2 does use are NOT flagged.
    for ok in (
        "Over-confident at its 50% calls (12 of 43 came true, 95% CI 15%–44%; Holm-adjusted p 0.0108)",
        "Consistent with stated confidence (not established)",
        "Insufficient evidence",
        "No demonstrated advantage over the guess that nothing changes",
        "Calibration across confidence levels not estimable",
    ):
        assert not scan(ok), ok


def test_grade_your_coach_never_reads_the_v1_fields():
    js = (ROOT / "site" / "assets" / "js" / "grade_your_coach.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith("//"))
    assert 'from "/assets/js/calibration-v2-core.js"' in code, "the verdict must come from the calibration-v2 port"
    for v1 in ("s.calibration", "s.label", "s.score", "VERDICT_COPY", "LABEL_COPY"):
        assert v1 not in code, f"grade_your_coach.js reads the deprecated v1 field via {v1!r}"


def test_the_legacy_calibration_page_reads_only_v2_for_its_verdict():
    js = (ROOT / "site" / "assets" / "js" / "evidence_intelligence.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith("//"))
    assert re.search(r"\.calibration\b", code) is None, "evidence_intelligence.js reads a v1 `calibration` field"
    assert "calibration_v2_words.js" in code


def test_the_api_keeps_v1_fields_only_as_deprecated():
    from web import site_api_calibration_v2 as s

    m = s.method_block()
    assert m["status"] == "adopted" and m["adopted"] == "2026-11-09" and m["authority"] == "assessment_v2"
    assert set(m["deprecated_fields"]["fields"]) == {"calibration", "label", "score"}
    assert [h["version"] for h in m["history"]] == ["calibration-v1", "calibration-v2"]
    assert m["history"][0]["until"] == m["history"][1]["effective"] == "2026-11-09"
    assert all(h["note"] for h in m["history"])
    a = s.assessment_v2({"sleep": []}, {"hypotheses": []})
    assert a["status"] == "adopted" and a["adopted"] == "2026-11-09" and a["method_history"] == m["history"]


PRAISE = re.compile(r"\bwell[\s-]?calibrated\b|\bgood\b|\breliable\b|\bskilled\b|\bskillful\b|\baccurate\b|\bexcellent\b|\bstrong\b", re.I)


def test_v2_words_never_praise():
    from experiment import calibration_v2

    rng = random.Random(20261109)
    seen = set()
    for _ in range(300):
        n = rng.choice([0, 1, 3, 8, 20, 45, 120])
        levels = rng.sample([0.1, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9], k=rng.choice([1, 2, 3]))
        pairs = []
        for _ in range(n):
            p = rng.choice(levels)
            pairs.append((p, 1 if rng.random() < rng.choice([p, p * 0.6, min(1.0, p * 1.4)]) else 0))
        a = calibration_v2.assess(pairs)
        for q in ("estimability", "confidence_direction", "skill"):
            for field in ("wording", "short"):
                assert not PRAISE.search(a[q][field]), (q, a[q][field])
        cd = a["confidence_direction"]
        seen.add(cd["result"])
        if cd["result"] == "consistent_not_established":
            assert "(not established)" in cd["wording"]
        if cd["result"] in ("over_confident", "under_confident", "mixed"):
            assert "at its" in cd["wording"] and "not about calibration across confidence levels" in cd["wording"]
    assert {"consistent_not_established", "insufficient_evidence", "over_confident"} <= seen
