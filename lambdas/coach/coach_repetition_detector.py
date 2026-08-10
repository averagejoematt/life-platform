"""
coach_repetition_detector.py — deterministic self-repetition detector (#2350)

"The coach said this same thing nine times" becomes a measurable fact instead of
an impression. Given a candidate output and the coach's own trailing OUTPUT#
history, this module scores how much of the candidate's *phrasing* is reused
from an earlier output and flags when that reuse exceeds a threshold derived
from the coach's own measured output-to-output variance.

ADR-105 discipline, all four clauses:
  * **Deterministic computation before any LLM verdict** — this is plain-code
    similarity (token-set Jaccard + word 3-gram shingle Jaccard). No LLM call,
    no embedding call, no network at all: the module is pure and takes its
    corpus as an argument.
  * **Thresholds from personal variance, not guessed constants** — the flag
    threshold is `mean + BASELINE_K * stddev` of the pairwise shingle-Jaccard
    distribution over the coach's own trailing history, clamped to a stated
    domain floor/ceiling. A chatty coach with naturally overlapping outputs
    earns a higher bar than a terse one. The derivation is stated in the
    report, with n.
  * **Uncertainty + n stated** — every report carries `n_history`, `n_pairs`,
    the baseline mean/std, and the derived threshold.
  * **A flagged repetition is checkable, not asserted** — the finding names the
    earlier output it resembles (its DynamoDB sk) plus an excerpt and the score.

Advisory posture (issue acceptance / ADR-108 promotion pattern): the detector
only reports. It never blocks, never regenerates, and the caller must not flip
a pass/fail bit on it until its flag rate has been measured against real
outputs.

Fail-soft honesty: a verdict of "novel" is only ever produced from a computed
score against a sufficient baseline. Missing history, degenerate text, or an
internal error all yield `verdict: None` with a stated status — absence, never
a green "no repetition".

Tunable constants (module top) are plain integers/floats so operators can tune
without code archaeology.

v1.0.0 — 2026-08-09 (#2350, epic #1080; roadmap idea 42)
"""

from itertools import combinations

# ══════════════════════════════════════════════════════════════════════════════
# TUNABLE CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# How many of the coach's own most-recent outputs the candidate is compared
# against (the issue's "trailing 30").
TRAILING_WINDOW = 30

# Word n-gram size for the shingle similarity. 3-word shingles are the smallest
# unit that captures *phrasing* rather than shared vocabulary: two outputs about
# sleep will always share tokens ("sleep", "recovery", "hrv"), but they only
# share 3-grams when whole phrases are reused.
SHINGLE_N = 3

# Threshold = baseline_mean + BASELINE_K * baseline_std over the pairwise
# similarity distribution of the coach's own history (ADR-105: personal
# variance, not a guessed constant). K=2 flags a candidate more similar to some
# earlier output than ~97.7% of the coach's normal output-to-output overlap
# would predict (one-sided, under a normal approximation of the pairwise
# distribution — stated as an approximation, not a p-value claim).
BASELINE_K = 2.0

# Below this many pairwise baseline scores, mean/std are too unstable to state
# a personal-variance threshold, so no verdict is issued (absence, not green).
# 10 pairs = 5 usable history outputs.
MIN_BASELINE_PAIRS = 10

# Domain clamp on the derived threshold. Jaccard lives in [0, 1]:
#   * floor — a very *diverse* history (baseline mean+2std near 0) must not flag
#     ordinary vocabulary overlap as repetition; below ~0.35 shingle-Jaccard two
#     prose texts share scattered phrases, not substance (empirically, unrelated
#     same-domain prose sits < 0.2; see tests for fixture evidence).
#   * ceiling — a very *repetitive* history must not launder near-duplicates:
#     0.90+ shingle overlap is duplicate territory regardless of baseline.
THRESHOLD_FLOOR = 0.35
THRESHOLD_CEILING = 0.90

# Texts shorter than this many normalized tokens make Jaccard degenerate
# (a 6-word output shares 100% of its shingles with any superset). Such
# candidates get no verdict; such history entries are excluded.
MIN_TOKENS = 20

# Excerpt length for the named earlier output in a finding.
EXCERPT_CHARS = 200


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION + SIMILARITY (pure functions)
# ══════════════════════════════════════════════════════════════════════════════


def normalize_tokens(text):
    """Lowercase word tokens, punctuation stripped.

    Deterministic and stdlib-only: split on non-alphanumeric so "HRV," == "hrv"
    and smart quotes / markdown don't manufacture differences.
    """
    if not isinstance(text, str):
        return []
    tokens = []
    current = []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def shingle_set(tokens, n=SHINGLE_N):
    """Set of word n-gram tuples. Empty set when the text is shorter than n."""
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def similarity(text_a, text_b):
    """Pairwise similarity of two texts.

    Returns {"shingle_jaccard", "token_jaccard"}. `shingle_jaccard` (word
    3-grams) is the flagging metric — it measures reused phrasing.
    `token_jaccard` is reported for context only: same-domain outputs share
    vocabulary by nature, so it runs high on honest non-repeats.
    """
    ta, tb = normalize_tokens(text_a), normalize_tokens(text_b)
    return {
        "shingle_jaccard": round(_jaccard(shingle_set(ta), shingle_set(tb)), 4),
        "token_jaccard": round(_jaccard(set(ta), set(tb)), 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# THRESHOLD DERIVATION (ADR-105: from the measured distribution)
# ══════════════════════════════════════════════════════════════════════════════


def derive_threshold(history_shingle_sets):
    """Personal-variance threshold from the coach's own history.

    Computes shingle-Jaccard over every pair of trailing outputs (n outputs →
    n·(n−1)/2 pairs; at the 30-output window that is ≤ 435 brute-force pairs —
    ADR-150's arithmetic, no index needed) and returns
    `clamp(mean + BASELINE_K·std, THRESHOLD_FLOOR, THRESHOLD_CEILING)` with the
    full derivation stated.

    Returns None when fewer than MIN_BASELINE_PAIRS pairwise scores exist —
    the caller must then issue no verdict.
    """
    scores = [_jaccard(a, b) for a, b in combinations(history_shingle_sets, 2)]
    n_pairs = len(scores)
    if n_pairs < MIN_BASELINE_PAIRS:
        return None
    mean = sum(scores) / n_pairs
    var = sum((s - mean) ** 2 for s in scores) / n_pairs
    std = var**0.5
    raw = mean + BASELINE_K * std
    threshold = min(max(raw, THRESHOLD_FLOOR), THRESHOLD_CEILING)
    return {
        "threshold": round(threshold, 4),
        "baseline_mean": round(mean, 4),
        "baseline_std": round(std, 4),
        "baseline_k": BASELINE_K,
        "n_pairs": n_pairs,
        "derivation": (
            f"mean+{BASELINE_K}*std of shingle-Jaccard over {n_pairs} pairs of this "
            f"coach's trailing outputs = {raw:.4f}, clamped to "
            f"[{THRESHOLD_FLOOR}, {THRESHOLD_CEILING}]"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# DETECTOR
# ══════════════════════════════════════════════════════════════════════════════


def detect(candidate_text, history):
    """Score a candidate output against the coach's own trailing history.

    Args:
      candidate_text: the newly generated output (str).
      history: list of {"id": <sk or other stable identifier>, "content": str},
        most recent first. Callers pass the coach's own OUTPUT# records;
        entries beyond TRAILING_WINDOW or shorter than MIN_TOKENS are ignored.

    Returns an advisory report dict:
      status   — "ok" | "insufficient_text" | "insufficient_history" | "error"
      verdict  — "repeat" | "novel" | None (None = no claim made, never green)
      score    — max shingle-Jaccard vs history (present whenever computable)
      most_similar — {"id", "excerpt", "shingle_jaccard", "token_jaccard"}
                 naming the earlier output the candidate most resembles
      threshold — the stated derivation (see derive_threshold)
      n_history — usable history outputs compared against
      advisory — always True (ADR-108 posture: report, never block)

    Never raises: any internal failure returns status="error", verdict=None.
    """
    base = {"advisory": True, "detector_version": "1.0.0"}
    try:
        cand_tokens = normalize_tokens(candidate_text)
        if len(cand_tokens) < MIN_TOKENS:
            return {
                **base,
                "status": "insufficient_text",
                "verdict": None,
                "reason": f"candidate has {len(cand_tokens)} tokens; minimum {MIN_TOKENS}",
            }
        cand_shingles = shingle_set(cand_tokens)

        usable = []
        for entry in history or []:
            content = (entry or {}).get("content") or ""
            tokens = normalize_tokens(content)
            if len(tokens) < MIN_TOKENS:
                continue
            usable.append(
                {
                    "id": str((entry or {}).get("id") or "unknown"),
                    "content": content,
                    "tokens": tokens,
                    "shingles": shingle_set(tokens),
                }
            )
            if len(usable) >= TRAILING_WINDOW:
                break

        threshold_info = derive_threshold([u["shingles"] for u in usable])
        if threshold_info is None:
            return {
                **base,
                "status": "insufficient_history",
                "verdict": None,
                "n_history": len(usable),
                "reason": (
                    f"{len(usable)} usable trailing outputs yield fewer than "
                    f"{MIN_BASELINE_PAIRS} baseline pairs; no personal-variance "
                    "threshold can be stated (ADR-105), so no verdict is issued"
                ),
            }

        best = None
        best_score = -1.0
        for u in usable:
            s = _jaccard(cand_shingles, u["shingles"])
            if s > best_score:
                best_score = s
                best = u

        score = round(best_score, 4)
        verdict = "repeat" if score >= threshold_info["threshold"] else "novel"
        report = {
            **base,
            "status": "ok",
            "verdict": verdict,
            "score": score,
            "threshold": threshold_info,
            "n_history": len(usable),
            "most_similar": {
                "id": best["id"],
                "excerpt": best["content"][:EXCERPT_CHARS],
                "shingle_jaccard": score,
                "token_jaccard": similarity(candidate_text, best["content"])["token_jaccard"],
            },
        }
        if verdict == "repeat":
            report["finding"] = (
                f"output repeats {best['id']} (shingle-Jaccard {score} ≥ derived "
                f"threshold {threshold_info['threshold']}; baseline "
                f"{threshold_info['baseline_mean']}±{threshold_info['baseline_std']} "
                f"over n={threshold_info['n_pairs']} pairs)"
            )
        return report
    except Exception as e:  # pragma: no cover — belt-and-braces; individual paths tested
        return {**base, "status": "error", "verdict": None, "error": str(e)}
