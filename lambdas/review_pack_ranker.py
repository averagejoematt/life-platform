"""review_pack_ranker.py — the Hybrid ranker + tagger for the weekly AI review-pack
(#1688, foundation story S1 of epic #1687 "The Coach Correction Loop").

The weekly review-pack email (#1594 / `lambdas/emails/ai_review_pack_lambda.py`)
used to list the week's AI generations flat. This module uplifts it: each generation
gets a **stable number**, a **wrongness rank**, an extracted **checkable claim**, and
an **error-class tag** — so Matthew can correct by number and the correction compounds
(the rest of epic #1687: #1689 the corrections ledger, #1690 the feedback channels).

Design (per the issue's MUST-REUSE constraints — one source of truth, no re-invention):
- **Numbering** (`numbered_entries`) is a PURE, deterministic helper split out here so
  #1690's feedback channels can import it to resolve a "#N" correction back to its
  archived generation. Same week → same numbers, independent of any prior in-place
  sorting the caller did (it re-derives the canonical order itself).
- **Error-class tags** come from `coach_corrections.ERROR_CLASSES` (#1689) — imported,
  never re-listed here.
- **baseline-mismatch** reuses `grounded_generation.baseline_freshness_findings` (#1691,
  the deterministic stale-baseline/stale-phase gate) — this module does NOT write a
  second baseline detector.
- **HYBRID ranking** (Matthew-locked, #1687): deterministic heuristics ALWAYS (the
  zero-cost floor #1594 preserves) — baseline-mismatch, ungrounded-behavioral-verb,
  claim-density, hedge-absence — PLUS a cheap Haiku "critic" pass layered on ONLY when
  the budget tier ≤ 1. The critic is a per-feature policy the epic locked specifically
  for this cheap pass: it is gated on `tier <= 1` directly, NOT folded into
  `budget_guard.allow()`'s generic internal-AI band. At tier ≥ 2 the deterministic
  ranking stands unchanged (and Bedrock is never called).

This module is bundled at lambdas/ root (#781 — one bundle, no layer), so it imports
cleanly from `ai_review_pack_lambda` today and from #1690's channels later.

v1.0.0 — 2026-07-22 (#1688)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

# Error-class vocabulary — the ONE source of truth (#1689). Imported, never re-listed.
from coach_corrections import ERROR_CLASSES

# The deterministic stale-baseline/stale-phase gate (#1691). Bundled (#781); import
# fail-soft so a missing module degrades the baseline heuristic off rather than
# killing the pack (mirrors ai_review_pack_lambda's own fail-soft import).
try:
    import grounded_generation as _gg
except Exception:  # pragma: no cover — bundle-dependent
    _gg = None

logger = logging.getLogger()

# Canonical surface order — the numbering anchor. Kept identical to
# ai_review_pack_lambda.SURFACE_ORDER (a test pins them equal so they can't drift).
# #1690 must number with THIS order (or the pack's SURFACE_ORDER, which equals it) so
# the same week always numbers the same way.
DEFAULT_SURFACE_ORDER = ("chronicle", "state_of_matthew", "coach_brief", "board_ask", "field_notes", "memoir")

# ── wrongness weights (deterministic floor) ─────────────────────────────────────
_W_BASELINE = 3.0  # a stale-baseline / stale-phase / pre-genesis finding
_W_BEHAVIORAL = 2.5  # an ungrounded behavioral-verb claim
_W_CROSS_COACH = 2.0  # a cross-coach numeric inconsistency
_W_HEDGE_ABSENCE = 1.0  # checkable claims made with zero hedging
_W_CLAIM_UNIT = 0.25  # per checkable numeric claim (capped)
_CLAIM_CAP = 8  # claim-density contribution caps at this many claims
_W_CRITIC_MAX = 2.0  # the Haiku critic can add at most this much

# ── ungrounded-behavioral-verb detection ────────────────────────────────────────
# A behavioral verb asserts Matthew *performed an action* ("you maintained your eating
# window today"). This is DISTINCT from the grounding number gate (fabricated numbers):
# here the claim may carry no number at all — it asserts a behavior with no supporting
# log. We flag a sentence that (a) addresses Matthew ("you"/"your"), (b) contains a
# completed-action behavioral verb, (c) is NOT modal/conditional/future, and (d) carries
# no supporting number in that same sentence (a number is the log-shaped evidence that
# would move it out of "ungrounded").
_BEHAVIORAL_VERB_RE = re.compile(
    r"\b(maintained|kept|stuck\s+(?:to|with)|hit|completed|logged|avoided|resisted|"
    r"skipped|nailed|crushed|stayed|held|sustained|followed|finished|closed|showed\s+up)\b",
    re.IGNORECASE,
)
_SECOND_PERSON_RE = re.compile(r"\byou(?:r|'ve|'ll|'d)?\b", re.IGNORECASE)
# Modal / conditional / future markers that turn a behavioral verb into advice, not a
# claim of a completed action ("you could maintain…", "if you keep…", "try to hit…").
_MODAL_RE = re.compile(
    r"\b(could|should|would|can|will|might|may|must|need\s+to|try(?:ing)?\s+to|let'?s|if\s+you|keep\s+(?:up|on)|to)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# ── hedge detection ─────────────────────────────────────────────────────────────
_HEDGE_RE = re.compile(
    r"\b(might|may|maybe|could|would|perhaps|approximately|roughly|around|about|"
    r"nearly|likely|probably|appears?|seems?|suggests?|estimate[ds]?|tends?\s+to|"
    r"on\s+average|or\s+so|somewhat|possibly|uncertain)\b|~",
    re.IGNORECASE,
)

# ── cross-coach numeric consistency ─────────────────────────────────────────────
# The validated 2026-07-22 case: two coaches citing different protein targets in the
# same week (170g vs 190g). We extract a per-coach protein-gram target and flag a
# disagreement across coaches. Kept to protein deliberately (the observed class); the
# _TARGET_METRICS registry makes adding another cross-coach metric a one-line change.
_PROTEIN_TARGET_RE = re.compile(
    r"(?:(\d{2,3})\s*g(?:rams?)?\s+(?:of\s+)?protein)|(?:protein[^.\n]{0,24}?(\d{2,3})\s*g(?:rams?)?)",
    re.IGNORECASE,
)
_TARGET_METRICS = ("protein",)


# ════════════════════════════════════════════════════════════════════════════════
# Numbering (pure, deterministic) — #1690 imports this.
# ════════════════════════════════════════════════════════════════════════════════
def _order_key(entry: dict, surface_order) -> tuple:
    """The canonical sort key for one archived entry.

    Order: (surface rank in `surface_order`, date, archived_at, _key). Unknown
    surfaces sort AFTER all known ones (rank = len) then alphabetically by surface,
    so a new surface never renumbers the known ones. `_key` is the final, always-unique
    tie-break (the archive key embeds a uuid8), guaranteeing a total order.
    """
    surface = entry.get("surface", "unknown")
    try:
        rank = surface_order.index(surface)
    except (ValueError, AttributeError):
        rank = len(surface_order)
    return (rank, surface, entry.get("date", ""), entry.get("archived_at", ""), entry.get("_key", ""))


def numbered_entries(by_surface: dict, *, surface_order=DEFAULT_SURFACE_ORDER) -> list:
    """PURE: assign each archived generation a STABLE 1-indexed number.

    Args:
        by_surface: {surface: [entry_dict, ...]} as produced by
            `ai_review_pack_lambda.gather_week` (each entry carries `_key`,
            `surface`, `date`, `archived_at`).
        surface_order: the surface ranking (defaults to the canonical
            `DEFAULT_SURFACE_ORDER`). Pass the pack's SURFACE_ORDER — it is equal.

    Returns:
        [(n, entry), ...] with n starting at 1, in the deterministic canonical order
        (see `_order_key`). The SAME week always yields the SAME (n → entry) mapping,
        independent of any in-place ordering the caller applied — this is the contract
        #1690 relies on to resolve a "#N" correction back to its archived generation.
    """
    flat = [e for entries in by_surface.values() for e in entries]
    flat.sort(key=lambda e: _order_key(e, surface_order))
    return [(i, e) for i, e in enumerate(flat, start=1)]


# ════════════════════════════════════════════════════════════════════════════════
# Deterministic heuristics (pure) — the always-on zero-cost floor.
# ════════════════════════════════════════════════════════════════════════════════
def _sentences(text: str) -> list:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]


def baseline_mismatch_findings(entry: dict, *, baseline_lbs=None, start_date_iso=None) -> list:
    """The baseline-mismatch heuristic — reuses #1691's `baseline_freshness_findings`
    over the entry's archived TEXT (not generation-time meta). Non-coach_brief entries,
    a missing bundle module, or a missing generation date → []. Fail-soft."""
    if _gg is None or entry.get("surface") != "coach_brief":
        return []
    meta = entry.get("meta") or {}
    gen_date = meta.get("generation_date") or entry.get("date")
    if not gen_date or not start_date_iso:
        return []
    try:
        return _gg.baseline_freshness_findings(
            entry.get("text") or "",
            generation_date_iso=gen_date,
            baseline_lbs=baseline_lbs,
            start_date_iso=start_date_iso,
        )
    except Exception as e:  # pragma: no cover — advisory; never break the pack
        logger.warning(f"[review_pack_ranker] baseline re-check failed for {entry.get('_key')}: {e}")
        return []


def behavioral_findings(text: str) -> list:
    """Ungrounded-behavioral-verb findings: sentences asserting a completed action by
    Matthew ("you maintained your eating window today") with no supporting number and
    no modal/conditional framing. Returns [{type, detail}]."""
    out = []
    for sent in _sentences(text):
        if not _SECOND_PERSON_RE.search(sent):
            continue
        vm = _BEHAVIORAL_VERB_RE.search(sent)
        if not vm:
            continue
        if _MODAL_RE.search(sent):  # advice / conditional / future — not a completed-action claim
            continue
        if _NUMBER_RE.search(sent):  # a number is log-shaped evidence — out of scope for THIS heuristic
            continue
        verb = vm.group(0).lower()
        snippet = sent if len(sent) <= 140 else sent[:137].rstrip() + "…"
        out.append({"type": "ungrounded_behavioral", "verb": verb, "detail": f'behavioral claim with no supporting log: "{snippet}"'})
    return out


def claim_stats(text: str) -> dict:
    """Checkable-claim density: numeric-claim count and per-100-word density. Uses
    grounded_generation.numbers_in_text when available (its thousands-aware tokenizer),
    else a bare digit-run count."""
    text = text or ""
    if _gg is not None:
        try:
            count = len(_gg.numbers_in_text(text))
        except Exception:  # pragma: no cover
            count = len(re.findall(r"\d+(?:\.\d+)?", text))
    else:
        count = len(re.findall(r"\d+(?:\.\d+)?", text))
    words = max(len(text.split()), 1)
    return {"count": count, "density_per_100w": round(count / words * 100, 2)}


def hedge_stats(text: str) -> dict:
    """Hedge presence: how many hedge markers the text carries. Zero hedges on a text
    that makes checkable claims raises wrongness (over-confident assertion)."""
    matches = _HEDGE_RE.findall(text or "")
    count = len(matches)
    return {"count": count, "hedged": count > 0}


def genesis_mismatch_finding(entry: dict, *, start_date_iso=None) -> Optional[dict]:
    """generation-date-vs-current-genesis flag: a coach_brief whose generation date
    predates the current EXPERIMENT_START_DATE was authored in a prior cycle window and
    frames a stale cycle. Distinct from the stale_phase text check — this is about WHEN
    the brief was generated, not what it says. Returns a finding or None."""
    if entry.get("surface") != "coach_brief" or not start_date_iso:
        return None
    meta = entry.get("meta") or {}
    gen_date = meta.get("generation_date") or entry.get("date")
    if not gen_date:
        return None
    try:
        if str(gen_date) < str(start_date_iso):
            return {
                "type": "genesis_mismatch",
                "detail": f"generated {gen_date}, BEFORE the current genesis {start_date_iso} — a prior-cycle brief",
            }
    except Exception:  # pragma: no cover
        return None
    return None


def _protein_targets(text: str) -> set:
    out = set()
    for m in _PROTEIN_TARGET_RE.finditer(text or ""):
        val = m.group(1) or m.group(2)
        if val:
            out.add(int(val))
    return out


def cross_coach_findings(by_surface: dict) -> dict:
    """Pack-level: detect two coaches citing different targets for the same metric in
    the same week (the validated 170g-vs-190g protein case). Returns
    {_key: [{type, detail}]} for every coach_brief entry that participates in a
    disagreement. Only coach_brief entries (variant = coach_id) are considered."""
    out: dict = {}
    briefs = [e for e in by_surface.get("coach_brief", []) if e.get("_key")]
    for metric in _TARGET_METRICS:
        # coach_id -> {value -> [keys]}
        by_coach: dict = {}
        for e in briefs:
            coach = e.get("variant") or "unknown"
            vals = _protein_targets(e.get("text") or "") if metric == "protein" else set()
            for v in vals:
                by_coach.setdefault(coach, {}).setdefault(v, []).append(e["_key"])
        # Distinct values asserted across DIFFERENT coaches → inconsistency.
        coach_to_values = {c: set(vd.keys()) for c, vd in by_coach.items()}
        all_values = sorted({v for vs in coach_to_values.values() for v in vs})
        if len({c for c, vs in coach_to_values.items() if vs}) < 2 or len(all_values) < 2:
            continue
        for coach, vd in by_coach.items():
            for v, keys in vd.items():
                others = sorted(ov for oc, ovs in coach_to_values.items() if oc != coach for ov in ovs if ov != v)
                if not others:
                    continue
                detail = f"cites {metric} target {v}g; other coaches this week cite {', '.join(f'{o}g' for o in others)}"
                for k in keys:
                    out.setdefault(k, []).append({"type": "cross_coach_inconsistency", "metric": metric, "detail": detail})
    return out


# ════════════════════════════════════════════════════════════════════════════════
# Per-entry analysis + scoring.
# ════════════════════════════════════════════════════════════════════════════════
def _primary_class(analysis: dict) -> str:
    """Map the heuristic findings to ONE error-class tag from ERROR_CLASSES, most-severe
    first. Human-only classes (framing / defense-held) are never auto-assigned."""
    if analysis["baseline"] or analysis["genesis"]:
        cls = "stale-baseline"
    elif analysis["behavioral"]:
        cls = "ungrounded-behavioral"
    elif analysis["cross_coach"]:
        cls = "cross-coach-inconsistency"
    elif analysis["claim"]["count"] and not analysis["hedge"]["hedged"]:
        cls = "checkable-metric"
    elif analysis["hedge"]["hedged"] and analysis["claim"]["count"]:
        cls = "hedged-safe"
    else:
        cls = "other"
    # Invariant: only ever emit a tag the ledger vocabulary knows (#1689).
    return cls if cls in ERROR_CLASSES else "other"


def _deterministic_score(analysis: dict) -> float:
    score = 0.0
    score += _W_BASELINE * len(analysis["baseline"])
    score += _W_BASELINE * len(analysis["genesis"])
    score += _W_BEHAVIORAL * len(analysis["behavioral"])
    score += _W_CROSS_COACH * len(analysis["cross_coach"])
    if analysis["claim"]["count"] and not analysis["hedge"]["hedged"]:
        score += _W_HEDGE_ABSENCE
    score += _W_CLAIM_UNIT * min(analysis["claim"]["count"], _CLAIM_CAP)
    return round(score, 4)


def extract_checkable_claim(text: str, analysis: dict) -> str:
    """The single most checkable sentence — the one tied to the highest-severity finding
    (baseline > behavioral > cross-coach), else the first sentence carrying a number,
    else the first sentence, else "". Trimmed to a readable length."""
    for key in ("baseline", "genesis", "behavioral", "cross_coach"):
        for f in analysis.get(key, []):
            detail = f.get("detail", "")
            # behavioral/baseline details already quote the sentence; prefer that.
            if detail:
                claim = detail
                break
        else:
            continue
        break
    else:
        claim = ""
    if not claim:
        for sent in _sentences(text):
            if _NUMBER_RE.search(sent):
                claim = sent
                break
    if not claim:
        sents = _sentences(text)
        claim = sents[0] if sents else ""
    claim = claim.strip()
    return claim if len(claim) <= 200 else claim[:197].rstrip() + "…"


def analyze_entry(entry: dict, *, baseline_lbs=None, start_date_iso=None, cross_coach: Optional[list] = None) -> dict:
    """Full deterministic analysis of one archived generation. PURE. Returns an analysis
    dict: score (deterministic floor), the per-heuristic findings, the derived
    error-class tag, and the extracted checkable claim."""
    text = entry.get("text") or ""
    analysis = {
        "baseline": baseline_mismatch_findings(entry, baseline_lbs=baseline_lbs, start_date_iso=start_date_iso),
        "genesis": [g] if (g := genesis_mismatch_finding(entry, start_date_iso=start_date_iso)) else [],
        "behavioral": behavioral_findings(text),
        "cross_coach": list(cross_coach or []),
        "claim": claim_stats(text),
        "hedge": hedge_stats(text),
        "critic": None,  # filled by run_critic when the tier gate opens
    }
    analysis["error_class"] = _primary_class(analysis)
    analysis["checkable_claim"] = extract_checkable_claim(text, analysis)
    analysis["deterministic_score"] = _deterministic_score(analysis)
    analysis["score"] = analysis["deterministic_score"]
    return analysis


# ════════════════════════════════════════════════════════════════════════════════
# Haiku critic (budget-gated, tier ≤ 1) — the layered-on smarter ranking.
# ════════════════════════════════════════════════════════════════════════════════
_CRITIC_SYSTEM = (
    "You are a terse QA critic auditing an AI health-coach's weekly generations for a "
    "single user (Matthew). For each numbered item you are given an extracted checkable "
    "claim. Judge ONLY how likely that claim is to be factually WRONG or misleading — "
    "not its tone. Return STRICT JSON: an array of objects "
    '{"n": <int>, "wrongness": <float 0..1>, "why": "<=10 words"}. '
    "0 = almost certainly correct, 1 = almost certainly wrong. Include every item. "
    "Do not invent facts; judge only the claim as written."
)


def _build_critic_body(items: list) -> dict:
    """Compact Haiku request. `items` = [(n, checkable_claim), ...]. System block is a
    cached content block (COST-OPT-2 / ADR-049 prompt caching)."""
    lines = [f"#{n}: {claim}" for n, claim in items]
    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 700,
        "system": [{"type": "text", "text": _CRITIC_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Items:\n" + "\n".join(lines) + "\n\nReturn the JSON array."}],
    }


def _parse_critic(resp: dict) -> dict:
    """Parse the critic's JSON array → {n: wrongness float in 0..1}. Defensive: tolerate
    fences/prose, drop malformed rows. Returns {} on any parse failure."""
    text = "".join(p.get("text", "") for p in (resp or {}).get("content", []) if p.get("type") == "text").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        arr = json.loads(text[start : end + 1])  # noqa: E203
    except (ValueError, TypeError):
        return {}
    out = {}
    for row in arr if isinstance(arr, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            n = int(row["n"])
            w = float(row["wrongness"])
        except (KeyError, TypeError, ValueError):
            continue
        out[n] = max(0.0, min(1.0, w))
    return out


def run_critic(numbered_analyses: list, invoke_fn: Callable) -> dict:
    """Run the Haiku critic over [(n, analysis), ...]. Returns {n: wrongness float}.
    Fail-soft: any Bedrock/parse error → {} (the deterministic ranking stands). The
    CALLER decides whether to run this at all (the tier gate lives in `rank_pack`)."""
    items = [(n, a.get("checkable_claim") or "") for n, a in numbered_analyses if (a.get("checkable_claim") or "").strip()]
    if not items:
        return {}
    try:
        resp = invoke_fn(_build_critic_body(items), model_name="claude-haiku-4-5-20251001")
    except Exception as e:  # pragma: no cover — advisory; deterministic floor stands
        logger.warning(f"[review_pack_ranker] Haiku critic failed (non-fatal): {e}")
        return {}
    return _parse_critic(resp)


# ════════════════════════════════════════════════════════════════════════════════
# The public entrypoint — rank the whole pack (HYBRID).
# ════════════════════════════════════════════════════════════════════════════════
_CRITIC_TIER_CEILING = 1  # the epic-locked per-feature policy: critic runs only at tier ≤ 1


def _default_tier_reader() -> int:
    """Read the current budget tier. Fail-open to 0 (never let a monitoring blip change
    ranking behavior). Isolated so tests can inject a fixed tier."""
    try:
        import budget_guard

        return budget_guard.current_tier()
    except Exception:  # pragma: no cover — fail-open
        return 0


def rank_pack(
    by_surface: dict,
    *,
    baseline_lbs=None,
    start_date_iso=None,
    surface_order=DEFAULT_SURFACE_ORDER,
    tier_reader: Optional[Callable[[], int]] = None,
    invoke_fn: Optional[Callable] = None,
) -> dict:
    """HYBRID rank the week's pack.

    Deterministic heuristics ALWAYS run. The Haiku critic is layered on ONLY when the
    budget tier ≤ 1 (`_CRITIC_TIER_CEILING`) — read from `tier_reader` (defaults to
    budget_guard.current_tier). At tier ≥ 2 the critic is skipped cleanly and Bedrock is
    never called (preserves #1594's zero-cost floor).

    Returns:
        {
          "numbered": [(n, entry), ...],           # stable numbering (numbered_entries)
          "analyses": {n: analysis, ...},          # per-item analysis keyed by number
          "ranked":   [(n, entry, analysis), ...], # most-likely-wrong → least
          "critic_ran": bool,
          "tier": int,
        }
    On a quiet week (no generations) everything is empty and the critic is NEVER called.
    """
    numbered = numbered_entries(by_surface, surface_order=surface_order)
    cross = cross_coach_findings(by_surface)

    analyses: dict = {}
    for n, entry in numbered:
        analyses[n] = analyze_entry(
            entry,
            baseline_lbs=baseline_lbs,
            start_date_iso=start_date_iso,
            cross_coach=cross.get(entry.get("_key", "")),
        )

    tier = (tier_reader or _default_tier_reader)()
    critic_ran = False
    if numbered and tier <= _CRITIC_TIER_CEILING:
        invoke = invoke_fn
        if invoke is None:
            try:
                from bedrock_client import invoke as _bedrock_invoke

                invoke = _bedrock_invoke
            except Exception:  # pragma: no cover — no client → deterministic only
                invoke = None
        if invoke is not None:
            wrongness = run_critic([(n, analyses[n]) for n, _ in numbered], invoke)
            if wrongness:
                critic_ran = True
                for n, w in wrongness.items():
                    if n in analyses:
                        analyses[n]["critic"] = round(w, 4)
                        analyses[n]["score"] = round(analyses[n]["deterministic_score"] + _W_CRITIC_MAX * w, 4)

    ranked = sorted(
        ((n, entry, analyses[n]) for n, entry in numbered),
        key=lambda t: (-t[2]["score"], t[0]),
    )
    return {"numbered": numbered, "analyses": analyses, "ranked": ranked, "critic_ran": critic_ran, "tier": tier}
