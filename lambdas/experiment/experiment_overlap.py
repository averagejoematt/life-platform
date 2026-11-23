"""#6210 (epic #6206): proportional overlap check between concurrent N=1 experiments.

"One variable at a time" used to be advisory prose. This module makes it a rule with
proportion (owner ruling 2026-11-22), not a blanket prohibition:

  none     no active experiment, or the active ones share neither metric nor family.
  note     allowed; returned in the response, nothing required. The NEW experiment is
           observational, or only the outcome FAMILY (not the criterion metric) is shared,
           or either side has no design (compared on library_id / tags only).
  warning  a new BEHAVIOURAL experiment whose criterion metric equals an active
           BEHAVIOURAL experiment's criterion metric, or whose start falls inside the
           washout of an active behavioural experiment. Creation is refused unless the
           caller passes `acknowledge_overlap` (the owner's reason, 20-300 chars).

Pure functions only; the caller does the DynamoDB read and the write.
"""

from datetime import timedelta

from common.pacific_time import parse_day_key

INTERVENTION_KINDS = ("observational", "behavioral")
DEFAULT_INTERVENTION_KIND = "behavioral"
ACK_MIN_CHARS = 20
ACK_MAX_CHARS = 300

# Outcome families, keyed by design criterion metric slug (experiment_design.DESIGN_METRICS).
# A metric missing here has no family: it can still conflict on an EXACT metric match, never
# on family. Deliberately NOT a coverage test over DESIGN_METRICS — that dict grows in other
# lanes and a registry that must be edited in lockstep would red main.
OUTCOME_FAMILIES = {
    "sleep": (
        "sleep_score",
        "sleep_efficiency_pct",
        "deep_pct",
        "rem_pct",
        "sleep_duration_hours",
        "sleep_onset_latency_min",
    ),
    "recovery_hr": ("recovery_score", "hrv_rmssd", "resting_heart_rate", "garmin_stress", "body_battery_high"),
    "body_weight_intake": ("weight_lbs", "calories", "protein_g"),
    "glucose": ("cgm_mean_glucose", "cgm_time_in_range_pct"),
    "activity": ("steps",),
    # Training metrics are matched by prefix so a metric added to DESIGN_METRICS later joins
    # the family without touching this file.
    "training": (),
}
TRAINING_PREFIXES = ("training_", "strength_", "hevy_", "lift_")

_METRIC_TO_FAMILY = {m: fam for fam, metrics in OUTCOME_FAMILIES.items() for m in metrics}


def family_of(metric):
    """Outcome family for a criterion metric slug, or None."""
    if not metric:
        return None
    if metric in _METRIC_TO_FAMILY:
        return _METRIC_TO_FAMILY[metric]
    if str(metric).startswith(TRAINING_PREFIXES):
        return "training"
    return None


def normalize_kind(value):
    """'' / None -> default; anything not in INTERVENTION_KINDS raises ValueError."""
    kind = (value or "").strip().lower() if isinstance(value, str) else value
    if not kind:
        return DEFAULT_INTERVENTION_KIND
    if kind not in INTERVENTION_KINDS:
        raise ValueError(f"intervention_kind must be one of {list(INTERVENTION_KINDS)}")
    return kind


def validate_acknowledgement(reason):
    """Return the stripped reason, or None when absent. Raises ValueError on a bad length."""
    if reason is None:
        return None
    reason = str(reason).strip()
    if not reason:
        return None
    if not (ACK_MIN_CHARS <= len(reason) <= ACK_MAX_CHARS):
        raise ValueError(f"acknowledge_overlap must be {ACK_MIN_CHARS}-{ACK_MAX_CHARS} characters (the reason, in your own words)")
    return reason


def _metric(exp):
    design = exp.get("design") or {}
    return ((design.get("criterion") or {}).get("metric")) if isinstance(design, dict) else None


def _kind(exp):
    k = exp.get("intervention_kind")
    return k if k in INTERVENTION_KINDS else DEFAULT_INTERVENTION_KIND


def _day(value):
    """Calendar-day parse through the sanctioned parser (#3741); tolerates a longer stamp."""
    return parse_day_key(str(value)[:10]) if value else None


def _washout_end(exp):
    """First day AFTER the active experiment's washout, or None when it has none/unknown."""
    design = exp.get("design") or {}
    start = _day(exp.get("start_date"))
    try:
        washout = int(design.get("washout_days") or 0) if isinstance(design, dict) else 0
    except (TypeError, ValueError):
        washout = 0
    if start is None or washout <= 0:
        return None
    return start + timedelta(days=washout)


def _shared_tags(a, b):
    ta = {str(t).strip().lower() for t in (a.get("tags") or []) if str(t).strip()}
    tb = {str(t).strip().lower() for t in (b.get("tags") or []) if str(t).strip()}
    return sorted(ta & tb)


def _conflict(active, kind, detail, **extra):
    return {
        "experiment_id": active.get("experiment_id") or str(active.get("sk", ""))[4:],
        "name": active.get("name"),
        "kind": kind,
        "detail": detail,
        **extra,
    }


def assess_overlap(new_experiment, active_experiments):
    """Classify the overlap of a NEW experiment against the ACTIVE ones.

    new_experiment: dict with start_date, design (or None), intervention_kind, library_id, tags.
    Returns {"level": "none"|"note"|"warning", "conflicts": [...], "reason": str}.
    """
    new_metric = _metric(new_experiment)
    new_family = family_of(new_metric)
    new_kind = _kind(new_experiment)
    new_start = _day(new_experiment.get("start_date"))
    new_lib = new_experiment.get("library_id") or None

    warnings, notes = [], []
    for active in active_experiments or []:
        if active.get("status", "active") != "active":
            continue
        act_metric = _metric(active)
        act_kind = _kind(active)
        both_designed = bool(new_metric and act_metric)

        if not both_designed:
            # Legacy / design-less rows: library_id and tags only, never above a note.
            shared = _shared_tags(new_experiment, active)
            same_lib = bool(new_lib and new_lib == (active.get("library_id") or None))
            if same_lib or shared:
                detail = "same library entry" if same_lib else "shared tags " + ", ".join(shared)
                notes.append(_conflict(active, "tags", detail + " (no pre-registered design on one side)"))
            continue

        act_family = family_of(act_metric)
        if new_metric == act_metric:
            detail = f"both name {new_metric} as the criterion metric"
            if new_kind == "behavioral" and act_kind == "behavioral":
                warnings.append(_conflict(active, "metric", detail, metric=new_metric, family=new_family))
            else:
                notes.append(_conflict(active, "metric", detail, metric=new_metric, family=new_family))
            continue

        w_end = _washout_end(active)
        if new_kind == "behavioral" and act_kind == "behavioral" and w_end is not None and new_start is not None and new_start < w_end:
            warnings.append(
                _conflict(
                    active,
                    "washout",
                    f"starts {new_start.isoformat()}, before the active experiment's washout ends {w_end.isoformat()}",
                    metric=act_metric,
                    family=act_family,
                )
            )
            continue

        if new_family and new_family == act_family:
            notes.append(
                _conflict(
                    active,
                    "family",
                    f"{new_metric} and {act_metric} are both {new_family} outcomes",
                    metric=act_metric,
                    family=new_family,
                )
            )

    if warnings:
        return {
            "level": "warning",
            "conflicts": warnings + notes,
            "reason": (
                "a behavioural experiment already running measures the same outcome or is still in washout; "
                "results would be confounded. Pass acknowledge_overlap (your reason, 20-300 chars) to proceed."
            ),
        }
    if notes:
        return {
            "level": "note",
            "conflicts": notes,
            "reason": "overlaps an active experiment only loosely (observational, same outcome family, or no design) — allowed; read the caveat when it closes.",
        }
    return {"level": "none", "conflicts": [], "reason": "no active experiment shares a metric or outcome family."}


def acknowledgement_record(reason, assessment, acknowledged_at):
    """The row's `overlap_acknowledged` value (JSON-safe strings only)."""
    return {"reason": reason, "conflicts": assessment.get("conflicts") or [], "acknowledged_at": acknowledged_at}


def closing_caveat(exp, all_experiments):
    """One line naming the experiment(s) this one overlapped with on an acknowledged overlap, or None.

    Either direction: this row acknowledged an overlap naming others, or another row's
    acknowledgement names this one."""
    me = exp.get("experiment_id") or str(exp.get("sk", ""))[4:]
    names = {}
    for c in ((exp.get("overlap_acknowledged") or {}).get("conflicts")) or []:
        if c.get("kind") in ("metric", "washout"):
            names[c.get("experiment_id")] = c.get("name") or c.get("experiment_id")
    for other in all_experiments or []:
        oid = other.get("experiment_id") or str(other.get("sk", ""))[4:]
        if oid == me:
            continue
        for c in ((other.get("overlap_acknowledged") or {}).get("conflicts")) or []:
            if c.get("experiment_id") == me and c.get("kind") in ("metric", "washout"):
                names[oid] = other.get("name") or oid
    if not names:
        return None
    listed = "; ".join(sorted(str(n) for n in names.values()))
    return f"Caveat: ran alongside {listed} with an acknowledged overlap, so the effect may not be attributable to this protocol alone."


# ── call-site helpers (keep mcp/tools_lifestyle.py under its module/function ceilings) ─────────


def parse_args(args):
    """(intervention_kind, acknowledge_reason|None) from the tool args; ValueError on bad input."""
    return normalize_kind(args.get("intervention_kind")), validate_acknowledgement(args.get("acknowledge_overlap"))


def _all_rows(table, pk):
    from boto3.dynamodb.conditions import Key

    return table.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("EXP#")).get("Items", [])


def row_fields(intervention_kind, overlap_acknowledged):
    """Fields stored on the experiment row (None values are dropped by the caller's clean pass)."""
    return {"intervention_kind": intervention_kind, "overlap_acknowledged": overlap_acknowledged}


def response_fields(intervention_kind, overlap, overlap_acknowledged):
    """Fields echoed in the create_experiment response."""
    return {
        "intervention_kind": intervention_kind,
        "overlap": overlap,
        **({"overlap_acknowledged": overlap_acknowledged} if overlap_acknowledged else {}),
    }


def check_creation(table, pk, start_date, design, intervention_kind, library_id, tags, acknowledge_reason, now):
    """Assess + enforce. Returns (overlap, overlap_acknowledged|None); raises ValueError on an
    unacknowledged warning. A read failure fails open to level none (advisory infrastructure)."""
    new_experiment = {
        "start_date": start_date,
        "design": design,
        "intervention_kind": intervention_kind,
        "library_id": library_id or None,
        "tags": tags,
    }
    try:
        rows = _all_rows(table, pk)
    except Exception:  # noqa: BLE001
        rows = []
    overlap = assess_overlap(new_experiment, [r for r in rows if r.get("status") == "active"])
    if overlap["level"] != "warning":
        return overlap, None
    if not acknowledge_reason:
        why = "; ".join(
            f"{c['name'] or c['experiment_id']} ({c['kind']}: {c['detail']})"
            for c in overlap["conflicts"]
            if c["kind"] in ("metric", "washout")
        )
        raise ValueError(
            f"overlap refused (#6210): {why}. Re-run with acknowledge_overlap=<your reason, 20-300 chars> to proceed, "
            "or intervention_kind='observational' if this changes no behaviour."
        )
    return overlap, acknowledgement_record(acknowledge_reason, overlap, now.strftime("%Y-%m-%dT%H:%M:%SZ"))


def attach_closing_caveat(table, pk, existing, analysis):
    """Append the one-line overlap caveat to a closing analysis in place; verdict untouched, fail-soft."""
    if analysis is None:
        return
    try:
        caveat = closing_caveat(existing, _all_rows(table, pk))
    except Exception:  # noqa: BLE001
        return
    if caveat:
        analysis["overlap_caveat"] = caveat
        analysis["summary"] = f"{analysis.get('summary', '')} {caveat}".strip()


def iteration_count(table, pk, library_id, slug):
    """EL-F5: 1 + the past runs sharing this library_id or slug (moved here from create_experiment,
    which shares the one experiment-row read). Fail-soft: a read error leaves iteration at 1."""
    import re

    iteration = 1
    try:
        for past in _all_rows(table, pk):
            past_slug = re.sub(r"[^a-z0-9]+", "-", past.get("name", "").lower()).strip("-")[:40]
            if (library_id and (past.get("library_id") or "") == library_id) or past_slug == slug:
                iteration += 1
    except Exception:  # noqa: BLE001
        pass
    return iteration
