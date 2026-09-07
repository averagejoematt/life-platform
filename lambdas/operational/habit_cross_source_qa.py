"""habit_cross_source_qa.py — #3666: the habit/instrument cross-source contract.

THE CHECK THAT WOULD HAVE CAUGHT #3666 ON DAY ONE.

Some habits are *claims about an event another source measures independently*. "Weigh
In" is a claim about a Withings weigh-in; "Food Journal" is a claim about a MacroFactor
log. Those two sources cannot both be wrong in the same direction by accident, so the
pair is a contract:

    a habit may not read `failed` on a Pacific day the partner source has evidence for.

On 2026-09-06 both legs were violated at once, live: Withings logged 327.34 lb and
MacroFactor ingested a full day's entries, while the habitify record read `failed` for
both habits — because `/journal` buckets by the UTC date of the tick and the record is
filed under a Pacific `DATE#` key, so the fifteen 19:11-19:13 PT completions landed on
`DATE#2026-09-07` and `DATE#2026-09-06` was rewritten to 61 failed / 0 completed.

Nothing noticed for sixteen stored days. Every existing habit check asked whether a
RECORD existed, or whether its SHAPE was valid — never whether its content agreed with
an instrument that measured the same behaviour. This is that check, and it is
deliberately *cross-source*: it cannot be satisfied by the same bug that produced the
data, which is what made every same-source assertion blind to this class.

Direction matters. Only `failed`-with-evidence is a violation:

  * `failed` + partner evidence  -> RED. The habit says the owner did not do a thing an
    instrument recorded him doing. One of the two is wrong and the habit record is the
    one with a known failure mode.
  * `pending` + evidence         -> fine. The Pacific day is still open; the tick may
    genuinely be coming, and #3666's whole point is that `pending` must survive the day.
  * `completed` + no evidence    -> NOT a violation, and deliberately so. He can step on
    the scale with the app closed, or log food a day late (MacroFactor is ~24h behind by
    design). Asserting that direction would red on the partner's latency, not on truth.

Dependency-injected like acwr_liveness_qa / nudge_ledger_qa: qa_smoke_lambda owns the
clients and the nightly wiring, this module owns the logic, and `cross_source_violations`
is a pure function so the contract is provable offline with no AWS
(``tests/test_habit_cross_source_contract_3666.py`` replays the real 2026-09-06 rows).
"""

from __future__ import annotations

from datetime import timedelta

# A habit whose completion an independent instrument also measures.
#   habit    — the Habitify habit name (the key in `habit_statuses`)
#   source   — the partner source's DDB partition suffix
#   evidence — human-readable description of what counts as evidence, for the message
#   fields   — the partner record fields whose presence (numeric, non-zero) is evidence
CROSS_SOURCE_CONTRACTS = (
    {
        "habit": "Weigh In",
        "source": "withings",
        "evidence": "a weigh-in",
        "fields": ("weight_lbs", "weight_kg"),
    },
    {
        "habit": "Food Journal",
        "source": "macrofactor",
        "evidence": "logged entries",
        "fields": ("entries_count", "total_meals", "total_calories_kcal"),
    },
)

# Only this status contradicts an instrument. `pending` is an open day, not a claim.
CONTRADICTING_STATUSES = ("failed",)


def has_evidence(record, fields) -> bool:
    """True when the partner record carries a positive value in any evidence field.

    A record that exists but is empty (an ADR-104 absence marker, a zeroed row) is NOT
    evidence — the check must red on a contradiction, never on the mere presence of a key.
    """
    if not isinstance(record, dict):
        return False
    for field in fields:
        value = record.get(field)
        if value is None or isinstance(value, bool):
            continue
        try:
            if float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def cross_source_violations(date_str: str, habit_statuses, evidence) -> list[str]:
    """The pure contract. Returns one message per violated pair (empty == the day agrees).

    ``habit_statuses`` is the habitify record's map; ``evidence`` is
    ``{source_name: bool}``. Both are plain data on purpose — the whole point of this
    check is that it can be replayed against a stored day with no live credentials.
    """
    statuses = habit_statuses if isinstance(habit_statuses, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    out = []
    for contract in CROSS_SOURCE_CONTRACTS:
        entry = statuses.get(contract["habit"])
        if not isinstance(entry, dict):
            continue
        if entry.get("status") not in CONTRADICTING_STATUSES:
            continue
        if evidence.get(contract["source"]) is not True:
            continue
        out.append(
            f"{date_str}: habit {contract['habit']!r} reads '{entry.get('status')}' but "
            f"{contract['source']} recorded {contract['evidence']} that Pacific day (#3666)"
        )
    return out


def check_habit_cross_source(table, user_prefix, check_cls, partition, pt_now):
    """Nightly leg: replay the contract over the last CLOSED Pacific day.

    Yesterday, not today — a day still open legitimately holds `pending` habits, and this
    check must measure a finalised day or it would red on the very state #3666 restored.
    """
    c = check_cls("habit_cross_source", "Data Freshness", partition)
    day = (pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        habitify = table.get_item(Key={"pk": user_prefix + "habitify", "sk": "DATE#" + day}).get("Item") or {}
        evidence = {}
        for contract in CROSS_SOURCE_CONTRACTS:
            source = contract["source"]
            if source in evidence:
                continue
            partner = table.get_item(Key={"pk": user_prefix + source, "sk": "DATE#" + day}).get("Item") or {}
            evidence[source] = has_evidence(partner, contract["fields"])
    except Exception as e:
        c.fail(f"habit cross-source contract — DDB error: {e}")
        return [c]

    if not habitify.get("habit_statuses"):
        # No habit record at all is the freshness checker's job, not this one. Say so
        # rather than reporting a green nobody earned.
        c.warn(f"no habitify habit_statuses for {day} — cross-source contract not evaluable")
        return [c]

    violations = cross_source_violations(day, habitify.get("habit_statuses"), evidence)
    if violations:
        c.fail("; ".join(violations))
    else:
        checked = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in sorted(evidence.items()))
        c.ok(f"{day}: no habit contradicts its partner instrument ({checked})")
    return [c]
