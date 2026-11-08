#!/usr/bin/env python3
"""scripts/publish_snapshot_lab.py — the Laboratory's data file (L1), written ONLY for a dark build.

Owner brief 2026-11-08: "Proceed with private Laboratory prototypes using existing public-safe experiments,
hypotheses and findings. Keep interactive challenge actions disabled until their record-writing behavior is safe."
So this data file exists only when ``WEB_LAB=1`` (the same switch as ``www/src/lib/lab.js``): with the switch off,
the producer neither fetches it nor writes it, and the snapshot — manifest included — is byte-identical to a
snapshot made without this module. The deploy workflow never sets the switch.

What it carries, never recomputed (README requirement A — the snapshot is the only source of a published statistic):
  * ``/api/experiments`` — the catalogue and any live run, as served (reader vote counts dropped: reader writes stay
    out of the Lab);
  * ``/api/hypotheses`` — the pre-registered tests: the frozen spec, the deterministic verdict, the effect and its
    interval, the arm sizes, as served. Each gains ``outcome_series`` / ``condition_series``: the snapshot series id
    the spec's metric names (an id mapping, ``SERIES_OF``), or null when the snapshot has no such series;
  * ``/api/discoveries`` — ``active_hypotheses`` (a protocol's text, joined to its experiment by name) and
    ``ai_findings`` (the weekly correlation engine's corrected findings, r with its interval);
  * ``/api/supplements`` — the protocol objects (dose, timing, why, paused), and ``/api/protocols``' count.

PRIVACY (owner rulings 2026-11-03/05; fail closed): journal activity, State of Mind and video-diary data are private
on every public surface, including by inference. An experiment, test, finding or protocol whose subject or
measurement names a mood, journal, State-of-Mind, diary or self-reported-feeling read is EXCLUDED here — not its
text, not its id, not a count of how many were excluded (a denominator is an inference). The export log names them
for the operator only. A test is also excluded when ``lambdas/common/activity_publication`` does not classify each
metric of its frozen spec as public (the same rule /api/hypotheses applies; an import failure excludes every test).

No new endpoint, no non-public read: every route is a public Site API GET the platform already serves anonymously.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Callable

LAB_ENV = "WEB_LAB"
EXPERIMENTS_PATH = "/api/experiments"
HYPOTHESES_PATH = "/api/hypotheses"
DISCOVERIES_PATH = "/api/discoveries"
SUPPLEMENTS_PATH = "/api/supplements"
PROTOCOLS_PATH = "/api/protocols"
SOURCES = [EXPERIMENTS_PATH, HYPOTHESES_PATH, DISCOVERIES_PATH, SUPPLEMENTS_PATH, PROTOCOLS_PATH]
ABSENT_LAB = {
    "state": "absent",
    "absent_text": "The platform did not serve the experiments for this snapshot.",
    "source": SOURCES,
    "as_of": None,
    "notice": None,
    "lab_experiments": [],
    "lab_tests": [],
    "lab_protocols": {"groups": [], "served_protocols": None},
    "lab_findings": [],
}

# The hypothesis engine's metric names → the snapshot's series ids (scripts/publish_snapshot.py METRIC_LABELS). An id
# mapping between two vocabularies for the same served reading, never a statistic. A name not listed has no series.
SERIES_OF = {
    "recovery": "recovery_score",
    "hrv": "hrv",
    "rhr": "resting_hr",
    "total_sleep_hrs": "sleep_duration_hours",
    "protein_g": "total_protein_g",
    "calories": "total_calories_kcal",
    "steps": "steps",
    "weight_lbs": "weight_lbs",
}

# The vocabulary of a private read: mood, the journal, State of Mind, the video diary, a self-reported feeling or
# energy. Matched on what an object MEASURES or is ABOUT (its name, hypothesis, tags, protocol, measurement), never on a
# literature citation's title ("Journal of …" is a publication, not his journal).
PRIVATE_READ = re.compile(
    r"\b(?:mood\w*|journal(?:s|ing|ed)?(?! of\b)|state[ _-]of[ _-]mind|diar(?:y|ies)|vlog\w*|gratitude\w*|emotion\w*|anxiety|"
    r"well-?being|valence|how we feel|morning pages|expressive writing|subjective \w+|self-report\w*|"
    r"energy(?! expenditure| metabolism))\b",
    re.IGNORECASE,
)

STATUS_GROUP = {"active": "running", "available": "ready", "backlog": "backlog", "completed": "done", "abandoned": "done"}
_LIVE_RUN_KEYS = (
    "start_date",
    "end_date",
    "days_in",
    "progress_pct",
    "duration_days",
    "primary_metric",
    "baseline_value",
    "result_value",
    "hypothesis_confirmed",
    "compliance_pct",
    "design",
    "analysis",
    "pre_registered_at",
    "pre_registration_url",
    "measurement",
    "hoped_outcome",
    "why_now",
    "protocol",
    "key_finding",
    "result_summary",
)


def lab_enabled(env: dict | None = None) -> bool:
    """The Python twin of www/src/lib/lab.js::labEnabled — only the literal "1" turns the Lab on."""
    return (os.environ if env is None else env).get(LAB_ENV) == "1"


def private_read(*texts: Any) -> str | None:
    """The first private-read word in any of the texts (lists and dicts are flattened), or None."""
    for t in texts:
        s = t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) if t is not None else ""
        m = PRIVATE_READ.search(s)
        if m:
            return m.group(0)
    return None


def _metric_policy() -> Callable[[Any], bool]:
    """``activity_publication.hypothesis_metric_is_public`` — the rule /api/hypotheses applies. Fail closed."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
        from common.activity_publication import hypothesis_metric_is_public  # type: ignore

        return hypothesis_metric_is_public
    except Exception:  # pragma: no cover — the module is in the repo
        return lambda _m: False


def _day(v: Any) -> str | None:
    s = str(v or "")[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def _num(v: Any) -> float | int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if float(v).is_integer() and abs(v) < 1e12 else v


def _text(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _protocol_detail(h: dict) -> dict:
    return {
        "protocol": _text(h.get("protocol")),
        "why": _text(h.get("why")),
        "rationale": _text(h.get("rationale")),
        "metrics": [str(m) for m in (h.get("metrics") or []) if isinstance(m, str)],
        "duration_days": _num(h.get("duration_days")),
        "protocol_kind": _text(h.get("protocol_kind")),
        "active_since": _day(h.get("active_since")),
        "carried_over": bool(h.get("carried_over")),
        "evidence_for": [_source(s, "supports") for s in (h.get("evidence_for") or []) if isinstance(s, dict)],
        "evidence_against": [_source(s, "challenges") for s in (h.get("evidence_against") or []) if isinstance(s, dict)],
    }


def _source(s: dict, stance: str | None = None) -> dict:
    url = s.get("url") if isinstance(s.get("url"), str) and s["url"].startswith("https://") else None
    return {"title": _text(s.get("title")), "url": url, "summary": _text(s.get("summary")), "stance": stance or _text(s.get("stance"))}


def shape_experiments(payload: Any, discoveries: Any, excluded: list) -> list[dict]:
    rows = (payload or {}).get("experiments") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    active = {}
    for h in (discoveries or {}).get("active_hypotheses") or [] if isinstance(discoveries, dict) else []:
        if isinstance(h, dict) and isinstance(h.get("name"), str):
            active[h["name"].strip().lower()] = h
    out = []
    for x in rows:
        if not isinstance(x, dict) or not isinstance(x.get("id"), str):
            continue
        h = active.get(str(x.get("name") or "").strip().lower())
        detail = _protocol_detail(h) if h else None
        word = private_read(
            x.get("name"),
            x.get("hypothesis"),
            x.get("tags"),
            x.get("protocol"),
            x.get("measurement"),
            x.get("primary_metric"),
            x.get("metrics_tracked"),
            detail and [detail["protocol"], detail["why"], detail["rationale"], detail["metrics"]],
        )
        if word:
            excluded.append(("experiment", x["id"], word))
            continue
        status = str(x.get("status") or "unknown")
        live = x.get("origin") == "live"
        row = {
            "id": x["id"],
            "name": _text(x.get("name")) or x["id"],
            "status": status,
            "group": STATUS_GROUP.get(status, "backlog" if not live else "done"),
            "origin": "live" if live else "library",
            "pillar": _text(x.get("pillar")),
            "hypothesis": _text(x.get("hypothesis")),
            "planned_duration_days": _num(x.get("planned_duration_days")),
            "difficulty": _text(x.get("difficulty")),
            "evidence_tier": _text(x.get("evidence_tier")),
            "evidence_citation": _text(x.get("evidence_citation")),
            "source_url": x.get("source_url") if isinstance(x.get("source_url"), str) and x["source_url"].startswith("https://") else None,
            "citation_status": _text(x.get("citation_status")),
            # A library entry's `result_summary` is the catalogue's pitch, not a result: carried under its true name.
            "pitch": _text(x.get("result_summary")) if not live else None,
            "tags": [str(t) for t in (x.get("tags") or []) if isinstance(t, str)],
            "protocol_detail": detail,
            "run": {k: x.get(k) for k in _LIVE_RUN_KEYS} if live else None,
        }
        out.append(row)
    return sorted(out, key=lambda r: r["id"])


def _spec(spec: Any) -> dict | None:
    if not isinstance(spec, dict):
        return None
    basis = spec.get("min_effect_basis") if isinstance(spec.get("min_effect_basis"), dict) else {}
    deriv = spec.get("min_effect_derivation") if isinstance(spec.get("min_effect_derivation"), dict) else {}
    prov = spec.get("min_effect_provenance") if isinstance(spec.get("min_effect_provenance"), dict) else {}
    return {
        "condition_metric": _text(spec.get("condition_metric")),
        "condition_op": _text(spec.get("condition_op")),
        "condition_threshold": _num(spec.get("condition_threshold")),
        "outcome_metric": _text(spec.get("outcome_metric")),
        "direction": _text(spec.get("direction")),
        "lag_days": _num(spec.get("lag_days")),
        "min_days_per_arm": _num(spec.get("min_days_per_arm")),
        "min_effect": _num(spec.get("min_effect")),
        "min_effect_unit": _text(basis.get("unit") or deriv.get("unit")),
        "min_effect_kind": _text(prov.get("kind")),
        "baseline_window_days": _num(deriv.get("window_days") or basis.get("window_days")),
        "baseline_n": _num(deriv.get("n") or basis.get("n")),
        "baseline_sd": _num(deriv.get("sd") or basis.get("value")),
        "baseline_statistic": _text(basis.get("statistic")),
    }


def shape_tests(payload: Any, excluded: list, metric_is_public: Callable[[Any], bool] | None = None) -> list[dict]:
    rows = (payload or {}).get("hypotheses") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    is_public = metric_is_public or _metric_policy()
    out = []
    for h in rows:
        if not isinstance(h, dict) or not isinstance(h.get("hypothesis_id"), str):
            continue
        spec = _spec(h.get("test_spec"))
        hid = h["hypothesis_id"]
        names = [m for m in ((spec or {}).get("condition_metric"), (spec or {}).get("outcome_metric")) if m]
        word = private_read(h.get("hypothesis"), h.get("domains"), h.get("confirmation_criteria"), h.get("actionable_if_confirmed"), names)
        if word or not all(is_public(m) for m in names):
            excluded.append(("test", hid, word or "a spec metric the publication policy does not classify public"))
            continue
        cond = (spec or {}).get("condition_metric")
        outc = (spec or {}).get("outcome_metric")
        out.append(
            {
                "id": hid,
                "status": _text(h.get("status")) or "pending",
                "confidence": _text(h.get("confidence")),
                "statement": _text(h.get("hypothesis")),
                "criterion": _text(h.get("confirmation_criteria")),
                "actionable": _text(h.get("actionable_if_confirmed")),
                "pre_registered": _day(h.get("pre_registered_at") or h.get("created_at")),
                "last_checked": _day(h.get("last_checked")),
                "check_count": _num(h.get("check_count")),
                "monitoring_window_days": _num(h.get("monitoring_window_days")),
                "min_days_per_arm": _num(h.get("min_days_per_arm")),
                "spec": spec,
                "verdict": _text(h.get("deterministic_verdict")),
                "effect_size": _num(h.get("effect_size")),
                "ci95_low": _num(h.get("ci95_low")),
                "ci95_high": _num(h.get("ci95_high")),
                "n_condition": _num(h.get("n_condition")),
                "n_comparison": _num(h.get("n_comparison")),
                "days_observed": _num(h.get("days_observed")),
                "outcome_series": SERIES_OF.get(outc or ""),
                "condition_series": SERIES_OF.get(cond or ""),
            }
        )
    return sorted(out, key=lambda t: (t["pre_registered"] or "", t["id"]), reverse=True)


def shape_findings(payload: Any, excluded: list) -> list[dict]:
    rows = (payload or {}).get("ai_findings") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for f in rows:
        if not isinstance(f, dict) or not isinstance(f.get("metric_a"), str) or not isinstance(f.get("metric_b"), str):
            continue
        fid = re.sub(r"[^a-z0-9]+", "-", f"{f.get('week')}-{f['metric_a']}-{f['metric_b']}".lower()).strip("-")
        word = private_read(f.get("metric_a"), f.get("metric_b"), f.get("title"))
        if word:
            excluded.append(("finding", fid, word))
            continue
        ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
        ci = ev.get("ci95") if isinstance(ev.get("ci95"), list) and len(ev["ci95"]) == 2 else [None, None]
        out.append(
            {
                "id": fid,
                "week": _text(f.get("week")),
                "metric_a": f["metric_a"],
                "metric_b": f["metric_b"],
                "r": _num(f.get("r")),
                "n": _num(f.get("n")),
                "n_eff": _num(f.get("n_eff")),
                "ci95_low": _num(ci[0]),
                "ci95_high": _num(ci[1]),
                "fdr_corrected": bool(ev.get("fdr_significant")),
                "level": _text(ev.get("level")),
            }
        )
    return sorted(out, key=lambda r: (r["week"] or "", r["id"]), reverse=True)


def shape_protocols(supplements: Any, protocols: Any, excluded: list) -> dict:
    groups = (supplements or {}).get("groups") if isinstance(supplements, dict) else None
    out = []
    for gid, g in (groups or {}).items() if isinstance(groups, dict) else []:
        if not isinstance(g, dict):
            continue
        items = []
        for it in g.get("items") or []:
            if not isinstance(it, dict) or not isinstance(it.get("key"), str):
                continue
            word = private_read(
                it.get("name"),
                it.get("why"),
                it.get("pausedReason"),
                it.get("impact"),
                it.get("watching"),
                it.get("measured_by"),
                it.get("hoped_outcome"),
            )
            if word:
                excluded.append(("protocol", it["key"], word))
                continue
            sources = [_source(s) for s in (it.get("sources") or []) if isinstance(s, dict)]
            items.append(
                {
                    "id": it["key"],
                    "name": _text(it.get("name")) or it["key"],
                    "dose": _text(it.get("dose")),
                    "timing": _text(it.get("timing")),
                    "why": _text(it.get("why")),
                    "paused": bool(it.get("paused")),
                    "paused_reason": _text(it.get("pausedReason")),
                    "evidence_tier": _text(it.get("ev")),
                    "experiment": _text(it.get("experiment")),
                    "sources": sources,
                }
            )
        out.append({"id": str(gid), "name": _text(g.get("name")) or str(gid), "desc": _text(g.get("desc")), "items": items})
    served = (protocols or {}).get("count") if isinstance(protocols, dict) else None
    return {"groups": out, "served_protocols": _num(served)}


def shape(
    experiments: Any, hypotheses: Any, discoveries: Any, supplements: Any, protocols: Any, log: Callable[[str], None] = print
) -> dict:
    """The data file from the served payloads; ABSENT_LAB when /api/experiments is missing or malformed."""
    if not isinstance(experiments, dict) or not isinstance(experiments.get("experiments"), list):
        return json.loads(json.dumps(ABSENT_LAB))
    excluded: list = []
    data = {
        "state": "ok",
        "absent_text": None,
        "source": SOURCES,
        "as_of": None,
        "notice": _text((hypotheses or {}).get("_notice")) if isinstance(hypotheses, dict) else None,
        "lab_experiments": shape_experiments(experiments, discoveries, excluded),
        "lab_tests": shape_tests(hypotheses, excluded),
        "lab_protocols": shape_protocols(supplements, protocols, excluded),
        "lab_findings": shape_findings(discoveries, excluded),
    }
    for kind, oid, word in excluded:  # the operator's log only — never the data file
        log(f"  lab: excluded {kind} {oid} (private read: {word!r})")
    return data


def live_lab(get: Callable[[str], Any], log: Callable[[str], None] = print) -> dict:
    """Fetch the public routes; a failure of /api/experiments leaves the Lab's data file absent (the page says so)."""

    def opt(path: str) -> Any:
        try:
            return get(path)
        except Exception as exc:  # noqa: BLE001 — an optional route missing is an absent block, never a partial row
            log(f"  lab: {path} unavailable ({exc})")
            return None

    try:
        experiments = get(EXPERIMENTS_PATH)
    except Exception as exc:  # noqa: BLE001
        log(f"  lab: experiments unavailable ({exc}); lab.json written absent")
        return json.loads(json.dumps(ABSENT_LAB))
    return shape(experiments, opt(HYPOTHESES_PATH), opt(DISCOVERIES_PATH), opt(SUPPLEMENTS_PATH), opt(PROTOCOLS_PATH), log)


def fixture_lab(fixtures_dir: str) -> dict:
    """The committed sample (content/fixtures/lab.json, already in data-file shape)."""
    path = os.path.join(fixtures_dir, "lab.json")
    if not os.path.exists(path):
        return json.loads(json.dumps(ABSENT_LAB))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _subject(detail: Any) -> Any:
    """What a protocol is about (its text and metrics) — not the literature it cites."""
    if not isinstance(detail, dict):
        return None
    return [detail.get("protocol"), detail.get("why"), detail.get("rationale"), detail.get("metrics")]


def resolve_and_validate(payload: dict, public: dict[str, list[dict]], series_ids: set[str] | None = None) -> dict:
    """Stamp ``as_of`` from the public edition, null every series id the snapshot does not carry, check the shape.

    Raises ValueError (the caller maps it to SchemaError) on a malformed ok payload, and on any private-read word that
    reached the file (the second, independent half of the privacy screen)."""
    if payload.get("state") != "ok":
        return payload
    editions = public.get("edition") or []
    payload["as_of"] = max((e.get("as_of") for e in editions if e.get("as_of")), default=None)
    have = series_ids if series_ids is not None else {o["id"] for o in public.get("metric", [])}
    for key in ("lab_experiments", "lab_tests", "lab_findings"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"lab.json: {key} must be a list")
    if not isinstance((payload.get("lab_protocols") or {}).get("groups"), list):
        raise ValueError("lab.json: lab_protocols.groups must be a list")
    ids = [x.get("id") for x in payload["lab_experiments"]]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9._-]+", i) for i in ids):
        raise ValueError("lab.json: experiment ids must be unique url-safe strings")
    for t in payload["lab_tests"]:
        if not isinstance(t.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9._-]+", t["id"]):
            raise ValueError(f"lab.json: a test id is not url-safe: {t.get('id')!r}")
        for k in ("outcome_series", "condition_series"):
            if t.get(k) not in have:
                t[k] = None
        lo, hi = t.get("ci95_low"), t.get("ci95_high")
        if (lo is None) != (hi is None) or (lo is not None and lo > hi):
            raise ValueError(f"lab.json: test {t['id']} carries a malformed interval")
    for x in payload["lab_experiments"]:
        if x.get("group") not in ("running", "ready", "backlog", "done"):
            raise ValueError(f"lab.json: experiment {x.get('id')} has no group")
    word = private_read(
        [(x.get("name"), x.get("hypothesis"), x.get("tags"), _subject(x.get("protocol_detail"))) for x in payload["lab_experiments"]],
        [(t.get("statement"), t.get("criterion"), t.get("spec")) for t in payload["lab_tests"]],
        [(f.get("metric_a"), f.get("metric_b")) for f in payload["lab_findings"]],
        [(i.get("name"), i.get("why"), i.get("paused_reason")) for g in payload["lab_protocols"]["groups"] for i in g.get("items") or []],
    )
    if word:
        raise ValueError(f"lab.json: a private read ({word!r}) reached the Lab's data file")
    return payload
