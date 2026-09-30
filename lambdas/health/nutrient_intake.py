"""nutrient_intake.py — THE micronutrient intake derivation: food + the supplement record (#4244/#4245).

`micronutrient_sufficiency` used to be computed from MacroFactor totals ALONE
(`ingestion.macrofactor_lambda.compute_micronutrient_sufficiency`) and then published under
labels that claimed total intake — "Sufficiency vs daily target" on the site, "Micro = avg
sufficiency %" in the weekly email, "Any micro <50% for 3+ days" in the panel prompt. The
platform held the other half of the intake the whole time: `USER#matthew#SOURCE#supplements`
(written by `habitify_lambda.supplement_bridge` from the ticked supplement habits) carries
name + dose + unit for every dose TAKEN that day. On 2026-09-25 the served vitamin D read
5.0% while the supplement record held Vitamin D 5,000 IU = 125 mcg against a 100 mcg target.
The owner's reading (2026-09-26): "a metric named for a total that reads one channel".

This module is the one place the two channels meet, and it is a UNIT problem before it is a
sum (#4245): IU is not mcg, a compound's mass is not its elemental mineral, a fish-oil dose
is EPA/DHA while the food side's omega-3 is mostly ALA, and "Multivitamin 1 capsule" has no
nutrient content the platform knows. Every conversion below is data with a citation; a dose
whose unit cannot be converted is NOT summed — it lands in `unconverted[]` by name, and any
nutrient it MAY carry is marked so the total for that nutrient is not claimed as complete
(ADR-104: absent is absent, never a silent zero AND never a silent addition).

Pure: no AWS, no clock. The caller supplies the MacroFactor day row and the supplements day
row (or None when the partition has no row for the day).

Consumers (each must publish `intake_channels` beside the number — the label names what was
counted, #4244 acceptance): `web.site_api_nutrition.nutrition_overview` (the public door),
`emails.nutrition_review_lambda.extract_daily_nutrition` (the weekly table + the panel's
deterministic numbers). `ingestion.macrofactor_lambda` still stores the food-only figure
at ingest — stamped `micronutrient_intake_channels: ["food"]` so the artifact at rest says
what it is.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

# ── Targets (moved here from macrofactor_lambda; re-exported there) ────────────────────
# Board of Directors consensus targets for adult male, active, weight-loss phase.
MICRONUTRIENT_TARGETS: dict[str, dict[str, Any]] = {
    "fiber_g": {"target": 38, "label": "Fiber"},
    "potassium_mg": {"target": 3400, "label": "Potassium"},
    "magnesium_mg": {"target": 420, "label": "Magnesium"},
    "vitamin_d_mcg": {"target": 100, "label": "Vitamin D"},  # 4000 IU
    # #4245 box 3: omega-3 is TWO targets, never one summed total. The retired single
    # `omega3_total_g` target (3 g) was filled almost entirely by plant ALA on the food side
    # (2026-09-24: ALA 3.7 g, EPA 0, DHA 0) while the supplement dose is EPA/DHA, so summing
    # them published "Omega-3 80%" for a day with no marine omega-3 in the food at all. 3 g is
    # also the wrong KIND of number for EPA+DHA: FDA 21 CFR 184.1472 treats up to 3 g/day of
    # EPA+DHA as the safe ceiling, not an intake goal.
    "omega3_epa_dha_g": {
        "target": 0.5,
        "label": "Omega-3 EPA+DHA",
        "food_fields": ("omega3_epa_g", "omega3_dha_g"),
        "decimals": 2,
        "source": "ISSFAL 2004 policy statement: >=500 mg/day EPA+DHA for cardiovascular health in adults; EFSA 2012 "
        "(EFSA Journal 10(7):2815) sets 250 mg/day EPA+DHA as the adult Adequate Intake floor. No US DRI exists for "
        "EPA/DHA (NIH ODS Omega-3 fact sheet).",
    },
    "omega3_ala_g": {
        "target": 1.6,
        "label": "Omega-3 ALA",
        "decimals": 2,
        "source": "IOM/Food and Nutrition Board DRI 2005, as tabled in the NIH ODS Omega-3 fact sheet: ALA Adequate "
        "Intake for men 19+ = 1.6 g/day. ALA is the only omega-3 with a US DRI.",
    },
}

# The channels this derivation joins. Published verbatim beside every number it produces.
INTAKE_CHANNELS: tuple[str, ...] = ("food", "supplements")
AVG_PCT_BASIS = "average of per-nutrient TOTALS (food + supplements), each capped at 100%"

# ── Unit conversions — every factor carries its source ──────────────────────────────────
# Keyed (unit as the supplement record writes it, nutrient key). A `None` factor is a
# documented REFUSAL: the unit is real but the conversion depends on a fact the record does
# not carry, so the dose is reported unconverted rather than guessed.
UNIT_CONVERSIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("IU", "vitamin_d_mcg"): {
        "factor": 0.025,
        "source": "FDA 21 CFR 101.9(c)(8)(iv) (2016 Nutrition/Supplement Facts rule): vitamin D is declared in mcg, "
        "1 mcg = 40 IU; NIH ODS Vitamin D fact sheet states the same equivalence.",
    },
    ("mg", "omega3_epa_dha_g"): {
        "factor": 0.001,
        "source": "SI: 1 g = 1,000 mg.",
    },
    ("mg", "magnesium_mg"): {"factor": 1.0, "source": "same unit."},
    ("mg", "zinc_mg"): {"factor": 1.0, "source": "same unit."},
    ("mcg", "vitamin_d_mcg"): {"factor": 1.0, "source": "same unit."},
    # REFUSED — the form decides the factor and no record carries the form.
    ("IU", "vitamin_e_mg"): {
        "factor": None,
        "source": "NIH ODS Vitamin E fact sheet: natural RRR-alpha-tocopherol 1 IU = 0.67 mg, synthetic all-rac "
        "1 IU = 0.45 mg. The form is not on the supplement record, so IU vitamin E is NOT converted.",
    },
}

# ── The supplement → nutrient registry ──────────────────────────────────────────────────
# Keyed by the habit name exactly as `habitify_lambda.SUPPLEMENT_MAP` (and so the bridge)
# writes it, matched case-insensitively. Three dispositions, all explicit:
#   * a list of contributions — each names the nutrient it feeds, the unit the record must
#     carry, the fraction of the recorded dose that IS that nutrient (elemental / species),
#     and the source for that fraction;
#   * `[]` — known to carry NONE of the tracked micronutrients (creatine, glycine, …);
#   * `None` — multi-ingredient or unlabelled: content unknown to the platform. Reported in
#     `unconverted[]`; `may_contain` marks the tracked nutrients its label commonly carries
#     so the total for those nutrients is not claimed as complete.
# A name absent from this registry is treated like `None` (unknown), so a NEW habit can
# never be silently counted or silently dropped — it shows up unconverted by name until
# someone writes its row. tests/test_macrofactor_ingestion_behavior.py guards the SET
# against SUPPLEMENT_MAP.
SUPPLEMENT_NUTRIENT_CONTENT: dict[str, Optional[dict[str, Any]]] = {
    "Vitamin D": {
        "content": [
            {
                "nutrient": "vitamin_d_mcg",
                "unit": "IU",
                "fraction": 1.0,
                "basis": "the dose IS vitamin D3; converted IU→mcg by UNIT_CONVERSIONS. The stack's product is "
                "'Vitamin D3 + K2' (config/supplement_registry.json vitamin_d) — its K2 content is not on the record "
                "and vitamin K is not a tracked target, so nothing is claimed for it.",
            }
        ],
    },
    "L-Threonate": {
        "content": [
            {
                "nutrient": "magnesium_mg",
                "unit": "mg",
                "fraction": 0.072,
                "basis": "the recorded 2,000 mg is the COMPOUND (magnesium L-threonate); elemental magnesium is 7.2% "
                "of it = 144 mg. Source: config/supplement_registry.json l_threonate.dose '144mg elemental' for the "
                "2,000 mg habit dose in habitify_lambda.SUPPLEMENT_MAP, matching the Magtein(R) label (2,000 mg "
                "magnesium L-threonate supplies 144 mg Mg; the compound Slutsky et al., Neuron 2010 studied). A naive "
                "join would publish magnesium at 100% on the strength of 2,000 mg.",
            }
        ],
    },
    "Zinc Picolinate": {
        "content": [
            {
                "nutrient": "zinc_mg",
                "unit": "mg",
                "fraction": 1.0,
                "basis": "Supplement Facts declare minerals as the ELEMENTAL amount with the compound named as the "
                "source (21 CFR 101.36(b)(2)(i); e.g. 'Zinc 30 mg (as zinc picolinate)'), and the stack lists the "
                "dose as 30mg (config/supplement_registry.json zinc), so 30 mg is read as elemental zinc. Zinc is "
                "not a tracked target; it is carried in `counted[]` only.",
            }
        ],
    },
    "Omega 3": {
        "content": [
            {
                "nutrient": "omega3_epa_dha_g",
                "unit": "mg",
                "fraction": 1.0,
                "basis": "STACK-DECLARED, not label-verified: config/supplement_registry.json omega3 ('Omega-3 "
                "(EPA/DHA)', dose '2-4g combined') declares the dose as EPA+DHA COMBINED, so the 2,000 mg habit dose "
                "is read as 2.0 g EPA+DHA — the lower bound of the declared range, not fish-oil capsule mass. If the "
                "habit were logging capsule mass instead, this would overstate. It feeds the EPA+DHA target only, "
                "never the food side's plant ALA (#4245).",
            }
        ],
    },
    # Known to carry none of the tracked micronutrients.
    "Collagen": {"content": []},
    "Creatine": {"content": []},
    "L Glutamine": {"content": []},
    "Glycine": {"content": []},
    "Inositol": {"content": []},
    "NAC": {"content": []},
    "Apigenin": {"content": []},
    "Theanine": {"content": []},
    "Reishi": {"content": []},
    "Lions Mane": {"content": []},
    "Green Tea Phytosome": {"content": []},
    "Cordyceps": {"content": []},
    "Protein Supplement": {"content": []},
    # Content unknown to the platform — reported unconverted, never summed.
    "Multivitamin": {
        "content": None,
        "reason": "multi-ingredient capsule; per-nutrient content is not on any record the platform holds",
        "may_contain": ["vitamin_d_mcg", "magnesium_mg", "zinc_mg", "potassium_mg"],
    },
    "Basic B Complex": {
        "content": None,
        "reason": "B-vitamin complex; per-nutrient content is not on any record the platform holds (no tracked target)",
        "may_contain": [],
    },
    "Electrolytes": {
        "content": None,
        "reason": "'1 packet' — potassium/magnesium content is not on any record the platform holds",
        "may_contain": ["potassium_mg", "magnesium_mg"],
    },
    "Probiotics": {
        "content": None,
        "reason": "'1 capsule' — no nutrient content on the record (no tracked target)",
        "may_contain": [],
    },
}

_REGISTRY_BY_NORM = {name.strip().lower(): spec for name, spec in SUPPLEMENT_NUTRIENT_CONTENT.items()}


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _food_value(row: Mapping[str, Any], key: str) -> Optional[float]:
    """A target's food amount from `total_*` fields. A composite target (`food_fields`, e.g.
    EPA+DHA) sums the fields that were logged, and is absent only when none of them was."""
    fields = MICRONUTRIENT_TARGETS[key].get("food_fields")
    direct = _num(row.get(f"total_{key}"))
    if direct is not None or not fields:
        return direct
    parts = [v for v in (_num(row.get(f"total_{f}")) for f in fields) if v is not None]
    return sum(parts) if parts else None


def food_sufficiency(totals_prefixed: Mapping[str, Any]) -> tuple[Optional[dict[str, dict[str, Any]]], Optional[float]]:
    """The FOOD-ONLY scorer — what ingest stores (moved intact from macrofactor_lambda).

    Returns (sufficiency_map, avg_pct) or (None, None) if no target nutrient was logged.
    sufficiency_map: {nutrient_key: {"actual": float, "target": float, "pct": float}};
    pct is capped at 100 — exceeding target still scores 100%.
    """
    sufficiency: dict[str, dict[str, Any]] = {}
    pcts: list[float] = []
    for nutrient_key, config in MICRONUTRIENT_TARGETS.items():
        actual = _food_value(totals_prefixed, nutrient_key)
        if actual is None:
            continue
        target = config["target"]
        pct = min(round(actual / target * 100, 1), 100.0)
        sufficiency[nutrient_key] = {"actual": round(actual, config.get("decimals", 1)), "target": target, "pct": pct}
        pcts.append(pct)
    if not pcts:
        return None, None
    return sufficiency, round(sum(pcts) / len(pcts), 1)


def _food_amounts(food_row: Optional[Mapping[str, Any]]) -> dict[str, float]:
    """Per-target food amounts: the `total_*` field(s), else the stored food-only `actual`."""
    if not food_row:
        return {}
    stored = food_row.get("micronutrient_sufficiency") or {}
    out: dict[str, float] = {}
    for key in MICRONUTRIENT_TARGETS:
        v = _food_value(food_row, key)
        if v is None and isinstance(stored, Mapping):
            entry = stored.get(key)
            v = _num(entry.get("actual")) if isinstance(entry, Mapping) else None
        if v is not None:
            out[key] = v
    return out


def _empty_contrib(state: str) -> dict[str, Any]:
    return {"state": state, "amounts": {}, "counted": [], "unconverted": [], "may_contain": {}}


def _supplement_contributions(supplement_row: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Walk the day's TAKEN doses; convert what has a cited path, name what does not."""
    entries = (supplement_row or {}).get("supplements") if supplement_row else None
    if not supplement_row or not isinstance(entries, list):
        return _empty_contrib("absent")
    amounts: dict[str, float] = {}
    counted: list[dict[str, Any]] = []
    unconverted: list[dict[str, Any]] = []
    may_contain: dict[str, list[str]] = {}
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        name = str(e.get("name") or "").strip()
        dose = _num(e.get("dose"))
        unit = str(e.get("unit") or "").strip()
        spec = _REGISTRY_BY_NORM.get(name.lower())
        if spec is None or spec.get("content") is None:
            reason = (
                spec.get("reason") if spec else "not in health.nutrient_intake.SUPPLEMENT_NUTRIENT_CONTENT — content unknown, not counted"
            )
            unconverted.append({"name": name, "dose": dose, "unit": unit, "reason": reason})
            for key in (spec or {}).get("may_contain") or []:
                may_contain.setdefault(key, []).append(name)
            continue
        for c in spec["content"]:
            conv = UNIT_CONVERSIONS.get((unit, c["nutrient"]))
            if dose is None or conv is None or conv.get("factor") is None:
                why = conv["source"] if conv else f"unit {unit!r} has no cited conversion to {c['nutrient']}"
                unconverted.append({"name": name, "dose": dose, "unit": unit, "reason": why})
                # A TAKEN dose of this nutrient that could not be converted: the total is a floor,
                # never a `from_supplements: 0.0` that reads as "took none".
                may_contain.setdefault(c["nutrient"], []).append(name)
                continue
            amount = dose * float(c["fraction"]) * float(conv["factor"])
            amounts[c["nutrient"]] = amounts.get(c["nutrient"], 0.0) + amount
            counted.append(
                {
                    "name": name,
                    "dose": dose,
                    "unit": unit,
                    "nutrient": c["nutrient"],
                    "amount": round(amount, 3),
                    "basis": c["basis"],
                    "conversion": conv["source"],
                }
            )
    return {"state": "recorded", "amounts": amounts, "counted": counted, "unconverted": unconverted, "may_contain": may_contain}


# ── #4245 box 4: a SCHEDULED MISS is a zero; no record is absent ────────────────────────
# The supplements partition lists TAKEN doses only, and the bridge writes no row on a day with
# no tick — so "no row" cannot tell "not recorded" from "scheduled and not taken". The Habitify
# day record can: every scheduled habit carries a resolved status (#3666). A supplement habit
# resolved `failed` (the vendor's miss, or the platform's at Pacific day close — `miss_source`
# says which) or `skipped` (an owner decision) was scheduled and not taken: its nutrients are a
# recorded ZERO. `pending` (the day is still open) and a missing Habitify row stay ABSENT. Only
# names in SUPPLEMENT_NUTRIENT_CONTENT are ever read, so no non-supplement habit name leaves here.
NOT_TAKEN_STATUSES: tuple[str, ...] = ("failed", "skipped")


def _supplement_habit_statuses(habit_row: Optional[Mapping[str, Any]]) -> dict[str, list[Any]]:
    statuses = (habit_row or {}).get("habit_statuses") if habit_row else None
    out: dict[str, list[Any]] = {"not_taken": [], "pending": [], "completed": []}
    if not isinstance(statuses, Mapping):
        return out
    for name, hs in statuses.items():
        if str(name).strip().lower() not in _REGISTRY_BY_NORM or not isinstance(hs, Mapping):
            continue
        status = hs.get("status")
        if status in NOT_TAKEN_STATUSES:
            out["not_taken"].append({"name": str(name), "status": status, "miss_source": hs.get("miss_source")})
        elif status in ("pending", "completed"):
            out[status].append(str(name))
    return out


def _fed_by(names: list[str]) -> dict[str, list[str]]:
    """Tracked nutrient -> the named supplements whose registry row feeds (or may feed) it."""
    fed: dict[str, list[str]] = {}
    for name in names:
        spec = _REGISTRY_BY_NORM.get(name.strip().lower()) or {}
        keys = [c["nutrient"] for c in spec.get("content") or []] + list(spec.get("may_contain") or [])
        for key in keys:
            if key in MICRONUTRIENT_TARGETS and name not in fed.get(key, []):
                fed.setdefault(key, []).append(name)
    return fed


def nutrient_intake(
    food_row: Optional[Mapping[str, Any]],
    supplement_row: Optional[Mapping[str, Any]],
    habit_row: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """ONE day's micronutrient intake across every channel the platform can convert.

    Per target nutrient: `total` (the sum of the channels counted; `actual` is the same number
    under its original served name — both are kept, #4245 box 2), `from_food`,
    `from_supplements`, `channels_counted`, `pct` (of target, capped 100), `label` — and, where
    an unconverted or still-pending dose MAY carry the nutrient, `uncounted_supplements` naming
    it, so the total is read as a floor. `habit_row` is the day's Habitify record (optional).
    Absence rules (ADR-104):
      * no supplement row and no Habitify evidence → `supplements_state: "absent"`,
        `from_supplements` None everywhere, totals are food-only and `channels_counted` says so;
      * no supplement row, and Habitify resolved the scheduled supplement habits `failed` or
        `skipped` with none ticked → `supplements_state: "scheduled_miss"`: the supplement channel
        is a recorded ZERO, each nutrient a missed dose would have fed names it in
        `missed_supplements`, and `not_taken[]` carries each habit's status + `miss_source`;
      * a supplement row that carries no dose feeding a nutrient → `from_supplements` 0.0
        (the record was consulted and holds none — the row lists TAKEN doses only) — but only
        beside a food figure or a named missed dose: otherwise the nutrient is absent, never 0%;
      * a nutrient only an unconverted dose might feed → `from_supplements` None, the
        dose named — never a 0 that reads as "took none".
    """
    food = _food_amounts(food_row)
    contrib = _supplement_contributions(supplement_row)
    habits = _supplement_habit_statuses(habit_row)
    not_taken = habits["not_taken"]
    if contrib["state"] == "absent" and not_taken and not habits["completed"]:
        # A ticked supplement habit with no supplement row is a bridge gap, not a miss — that
        # day stays absent. Still-pending habits leave their nutrients uncounted (a floor).
        contrib = _empty_contrib("scheduled_miss")
        for key, names in _fed_by(habits["pending"]).items():
            contrib["may_contain"].setdefault(key, []).extend(names)
    consulted = contrib["state"] in ("recorded", "scheduled_miss")
    missed_by_key = _fed_by([m["name"] for m in not_taken]) if consulted else {}
    sufficiency: dict[str, dict[str, Any]] = {}
    pcts: list[float] = []
    for key, cfg in MICRONUTRIENT_TARGETS.items():
        f = food.get(key)
        s: Optional[float] = contrib["amounts"].get(key)
        uncounted = contrib["may_contain"].get(key, [])
        missed = missed_by_key.get(key, []) if not s else []
        if consulted and s is None and not uncounted:
            s = 0.0
        # Absent, not 0%: with no food figure, a supplement record that fed nothing into this
        # nutrient says nothing about the day's intake of it — unless a dose of it was SCHEDULED
        # and not taken, which is the zero #4245 box 4 asks for.
        if f is None and not s and not missed:
            continue
        channels: list[str] = []
        total = 0.0
        if f is not None:
            total += f
            channels.append("food")
        if s is not None:
            total += s
            channels.append("supplements")
        target = cfg["target"]
        pct = min(round(total / target * 100, 1), 100.0)
        dp = cfg.get("decimals", 1)
        entry: dict[str, Any] = {
            "label": cfg["label"],
            "total": round(total, dp),
            "actual": round(total, dp),
            "target": target,
            "pct": pct,
            "from_food": round(f, dp) if f is not None else None,
            "from_supplements": round(s, dp) if s is not None else None,
            "channels_counted": channels,
        }
        if uncounted:
            entry["uncounted_supplements"] = list(uncounted)
        if missed:
            entry["missed_supplements"] = list(missed)
        sufficiency[key] = entry
        pcts.append(pct)
    food_only_map, food_only_avg = food_sufficiency({f"total_{k}": v for k, v in food.items()})
    return {
        "sufficiency": sufficiency,
        "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "avg_pct_basis": AVG_PCT_BASIS,
        "intake_channels": list(INTAKE_CHANNELS),
        "supplements_state": contrib["state"],
        "counted": contrib["counted"],
        "unconverted": contrib["unconverted"],
        "not_taken": not_taken if consulted else [],
        "food_only_avg_pct": food_only_avg,
    }
