"""reading_recommender.py — the rules-based, transparent recommender v1 (spec §4).

Pure logic, no I/O — the MCP tool (`tools_reading.get_reading_recommendation`)
gathers the state and calls `rank()`. Anti-black-box by construction: every
candidate's `fit` decomposes into named component scores, and the **reason
string** is assembled from its top contributors. If `fit` can't be explained, the
book isn't surfaced (hard rule). Confidence is `f(n_finished, n_abandoned)`; below
the n-gate the engine is **propose-and-dispose only** (he approves every pick).

Objective (spec §4):
    fit =  w_cap*capacity_fit + w_diff*difficulty_fit + w_breadth*breadth_gain
         + w_mom*momentum_fit + w_res*journal_resonance + w_phase*phase_fit
         - p_whip*whiplash_penalty - p_rep*repeat_pattern_penalty
         - p_goal*goal_domain_penalty

Weights shift by curriculum phase (calibration §4/§5): Phase 1 (on-ramp) lets
capacity + completion-probability dominate and keeps difficulty/breadth low; later
phases raise breadth + depth. The weight sets are versioned here (`WEIGHTS`).

The recommender NEVER invents data — it scores only the candidate facts + state
it's handed, and labels confidence honestly while `n` is small (no hype).
"""

from __future__ import annotations

WEIGHTS_VERSION = "v1.0.0"

# Per-phase weight sets (calibration §4). Phase 1 = guaranteed-win on-ramp:
# capacity + completion-probability dominate; growth agenda is muted. Breadth and
# depth ramp as the habit proves out.
WEIGHTS: dict[int, dict[str, float]] = {
    1: {"cap": 0.40, "diff": 0.05, "breadth": 0.05, "mom": 0.30, "res": 0.10, "phase": 0.10, "whip": 0.20, "rep": 0.15, "goal": 0.30},
    2: {"cap": 0.25, "diff": 0.10, "breadth": 0.20, "mom": 0.20, "res": 0.15, "phase": 0.10, "whip": 0.20, "rep": 0.15, "goal": 0.30},
    3: {"cap": 0.20, "diff": 0.25, "breadth": 0.20, "mom": 0.10, "res": 0.15, "phase": 0.10, "whip": 0.15, "rep": 0.15, "goal": 0.25},
    4: {"cap": 0.15, "diff": 0.30, "breadth": 0.25, "mom": 0.10, "res": 0.15, "phase": 0.05, "whip": 0.10, "rep": 0.10, "goal": 0.20},
}

# Domains that are "goal-domain" — de-prioritized by default (the anti-Goggins
# rule, calibration §11): he's saturated in optimization; reading adds texture.
GOAL_DOMAINS = frozenset({"self-help", "business", "psychology", "productivity", "fitness", "health", "nutrition", "discipline"})

_WEEK_CAPACITY = {"GREEN": 1.0, "YELLOW": 0.6, "RED": 0.25}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _composite(book: dict) -> float:
    """Difficulty composite on a 0-1 scale (subscores are 1-5; composite ~1-5)."""
    diff = (book.get("difficulty") or {}).get("composite")
    if diff is None:
        # fall back to a length-based proxy if un-enriched
        pages = book.get("pageCount")
        try:
            return _clamp01((int(pages) - 150) / 600) if pages else 0.5
        except (TypeError, ValueError):
            return 0.5
    return _clamp01((float(diff) - 1.0) / 4.0)


# ── component scores (each returns 0..1) ──────────────────────────────────────
def capacity_fit(book: dict, state: dict) -> float:
    """How well the book fits this week's capacity. A depleted week wants short +
    easy; a GREEN week can take the longer/harder book. (calibration §3)."""
    cap = _WEEK_CAPACITY.get(state.get("week_color", "YELLOW"), 0.6)
    demand = _composite(book)
    # fit is high when demand <= capacity; falls off as demand exceeds capacity.
    return _clamp01(1.0 - max(0.0, demand - cap))


def difficulty_fit(book: dict, state: dict) -> float:
    """In-zone picks score highest; a programmed stretch is rewarded only on a
    GREEN week, and subtracted on RED (the ratchet, calibration §3)."""
    demand = _composite(book)
    ratchet = _clamp01(float(state.get("ratchet_position", 0.5)))
    gap = demand - ratchet  # >0 = a stretch, <0 = below the line
    color = state.get("week_color", "YELLOW")
    if gap <= 0:
        return _clamp01(1.0 + gap)  # in-zone/just-below scores near 1
    # a stretch: rewarded on GREEN, penalized on RED
    bonus = {"GREEN": 1.0, "YELLOW": 0.4, "RED": -0.5}.get(color, 0.4)
    return _clamp01(1.0 - gap + bonus * gap)


def breadth_gain(book: dict, state: dict) -> float:
    """Higher when the book's domains are under-represented in the wheel
    (roundedness, calibration §1)."""
    wheel = state.get("wheel_distribution") or {}
    total = sum(wheel.values()) or 1
    tags = book.get("domainTags") or []
    if not tags:
        return 0.3
    # average rarity across the book's tags
    rarities = [1.0 - (wheel.get(t, 0) / total) for t in tags]
    return _clamp01(sum(rarities) / len(rarities))


def momentum_fit(book: dict, state: dict) -> float:
    """Rewards continuity with what's working — a genre on a current streak or
    matching recent likes (calibration §6)."""
    tags = set(book.get("domainTags") or [])
    score = 0.5
    streak = state.get("recent_streak_genre")
    if streak and streak in tags:
        score += 0.3
    liked = set(state.get("recent_liked_domains") or [])
    if tags & liked:
        score += 0.2
    return _clamp01(score)


def phase_fit(book: dict, state: dict) -> float:
    """Phase-appropriateness. Phase 1 favors short + propulsive (high completion
    probability); later phases relax that (calibration §4)."""
    phase = int(state.get("curriculum_phase", 1))
    pages = book.get("pageCount")
    if phase == 1:
        try:
            p = int(pages)
            return _clamp01(1.0 - max(0.0, (p - 300) / 500))  # short books win the on-ramp
        except (TypeError, ValueError):
            return 0.6
    return 0.6  # neutral once past the on-ramp (breadth/depth carry later phases)


# ── penalties (each returns 0..1; subtracted) ─────────────────────────────────
def whiplash_penalty(book: dict, state: dict) -> float:
    """Penalize a hard genre lurch off the last finished book (calibration §1:
    alternate, don't whiplash)."""
    last = state.get("last_finished") or {}
    last_tags = set(last.get("domainTags") or [])
    tags = set(book.get("domainTags") or [])
    if not last_tags or not tags:
        return 0.0
    # fiction <-> dense-nonfiction is the classic whiplash; penalize zero overlap
    overlap = tags & last_tags
    return 0.0 if overlap else 0.5


def repeat_pattern_penalty(book: dict, state: dict) -> float:
    """Penalize repeating the exact pattern of the last two books (calibration §6)."""
    last2 = state.get("last_2_books") or []
    tags = set(book.get("domainTags") or [])
    if len(last2) < 2 or not tags:
        return 0.0
    shared = all(tags & set((b.get("domainTags") or [])) for b in last2[:2])
    return 0.4 if shared else 0.0


def goal_domain_penalty(book: dict, state: dict) -> float:
    """Anti-Goggins (calibration §11): de-prioritize goal-domain books by default."""
    tags = set(book.get("domainTags") or [])
    return 0.8 if tags & GOAL_DOMAINS else 0.0


_COMPONENTS = [
    ("cap", "capacity", capacity_fit),
    ("diff", "difficulty", difficulty_fit),
    ("breadth", "breadth", breadth_gain),
    ("mom", "momentum", momentum_fit),
    ("phase", "phase", phase_fit),
]
_PENALTIES = [
    ("whip", "whiplash", whiplash_penalty),
    ("rep", "repeat", repeat_pattern_penalty),
    ("goal", "goal-domain", goal_domain_penalty),
]

# Plain-language fragments for the reason string (anti-black-box, spec §4/§7).
_REASON = {
    "capacity": "it fits this week's capacity",
    "difficulty": "it's right at your current difficulty line",
    "breadth": "it widens a thin slice of your reading",
    "momentum": "it carries the momentum of what you've been enjoying",
    "resonance": "it resonates with what your journal's been circling",
    "phase": "it suits where you are in the curriculum",
}


def _confidence(n_finished: int, n_abandoned: int) -> str:
    n = int(n_finished) + int(n_abandoned)
    if n < 5:
        return "very-low"
    if n < 15:
        return "low"
    if n < 30:
        return "medium"
    return "high"


def _reason_string(components: dict, resonance: float, penalties: dict) -> str:
    """Assemble a decomposed reason from the top contributing components."""
    contrib = dict(components)
    if resonance > 0:
        contrib["resonance"] = resonance
    top = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)[:3]
    parts = [_REASON[name] for name, score in top if score > 0.45 and name in _REASON]
    if not parts:
        parts = ["it's a reasonable next step"]
    reason = "Recommended because " + ", ".join(parts[:-1] + ([("and " + parts[-1]) if len(parts) > 1 else parts[-1]])) + "."
    # name the strongest active penalty honestly (the "passing over" half)
    pen = max(penalties.items(), key=lambda kv: kv[1], default=(None, 0.0))
    if pen[1] >= 0.5:
        notes = {
            "goal-domain": " Held back a touch because it's in your saturated optimization lane.",
            "whiplash": " Noting it's a sharp turn from your last read.",
            "repeat": " Noting it repeats your recent pattern.",
        }
        reason += notes.get(pen[0], "")
    return reason


def score_one(book: dict, state: dict, weights: dict) -> dict:
    """Score a single candidate → fit + decomposed components + reason."""
    components = {label: fn(book, state) for _key, label, fn in _COMPONENTS}
    penalties = {label: fn(book, state) for _key, label, fn in _PENALTIES}
    resonance = _clamp01(float((state.get("journal_resonance") or {}).get(book.get("bookId"), 0.0)))

    fit = sum(weights[key] * components[label] for key, label, _ in _COMPONENTS)
    fit += weights["res"] * resonance
    fit -= sum(weights[key] * penalties[label] for key, label, _ in _PENALTIES)

    return {
        "bookId": book.get("bookId"),
        "title": book.get("title"),
        "fit": round(fit, 4),
        "components": {k: round(v, 3) for k, v in components.items()},
        "resonance": round(resonance, 3),
        "penalties": {k: round(v, 3) for k, v in penalties.items()},
        "reason": _reason_string(components, resonance, penalties),
    }


def rank(candidates: list, state: dict, *, top_n: int = 5) -> dict:
    """Rank candidate books for the given state. Returns the ordered picks, each
    with a decomposed reason + the run's confidence + trust-ladder mode. Honest
    empty result when there are no candidates (never a fabricated pick)."""
    phase = int(state.get("curriculum_phase", 1))
    weights = WEIGHTS.get(phase, WEIGHTS[1])
    confidence = _confidence(state.get("n_finished", 0), state.get("n_abandoned", 0))
    mode = state.get("trust_ladder_mode", "propose")
    # propose-and-dispose while n is small (calibration §2): cap surfaced picks.
    low_n = confidence in ("very-low", "low")
    effective_top = 1 if (low_n or mode == "propose") else top_n

    scored = [score_one(b, state, weights) for b in (candidates or [])]
    scored.sort(key=lambda r: r["fit"], reverse=True)
    return {
        "recommendations": scored[:effective_top],
        "confidence": confidence,
        "trust_ladder_mode": mode,
        "propose_and_dispose": low_n or mode == "propose",
        "weights_version": WEIGHTS_VERSION,
        "curriculum_phase": phase,
        "candidate_count": len(scored),
    }
