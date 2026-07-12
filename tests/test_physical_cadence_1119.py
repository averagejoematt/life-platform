"""tests/test_physical_cadence_1119.py — #1119 /data/physical/ restructure.

The page reads at the right rhythm: the fluid (daily) weight block leads, the
checkpoint block is grouped and labeled with its ACTUAL cadence — and every
cadence label derives from measurement metadata (source_registry's withings
entry + the handler's own DEXA recheck interval), never a hand-typed string.

Guards:
1. `_physical_cadences()` numbers come FROM the registry / the shared constant —
   a registry change flows through, a hand-edit that forks them fails here.
2. `next_dexa_recommended` and the DEXA cadence label share ONE constant.
3. The front-end renders the fluid tier head before the trend hero and the
   checkpoint tier head before the first DEXA section (source-order assertion,
   same style as tests/test_data_truth_batch.py).
4. The front-end reads `d.cadences` and hand-types no interval of its own
   (the only "every N days" strings are payload-derived).
"""

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from source_registry import SOURCE_REGISTRY  # noqa: E402
from web import site_api_observatory as obs  # noqa: E402

EV_BODY = open(os.path.join(_REPO, "site", "assets", "js", "evidence_body.js")).read()


# ── 1. cadence block derives from the registry, not hand-typed strings ──────────


def test_weight_cadence_derives_from_withings_registry_entry():
    c = obs._physical_cadences()
    w = SOURCE_REGISTRY["withings"]
    assert c["weight"]["kind"] == "fluid"
    assert c["weight"]["source"] == "withings"
    assert c["weight"]["stale_days"] == w["stale_hours"] // 24
    assert c["weight"]["expected_days_per_week"] == w["expected_days"]
    # the label carries the registry number — if the registry moves, the label moves
    assert str(w["expected_days"]) in c["weight"]["label"]


def test_dexa_cadence_uses_the_shared_recheck_constant():
    c = obs._physical_cadences()
    assert c["dexa"]["kind"] == "checkpoint"
    assert c["dexa"]["interval_days"] == obs.DEXA_RECHECK_DAYS
    assert str(obs.DEXA_RECHECK_DAYS) in c["dexa"]["label"]


def test_checkpoint_entries_are_all_checkpoint_kind():
    c = obs._physical_cadences()
    for k in ("dexa", "phenoage", "tape"):
        assert c[k]["kind"] == "checkpoint", k
    # labels are self-describing (they name the measurement they speak for)
    assert c["phenoage"]["label"].lower().startswith("phenoage")
    assert c["tape"]["label"].lower().startswith("tape")


# ── 2. next_dexa_recommended and the label can't drift apart ────────────────────


def test_next_dexa_recommended_shares_the_constant():
    src = open(os.path.join(_REPO, "lambdas", "web", "site_api_observatory.py")).read()
    assert "timedelta(days=DEXA_RECHECK_DAYS)" in src
    # the old hand-typed interval is gone from the DEXA path
    assert "scan_dt + timedelta(days=90)" not in src


# ── 3. front-end structure: fluid tier first, checkpoint block grouped+labeled ──


def _render_physical_src():
    i = EV_BODY.index("export async function renderPhysical")
    return EV_BODY[i:]


def test_fluid_tier_head_renders_before_checkpoint_tier_head():
    body = _render_physical_src()
    i_fluid = body.index('physicalTierHead("The daily signal"')
    i_hero = body.index("physicalTrendHero(readings")
    i_checkpoint = body.index('physicalTierHead("The checkpoints"')
    i_dexa = body.index("physicalDexaCountdown(d)")
    assert i_fluid < i_hero, "the fluid tier head must lead the page"
    assert i_hero < i_checkpoint, "every fluid section sits above the checkpoint head"
    assert i_checkpoint < i_dexa, "the checkpoint head labels the DEXA/PhenoAge block"


def test_checkpoint_tier_head_carries_the_cadence_chips():
    body = _render_physical_src()
    m = re.search(r'physicalTierHead\("The checkpoints"[\s\S]*?\[(.*?)\]', body)
    assert m, "checkpoint tier head must pass cadence chips"
    assert "cad.dexa" in m.group(1) and "cad.phenoage" in m.group(1) and "cad.tape" in m.group(1)


def test_frontend_reads_payload_cadences_and_hand_types_no_interval():
    # the renderer consumes d.cadences …
    assert "physicalCadences(d)" in EV_BODY
    assert "d.cadences" in EV_BODY or "(d && d.cadences)" in EV_BODY
    # … and never hand-types a cadence interval: any "every N days" literal in the
    # physical renderer must be template-interpolated from payload data, not a number.
    for m in re.finditer(r"every\s+(\S+)\s+days", EV_BODY):
        assert not m.group(1).strip("~").isdigit(), f"hand-typed cadence found: {m.group(0)}"
