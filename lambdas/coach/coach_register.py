"""coach_register.py — the tone dial (#1390, epic #1080 "coach experience uplevel").

A **register** is a selectable coach *voice* — clinical / blunt / warm — that changes
only HOW a coaching message is phrased, never WHAT it asserts. The market signal is
Oura Advisor's tone selection; the differentiation this platform ships is the promise
made **structurally verifiable**: the deterministic content (numbers, verdicts,
citations) is byte-identical across all three registers, and the prompt variants are
published verbatim on /method/ so a reader can check the register never edits the facts.

The design that makes AC#1 ("byte-identical deterministic payloads across registers")
a *structural* guarantee rather than a hope:

  1. `build_deterministic_payload(facts)` is PURE and **does not accept a register** —
     it cannot vary by register because register is not one of its inputs. It produces
     the canonical, ordered fact block (the numbers/verdicts/citations the coach may
     narrate but never invent — ADR-104/105's "narrate pre-computed numbers only").

  2. `serialize_payload(payload)` renders that block to a canonical string (sorted
     keys, fixed separators) — the exact bytes the prompt embeds.

  3. `compose_coach_prompt(payload, register)` embeds the serialized payload between
     two sentinels and appends ONLY the register's phrasing instructions after the
     closing sentinel. The bytes between the sentinels are therefore identical for
     every register, by construction — the phrasing layer is physically downstream of
     the fact block and cannot reach back into it.

`tests/test_coach_register_1390.py` proves this end-to-end: it diffs the between-sentinel
slice of `compose_coach_prompt(payload, r)` across all three registers and asserts byte
equality, while asserting the phrasing tails differ.

The register only ever selects a phrasing string; it is never handed the raw numbers to
recompute, so it structurally cannot change a verdict — the same guarantee `bedrock_client`
gives the platform as a whole, applied one level down to the tone dial.

v1.0.0 — 2026-07-24 (#1390)
"""

from __future__ import annotations

import json
from typing import Any

# ── The three registers ──────────────────────────────────────────────────────
# Each register is a phrasing-layer instruction block, published verbatim on
# /method/tone/ (generated from this dict by scripts/v4_build_tone.py, so the page
# cannot drift from the prompt actually used). The `phrasing` string is the ONLY
# thing that varies the model's output; it is appended AFTER the deterministic
# payload and must never instruct the model to change, re-derive, round, reorder,
# or omit any number, verdict, or citation.
REGISTERS: dict[str, dict[str, str]] = {
    "clinical": {
        "label": "Clinical",
        "summary": "Precise and impersonal — reads like a well-written medical note. "
        "States the finding and the mechanism, no exhortation.",
        "phrasing": (
            "Register: CLINICAL.\n"
            "Write like a careful clinician writing a chart note for a colleague. Neutral, "
            "precise, third-person where natural. State each finding and, where the payload "
            "supplies one, its mechanism. No motivational language, no second-person pep, no "
            "exclamation. Hedge exactly as much as the payload's confidence labels hedge — no "
            "more, no less.\n"
            "You are phrasing the facts in the payload above. You may not add, drop, round, "
            "reorder, or reinterpret any number, verdict, or citation. If the payload does not "
            "contain a fact, you do not have it."
        ),
    },
    "blunt": {
        "label": "Blunt",
        "summary": "Direct and unsoftened — the shortest true sentence. " "No cushioning, no hedging beyond what the data itself hedges.",
        "phrasing": (
            "Register: BLUNT.\n"
            "Write like a no-nonsense coach who respects the reader too much to pad. Short "
            "declarative sentences. Lead with the single most important fact. Cut every "
            "qualifier that the payload's own confidence labels do not require. No cushioning "
            "preamble, no 'great job', no softening.\n"
            "You are phrasing the facts in the payload above. You may not add, drop, round, "
            "reorder, or reinterpret any number, verdict, or citation. If the payload does not "
            "contain a fact, you do not have it."
        ),
    },
    "warm": {
        "label": "Warm",
        "summary": "Encouraging and human — acknowledges effort, then delivers the same "
        "finding. Supportive framing, identical substance.",
        "phrasing": (
            "Register: WARM.\n"
            "Write like a coach who is genuinely in the reader's corner. Acknowledge the effort "
            "or the context first, then deliver the finding plainly. Second person, encouraging, "
            "but never false — do not manufacture praise the payload does not support, and do not "
            "let warmth soften a hard number into a vaguer one.\n"
            "You are phrasing the facts in the payload above. You may not add, drop, round, "
            "reorder, or reinterpret any number, verdict, or citation. If the payload does not "
            "contain a fact, you do not have it."
        ),
    },
}

DEFAULT_REGISTER = "clinical"

# Sentinels bracketing the deterministic payload inside the composed prompt. The
# region between them is byte-identical across registers by construction; the test
# and any future auditor can slice on these exact strings.
PAYLOAD_OPEN = "<<<DETERMINISTIC_PAYLOAD>>>"
PAYLOAD_CLOSE = "<<<END_DETERMINISTIC_PAYLOAD>>>"

# The instruction that always precedes the payload — register-independent, part of
# the byte-identical prelude.
_PAYLOAD_PREAMBLE = (
    "The block below is the deterministic coaching payload: every number, verdict, and "
    "citation was computed in Python before you were called (ADR-104/105). It is the "
    "complete and only set of facts you may state. Treat it as read-only."
)


def registers() -> list[str]:
    """The register keys, in published order (clinical, blunt, warm)."""
    return list(REGISTERS.keys())


def is_register(name: str) -> bool:
    return name in REGISTERS


def normalize_register(name: str | None) -> str:
    """Coerce an arbitrary/absent selection to a valid register — unknown or None
    falls back to DEFAULT_REGISTER (never raises, so a bad query param degrades
    gracefully rather than 500-ing a coach surface)."""
    return name if name in REGISTERS else DEFAULT_REGISTER


def build_deterministic_payload(facts: dict[str, Any]) -> dict[str, Any]:
    """PURE, register-INDEPENDENT: normalize `facts` into the canonical deterministic
    payload — the numbers, verdicts, and citations the coach may narrate.

    Deliberately takes NO register argument: the deterministic content structurally
    cannot vary by register because register is not an input here (AC#1). The output is
    a plain dict with a fixed set of keys; missing sections normalize to empty, never to
    a fabricated value (ADR-104 honest-absence).

    `facts` is the caller's raw computed bundle. Recognized sections:
      - "metrics":   list of {name, value, unit?, confidence?} — the numbers.
      - "verdicts":  list of {claim, verdict, n?, p?} — the deterministic calls.
      - "citations": list of {source, ref} — where each fact came from.
    Any other keys are preserved under "extra" (sorted) so nothing is silently dropped,
    but they are still register-independent.
    """

    def _metric(m: dict) -> dict:
        out = {"name": str(m.get("name", "")), "value": _canon_num(m.get("value"))}
        if m.get("unit") not in (None, ""):
            out["unit"] = str(m["unit"])
        if m.get("confidence") not in (None, ""):
            out["confidence"] = str(m["confidence"])
        return out

    def _verdict(v: dict) -> dict:
        out = {"claim": str(v.get("claim", "")), "verdict": str(v.get("verdict", ""))}
        if v.get("n") is not None:
            out["n"] = int(v["n"])
        if v.get("p") is not None:
            out["p"] = _canon_num(v["p"])
        return out

    def _citation(c: dict) -> dict:
        return {"source": str(c.get("source", "")), "ref": str(c.get("ref", ""))}

    recognized = {"metrics", "verdicts", "citations"}
    extra = {k: facts[k] for k in facts if k not in recognized}

    payload: dict[str, Any] = {
        "metrics": [_metric(m) for m in facts.get("metrics", []) or []],
        "verdicts": [_verdict(v) for v in facts.get("verdicts", []) or []],
        "citations": [_citation(c) for c in facts.get("citations", []) or []],
    }
    if extra:
        payload["extra"] = {k: extra[k] for k in sorted(extra)}
    return payload


def _canon_num(value: Any) -> Any:
    """Canonicalize a numeric so its serialized bytes are stable and register-agnostic.
    Ints stay ints; floats that are integral collapse to int (2.0 -> 2); other floats
    keep full repr. Non-numerics pass through as-is (already str/None)."""
    if isinstance(value, bool):  # bool is an int subclass — keep it a bool
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    return value


def serialize_payload(payload: dict[str, Any]) -> str:
    """Canonical string form of the deterministic payload — sorted keys, fixed
    separators, ensure_ascii for byte-stability across locales. These are the exact
    bytes embedded in every register's prompt."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def deterministic_block(payload: dict[str, Any]) -> str:
    """The full register-independent prelude: preamble + bracketed serialized payload.
    Byte-identical for every register (it never sees `register`)."""
    return f"{_PAYLOAD_PREAMBLE}\n{PAYLOAD_OPEN}\n{serialize_payload(payload)}\n{PAYLOAD_CLOSE}"


def compose_coach_prompt(payload: dict[str, Any], register: str | None = None) -> str:
    """Compose the full coach prompt = byte-identical deterministic block + the selected
    register's phrasing instructions.

    The phrasing is appended strictly AFTER the closing sentinel, so the region between
    PAYLOAD_OPEN and PAYLOAD_CLOSE is identical for every register by construction. An
    unknown/None register degrades to DEFAULT_REGISTER (never raises).
    """
    reg = normalize_register(register)
    block = deterministic_block(payload)
    phrasing = REGISTERS[reg]["phrasing"]
    return f"{block}\n\n{phrasing}"


def extract_deterministic_slice(prompt: str) -> str:
    """Return the substring between (and including) the payload sentinels — the byte
    region that must match across registers. Raises if the sentinels are absent/malformed
    (a composed prompt that lost its payload block is a bug, not a silent pass)."""
    start = prompt.index(PAYLOAD_OPEN)
    end = prompt.index(PAYLOAD_CLOSE) + len(PAYLOAD_CLOSE)
    return prompt[start:end]
