"""Publication policy for RESTRAINT habits — which of them may be NAMED on a public surface (#5948).

THE RULE (docs/DATA_GOVERNANCE.md, "Editorial guardrails (public surfaces)"): since #6224 (owner ruling
2026-11-23) NO restraint category is named publicly and NO restraint figure — streak, relapse count,
held/tracked total, adherence aggregate, the number of private categories — is published, because no
explicit owner approval for any of them was found (``NAMED_CATEGORIES`` is empty and
``RESTRAINT_DATA_PUBLISHED`` is False). Until then the alcohol and food-delivery categories were named and
every other restraint category was served as unlabelled aggregates. This module is the ONE place the rule
is decided. A public serializer
that holds a restraint habit's name asks here before the name reaches a payload, and serves whatever
is not nameable through the unlabelled shapes below.

WHY A MODULE (the leak this closes, twice). The rule was first enforced on 2026-06-23 by one renderer
on one page: the Mind page stopped printing the names its payload still carried, while the sibling
page's renderer and three more payloads went on serving them (docs/CHANGELOG.md, 2026-11-14). A hide
in a renderer leaves the label on the wire and guards one instance. The decision therefore lives on
the SERVING side, in one function every public reader of a restraint name goes through, and
``tests/test_restraint_labels_5948.py`` walks every public GET route with synthetic restraint names
planted in the table, so a route that forgets to ask fails by name.

FAIL CLOSED. A restraint habit is nameable only when its exact name is in ``NAMED_CATEGORIES``. A
new habit, a renamed habit, a habit in a category nobody has ruled on: aggregate-only until a line
is added here (which is an owner decision about a public surface, not a refactor). Classification is
by the whole canonical name, never by a word inside it.

WHAT COUNTS AS A RESTRAINT HABIT. Any one of: its tracker group is a restraint group
(``RESTRAINT_GROUPS``); the owner's registry flags it (``habit_registry[name].vice``); it has a key
in a stored ``habit_scores.vice_streaks`` map. The union, so that no single source going quiet makes
a restraint habit look like an ordinary one.

This is a different rule from the content filter (``web.site_api_common._is_blocked_vice``): the
never-public categories are removed from public payloads ENTIRELY, counts included, and that screen
still runs first. This module governs what is left — habits whose existence and streak counts are
public and whose labels are not.

The stored rows are never changed: the owner's tools (MCP, coaches, the daily brief) read the table
directly and keep every name.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

# The whole canonical name (lower-cased, whitespace collapsed) of each habit that may be named, and the
# governance category it stands for. EMPTY since #6224 (owner ruling 2026-11-23: "Check those disclosures
# against my explicit public-content approvals ... Where authorization is absent, withhold the data rather
# than silently grandfathering it"). The two categories named here until then came from an editorial
# guardrail that LIMITED naming (docs/DATA_GOVERNANCE.md, migrated from a 2026-06-07 review), not from an
# owner approval to name them, and no such approval was found. Adding a line here publishes a label: it
# needs the owner's explicit ruling, recorded in docs/DATA_GOVERNANCE.md, in the same change.
NAMED_CATEGORIES: dict[str, str] = {}

# #6224: is ANY restraint figure published — a streak, a relapse count, a held/tracked total, an adherence
# aggregate, the number of private categories? False: no explicit owner approval was found for any of them,
# and the unlabelled aggregates let a reader count the private categories and read their behaviour by
# inference (the owner's boundary covers "paraphrases and inferences"). Flipping it is an owner ruling plus a
# docs/DATA_GOVERNANCE.md edit, never a refactor; tests/test_restraint_withheld_6224.py pins it.
RESTRAINT_DATA_PUBLISHED = False

RESTRAINT_GROUPS: frozenset = frozenset({"vice"})  # the tracker area the owner files restraint habits under
REGISTRY_FLAG = "vice"  # PROFILE#v1.habit_registry[name][REGISTRY_FLAG] is truthy for a restraint habit


def _norm(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def category(name: Any) -> Optional[str]:
    """The public category a restraint habit may be named under, or None (aggregate-only)."""
    return NAMED_CATEGORIES.get(_norm(name))


def may_name(name: Any) -> bool:
    return category(name) is not None


def is_restraint(status: Any = None, registry_meta: Any = None) -> bool:
    """True when a stored tracker status or the owner's registry entry marks the habit a restraint."""
    st = status if isinstance(status, Mapping) else {}
    meta = registry_meta if isinstance(registry_meta, Mapping) else {}
    groups = {_norm(st.get("group")), _norm(meta.get("group"))}
    return bool(groups & RESTRAINT_GROUPS) or bool(meta.get(REGISTRY_FLAG))


def restraint_names(statuses: Any = None, registry: Any = None, streaks: Any = None) -> set:
    """Every habit name any of the three sources marks a restraint (the union; see the module docstring)."""
    out: set = set()
    reg = registry if isinstance(registry, Mapping) else {}
    for name, st in (statuses or {}).items() if isinstance(statuses, Mapping) else ():
        if is_restraint(st, reg.get(name)):
            out.add(str(name))
    for name, meta in reg.items():
        if is_restraint(None, meta):
            out.add(str(name))
    if isinstance(streaks, Mapping):
        out.update(str(k) for k in streaks)
    return out


def is_unnamed(name: Any, restraints: Optional[Iterable[Any]]) -> bool:
    """True when ``name`` must not be served as a label.

    ``restraints`` is the set of known restraint names, or None when it could not be read. Unknown is
    not "none": with no set to ask, only a nameable habit is served by name (over-hide, never leak)."""
    if may_name(name):
        return False
    if restraints is None:
        return True
    return str(name) in {str(r) for r in restraints}


def nameable_names(names: Any, restraints: Optional[Iterable[Any]]) -> list:
    """A list of habit names with every restraint that may not be named removed (order kept)."""
    known = None if restraints is None else {str(r) for r in restraints}
    return [n for n in (names or []) if not is_unnamed(n, known)]


# ── the unpublished shape ──────────────────────────────────────────────────────────────────
#
# #6224: the unlabelled aggregates that stood here (a streak portfolio, nameless streak rows, an adherence
# figure) went when no restraint figure was published; they let a reader count the private categories.


def unpublished_vice_portfolio() -> dict:
    """The whole /api/vice_streaks body while ``RESTRAINT_DATA_PUBLISHED`` is False (#6224): the one fact that the
    section is not published. No name, streak, count or total — nothing to subtract a private count from."""
    return {"published": False}


# ── the known restraint set, for a serializer that holds names and nothing else ────────────


def load_restraint_names(table: Any, user_prefix: str, user_id: str) -> Optional[set]:
    """The restraint habit names the table knows, for a reader whose own input is a bare list of names
    (a config file's ``habit_names``). Three single-item reads: the latest tracker row, the latest
    ``habit_scores`` row, the owner's registry — each partition named literally and each read projected
    to the one attribute it needs, so this is not a general partition reader. No phase filter — this
    classifies, it publishes nothing, and a restraint habit from before the current cycle is still one.

    Returns None when ANY read fails or there is no table: the caller then cannot tell a restraint
    habit from an ordinary one and must serve only nameable names (``is_unnamed``)."""
    if table is None:
        return None
    try:
        from boto3.dynamodb.conditions import Key  # noqa: PLC0415 — the pure half of this module needs no boto3

        def first(resp: Any) -> Mapping:
            items = (resp or {}).get("Items") or []
            return items[0] if items and isinstance(items[0], Mapping) else {}

        tracker = table.query(
            KeyConditionExpression=Key("pk").eq(user_prefix + "habitify"),
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="habit_statuses",
        )
        scores = table.query(
            KeyConditionExpression=Key("pk").eq(user_prefix + "habit_scores"),
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="vice_streaks",
        )
        statuses = first(tracker).get("habit_statuses") or {}
        streaks = first(scores).get("vice_streaks") or {}
        profile = (table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE#v1"}) or {}).get("Item") or {}
        registry = profile.get("habit_registry") or {}
        return restraint_names(statuses, registry, streaks)
    except Exception as e:  # noqa: BLE001 — any failure is "unknown", and unknown is served closed
        logger.warning("[restraint_publication] restraint set could not be read; serving nameable names only: %s", e)
        return None
