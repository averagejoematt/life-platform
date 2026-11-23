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
from decimal import Decimal

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


class OverlapCheckIncomplete(Exception):
    """The check could not be completed; carries WHICH row and field (never values)."""

    def __init__(self, message, row_id=None, field=None):
        super().__init__(message)
        self.row_id = row_id
        self.field = field


MAX_PAGES = 50  # a sane cap: the experiments partition is tens of rows, one page in practice
_INACTIVE_STATUSES = ("completed", "abandoned")


def _row_id(row):
    if not isinstance(row, dict):
        return "?"
    return str(row.get("experiment_id") or str(row.get("sk", ""))[4:] or "?")[:80]


def _bad(row, field):
    return OverlapCheckIncomplete(f"unassessable row field {field}", _row_id(row), field)


def _validate_active(row):
    """Raise OverlapCheckIncomplete unless an ACTIVE row is assessable. A row with NO design is the
    documented legacy case (note at most) and passes; a design that is present but malformed does not."""
    design = row.get("design")
    if design is None:
        return
    if not isinstance(design, dict):
        raise _bad(row, "design")
    criterion = design.get("criterion")
    if not isinstance(criterion, dict):
        raise _bad(row, "design.criterion")
    metric = criterion.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        raise _bad(row, "design.criterion.metric")
    washout = design.get("washout_days")
    if washout is not None:
        ok = not isinstance(washout, bool) and isinstance(washout, (int, float, Decimal)) and washout == int(washout) and washout >= 0
        if not ok:
            raise _bad(row, "design.washout_days")
    if _day(row.get("start_date")) is None:
        raise _bad(row, "start_date")


def assess_overlap(new_experiment, active_experiments):
    """Classify the overlap of a NEW experiment against the ACTIVE ones.

    new_experiment: dict with start_date, design (or None), intervention_kind, library_id, tags.
    Returns {"level": "none"|"note"|"warning", "check_status": "checked", "conflicts": [...], "reason": str}.
    Pass ALL experiment rows: completed/abandoned rows are skipped; any other row that is not a
    well-formed active row raises OverlapCheckIncomplete (state 3), never a silent skip.
    A check that could not be completed is NEVER produced here — see `indeterminate()`; the
    caller turns any exception from this function into that state, never into "none".
    """
    new_metric = _metric(new_experiment)
    new_family = family_of(new_metric)
    new_kind = _kind(new_experiment)
    new_start = _day(new_experiment.get("start_date"))
    new_lib = new_experiment.get("library_id") or None

    warnings, notes = [], []
    for active in active_experiments or []:
        if not isinstance(active, dict):
            raise _bad(active, "row")
        status = str(active.get("status") or "").strip().lower()
        if status in _INACTIVE_STATUSES:
            continue
        if status != "active":
            raise _bad(active, "status")  # cannot be classified as inactive, so it must be assessed
        _validate_active(active)
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
            "check_status": "checked",
            "conflicts": warnings + notes,
            "reason": (
                "a behavioural experiment already running measures the same outcome or is still in washout; "
                "results would be confounded. Pass acknowledge_overlap (your reason, 20-300 chars) to proceed."
            ),
        }
    if notes:
        return {
            "level": "note",
            "check_status": "checked",
            "conflicts": notes,
            "reason": "overlaps an active experiment only loosely (observational, same outcome family, or no design) — allowed; read the caveat when it closes.",
        }
    return {
        "level": "none",
        "check_status": "checked",
        "conflicts": [],
        "reason": "no active experiment shares a metric or outcome family.",
    }


def indeterminate(exc):
    """State 3 of the owner's three-state result: the check could not be completed.

    Names the error CLASS only (no message — it can carry table names or request ids)."""
    cls = type(exc).__name__
    where = ""
    if isinstance(exc, OverlapCheckIncomplete) and exc.field:
        where = f" (row {exc.row_id}, field {exc.field})"
    return {
        "level": "indeterminate",
        "check_status": "indeterminate",
        "conflicts": [],
        "error_class": cls,
        "reason": f"overlap check could not be completed: {cls}{where}",
    }


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
    """Every EXP# row, paginated to completion. A page cap hit or an error mid-way raises: a partial
    read must never be reported as a checked result."""
    from boto3.dynamodb.conditions import Key

    rows, start_key = [], None
    for _ in range(MAX_PAGES):
        kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("EXP#")}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            return rows
    raise OverlapCheckIncomplete(f"pagination did not complete within {MAX_PAGES} pages", None, "pagination")


def row_fields(intervention_kind, overlap_acknowledged, overlap=None):
    """Fields stored on the experiment row (None values are dropped by the caller's clean pass).

    Every NEW row carries `overlap.check_status` ("checked" or "indeterminate") so a cleared row is
    distinguishable from a pre-PR row, and an uncleared one is never read later as cleared. An
    indeterminate result also stores its reason and error class (class only, no values)."""
    stored = None
    if overlap:
        keys = ("check_status", "reason", "error_class") if overlap.get("check_status") == "indeterminate" else ("check_status",)
        stored = {k: overlap[k] for k in keys if k in overlap}
    return {"intervention_kind": intervention_kind, "overlap_acknowledged": overlap_acknowledged, "overlap": stored}


def response_fields(intervention_kind, overlap, overlap_acknowledged):
    """Fields echoed in the create_experiment response."""
    warn = (
        {"overlap_warning": overlap["reason"] + " — this experiment was created WITHOUT overlap clearance."}
        if overlap.get("check_status") == "indeterminate"
        else {}
    )
    return {
        "intervention_kind": intervention_kind,
        "overlap": overlap,
        **warn,
        **({"overlap_acknowledged": overlap_acknowledged} if overlap_acknowledged else {}),
    }


def check_creation(table, pk, start_date, design, intervention_kind, library_id, tags, acknowledge_reason, now):
    """Assess + enforce. Returns (overlap, overlap_acknowledged|None); raises ValueError when refused.

    Three states (owner ruling 2026-11-22): checked/overlap, checked/no overlap, and indeterminate.
    A failed read, or a malformed row that breaks the assessment, is the third state and is never
    folded into "none": observational proceeds with a warning, behavioural is refused unless
    `acknowledge_overlap` is given (stored with check_status "indeterminate", never as cleared)."""
    new_experiment = {
        "start_date": start_date,
        "design": design,
        "intervention_kind": intervention_kind,
        "library_id": library_id or None,
        "tags": tags,
    }
    try:
        overlap = assess_overlap(new_experiment, _all_rows(table, pk))
    except Exception as exc:  # noqa: BLE001 — becomes the explicit indeterminate state, not "none"
        overlap = indeterminate(exc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if overlap["check_status"] == "indeterminate":
        if intervention_kind == "observational":
            return overlap, None
        if not acknowledge_reason:
            raise ValueError(f"{overlap['reason']}; retry, or pass acknowledge_overlap with your reason to proceed without clearance")
        return overlap, {**acknowledgement_record(acknowledge_reason, overlap, stamp), "check_status": "indeterminate"}
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
    return overlap, {**acknowledgement_record(acknowledge_reason, overlap, stamp), "check_status": "checked"}


NOT_VERIFIED_CAVEAT = "overlap not verified at creation"


def _stored_status(exp):
    """The stored creation-time check status, or None for a pre-PR row (no overlap block)."""
    for key in ("overlap", "overlap_acknowledged"):
        block = exp.get(key)
        if isinstance(block, dict) and block.get("check_status") == "indeterminate":
            return "indeterminate"
    return None


def attach_closing_caveat(table, pk, existing, analysis):
    """Append the one-line overlap caveat to a closing analysis in place; verdict untouched.

    Fail-soft for the CLOSE (an error never blocks ending an experiment) but never silent: the
    analysis records `overlap_caveat_check` = "not_run: <ErrorClass>" when the check could not run
    (absent = it ran), so a missing caveat is distinguishable from "no overlap"."""
    if analysis is None:
        return
    if _stored_status(existing) == "indeterminate":
        # Created without overlap clearance: say so on the close; verdict untouched.
        analysis["overlap_caveat"] = NOT_VERIFIED_CAVEAT
        analysis["summary"] = f"{analysis.get('summary', '')} {NOT_VERIFIED_CAVEAT}.".strip()
        return
    try:
        caveat = closing_caveat(existing, _all_rows(table, pk))
    except Exception as exc:  # noqa: BLE001
        analysis["overlap_caveat_check"] = f"not_run: {type(exc).__name__}"
        analysis["summary"] = f"{analysis.get('summary', '')} (Overlap caveat check did not run.)".strip()
        return
    if caveat:
        analysis["overlap_caveat"] = caveat
        analysis["summary"] = f"{analysis.get('summary', '')} {caveat}".strip()


def iteration_count(table, pk, library_id, slug):
    """EL-F5: 1 + the past runs sharing this library_id or slug (moved here from create_experiment,
    which shares the one experiment-row read). Fail-soft exactly as before the move: a read error
    leaves iteration at 1. This is a label counter, not an overlap verdict — it never feeds the
    none/note/warning/indeterminate result, which reads the rows independently."""
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
