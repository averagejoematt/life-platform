"""week_agreement_qa.py — the nightly same-week agreement gate (#3615 boxes 2 + 3).

THREE VERDICTS, ONE WALK, inside qa-smoke's existing nightly invocation:

  weeks:fact_agreement     every registered week-narrating surface is read, and the facts
                           they restate about the SAME week must match: cycle genesis,
                           day_n, week label, baseline weight, current weight, the named
                           plan figures. A mismatch is a FAIL naming both surfaces, the
                           fact, and each side's value.
  weeks:absence_agreement  every surface narrating a PAUSED or LAGGING source must render
                           that source's DURATION and its CAUSE, and the cause must be the
                           one `source_registry.availability_facet()` gives — never a
                           sync-failure story about a source that is paused by decree.
  weeks:rate_disclosure    a surface that shows a RATE must show its n and whether it is
                           provisional (ADR-105).

WHAT THIS GATE IS FORBIDDEN TO DO
  Re-derive a fact. Every value compared is the value a surface actually serves, taken
  from its own producer's payload. If the gate computed day_n itself and compared each
  surface to that, it would be grading the platform against a second implementation of
  the same arithmetic — and the two would agree while the pages disagreed with each
  other, which is the failure mode that made "9 green runs over a live clobber" possible.
  Surfaces are compared to EACH OTHER. Nothing here owns a truth.

WHY A DATED FACT IS ONLY COMPARED WITHIN ITS OWN AS-OF
  A chronicle installment published on 2026-09-15 says "Week 2" forever, and it is right
  forever. Today's cockpit says Week 3, and it is also right. The contradiction #3615
  names is two surfaces disagreeing about the SAME week, so each observation carries the
  as-of date its own surface stamps and dated facts are grouped by it. Anything looser
  manufactures reds out of the archive, and a gate that cries wolf at the archive is a
  gate somebody mutes.

WHY A MISSING RENDERING IS A WARN AND A CONTRADICTION IS A FAIL
  A surface can legitimately WITHHOLD a fact — pre-start, /api/journey withholds
  current_weight_lbs on purpose (the #ADR-104 honest-absence path), and an installment
  can ship without a stats line. Withholding is not lying. Rendering a DIFFERENT number
  than the page next door is. So an absent value is reported, by name, as a warn; a
  disagreement is the red.

CONTENT_TRUTH, not DEPLOY_HEALTH (#1921): these are claims the world is making right
now, and a fleet rollback cannot un-publish a stale number.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from operational import week_narration_registry as reg
from operational.census_probe import ProbeBudget

# ── small helpers ────────────────────────────────────────────────────────────
_REL_DAYS = re.compile(r"(\d+(?:\.\d+)?)\s*(d|day|days|h|hour|hours|w|week|weeks|mo|month|months|y|year|years)\b", re.I)
_UNIT_DAYS = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24.0, "hour": 1 / 24.0, "hours": 1 / 24.0, "w": 7.0, "week": 7.0, "weeks": 7.0}
_UNIT_DAYS.update({"mo": 30.0, "month": 30.0, "months": 30.0, "y": 365.0, "year": 365.0, "years": 365.0})


def _pt_date_of(iso_ts: str) -> Optional[str]:
    try:
        from common.pacific_time import pacific_date_of

        return pacific_date_of(iso_ts)
    except Exception:  # noqa: BLE001 — a clock helper must never break the sweep
        return str(iso_ts or "")[:10] or None


def _path(data: Any, dotted: Optional[str]) -> Any:
    if not dotted:
        return None
    cur = data
    for part in str(dotted).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relative_to_days(text: str) -> Optional[float]:
    """'97d ago' → 97.0, '5mo ago' → 150.0, 'today' → 0, 'yesterday' → 1. None = no duration rendered."""
    low = str(text or "").strip().lower()
    if not low:
        return None
    if low in ("today", "just now", "now"):
        return 0.0
    if low == "yesterday":
        return 1.0
    m = _REL_DAYS.search(low)
    if not m:
        return None
    return float(m.group(1)) * _UNIT_DAYS.get(m.group(2).lower(), 1.0)


# ── selectors + transforms (registry-named, dispatched here) ─────────────────
def _select_newest_post(payload: Any) -> Any:
    posts = (payload or {}).get("posts") if isinstance(payload, dict) else None
    posts = [p for p in (posts or []) if isinstance(p, dict) and p.get("date")]
    if not posts:
        return None
    return sorted(posts, key=lambda p: (str(p.get("date")), int(p.get("sequence") or 0)))[-1]


_SELECTORS = {"newest_post": _select_newest_post}


def _t_week_label_from_n(value: Any) -> tuple:
    n = _as_float(value)
    if n is None:
        return None, None
    return f"Week {int(n)}", None


def _t_last_weight_point(value: Any) -> tuple:
    points = [p for p in (value or []) if isinstance(p, dict) and p.get("date")]
    if not points:
        return None, None
    newest = sorted(points, key=lambda p: str(p["date"]))[-1]
    return _as_float(newest.get("lbs")), str(newest["date"])[:10]


def _t_stats_line_weight(value: Any) -> tuple:
    """'Weight: 318.9 lbs | Week Grade: …' → 318.9. None when the line carries no weight."""
    m = re.search(r"weight:\s*(-?\d+(?:\.\d+)?)", str(value or ""), re.I)
    return (float(m.group(1)) if m else None), None


_TRANSFORMS = {
    "week_label_from_n": _t_week_label_from_n,
    "last_weight_point": _t_last_weight_point,
    "stats_line_weight": _t_stats_line_weight,
}


def _normalize(fact_id: str, value: Any) -> Any:
    fact = reg.FACTS[fact_id]
    if value is None or value == "":
        return None
    if fact.unit == "lbs":
        return _as_float(value)
    if fact.unit == "day":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
    if fact.unit == "date":
        return str(value)[:10]
    return str(value).strip()


# ── observation ──────────────────────────────────────────────────────────────
class Observation:
    __slots__ = ("surface", "fact", "value", "as_of")

    def __init__(self, surface: str, fact: str, value: Any, as_of: Optional[str]):
        self.surface = surface
        self.fact = fact
        self.value = value
        self.as_of = as_of

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return f"Observation({self.surface}, {self.fact}={self.value!r}@{self.as_of})"


def _share_kit_url(budget: ProbeBudget, site_base: str) -> Optional[str]:
    """The newest installment's kit url, from the manifest + the PRODUCER's own key function."""
    res = budget.get(site_base + "/journal/posts.json")
    newest = _select_newest_post(res.json() if res.ok else None)
    if not newest or not newest.get("url"):
        return None
    from content.chronicle_share_kit import kit_s3_key

    key = kit_s3_key(str(newest["url"]))
    # generated/moments/share-kits/<slug>/kit.json is served at /moments/share-kits/<slug>/kit.json
    # (ADR-046: the generated/ prefix is a CloudFront origin path, never part of the url).
    return "/" + key.split("generated/", 1)[-1]


def observe(budget: ProbeBudget, site_base: str) -> tuple:
    """(observations, unrendered, unreachable) across every registered week surface."""
    observations: list = []
    unrendered: list = []
    unreachable: list = []
    for surface in reg.WEEK_SURFACES:
        locator = surface.locator
        if locator.startswith("derive:"):
            name = locator.split(":", 1)[1]
            if name != "newest_post_share_kit_url":  # pragma: no cover — registry-guarded
                unreachable.append((surface.id, f"unknown derivation {name!r}"))
                continue
            derived = _share_kit_url(budget, site_base)
            if not derived:
                unreachable.append((surface.id, "no installment in the served manifest to resolve a kit from"))
                continue
            locator = derived
        res = budget.get(site_base + locator)
        if res.deferred or res.error or res.status != 200:
            unreachable.append((surface.id, res.error or f"HTTP {res.status}"))
            continue
        payload = res.json()
        if payload is None:
            unreachable.append((surface.id, "response is not JSON"))
            continue
        default_as_of = _pt_date_of(str(_path(payload, surface.default_as_of_path) or "")) if surface.default_as_of_path else None
        if surface.select:
            payload = _SELECTORS[surface.select](payload)
            if payload is None:
                unreachable.append((surface.id, f"selector {surface.select!r} matched nothing"))
                continue
        for fact_id, ref in surface.facts:
            raw = _path(payload, ref.path)
            as_of_override = None
            if ref.transform:
                raw, as_of_override = _TRANSFORMS[ref.transform](raw)
            value = _normalize(fact_id, raw)
            if value is None:
                unrendered.append((surface.id, fact_id))
                continue
            as_of = None
            if reg.FACTS[fact_id].dated:
                as_of = as_of_override or (str(_path(payload, ref.as_of_path))[:10] if ref.as_of_path else None) or default_as_of
            observations.append(Observation(surface.id, fact_id, value, as_of))
    return observations, unrendered, unreachable


def disagreements(observations: list) -> list:
    """Every within-group contradiction: [(fact, as_of, [(surface, value), …]), …]."""
    groups: dict = {}
    for obs in observations:
        key = (obs.fact, obs.as_of if reg.FACTS[obs.fact].dated else None)
        groups.setdefault(key, []).append(obs)
    out = []
    for (fact_id, as_of), members in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if len(members) < 2:
            continue
        tol = reg.FACTS[fact_id].tolerance
        anchor = members[0]
        bad = []
        for other in members[1:]:
            if isinstance(anchor.value, (int, float)) and isinstance(other.value, (int, float)):
                if abs(float(anchor.value) - float(other.value)) > tol:
                    bad.append(other)
            elif anchor.value != other.value:
                bad.append(other)
        if bad:
            # EVERY member of the group is named, not just the outliers: an operator
            # reading the finding needs to see who agrees as well as who does not.
            out.append((fact_id, as_of, [(m.surface, m.value) for m in members]))
    return out


def check_week_agreement(Check, tier, *, site_base_url: str, budget: Optional[ProbeBudget] = None) -> list:
    check = Check("weeks:fact_agreement", "Cross-surface Week Truth", tier)
    budget = budget if budget is not None else ProbeBudget()
    try:
        observations, unrendered, unreachable = observe(budget, site_base_url.rstrip("/"))
    except Exception as exc:  # noqa: BLE001
        return [check.warn(f"week-agreement census errored (no verdict was reached): {str(exc)[:160]}")]
    bad = disagreements(observations)
    details = [f"{o.surface}: {o.fact}={o.value!r} as-of {o.as_of}" for o in observations]
    details += [f"{sid}: {fid} NOT RENDERED" for sid, fid in unrendered]
    details += [f"{sid}: UNREACHABLE — {why}" for sid, why in unreachable]
    if bad:
        lines = []
        for fact_id, as_of, members in bad:
            rendered = ", ".join(f"{s}={v!r}" for s, v in members)
            lines.append(f"{reg.FACTS[fact_id].label}{f' as-of {as_of}' if as_of else ''}: {rendered}")
        return [
            check.fail(
                f"{len(bad)} same-week fact(s) CONTRADICT across surfaces — "
                + " | ".join(lines[:4])
                + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else "")
                + " (#3615)"
            ).with_details(details)
        ]
    if unreachable:
        named = ", ".join(f"{sid} ({why})" for sid, why in unreachable[:4])
        return [
            check.warn(
                f"{len(observations)} week facts agree across {len({o.surface for o in observations})} surfaces, but "
                f"{len(unreachable)} registered surface(s) were NOT OBSERVED: {named} (#3615)"
            ).with_details(details)
        ]
    if unrendered:
        named = ", ".join(f"{sid}:{fid}" for sid, fid in unrendered[:5])
        return [
            check.warn(
                f"{len(observations)} week facts agree across {len({o.surface for o in observations})} surfaces; "
                f"{len(unrendered)} declared fact(s) were not rendered (withheld or dropped): {named} (#3615)"
            ).with_details(details)
        ]
    surfaces_seen = len({o.surface for o in observations})
    return [check.ok(f"{len(observations)} week facts agree across {surfaces_seen} narrating surfaces (#3615)").with_details(details)]


# ── box 3: the absence half ──────────────────────────────────────────────────
def _extract_freshness_rows(payload: dict) -> dict:
    out = {}
    for row in (payload or {}).get("sources") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        status = str(row.get("status") or "")
        days = row.get("days_dark")
        duration = _as_float(days)
        if duration is None and row.get("age_hours") is not None:
            duration = (_as_float(row.get("age_hours")) or 0.0) / 24.0
        cause = " ".join(str(row.get(k) or "") for k in ("desc", "status", "paused_reason", "absence_caveat"))
        out[str(row["id"])] = {
            "narrating_absence": status in ("paused", "stale", "behavioral-stale", "unknown"),
            "duration_days": duration,
            "duration_rendered": any(row.get(k) is not None for k in reg.DURATION_FIELDS),
            "cause_text": cause,
        }
    return out


def _extract_status_components(payload: dict) -> dict:
    out = {}
    for group in (payload or {}).get("groups") or []:
        for comp in (group or {}).get("components") or []:
            if not isinstance(comp, dict) or not comp.get("id"):
                continue
            rel = str(comp.get("last_sync_relative") or "")
            comment = str(comp.get("comment") or "")
            rel_days = _relative_to_days(rel)
            # "never" / "not imported" is an HONEST terminal rendering, not a missing
            # duration: nothing has ever arrived, so there is no elapsed time to state.
            explicit_never = rel.strip().lower() in ("never", "not imported", "no data")
            out[str(comp["id"])] = {
                "narrating_absence": str(comp.get("status") or "") in ("yellow", "red", "blue"),
                "duration_days": rel_days,
                "duration_rendered": bool(rel) and (rel_days is not None or explicit_never),
                "cause_text": f"{comment} {comp.get('description') or ''}",
            }
    return out


_ABSENCE_EXTRACTORS = {"freshness_rows": _extract_freshness_rows, "status_components": _extract_status_components}


#: Words that turn a mention of a broken pipe into a DENIAL of one. The registry's own
#: canonical caveat ends "…never a sync failure", and an earlier draft of this matcher
#: red-flagged the registry's own honest sentence — the gate must read a negated mention
#: as what it is. The window is short on purpose: "never a sync failure" and "not a
#: broken pipe" are denials; a sentence that says "check auth" thirty words after the
#: word "not" is not.
_NEGATORS = ("not ", "never ", "n't ", "rather than ", "no ")
_NEGATION_WINDOW = 24


def _claims_broken_pipe(low: str) -> Optional[str]:
    """The first sync-failure phrase ASSERTED (not denied) in `low`, or None."""
    for phrase in reg.SYNC_FAILURE_PHRASES:
        start = low.find(phrase)
        while start != -1:
            window = low[max(0, start - _NEGATION_WINDOW) : start]
            if not any(neg in window for neg in _NEGATORS):
                return phrase
            start = low.find(phrase, start + 1)
    return None


def _cause_verdict(facet: dict, cause_text: str, duration_days: Optional[float]) -> Optional[tuple]:
    """(severity, message) when the rendered cause fights the registry facet, else None.

    TWO SEVERITIES, and the split is the honest part:

    FAIL — a PAUSED source narrated as a broken pipe. The registry says it cannot report
      at all (garmin, ADR-074), so there is no auth to check and no webhook to fix at any
      duration. This is unambiguous and it is fixed in-tree: `site_api_status`'s comment
      for a paused source is built from this same facet.

    WARN — a LAGGING source narrated as a broken pipe INSIDE the gap the registry itself
      expects. This one is a real finding and NOT a settled one: the health panel's rule
      ("an API poller writes daily, so a 2-day gap is expired auth") and the registry's
      per-source cadence (withings 168h, notion 336h — weigh-ins and journal entries are
      behavioural) are both defensible, and choosing between them is a product call. The
      census names the source every night rather than silently preferring one rule.

    Past the declared cadence, a lagging source draws NO finding: a source expected to lag
    96h is not excused at 20 days, and requiring "by design" copy there would turn this
    gate into the thing that hides outages behind a facet.
    """
    low = (cause_text or "").lower()
    hit = _claims_broken_pipe(low)
    status = facet.get("status")
    if status == "paused":
        if hit:
            return "fail", f"attributes the silence to a broken pipe ({hit!r}) on a source the registry says is PAUSED and cannot report"
        if "paus" not in low:
            return "fail", "does not say the source is PAUSED — the registry's own cause is missing from the rendering"
        return None
    if status == "lagging":
        lag = facet.get("lag_hours")
        within = duration_days is not None and lag and (duration_days * 24.0) <= float(lag)
        if not within:
            return None  # past the declared cadence: a real anomaly, honestly narratable
        if hit:
            return "warn", f"attributes the silence to a broken pipe ({hit!r}) inside the {int(lag)}h gap the registry itself expects"
        expected = ("design", "expect", "lag", "behind", "cadence", "due")
        if not any(w in low for w in expected) and str(int(lag)) not in low:
            return "warn", f"renders no designed-lag cause for a silence inside the {int(lag)}h the registry expects"
    return None


def check_absence_agreement(Check, tier, pt_now, *, site_base_url: str, budget: Optional[ProbeBudget] = None) -> list:
    """Every narrating surface tells ONE absence story: duration + the registry's cause."""
    check = Check("weeks:absence_agreement", "Cross-surface Absence Truth", tier)
    budget = budget if budget is not None else ProbeBudget()
    try:
        from ingestion.source_registry import availability_facet, caveated_source_ids

        facets = {sid: availability_facet(sid) for sid in sorted(caveated_source_ids())}
    except Exception as exc:  # noqa: BLE001
        return [check.warn(f"source facets unreadable (no absence verdict was reached): {str(exc)[:140]}")]

    rendered: dict = {}
    unreachable = []
    for surface in reg.ABSENCE_SURFACES:
        res = budget.get(site_base_url.rstrip("/") + surface.locator)
        if res.deferred or res.error or res.status != 200 or res.json() is None:
            unreachable.append((surface.id, res.error or f"HTTP {res.status}"))
            continue
        rendered[surface.id] = _ABSENCE_EXTRACTORS[surface.extractor](res.json())

    violations: list = []  # FAIL-severity: the registry unambiguously contradicts the copy
    advisories: list = []  # WARN-severity: two honest rules disagree (named, never silent)
    durations: dict = {}
    details: list = []
    for sid, facet in facets.items():
        for surface_id, rows in rendered.items():
            row = rows.get(sid)
            if not row or not row["narrating_absence"]:
                continue
            details.append(f"{surface_id}/{sid}: {facet['status']} duration={row['duration_days']} cause={row['cause_text'][:90]!r}")
            problem = _cause_verdict(facet, row["cause_text"], row["duration_days"])
            if problem:
                severity, message = problem
                (violations if severity == "fail" else advisories).append(f"{surface_id} narrating {sid}: {message}")
            if not row["duration_rendered"]:
                line = f"{surface_id} narrating {sid}: renders NO duration for a {facet['status']} source"
                (violations if facet["status"] == "paused" else advisories).append(line)
            elif row["duration_days"] is not None:
                durations.setdefault(sid, []).append((surface_id, float(row["duration_days"])))

    for sid, pairs in durations.items():
        if len(pairs) < 2:
            continue
        lo = min(p[1] for p in pairs)
        hi = max(p[1] for p in pairs)
        # 20% of the larger figure: surfaces legitimately render the SAME silence at
        # different granularity — the freshness board says `days_dark: 176` where the
        # health panel says "5mo ago" — and a month-rounded value is up to a month adrift
        # by construction. Anything past a fifth is two different last-record dates.
        tol = max(1.5, 0.2 * hi)
        if hi - lo > tol:
            shown = ", ".join(f"{s}={d:.0f}d" for s, d in pairs)
            violations.append(f"{sid}: surfaces disagree on how long it has been silent ({shown}; tolerance {tol:.0f}d)")

    if violations:
        head = "; ".join(violations[:4])
        more = f" (+{len(violations) - 4} more)" if len(violations) > 4 else ""
        return [
            check.fail(
                f"{len(violations)} absence-narration violation(s) against source_registry's own facets: {head}{more} (#3615/#3516)"
            ).with_details(details)
        ]
    if unreachable:
        named = ", ".join(f"{s} ({w})" for s, w in unreachable)
        return [check.warn(f"absence agreement NOT OBSERVED on {named} (#3615)").with_details(details)]
    if advisories:
        head = "; ".join(advisories[:3])
        more = f" (+{len(advisories) - 3} more)" if len(advisories) > 3 else ""
        # chronic=True, class (b) — a known-recurring warn PINNED TO A FILED ISSUE (#3615's
        # named residual). It recurs every night for as long as a lagging source sits inside
        # its declared cadence while the health panel's activity heuristic calls that a
        # possible auth failure (live: notion, 11d dark inside a 336h expectation). Alarming
        # qa-smoke-warnings nightly over an already-filed product question carries zero
        # marginal information (ADR-105) — the finding stays fully visible in the email, the
        # logs and ChronicWarnCount. UN-CHRONIC THIS BRANCH the moment the owner rules on
        # which rule wins; the FAIL side (a PAUSED source narrated as a broken pipe) is
        # untouched and stays alarmed.
        return [
            check.warn(
                f"{len(advisories)} lagging-source narration(s) fight the registry's own cadence facet — the panel "
                f"heuristic vs the registry cadence is an open product call (#3615 residual): {head}{more}",
                chronic=True,
            ).with_details(details)
        ]
    return [
        check.ok(
            f"{len(facets)} paused/lagging source(s) narrate one story across "
            f"{len(rendered)} surface(s): duration + the registry's own cause (#3615)"
        ).with_details(details)
    ]


def check_rate_disclosure(Check, tier, *, site_base_url: str, budget: Optional[ProbeBudget] = None) -> list:
    """ADR-105: a rendered RATE carries its n and its provisional flag, or it is a red."""
    check = Check("weeks:rate_disclosure", "Rate Honesty", tier)
    budget = budget if budget is not None else ProbeBudget()
    findings: list = []
    details: list = []
    unreachable: list = []
    for consumer in reg.RATE_CONSUMERS:
        res = budget.get(site_base_url.rstrip("/") + consumer.locator)
        payload = res.json() if (res.status == 200 and not res.error) else None
        if payload is None:
            unreachable.append(f"{consumer.id} ({res.error or f'HTTP {res.status}'})")
            continue
        rate = _path(payload, consumer.rate_path)
        n = _path(payload, consumer.n_path)
        provisional = _path(payload, consumer.provisional_path)
        details.append(f"{consumer.id}: rate={rate!r} n={n!r} provisional={provisional!r}")
        if rate is None:
            continue  # no rate rendered = nothing to qualify (honest absence, ADR-104)
        if n is None:
            findings.append(f"{consumer.id} renders a rate ({rate}) with NO n at {consumer.n_path}")
        if provisional is None:
            findings.append(f"{consumer.id} renders a rate ({rate}) with NO provisional flag at {consumer.provisional_path}")
    if findings:
        return [check.fail("; ".join(findings[:4]) + " (ADR-105, #3615)").with_details(details)]
    if unreachable:
        return [check.warn(f"rate disclosure NOT OBSERVED on {', '.join(unreachable)} (#3615)").with_details(details)]
    return [check.ok(f"every rate consumer ({len(reg.RATE_CONSUMERS)}) renders its n and provisional flag (ADR-105)").with_details(details)]


def checks(Check, tier, pt_now, *, site_base_url: str, budget: Optional[ProbeBudget] = None) -> list:
    """All three verdicts, sharing ONE read budget so a url is fetched at most once."""
    shared = budget if budget is not None else ProbeBudget()
    out = check_week_agreement(Check, tier, site_base_url=site_base_url, budget=shared)
    out += check_absence_agreement(Check, tier, pt_now, site_base_url=site_base_url, budget=shared)
    out += check_rate_disclosure(Check, tier, site_base_url=site_base_url, budget=shared)
    return out
