"""tests/test_coach_stance.py — CC-09 coach stance / stage-ladder validator.

Enforces that every operational coach has a well-formed stage ladder:
  * required fields per stage,
  * bands contiguous + non-overlapping + tiling the metric (-inf, +inf),
  * `watches` reference only real computable signals,
  * the rung resolver returns the right stage for a value,
and that the NUTRITION stance honours the non-negotiable wellbeing guardrail
(leads with logging; no aggressive numeric rate; supportive concern_watches;
rate deferred to deficit_sustainability).
"""

import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import coach_stance  # noqa: E402
import persona_registry  # noqa: E402

REQUIRED_STAGE_FIELDS = [
    "stage_id",
    "entry",
    "headline",
    "read_of_him",
    "cares_most",
    "cares_less_right_now",
    "plan",
    "graduation_gate",
    "watches",
]


def _load(coach_id):
    return coach_stance.load_stance(coach_id, force_refresh=True)


def _all():
    return {c: _load(c) for c in persona_registry.OPERATIONAL_COACH_IDS}


# ── presence + shape ─────────────────────────────────────────────────────────


def test_every_operational_coach_has_a_stance():
    for coach_id, stance in _all().items():
        assert stance, f"{coach_id}: missing stance file"
        assert stance.get("coach") == coach_id, f"{coach_id}: stance 'coach' field mismatch"
        assert stance.get("band_metric"), f"{coach_id}: missing band_metric"
        assert stance.get("stage_ladder"), f"{coach_id}: empty stage_ladder"


def test_every_stage_has_required_fields():
    for coach_id, stance in _all().items():
        for st in stance["stage_ladder"]:
            for f in REQUIRED_STAGE_FIELDS:
                assert f in st, f"{coach_id}/{st.get('stage_id')}: missing {f}"
            assert isinstance(st["cares_most"], list) and st["cares_most"]
            assert isinstance(st["cares_less_right_now"], list)
            assert isinstance(st["watches"], list) and st["watches"]
            assert st["entry"].get("metric") == stance["band_metric"], f"{coach_id}/{st['stage_id']}: entry metric != band_metric"


# ── bands tile the metric (contiguous, non-overlapping, full coverage) ────────


def test_bands_tile_the_metric():
    for coach_id, stance in _all().items():
        bands = [(s["entry"].get("min"), s["entry"].get("max")) for s in stance["stage_ladder"]]
        # sort by lower bound, None == -inf
        bands.sort(key=lambda b: (b[0] is not None, b[0]))
        # first must be open at the bottom, last open at the top
        assert bands[0][0] is None, f"{coach_id}: lowest band must have min=null (covers -inf)"
        assert bands[-1][1] is None, f"{coach_id}: highest band must have max=null (covers +inf)"
        # contiguity: each band's max equals the next band's min
        for (lo_a, hi_a), (lo_b, hi_b) in zip(bands, bands[1:]):
            assert hi_a is not None and lo_b is not None, f"{coach_id}: interior band cannot be unbounded"
            assert hi_a == lo_b, f"{coach_id}: gap/overlap between bands at {hi_a} != {lo_b}"


def test_watches_reference_real_signals():
    for coach_id, stance in _all().items():
        for st in stance["stage_ladder"]:
            for w in st["watches"]:
                assert w in coach_stance.KNOWN_SIGNALS, f"{coach_id}/{st['stage_id']}: unknown watch signal {w!r}"


# ── the rung resolver ────────────────────────────────────────────────────────


def test_resolver_picks_the_right_rung():
    # weight-banded coach: baseline ~306 -> foundation
    tr = _load("training_coach")
    st = coach_stance.resolve_stage(tr["stage_ladder"], 306.87)
    assert st and st["stage_id"] == "foundation"
    # a lighter weight lands in a later rung
    st2 = coach_stance.resolve_stage(tr["stage_ladder"], 225)
    assert st2 and st2["stage_id"] == "develop"
    # None resolves to nothing (honest empty-state pre-data)
    assert coach_stance.resolve_stage(tr["stage_ladder"], None) is None
    # every value in range resolves to exactly one stage
    for v in (180, 215, 245, 290, 400):
        assert coach_stance.resolve_stage(tr["stage_ladder"], v) is not None


def test_nutrition_resolver_on_logging_consistency():
    nut = _load("nutrition_coach")
    assert nut["band_metric"] == "logging_consistency"
    assert coach_stance.resolve_stage(nut["stage_ladder"], 0.2)["stage_id"] == "visibility"
    assert coach_stance.resolve_stage(nut["stage_ladder"], 0.9)["stage_id"] == "tune"


# ── nutrition wellbeing guardrail (non-negotiable) ───────────────────────────


def _nutrition_prose(stance):
    """All human-facing prose across the nutrition ladder (excludes entry bands)."""
    chunks = []
    for st in stance["stage_ladder"]:
        chunks += [st["headline"], st["read_of_him"], st["plan"], st["graduation_gate"]]
        chunks += st["cares_most"] + st["cares_less_right_now"]
    return " ".join(chunks).lower()


def test_nutrition_leads_with_logging():
    nut = _load("nutrition_coach")
    first = nut["stage_ladder"][0]
    text = (first["headline"] + " " + first["plan"] + " " + " ".join(first["cares_most"])).lower()
    assert "log" in text or "see what you eat" in text, "nutrition first rung must lead with logging"


def test_nutrition_has_no_aggressive_numeric_rate():
    """No published hard rate/target — pace defers to deficit_sustainability."""
    prose = _nutrition_prose(_load("nutrition_coach"))
    banned = [
        r"\d+\s*lb",  # e.g. "3 lb/week"
        r"\d+\s*pounds?",
        r"\d+\s*kg",
        r"\d+\s*(k?cal|calorie)",  # e.g. "1500 calories"
        r"\d+\s*%\s*deficit",
    ]
    for pat in banned:
        assert not re.search(pat, prose), f"nutrition stance publishes an aggressive numeric rate matching {pat!r}"


def test_nutrition_concern_watches_supportive_and_rate_deferred():
    nut = _load("nutrition_coach")
    # every stage carries supportive concern_watches (a list of gentle, correlative flags)
    for st in nut["stage_ladder"]:
        assert isinstance(st.get("concern_watches"), list) and st["concern_watches"], f"{st['stage_id']}: missing concern_watches"
    # the rate is explicitly deferred to the sustainability monitor somewhere
    blob = json.dumps(nut).lower()
    assert (
        "deficit_sustainability" in blob or "sustainability monitor" in blob
    ), "nutrition stance must defer the rate to deficit_sustainability"
