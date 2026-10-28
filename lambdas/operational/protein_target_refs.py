"""protein_target_refs.py — #5471: a stated protein FLOOR / target is a reference, not an intake claim.

Split out of `weight_truth_qa` (module-size ceiling, #1665): the figure-scoped exemption `classify_claims_counted` applies
to the protein quantity, kept beside `protein_window_claims` (the other protein-claim reader) and importable without a cycle.
"""

import re

# ── #5471: a protein FLOOR/target is a reference, not an intake claim ─────────
#
# The specimen (2026-10-27, `qa-smoke-failures` CAUSE `cross_surface:coach_vs_engine`): "he ate 126 grams of
# protein yesterday but his floor is 170 grams daily" read 170 as an intake claim and failed it against the
# engine's 138.3 g average. The figure is the charter's protein floor, the number he is short of. The sentence
# exemption (`_VITALS_TARGET_SENTENCE`) cannot carry this: "floor is" is not "floor of", and a sentence-wide
# skip would also drop the real claim ("ate 126 grams") that shares the sentence.
#
# So the exemption is FIGURE-scoped: within one clause (cut at a contrast word or dash) each target word binds
# to the NEAREST gram figure, and only that figure is a target reference. "126 g, well under the 170 g floor"
# binds floor to 170; "his floor is 170 grams" binds to 170; a figure no target word sits beside stays a claim,
# so "he averaged 170 g this week" still fails. Counted, never silent (the emitted counts line names it).
_TARGET_WORD = re.compile(r"\b(?:floors?|targets?|goals?|minimums?|quotas?)\b", re.IGNORECASE)
_GRAM_FIGURE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:g\b|grams?\b)", re.IGNORECASE)
_CLAUSE_CUT = re.compile(r"\b(?:but|while|whereas|though|although|yet|however)\b|[—–]|\s-\s", re.IGNORECASE)
_TARGET_REACH_CHARS = 40  # a target word more than this far from every gram figure binds to none


def protein_target_starts(sentence: str) -> set:
    """Offsets (in `sentence`) of the gram figures a floor/target/goal/minimum word binds to — see above."""
    starts: set = set()
    cuts = [0] + [x for m in _CLAUSE_CUT.finditer(sentence) for x in (m.start(), m.end())] + [len(sentence)]
    for lo, hi in zip(cuts[0::2], cuts[1::2]):
        clause = sentence[lo:hi]
        figures = [(lo + m.start(1), lo + m.end()) for m in _GRAM_FIGURE.finditer(clause)]
        if not figures:
            continue
        for w in _TARGET_WORD.finditer(clause):
            ws, we = lo + w.start(), lo + w.end()
            gap, start = min((max(fs - we, ws - fe, 0), fs) for fs, fe in figures)
            if gap <= _TARGET_REACH_CHARS:
                starts.add(start)
    return starts
