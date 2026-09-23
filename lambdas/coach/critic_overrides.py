"""critic_overrides.py — the owner override of ONE vetoing critic (#4076, epic #3742).

WHY THIS EXISTS

A stage-2 veto (`coach.critics`) used to have exactly one way past it besides a redraft:
skip stage 2. On 2026-09-22 that is what happened, and skipping stage 2 also dropped every
OTHER critic's change — the joints critic's set cap went with a veto it had nothing to do
with. This is the narrow door instead: the owner names ONE vetoing critic and says why in
his own words; that critic's veto is marked overridden (its verdict stays `veto` on the
record — the critic still said it), `critics.veto_reason` stops counting it, and nothing
else moves. Every other verdict, veto or change, stands exactly as the critics returned it.

The words ride on the verdict, on the record's `owner_overrides`, into the Hevy notes and
the commit line, and are written to the corrections ledger through the same
`coach_corrections.write_correction` the `log_coach_correction` tool uses. If that ledger
write fails the override is NOT applied: an override with no audit row is the silent bypass
this door replaces.

PURE, like `coach.critics`: the ledger write is injected by `mcp/tools_plan.py`.
"""

from __future__ import annotations

from typing import Any, Callable

from coach.critics import CRITIC_IDS

OVERRIDE_SURFACE = "plan_critics"
OVERRIDE_COACH = "training_coach"  # the red team is the training coach's; the ledger's `{bare}_coach` form
OVERRIDE_DEFAULT_CLASS = "other"


def parse_overrides(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    """(overrides, error) from the caller's `veto_override` argument.

    Accepts one object or a list of them: {critic, owner_words[, error_class]}. The words
    are stored EXACTLY as given — no strip, no paraphrase — and must not be blank. A
    critic id outside CRITIC_IDS, or the same critic named twice, is an error, never a
    silent pick."""
    if raw is None or raw == [] or raw == {}:
        return [], None
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for o in items:
        if not isinstance(o, dict):
            return [], "veto_override entries must be objects {critic, owner_words}"
        cid = o.get("critic")
        words = o.get("owner_words")
        if cid not in CRITIC_IDS:
            return [], f"veto_override.critic must be one of {', '.join(CRITIC_IDS)} — got {cid!r}"
        if not isinstance(words, str) or not words.strip():
            return [], f"veto_override for {cid} needs owner_words — his own words, stored verbatim"
        if cid in seen:
            return [], f"veto_override names {cid} twice — one override per critic"
        seen.add(cid)
        out.append({"critic": cid, "owner_words": words, "error_class": (o.get("error_class") or OVERRIDE_DEFAULT_CLASS)})
    return out, None


def override_item_ref(v: dict[str, Any], *, routine_id: Any, target_date: Any) -> dict[str, Any]:
    """What the corrections-ledger row says was corrected: the vetoing critic and the
    signal it vetoed on. Deliberately no routine VERSION — a re-run with the same words
    is the same correction, and `derive_correction_id` makes it one row (#3114)."""
    return {
        "surface": OVERRIDE_SURFACE,
        "coach": OVERRIDE_COACH,
        "critic": v.get("critic"),
        "signal": v.get("metric"),
        "value": v.get("value"),
        "redline": v.get("redline"),
        "routine_id": routine_id,
        "target_date": target_date,
        "vetoed_reason": str(v.get("reason") or "")[:300],
    }


def apply_overrides(
    verdicts: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
    *,
    at: str,
    routine_id: Any,
    target_date: Any,
    record_correction: Callable[[dict[str, Any], str, str], str],
) -> list[dict[str, Any]]:
    """Mark the named critics' vetoes overridden, in place. One record per override.

    Touches ONLY a verdict whose critic the owner named AND which is a veto. A named
    critic that did not veto this run is recorded `applied: False` with why — its verdict
    is untouched. `record_correction(item_ref, words, error_class) -> sk` is the injected
    ledger write (the `log_coach_correction` path); it runs BEFORE the verdict is marked,
    and if it raises the override is not applied and the veto stands."""
    records: list[dict[str, Any]] = []
    by_critic = {v.get("critic"): v for v in verdicts}
    for o in overrides or []:
        cid = o["critic"]
        v = by_critic.get(cid)
        rec: dict[str, Any] = {"critic": cid, "owner_words": o["owner_words"], "at": at, "applied": False, "why": None}
        if v is None or v.get("verdict") != "veto":
            rec["why"] = (
                f"{cid} did not veto on this run (verdict={(v or {}).get('verdict')!r}) — nothing to override; "
                "its verdict stands as returned and no correction was logged"
            )
            records.append(rec)
            continue
        rec.update({"signal": v.get("metric"), "value": v.get("value"), "redline": v.get("redline"), "vetoed_reason": v.get("reason")})
        item_ref = override_item_ref(v, routine_id=routine_id, target_date=target_date)
        try:
            rec["correction_id"] = record_correction(item_ref, o["owner_words"], o.get("error_class") or OVERRIDE_DEFAULT_CLASS)
        except Exception as e:  # noqa: BLE001 — an override without its ledger row is not applied
            rec["why"] = f"corrections-ledger write failed ({type(e).__name__}: {e})"[:240] + " — override NOT applied, the veto stands"
            records.append(rec)
            continue
        v["owner_override"] = {"owner_words": o["owner_words"], "at": at, "correction_id": rec["correction_id"]}
        rec["applied"] = True
        records.append(rec)
    return records
