"""lambdas/web/site_api_coach_stance.py — what the coaches think RIGHT NOW (/api/coach_team).

Split out of ``site_api_coach.py`` (#1654 — god-module breakup). One seam: **the
current read**. The coach-opinion engine's evidence-derived ``STANCE#latest`` (with
its hand-authored weight-band ladder as the silent scaffold when no stance exists
yet), the honest "held since" walk back through the weekly snapshots, the
integrator digest, and the team view that assembles all of it — the tension map and
the live inter-coach dispute included.

Every DDB read here is tombstone/phase-guarded (#946/#1085): these are singleton
records that ``get_item`` fetches, which bypasses the query-level phase filter, so
a wiped cycle's read would otherwise keep serving as "right now".

The routed handler entrypoints stay in the ``site_api_coach`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]``. That
matters especially here: ``test_coach_stance_engine`` stubs ``_stance_latest`` on
the facade and then calls ``_stance_block``, and ``test_singleton_tombstone_guards``
stubs ``_integrator_digest`` and then calls ``_team_tensions`` — both fan-outs go
back through ``_g``, so the stubs land. This module does NOT import the facade.
"""

import re
from typing import Any

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

from web.site_api_coach_ledger import _CALIB_COACH_NAMES  # the huddle shows the same calibration the scoreboard does (#538)
from web.site_api_coach_profile import _DISCLOSURE
from web.site_api_common import (
    USER_PREFIX,
    _decimal_to_float,
    _ok,
    logger,
)


def _stance_latest(coach_id, *, _g):
    """The coach-opinion engine's current evidence-derived stance (STANCE#latest),
    written weekly by coach_history_summarizer. None pre-data / during engine lag.

    Honors the restart tombstone: the intelligence wipe stamps tombstone=true +
    phase=pilot (tombstoned_reason=experiment_restart_<genesis>) on every COACH#
    record, but get_item bypasses the query-level phase filter — without this guard
    the old cycle's stance kept serving post-reset and the CC-09 pre-start ladder
    fallback never engaged. The next weekly summarizer run overwrites the record
    clean, so this is only the between-reset-and-first-compute window."""
    table = _g["table"]
    try:
        item = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": "STANCE#latest"}).get("Item")
        if not singleton_visible(item):  # #946/#1085: tombstone + any non-current phase
            return None
        return _decimal_to_float(item)
    except Exception:
        return None


def _integrator_digest(*, _g):
    """The integrator's cross-coach weekly digest (ai_analysis EXPERT#integrator),
    written weekly by ai-expert-analyzer. None pre-data or while the record is
    tombstoned from a reset.

    #946 — same class as _stance_latest above: the intelligence wipe stamps
    tombstone=true + phase=pilot on every ai_analysis record, but four get_item
    call sites (weekly_priority, coaching-dashboard, coach_analysis cross-domain
    note, coach_team tensions) bypassed the query-level phase filter, so
    /coaching/ kept narrating the WIPED cycle as "the board's read on you ·
    right now". One guarded accessor closes the get_item-bypass class on this
    record; the first post-genesis integrator run overwrites it clean."""
    table = _g["table"]
    try:
        item = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#integrator"}).get("Item")
        if not singleton_visible(item):
            return None
        return _decimal_to_float(item)
    except Exception:
        return None


def _latest_cycle_digest(*, _g):
    """The newest ENSEMBLE#digest CYCLE# record, or None while it's hidden.

    #1085 (extends #946): experiment-scoped like ENSEMBLE#dispute, and this was the
    one unguarded DDB read on the /api/coach_analysis route — between the reset and
    the first post-genesis ensemble run, the WIPED cycle's active_disagreements
    leaked into the response as cross_coach_reference. Newest-hidden means "no
    current-cycle digest"; we don't skip past it to an older wiped one."""
    table = _g["table"]
    try:
        items = table.query(
            KeyConditionExpression=Key("pk").eq("ENSEMBLE#digest") & Key("sk").begins_with("CYCLE#"),
            ScanIndexForward=False,
            Limit=1,
        ).get("Items", [])
        if not items or not singleton_visible(items[0]):
            return None
        return _decimal_to_float(items[0])
    except Exception:
        return None


def _stance_history(coach_id, limit=8, *, _g):
    """Recent STANCE# snapshots (newest first) for the 'how this read evolved' trail.
    Skips the STANCE#latest pointer — the dated series IS the history."""
    table = _g["table"]
    out = []
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("STANCE#"),
                    "ScanIndexForward": False,
                    "Limit": limit + 1,  # +1: STANCE#latest sorts among the dated keys
                }
            )
        )
        for it in resp.get("Items", []):
            it = _decimal_to_float(it)
            sk = it.get("sk", "")
            if sk == "STANCE#latest":
                continue
            out.append(
                {
                    "as_of": it.get("as_of") or sk.replace("STANCE#", ""),
                    "headline_read": it.get("headline_read", ""),
                    "stage": it.get("stage", {}),
                    "how_my_read_changed": it.get("how_my_read_changed", ""),
                }
            )
    except Exception:
        pass
    return out[:limit]


def _stance_held_since(coach_id, current_stage_label, *, _g):
    """The honest 'held since' date for a coach's current stance — the earliest
    consecutive STANCE# snapshot (walking newest→older) whose stage still matches
    the current one. STANCE# records are written WEEKLY, so this resolves to a real
    date / a count of weeks, NEVER a day count (ADR-104/105 — no fabricated
    day-granularity). Returns an ISO date string or None (no history / fallback
    ladder), and the front-end formats it as 'held since {date}' / '~N weeks'."""
    _stance_history = _g["_stance_history"]
    if not current_stage_label:
        return None
    held = None
    for snap in _stance_history(coach_id, limit=12):  # newest first
        label = (snap.get("stage") or {}).get("label")
        if label and label == current_stage_label:
            held = snap.get("as_of")
        else:
            break
    return held


def _stance_from_latest(latest):
    """Normalize a STANCE#latest record into the public stance shape (the
    evidence-derived branch of _stance_block; split out so the lead-tier coach
    page (#1112) can prefer a real stance without the staff ladder fallback)."""
    return {
        "source": "stance",
        "headline_read": latest.get("headline_read", ""),
        "focused_on_now": latest.get("focused_on_now", []),
        "set_aside_for_now": latest.get("set_aside_for_now", []),
        "stage": latest.get("stage", {}) or {},
        "how_my_read_changed": latest.get("how_my_read_changed", ""),
        "confidence_note": latest.get("confidence_note", ""),
        "as_of": latest.get("as_of"),
        "grounding_flag": bool(latest.get("grounding_flag")),
    }


def _stance_block(coach_id, weight_lbs, *, _g):
    """The coach's public read of Matthew, in a single normalized shape both the
    coach page (CC-01) and the My Team view (CC-10) consume.

    Prefers the evolving, evidence-derived STANCE#latest (the coach-opinion engine).
    Falls back to the hand-authored weight-band ladder (CC-09) ONLY when no stance
    exists yet — a silent scaffold so the page never blanks, never a parallel read.
    """
    _S3 = _g["_S3"]
    _S3_BUCKET = _g["_S3_BUCKET"]
    _stance_from_latest = _g["_stance_from_latest"]
    _stance_latest = _g["_stance_latest"]
    coach_stance = _g["coach_stance"]
    latest = _stance_latest(coach_id)
    if latest:
        return _stance_from_latest(latest)

    # ── Fallback: weight-band ladder, mapped into the same normalized keys ──
    stance = coach_stance.load_stance(coach_id, _S3, _S3_BUCKET) if coach_stance else {}
    ladder = stance.get("stage_ladder", [])
    metric = stance.get("band_metric")
    value = weight_lbs if metric == "weight_lbs" else None
    rung = (coach_stance.resolve_stage(ladder, value) if coach_stance else None) or (ladder[0] if ladder else None)
    rung = rung or {}
    return {
        "source": "ladder",
        "headline_read": rung.get("read_of_him", ""),
        "focused_on_now": rung.get("cares_most", []),
        "set_aside_for_now": rung.get("cares_less_right_now", []),
        "stage": {"label": rung.get("headline") or rung.get("stage_id"), "rationale": rung.get("read_of_him", "")},
        "how_my_read_changed": "",
        "confidence_note": "",
        "as_of": None,
        "grounding_flag": False,
        # ladder-only extras (kept for the scaffold's graduation framing)
        "graduation_gate": rung.get("graduation_gate"),
        "band_metric": metric,
        "current_value": value,
        "rung": rung,
        "ladder": [{"stage_id": s.get("stage_id"), "headline": s.get("headline")} for s in ladder],
    }


# #2385 — the AI writers occasionally emit markdown emphasis despite prompt rules
# ("prompt rules can't guarantee structure"), and the front-end esc()-renders these
# fields verbatim as plain text, so `**bold**`/`*em*` reached readers as literal
# asterisks. Deterministic strip at the serving seam: one place, covers every
# stored row (including history written before this shipped) with no re-generation.
# Ordered passes — `***both***` resolves bold first, then the leftover `*em*`.
_MD_EMPHASIS_PASSES: tuple = (
    re.compile(r"\*\*(.+?)\*\*", re.S),  # **bold**
    re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"),  # *em* (never a bare/mismatched asterisk)
    re.compile(r"(?<!_)__(.+?)__(?!_)", re.S),  # __bold__
)


def _strip_md_emphasis(text: Any) -> Any:
    """Strip markdown emphasis tokens from AI prose destined for plain-text
    rendering. Keeps the words, drops the tokens; non-strings pass through
    untouched (fields here are Optional). Unpaired asterisks (e.g. "5*10kg")
    are left alone — only paired emphasis is markdown."""
    if not isinstance(text, str) or ("*" not in text and "__" not in text):
        return text
    for _rx in _MD_EMPHASIS_PASSES:
        text = _rx.sub(r"\1", text)
    return text


def _team_tensions(*, _g):
    """Live cross-coach disagreements from the integrator digest (CC-10).
    Same source as get_coach_disagreements; honest empty pre-data."""
    _integrator_digest = _g["_integrator_digest"]
    try:
        item = _integrator_digest()  # #946: tombstone/phase-guarded
        if not item:
            return []
        raw = item.get("disagreements") or item.get("active_disagreements") or []
        # #2383 (ADR-104 honest dating) — every tension carries the digest's
        # generated_at so the front-end can date the band ("as of <date>") and
        # refuse to render undated argument prose as today's live coaching.
        # No fallback mark here: this writer (ai-expert-analyzer's weekly
        # synthesis) has no fallback path — a failed synthesis writes nothing —
        # unlike the ensemble digest's `_fallback` (#2333).
        gen = item.get("generated_at")
        out = []
        for d in raw if isinstance(raw, list) else []:
            if not isinstance(d, dict):
                continue
            coaches = d.get("coaches_involved") or d.get("coaches") or []
            # WQA-06: the integrator digest stores the argument as position_a/position_b
            # + the lead's adjudication. Earlier code read the wrong field names, so the
            # head-to-head came back empty. Read the real names first.
            # #1986: the adjudication key is now `lead_call` (it used to be named after
            # the character who signed it). Rows written before this ship still carry
            # `nakamura_call`, so both are read — persisted history stays legible without
            # a backfill, and the byline above it resolves from the registry either way.
            out.append(
                {
                    # #2385 — every prose field is markdown-stripped at the seam;
                    # the front-end renders these verbatim via esc().
                    "topic": _strip_md_emphasis(d.get("topic") or d.get("domain") or ""),
                    "coaches": coaches,
                    "position_a": _strip_md_emphasis(d.get("position_a") or d.get("coach_a_position")),
                    "position_b": _strip_md_emphasis(d.get("position_b") or d.get("coach_b_position")),
                    "resolution": _strip_md_emphasis(
                        d.get("lead_call")
                        or d.get("nakamura_call")
                        or d.get("resolution_suggested")
                        or d.get("tension")
                        or d.get("summary")
                        or ""
                    ),
                    "generated_at": gen,
                }
            )
        return out
    except Exception as _e:
        logger.warning(f"[coach_team] tensions: {_e}")
        return []


def _lead_block(team_focus, *, _g):
    """The Principal Investigator (Dr. Eli Marsh) — the lead above the 8 coaches.
    A non-operational orchestrator persona; surfaced as the head of the team."""
    _registry = _g["_registry"]
    lp = _registry().get("personas", {}).get("eli_marsh")
    if not lp:
        return None
    return {
        "persona_id": "eli_marsh",
        "name": lp.get("name"),
        "emoji": lp.get("emoji"),
        "color": lp.get("color"),
        "role": lp.get("board_role"),
        "short_bio": lp.get("short_bio"),
        "philosophy": lp.get("philosophy"),
        "expertise": lp.get("expertise", []),
        "staff_focus": (team_focus or [])[:3],  # what he's got the staff focused on
    }


def _latest_dispute(*, _g):
    """#540: the most recent inter-coach dispute thread — an ACTUAL exchange
    (coach B answered coach A's specific claim, gated turns), not a post-hoc
    summary. None when nothing has aired; the page renders nothing rather than
    inventing a fight.

    #1085 (extends #946): the restart wipe stamps tombstone=true + phase=pilot on
    every ENSEMBLE#dispute thread, but this reader queried the newest record with
    no guard — /api/coach_team kept serving the WIPED cycle's argument pre-start.
    The newest thread being hidden means "no current-cycle dispute" (we do NOT
    skip past it to resurrect an even older one); coach_team serves dispute:null
    and the front-end self-hides the section."""
    table = _g["table"]
    try:
        items = table.query(
            KeyConditionExpression=Key("pk").eq("ENSEMBLE#dispute"),
            ScanIndexForward=False,
            Limit=1,
        ).get("Items", [])
        if not items or not singleton_visible(items[0]):
            return None
        t = _decimal_to_float(items[0])
        return {
            "topic": t.get("topic"),
            "week": t.get("week"),
            "coach_a": t.get("coach_a"),
            "coach_b": t.get("coach_b"),
            "turns": [
                {"speaker": x.get("speaker"), "name": x.get("name"), "line": x.get("line"), "kind": x.get("kind")}
                for x in (t.get("turns") or [])
            ],
            "created_at": t.get("created_at"),
        }
    except Exception as e:
        logger.warning(f"[coach_team] dispute unavailable: {e}")
        return None


def handle_coach_team(event, *, _g):
    """GET /api/coach_team — the "My Team" view (CC-10): the team's collective read
    on Matthew right now. Stance focus + per-coach huddle + the live tension map.
    All from CC-09 stance + the integrator digest; no new inference. Shaped-empty 200."""
    EXPERIMENT_BASELINE_WEIGHT_LBS = _g["EXPERIMENT_BASELINE_WEIGHT_LBS"]
    _COACH_MODULES = _g["_COACH_MODULES"]
    _latest_dispute = _g["_latest_dispute"]
    _latest_weight_lbs = _g["_latest_weight_lbs"]
    _lead_block = _g["_lead_block"]
    _prefetch_calibration_partitions = _g["_prefetch_calibration_partitions"]
    _registry = _g["_registry"]
    _score_coach_calibration = _g["_score_coach_calibration"]
    _stance_block = _g["_stance_block"]
    _stance_held_since = _g["_stance_held_since"]
    _team_tensions = _g["_team_tensions"]
    persona_registry = _g["persona_registry"]
    if not _COACH_MODULES:
        return _ok({"huddle": [], "team_focus": [], "tensions": []}, cache_seconds=60)
    try:
        ops = {k: v for k, v in _registry().get("personas", {}).items() if v.get("operational")}
        weight = _latest_weight_lbs() or EXPERIMENT_BASELINE_WEIGHT_LBS
        huddle, focus, stages = [], [], {}
        # #1527: the per-coach calibration reads below each walked a full
        # PREDICTION# partition sequentially — prefetch them concurrently.
        _cal_records = _prefetch_calibration_partitions(
            [
                pid.removesuffix("_coach")
                for pid in persona_registry.OPERATIONAL_COACH_IDS
                if pid.removesuffix("_coach") in _CALIB_COACH_NAMES
            ]
        )
        for pid in persona_registry.OPERATIONAL_COACH_IDS:
            p = ops.get(pid)
            if not p:
                continue
            sb = _stance_block(pid, weight)
            stage = sb.get("stage") or {}
            # Canonical id for the cross-coach 'all same stage' check: the ladder's
            # stage_id on the fallback (a shared id space), else the evidence stage
            # label (stances have no shared id space — each coach's stage is its own).
            stage_id = (sb.get("rung") or {}).get("stage_id") or stage.get("label")
            stages[pid] = stage_id
            cares = sb.get("focused_on_now") or []
            if cares:
                focus.append(cares[0])
            # #538: the same calibration numbers the scoreboard shows — so a coach's
            # confidence in the huddle is legible next to how well-calibrated it's been.
            _bare = pid.removesuffix("_coach")
            _cal = {}
            if _bare in _CALIB_COACH_NAMES:
                _summ, _, _lifetime_summ, _ = _score_coach_calibration(_bare, records=_cal_records.get(_bare, []))
                _cal = {
                    "brier": _summ["brier"],
                    "calibration": _summ["calibration"],
                    "scored_n": _summ["n"],
                    # #1376: the huddle's confidence read shouldn't go dark on cycle
                    # 1 of a fresh season — carry the career figure alongside.
                    "lifetime_scored_n": _lifetime_summ["n"],
                    "lifetime_brier": _lifetime_summ["brier"],
                }
            huddle.append(
                {
                    "persona_id": pid,
                    "name": p.get("name"),
                    "emoji": p.get("emoji"),
                    "stage_id": stage_id,
                    "headline": stage.get("label"),
                    "read_of_him": sb.get("headline_read"),
                    "watch": cares[0] if cares else None,
                    "graduation_gate": sb.get("graduation_gate"),  # ladder-only; absent on stance
                    "calibration": _cal,
                    "source": sb.get("source"),
                    # #591: honest stance age — the date this stage was first held
                    # (weekly resolution; the cockpit renders "held since {date}").
                    "held_since": _stance_held_since(pid, stage.get("label")),
                }
            )
        seen = set()
        team_focus = [f for f in focus if not (f in seen or seen.add(f))]
        all_same = len(set(stages.values())) == 1 and bool(stages)
        return _ok(
            {
                "as_of_weight_lbs": weight,
                "lead": _lead_block(team_focus),
                "team_focus": team_focus,
                "huddle": huddle,
                "tensions": _team_tensions(),
                "dispute": _latest_dispute(),
                "all_same_stage": all_same,
                "current_stage": next(iter(stages.values())) if all_same else None,
                "disclosure": _DISCLOSURE,
            },
            cache_seconds=300,
        )
    except Exception as _e:
        logger.warning(f"[/api/coach_team] {_e}")
        return _ok({"huddle": [], "team_focus": [], "tensions": []}, cache_seconds=60, degraded=_e)
