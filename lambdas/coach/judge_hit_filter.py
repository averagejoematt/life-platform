"""coach/judge_hit_filter.py — drop a judge anti-pattern hit the text does not contain (#4343, cause A).

The N-06 judge (Haiku, `coach_quality_gate._run_quality_gate`) is handed the coach's
Forbidden Phrases list and reports `anti_pattern_violations`. On the 2026-09-27 brief it
reported list terms that were NOT in the text it judged — explorer `mechanistically` and
`autocorrelation`, mind `emotional texture`, physical `liquidation` (5 of 9 hits on the
final drafts). Each phantom hit did two kinds of harm:

  (a) it rode the report as a finding and helped fail the verdict, and
  (b) `ai_calls._quality_gate_correction_note` wrote it into the rewrite instruction
      ("Remove/avoid the forbidden phrase: \"slow-wave\""), and the rewrite then USED
      the word — sleep and glucose finals contained terms their drafts did not.

A forbidden phrase is a literal claim about the text, so whether it is there is a
deterministic question (ADR-105: deterministic computation before any LLM verdict).
`drop_unfounded_hits` answers it with a normalised substring check and removes every hit
that fails it — from `anti_pattern_violations` AND from the free-text `suggestions` that
quote it — before the report leaves the gate Lambda, so neither the verdict nor the
correction note ever sees it.

Structural-blacklist findings are not phrases ("Opening with a compliment before the
substance"): a hit whose phrase names a structural pattern is kept untouched.

Verdict: when the judge failed the draft and, after the drop, it names NO surviving
finding (anti-pattern, decision-class, similarity) and its voice score clears the
minimum, the fail rested only on phantoms — the verdict is restored to the pass
threshold and the report says so (`judge_verdict_restored`). Deterministic checks
applied after this (number grounding here; served facts + reader checks in
`ai_calls`) still fail the draft on their own.

Every drop is logged as one `JUDGE_HIT_DROPPED {json}` line so the live proof can count
them in `/aws/lambda/coach-quality-gate`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterable

# Hyphen/dash family + the minus sign: "slow-wave", "slow‑wave", "slow–wave", "slow wave"
# are one phrase to a reader, so they are one phrase to this check.
_DASHES_RE = re.compile(r"[\-‐‑‒–—―−]")
_EMPHASIS_RE = re.compile(r"[*_`]")
_WS_RE = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_EDGE_PUNCT = " \t\n\"'.,;:!?()[]"

DROP_LOG_TAG = "JUDGE_HIT_DROPPED"
RESTORE_LOG_TAG = "JUDGE_VERDICT_RESTORED"


def normalise(text: Any) -> str:
    """Casefolded, NFKC, dashes → space, markdown emphasis stripped, whitespace collapsed."""
    s = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTES).casefold()
    s = _EMPHASIS_RE.sub("", _DASHES_RE.sub(" ", s))
    return _WS_RE.sub(" ", s).strip()


def _phrase_of(hit: Any) -> str:
    return str((hit.get("phrase") if isinstance(hit, dict) else hit) or "")


def phrase_in_text(phrase: str, text: str) -> bool:
    """True when the normalised phrase appears in the normalised text."""
    p = normalise(phrase).strip(_EDGE_PUNCT)
    return bool(p) and p in normalise(text)


def _is_structural(phrase: str, structural: Iterable[str]) -> bool:
    p = normalise(phrase).strip(_EDGE_PUNCT)
    for s in structural or ():
        n = normalise(s).strip(_EDGE_PUNCT)
        if n and (p == n or (len(p) >= 12 and (p in n or n in p))):
            return True
    return False


def drop_unfounded_hits(
    result: dict, output_text: str, *, structural=(), voice_minimum=40, pass_threshold=60, coach_id=None, logger=None
) -> list:
    """Remove every judge anti-pattern hit whose phrase is not in ``output_text``.

    Mutates ``result`` in place and returns the dropped phrases. Hits with an empty
    phrase and hits naming a structural pattern are kept (nothing literal to check).
    """
    kept, dropped = [], []
    for hit in result.get("anti_pattern_violations") or []:
        phrase = _phrase_of(hit)
        if not phrase.strip() or _is_structural(phrase, structural) or phrase_in_text(phrase, output_text):
            kept.append(hit)
        else:
            dropped.append(phrase)
    if not dropped:
        return []

    result["anti_pattern_violations"] = kept
    gone = [normalise(p).strip(_EDGE_PUNCT) for p in dropped]
    result["suggestions"] = [s for s in result.get("suggestions") or [] if not any(g in normalise(s) for g in gone)]
    result["dropped_judge_hits"] = dropped
    for phrase in dropped:
        _log(logger, DROP_LOG_TAG, {"event": "judge_hit_dropped", "coach_id": coach_id, "phrase": phrase, "reason": "not_in_text"})

    surviving = kept or result.get("decision_class_violations") or result.get("cross_coach_similarity_flags")
    voice = result.get("voice_distinctiveness_score")
    voice_ok = not isinstance(voice, (int, float)) or voice >= voice_minimum
    if not result.get("passed", True) and not surviving and voice_ok:
        prior = result.get("score")
        result["passed"] = True
        if not isinstance(prior, (int, float)) or prior < pass_threshold:
            result["score"] = pass_threshold
        result["judge_verdict_restored"] = {"prior_score": prior, "dropped": dropped}
        _log(logger, RESTORE_LOG_TAG, {"event": "judge_verdict_restored", "coach_id": coach_id, "prior_score": prior, "dropped": dropped})
    return dropped


def _log(logger, tag: str, payload: dict) -> None:
    line = f"{tag} {json.dumps(payload, default=str, sort_keys=True)}"
    if logger is not None:
        logger.info(line)
    else:
        print(line)
