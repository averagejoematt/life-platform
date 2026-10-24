"""coach/response_protocol.py — ONE coach owns the early-warning response (#5126, epic #5120).

THE DEFECT. ``config/user_goals.json`` ``failure_mode.coach_response`` told "the board lead" to acknowledge an
early-warning signal and "Maya" (a board advisor with no coach config and no engine) to address the behavioural
pattern, while the coach whose domain that is — the mind coach, ``config/coaches/mind_coach.json`` — was named
nowhere. Two owners, so neither acted (mind/coping/habits panel review 2026-10-18).

THE CONTRACT.
  * ``failure_mode.response_owner`` names the ONE owner, as a coach id: an operational coach
    (``persona_registry.OPERATIONAL_COACH_IDS``), so it has a config, a daily engine and a Telegram seat.
  * ``failure_mode.coach_response`` (the prose every coach preamble renders) names no OTHER persona and no
    other role — ``claimants`` reads it with the persona registry's names, and a second name is a second claim.
  * ``problems`` states every breach; ``tests/test_response_protocol_owner_5126.py`` runs it over the repo's
    config, and over a two-claimant fixture to prove it can fail.

THE READ. ``view`` is the protocol as the coach context carries it (``training.coach_context.assemble``'s
``response_protocol``, owner channel only, and the mind coach's own Telegram thread): the owner, the signals,
the protocol text and its source. PURE over what it is handed; ``load`` is the one I/O (the repo file when
present, else the S3 twin ``config/user_goals.json`` — config/ is not in the Lambda bundle), fail-soft to None.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

VERSION = "response-protocol@1.0.0"
SOURCE = "config/user_goals.json failure_mode (coach.response_protocol)"
OWNER_KEY = "response_owner"
PROSE_KEY = "coach_response"

# Role words that name a persona without naming them. "The board lead" is the lead persona (Eli Marsh).
_ROLE_CLAIMS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:board\s+lead|head\s+coach|principal\s+investigator|the\s+lead)\b", re.IGNORECASE), "eli_marsh"),
)
# A first name that is also an ordinary capitalised word is never read as a name on its own.
_NOT_A_FIRST_NAME = frozenset({"The", "Coach"})


def _name_patterns(name: str) -> list[re.Pattern]:
    """The ways prose names a persona: the full name, and its first and last names (case-sensitive, whole word)."""
    parts = [p for p in str(name or "").replace("Coach ", "").split() if p]
    forms = {" ".join(parts)} if parts else set()
    if len(parts) >= 2:
        forms.add(parts[-1])
        if parts[0] not in _NOT_A_FIRST_NAME:
            forms.add(parts[0])
    return [re.compile(r"\b" + re.escape(f) + r"\b") for f in sorted(forms) if f]


def claimants(failure_mode: Mapping[str, Any], names: Mapping[str, str]) -> list[str]:
    """Every persona id the failure-mode block assigns the response to: the named owner, every persona
    whose name the protocol prose carries, and every role it names. Personas sharing the owner's display
    name (a board twin of the same character) count as the owner. Sorted, de-duplicated."""
    fm = failure_mode if isinstance(failure_mode, Mapping) else {}
    owner = str(fm.get(OWNER_KEY) or "").strip()
    owner_name = str(names.get(owner) or "").replace("Coach ", "").strip()
    prose = str(fm.get(PROSE_KEY) or "")
    found: set[str] = {owner} if owner else set()
    for pid, name in names.items():
        if pid == owner or (owner_name and str(name).replace("Coach ", "").strip() == owner_name):
            continue
        if any(p.search(prose) for p in _name_patterns(name)):
            found.add(pid)
    for pattern, pid in _ROLE_CLAIMS:
        if pattern.search(prose) and pid != owner:
            found.add(pid)
    return sorted(found)


def problems(failure_mode: Mapping[str, Any], names: Mapping[str, str], operational_ids: Any) -> list[str]:
    """Every breach of the one-owner contract, in words. Empty = one live coach owns the response."""
    fm = failure_mode if isinstance(failure_mode, Mapping) else {}
    owner = str(fm.get(OWNER_KEY) or "").strip()
    out: list[str] = []
    if not owner:
        out.append(f"failure_mode.{OWNER_KEY} is not set: no coach owns the early-warning response")
    elif owner not in set(operational_ids or ()):
        out.append(f"failure_mode.{OWNER_KEY} {owner!r} is not an operational coach (no config, engine or Telegram seat)")
    if not str(fm.get(PROSE_KEY) or "").strip():
        out.append(f"failure_mode.{PROSE_KEY} is empty: the owner has no protocol to run")
    who = claimants(fm, names)
    if len(who) > 1:
        out.append(f"{len(who)} personas claim the early-warning response ({', '.join(who)}); exactly one may")
    return out


def view(goals: Optional[Mapping[str, Any]], names: Mapping[str, str]) -> Optional[dict[str, Any]]:
    """The protocol as a coach context carries it, or None when the plan root has no failure-mode block."""
    fm = (goals or {}).get("failure_mode") if isinstance(goals, Mapping) else None
    if not isinstance(fm, Mapping) or not fm:
        return None
    owner = str(fm.get(OWNER_KEY) or "").strip() or None
    owner_name = str(names.get(owner) or owner or "unassigned")
    signals = [str(s) for s in (fm.get("early_warning_signals") or []) if str(s).strip()]
    protocol = str(fm.get(PROSE_KEY) or "").strip()
    return {
        "source": SOURCE,
        "version": VERSION,
        "owner": owner,
        "owner_name": owner_name,
        "signals": signals,
        "protocol": protocol,
        "line": f"Owner: {owner_name} ({owner or 'unassigned'}) — the ONE coach who answers an early-warning signal. {protocol}",
    }


def load(s3_client: Any = None, bucket: Optional[str] = None) -> Optional[dict[str, Any]]:
    """The plan root (the repo file when present, else the S3 twin), or None on any failure (fail-soft)."""
    try:
        from common.repo_config import config_path  # noqa: PLC0415

        with open(config_path("user_goals.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 — in Lambda config/ is not bundled: the S3 twin is the source
        pass
    try:
        if s3_client is None:
            import boto3  # noqa: PLC0415

            s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        body = s3_client.get_object(Bucket=bucket or os.environ.get("S3_BUCKET", "matthew-life-platform"), Key="config/user_goals.json")
        return json.loads(body["Body"].read())
    except Exception as e:  # noqa: BLE001 — a coach context is never load-bearing on this read
        logger.warning("[response_protocol] plan root unavailable (protocol omitted): %s", type(e).__name__)
        return None


def persona_names() -> dict[str, str]:
    """persona id -> display name, from the persona registry (fail-soft: {})."""
    try:
        from coach import persona_registry  # noqa: PLC0415

        return {pid: str((p or {}).get("name") or "") for pid, p in persona_registry.personas().items()}
    except Exception as e:  # noqa: BLE001
        logger.warning("[response_protocol] persona registry unavailable: %s", type(e).__name__)
        return {}


def current() -> Optional[dict[str, Any]]:
    """``view`` over the live plan root and registry — the owner-channel callers' one call. None on any trouble."""
    try:
        return view(load(), persona_names())
    except Exception as e:  # noqa: BLE001
        logger.warning("[response_protocol] protocol unavailable: %s", type(e).__name__)
        return None
