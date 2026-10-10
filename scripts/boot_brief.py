#!/usr/bin/env python3
"""scripts/boot_brief.py — the boot contract (#3314, epic #2842): what a session or a
routine reads FROM THE MODEL at boot, and the brief that renders it.

THE CONTRACT
  A booting session or routine takes the facts in BOOT_CONTRACT from
  ``model/platform_model.json`` — never from CLAUDE.md, a handover, or memory. Each entry
  names the model path the fact is read from and why an operator needs it before acting.
  Prose may POINT at the model (docs/CHARTER.md "Session boot"); it may not restate a
  boot fact with a different value. The SessionStart hook
  (``scripts/hooks/session_preflight.py``) prints this brief, so the boot that happens on
  every session IS a consumer of the model, not a re-reader of prose.

WHAT PINS IT (tests/test_boot_contract_3314.py)
  * every BOOT_CONTRACT path resolves in the committed model (registry ↔ model);
  * the brief's numbers equal the model's (derivation guard — the brief cannot restate);
  * the SessionStart hook renders this module, and settings.json registers the hook;
  * a mutated model changes the brief (the gate can fail, not merely pass);
  * a model whose ``meta.counts`` disagree with its planes renders a STALE line — the
    dead-man that turns a hand-edit into something a booting session sees;
  * CLAUDE.md's hand-stated copies of a boot fact agree with the model or are absent.

  #3603 adds ONE line that is not a model fact and says so: the review lenses whose grades
  have been carried forward past the operating calendar's cap. It is read from the review
  artifacts through scripts/operating_calendar.py (the one home for the cap), printed
  fail-soft with its reason, and it is deliberately NOT a BOOT_CONTRACT entry — the model
  carries the platform's shape, not the review's clock.

  python3 scripts/boot_brief.py             # the brief, as the SessionStart hook prints it
  python3 scripts/boot_brief.py --json      # the same facts as JSON (a routine's boot)
  python3 scripts/boot_brief.py --model P   # render another model file (tests)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "model" / "platform_model.json"


class BootFact(NamedTuple):
    # A NamedTuple, not a dataclass: the hook loads this module by path, and a dataclass
    # resolves its annotations through sys.modules[<name>] — absent for a spec-loaded
    # module, which is exactly how the SessionStart hook imports it.
    key: str
    path: str  # dotted path into the model, or "derived:<name>" for a computed fact
    why: str


# One entry per fact a boot reads from the model. Adding a fact here is the ONLY way a
# number enters the brief; the contract test walks this tuple.
BOOT_CONTRACT: tuple[BootFact, ...] = (
    BootFact("lambdas", "meta.counts.lambdas", "the fleet — what 'all Lambdas' means today (CLAUDE.md's ~N is a pointer, not the count)"),
    BootFact(
        "scheduled_lambdas", "meta.counts.scheduled_lambdas", "how many run on a clock — the operator's blast radius for a cron change"
    ),
    BootFact("schedules", "meta.counts.schedules", "one row per (lambda, cron) — multi-schedule lambdas count each"),
    BootFact("alarms", "meta.counts.alarms", "the alarm estate the operator triages (the #795 inventory + composites)"),
    BootFact(
        "alarms_by_routing", "meta.counts.alarms_by_routing", "who gets woken: paging vs urgent vs digest — the routing facet #3314 added"
    ),
    BootFact("partitions", "meta.counts.partitions", "the ADR-077 census size"),
    BootFact("edges", "meta.counts.edges", "module→partition edges — what blast_radius answers over"),
    BootFact("contracts_enrolled", "meta.counts.contracts_enrolled", "producer/consumer pairs with a live contract (#2847)"),
    BootFact("contracts_ratchet", "meta.counts.contracts_ratchet", "the enrolled floor — it only grows"),
    BootFact("mcp_tools", "meta.counts.mcp_tools", "the MCP surface (the registry count, never the grep)"),
    BootFact(
        "privacy_sources_owner_only",
        "meta.counts.privacy_sources_owner_only",
        "partitions that must never reach a public surface or an AI narrative",
    ),
    BootFact(
        "privacy_sources_owner_published",
        "meta.counts.privacy_sources_owner_published",
        "Tier-2-class data published by recorded consent (ADR-155)",
    ),
    BootFact(
        "privacy_fields_owner_only",
        "meta.counts.privacy_fields_owner_only",
        "field-level owner-only rulings (the withings trio and its #3045 port)",
    ),
    BootFact("consent", "privacy.consent", "the ADR + date every owner_published stamp cites"),
    BootFact("next_runs", "derived:next_runs", "the next fixed-time crons after now (UTC) — what is about to happen on the platform"),
)

_CONSISTENCY = (
    ("meta.counts.lambdas", "lambdas"),
    ("meta.counts.alarms", "alarms"),
    ("meta.counts.partitions", "partitions"),
    ("meta.counts.edges", "edges"),
    ("meta.counts.schedules", "schedules"),
    ("meta.counts.contracts", "contracts"),
)


def load_model(path: pathlib.Path = MODEL_PATH) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def resolve(model: dict, path: str):
    cur = model
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def next_runs(model: dict, now: _dt.datetime, n: int = 3) -> list[dict]:
    """The next `n` fixed-time schedule rows after `now` (UTC), wrapping past midnight.
    Day-of-week/month fields are NOT evaluated — this is 'what the clock says next', and
    it says so; a MON-only cron shows on a Tuesday with its expr visible."""
    rows = [r for r in model.get("schedules", []) if r.get("utc")]
    if not rows:
        return []
    hhmm = now.strftime("%H:%M")
    ordered = sorted(rows, key=lambda r: (r["utc"] <= hhmm, r["utc"], r["lambda"]))
    return ordered[:n]


def consistency(model: dict) -> list[str]:
    """Problems that make the committed model untrustworthy at boot (a hand-edit, a
    partial regeneration, a schema the brief does not know). Empty = consistent."""
    problems: list[str] = []
    if "meta" not in model or "counts" not in model.get("meta", {}):
        return ["meta.counts missing — not a generated model"]
    for path, plane in _CONSISTENCY:
        try:
            declared = resolve(model, path)
        except KeyError:
            problems.append(f"{path} missing")
            continue
        actual = len(model.get(plane, ()))
        if declared != actual:
            problems.append(f"{path}={declared} but len({plane})={actual}")
    return problems


def stale_review_lenses(today: _dt.date | None = None, repo: pathlib.Path = ROOT) -> dict:
    """Which review lenses a reader is being shown a grade for that nobody has re-derived
    inside the carry-forward cap (#3603).

    Fail-soft by construction: a boot brief that raises kills the SessionStart hook for
    every session, so a failure here prints its own reason on the line instead of a
    traceback. The verdict itself is the calendar's — the cap and the parser live there.
    """
    out: dict = {"expired": [], "newest": None, "cap_days": None, "error": None}
    try:
        import importlib.util

        path = repo / "scripts" / "operating_calendar.py"
        spec = importlib.util.spec_from_file_location("_operating_calendar_for_boot", path)
        oc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(oc)
        runs = oc.load_grade_runs(str(repo))
        out["cap_days"] = oc.CARRY_FORWARD_MAX_DAYS
        if runs:
            out["newest"] = max(runs, key=lambda r: r[0])[0].isoformat()
        out["expired"] = [
            {"lens": row["lens"], "age_days": row["age_days"]} for row in oc.expired_carry_forward(runs, today or _dt.date.today())
        ]
    except Exception as exc:  # pragma: no cover - exercised by the missing-script test
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def facts(model: dict, now: _dt.datetime | None = None) -> dict:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    out: dict = {}
    for fact in BOOT_CONTRACT:
        if fact.path == "derived:next_runs":
            out[fact.key] = next_runs(model, now)
        else:
            out[fact.key] = resolve(model, fact.path)
    out["_consistency"] = consistency(model)
    out["_review_carry_forward"] = stale_review_lenses(now.date())
    out["_now_utc"] = now.strftime("%Y-%m-%dT%H:%MZ")
    return out


def render_lines(model: dict, now: _dt.datetime | None = None) -> list[str]:
    """The hook-shaped brief: two-column lines matching session_preflight's layout."""
    f = facts(model, now)
    problems = f["_consistency"]
    model_line = (
        "CONSISTENT (meta.counts == plane sizes)"
        if not problems
        else "STALE — " + "; ".join(problems) + " — regenerate: python3 scripts/generate_platform_model.py"
    )
    routing = " · ".join(f"{k} {v}" for k, v in f["alarms_by_routing"].items())
    runs = " · ".join(f"{r['utc']}Z {r['lambda']}" for r in f["next_runs"]) or "no fixed-time schedules"
    consent = f["consent"]
    carry = f["_review_carry_forward"]
    cap = carry["cap_days"] if carry["cap_days"] is not None else "?"
    if carry["error"]:
        stale = f"UNREAD ({carry['error']})"
    elif not carry["expired"]:
        stale = f"[] (newest full-lens grades {carry['newest'] or 'none'})"
    else:
        rows = ", ".join(
            f"{r['lens']} ({r['age_days']}d)" if r["age_days"] is not None else f"{r['lens']} (no source run)" for r in carry["expired"]
        )
        stale = f"[{rows}] — expired, re-verify or refile before the next delta carries them again"
    return [
        f"  model       {model_line}",
        f"  fleet       {f['lambdas']} lambdas · {f['scheduled_lambdas']} scheduled ({f['schedules']} crons) · {f['mcp_tools']} MCP tools",
        f"  next runs   {runs}   (clock order at {f['_now_utc']}; day-of-week not evaluated)",
        f"  alarms      {f['alarms']} · {routing}",
        f"  privacy     {f['privacy_sources_owner_only']} owner-only + {f['privacy_sources_owner_published']} owner-published sources · "
        f"{f['privacy_fields_owner_only']} owner-only fields · consent {consent.get('adr')} ({consent.get('date')})",
        f"  data        {f['partitions']} partitions · {f['edges']} edges · {f['contracts_enrolled']} contracts enrolled (floor {f['contracts_ratchet']})",
        f"  review      lenses not graded from scratch in >{cap}d: {stale}",
        "  query       scripts/blast_radius.py --touches P | --feeds M | --alarm A | --at HH | --privacy S | --lambda L",
        "  read        docs/CHARTER.md first · docs/DEPENDENCY_GRAPH.md is the model's rendering · prose is depth, not prerequisite",
    ]


# ---------------------------------------------------------------------------------------
# #4709 — live red alarms at boot. NOT a model fact (the model carries the estate's shape,
# not CloudWatch's clock), so it is a separate fail-soft function the SessionStart hook
# calls; render_lines() stays offline-pure. Read-only: describe_alarms + describe_alarm_history.
ALARM_REGIONS = ("us-west-2", "us-east-1")
FLAP_WINDOW_HOURS = 24
_MAX_HISTORY_PAGES = 5


def _fmt_duration(delta: _dt.timedelta) -> str:
    secs = max(int(delta.total_seconds()), 0)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    if days:
        return f"{days}d{hours:02d}h"
    return f"{hours}h{rem // 60:02d}m"


def _entered_alarm(item: dict) -> bool:
    """A StateUpdate history item whose new state is ALARM (HistoryData is a JSON string)."""
    try:
        data = item.get("HistoryData")
        data = json.loads(data) if isinstance(data, str) else (data or {})
        return (data.get("newState") or {}).get("stateValue") == "ALARM"
    except (ValueError, AttributeError):
        return "to ALARM" in (item.get("HistorySummary") or "")


def _make_cw_client(region: str):
    import boto3
    from botocore.config import Config

    cfg = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
    return boto3.client("cloudwatch", region_name=region, config=cfg)


def red_alarm_lines(now: _dt.datetime | None = None, client_factory=None, regions=ALARM_REGIONS) -> list[str]:
    """One line per alarm in ALARM (name + red duration from StateTransitionedTimestamp,
    falling back to StateUpdatedTimestamp) and one per alarm that fired and cleared in the
    last 24h. Any AWS failure yields a single UNVERIFIED line — never blank, never 'none'
    unless the read succeeded and found nothing."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    factory = client_factory or _make_cw_client
    red: list[tuple[_dt.timedelta, str, str]] = []
    fired: dict[str, tuple[_dt.datetime, str]] = {}
    try:
        for region in regions:
            cw = factory(region)
            tags = "" if region == regions[0] else f" [{region}]"
            kw = {"StateValue": "ALARM", "AlarmTypes": ["CompositeAlarm", "MetricAlarm"], "MaxRecords": 100}
            while True:
                resp = cw.describe_alarms(**kw)
                for a in list(resp.get("MetricAlarms") or []) + list(resp.get("CompositeAlarms") or []):
                    since = a.get("StateTransitionedTimestamp") or a.get("StateUpdatedTimestamp")
                    age = now - since if since else _dt.timedelta(0)
                    red.append((age, a.get("AlarmName", "?") + tags, "" if since else " (red since unknown)"))
                if not resp.get("NextToken"):
                    break
                kw["NextToken"] = resp["NextToken"]
            hkw = {
                # The API default is metric alarms only — without this a composite that fired
                # and cleared in the window is invisible here (#3390/#3503).
                "AlarmTypes": ["CompositeAlarm", "MetricAlarm"],
                "HistoryItemType": "StateUpdate",
                "StartDate": now - _dt.timedelta(hours=FLAP_WINDOW_HOURS),
                "EndDate": now,
                "MaxRecords": 100,
            }
            for _ in range(_MAX_HISTORY_PAGES):
                resp = cw.describe_alarm_history(**hkw)
                for item in resp.get("AlarmHistoryItems") or []:
                    if _entered_alarm(item):
                        name = item.get("AlarmName", "?") + tags
                        ts = item.get("Timestamp")
                        if ts and (name not in fired or ts > fired[name][0]):
                            fired[name] = (ts, item.get("HistorySummary") or "")
                if not resp.get("NextToken"):
                    break
                hkw["NextToken"] = resp["NextToken"]
    except Exception as exc:  # noqa: BLE001 — offline/no creds/throttle must degrade, not crash
        return [f"  red alarms  UNVERIFIED (CloudWatch read failed: {type(exc).__name__}: {str(exc)[:80]}) — this is not a clean board"]
    lines: list[str] = []
    red_names = {n for _, n, _ in red}
    for age, name, note in sorted(red, key=lambda r: -r[0].total_seconds()):
        lines.append(f"  RED ALARM   {name} — in ALARM for {_fmt_duration(age)}{note}")
    for name, (ts, _summary) in sorted(fired.items()):
        if name not in red_names:
            lines.append(f"  flapped 24h {name} — fired {_fmt_duration(now - ts)} ago, now cleared")
    if not lines:
        lines.append(f"  red alarms  none in ALARM, none fired in the last {FLAP_WINDOW_HOURS}h (read {', '.join(regions)})")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit the facts as JSON (a routine's boot)")
    parser.add_argument("--model", default=str(MODEL_PATH), help="model file to render (default: model/platform_model.json)")
    args = parser.parse_args()
    model = load_model(pathlib.Path(args.model))
    if args.json:
        print(json.dumps(facts(model), indent=2, sort_keys=True, default=str))
        return 0
    print("── boot brief · model/platform_model.json (#3314) " + "─" * 18)
    for line in render_lines(model):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
