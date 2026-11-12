"""block_design_review.py — each new block's accessory selection as a PROPOSAL the owner approves (#5776, epic #5770 S7).

WHAT IT IS. Block accessories used to change with no reviewed proposal: he saw the result, not the reasoning, and could
not veto a pick before it was drafted. At each new 6-week block (`block_model.block_weeks()`), this turns the selection
engine's own record (`selection_engine.select_week`, #5773) into a proposal, per accessory slot:

    pick           what the engine ranks first, with WHY THIS AND WHY NOW — its quality tier (S-D, #5857) for the slot's
                   muscle and its evidence confidence, his N=1 fit, variety (served in the lookback or not, new to him or
                   familiar), a C/D pick's recorded reason, a
                   lengthened-bias swap — all read off the record, nothing re-ranked here;
    replaces       what the slot served last block: the prior block's approved pick, else the rotation ledger's last
                   variant for the slot, else the template accessory;
    alternatives   the slot's ranked eligible candidates below the pick (the engine's order, deterministic);
    unlocks next   the slot's gate-locked library movements and, per gate, its STATE ONLY — "unlocked", "locked: threshold
                   not set", "locked: input not measured", "locked: measured, standard not yet met", "locked: not
                   evaluated yet". A gate's value (a bodyweight mean, a threshold) is private and never read here: only
                   the evaluator row's `state` and `input` fields are (`gate_phrase`).

Plus two sections that are the owner's to decide: the block-end VOLUME RESPONSE (#5801, `volume_response.build_report`
— advisory, carried as it was produced) and the EXPERIMENT SLOT (owner request 2026-11-11, folded into #5776): one
owner-pinned movement variant on one muscle for ONE block, linked to its `create_experiment` record. It is EMPTY by
default and never a default: only an owner-supplied pin fills it (`experiment_pin`), and the next block's proposal and
drafting drop it unless he re-pins it (`resolve`).

THE MODEL. The ranking is deterministic. ONE narration call over it is allowed (`narrate`): through
`bedrock_client.invoke` on route `charter.retro` (this is the block-end ritual of the same skill), budget-tier aware
(`panel_judge._allowed`), and fail-soft — a paused or failed call returns the deterministic summary, said so. Nightly
drafting never calls a model; it reads the approval row.

THE APPROVAL. When he approves, `approval_item` builds ONE owner-only row,
`USER#matthew#SOURCE#training_constraints / BLOCKREVIEW#APPROVED#B<nnn>` (docs/SCHEMA.md): per slot the approved
catalog key (as proposed, an alternative, or the template accessory) plus the experiment pin. Drafting reads it
(`load_failsoft` -> `resolve`, from `variant_rotation.for_session`) and the selection engine honours it as owner pins
for the block (`selection_engine.select_week(owner_pins=...)`). A block with no approval falls back to the PRIOR
block's approved picks, said so, without its experiment; with neither, live drafting serves the #5075 pools.

PRIVATE. The proposal is owner-only scratch output (`scripts/block_design_review.py` refuses an `--out` inside the
repo); the row is Tier 2 owner-only. No load, e1RM, bodyweight or threshold reaches a log line.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

ISSUE = "#5776"
VERSION = "block-design-review@1.0.0"
SOURCE = "training_constraints"
APPROVAL_SK_PREFIX = "BLOCKREVIEW#APPROVED#"
KIND = "block_design_approval"
NARRATION_ROUTE = "charter.retro"
NARRATION_MAX_TOKENS = 900

APPROVED, PRIOR_BLOCK, NONE, READ_FAILED = "approved", "prior_block", "none", "read_failed"
SERVES = (APPROVED, PRIOR_BLOCK)  # the states the selection engine honours (`selection_engine.APPROVAL_SERVES`)
AS_PROPOSED, ALTERNATIVE, INCUMBENT = "as_proposed", "alternative", "incumbent"

EXPERIMENT_EMPTY = {
    "state": "empty",
    "note": "owner-pinned only, never a default: name one slot, the technique, and the create_experiment record it runs under",
}

# The gate value-state vocabulary. Read from an evaluator row's `state` and `input` ONLY (#5772's row also holds
# `value_seen` and a `reason`, both private-capable): the phrase never carries a number.
LOCK_STATE_WORDS = {
    "unlocked": "unlocked",
    "cue": "a cue, never a lock",
    "not_set": "locked: threshold not set",
    "unknown": "locked: input not measured",
    "measured": "locked: measured, standard not yet met",
    "not_evaluated": "locked: not evaluated yet (#5772's evaluator has not stored a row)",
}


# ── keys ─────────────────────────────────────────────────────────────────────
def pk(user_id: str = "matthew") -> str:
    return f"USER#{user_id}#SOURCE#{SOURCE}"


def approval_sk(block: int) -> str:
    return f"{APPROVAL_SK_PREFIX}B{int(block):03d}"


def block_position(block: int) -> dict[str, Any] | None:
    """The rotation position of the block's first program week — the week the proposal is for."""
    from training import variant_rotation as vr
    from training.block_model import block_weeks

    return vr.position({"week": (int(block) - 1) * block_weeks() + 1, "block": int(block)})


# ── gates: the value STATE, never the value ──────────────────────────────────
def gate_state(gate_eval: Optional[Mapping[str, Any]], gate_id: str, movement_id: str) -> dict[str, str]:
    """`{state, input}` for one gate on one movement from #5772's stored evaluation (`EXGATE#EVAL#<monday>` `gates`).
    Only these two fields are read. No evaluation, or no row for the gate => `not_evaluated` (locked)."""
    rows = (gate_eval or {}).get("gates") if isinstance(gate_eval, Mapping) else None
    row = (rows or {}).get(gate_id) if isinstance(rows, Mapping) else None
    if not isinstance(row, Mapping):
        return {"state": "locked", "input": "not_evaluated"}
    by = row.get("by_movement")
    if isinstance(by, Mapping):
        row = by.get(movement_id) or {"state": "unlocked", "input": row.get("input")}
    return {"state": str(row.get("state") or "locked"), "input": str(row.get("input") or "unknown")}


def gate_phrase(state: Mapping[str, Any]) -> str:
    """The owner-facing words for a gate's value state. Never a number."""
    if state.get("input") == "cue":
        return LOCK_STATE_WORDS["cue"]
    if state.get("state") == "unlocked":
        return LOCK_STATE_WORDS["unlocked"]
    return LOCK_STATE_WORDS.get(str(state.get("input")), LOCK_STATE_WORDS["unknown"])


def unlocks_next(slot: Mapping[str, Any], lib: Mapping[str, Any], gate_eval: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The slot's gate-locked library movements (`selection_engine` `locked_next`), best tier first, each gate with its
    kind and value-state phrase."""
    gates = lib.get("gates") or {}
    out = []
    for x in slot.get("locked_next") or []:
        rows = []
        for gid in x.get("gates") or []:
            st = gate_state(gate_eval, gid, x["movement_id"])
            rows.append({"gate": gid, "kind": (gates.get(gid) or {}).get("kind"), "state": gate_phrase(st)})
        out.append({"movement_id": x["movement_id"], "title": x.get("title"), "tier": x.get("tier"), "gates": rows})
    return out


# ── per slot ─────────────────────────────────────────────────────────────────
def _title(catalog: Mapping[str, Any], key: Optional[str]) -> Optional[str]:
    return str((catalog.get(key or "") or {}).get("title") or key) if key else None


def replaces(
    slot: Mapping[str, Any],
    block: int,
    catalog: Mapping[str, Any],
    *,
    prior: Optional[Mapping[str, Any]] = None,
    rows: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """What the slot served last block: the prior block's approved pick, else the ledger's last phase variant for the
    slot in block-1, else the template accessory."""
    from training import variant_rotation as vr

    sid = slot["slot_id"]
    pin = ((prior or {}).get("pins") or {}).get(sid) if isinstance(prior, Mapping) else None
    if isinstance(pin, Mapping) and pin.get("catalog_key"):
        return {
            "catalog_key": pin["catalog_key"],
            "title": _title(catalog, pin["catalog_key"]),
            "source": f"approved for block {block - 1}",
        }
    for r in rows or []:
        if r.get("sk") == vr.ledger_sk(int(block) - 1, sid):
            phases = sorted(
                (k for k, v in r.items() if k.startswith("phase_") and isinstance(v, Mapping) and v.get("variant")), reverse=True
            )
            if phases:
                ck = str(r[phases[0]]["variant"])
                return {"catalog_key": ck, "title": _title(catalog, ck), "source": f"rotation ledger, block {block - 1}"}
    inc = slot["incumbent"]
    return {"catalog_key": inc, "title": _title(catalog, inc), "source": "the template accessory"}


def why(slot: Mapping[str, Any], recent: set[str], replaced: Mapping[str, Any]) -> dict[str, str]:
    """Why this (quality tier + evidence, N=1 fit, variety, a C/D pick's reason) and why now, read off the engine's record."""
    p = slot.get("pick") or {}
    muscle = slot.get("muscle") or "the slot's muscle"
    n1 = p.get("n1") or {}
    fit = "his N=1 fit is unknown (no overlay read)" if n1.get("fit") != "known" else f"his N=1 fit scores {n1.get('score'):+d}"
    variety = "new to him (novel-again caps and a cue sheet ride it)" if p.get("novel") else "familiar"
    variety += ", served in the last block's rotation" if p.get("catalog_key") in recent else ", not served in the lookback"
    evidence = f" (evidence: {p['evidence']})" if p.get("evidence") else ""
    parts = [f"tier {p.get('tier')} for {muscle}{evidence}", fit, variety]
    if p.get("c_reason"):
        parts.append(f"{p.get('tier')} because {p['c_reason'].get('code')}: {p['c_reason'].get('why')}")
    if slot.get("lengthened_swap"):
        parts.append(f"taken as the week's lengthened-bias movement for {muscle}")
    if p.get("catalog_key") == replaced.get("catalog_key"):
        now = f"it holds from last block ({replaced.get('source')}); nothing ranked above it is servable"
    else:
        now = f"block start: the slot rotates, and it now outranks {replaced.get('title')} ({replaced.get('source')})"
    return {"this": "; ".join(parts), "now": now}


def alternatives(slot: Mapping[str, Any], lib: Mapping[str, Any], idx: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
    """The slot's ranked eligible candidates below the pick, in the engine's order."""
    from training import selection_engine as se  # the library is read through the engine only (#5769's guard)

    mv = se.xl.movements(dict(lib))
    pick = (slot.get("pick") or {}).get("movement_id")
    out = []
    for rank, mid in enumerate(slot.get("ranked_top") or [], start=1):
        if mid == pick:
            continue
        e = mv.get(mid) or {}
        out.append(
            {
                "rank": rank,
                "movement_id": mid,
                "catalog_key": idx["to_cat"].get(mid),
                "title": e.get("title") or mid,
                "tier": se.tier_for(e, str(slot.get("muscle") or "")),
            }
        )
    return out


# ── the experiment slot ──────────────────────────────────────────────────────
def experiment_pin(spec: Optional[Mapping[str, Any]], slots: list[Mapping[str, Any]], block: int) -> dict[str, Any]:
    """Validate an owner-supplied experiment pin `{slot_id, technique, experiment_id, catalog_key?, hypothesis?,
    outcome_metric?}`. None => the empty slot. Raises ValueError on a pin that names no selectable slot, no technique or
    no experiment record (the owner act is `create_experiment` first)."""
    if not spec:
        return dict(EXPERIMENT_EMPTY)
    by = {s["slot_id"]: s for s in slots}
    sid = str(spec.get("slot_id") or "")
    s = by.get(sid)
    if s is None:
        raise ValueError(f"experiment slot_id {sid!r} is not an accessory slot of this block")
    if s.get("pinned"):
        raise ValueError(f"experiment slot_id {sid!r} is an owner-pinned slot (variant_rotation.PINNED_SLOTS)")
    for k in ("technique", "experiment_id"):
        if not str(spec.get(k) or "").strip():
            raise ValueError(f"experiment pin needs `{k}` (create the experiment record with create_experiment first)")
    ck = str(spec.get("catalog_key") or (s.get("pick") or {}).get("catalog_key") or s["incumbent"])
    return {
        "state": "pinned",
        "slot_id": sid,
        "muscle": s.get("muscle"),
        "catalog_key": ck,
        "technique": str(spec["technique"]),
        "experiment_id": str(spec["experiment_id"]),
        "hypothesis": spec.get("hypothesis"),
        "outcome_metric": spec.get("outcome_metric"),
        "block": int(block),
        "scope": "this block only — the next block drops it unless the owner re-pins it",
    }


# ── the proposal ─────────────────────────────────────────────────────────────
def build_proposal(
    block: int,
    selection: Mapping[str, Any],
    lib: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    rows: Optional[list[dict[str, Any]]] = None,
    prior: Optional[Mapping[str, Any]] = None,
    gate_eval: Optional[Mapping[str, Any]] = None,
    volume_report: Optional[Mapping[str, Any]] = None,
    experiment: Optional[Mapping[str, Any]] = None,
    reads: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """The block's proposal from the engine's record (`select_week` output for the block's first week). Pure."""
    from training import selection_engine as se, week_floors

    idx = se.key_index(dict(lib), dict(catalog))
    recent = se.recent_uses(rows, selection.get("position"))
    slots = []
    for s in selection.get("slots") or []:
        replaced = replaces(s, block, catalog, prior=prior, rows=rows)
        pick = s.get("pick") or {}
        row = {
            "slot_id": s["slot_id"],
            "role": s["role"],
            "muscle": s.get("muscle"),
            "incumbent": s["incumbent"],
            "pinned": s.get("pinned"),
            "pick": (
                {k: pick.get(k) for k in ("movement_id", "catalog_key", "title", "tier", "evidence", "novel", "length_bias")}
                if pick
                else None
            ),
            "replaces": replaced,
            "changes": bool(pick) and pick.get("catalog_key") != replaced.get("catalog_key"),
            "alternatives": [] if s.get("pinned") else alternatives(s, lib, idx),
            "unlocks_next": unlocks_next(s, lib, gate_eval),
        }
        if s.get("pinned"):
            row["why"] = {"this": f"owner-pinned slot: {s['pinned']}", "now": "pinned slots are not up for selection"}
        elif pick:
            row["why"] = why(s, recent, replaced)
        else:
            row["why"] = {"this": s.get("reason") or "no eligible library candidate", "now": "the template accessory serves"}
        slots.append(row)
    exp = experiment_pin(experiment, slots, block)
    from training import variant_rotation as vr

    missing = [x["slot_id"] for x in vr.slots() if x["slot_id"] not in {r["slot_id"] for r in slots}]
    return {
        "issue": ISSUE,
        "version": VERSION,
        "block": int(block),
        "position": selection.get("position"),
        "library_version": selection.get("library_version"),
        "library_status": selection.get("library_status"),
        "engine_mode": "live" if selection.get("library_status") == se.APPROVED else "shadow",
        "prior_approval": {"block": (prior or {}).get("block"), "state": "read" if prior else "none"},
        "gate_eval": {"week": (gate_eval or {}).get("week_start"), "state": "read" if gate_eval else "not_evaluated"},
        "reads": dict(reads or {}),
        "slots": slots,
        "complete": not missing,  # every accessory slot of the week is on the proposal
        "missing_slots": missing,
        "lengthened": selection.get("lengthened"),
        "week_check": week_floors.lines(dict(selection["week_check"])) if selection.get("week_check") else [],
        "volume_response": _volume_section(volume_report),
        "experiment": exp,
        "approval": "pending — the owner approves with `scripts/block_design_review.py approve`",
    }


def _volume_section(report: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """#5801's per-muscle proposal, carried as it was produced (advisory; nothing applied)."""
    if not isinstance(report, Mapping):
        return {"state": "not_supplied", "note": "run `training_block_retro.py volume-response` and pass its JSON"}
    rows = [
        {"muscle": r.get("muscle"), "response": r.get("response"), "proposal": r.get("proposal")}
        for r in report.get("muscles") or []
        if isinstance(r, Mapping)
    ]
    return {
        "state": "supplied",
        "version": report.get("version"),
        "block_end": report.get("block_end"),
        "caveat": report.get("caveat"),
        "muscles": rows,
    }


def deterministic_summary(proposal: Mapping[str, Any]) -> str:
    """The narration's fail-soft fallback, and its input: one line per slot that changes, then the count that hold."""
    changes = [s for s in proposal["slots"] if s.get("changes") and s.get("pick")]
    lines = [f"Block {proposal['block']}: {len(changes)} slot(s) change, {len(proposal['slots']) - len(changes)} hold."]
    if proposal.get("missing_slots"):
        lines.append(f"INCOMPLETE: no proposal for {', '.join(proposal['missing_slots'])}.")
    for s in changes:
        lines.append(f"- {s['slot_id']}: {s['pick']['title']} replaces {s['replaces']['title']} — {s['why']['this']}.")
    exp = proposal.get("experiment") or {}
    lines.append(
        f"Experiment slot: {exp.get('technique')} on {exp.get('slot_id')} ({exp.get('experiment_id')}), this block only."
        if exp.get("state") == "pinned"
        else "Experiment slot: empty (owner-pinned only)."
    )
    return "\n".join(lines)


def _narration_facts(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """What the model sees: movement names, tiers, reasons and gate STATE phrases. No volume section (its sets and e1RM
    moves are private numbers), no gate values."""
    return {
        "block": proposal["block"],
        "slots": [
            {
                "slot": s["slot_id"],
                "pick": (s.get("pick") or {}).get("title"),
                "tier": (s.get("pick") or {}).get("tier"),
                "replaces": (s.get("replaces") or {}).get("title"),
                "why_this": s["why"]["this"],
                "why_now": s["why"]["now"],
                "alternatives": [a["title"] for a in s.get("alternatives") or []][:3],
                "unlocks_next": [{"movement": u["title"], "gates": [g["state"] for g in u["gates"]]} for u in s.get("unlocks_next") or []],
            }
            for s in proposal["slots"]
        ],
        "experiment": {k: (proposal.get("experiment") or {}).get(k) for k in ("state", "slot_id", "technique")},
    }


NARRATION_SYSTEM = (
    "You narrate a strength-training block's accessory selection proposal for the athlete who will approve it. Use ONLY "
    "the facts given: never add a movement, a tier, a reason or a number. In under 250 words say which slots change and "
    "why, which hold, and what is locked and why it is locked, in plain words. The ranking is fixed; do not re-rank."
)


def narrate(proposal: Mapping[str, Any], *, call: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None) -> dict[str, Any]:
    """ONE model narration over the deterministic proposal. `call` is the transport (tests pass a replay; None =
    `bedrock_client.invoke` on route `charter.retro` after the budget-tier check). Never raises: a paused, failed or
    empty call returns the deterministic summary with its status."""
    fallback = deterministic_summary(proposal)
    if call is None:
        from training import panel_judge

        ok, reason = panel_judge._allowed(NARRATION_ROUTE)
        if not ok:
            return {"status": "paused", "reason": reason, "text": fallback, "source": "deterministic"}
    body = {
        "max_tokens": NARRATION_MAX_TOKENS,
        "system": NARRATION_SYSTEM,
        "messages": [{"role": "user", "content": json.dumps(_narration_facts(proposal), sort_keys=True)}],
    }
    try:
        if call is None:
            from training import panel_judge

            call = panel_judge._bedrock_call(NARRATION_ROUTE)
        resp = call(body)
        text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if isinstance(c, Mapping)).strip()
        if not text:
            return {"status": "failed", "reason": "empty narration", "text": fallback, "source": "deterministic"}
        return {"status": "ok", "route": NARRATION_ROUTE, "text": text, "source": "model", "usage": (resp or {}).get("usage")}
    except Exception as e:  # noqa: BLE001 — the narration is optional; the deterministic text stands
        logger.warning("block_design_review: narration failed (%s) — the deterministic summary stands", type(e).__name__)
        return {"status": "failed", "reason": type(e).__name__, "text": fallback, "source": "deterministic"}


def render_markdown(proposal: Mapping[str, Any], narration: Optional[Mapping[str, Any]] = None) -> str:
    """The owner-only doc text for the private review doc."""
    out = [
        f"# Block design review — block {proposal['block']} (PROPOSAL, awaiting approval)",
        "",
        f"Library {proposal.get('library_version')} ({proposal.get('library_status')}); engine {proposal.get('engine_mode')}. "
        "Ranking is the selection engine's (deterministic); approve, swap a slot for a ranked alternative, or keep the template.",
        "",
    ]
    if narration:
        out += [f"**Narration ({narration.get('source')}, {narration.get('status')})**", "", str(narration.get("text") or ""), ""]
    for s in proposal["slots"]:
        p = s.get("pick") or {}
        out.append(f"## {s['slot_id']} ({s.get('muscle')})")
        out.append(f"- Pick: {p.get('title') or '—'} [tier {p.get('tier')}]; replaces {s['replaces']['title']} ({s['replaces']['source']})")
        out.append(f"- Why this: {s['why']['this']}")
        out.append(f"- Why now: {s['why']['now']}")
        if s.get("alternatives"):
            out.append("- Alternatives: " + "; ".join(f"{a['rank']}. {a['title']} [{a['tier']}]" for a in s["alternatives"]))
        for u in s.get("unlocks_next") or []:
            out.append(f"- Unlocks next: {u['title']} [{u['tier']}] — " + "; ".join(f"{g['gate']} {g['state']}" for g in u["gates"]))
        out.append("")
    exp = proposal.get("experiment") or {}
    out.append("## Experiment slot (owner-pinned, one block)")
    if exp.get("state") == "pinned":
        out.append(
            f"- {exp['technique']} on {exp['slot_id']} ({exp.get('muscle')}), movement {exp['catalog_key']}; record {exp['experiment_id']}"
        )
        out.append(f"- {exp['scope']}")
    else:
        out.append(f"- Empty. {exp.get('note')}")
    out.append("")
    vol = proposal.get("volume_response") or {}
    out.append("## Volume response (#5801, advisory)")
    if vol.get("state") == "supplied":
        out.append(f"- {vol.get('caveat')}")
        for r in vol.get("muscles") or []:
            pr = r.get("proposal") or {}
            nxt = (
                f"{pr.get('sets_per_wk')} sets/wk ({pr.get('status')})"
                if "sets_per_wk" in pr
                else pr.get("status") or "insufficient evidence"
            )
            out.append(f"- {r['muscle']}: response {r.get('response')}; next block {nxt}")
    else:
        out.append(f"- Not supplied. {vol.get('note')}")
    return "\n".join(out).rstrip() + "\n"


# ── the approval row ─────────────────────────────────────────────────────────
def approval_item(
    proposal: Mapping[str, Any], decisions: Optional[Mapping[str, Any]], *, approved_at: str, user_id: str = "matthew"
) -> dict[str, Any]:
    """The owner-only approval row. `decisions` {slot_id: catalog_key | "incumbent"} departs from the proposal per slot
    (default: every slot as proposed); a key that is neither the pick, a ranked alternative nor the template accessory is
    refused (ValueError). Owner-pinned slots are never written (they hold by `variant_rotation.PINNED_SLOTS`)."""
    decisions = dict(decisions or {})
    by = {s["slot_id"]: s for s in proposal["slots"]}
    unknown = sorted(set(decisions) - set(by))
    if unknown:
        raise ValueError(f"decisions name slots the proposal does not hold: {unknown}")
    pins: dict[str, dict[str, Any]] = {}
    for sid, s in by.items():
        if s.get("pinned"):
            continue
        pick = s.get("pick") or {}
        want = decisions.get(sid)
        if want is None:
            ck, how = pick.get("catalog_key") or s["incumbent"], AS_PROPOSED if pick.get("catalog_key") else INCUMBENT
        elif want in (INCUMBENT, s["incumbent"]):
            ck, how = s["incumbent"], INCUMBENT
        elif want == pick.get("catalog_key"):
            ck, how = want, AS_PROPOSED
        elif want in {a.get("catalog_key") for a in s.get("alternatives") or [] if a.get("catalog_key")}:
            ck, how = want, ALTERNATIVE
        else:
            raise ValueError(f"{sid}: {want!r} is not the pick, a ranked alternative or the template accessory")
        pins[sid] = {"catalog_key": ck, "decision": how}
    exp = proposal.get("experiment") or {}
    return {
        "pk": pk(user_id),
        "sk": approval_sk(proposal["block"]),
        "kind": KIND,
        "issue": ISSUE,
        "version": VERSION,
        "block": int(proposal["block"]),
        "library_version": proposal.get("library_version"),
        "pins": pins,
        "experiment": {k: v for k, v in exp.items() if k != "note"} if exp.get("state") == "pinned" else None,
        "approved_at": approved_at,
        "tier": "owner_only",
    }


def resolve(rows: Optional[list[Mapping[str, Any]]], block: int) -> dict[str, Any]:
    """The approval drafting honours for `block`: this block's row (`approved`, with its experiment), else the prior
    block's (`prior_block` — its picks, NEVER its experiment), else `none`. `pins` is the selection engine's
    `owner_pins` shape {slot_id: {catalog_key, source, approved_block, experiment}}."""
    by: dict[int, Mapping[str, Any]] = {}
    for r in rows or []:
        if str(r.get("sk") or "").startswith(APPROVAL_SK_PREFIX):
            by[int(r.get("block") or str(r["sk"])[len(APPROVAL_SK_PREFIX) + 1 :])] = r
    block = int(block)
    row, state = (by.get(block), APPROVED) if block in by else (by.get(block - 1), PRIOR_BLOCK)
    if row is None:
        return {
            "state": NONE,
            "block": block,
            "approved_block": None,
            "pins": {},
            "experiment": None,
            "note": f"no approval for block {block} or {block - 1}",
        }
    exp = row.get("experiment") if state == APPROVED else None
    exp = exp if isinstance(exp, Mapping) and int(exp.get("block") or -1) == block else None
    pins = {}
    for sid, p in (row.get("pins") or {}).items():
        x = exp if exp is not None and exp.get("slot_id") == sid else None
        pins[sid] = {
            "catalog_key": x["catalog_key"] if x is not None else p.get("catalog_key"),
            "source": state,
            "approved_block": int(row.get("block") or block),
            "experiment": {k: x.get(k) for k in ("technique", "experiment_id", "muscle", "block")} if x is not None else None,
        }
    note = (
        f"block {block} approved"
        if state == APPROVED
        else f"block {block} has no approved proposal — block {block - 1}'s approved picks serve (its experiment does not carry over)"
    )
    return {"state": state, "block": block, "approved_block": int(row.get("block") or block), "pins": pins, "experiment": exp, "note": note}


def load_rows(block: int, table: Any = None, user_id: str = "matthew") -> list[dict[str, Any]]:
    """The approval rows for `block` and the block before it (read-only). Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    if table is None:
        from training import exercise_history

        table = exercise_history._table()
    cond = Key("pk").eq(pk(user_id)) & Key("sk").between(approval_sk(max(1, int(block) - 1)), approval_sk(int(block)))
    return list(table.query(KeyConditionExpression=cond).get("Items") or [])


def load_failsoft(block: int, table: Any = None) -> dict[str, Any]:
    """`resolve` over the stored rows; a failed read is `read_failed` (live drafting then serves the pools, said so)."""
    try:
        return resolve(load_rows(block, table), block)
    except Exception as e:  # noqa: BLE001 — an unread approval never blocks a draft
        logger.warning("block_design_review: the approval read failed (%s) — live drafting serves the pools", type(e).__name__)
        return {
            "state": READ_FAILED,
            "block": int(block),
            "approved_block": None,
            "pins": {},
            "experiment": None,
            "note": f"read_failed: {type(e).__name__}",
        }
