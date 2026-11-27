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

`--state low|high --now ISO` is the INVARIANCE axis (#6224, owner ruling 2026-11-24: no figure from which a restraint
habit's count or behaviour can be derived): only the restraint habits move — every planted restraint habit done
(`high`) or missed (`low`) on every day, every stored restraint streak 90 or 0 — with the ordinary habits, every other
row and the clock (frozen at `--now`) held fixed, so `tests/test_restraint_public_figures_6224.py` can require every
public route's body to be identical across the two states. The stored ingest roll-ups (`by_group`, `habits`) and the
stored tier-0 counts and streak are recomputed per state the way the ingest and the scorer write them, so a route that
reads a stored figure which counted a restraint habit moves and fails by name.

`--fd early|late` is the FOOD-DELIVERY axis (#6224, owner ruling 2026-11-26: the food-delivery source's last-recorded
date is private): only the food_delivery partition's newest row and the stored character manifest's food_delivery
`latest_day` move (two dates far apart), so a route that says when that source last recorded moves and fails.
`--fd-public` is its control (the source re-classified public, the state before the ruling). `--mind-scored` is the
control for the Mind assertion (#6224: Mind is not scored in public): `public_sheet` stops replacing Mind with the
not-scored shape, so the stored variant's Mind numbers reach the character routes and `mind_numbers` must see them.

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
    # #6224: the restraint-derived names a stored character variant carried (an effect read from the restraint streaks,
    # its condition, the restraint component and its event label).
    out += [EFFECT_CANARY.lower()]
    # #6224/#6223: the policy's own withheld words (the restraint component, the condition, the config's restraint-
    # conditioned effect names) — the ONE list the public-copies guard's archive rule reads too.
    from health import character_privacy as CP

    out += CP.withheld_public_tokens(_engine_config())
    # #6224 (owner ruling 2026-11-26 23:50Z): a reconstructed event's INTERNAL provenance never reaches a public body
    out += [k.lower() for k in CP.PROVENANCE_KEYS]
    return out


def _engine_config() -> dict:
    with open(os.path.join(os.path.dirname(_HERE), "config", "character_sheet.json"), encoding="utf-8") as fh:
        return json.load(fh)


class _ConfigS3(rw._DeadClient):
    """#6224: an S3 client that serves the repo's engine config (so /api/character_config answers and the walk reads
    what it serves) and nothing else — every other call is dead, as in the base walk."""

    def get_object(self, Bucket=None, Key=None, **_kw):  # noqa: N803 — boto3's spelling
        if str(Key).endswith("/character_sheet.json"):
            import io

            return {"Body": io.BytesIO(json.dumps(_engine_config()).encode())}
        raise rw._Dead("external call get_object disabled in the route walk")


STATE: dict = {"value": None}  # None: the label walk's mixed pattern; "low" | "high": the invariance axis (#6224)
FD: dict = {"day_offset": None}  # #6224: days before today of the food_delivery partition's newest row (None: no row)
FD_OFFSETS = {"early": 200, "late": 120}

# #6224: what a stored pre-#6224 public character variant carried — a cross-pillar effect read from the restraint
# streaks, the restraint component on Mind's driver list and component details, and a level event naming it. Planted on
# the walk's stored character row; none of them may reach a public body (the tokens below).
EFFECT_CANARY = "Restraint Effect Canary"
RESTRAINT_COMPONENT = "vice_control"
RESTRAINT_CONDITION = "any_vice_streak > 30"


def _restraint_done(i: int, k: int) -> bool:
    state = STATE["value"]
    if state is None:
        return (i + k) % 4 != 0
    return state == "high"


PROVENANCE: dict = {"plant": False}  # #6224: --provenance plants a corrected-chain variant with reconstructed events


def _plant_provenance(pv: dict) -> None:
    """The stored row as a CURRENT-method (corrected-chain) variant whose events carry internal provenance: one original
    public-input pillar event, one reconstructed pillar event and one reconstructed, re-dated character level-up."""
    from health import character_privacy as CP

    pv["public_method_version"] = CP.PUBLIC_METHOD_VERSION
    rec = {"event_provenance": CP.RECONSTRUCTED, "reconstructed_at": "2026-11-26", "reconstructed_method": CP.PUBLIC_METHOD_VERSION}
    pv["level_events"] = [
        {"type": "level_up", "pillar": "sleep", "old_level": Decimal("3"), "new_level": Decimal("4")},
        dict(rec, type="level_up", pillar="movement", old_level=Decimal("6"), new_level=Decimal("7")),
        dict(rec, type="character_level_up", old_level=Decimal("4"), new_level=Decimal("5"), redated_from="2026-09-01"),
    ]


def _plant_character(r: dict) -> None:
    pv = r.get("public")
    if not isinstance(pv, dict):
        return
    if PROVENANCE["plant"]:
        _plant_provenance(pv)
        return
    pv["active_effects"] = [{"name": EFFECT_CANARY, "emoji": "", "condition": RESTRAINT_CONDITION, "targets": {"mind": {"value": 0.03}}}]
    mind = pv.setdefault("pillar_mind", {})
    mind["drivers"] = {"top": [RESTRAINT_COMPONENT], "dragging": [], "absent": [], "no_data": []}
    mind["components"] = {RESTRAINT_COMPONENT: {"score": Decimal("100"), "weight": Decimal("0.1")}}
    pv["level_events"] = [{"type": "level_up", "pillar": "mind", "top_driver": "Vice Control", "top_driver_value": Decimal("100")}]


def _fd_day():
    from datetime import timedelta

    from common.pacific_time import PACIFIC

    return (jw.FROZEN.astimezone(PACIFIC).date() - timedelta(days=FD["day_offset"])).isoformat()


def _augment(rows: list) -> list:
    ids = _ids()
    user = "USER#matthew"
    if FD["day_offset"] is not None:
        # #6224: the food-delivery source's rows (synthetic) — the newest one's date is the axis; an older one is fixed.
        for day in ("2026-01-10", _fd_day()):
            rows.append({"pk": f"{user}#SOURCE#food_delivery", "sk": f"DATE#{day}", "date": day, "import_date": day, "delivery_index": 0})
    for i, r in enumerate(rows):
        pk = str(r.get("pk", ""))
        if pk.endswith("#SOURCE#character_sheet"):
            _plant_character(r)
            if FD["day_offset"] is not None and isinstance((r.get("input_manifest") or {}).get("sources"), dict):
                r["input_manifest"]["sources"]["food_delivery"] = {
                    "status": "paused",
                    "latest_day": _fd_day(),
                    "age_hours": Decimal(FD["day_offset"] * 24),
                    "stale_after_hours": Decimal("336"),
                }
        if pk.endswith("#SOURCE#habitify"):
            statuses = r["habit_statuses"]
            for k, (name, (group, _streak, _flag)) in enumerate(SIGNALS.items()):
                done = _restraint_done(i, k)
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
            if STATE["value"] is None:
                r["vice_streaks"] = {n: Decimal((day + k) % 9) for k, (n, sig) in enumerate(SIGNALS.items()) if sig[1]}
            else:
                # The stored tier-0 counts and run, as the scorer writes them: every planted restraint habit is tier 0
                # in the registry below, so they move with the restraint state (a route that reads them moves too).
                held = STATE["value"] == "high"
                r["vice_streaks"] = {n: Decimal(90 if held else 0) for n, sig in SIGNALS.items() if sig[1]}
                r["tier0_done"] = Decimal(int(r.get("tier0_done", 0)) + (len(SIGNALS) if held else 0))
                r["tier0_total"] = Decimal(int(r.get("tier0_total", 0)) + len(SIGNALS))
                r["tier0_pct"] = Decimal(str(round(int(r["tier0_done"]) / int(r["tier0_total"]), 3)))
                r["t0_perfect_streak"] = Decimal(9 if held else 0)
            r["vices_held"] = Decimal(sum(1 for v in r["vice_streaks"].values() if v > 0))
            r["vices_total"] = Decimal(len(r["vice_streaks"]))
            r["missed_tier0"] = [CANARIES[0], ORDINARY]
        elif pk == user and r.get("sk") == "PROFILE#v1":
            r["habit_registry"] = {n: {"status": "active", "tier": 2, "vice": True} for n, sig in SIGNALS.items() if sig[2]}
            if STATE["value"] is not None:
                # #6224: every planted restraint habit in TIER 0 (the registry flag kept where the label walk set it), and
                # the ordinary habit too, so the public tier-0 figures have a public habit to count and are not vacuous.
                reg = r["habit_registry"]
                for n, sig in SIGNALS.items():
                    reg[n] = {"status": "active", "tier": 0, **({"vice": True} if sig[2] else {})}
                reg[ORDINARY] = {"status": "active", "tier": 0}
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


def _publish() -> None:
    """#6224's mutation control: the restraint switch flipped (``RESTRAINT_DATA_PUBLISHED``) — the state an owner
    approval would put it in. The character and tier-0 holds key off it, so with it on the planted restraint names
    reach /api/character and the restraint state moves the tier-0 routes: the walk can see both."""
    from common import restraint_publication as RP

    RP.RESTRAINT_DATA_PUBLISHED = True


def _fd_public() -> None:
    """#6224's food-delivery control: the source classified public again (the state before the 2026-11-26 ruling)."""
    from common import activity_publication as AP

    AP.ACTIVITY_ONLY_SOURCES["food_delivery"] = AP.PUBLIC


def _mind_scored() -> None:
    """#6224's Mind control: ``public_sheet`` serves the stored variant's Mind as stored (the not-scored shape is not
    applied), the state before Mind was unscored in public."""
    from health import character_privacy as CP

    keep = CP.public_pillar
    CP.scrub_unscored = lambda view: view
    CP.public_pillar = lambda name, pillar: pillar if name == "mind" else keep(name, pillar)


# #6224: the keys that carry a Mind score, level, tier or XP on a served body.
MIND_SCORE_KEYS = frozenset({"level", "raw_score", "score", "level_score", "tier", "xp_total", "xp_delta", "xp_earned", "xp_debt"})
MIND_KEYS = frozenset({"mind", "pillar_mind", "mind_pillar"})


def mind_numbers(body) -> list:
    """Every place a served body carries a Mind score/level/tier/XP value (#6224: Mind is not scored in public) — a
    pillar row named "mind", or the value under a Mind key — as sorted key paths. None is not a value."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    found: set = set()

    def value(v) -> bool:
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or (isinstance(v, str) and v != "")

    def walk_(node, path):
        if isinstance(node, dict):
            if str(node.get("name") or "").lower() == "mind" or str(node.get("pillar") or "").lower() == "mind":
                found.update(f"{path}.{k}" for k in MIND_SCORE_KEYS | {"old_level", "new_level"} if value(node.get(k)))
            for k, v in node.items():
                if k in MIND_KEYS:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        found.add(f"{path}.{k}")
                    elif isinstance(v, dict):
                        found.update(f"{path}.{k}.{x}" for x in MIND_SCORE_KEYS if v.get(x) is not None)
                walk_(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk_(v, f"{path}[]")

    walk_(body, "")
    return sorted(found)


# #6224 (containment, owner ruling 2026-11-26): while the character scores are pending a recompute no public body carries
# a numeric overall level, tier, XP, XP debt or composite.
OVERALL_KEYS = frozenset({"character_level", "character_xp", "character_xp_debt", "character_tier", "composite_score", "current_level"})
OVERALL_HOLDERS = frozenset({"character", "character_stats", "character_sheet"})
OVERALL_HELD_KEYS = frozenset({"level", "xp_total", "xp", "xp_debt", "tier", "composite_score", "composite_delta_1d"})


def overall_numbers(body) -> list:
    """Every overall character value (level/tier/XP/composite) a served body carries, as sorted key paths."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    found: set = set()

    def value(v) -> bool:
        return (isinstance(v, (int, float)) and not isinstance(v, bool)) or (isinstance(v, str) and v != "")

    def walk_(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in OVERALL_KEYS and value(v):
                    found.add(f"{path}.{k}")
                if k in OVERALL_HOLDERS and isinstance(v, dict):
                    found.update(f"{path}.{k}.{x}" for x in OVERALL_HELD_KEYS if value(v.get(x)))
                walk_(v, f"{path}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk_(v, f"{path}[]")

    walk_(body, "")
    return sorted(found)


def _scores_live() -> None:
    """#6224's containment control: the pending switch off (the state after a verified recompute)."""
    from health import character_privacy as CP

    CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False


def walk(
    ungated: bool = False,
    frozen: bool = False,
    published: bool = False,
    fd_public: bool = False,
    mind_scored: bool = False,
    scores_live: bool = False,
) -> dict:
    if not frozen:
        jw.FROZEN = datetime.now(timezone.utc)  # the base rows are dated relative to this; the real clock, not a frozen one
    base_rows = jw._rows
    jw._rows = lambda variant: _augment(base_rows(variant))
    if ungated:
        _ungate()
    if published:
        _publish()
    if fd_public:
        _fd_public()
    if mind_scored:
        _mind_scored()
    if scores_live:
        _scores_live()
    L = jw._wire("gaps")
    import boto3

    boto3.client = lambda *a, **k: _ConfigS3()  # type: ignore[assignment]

    from web import site_api_protocols as P

    P._domains_cache = json.loads(json.dumps(DOMAINS_CONFIG))

    toks = tokens()
    out = {"routes": 0, "answered": 0, "raised": {}, "leaks": {}, "figures": {}, "bodies": {}, "mind": {}, "overall": {}}
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
        minds = mind_numbers(resp.get("body"))
        if minds:
            out["mind"][path] = minds
        overall = overall_numbers(resp.get("body"))
        if overall:
            out["overall"][path] = overall
        if path in KEEP_BODIES:
            body = resp.get("body")
            out["bodies"][path] = json.loads(body) if isinstance(body, str) else body
        if frozen:  # the invariance axis compares every route's whole body across the two restraint states
            body = resp.get("body")
            try:
                parsed = json.loads(body) if isinstance(body, str) else body
            except ValueError:
                parsed = body
            out.setdefault("all_bodies", {})[path] = json.dumps(
                {"status": resp.get("statusCode"), "body": jw._normalise(parsed)}, sort_keys=True, default=str
            )
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
    state = sys.argv[sys.argv.index("--state") + 1] if "--state" in sys.argv else None
    if state is not None:
        assert state in ("low", "high"), state
        STATE["value"] = state
        jw._freeze(sys.argv[sys.argv.index("--now") + 1])  # one instant for both states (before any handler import)
    PROVENANCE["plant"] = "--provenance" in sys.argv
    if "--provenance-leak" in sys.argv:  # #6224's control: the public strip of provenance and reconstructed events off
        from health import character_privacy as _CP

        _CP.without_provenance = lambda e: e
        _CP.is_reconstructed = lambda e: False
    if "--fd" in sys.argv:
        FD["day_offset"] = FD_OFFSETS[sys.argv[sys.argv.index("--fd") + 1]]
    try:
        result = walk(
            ungated="--ungated" in sys.argv,
            frozen=state is not None,
            published="--published" in sys.argv,
            fd_public="--fd-public" in sys.argv,
            mind_scored="--mind-scored" in sys.argv,
            scores_live="--scores-live" in sys.argv,
        )
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(result, default=str))
