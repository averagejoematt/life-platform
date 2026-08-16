"""site_api_ai_context.py — the AI endpoints' context/facts fetch layer (#2667).

Extracted from site_api_ai_lambda.py (which sits at its module-size ceiling,
#1665/#2610) so the per-metric as-of layer had somewhere to live: #2667 found the
model narrating the latest stored weight as "as of today" when the newest record
was days old — `_latest_item` had no age concept and the prompt rendered every
metric under a bare CURRENT DATA header. The defect was structural, not
weight-specific: ANY source that goes stale was narrated as current (ADR-104).

What this module owns:
  * `_latest_item` — the recency reader (per-source cross-phase, #2109), now
    also recording WHEN the row it returned is from (`_AS_OF`, from the sk).
  * `_soft_block` / `_ask_fetch_context` / `_ask_fetch_computed_reads` — the
    fail-soft context assembly (#2277), unchanged in behavior, plus a
    `ctx["as_of"]` map (metric-group -> ISO date) and `ctx["stale"]` flags
    derived from each source's own registry `stale_hours` facet (#2003 — read
    the registry, never hand-state a threshold).
  * `_board_facts_block` — the shared board CURRENT DATA line set, now dated.
  * `age_annotation` — the ONE renderer for "(as of …)" / staleness text, so
    the ask block and the board block cannot phrase honesty differently.

Grounding coherence: the as-of dates rendered into prompts are automatically
allow-listed — /api/ask's `allowed_dates` derives from the prompt text itself
(#1967), so a model echoing "as of 2026-08-11" is gate-legal by construction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS  # ADR-058
from experiment.phase_filter import singleton_visible, source_reads_cross_phase, with_phase_filter  # ADR-058 / #946 / #2109

from web.site_api_common import PT, USER_PREFIX, _decimal_to_float

logger = logging.getLogger(__name__)


def _table():
    """The ONE table handle — resolved through the lambda module at call time, so
    the behavior suite's 39 existing `monkeypatch.setattr(ai, "table", ...)` sites
    keep governing every read this layer makes (an extraction that orphaned those
    patches would send the whole suite to real DynamoDB). Lazy import: the lambda
    imports this module at load, so the reverse edge only ever resolves warm."""
    from web import site_api_ai_lambda as _ai

    return _ai.table


def _hook(name: str):
    """Resolve an intra-layer seam through the LAMBDA namespace when available.

    The behavior suite's one patch surface is `ai.<name>` (six sites patch
    `ai._latest_item` alone); after the extraction those names are re-exports,
    and a sibling-internal call that bypassed them would make every such patch
    silently dead — the suite would test nothing while green. Falls back to this
    module's own def for direct importers (the canary) and import-order edges."""
    try:
        from web import site_api_ai_lambda as _ai

        return getattr(_ai, name)
    except Exception:
        return globals()[name]


# The internal key `_latest_item` stashes the row date under. Underscored and
# stripped by nothing downstream because ctx is prompt-side only — it never
# serializes into a public payload.
_AS_OF = "_as_of_date"


def _sk_date(item: dict | None) -> str | None:
    """The ISO date segment of a DATE#-keyed sort key, or None.

    Sub-keyed rows (whoop workouts: DATE#YYYY-MM-DD#WORKOUT#<uuid>) keep lexical
    date ordering, so the first segment is the row date — the same parse the i16
    integration gate settled on (#2768)."""
    sk = (item or {}).get("sk") or ""
    if not sk.startswith("DATE#"):
        return None
    seg = sk[len("DATE#") :].split("#")[0]
    return seg if len(seg) == 10 else None


def _stale_hours_for(source: str) -> int | None:
    """The source's own registry staleness threshold (#2003: read the registry,
    never hand-state a cadence), or None when the source is unregistered."""
    try:
        from ingestion.source_registry import DEFAULT_STALE_HOURS, stale_hours_overrides

        return int(stale_hours_overrides().get(source, DEFAULT_STALE_HOURS))
    except Exception:
        return None


def age_annotation(as_of: str | None, source: str | None = None, today: str | None = None) -> str:
    """The ONE honesty annotation for a dated metric line.

    - same-day reading -> "" (no noise on fresh data)
    - older reading    -> " (as of YYYY-MM-DD)"
    - past the source's registry stale_hours -> the STALE form, which instructs
      the model to present the value as last-known, never as today's.
    """
    if not as_of:
        return " (reading date unknown — treat as not current)"
    today = today or datetime.now(PT).strftime("%Y-%m-%d")
    if as_of == today:
        return ""
    try:
        age_days = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(as_of, "%Y-%m-%d")).days
    except ValueError:
        return f" (as of {as_of})"
    hours = _stale_hours_for(source) if source else None
    if hours is not None and age_days * 24 > hours:
        return f" (as of {as_of} — STALE, {age_days}d old; last-known value, NOT current)"
    return f" (as of {as_of})"


def _latest_item(source: str) -> dict | None:
    """Get the most recent item for a source, PER-SOURCE cross-phase (#2109).

    The recency reader behind the AI ask's context block. It is the #1203 shape
    verbatim — newest-first `Limit: 1` — and DynamoDB applies `Limit` BEFORE
    `FilterExpression`, so a phase-filtered read took the single newest row, discarded
    it for being pilot-tagged, and returned nothing at all. On a fresh cycle that is
    the normal state of the `withings` and `whoop` partitions, so the ask lost the
    reader's latest weigh-in and last night's recovery entirely.

    Its other three callers read `computed_metrics`, `computed_insights` and
    `adaptive_mode`, which are EXPERIMENT_SCOPED — derived intelligence the reset
    tombstones, where the filter is load-bearing and must stay. That split is exactly
    why this is derived per source (#2092's shape, and the treatment this function's
    `site_api_common` namesake already gets via its explicit `include_pilot`
    pass-through) rather than flipped.

    NB the EXPERIMENT_SCOPED half still carries the `Limit`-before-filter mechanic, so
    a scoped read here can return nothing in the hours after a genesis. That is the
    honest answer for a scoped source (a prior cycle's row does not speak for this
    one), and #2113's `phase_taxonomy.cycle_read_floor` is the key-floor treatment for
    it — deliberately not duplicated here.
    """
    pk = f"{USER_PREFIX}{source}"
    resp = _table().query(
        **with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(pk),
                "ScanIndexForward": False,
                "Limit": 1,
            },
            include_pilot=source_reads_cross_phase(source),
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return None
    # #2667: record WHEN this row is from, so downstream renderers can date the
    # metric instead of implying it is today's. Internal key, prompt-side only.
    items[0][_AS_OF] = _sk_date(items[0])
    return items[0]


def _soft_block(label: str, block) -> None:
    """Run one context block fail-soft (#2277).

    Every read behind /api/ask is degradable: a throttle on one secondary
    partition should cost the reader that block, not the whole answer — which is
    the position `_ask_fetch_computed_reads` already takes ("a missing compute
    just omits that read; ask still answers from the vitals"). The blocks in
    `_ask_fetch_context` are registered through this one helper so the property
    is a property of the read SET, not of two hand-patched call sites.

    MEASURED 2026-08-08 (#2277 named two): FOUR reads here were unguarded, not
    two — the `character_sheet` get_item and the `habit_scores` query the issue
    names, plus BOTH `_latest_item` vitals reads (withings, whoop), which are the
    reads the answer actually leans on. `tests/test_site_api_ai_behavior.py`
    derives the read set at runtime and fails each read in turn, so a fifth
    unguarded read cannot ship unnoticed.
    """
    try:
        block()
    except Exception as e:
        logger.warning(f"[ask ctx] {label} skipped: {e}")


def _ask_fetch_context() -> dict:
    """Fetch sanitized aggregate data for the AI prompt.

    Every read is fail-soft (#2277) — see `_soft_block`. A blip degrades the
    answer (the missing block is simply absent from the prompt); it never turns
    into a blanket `500 AI service error` for a question the vitals could have
    answered.
    """
    today_str = datetime.now(PT).strftime("%Y-%m-%d")  # #2414: the reader's "today" is the Pacific day
    yesterday_str = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
    ctx: dict = {
        # Pre-seeded so a profile blip leaves the journey framing intact rather
        # than undefined; the profile block overwrites both on success.
        "start_weight": EXPERIMENT_BASELINE_WEIGHT_LBS,
        "goal_weight": 185,
        # #2667: metric-group -> ISO date of the row that supplied it. Renderers
        # date every line from this; a missing entry renders as unknown-age.
        "as_of": {},
    }

    def _withings() -> None:
        w = _hook("_latest_item")("withings")
        if w and w.get("weight_lbs"):
            ctx["weight_lbs"] = float(w["weight_lbs"])
            ctx["as_of"]["weight"] = w.get(_AS_OF)

    def _whoop() -> None:
        wh = _hook("_latest_item")("whoop")
        if not wh:
            return
        for src_key, out_key in (
            ("hrv", "hrv_ms"),
            ("resting_heart_rate", "rhr_bpm"),
            ("recovery_score", "recovery_pct"),
            ("sleep_duration_hours", "sleep_hours"),
        ):
            if wh.get(src_key):
                ctx[out_key] = float(wh[src_key])
                ctx["as_of"]["vitals"] = wh.get(_AS_OF)

    def _character_sheet() -> None:
        cs_pk = f"{USER_PREFIX}character_sheet"
        for d in [today_str, yesterday_str]:
            resp = _table().get_item(Key={"pk": cs_pk, "sk": f"DATE#{d}"})
            rec = _decimal_to_float(resp.get("Item"))
            if rec:
                ctx["character_level"] = float(rec.get("character_level", 1))
                ctx["character_tier"] = rec.get("character_tier", "Foundation")
                pillars = {}
                for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                    pd = rec.get(f"pillar_{p}", {})
                    pillars[p] = {
                        "level": float(pd.get("level", 1)),
                        "raw_score": float(pd.get("raw_score", 0)),
                        "tier": pd.get("tier", "Foundation"),
                    }
                ctx["pillars"] = pillars
                ctx["as_of"]["character"] = d
                break

    def _habit_scores() -> None:
        hs_pk = f"{USER_PREFIX}habit_scores"
        hs_resp = _table().query(
            **with_phase_filter(  # ADR-058: hide pilot habit scores
                {"KeyConditionExpression": Key("pk").eq(hs_pk), "ScanIndexForward": False, "Limit": 1}
            )
        )
        hs_items = _decimal_to_float(hs_resp.get("Items", []))
        if hs_items:
            ctx["tier0_streak"] = int(hs_items[0].get("t0_perfect_streak", 0) or 0)

    def _profile() -> None:
        # Fetch start/goal from profile for dynamic prompt injection.
        # Canonical profile key — the old {USER_PREFIX}profile/PROFILE item never
        # existed, so this read silently fell back to constants (found 2026-06-12).
        prof_resp = _table().get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})
        prof = _decimal_to_float(prof_resp.get("Item", {}))
        ctx["start_weight"] = float(prof.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS))
        ctx["goal_weight"] = float(prof.get("goal_weight_lbs", 185))

    def _computed_reads() -> None:
        ctx["reads"] = _hook("_ask_fetch_computed_reads")()

    for _label, _block in (
        ("withings", _withings),
        ("whoop", _whoop),
        ("character_sheet", _character_sheet),
        ("habit_scores", _habit_scores),
        ("profile", _profile),
        ("computed_reads", _computed_reads),
    ):
        _soft_block(_label, _block)
    ctx.setdefault("reads", {})
    return ctx


def _ask_fetch_computed_reads() -> dict:
    """#387: the drivers/trends/correlations the platform ALREADY computes,
    assembled server-side so the model narrates Python's work instead of
    confessing it only has a handful of latest numbers (or worse, asking the
    reader to supply Matthew's data). Every block is fail-soft — a missing
    compute just omits that read; ask still answers from the vitals."""
    reads: dict = {}

    # Canonical daily facts (computed_metrics → the same numbers coaches ground
    # on): weight trend rate + the protein trio the vitals block doesn't carry.
    try:
        from experiment.canonical_facts import build_canonical_facts

        facts = build_canonical_facts(_hook("_latest_item")("computed_metrics") or {})
        if facts.get("weekly_rate_lbs") is not None:
            reads["weekly_rate_lbs"] = facts["weekly_rate_lbs"]
        if facts.get("protein_g_avg") is not None:
            # #1919 — MEASURED: `protein_g_avg` is computed in
            # daily_metrics_compute_lambda.py from a 30-day cross-phase
            # `fetch_range` window (RAW_TIMESERIES, #2109) — it has always been a
            # real 30-day average, never a genesis-clamp casualty. The defect was
            # the KEY, not the window: it published as `avg_7d_g` (and narrated
            # "7-day avg") while the underlying computation was 30 days. Renamed
            # to match reality rather than gated, because there is nothing to gate
            # — the window is genuinely, permanently full.
            reads["protein"] = {
                "avg_30d_g": facts["protein_g_avg"],
                "target_g": facts.get("protein_g_target"),
                "floor_g": facts.get("protein_g_floor"),
            }
    except Exception as e:
        logger.warning(f"[ask reads] canonical facts skipped: {e}")

    # Daily insight drivers (computed_insights): momentum + which metrics are
    # moving which way + habit strengths/weaknesses.
    try:
        ins = _hook("_latest_item")("computed_insights") or {}
        if ins.get("momentum_signal"):
            reads["momentum"] = str(ins["momentum_signal"])[:300]
        for src_key, out_key in (("improving_metrics", "improving"), ("declining_metrics", "declining")):
            raw = ins.get(src_key)
            vals = json.loads(raw) if isinstance(raw, str) else raw
            if vals:
                reads[out_key] = [str(v)[:80] for v in vals][:4]
        if ins.get("strongest_habits"):
            reads["strongest_habits"] = [str(h)[:60] for h in ins["strongest_habits"]][:3]
        if ins.get("weakest_habits"):
            reads["weakest_habits"] = [str(h)[:60] for h in ins["weakest_habits"]][:3]
    except Exception as e:
        logger.warning(f"[ask reads] computed_insights skipped: {e}")

    # Adaptive-mode read (the platform's own morning verdict + its reasons —
    # this is the precomputed answer to "what drove today?").
    try:
        am = _hook("_latest_item")("adaptive_mode") or {}
        if am.get("mode_label"):
            factors = am.get("factors") or {}
            reads["adaptive_mode"] = {
                "label": str(am["mode_label"])[:60],
                "score": am.get("engagement_score"),
                "factors": {str(k)[:30]: str(v)[:120] for k, v in factors.items() if v},
            }
    except Exception as e:
        logger.warning(f"[ask reads] adaptive_mode skipped: {e}")

    # Monthly motion (what_changed SNAPSHOT#current — trailing-30d vs prior-30d,
    # written weekly; real deltas only, honest_null on a flat month).
    try:
        wc = _table().get_item(Key={"pk": f"{USER_PREFIX}what_changed", "sk": "SNAPSHOT#current"}).get("Item")
        # #1895: same restart tombstone as the /api/what_changed reader. Unguarded,
        # this grounded AI answers in the WIPED cycle's monthly deltas — the leak
        # reaching the model rather than the page.
        wc = _decimal_to_float(wc if singleton_visible(wc) else {})
        deltas = []
        for d in (wc.get("deltas") or [])[:6]:
            deltas.append(
                {
                    "label": d.get("label") or d.get("metric"),
                    "this_month_avg": d.get("this_month_avg"),
                    "prior_month_avg": d.get("prior_month_avg"),
                    "delta": d.get("delta"),
                    "unit": d.get("unit") or "",
                    "direction": d.get("direction"),
                }
            )
        if deltas:
            reads["month_deltas"] = deltas
    except Exception as e:
        logger.warning(f"[ask reads] what_changed skipped: {e}")

    # FDR-significant correlations (weekly_correlations) — the statistically
    # defensible pattern set, strongest first.
    try:
        resp = _table().query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}weekly_correlations"),
                    "ScanIndexForward": False,
                    "Limit": 4,
                }
            )
        )
        pairs: dict = {}
        for item in _decimal_to_float(resp.get("Items", [])):
            corrs = item.get("correlations", {})
            if not isinstance(corrs, dict):
                continue
            for label, data in corrs.items():
                if not isinstance(data, dict) or not data.get("fdr_significant") or label in pairs:
                    continue
                pairs[label] = {
                    "a": str(data.get("metric_a", ""))[:40],
                    "b": str(data.get("metric_b", ""))[:40],
                    "r": round(float(data.get("pearson_r", 0) or 0), 2),
                    "n_days": int(data.get("n_days", 0) or 0),
                }
        if pairs:
            reads["correlations"] = sorted(pairs.values(), key=lambda p: -abs(p["r"]))[:5]
    except Exception as e:
        logger.warning(f"[ask reads] correlations skipped: {e}")

    # Presence (engagement_state — same public allowlist as /api/presence, so a
    # quiet stretch is narrated honestly instead of read as missing data).
    try:
        pres = _table().get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"}).get("Item")
        # #1895: engagement_state is wiped ("all") at a restart and TOMBSTONED, not
        # deleted — get_item bypasses the query-level phase filter, so without this
        # the wiped cycle's presence class would ground AI answers until the next
        # engagement compute overwrote it. Same #946 predicate as the stance reads.
        pres = _decimal_to_float(pres if singleton_visible(pres) else {})
        if pres.get("presence_class"):
            reads["presence"] = {
                "class": str(pres["presence_class"])[:20],
                "gap_days": pres.get("gap_days"),
                "passive_still_flowing": bool(pres.get("passive_still_flowing")),
            }
    except Exception as e:
        logger.warning(f"[ask reads] presence skipped: {e}")

    return reads


def _board_facts_block(ctx: dict = None) -> str:
    """The shared CURRENT DATA block — the same sanitized aggregates /api/ask
    grounds on, formatted once per request and injected into every persona turn.

    #743: accepts a pre-fetched `ctx` (the exact generation brief) so a caller
    that also needs `board_grounding_receipts(ctx)` for the reader-facing
    footer shares ONE fetch instead of two — the receipt must describe the
    SAME brief the prompt was built from, not a second, possibly-different read.
    """
    if ctx is None:
        ctx = _ask_fetch_context()
    # #2667: every dated line carries its own as-of annotation — a coach citing a
    # five-day-old weigh-in as today's is the exact ADR-104 violation this closes.
    _asof = ctx.get("as_of") or {}
    _w_ann = age_annotation(_asof.get("weight"), "withings")
    _v_ann = age_annotation(_asof.get("vitals"), "whoop")
    lines = []
    if ctx.get("weight_lbs") is not None:
        lines.append(f"weight: {ctx['weight_lbs']:.1f} lb{_w_ann}")
    if ctx.get("recovery_pct") is not None:
        lines.append(f"whoop recovery score: {ctx['recovery_pct']:.0f}%{_v_ann}")
    if ctx.get("hrv_ms") is not None:
        lines.append(f"HRV: {ctx['hrv_ms']:.1f} ms{_v_ann}")
    if ctx.get("rhr_bpm") is not None:
        lines.append(f"resting HR: {ctx['rhr_bpm']:.0f} bpm{_v_ann}")
    if ctx.get("sleep_hours") is not None:
        lines.append(f"last sleep: {ctx['sleep_hours']:.1f} h{_v_ann}")
    if ctx.get("character_level") is not None:
        lines.append(f"character level: {ctx['character_level']:.0f} ({ctx.get('character_tier', 'Foundation')})")
    for pname, pd in (ctx.get("pillars") or {}).items():
        lines.append(f"pillar {pname}: {pd.get('raw_score', 0):.0f}/100")
    if ctx.get("habit_completion_pct") is not None:
        lines.append(f"habit completion: {ctx['habit_completion_pct']:.0f}%")
    return "; ".join(lines) if lines else "no current data available"
