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

CONTEXT_VERSION = "coach-context@1.2.0"  # 1.1.0 #5059: clinical_guidance.freshness (owner channel, reference only); 1.2.0 #5090: run_gate

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


def _packet_section(packet: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(packet, dict) or not isinstance(packet.get("fields"), dict):
        return {
            "source": SRC_PACKET,
            "state": NOT_SUPPLIED,
            "fields": {},
            "detail": "this caller read no plan packet (get_coach_session_packet carries it in a planning chat)",
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


def _tracker_section(tracker: Any) -> dict[str, Any]:
    if tracker is None:
        return {
            "source": SRC_TRACKER,
            "state": NOT_SUPPLIED,
            "detail": "no May tracker was supplied to this context (#5073 lands it); nothing here stands in for one",
        }
    return {"source": SRC_TRACKER, "state": "measured", "value": tracker}


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
        "Every session in this plan is judged by whether it protects muscle and holds the band to that date."
    )
    return {
        "source": SRC_MAY,
        "target_date": target,
        "weeks_to_target": weeks,
        "days_to_target": days,
        "rate_band": band or raw,
        "line": line,
    }


# ── the one assembly ─────────────────────────────────────────────────────────────────────
def assemble(
    target_date: str,
    *,
    packet: Optional[dict[str, Any]],
    constraint_block: Optional[dict[str, Any]],
    tracker: Any = None,
    guidance: Any = None,
    guidance_freshness: Any = None,
    published: bool = False,
) -> dict[str, Any]:
    """The planning context for `target_date`: a dict for code and ``text`` for a prompt.

    ``published=False`` is the owner channel (the may_frame and the owner-channel clinical block);
    pass True from any surface whose output can reach a reader."""
    from training import training_charter as tc  # noqa: PLC0415

    sections = {
        "charter": charter_section(published),
        "panel_synthesis": _panel_section(published),
        "clinical_guidance": _guidance_section(guidance, published, guidance_freshness),
        "plan_packet": _packet_section(packet),
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
        "not_supplied": sorted(k for k, s in sections.items() if s.get("state") == NOT_SUPPLIED),
    }
    out["text"] = render(out)
    return out


def summary(ctx: dict[str, Any]) -> dict[str, Any]:
    """The compact form a payload carries beside its own data (the text block is the AI-facing form)."""
    return {
        "context_version": ctx.get("context_version"),
        "charter_version": ctx.get("charter_version"),
        "states": {k: s.get("state") for k, s in (ctx.get("sections") or {}).items()},
        "not_supplied": ctx.get("not_supplied"),
        "may_frame": (ctx.get("may_frame") or {}).get("line"),
        "run_gate": (ctx.get("run_gate") or {}).get("line"),
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
        parts.append(_render_fields("MAY TRACKER", tr, [("value", tr.get("value"))] if tr.get("state") == "measured" else []))
    if ctx.get("may_frame"):
        parts.append([f"MAY FRAME (owner-only) [{ctx['may_frame']['source']}]", ctx["may_frame"]["line"]])
    if ctx.get("run_gate"):  # #5090: owner channel only (assemble sets None when published)
        rg = ctx["run_gate"]
        parts.append([f"RUN GATE (owner-only) [{rg['source']}; {rg['state']}]", rg["line"]])
    if not ctx["published"]:  # the order contract is the owner's planning conversation's, never a reader prompt's
        parts.append(["ORDER: " + " -> ".join(ctx["order"]) + " (pre-flight = " + ", ".join(PRE_FLIGHT) + ")"])
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
