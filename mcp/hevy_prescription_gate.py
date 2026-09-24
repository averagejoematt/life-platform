# gate-entrypoint: this file computes the commit refusal and `tools_hevy_routine.
# _action_commit` blocks on it — `mcp_error(refusal_message(gate), error_code=
# SUBTRACT_ONLY_VIOLATION)`, and the routine never reaches Hevy. Nothing here raises or
# exits, so the census's structural classifier cannot see that enforcement; this is the
# `declared-entrypoint` case (scripts/gate_census_enforcement.py). #3220 Q1 YES — a
# blocking consumer obeys this file's verdict. Q2 NO COVERING ROW — the only other row
# that could report this verdict would be a structural:: test, and
# tests/test_subtract_only_commit_gate_behavior.py is a behaviour test, not a
# tree-sweeping one, so it is not in that family. Proof record:
# scripts/gate_census_proofs.py::GUARD_PROOFS["guard::mcp/hevy_prescription_gate.py"].
"""hevy_prescription_gate.py — subtract-only as a GATE on the chat path (#3971).

WHY THIS EXISTS

#3927 made the subtract-only rule real on the CRON path: `routine_generator.
_enforce_load_floors()` raises every working set to the movement's band-matched
prescription floor and records the pass in `inputs_snapshot["load_floors"]`. The
chat path — `manage_hevy_routine draft_custom -> dry_run -> commit`, which is the
surface that authored BOTH #3927 specimens — was left governed only by SKILL.md
prose plus `recovery_authoring.audit_prescription()`, which the authoring session
has to REMEMBER to call. A rule that depends on remembering is a discipline, not a
gate: a routine whose notes say "if set 1 feels good, go up to 85" could still be
committed, and one of them was.

So this module is the refusal. It is shaped after the #3752 critic veto in
`coach.critics` (`veto_reason` -> `mcp_error(..., error_code=...)`): a NAMED error
code, the offending clause quoted, and — for a below-floor set — the floor's
PROVENANCE, because "you prescribed too little" is unactionable without the date,
the load and the bodyweight the floor was drawn from.

WHAT IT DOES NOT DO

It does not raise the load. ADR-069's escape hatch exists precisely so the chat
path can prescribe what the platform did not compute; silently rewriting a
caller-supplied number would be a different (and worse) surprise than refusing.
The cron path applies; the chat path refuses. Both derive the floor the same way,
from `routine_generator.prescription_floor`, so there is ONE definition of a floor.
#4107: while the v0.3 program is ACTIVE the floor is `load_ramp.v03_floor` on both paths
(the band anchor, the nearest-band fallback, the week's §3 entry ramp) — the chat path
used to hold a draft_custom routine to the 100 % best-load floor the generator no longer
prescribes, so the two paths disagreed about the same session.

`floor` and `re_entry` variants are exempt BY DESIGN and say so in the result:
they prescribe a deliberately reduced session, and a floor asserted over one would
be the exact inverse of the rule.

I/O: the floor arm needs the Hevy history + Withings bodyweight indexes, so it is
NOT pure — but every load is fail-soft and the absence is reported BY NAME
(`indexes_unavailable`, `no_current_bodyweight`) rather than passing for a clean
audit. The conditional-up arm is pure text and always runs; a DynamoDB hiccup can
cost the floor check, never the prose check. Both index arguments are injectable
so the gate tests against the live wire shapes in
tests/fixtures/subtract_only_3927/ with no AWS.

COST, MEASURED not assumed (2026-09-21, from a laptop over the internet — in-region
from the MCP Lambda it is faster): the 3,650-day Hevy history Query returned 502
templates in 2.95s and the Withings bodyweight Query 1,047 weigh-ins in 0.03s. So
the gate adds roughly one such pair to `dry_run` and one to `commit`. That is the
same pair `_action_draft` already pays per call, and it is deliberately NOT cached:
a memoised history index is a stale floor, and a stale floor is the exact defect
#3927 was filed on.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

logger = logging.getLogger("hevy_prescription_gate")

# The named refusal, in the shape of #3752's CRITIC_VETO.
SUBTRACT_ONLY_ERROR_CODE = "SUBTRACT_ONLY_VIOLATION"

# Variants that prescribe no load by design (#3927: "a floor stamped on a
# deliberately-easy variant would be the opposite rule").
NO_LOAD_VARIANTS = frozenset({"floor", "re_entry"})

SKIP_NOTE = (
    "subtract-only gate SKIPPED — variant={variant} prescribes a deliberately reduced session and asserts no load "
    "floor by design (#3927/#3971). Conditional up-branches and below-floor sets are NOT checked on this variant."
)

# `status` vocabulary is deliberately the SAME as `_enforce_load_floors`'s, because the
# live readback (#3971 acceptance box 4) reads `inputs_snapshot.load_floors.status` and
# must not have to know which path authored the routine. "applied" means the floor pass
# RAN against a resolved bodyweight — on this path enforcement is a refusal rather than a
# silent raise, which `enforcement` records.
ENFORCEMENT = "chat_commit_gate_refusal"


def _catalog_movements() -> dict[str, Any]:
    from training.routine_generator import _load_json

    return (_load_json("movement_catalog.json") or {}).get("movements", {})


def _template_id_for(movement_key: str | None, movements: dict[str, Any]) -> str | None:
    """movement_key -> Hevy template id, WITHOUT any network resolve.

    `tmpl:<id>` keys (ADR-069 index-resolved / auto-created movements) already carry
    the id; curated keys carry a catalog hint. A key with neither yields None, which
    `prescription_floor` reports as `no_template_id` — an absence, never a guess.
    """
    if not movement_key:
        return None
    if movement_key.startswith("tmpl:"):
        return movement_key[len("tmpl:") :]
    return ((movements or {}).get(movement_key) or {}).get("hevy_template_id_hint")


def _days_since_last_workout(history_index: dict[str, list], target_date: str) -> int | None:
    """Derived from the history itself, never assumed.

    The layoff discount is the ONLY sanctioned path to a floor below an achieved load,
    so the number that triggers it has to come from evidence. None (no prior session on
    record) means no discount — the strictest floor — rather than a guessed gap.
    """
    from common.pacific_time import parse_day_key

    latest = ""
    for sessions in (history_index or {}).values():
        for s in sessions or []:
            d = str((s or {}).get("date") or "")
            if d and (not target_date or d < target_date) and d > latest:
                latest = d
    if not latest or not target_date:
        return None
    # #3609: calendar-day arithmetic on two bare DATE# day keys goes through the ONE day-key
    # parser (never a hand-rolled fromisoformat — the registry of those is shrink-only).
    a, b = parse_day_key(target_date), parse_day_key(latest)
    if a is None or b is None:
        return None
    return (a - b).days


def _load_indexes() -> tuple[dict[str, list], dict[str, float], str | None]:
    """The two live indexes the floor needs. Fail-soft, and the failure is NAMED."""
    from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_bodyweight_index, load_history_indexes

    try:
        history = load_history_indexes(lookback_days=max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS))[0]
        weights = load_bodyweight_index()
    except Exception as e:  # noqa: BLE001
        logger.warning("subtract-only gate: index load failed (%s) — the floor arm cannot run", e)
        return {}, {}, f"{type(e).__name__}: {e}"
    return history, weights, None


def derive_load_floors(
    ir: Any,
    *,
    movements: dict[str, Any] | None = None,
    history_index: dict[str, list] | None = None,
    weight_index: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The `inputs_snapshot["load_floors"]` audit for a chat-authored routine.

    Same shape and same `status` vocabulary as `routine_generator._enforce_load_floors`
    so one readback serves both paths — including the movements that got NO floor and
    why, because a silent absence reads as "the rule was satisfied".
    """
    from training.band_reference import band_key
    from training.exercise_history import nearest_bodyweight
    from training.routine_generator import SUBTRACT_ONLY_RULE, prescription_floor

    target_date = str(getattr(ir, "target_date", "") or "")
    audit: dict[str, Any] = {
        "rule": SUBTRACT_ONLY_RULE,
        "source": "chat_commit_gate",
        "enforcement": ENFORCEMENT,
        "target_date": target_date,
        "current_bodyweight_lb": None,
        "band": None,
        "movements": {},
    }
    if history_index is None or weight_index is None:
        loaded_history, loaded_weights, err = _load_indexes()
        history_index = loaded_history if history_index is None else history_index
        weight_index = loaded_weights if weight_index is None else weight_index
        if err:
            audit["status"] = "indexes_unavailable"
            audit["reason"] = err
            return audit

    current_lb = nearest_bodyweight(target_date, weight_index) if target_date else None
    if not current_lb:
        audit["status"] = "no_current_bodyweight"
        audit["reason"] = "no weigh-in within tolerance of the target date — no floor was asserted (#3927)"
        return audit

    audit["current_bodyweight_lb"] = round(float(current_lb), 1)
    audit["band"] = band_key(float(current_lb))
    audit["status"] = "applied"
    dslw = _days_since_last_workout(history_index, target_date)
    audit["days_since_last_workout"] = dslw
    movements = _catalog_movements() if movements is None else movements
    # #4065: the chat path's half of the #4090 back-off seam. The generator writes
    # `back_off_floor_kg` for the sets it authors; a hand-drafted v0.3 heavy exposure gets the
    # same field from the redline rep scheme (parsed, never a hand list; −pct off the floor,
    # rounded DOWN to the rack step). An unparsed scheme writes none, so back-offs fail closed.
    from training.rep_scheme import back_off_min_kg, heavy_back_off_scheme

    scheme = heavy_back_off_scheme()
    audit["back_off_scheme"] = {k: v for k, v in scheme.items() if k != "source_text"}

    floor_fn, back_off_pct = prescription_floor, None
    v03 = v03_load_rule(target_date)
    if v03 is not None:
        # #4107: under v0.3 the chat path's floor IS the generator's load — the same
        # `load_ramp.v03_floor` (band anchor -> nearest-band fallback -> the week's ramp),
        # not the #3927 100 % best-load floor. One load path, so a draft_custom routine
        # carrying the generator's own numbers commits, and one under them refuses.
        from training import load_ramp

        floor_fn = functools.partial(load_ramp.v03_floor, week=v03["week"])
        back_off_pct = v03["back_off_pct_of_top"]
        audit["load_rule"] = v03

    for ex in getattr(ir, "exercises", None) or []:
        key = getattr(ex, "movement_key", None) or "?"
        floor = floor_fn(
            _template_id_for(key, movements),
            history_index,
            weight_index,
            current_lb,
            days_since_last_workout=dslw,
            as_of=target_date,
        )
        row = {k: floor.get(k) for k in ("status", "template_id", "floor_kg", "best_kg", "basis", "discount_pct", "layoff_reason")}
        if v03 is not None:
            row.update({k: floor.get(k) for k in ("ramp", "anchor_band", "anchor_date", "fallback", "fallback_detail")})
            if floor.get("floor_kg") and back_off_pct is not None:
                # §3's heavy exposure is [top, back-off, back-off] at −10 % of the top set; the
                # chat path cannot know which exposure a caller meant as heavy, so every set
                # after the first is judged against the back-off floor — the same number the
                # generator records as `back_off_floor_kg` (#4090).
                from training.routine_generator import _floor_half_kg

                row["back_off_floor_kg"] = _floor_half_kg(float(floor["floor_kg"]) * back_off_pct / 100.0)
        if "back_off_floor_kg" not in row and floor.get("floor_kg") and scheme.get("status") == "ok":
            # #4065: outside the v0.3 load rule the back-off floor comes from the redline rep scheme.
            row["back_off_floor_kg"] = back_off_min_kg(float(floor["floor_kg"]), scheme)
        audit["movements"][key] = row
    return audit


def v03_load_rule(target_date: str, block_workouts: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The v0.3 load rule for `target_date`, or None (#4107).

    None when the program is not ACTIVE, or when the date is before the block start — the
    program's loads begin with its sequence, and a pre-block chat routine keeps the #3927
    best-load floor it was always judged against.

    #4110/#4161: the week is the session SEQUENCE's (`session_sequence.next_session` over `ledger()`) — HYBRID:
    a week advances only when its 4-session cycle is complete AND >= 7 days have passed since the previous
    advance (`session_sequence.WEEK_RULE`) — the same week `full_body_session` ramps and the
    `not_before_week` gate reads. `block_workouts` is the Hevy record since the block start;
    None reads it (`plan_hevy_windows._block_workouts`, the sanctioned MCP Hevy read). A read
    that fails leaves the week UNKNOWN: the rule then ramps as week 1 — the lowest ramp floor,
    so an unreadable record can never refuse the generator's own loads — and says so in
    `week_state` rather than presenting week 1 as measured."""
    from training import program_structure, session_sequence

    if not program_structure.ACTIVE or not target_date:
        return None
    if target_date < session_sequence.block_start():
        return None
    read_error = None
    if block_workouts is None:
        from mcp.plan_hevy_windows import _block_workouts

        try:
            block_workouts = _block_workouts(target_date)
        except Exception as e:  # noqa: BLE001 — reported on the rule as week_state, never a silent week
            read_error = f"{type(e).__name__}: {e}"
    try:
        entry = session_sequence.next_session(target_date, block_workouts)
    except ValueError:
        return None
    if entry is None:
        return None
    known = entry.get("source") == "session_sequence"
    pct = 100 + int(program_structure.EXPOSURES["heavy"]["back_off_pct"])  # §3: back-offs at −10 % of the top set
    return {
        "rule": "§3 entry ramp (load_ramp.v03_floor)",
        "program_version": program_structure.PROGRAM_VERSION,
        "week": int(entry.get("week") or 1),
        "week_state": "measured" if known else "unreadable",
        "week_source": (
            f"session sequence: {entry.get('position_label')}"
            if known
            else f"session sequence UNREADABLE ({read_error or entry.get('note')}) — ramped as week 1, the lowest v0.3 floor"
        ),
        "block": entry.get("block"),
        "back_off_pct_of_top": pct,
    }


def prescription_gate(ir: Any, **kw: Any) -> dict[str, Any]:
    """The verdict for ONE routine IR: clean, refuse, or skipped.

    A routine the generator already floored carries its own `load_floors` audit; that
    one is REUSED rather than recomputed — the cron path raised the sets, so re-deriving
    would only invite the two derivations to disagree about the same routine.
    """
    from training.routine_generator import SUBTRACT_ONLY_RULE

    from mcp.recovery_authoring import audit_prescription

    variant = str(getattr(ir, "variant", "") or "ideal").lower()
    out: dict[str, Any] = {"rule": SUBTRACT_ONLY_RULE, "variant": variant, "error_code": SUBTRACT_ONLY_ERROR_CODE}
    if variant in NO_LOAD_VARIANTS:
        out.update(
            {
                "enforced": False,
                "verdict": "skipped",
                "skipped_reason": SKIP_NOTE.format(variant=variant),
                "load_floors": {"status": "not_applicable", "reason": SKIP_NOTE.format(variant=variant)},
                "audit": None,
            }
        )
        return out

    stored = ((getattr(ir, "inputs_snapshot", None) or {}).get("load_floors")) or {}
    if stored.get("status") == "applied":
        floors = dict(stored)
        floors.setdefault("source", "routine_generator")
    else:
        floors = derive_load_floors(ir, **kw)

    audit = audit_prescription(getattr(ir, "exercises", None) or [], getattr(ir, "notes", "") or "", floors.get("movements"))
    out.update(
        {
            "enforced": True,
            "verdict": "clean" if audit["ok"] else "refuse",
            "skipped_reason": None,
            "load_floors": floors,
            "audit": audit,
        }
    )
    return out


def critic_set_floors(ir: Any, **kw: Any) -> Any:
    """Stage 2's critic clamp (#4149): `exercise -> [floor_kg | None per set]`, or None.

    The floors are `prescription_gate`'s own — the stored generator audit or
    `derive_load_floors` (under v0.3, `load_ramp.v03_floor`) — and the per-set split is
    `recovery_authoring.set_floors_kg`, the function `audit_prescription` judges with. So a
    critic change held to these floors is, by construction, one the commit gate accepts. None
    (no clamp) only where the gate itself asserts no floor: a no-load variant, or floors it
    could not derive — `critics.apply_changes` then records nothing it did not check."""
    from mcp.recovery_authoring import _n_back_offs, set_floors_kg

    try:
        gate = prescription_gate(ir, **kw)
    except Exception as e:  # noqa: BLE001 — a clamp that cannot read its floors is absent, not fatal
        logger.warning("critic floor clamp: prescription gate failed (%s) — no clamp this run", e)
        return None
    movements = (gate.get("load_floors") or {}).get("movements") or {}
    if not gate.get("enforced") or not movements:
        return None
    n_back_offs, _ = _n_back_offs(None)

    def floors_of(ex: Any) -> list:
        return set_floors_kg(ex, movements.get(getattr(ex, "movement_key", None) or "?") or {}, n_back_offs)

    return floors_of


def _fmt(kg: Any) -> str:
    from training.routine_generator import _fmt_load

    return _fmt_load(float(kg))


def _provenance(gate: dict[str, Any], v: dict[str, Any]) -> str:
    """Where this floor came from — a load, a date, a bodyweight, a band.

    Without it the refusal is "your number is too low", which Matthew cannot act on at
    11pm. With it he can check the claim against his own log in one glance.
    """
    floors = gate.get("load_floors") or {}
    movement = (floors.get("movements") or {}).get(v.get("where")) or {}
    basis = v.get("basis") or movement.get("basis") or {}
    bits: list[str] = []
    if basis:
        reps = "/".join(str(r) for r in (basis.get("reps") or []))
        bits.append(f"floor from {_fmt(basis.get('weight_kg') or 0)}{f' x {reps}' if reps else ''} on {basis.get('date')}")
        if basis.get("bodyweight_lb") is not None:
            bits.append(f"at {basis['bodyweight_lb']} lb")
    if floors.get("band"):
        bits.append(f"band {floors['band']}")
    if movement.get("layoff_reason"):
        bits.append(str(movement["layoff_reason"]))
    bits.append(f"floors source={floors.get('source', '?')}, status={floors.get('status', '?')}")
    return "; ".join(bits)


def refusal_message(gate: dict[str, Any] | None) -> str | None:
    """The commit refusal, or None. Names the clause or the set — never just the verdict."""
    if not gate or gate.get("verdict") != "refuse":
        return None
    lines: list[str] = []
    for v in (gate.get("audit") or {}).get("violations") or []:
        if v.get("kind") == "conditional_up":
            lines.append(
                f"conditional up-branch in {v.get('where')} [{v.get('pattern')}]: \"{v.get('clause')}\" "
                f"(matched {v.get('match')!r}) — progression is the platform's job, never his to trigger mid-set at 5am"
            )
        else:
            lines.append(
                f"{v.get('where')} set {v.get('set')} prescribes {_fmt(v.get('prescribed_kg'))} "
                f"against a floor of {_fmt(v.get('floor_kg'))} — {_provenance(gate, v)}"
                + (f" — not a prescribed back-off: {v['back_off_note']}" if v.get("back_off_note") else "")
            )
    return (
        f"Refusing to commit — subtract-only violation (#3927/#3971), {len(lines)} finding(s): "
        + " | ".join(lines)
        + f" || Rule: {gate.get('rule')} || Fix the draft (re-run draft_custom) and commit again — "
        "the gate is not overridable from chat."
    )


def summary(gate: dict[str, Any] | None) -> str:
    """One line for the commit/dry_run result: what the gate did, in the result itself."""
    if not gate:
        return "subtract-only gate: not run"
    if gate.get("verdict") == "skipped":
        return gate.get("skipped_reason") or "subtract-only gate: skipped"
    floors = gate.get("load_floors") or {}
    movements = floors.get("movements") or {}
    with_floor = sum(1 for m in movements.values() if m.get("floor_kg"))
    reason = f" ({floors['reason']})" if floors.get("reason") else ""
    audit = gate.get("audit") or {}
    return (
        f"subtract-only gate: {'clean' if gate.get('verdict') == 'clean' else 'REFUSED'} — "
        f"load_floors status={floors.get('status', '?')}{reason}, source={floors.get('source', '?')}, "
        f"{with_floor}/{len(movements)} movement(s) carry a band-matched floor; "
        f"conditional-up scan ran on routine notes + every exercise note, "
        f"{len(audit.get('violations') or [])} violation(s), floors_checked={audit.get('floors_checked')}, "
        f"{audit.get('back_offs_checked', 0)} back-off set(s) held to their back-off floor "
        f"(rep scheme {(audit.get('back_off_scheme') or {}).get('status', '?')}, #4065/#4090)"
    )
