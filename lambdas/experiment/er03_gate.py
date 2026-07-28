"""er03_gate.py — ER-03 offline truthfulness gate for reader-facing coach AI (CC-08).

Every coach-authored public string must pass this BEFORE it's published:
  * no banned causal connectives (reflections are correlative, never causal),
  * a confidence/hedge word present when the sample is small (N < 30),
  * every number in the output is present in the input (anti-fabrication —
    also catches LLM arithmetic, since a computed number won't be in the input),
  * no "Matthew"-prefixed opening (the in-voice opening rule).

Pure functions, no AWS — unit-tested in tests/test_er03_gate.py and called by the
coach-daily-reflection batch. Fail-closed: anything that doesn't pass is dropped,
never published.
"""

import re

# Causal language a correlative reflection must not use (Henning/ER-03 standard).
BANNED_CAUSAL = [
    "causes",
    "caused",
    "causing",
    "because",
    "due to",
    "leads to",
    "led to",
    "results in",
    "resulted in",
    "makes you",
    "made you",
    "thanks to",
    "drives your",
    "drove your",
    "the reason",
]

# Hedges that signal honest, correlative, small-sample framing.
HEDGES = [
    "preliminary",
    "early",
    "so far",
    "tentative",
    "appears",
    "appear",
    "seems",
    "suggest",
    "suggests",
    "correlat",
    "associat",
    "tends to",
    "trend",
    "may",
    "might",
    "could",
    "looks like",
    "not yet",
]

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _has(low: str, phrase: str) -> bool:
    """Word-boundary match — avoids substring false-positives like 'early' in 'clearly'."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", low) is not None


def numbers_in(text: str) -> set:
    """Set of distinct numeric values in a string (as floats)."""
    out = set()
    for m in _NUM_RE.findall(text or ""):
        try:
            out.add(round(float(m), 4))
        except ValueError:
            pass
    return out


def er03_check(text: str, allowed_numbers=None, n=None) -> tuple:
    """Return (ok: bool, reasons: list[str]). ok=True means safe to publish.

    allowed_numbers: iterable of numeric values present in the model's INPUT.
                     Any output number not in this set is a fabrication.
    n:               sample size behind the claim, if known. When n < 30 the
                     text must carry a hedge/confidence word.
    """
    reasons = []
    t = (text or "").strip()
    if not t:
        return False, ["empty"]

    low = t.lower()

    # 1) no "Matthew"-prefixed opening
    if low.startswith("matthew"):
        reasons.append("opens with 'Matthew' (in-voice opening rule)")

    # 2) no banned causal connectives
    for phrase in BANNED_CAUSAL:
        if _has(low, phrase):
            reasons.append(f"causal connective: {phrase!r}")

    # 3) anti-fabrication: every output number must appear in the input
    allowed = {round(float(x), 4) for x in (allowed_numbers or [])}
    for x in numbers_in(t):
        if not any(abs(x - a) < 0.01 for a in allowed):
            reasons.append(f"fabricated number: {x:g} not in input")

    # 4) small-sample claims must be hedged
    if n is not None and n < 30:
        if not any(_has(low, h) for h in HEDGES):
            reasons.append(f"unhedged claim at small N={n} (needs confidence framing)")

    return (len(reasons) == 0), reasons
