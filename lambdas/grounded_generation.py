"""grounded_generation.py — ADR-104: one grounded-generation harness for every
AI narrative surface.

The platform's rule is "the model never does the math" (ADR-062) — this module
is that rule's enforcement arm at generation time. It composes the three proven
pieces that previously lived apart:

  1. Fact injection    — authoritative_facts_block() renders canonical_facts as
                         the AUTHORITATIVE FACTS prompt block (the analyzer's
                         battle-tested wording, incl. the no-invent-trends rule).
  2. Deterministic     — grounding_findings() = hard canonical contradictions
     post-check          (grounding_guard, RHR/recovery/HRV) + the er03-style
                         allow-list number gate generalized for narratives:
                         every number in the output must appear in the input.
                         This is what kills "climbed from X to Y" fabrication —
                         the invented X isn't in anything the model was given.
  3. Regen-once        — regen_once() extracts the duplicated keep-if-strictly-
                         improved harness (ai_expert_analyzer / field_notes) so
                         every surface corrects the same way: one rewrite,
                         kept only if findings strictly decrease, never worse.

Pure functions, no AWS, no HTTP — the caller supplies the regeneration callable.
Fail modes are the caller's choice: keep-best (internal narratives) or
fail-closed (reader-facing surfaces drop/fallback, like the podcast gate).

Import paths: bundled at lambdas/ root in every function's deploy package (with a
flat copy of grounding_guard) so every consumer (ai_calls' V2 coach render)
can use it.
"""

import datetime as _dt
import json
import re

# The tight canonical-contradiction detector (SS-10). Dual path: package-style
# (bundled lambdas/), flat (layer / flattened bundle). Fail-soft to None — the
# number gate still runs; only the vitals-contradiction check is skipped.
try:
    from intelligence.grounding_guard import hard_canonical_contradictions as _hard_contradictions
except ImportError:  # pragma: no cover — environment-dependent
    try:
        from grounding_guard import hard_canonical_contradictions as _hard_contradictions
    except ImportError:
        _hard_contradictions = None

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Numbers narrative prose may always use without them appearing in the input:
# small counts ("three meals", "2 of the last 5 days"), the common prescriptive
# durations, round anchors, and years. Everything else must be earned from the
# input — a plausible-but-invented vital (58, 13.8, 172) is never benign.
_BENIGN_NUMBERS = (
    set(float(x) for x in range(0, 13)) | {15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 100.0} | set(float(y) for y in range(2020, 2031))
)


def numbers_in_text(text: str) -> set:
    """Distinct numeric values in a string (floats), thousands-separators handled."""
    out = set()
    for m in _NUM_RE.findall(_THOUSANDS_RE.sub("", text or "")):
        try:
            out.add(round(float(m), 4))
        except ValueError:
            pass
    return out


def allowed_numbers(*sources) -> set:
    """The allow-list: every number present in what the model was given.

    Accepts strings and any JSON-serializable structure (dicts/lists are
    json.dumps'd, so nested values count). Pass the prompt, the data blob,
    and the canonical facts — the union is the model's numeric vocabulary.
    """
    allowed = set()
    for src in sources:
        if src is None:
            continue
        text = src if isinstance(src, str) else json.dumps(src, default=str)
        allowed |= numbers_in_text(text)
    return allowed


def fabricated_numbers(text: str, allowed: set) -> list:
    """Numbers in the output that appear nowhere in the input (minus benign)."""
    out = []
    for x in sorted(numbers_in_text(text)):
        if x in _BENIGN_NUMBERS:
            continue
        if any(abs(x - a) < 0.01 for a in allowed):
            continue
        # An integer restatement of an input float (64 for 64.2) is grounded.
        if any(abs(x - round(a)) < 0.01 for a in allowed):
            continue
        out.append(x)
    return out


# ── weekday↔date grounding (#1220) ──────────────────────────────────────────
# A weekday paired with a calendar date is a mechanically checkable fact — the
# ADR-104 number gate never looked at it, so the cycle-6 chronicle draft called
# 2026-07-13 (a Monday) a "Sunday" (stale cycle-5 genesis, which WAS a Sunday)
# and the gate passed it. This deterministic, zero-AI check regexes weekday+date
# pairs out of the narrative and verifies each against the real calendar.
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_DAY_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_THE_NTH_RE = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)


def _safe_date(year, month, day):
    """A real date or None (guards Feb-30, day 0, non-leap Feb-29, bad types)."""
    try:
        return _dt.date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def weekday_date_findings(text: str, year: int, month_hint: int = None, proximity: int = 60) -> list:
    """Deterministic weekday↔date check. Returns [{type: "weekday_mismatch", ...}] — empty = consistent.

    Every weekday word (Monday…Sunday) is paired with the nearest calendar date
    within `proximity` characters — a full "Month Day" ("July 13th") always, and a
    bare "the Nth" ("the 14th") when `month_hint` is supplied. The pair is verified
    against `datetime`; a mismatch (e.g. "Sunday … July 13th" when 2026-07-13 was a
    Monday) is a finding. No date near a weekday ⇒ nothing to check (no finding).
    """
    text = text or ""
    if year is None:
        return []
    # (start, end, date_obj, matched_text) for every resolvable date token.
    tokens = []
    for m in _MONTH_DAY_RE.finditer(text):
        d = _safe_date(year, _MONTHS[m.group(1).lower()], m.group(2))
        if d:
            tokens.append((m.start(), m.end(), d, m.group(0)))
    if month_hint:
        for m in _THE_NTH_RE.finditer(text):
            d = _safe_date(year, month_hint, m.group(1))
            if d:
                tokens.append((m.start(), m.end(), d, m.group(0)))
    findings = []
    seen = set()
    for wm in _WEEKDAY_RE.finditer(text):
        stated = wm.group(1).capitalize()
        w_start, w_end = wm.start(), wm.end()
        best, best_dist = None, None
        for ds, de, dobj, dstr in tokens:
            if ds >= w_end:
                dist = ds - w_end
            elif de <= w_start:
                dist = w_start - de
            else:
                dist = 0
            if dist <= proximity and (best_dist is None or dist < best_dist):
                best, best_dist = (dobj, dstr, ds), dist
        if best is None:
            continue
        dobj, dstr, ds = best
        actual = dobj.strftime("%A")
        if actual.lower() != stated.lower():
            key = (w_start, ds)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "type": "weekday_mismatch",
                    "stated_weekday": stated,
                    "date": dobj.isoformat(),
                    "actual_weekday": actual,
                    "detail": (f'the narrative pairs "{stated}" with {dstr} ({dobj.isoformat()}), ' f"but that date was a {actual}"),
                }
            )
    return findings


def authoritative_facts_block(facts: dict) -> str:
    """Render canonical facts as the AUTHORITATIVE FACTS system-prompt block.

    The analyzer's proven wording (truth audit Phase 3 + the no-invent-trends
    hard rule) — one source so every surface injects facts identically.
    Returns "" when no facts are available (caller simply omits the block).
    """
    facts = facts or {}
    lines = []
    if facts.get("protein_g_avg") is not None:
        lines.append(
            f"  - Protein INTAKE averages {facts['protein_g_avg']:g} g/day "
            f"(target {int(facts.get('protein_g_target') or 190)} g, floor {int(facts.get('protein_g_floor') or 170)} g). "
            f"His actual intake is ~{facts['protein_g_avg']:g} g — never state intake as the target or floor."
        )
    if facts.get("recovery_pct") is not None:
        lines.append(f"  - Latest Whoop recovery: {facts['recovery_pct']:g}%")
    if facts.get("hrv_ms") is not None:
        lines.append(f"  - Latest HRV: {facts['hrv_ms']:g} ms (HRV is in MILLISECONDS, never bpm)")
    if facts.get("rhr_bpm") is not None:
        lines.append(f"  - Latest resting HR: {facts['rhr_bpm']:g} bpm")
    if facts.get("latest_weight") is not None:
        lines.append(f"  - Latest weight: {facts['latest_weight']:g} lb")
    if facts.get("weekly_rate_lbs") is not None:
        _rate_line = f"  - Weekly weight rate: {facts['weekly_rate_lbs']:g} lb/week (signed; negative = losing)"
        # #535: the rate carries its interval — narrative must not present it as exact.
        if facts.get("weekly_rate_ci_low") is not None and facts.get("weekly_rate_ci_high") is not None:
            _rate_line += f" [80% CI {facts['weekly_rate_ci_low']:g} to {facts['weekly_rate_ci_high']:g}]"
        # #914-B: a provisional rate (short weigh-in span) must be framed as provisional.
        if facts.get("rate_provisional"):
            _rate_line += " — PROVISIONAL (short weigh-in span; frame as an early estimate, never a settled rate)"
        lines.append(_rate_line)
    # #914-B: scale recency — the live incident was "maintained a 7.3 lb/week
    # trajectory" cited 14 days after the last weigh-in. When the caller supplies
    # weigh-in recency, render it; past ~a week of scale darkness the rate is
    # HISTORY, and present-tense rate claims ("maintaining", "is losing") are
    # fabrication. Callers without these keys render exactly as before.
    if facts.get("last_weighin_date"):
        _dsw = facts.get("days_since_weighin")
        _w_line = f"  - Last weigh-in: {facts['last_weighin_date']}"
        if _dsw is not None:
            _w_line += f" ({int(_dsw)} days ago)"
        lines.append(_w_line)
        if _dsw is not None and int(_dsw) >= 7:
            lines.append(
                "  - SCALE DARK: there has been NO weigh-in since the date above. Any weight-rate claim must be "
                "PAST-TENSE and dated (e.g. 'was losing ~X lb/week through "
                f"{facts['last_weighin_date']}; no weigh-in since') — never 'maintained', 'maintaining', or any "
                "present-tense trajectory. The current weight is UNKNOWN."
            )
    if facts.get("projected_goal_date_earliest") and facts.get("projected_goal_date_latest"):
        lines.append(
            f"  - Projected goal-weight date: a RANGE of {facts['projected_goal_date_earliest']} to "
            f"{facts['projected_goal_date_latest']} (never a single certain date)"
        )
    if not lines:
        return ""
    return (
        "AUTHORITATIVE FACTS (cite these EXACT numbers; do not invent, round away, or "
        "substitute a target/floor for an actual value):\n" + "\n".join(lines) + "\n"
        "HARD RULE for resting HR, HRV, and recovery: state ONLY the exact value above. "
        "Do NOT invent a trend, a range, a multi-day figure, or a 'climbed/dropped from X to Y' "
        "for these — you do not have that history. If you have no specific number for a claim, "
        "describe the pattern qualitatively instead of inventing a figure."
    )


# ── band↔adjective grounding (#1208) ─────────────────────────────────────────
# A number can be digit-grounded yet its VERDICT semantically false: the live
# mind-expert analysis called 44% Whoop recovery "Strong biometric recovery" —
# 44% is Whoop's YELLOW band. The ADR-104 number gate (above) checks digits only,
# never the adjective attached to them. This deterministic, zero-AI check maps a
# metric's canonical value to its documented band and flags a top-band superlative
# ("strong", "excellent", …) sitting next to a sub-band value. Thresholds are the
# source's documented band (ADR-105: personal_baselines has no absolute recovery
# band, so Whoop's published cutoffs are the authority).
#
# Whoop recovery bands (documented): red <34, yellow 34–66, green 67+. A top-band
# superlative is honest ONLY for green.
_RECOVERY_GREEN_FLOOR = 67.0

# Superlatives that assert a HIGH / top-band reading. Scoped tight to claims of
# strength — honest yellow-band words ("moderate", "steady", "middling", "fair")
# are deliberately absent so they never flag.
_HIGH_BAND_ADJECTIVES = (
    "strong",
    "excellent",
    "great",
    "solid",
    "robust",
    "outstanding",
    "superb",
    "stellar",
    "elite",
    "peak",
    "roaring",
    "exceptional",
    "impressive",
    "terrific",
    "fantastic",
)
_HIGH_BAND_RE = re.compile(r"\b(" + "|".join(_HIGH_BAND_ADJECTIVES) + r")\b", re.IGNORECASE)
# Recovery mentions — the noun the adjective must be attached to.
_RECOVERY_KW_RE = re.compile(r"\brecover(?:y|ed|ing)\b", re.IGNORECASE)


def band_adjective_findings(text: str, facts: dict = None, proximity: int = 40) -> list:
    """Deterministic band↔adjective check. Returns [{type: "band_contradiction", ...}].

    For each metric with a documented band and a sub-band canonical value, flag a
    top-band superlative sitting within `proximity` characters of the metric's noun
    (so "strong … recovery" is caught, an unrelated "strong squat" far away is not).
    A superlative that is genuinely consistent (attached to a GREEN-band value) does
    not flag. Empty list = no band mischaracterization.
    """
    text = text or ""
    facts = facts or {}
    findings = []

    rec = facts.get("recovery_pct")
    try:
        rec = float(rec) if rec is not None else None
    except (TypeError, ValueError):
        rec = None
    if rec is not None and rec < _RECOVERY_GREEN_FLOOR:
        band = "red" if rec < 34 else "yellow"
        for km in _RECOVERY_KW_RE.finditer(text):
            lo = max(0, km.start() - proximity)
            hi = km.end() + proximity
            window = text[lo:hi]
            am = _HIGH_BAND_RE.search(window)
            if am:
                findings.append(
                    {
                        "type": "band_contradiction",
                        "metric": "Whoop recovery",
                        "band": band,
                        "value": rec,
                        "adjective": am.group(1),
                        "detail": (
                            f'the narrative calls recovery "{am.group(1)}", but the authoritative '
                            f"Whoop recovery is {rec:g}% — the {band} band, not a strong reading"
                        ),
                    }
                )
                break  # one finding per metric is sufficient signal
    return findings


def grounding_findings(text: str, facts: dict = None, allowed: set = None) -> list:
    """Deterministic grounding check. Returns [{type, detail, ...}] — empty = grounded.

    - "contradiction": a stated RHR/recovery/HRV hard-contradicts canonical facts
      (grounding_guard's per-metric tolerances + grounded-anywhere logic).
    - "band_contradiction": a top-band superlative ("strong recovery") attached to
      a sub-band canonical value (44% = Whoop yellow) — #1208, band_adjective_findings.
    - "fabricated_number": a number appears in the output but nowhere in the
      input allow-list (and isn't benign) — the trend/range fabrication class.
    """
    findings = []
    if facts and _hard_contradictions is not None:
        for c in _hard_contradictions(text, facts):
            findings.append({"type": "contradiction", **c})
    if facts:
        findings.extend(band_adjective_findings(text, facts))
    if allowed is not None:
        for x in fabricated_numbers(text, allowed):
            findings.append(
                {
                    "type": "fabricated_number",
                    "claimed": x,
                    "detail": f"the number {x:g} appears in the narrative but nowhere in the data provided",
                }
            )
    return findings


def correction_prompt(findings: list) -> str:
    """The correction addendum for the single rewrite (analyzer's proven shape)."""
    lines = ["CORRECTION REQUIRED — your draft states numbers that are not grounded in the data:\n"]
    for i, f in enumerate(findings, 1):
        if f.get("type") == "contradiction" and f.get("canonical") is not None:
            lines.append(f"{i}. {f['detail']}. Use {f['canonical']:g}, or omit the metric — never invent one.")
        elif f.get("type") == "band_contradiction":
            lines.append(
                f"{i}. {f['detail']}. Use an accurate band word for a {f['band']} reading "
                f"(e.g. 'moderate' or 'low'), never a superlative."
            )
        elif f.get("type") == "weekday_mismatch":
            lines.append(f"{i}. {f['detail']}. Use {f['actual_weekday']} for that date, or drop the day-of-week — never guess a weekday.")
        else:
            lines.append(f"{i}. {f['detail']}. Remove it or describe the pattern qualitatively — never invent a figure.")
    lines.append("\nRewrite with these corrected. Keep your voice and length; do not mention that a correction was made.")
    return "\n".join(lines)


def regen_once(text: str, findings_fn, regen_fn):
    """One corrective rewrite, kept only if strictly better. Never regresses.

    findings_fn(text) -> list of findings (e.g. a grounding_findings closure).
    regen_fn(correction: str) -> str — the caller's single regeneration call
    (model, tokens, prompt assembly all stay the caller's business).

    Returns (best_text, findings_for_best_text, corrected: bool).
    """
    findings = findings_fn(text)
    if not findings:
        return text, [], False
    try:
        fixed = regen_fn(correction_prompt(findings))
    except Exception:
        return text, findings, False
    if not (fixed or "").strip():
        return text, findings, False
    fixed_findings = findings_fn(fixed)
    if len(fixed_findings) < len(findings):
        return fixed, fixed_findings, True
    return text, findings, False
