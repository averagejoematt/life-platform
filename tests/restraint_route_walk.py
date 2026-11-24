#!/usr/bin/env python3
"""tests/restraint_route_walk.py — every public GET route, served from a table that holds SYNTHETIC
restraint habits outside the nameable categories (#5948). Run by `tests/test_restraint_labels_5948.py`
in a fresh interpreter, so no handler cache carries the fixture into (or out of) the rest of the suite.

    python3 tests/restraint_route_walk.py [--ungated]

THE RULE (docs/DATA_GOVERNANCE.md): since #6224 no restraint category is named in public and no restraint
figure is published (before it, the alcohol and food-delivery categories were named and the rest aggregated). So plant restraint habits with names nobody
has ruled on — "Restraint Canary Alpha" … "Delta", each marked a restraint through a DIFFERENT signal,
so the walk proves the union and not one of its members — beside the two nameable ones, and read every
public response for a canary's name, slug or tracker id.

  canary    tracker group   key in vice_streaks   registry flag
  Alpha     Vice            yes                   -
  Bravo     Core            yes                   -      (the stored streak key alone)
  Charlie   Optimize        -                     vice   (the owner's registry flag alone)
  Delta     Vice            -                     -      (the tracker group alone: a habit added today)

The names are planted everywhere a habit name is really stored, not only where a handler is known to
read one: every Habitify status (and the ingest's own `by_group.habits_done` and `habits` roll-ups),
every `habit_scores.vice_streaks` map and `missed_tier0` list, the owner's registry, a protocol row's
`related_habits`, and the public domains config. A route that serves any of them by name fails, whether
or not it is one this issue knew about.

`--ungated` is the mutation control: the policy names every restraint habit (`category()` answers for
all of them). The same walk must then find the canaries on the routes the policy governs — so the test
proves it can see a reintroduced label on each of them, and pins WHICH routes the policy governs.

The public rows around the canaries, the fake table and the dead S3/HTTP/Bedrock clients are the
journal-activity walk's (`tests/journal_activity_route_walk.py`), reused rather than rebuilt. Its clock
is not frozen here: this walk compares nothing across runs, it only reads each body for a token.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import journal_activity_route_walk as jw  # noqa: E402 — the fake table, the wiring and the base public rows

rw = jw.rw

NAMEABLE = ("No alcohol", "No solo takeout")
CANARIES = ("Restraint Canary Alpha", "Restraint Canary Bravo", "Restraint Canary Charlie", "Restraint Canary Delta")
ORDINARY = "Synthetic Habit 1"  # one of the base walk's public, non-restraint habits
# name -> (tracker group, in vice_streaks, registry flag)
SIGNALS = {
    NAMEABLE[0]: ("Vice", True, False),
    NAMEABLE[1]: ("Vice", True, False),
    CANARIES[0]: ("Vice", True, False),
    CANARIES[1]: ("Core", True, False),
    CANARIES[2]: ("Optimize", False, True),
    CANARIES[3]: ("Vice", False, False),
}


def _ids() -> dict:
    """A classified-public tracker id per planted habit (an unclassified habit is omitted by the activity
    policy before the restraint policy is ever asked — that would make this walk pass for the wrong reason)."""
    from common import activity_publication as AP

    spare = sorted(AP.PUBLIC_HABIT_IDS)[3 : 3 + len(SIGNALS)]  # the base walk uses the first three
    assert len(spare) == len(SIGNALS)
    return dict(zip(SIGNALS, spare))


def tokens() -> list:
    """What must not reach any public body: each canary's name, its slugs and its tracker id — and, since #6224
    (no restraint category is nameable: no explicit owner approval was found), the two formerly nameable ones too."""
    out = []
    ids = _ids()
    for name in CANARIES + NAMEABLE:
        out += [name.lower(), name.lower().replace(" ", "-"), name.lower().replace(" ", "_"), ids[name].lower()]
    return out


def _augment(rows: list) -> list:
    ids = _ids()
    user = "USER#matthew"
    for i, r in enumerate(rows):
        pk = str(r.get("pk", ""))
        if pk.endswith("#SOURCE#habitify"):
            statuses = r["habit_statuses"]
            for k, (name, (group, _streak, _flag)) in enumerate(SIGNALS.items()):
                done = (i + k) % 4 != 0
                statuses[name] = {
                    "status": "completed" if done else "failed",
                    "habit_id": ids[name],
                    "group": group,
                    "scheduled_today": True,
                    "periodicity": "daily",
                    "current_value": Decimal("1") if done else Decimal("0"),
                    "target_value": Decimal("1"),
                }
            # The ingest's roll-ups over EVERY habit, as it stores them — names included.
            by_group: dict = {}
            for name, st in statuses.items():
                g = by_group.setdefault(st["group"], {"completed": 0, "possible": 0, "habits_done": []})
                g["possible"] += 1
                if st["status"] == "completed":
                    g["completed"] += 1
                    g["habits_done"].append(name)
            for g in by_group.values():
                g["pct"] = Decimal(str(round(g["completed"] / g["possible"], 4)))
            r["by_group"] = by_group
            r["habits"] = {n: Decimal("1") if s["status"] == "completed" else Decimal("0") for n, s in statuses.items()}
        elif pk.endswith("#SOURCE#habit_scores"):
            day = int(str(r["sk"])[-2:])
            r["vice_streaks"] = {n: Decimal((day + k) % 9) for k, (n, sig) in enumerate(SIGNALS.items()) if sig[1]}
            r["vices_held"] = Decimal(sum(1 for v in r["vice_streaks"].values() if v > 0))
            r["vices_total"] = Decimal(len(r["vice_streaks"]))
            r["missed_tier0"] = [CANARIES[0], ORDINARY]
        elif pk == user and r.get("sk") == "PROFILE#v1":
            r["habit_registry"] = {n: {"status": "active", "tier": 2, "vice": True} for n, sig in SIGNALS.items() if sig[2]}
    rows.append(
        {
            "pk": f"{user}#SOURCE#protocols",
            "sk": "PROTOCOL#synthetic",
            "id": "synthetic",
            "name": "Synthetic Protocol",
            "related_habits": [ORDINARY, *NAMEABLE, *CANARIES],
        }
    )
    return rows


DOMAINS_CONFIG = {
    "domains": [
        {"id": "discipline", "name": "Synthetic Domain", "habit_names": [ORDINARY, *NAMEABLE, *CANARIES], "order": 1},
    ]
}


def _ungate() -> None:
    """The mutation control: the policy's absence — every restraint habit is nameable."""
    from common import restraint_publication as RP

    RP.category = lambda _name: "ungated"


def walk(ungated: bool = False) -> dict:
    jw.FROZEN = datetime.now(timezone.utc)  # the base rows are dated relative to this; the real clock, not a frozen one
    base_rows = jw._rows
    jw._rows = lambda variant: _augment(base_rows(variant))
    if ungated:
        _ungate()
    L = jw._wire("gaps")

    from web import site_api_protocols as P

    P._domains_cache = json.loads(json.dumps(DOMAINS_CONFIG))

    toks = tokens()
    out = {"routes": 0, "answered": 0, "raised": {}, "leaks": {}, "figures": {}, "bodies": {}}
    for path in rw.route_paths(L):
        out["routes"] += 1
        event = {
            "rawPath": path,
            "path": path,
            "httpMethod": "GET",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {},
            "queryStringParameters": {},
        }
        try:
            resp = L._dispatch_route(event, path, "GET")
            if resp is None and callable(L.ROUTES.get(path)):
                resp = L.ROUTES[path]()
        except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
            out["raised"][path] = type(e).__name__
            continue
        if not isinstance(resp, dict):
            continue
        out["answered"] += 1
        blob = json.dumps(resp, default=str)
        hits = sorted({t for t in toks if t in blob.lower()})
        if hits:
            out["leaks"][path] = hits
        figs = restraint_figures(resp.get("body"))
        if figs:
            out["figures"][path] = figs
        if path in KEEP_BODIES:
            body = resp.get("body")
            out["bodies"][path] = json.loads(body) if isinstance(body, str) else body
    out["unparsed_queries"] = rw.STATS["unparsed_queries"]
    return out


# #6224: the keys that carried a restraint FIGURE (a count of the private categories, a held/tracked total, a
# streak or relapse aggregate) before no restraint figure was published. A non-empty restraint list counts too.
FIGURE_KEYS = frozenset({"restraints_unnamed", "unnamed", "total_tracked", "total_held", "vices_held", "vices_total", "relapses_90d"})
FIGURE_LISTS = frozenset({"vice_streaks", "vice_timeline", "vices"})


def restraint_figures(body) -> list:
    """Every restraint-figure key (or non-empty restraint list) anywhere in a served body, as sorted key paths."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    found: set = set()

    def walk_(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in FIGURE_KEYS or (k in FIGURE_LISTS and isinstance(v, list) and v):
                    found.add(f"{path}.{k}")
                walk_(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk_(v, f"{path}[]")

    walk_(body, "")
    return sorted(found)


# The routes whose bodies the test reads for the non-vacuity and wire-shape assertions.
KEEP_BODIES = ("/api/vice_streaks", "/api/habits", "/api/habit_registry", "/api/mind_overview", "/api/domains", "/api/protocols")


if __name__ == "__main__":
    import io
    import logging

    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; keep stdout for the one JSON line
    try:
        result = walk(ungated="--ungated" in sys.argv)
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(result, default=str))
