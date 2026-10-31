"""lean_mass_claims.py — a pound figure NAMED as lean / fat-free mass is a body-composition reading, not his weight (#5458).

Split beside `rate_claims` for the same reason: `weight_truth_qa` sits at the module-size ceiling (#1665).

The 2026-10-28 and 2026-10-31 analyzer runs both held the physical expert on "cites 170.6 lb as his weight; the latest
served weigh-in is 29x lb". 170.6 lb is the DXA lean mass the physical context serves (`weight_recency.dexa_facts`),
labelled "NOT his body weight" beside the figure, with a prompt rider (`dexa_prompt_block`) asking for the scan date in
the same sentence. The model wrote the figure as lean mass and left the date out, twice, and the regen did the same.
`weights_cited_in` read every pound figure of 100 or more as a bodyweight claim, so a correctly LABELLED lean-mass
figure was judged as his weight. That is a misreading by the extractor, not a wrong number by the model.

The label must sit right beside the figure: "lean mass of 170.6 lb", "170.6 lb of lean mass", "170.6 lb lean",
"fat-free mass sits at 170.6 lb", "your lean mass floor of 155 lb". "You look lean at 280 lb" and "lean mass is fine,
and you weigh 280 lb" are still his weight. Whether a lean figure was SERVED at all stays with the allow-list
(`grounded_generation.fabricated_numbers`), so a made-up lean figure is still held there.
"""

import re

_LEAN_NOUN = r"(?:lean(?:\s+body)?\s+(?:mass|tissue)|fat[-\s]free\s+mass|ffm|muscle\s+mass)"
_LEAN_BEFORE = re.compile(
    r"\b" + _LEAN_NOUN + r"(?:\s+(?:floor|reading|figure))?(?:\s+(?:of|is|was|at|measured|sits\s+at|came\s+in\s+at))*"
    r"[\s,:(—–-]+(?:about\s+|roughly\s+)?$",
    re.IGNORECASE,
)
_LEAN_AFTER = re.compile(r"^\s*(?:of\s+)?(?:lean|fat[-\s]free|ffm|muscle\s+mass)\b", re.IGNORECASE)
# How far before the figure the label may start: "fat-free mass came in at roughly " is 33 characters.
_BEFORE_WINDOW_CHARS = 40


def lean_mass_figure(text: str, start: int, end: int) -> bool:
    """True when the pound figure spanning `text[start:end]` (number AND unit) is labelled lean / fat-free mass."""
    return bool(_LEAN_BEFORE.search(text[max(0, start - _BEFORE_WINDOW_CHARS) : start]) or _LEAN_AFTER.match(text[end:]))
