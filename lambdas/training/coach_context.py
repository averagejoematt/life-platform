"""coach_context.py — ONE context assembly for every planning surface, and the tool-call order contract (#5071, epic #5067).

WHY THIS EXISTS
  Before this, each planning surface assembled its own context: the chat skills, the Telegram
  coach, the nightly pre-draft, the four plan critics and the physical_coach persona each read
  (or hand-copied) a different slice of the charter, the clinical guidance and the plan inputs.
  ``assemble()`` is the one function they all read, so every planning conversation starts from
  the same context and every plan can explain itself in May-target terms (``may_frame``).

WHAT IT IS
  PURE and DETERMINISTIC: no DynamoDB, no clock, no model. The caller hands in what it already
  read (the coach-session packet, the stage-1 constraint block, the clinical guidance, the May
  tracker); the only read here is the charter, through ``training_charter`` (bundled config,
  cached). It calls no model, so it carries no budget feature and no route (#5084 states that
  as a test: tests/test_charter_ai_budget_5084.py).

  Every section carries the ``source`` it was read from. A section the caller did not supply is
  ``not_supplied`` with that said in words — never an invented value (ADR-104).

THE CLINICAL GUIDANCE IS REFERENCE CONTEXT, NEVER A GATE
  It is rendered by ``health.clinical_facts`` (the one renderer): ``published=True`` gives the
  neutral guardrails only, ``published=False`` the owner-channel record. Nothing in this module
  branches on it.

PUBLISHED vs OWNER
  ``published=True`` (any surface whose output can reach a reader): the charter's
  ``public_view()`` only, the guardrails-only clinical block, and NO ``may_frame`` — the May
  target never reaches a published surface (owner ruling 2026-10-18, and NEVER_PUBLISHED in
  training_charter). ``published=False`` (the default here: every current caller is an owner
  channel — the MCP chat, the owner's Telegram thread, the pre-draft, the critics' Hevy notes).

THE ORDER CONTRACT (``ORDER`` / ``order_violations``)
  Every planning conversation runs: pre-flight (exercise history, exercise notes, the clinical
  guidance, the charter, the May tracker) -> ``plan_next_session`` -> ``manage_hevy_routine``
  draft. The clinical guidance, the charter and the May tracker arrive TOGETHER, as this
  module's context on ``get_coach_session_packet`` — so the packet is the pre-flight call that
  satisfies those three members (``PRE_FLIGHT``). ``order_violations`` checks a transcript's
  tool-call sequence against the contract; tests/test_coach_context_5071.py runs it over three
  real planning conversations (tests/fixtures/coach_transcripts_5071/).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

CONTEXT_VERSION = "coach-context@1.5.0"  # 1.5.0 #5111: lab_followup (the next draw, owner channel); 1.4.0 #5200: the May tracker read on every caller path + not_supplied_reason; 1.3.0 #5111: lab_priorities (owner channel, seam only); 1.1.0 #5059: clinical_guidance.freshness (owner channel, reference only); 1.2.0 #5090: run_gate

# ── the order contract, as data ───────────────────────────────────────────────────────────
ORDER: tuple[str, ...] = ("pre_flight", "plan_next_session", "manage_hevy_routine draft")

# Each pre-flight member and the tool calls that satisfy it. The clinical guidance, the charter and
# the May tracker have no tool of their own: they ride this module's context on the packet.
PRE_FLIGHT: dict[str, tuple[str, ...]] = {
    "exercise_history": ("get_exercise_history",),
    "exercise_notes": ("get_exercise_notes",),
    "clinical_guidance": ("get_coach_session_packet",),
    "charter": ("get_coach_session_packet",),
    "may_tracker": ("get_coach_session_packet",),
}
DRAFT_ACTIONS: frozenset[str] = frozenset({"draft", "draft_custom"})

# ── section sources (every number in the context is labelled with one of these) ──────────────
SRC_CHARTER = "config/training_charter.json (training.training_charter)"
SRC_PANEL = "config/training_charter.json concession_ledger (the panel synthesis)"
SRC_GUIDANCE = "USER#matthew#SOURCE#clinical GUIDANCE#current via health.clinical_facts (reference context, never a gate)"
SRC_PACKET = "get_coach_session_packet (mcp.tools_coach_packet)"
SRC_BLOCK = "plan_next_session stage 1 (training.plan_engine.constraint_block)"
SRC_TRACKER = "the May tracker (#5073)"
SRC_MAY = "config/training_charter.json governing_goal.target_date (owner-only)"
SRC_RUN_GATE = "training.run_onramp.gate_state (the May tracker's running_gate, #5090)"

NOT_SUPPLIED = "not_supplied"
_VALUE_CHARS = 160  # one packet value in the text block is clipped here; the dict keeps it whole


# ── the charter summary ──────────────────────────────────────────────────────────────────
def _charter_summary(published: bool) -> dict[str, Any]:
    """The charter as code reads it. Published: the whitelist. Owner: the planning keys of the public half."""
    from training import training_charter as tc  # noqa: PLC0415 — lazy, keeps the module import-light

    if published:
        return tc.public_view()
    keys = ("version", "split", "steps", "deload", "effort_ceilings", "progression", "cardio_menu", "volume_priorities", "disruption")
    out = {k: tc.charter_value(k) for k in keys}
    out["rate_band_lb_per_wk"] = tc.charter_value("governing_goal.rate_band_lb_per_wk")
    out["target_date"] = tc.charter_value("governing_goal.target_date")
    return {k: v for k, v in out.items() if v is not None}


def charter_section(published: bool = False) -> dict[str, Any]:
    """The charter section alone — what the four critics read (``critic_charter``)."""
    from training import training_charter as tc  # noqa: PLC0415

    summary = _charter_summary(published)
    return {
        "source": SRC_CHARTER,
        "charter_version": tc.charter_version(),
        "state": "measured" if summary else "absent",
        "summary": summary,
    }


def _panel_section(published: bool) -> dict[str, Any]:
    from training import training_charter as tc  # noqa: PLC0415

    ledger = (tc.public_view() if published else {"concession_ledger": tc.charter_value("concession_ledger")}).get("concession_ledger")
    return {"source": SRC_PANEL, "state": "measured" if ledger else "absent", "concessions": ledger or {}}


def _freshness_view(flag: Any, published: bool) -> Optional[dict[str, Any]]:
    """#5059: the guidance record's freshness flag (`health.guidance_freshness`), carried as reference on the
    owner channel only — a published context omits it (its guidance header names no record). None = not supplied."""
    if published or not isinstance(flag, dict):
        return None
    return {k: flag.get(k) for k in ("state", "guidance_effective", "latest_appointment_date", "prompt", "role")}


def _guidance_section(guidance: Any, published: bool, freshness: Any = None) -> dict[str, Any]:
    """`guidance` is the clinical partition's rows (rendered here by the one renderer) or an
    already-rendered block. None = the caller read none. `freshness` (#5059) rides the section as reference."""
    sec = _guidance_body(guidance, published)
    view = _freshness_view(freshness, published)
    if view is not None:
        sec["freshness"] = view
    return sec


def _guidance_body(guidance: Any, published: bool) -> dict[str, Any]:
    if guidance is None:
        return {"source": SRC_GUIDANCE, "state": NOT_SUPPLIED, "text": "", "detail": "the caller supplied no clinical guidance"}
    if isinstance(guidance, dict):  # the caller's read broke: {"state": "read_failed", "error": <class>}
        return {"source": SRC_GUIDANCE, "state": guidance.get("state") or "read_failed", "text": "", "detail": guidance.get("error")}
    if isinstance(guidance, str):
        text = guidance.strip()
    else:
        from health.clinical_facts import render_clinical_block  # noqa: PLC0415

        text = render_clinical_block(list(guidance), published=published)
    return {"source": SRC_GUIDANCE, "state": "measured" if text else "absent", "text": text, "role": "reference"}


def _packet_section(packet: Optional[dict[str, Any]], reason: Optional[str] = None) -> dict[str, Any]:
    if not isinstance(packet, dict) or not isinstance(packet.get("fields"), dict):
        return {
            "source": SRC_PACKET,
            "state": NOT_SUPPLIED,
            "fields": {},
            "detail": reason or "this caller read no plan packet (get_coach_session_packet carries it in a planning chat)",
        }
    fields = {
        name: {"state": (f or {}).get("state"), "source": (f or {}).get("source"), "value": (f or {}).get("value")}
        for name, f in packet["fields"].items()
    }
    return {"source": f"{SRC_PACKET} {packet.get('packet_version') or ''}".strip(), "state": "measured", "fields": fields}


_BLOCK_KEYS = ("session", "program_week", "rate_target", "steps_ramp", "deload_recommendation", "block_model", "tripped", "charter_version")


def _block_section(block: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(block, dict) or not block:
        return {
            "source": SRC_BLOCK,
            "state": NOT_SUPPLIED,
            "detail": "no constraint block in this context (plan_next_session builds it after pre-flight)",
        }
    return {"source": SRC_BLOCK, "state": "measured", **{k: block.get(k) for k in _BLOCK_KEYS if k in block}}


_TRACKER_ENVELOPE_STATES = frozenset({"measured", "stale", "absent", "read_failed"})


def _tracker_steps(row: dict) -> str:
    st = row.get("steps") or {}  # steps-truth: the May tracker row's steps, resolved by training.steps_resolver when written
    return f"{st.get('value')} ({st.get('state')})"


def _tracker_section(tracker: Any) -> dict[str, Any]:
    """`tracker` is `may_tracker.latest_completed_row`'s `{state, row}` envelope (#5200), a bare week row, or None
    (the caller read none). A stored week is supplied (`measured`, or `stale` with the gap said); no stored week is
    not_supplied with that said; a broken read is `read_failed` with its class — never an empty tracker."""
    if tracker is None:
        return {
            "source": SRC_TRACKER,
            "state": NOT_SUPPLIED,
            "detail": "this caller read no May tracker; nothing here stands in for one",
        }
    env = isinstance(tracker, dict) and tracker.get("state") in _TRACKER_ENVELOPE_STATES and "row" in tracker
    row, state = (tracker.get("row"), tracker["state"]) if env else (tracker, "measured")
    sec: dict[str, Any] = {"source": SRC_TRACKER, "state": state}
    if state in ("absent", "read_failed") or not row:
        sec["state"] = "read_failed" if state == "read_failed" else NOT_SUPPLIED
        sec["detail"] = (tracker.get("error") if state == "read_failed" else tracker.get("detail")) or "no May-tracker week is stored"
        return sec
    sec["value"] = row
    if isinstance(row, dict) and row.get("week_start"):
        sec["week_start"] = row["week_start"]
    if env and tracker.get("detail"):
        sec["detail"] = tracker["detail"]
    return sec


def _tracker_rows(tr: dict[str, Any]) -> list[tuple[str, Any]]:
    """The tracker week as prompt lines: the trajectory, the steps and every fired trigger WITH its lever."""
    row = tr.get("value")
    if not isinstance(row, dict) or not row.get("week_start"):
        return [("value", row)]
    w, trig = row.get("weight") or {}, row.get("triggers") or {}
    rate = w.get("rate_week") or {}
    out: list[tuple[str, Any]] = [
        ("week", f"{row.get('week_start')}..{row.get('week_end')} (charter v{row.get('charter_version')})"),
        (
            "rate",
            f"{rate.get('value')} lb/wk ({rate.get('pct_bodyweight_per_wk')}% of bodyweight); band position {w.get('band_position_week')}",
        ),
        ("steps", _tracker_steps(row)),
        ("status", trig.get("status")),
    ]
    out += [(f"trigger {t.get('id')} ({t.get('level')})", f"{t.get('condition')} -> {t.get('lever')}") for t in trig.get("fired") or []]
    if trig.get("unevaluated"):
        out.append(("unevaluated", ", ".join(str(u.get("id")) for u in trig["unevaluated"])))
    if tr.get("detail"):
        out.append(("note", tr["detail"]))
    return out


def run_gate(tracker: Any) -> dict[str, Any]:
    """#5090: the run gate line (owner channel). Measured from the tracker row's `running_gate` when one is supplied
    (a row, or `may_tracker.latest_row`'s `{state, row}`); otherwise the charter's rule, stated as not supplied."""
    from training import run_onramp  # noqa: PLC0415

    row = tracker.get("row") if isinstance(tracker, dict) and "row" in tracker else tracker
    rg = row.get("running_gate") if isinstance(row, dict) else None
    if isinstance(rg, dict) and rg.get("line"):
        return {"source": SRC_RUN_GATE, "state": "measured", "gate_state": rg.get("gate_state"), "line": rg["line"]}
    return {"source": SRC_RUN_GATE, "state": NOT_SUPPLIED, "gate_state": None, "line": run_onramp.rule_line()}


# ── the May frame (owner-only) ───────────────────────────────────────────────────────────
def _band_of(block: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return (((block or {}).get("rate_target") or {}).get("band")) or None


def may_frame(target_date: str, block: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Weeks from `target_date` to the charter's target date, and the rate band in lb AND %BW when a
    weight is known (the block's guidance-capped band). Derived from the arguments, never the clock.
    None when the charter or the date cannot be read."""
    from common.pacific_time import parse_day_key  # noqa: PLC0415 — THE calendar-day parse (#3741); no clock is read

    from training import training_charter as tc  # noqa: PLC0415

    target = tc.charter_value("governing_goal.target_date")
    end, start = parse_day_key(str(target)), parse_day_key(str(target_date)[:10])
    if end is None or start is None:
        return None
    days = (end - start).days
    weeks = round(days / 7, 1)
    band = _band_of(block)
    raw = tc.charter_value("governing_goal.rate_band_lb_per_wk") or {}
    if band:
        rate = (
            f"{band['floor_lb_wk']:.1f}-{band['ceiling_lb_wk']:.1f} lb/wk "
            f"({band['floor_pct_bodyweight_per_wk']:g}-{band['ceiling_pct_bodyweight_per_wk']:g}% of bodyweight at {band['weight_lb']:g} lb"
            + (", capped by the clinical guidance" if band.get("guidance_capped") else "")
            + ")"
        )
    elif raw.get("floor") is not None:
        rate = f"{raw['floor']:.1f}-{raw['ceiling']:.1f} lb/wk (% of bodyweight needs a weight; none was supplied)"
    else:
        rate = "unknown (the charter's rate band could not be read)"
    line = (
        f"May frame: {target_date} is {weeks:g} weeks before the {target} target; the loss-rate band is {rate}. "
        "Every session in this plan is judged by whether it protects muscle and holds the band through that date, "
        f"{_phase_one_clause()}"
    )
    return {
        "source": SRC_MAY,
        "target_date": target,
        "weeks_to_target": weeks,
        "days_to_target": days,
        "rate_band": band or raw,
        "line": line,
    }


def _phase_one_clause() -> str:
    """#5130: the date ends phase one, a milestone with a plan after it — read from the charter, and whether the
    post-deadline plan is written yet (`phase_after_may.plan`), so the frame never reads as a finish line."""
    from training import training_charter as tc  # noqa: PLC0415

    written = bool(tc.charter_value("phase_after_may.plan"))
    return "which ends phase one: a milestone, not a finish line (phase_after_may); " + (
        "the plan after it is in the charter's phase_after_may.plan." if written else "the plan after it is not written yet."
    )


# ── the one assembly ─────────────────────────────────────────────────────────────────────
def assemble(
    target_date: str,
    *,
    packet: Optional[dict[str, Any]],
    constraint_block: Optional[dict[str, Any]],
    tracker: Any = None,
    guidance: Any = None,
    guidance_freshness: Any = None,
    lab_priorities: Optional[dict[str, Any]] = None,
    lab_followup: Optional[dict[str, Any]] = None,
    published: bool = False,
    packet_reason: Optional[str] = None,
) -> dict[str, Any]:
    """The planning context for `target_date`: a dict for code and ``text`` for a prompt.

    ``published=False`` is the owner channel (the may_frame and the owner-channel clinical block);
    pass True from any surface whose output can reach a reader."""
    from training import training_charter as tc  # noqa: PLC0415

    sections = {
        "charter": charter_section(published),
        "panel_synthesis": _panel_section(published),
        "clinical_guidance": _guidance_section(guidance, published, guidance_freshness),
        "plan_packet": _packet_section(packet, packet_reason),
        "constraint_block": _block_section(constraint_block),
        "may_tracker": {"source": "omitted", "state": "omitted_published"} if published else _tracker_section(tracker),
    }
    frame = None if published else may_frame(target_date, constraint_block)
    out: dict[str, Any] = {
        "context_version": CONTEXT_VERSION,
        "target_date": target_date,
        "charter_version": tc.charter_version(),
        "published": published,
        "order": list(ORDER),
        "sections": sections,
        "may_frame": frame,
        "run_gate": None if published else run_gate(tracker),
        "lab_priorities": None if published else lab_priorities,  # #5111: owner-only; absent -> nothing is said
        "lab_followup": None if published else lab_followup,  # #5111: the next draw's date + state (training.lab_priorities.read)
        "not_supplied": sorted(k for k, s in sections.items() if s.get("state") == NOT_SUPPLIED),
    }
    out["not_supplied_reason"] = {k: sections[k].get("detail") for k in out["not_supplied"]}  # #5200: each absence says why
    out["text"] = render(out)
    return out


def summary(ctx: dict[str, Any]) -> dict[str, Any]:
    """The compact form a payload carries beside its own data (the text block is the AI-facing form)."""
    return {
        "context_version": ctx.get("context_version"),
        "charter_version": ctx.get("charter_version"),
        "states": {k: s.get("state") for k, s in (ctx.get("sections") or {}).items()},
        "not_supplied": ctx.get("not_supplied"),
        "not_supplied_reason": ctx.get("not_supplied_reason"),
        "may_tracker_week": ((ctx.get("sections") or {}).get("may_tracker") or {}).get("week_start"),
        "may_frame": (ctx.get("may_frame") or {}).get("line"),
        "run_gate": (ctx.get("run_gate") or {}).get("line"),
        "lab_followup": (ctx.get("lab_followup") or {}).get("line"),
        "order": ctx.get("order"),
        "text": ctx.get("text"),
    }


# ── rendering ────────────────────────────────────────────────────────────────────────────
def _clip(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str, sort_keys=True, separators=(",", ":"))
    return s if len(s) <= _VALUE_CHARS else s[: _VALUE_CHARS - 1] + "…"


# The charter paths the text block states (the full charter, ~7.7k tokens, is the AI callers' cached
# system block — ``training_charter.prompt_prefix`` via ``charter_ai.system_blocks`` — never re-sent per call here).
CHARTER_HEADLINES: tuple[str, ...] = (
    "split.sequence",
    "split.lifting_days_per_wk",
    "split.session_minutes",
    "split.frequency",
    "steps.floor",
    "steps.target",
    "deload.scheduled",
    "deload.automatic",
    "deload.applied_only_on",
    "effort_ceilings.by_movement_class",
    "progression.gain_rule.kind",
    "progression.gain_rule.size",
    "volume_priorities.sets_per_wk",
    "cardio_menu.default",
    "rate_band_lb_per_wk.floor",
    "rate_band_lb_per_wk.ceiling",
    "target_date",
)


def _dig(d: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def headlines(section: dict[str, Any]) -> dict[str, Any]:
    """The ``CHARTER_HEADLINES`` values present in a charter section's summary, by dotted path."""
    rows = ((p, _dig(section.get("summary") or {}, p)) for p in CHARTER_HEADLINES)
    return {p: v for p, v in rows if v is not None}


def _render_charter(sec: dict[str, Any]) -> list[str]:
    lines = [f"CHARTER v{sec.get('charter_version')} [{sec['source']}]"]
    if sec["state"] != "measured":
        return lines + ["- the charter could not be read: plan with no charter and say so"]
    return lines + [f"- {p}: {_clip(v)}" for p, v in headlines(sec).items()]


def _render_panel(sec: dict[str, Any]) -> list[str]:
    lines = [f"PANEL SYNTHESIS — what each school concedes to the deadline [{sec['source']}]"]
    for school, c in sorted((sec.get("concessions") or {}).items()):
        lines.append(f"- {school}: concedes {(c or {}).get('concedes')}; in return {(c or {}).get('in_return')}")
    return lines if len(lines) > 1 else lines + ["- absent"]


def _render_fields(title: str, sec: dict[str, Any], rows: Iterable[tuple[str, Any]]) -> list[str]:
    lines = [f"{title} [{sec['source']}]"]
    if sec.get("state") == NOT_SUPPLIED:
        return lines + [f"- not supplied: {sec.get('detail') or 'the caller passed none'}"]
    return lines + [f"- {k}: {_clip(v)}" for k, v in rows]


def _render_guidance(g: dict[str, Any], published: bool) -> list[str]:
    # A published prompt names no record: the guardrails' own header (health.clinical_facts) is the whole of it.
    head = (
        "COACHING GUARDRAILS [owner instructions]"
        if published
        else f"CLINICAL GUIDANCE — reference context, not a gate on intensity [{g['source']}]"
    )
    lines = [head, g.get("text") or f"- {g['state']}"]
    fr = g.get("freshness")
    if fr:  # #5059: reference only — says whether to load the latest instructions, never shapes the plan
        lines.append(f"- record freshness: {fr.get('state')}" + (f" — {fr['prompt']}" if fr.get("prompt") else ""))
    return lines


def _render_labs(ctx: dict[str, Any]) -> list[list[str]]:
    """#5111: the owner's lab-driven priorities and the next follow-up draw — owner channel only; absent says nothing."""
    if ctx.get("published"):
        return []
    parts: list[list[str]] = []
    lp = ctx.get("lab_priorities")
    if lp and lp.get("text"):  # the owner's own priorities, from his owner-only record (training.lab_priorities)
        parts.append([f"LAB-DRIVEN PRIORITIES (owner-only) [{lp.get('source')}]", lp["text"]])
    fu = ctx.get("lab_followup")
    if fu and fu.get("line"):  # the calibration cadence's lab_draw row: dates and a state, never a result
        parts.append([f"LAB FOLLOW-UP (owner-only) [{fu.get('source')}]", f"- {fu['line']}"])
    return parts


def render(ctx: dict[str, Any]) -> str:
    """The text block for a prompt: every section headed with its source; absence stated."""
    s = ctx["sections"]
    parts: list[list[str]] = [_render_charter(s["charter"]), _render_panel(s["panel_synthesis"])]
    parts.append(_render_guidance(s["clinical_guidance"], ctx["published"]))
    pk = s["plan_packet"]
    parts.append(
        _render_fields(
            "PLAN PACKET",
            pk,
            ((n, f"{f.get('state')} — {_clip(f.get('value'))} ({f.get('source')})") for n, f in (pk.get("fields") or {}).items()),
        )
    )
    cb = s["constraint_block"]
    parts.append(_render_fields("CONSTRAINT BLOCK", cb, ((k, cb[k]) for k in _BLOCK_KEYS if k in cb)))
    tr = s["may_tracker"]
    if not ctx["published"]:  # the May target never reaches a published prompt (owner ruling 2026-10-18)
        parts.append(
            _render_fields(
                "MAY TRACKER", tr, _tracker_rows(tr) if "value" in tr else [("state", f"{tr.get('state')} — {tr.get('detail')}")]
            )
        )
    if ctx.get("may_frame"):
        parts.append([f"MAY FRAME (owner-only) [{ctx['may_frame']['source']}]", ctx["may_frame"]["line"]])
    if ctx.get("run_gate"):  # #5090: owner channel only (assemble sets None when published)
        rg = ctx["run_gate"]
        parts.append([f"RUN GATE (owner-only) [{rg['source']}; {rg['state']}]", rg["line"]])
    parts.extend(_render_labs(ctx))
    if not ctx["published"]:  # the order contract is the owner's planning conversation's, never a reader prompt's
        parts.append(["ORDER: " + " -> ".join(ctx["order"]) + " (pre-flight = " + ", ".join(PRE_FLIGHT) + ")"])
    return "\n\n".join("\n".join(p) for p in parts)


# ── the nutrition coach's context (#5109, epic #5094) ───────────────────────────────────
# The nutrition coach (the daily brief's `nutrition_coach`, `coach.coach_input_facts.coach_inputs`) reads the SAME
# assembly: the charter's nutrition block, the redlines' nutrition rules, the ONE calorie target with its provenance,
# and the protein engine's and the macro floors' grade of the data day. Before this it read none of them: its persona
# carried example numbers that predated the charter and its only target was the system prompt's stale protein line.
# PURE like `assemble`: the caller hands in the MacroFactor day row it already read; the resolver's own titration read
# (inside a Lambda, cached) is the one I/O, and a failure there is a stated absence.
NUTRITION_CONTEXT_VERSION = "nutrition-context@1.1.0"  # 1.1.0 #5111: lab_priorities + lab_followup (owner channel)
SRC_NUTRITION = "config/training_charter.json nutrition (training.training_charter)"
SRC_REDLINES = "training.owner_redlines REDLINES (the nutrition rules; values read from the charter)"
SRC_CALORIE = "health.calorie_target.resolve (the ONE calorie target: titration, else the charter)"
SRC_PROTEIN = "health.protein_engine.evaluate_day (#5098)"
SRC_FLOORS = "health.macro_floors.evaluate_day (#5102)"

# The charter nutrition paths a PUBLISHED nutrition context states. Not on `PUBLISHED_WHITELIST` (that list is what
# the site renders of the charter); each is a daily figure the coach grades a logged day against. Never a
# `NEVER_PUBLISHED` prefix (tests/test_nutrition_coach_context_5109.py).
NUTRITION_PUBLISHED_PATHS: tuple[str, ...] = (
    "nutrition.protein.range_g.low",
    "nutrition.protein.range_g.high",
    "nutrition.protein.days_of_7",
    "nutrition.protein.feedings_per_day",
    "nutrition.protein.feeding_threshold_g",
    "nutrition.protein.feeding_target_g",
    "nutrition.calories.floor_any_day_kcal",
    "nutrition.calories.floor_lifting_day_kcal",
    "nutrition.floors.fat.floor_g",
    "nutrition.floors.carb.floor_g",
    "nutrition.floors.fibre.floor_g",
    "nutrition.floors.fibre.target_range_g",
)
# Owner channel only: the opening band, the reported 7-day floor and the training-day rule (its `surface` is owner-only).
NUTRITION_OWNER_PATHS: tuple[str, ...] = (
    "nutrition.calories.prescribed_band_kcal",
    "nutrition.calories.floor_7d_mean_kcal",
    "nutrition.training_day.lifting_uplift_kcal",
)
# The redlines' nutrition rules: (REDLINES key, the fields a context states). Notes and derivations are not rules.
REDLINE_NUTRITION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("energy_floor_kcal", ("floor_any_day", "floor_lifting_day", "floor_7d_mean")),
    ("protein_floor_g", ("value", "target_g", "days_of_7", "feedings", "feeding_g", "timing")),
    ("fat_floor_g", ("value",)),
    ("carb_floor_g", ("value",)),
)
# The calorie resolver fields a published context carries: the kcal and where it came from, never the titration
# record's reason or band (USER#…#SOURCE#nutrition_titration is TIER_OWNER_ONLY, privacy.field_tiers).
_CALORIE_PUBLISHED_KEYS = ("kcal", "base_kcal", "resolved_from", "floor_any_day_kcal", "floor_lifting_day_kcal", "charter_version")
_CALORIE_OWNER_KEYS = _CALORIE_PUBLISHED_KEYS + ("band_low", "band_high", "provenance", "week", "day_type", "uplift_kcal")
# The protein engine's day fields a published context carries: counts, never the feedings' clock times.
_PROTEIN_PUBLISHED_KEYS = ("date", "total_g", "range_low", "range_high", "hit", "feedings_40g", "feedings_target", "charter_version")

NUTRITION_CITE_RULE = (
    "Cite a calorie or protein target, floor or day total only from this context or from logging_record; "
    "a figure that is in neither is not one any engine serves: leave it out."
)


def _charter_nutrition(published: bool) -> dict[str, Any]:
    from training import training_charter as tc  # noqa: PLC0415

    paths = NUTRITION_PUBLISHED_PATHS + (() if published else NUTRITION_OWNER_PATHS)
    values = {p: tc.charter_value(p) for p in paths}
    values = {p: v for p, v in values.items() if v is not None}
    return {"source": SRC_NUTRITION, "charter_version": tc.charter_version(), "state": "measured" if values else "absent", "values": values}


def _redline_rules() -> dict[str, Any]:
    from training import owner_redlines  # noqa: PLC0415

    rules = {}
    for key, fields in REDLINE_NUTRITION_RULES:
        rec = owner_redlines.REDLINES.get(key) or {}
        rules[key] = {f: rec.get(f) for f in fields if rec.get(f) not in (None, [], "", 0)}
    return {"source": SRC_REDLINES, "version": owner_redlines.REDLINES_VERSION, "state": "measured", "rules": rules}


def _public_provenance(cal: dict[str, Any]) -> str:
    if cal.get("source") == "titration":
        return "the week's titration record (health.titration); the charter's energy floors are warnings, never a clamp"
    return str(cal.get("provenance") or "")


def _calorie_section(target_date: str, published: bool, calorie: Optional[dict[str, Any]]) -> dict[str, Any]:
    if calorie is None:
        from health.calorie_target import resolve  # noqa: PLC0415

        calorie = resolve(target_date)
    keys = _CALORIE_PUBLISHED_KEYS if published else _CALORIE_OWNER_KEYS
    calorie = {**calorie, "resolved_from": calorie.get("source")}  # the resolver's `source`; the section's is SRC_CALORIE
    out = {k: calorie.get(k) for k in keys if k in calorie}
    if published:
        out["provenance"] = _public_provenance(calorie)
    return {"source": SRC_CALORIE, "state": "measured" if calorie.get("kcal") is not None else "absent", **out}


def _day_sections(row: Optional[dict[str, Any]], published: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    from health import macro_floors, protein_engine  # noqa: PLC0415

    if not isinstance(row, dict) or not row:
        absent = {"state": NOT_SUPPLIED, "detail": "no MacroFactor day row was supplied: the day is unknown, never a miss"}
        return {"source": SRC_PROTEIN, **absent}, {"source": SRC_FLOORS, **absent}
    day = protein_engine.evaluate_day(row)
    protein = {k: day.get(k) for k in _PROTEIN_PUBLISHED_KEYS} if published else dict(day)
    return {"source": SRC_PROTEIN, "state": "measured", **protein}, {
        "source": SRC_FLOORS,
        "state": "measured",
        "date": row.get("date"),
        **macro_floors.evaluate_day(row),
    }


def nutrition_context(
    target_date: str,
    *,
    day_row: Optional[dict[str, Any]] = None,
    calorie: Optional[dict[str, Any]] = None,
    published: bool = True,
    lab_priorities: Optional[dict[str, Any]] = None,
    lab_followup: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The nutrition coach's context for `target_date` (#5109): a dict for code and ``text`` for a prompt.

    ``published=True`` (the DEFAULT: the daily brief's nutrition text reaches /api/coaching-dashboard) carries
    ``NUTRITION_PUBLISHED_PATHS``, the redlines' rules, the resolver's kcal and its public provenance, and the
    engines' grade of `day_row` without clock times. ``published=False`` (the owner's Telegram thread) adds the
    owner-only paths, the resolver's band and provenance and the feedings' times. `calorie` is a resolver result the
    caller already holds (tests); None resolves it here. `lab_priorities` / `lab_followup` (#5111, `training.lab_priorities.read`)
    ride the owner channel only: a published context drops both."""
    from training import training_charter as tc  # noqa: PLC0415

    protein, floors = _day_sections(day_row, published)
    sections = {
        "charter_nutrition": _charter_nutrition(published),
        "redlines": _redline_rules(),
        "calorie_target": _calorie_section(target_date, published, calorie),
        "protein_day": protein,
        "floors_day": floors,
    }
    out: dict[str, Any] = {
        "context_version": NUTRITION_CONTEXT_VERSION,
        "target_date": target_date,
        "charter_version": tc.charter_version(),
        "published": published,
        "sections": sections,
        "rule": NUTRITION_CITE_RULE,
        "lab_priorities": None if published else lab_priorities,
        "lab_followup": None if published else lab_followup,
    }
    out["served_figures"] = served_figures(out)
    out["text"] = render_nutrition(out)
    return out


def charter_goal_lines() -> str:
    """The daily coaches' standing training + priorities lines (`ai.ai_calls._run_coach_v2_pipeline`'s system prompt),
    read from the charter (#5109). They were typed into the prompt before the charter existed (a 190 g protein target
    and an 8,000-step line the charter never set, and strength training "planned but not yet started"). The steps and
    the split come from `public_view()` (the prompt's output is published); the protein range is a daily figure the
    published nutrition context states (`NUTRITION_PUBLISHED_PATHS`). An unreadable charter says so in words."""
    from training import training_charter as tc  # noqa: PLC0415

    pv = tc.public_view()
    split, steps = pv.get("split") or {}, pv.get("steps") or {}  # steps-truth: the charter's steps TARGETS, not a reading
    lo, hi = tc.charter_value("nutrition.protein.range_g.low"), tc.charter_value("nutrition.protein.range_g.high")
    days = tc.charter_value("nutrition.protein.days_of_7")
    if not (split.get("sequence") and steps.get("floor") and lo and hi):
        return "- Training and priorities: the training charter could not be read; state no target from memory"
    return (
        f"- Training: {split.get('lifting_days_per_wk')} lifting days a week in the sequence {', '.join(split['sequence'])}, plus daily walking\n"
        f"- Key priorities: sleep quality, protein adherence (at or above the {lo:g} g floor on {days} of 7 days; range {lo:g}-{hi:g} g), "
        f"consistent movement ({steps['floor']:,} steps/day floor, {steps.get('target'):,} target)\n"
        f"{wake_time_line()}"
    )


WAKE_RULE_KEYS = ("rule", "tolerance_minutes", "anchor_window_days", "min_days_for_anchor", "every_day", "weekends_included", "hit")


def wake_time_rule() -> Optional[dict[str, Any]]:
    """#5133: the charter's wake-time consistency rule (`sleep.wake_time`) as the coaches read it — the rule and its
    numbers, never a clock time (the anchor is his own trailing median, computed by `health.wake_consistency`, the one
    grader). Published-safe: the fields are on `PUBLISHED_WHITELIST`. None when the charter does not carry it."""
    from training import training_charter as tc  # noqa: PLC0415

    sec = (tc.public_view().get("sleep") or {}).get("wake_time") or {}
    out = {k: sec[k] for k in WAKE_RULE_KEYS if k in sec}
    if not out.get("tolerance_minutes") or not out.get("anchor_window_days"):
        return None
    return {"source": "config/training_charter.json sleep.wake_time (graded by health.wake_consistency)", **out}


def wake_time_line() -> str:
    """The daily coaches' standing sleep line (#5133), from `wake_time_rule()`; an unreadable rule says so in words."""
    r = wake_time_rule()
    if r is None:
        return "- Sleep: the charter's wake-time rule could not be read; state no wake target from memory"
    return (
        f"- Sleep: a consistent wake time, out of bed within {r['tolerance_minutes']} min of his own median wake time over the "
        f"trailing {r['anchor_window_days']} days, every day including weekends (charter sleep.wake_time; a day with no sleep "
        "record is unknown, never a miss)"
    )


def _numbers(v: Any) -> list[float]:
    if isinstance(v, bool) or v is None:
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    if isinstance(v, (list, tuple)):
        return [x for item in v for x in _numbers(item)]
    return []


def served_figures(ctx: dict[str, Any]) -> dict[str, list[float]]:
    """``{"calories": [...], "protein_g": [...], "fiber_g": [...]}`` — every target, floor and day figure this
    context serves, by the plan-figure gate's quantity names (`ai.plan_facts_gate`). The served-fact gate passes them
    as `observed`, so a coach stating one of them is licensed and a target no engine serves is not."""
    s = ctx.get("sections") or {}
    vals = (s.get("charter_nutrition") or {}).get("values") or {}
    cal = s.get("calorie_target") or {}
    rules = (s.get("redlines") or {}).get("rules") or {}
    protein, floors = s.get("protein_day") or {}, s.get("floors_day") or {}
    kcal = [cal.get(k) for k in ("kcal", "base_kcal", "floor_any_day_kcal", "floor_lifting_day_kcal", "band_low", "band_high")]
    kcal += [vals.get(p) for p in vals if p.startswith("nutrition.calories.")] + [rules.get("energy_floor_kcal")]
    grams = [vals.get(p) for p in vals if p.startswith("nutrition.protein.") and "_g" in p]  # grams, not day/feeding counts
    grams += [protein.get(k) for k in ("total_g", "range_low", "range_high")]
    grams += [rules.get("protein_floor_g", {}).get(k) for k in ("value", "target_g", "feeding_g")]
    fibre = [vals.get(p) for p in vals if p.startswith("nutrition.floors.fibre.")] + [(floors.get("fibre") or {}).get("value_g")]
    out = {"calories": kcal, "protein_g": grams, "fiber_g": fibre}
    return {
        q: sorted({x for v in vs for x in (_numbers(v) if not isinstance(v, dict) else _numbers(list(v.values())))})
        for q, vs in out.items()
    }


def render_nutrition(ctx: dict[str, Any]) -> str:
    """The nutrition context's text block: every section headed with its source; absence stated."""
    s = ctx["sections"]
    cn = s["charter_nutrition"]
    parts = [[f"NUTRITION CHARTER v{cn.get('charter_version')} [{cn['source']}] ({ctx['context_version']})"]]
    parts[0] += [f"- {p}: {_clip(v)}" for p, v in (cn.get("values") or {}).items()] or ["- the charter's nutrition block could not be read"]
    rl = s["redlines"]
    parts.append(
        [f"REDLINES v{rl.get('version')}: the nutrition rules [{rl['source']}]"] + [f"- {k}: {_clip(v)}" for k, v in rl["rules"].items()]
    )
    cal = s["calorie_target"]
    head = f"CALORIE TARGET [{cal['source']}]"
    parts.append(
        [head, f"- {cal['kcal']} kcal ({cal.get('provenance')})" if cal.get("kcal") is not None else "- no calorie target resolved: say so"]
    )
    pr = s["protein_day"]
    parts.append(
        _render_fields(
            f"PROTEIN — the engine's day {pr.get('date') or ''}".strip(),
            pr,
            ((k, pr.get(k)) for k in _PROTEIN_PUBLISHED_KEYS if k != "date"),
        )
    )
    fl = s["floors_day"]
    parts.append(_render_fields("FLOORS — the engine's day", fl, ((m, fl.get(m)) for m in ("fat", "carb", "fibre") if m in fl)))
    parts.extend(_render_labs(ctx))
    parts.append([f"RULE: {ctx['rule']}"])
    return "\n\n".join("\n".join(p) for p in parts)


# ── the order checker ────────────────────────────────────────────────────────────────────
def _call(c: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(c, str):
        return c, {}
    return str((c or {}).get("tool") or ""), dict((c or {}).get("args") or {})


def _stage_of(tool: str, args: dict[str, Any]) -> Optional[str]:
    if tool == "plan_next_session":
        return "stage_2" if args.get("routine_id") else "plan_next_session"
    if tool == "manage_hevy_routine":
        action = str(args.get("action") or "")
        return "manage_hevy_routine draft" if action in DRAFT_ACTIONS else ("commit" if action == "commit" else None)
    return None


def stage_of(call: Any) -> Optional[str]:
    """The ORDER stage one call is (``plan_next_session`` / ``manage_hevy_routine draft``), ``stage_2`` /
    ``commit`` for the later steps, or None for any other call (pre-flight reads included)."""
    return _stage_of(*_call(call))


def order_violations(tool_calls: Iterable[Any]) -> list[dict[str, Any]]:
    """Every place a planning conversation's tool calls break ``ORDER``, in call order.

    A call is ``{"tool": name, "args": {...}}`` (or a bare tool name). A conversation with no
    plan/draft/commit call is not a planning conversation and returns []. Codes:
    ``plan_before_preflight`` / ``draft_before_preflight`` (with the ``missing`` members),
    ``draft_before_plan``, ``commit_before_plan``, ``no_plan_next_session``."""
    seen: set[str] = set()
    planned = False
    out: list[dict[str, Any]] = []
    planning = False
    for i, c in enumerate(tool_calls):
        tool = _call(c)[0]
        seen.add(tool)
        stage = stage_of(c)
        if stage is None or stage == "stage_2":
            continue
        planning = True
        missing = [m for m, tools in PRE_FLIGHT.items() if not seen.intersection(tools)]
        if stage == "plan_next_session":
            if missing and not planned:
                out.append({"code": "plan_before_preflight", "at": i, "tool": tool, "missing": missing})
            planned = True
        elif stage == "manage_hevy_routine draft" and not planned:
            code = "draft_before_preflight" if missing else "draft_before_plan"
            out.append({"code": code, "at": i, "tool": tool, "missing": missing})
            if missing:
                out.append({"code": "draft_before_plan", "at": i, "tool": tool, "missing": []})
        elif stage == "commit" and not planned:
            out.append({"code": "commit_before_plan", "at": i, "tool": tool, "missing": missing})
    if planning and not planned:
        out.append({"code": "no_plan_next_session", "at": None, "tool": None, "missing": []})
    return out
