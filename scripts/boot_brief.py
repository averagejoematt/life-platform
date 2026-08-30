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


def facts(model: dict, now: _dt.datetime | None = None) -> dict:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    out: dict = {}
    for fact in BOOT_CONTRACT:
        if fact.path == "derived:next_runs":
            out[fact.key] = next_runs(model, now)
        else:
            out[fact.key] = resolve(model, fact.path)
    out["_consistency"] = consistency(model)
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
    return [
        f"  model       {model_line}",
        f"  fleet       {f['lambdas']} lambdas · {f['scheduled_lambdas']} scheduled ({f['schedules']} crons) · {f['mcp_tools']} MCP tools",
        f"  next runs   {runs}   (clock order at {f['_now_utc']}; day-of-week not evaluated)",
        f"  alarms      {f['alarms']} · {routing}",
        f"  privacy     {f['privacy_sources_owner_only']} owner-only + {f['privacy_sources_owner_published']} owner-published sources · "
        f"{f['privacy_fields_owner_only']} owner-only fields · consent {consent.get('adr')} ({consent.get('date')})",
        f"  data        {f['partitions']} partitions · {f['edges']} edges · {f['contracts_enrolled']} contracts enrolled (floor {f['contracts_ratchet']})",
        "  query       scripts/blast_radius.py --touches P | --feeds M | --alarm A | --at HH | --privacy S | --lambda L",
        "  read        docs/CHARTER.md first · docs/DEPENDENCY_GRAPH.md is the model's rendering · prose is depth, not prerequisite",
    ]


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
