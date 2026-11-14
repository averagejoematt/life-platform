"""tests/test_tier_review_5861.py — the tier review is generated from the library's own rated taxonomy (#5861 fix round 13).

The earlier review copies used a hand-kept muscle list, so a rated target the list did not name (the hip abductors, with an
S-rated machine) had no section. `scripts/gen_tier_review_5861.py` builds every section from the JSON; this test holds it
to the JSON both ways: every rated target and every rated movement appears exactly where it should, once, and every count
reconciles. Controls: a rated row the generator drops, a row placed under the wrong tier, and a count that drifted.
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts"):
    sys.path.insert(0, str(_p))

import gen_tier_review_5861 as gen  # noqa: E402
from training import quality_rubric as qr  # noqa: E402

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
CHARTER = json.loads((REPO / "config" / "training_charter.json").read_text())
MV = LIB["movements"]
REVIEW = gen.review(LIB, CHARTER)
TEXT = gen.render(REVIEW)
TIERS = qr.QUALITY_TIERS


def _placed(section: dict) -> dict[str, str]:
    """movement key -> the tier it is shown under in one section (a folded alias counts where its canonical's line sits)."""
    out: dict[str, str] = {}
    for tier, rows in section["rows"].items():
        for row in rows:
            for key in [row["key"]] + row["folded"]:
                assert key not in out, f"{section['id']}: {key} appears twice"
                out[key] = tier
    return out


def _offenders(review: dict, lib: dict) -> list[str]:
    """Every way the review can disagree with the library: a rated target with no section, a rated movement missing from
    its section or under the wrong tier, an unrated one shown, a count that does not reconcile."""
    mv, out = lib["movements"], []
    want: dict[str, dict[str, str]] = {}
    for key, e in mv.items():
        for r in e["hypertrophy"]:
            if r.get("tier") in TIERS:
                want.setdefault(str(r["target"]), {})[key] = r["tier"]
    have = {s["id"]: _placed(s) for s in review["hypertrophy"]}
    out += [f"target {t}: rated in the library, no section" for t in sorted(set(want) - set(have))]
    out += [f"target {t}: a section with no rated row" for t in sorted(set(have) - set(want))]
    for t in sorted(set(want) & set(have)):
        if want[t] != have[t]:
            out.append(f"hypertrophy/{t}: {sorted(set(want[t].items()) ^ set(have[t].items()))[:4]}")
    for s in review["objectives"]:
        expect = {k: e["ratings"][s["id"]]["tier"] for k, e in mv.items() if e["ratings"][s["id"]]["tier"] in TIERS}
        if expect != _placed(s):
            out.append(f"{s['id']}: {sorted(set(expect.items()) ^ set(_placed(s).items()))[:4]}")
    prov = lib["_provenance"]
    for s in review["hypertrophy"] + review["objectives"]:
        shown = {t: sum(1 + len(r["folded"]) for r in s["rows"][t]) for t in TIERS}
        if shown != s["counts"]:
            out.append(f"{s['id']}: header counts {s['counts']} but {shown} rows are listed")
    if review["hypertrophy_rows_by_tier"] != {t: prov["hypertrophy_rows_by_tier"][t] for t in TIERS}:
        out.append("hypertrophy rows by tier do not reconcile with _provenance")
    for s in review["objectives"]:
        if s["counts"] != {t: prov["ratings_by_objective"][s["id"]][t] for t in TIERS}:
            out.append(f"{s['id']} counts do not reconcile with _provenance")
    return out


def test_every_rated_target_and_movement_appears_exactly_where_it_should():
    assert _offenders(REVIEW, LIB) == []
    assert [s["id"] for s in REVIEW["objectives"]] == [o for o in qr.OBJECTIVES if o != "hypertrophy"]
    assert REVIEW["movements"] == len(MV) == LIB["_provenance"]["movements"]
    assert REVIEW["canonical"] + REVIEW["aliases"] + REVIEW["variants"] == len(MV), "canonical + aliases + variants = every movement"


def test_the_hip_abductors_have_their_section_and_its_s_rated_machine():
    """The v5 review's defect: the JSON's target id is `hip_abductors`; the hand list said `abductors`, so it was dropped."""
    section = next(s for s in REVIEW["hypertrophy"] if s["id"] == "hip_abductors")
    assert [r["key"] for r in section["rows"]["S"]] == ["hip_abduction_machine"] and section["counts"]["S"] == 1
    row = section["rows"]["S"][0]
    assert "unknown: not served" in row["flags"], "the deferred machine is flagged, not hidden"
    assert "### Hip abductors (`hip_abductors`): S 1" in TEXT and "Hip Abduction (Machine) (`hip_abduction_machine`)" in TEXT


def test_the_markdown_carries_every_section_row_and_count():
    blocks = re.split(r"^#{2,3} ", TEXT, flags=re.M)
    by_id = {m.group(1): b for b in blocks if (m := re.match(r"[^\n]*\(`([a-z_]+)`\): ", b))}
    for s in REVIEW["hypertrophy"] + REVIEW["objectives"]:
        block = by_id[s["id"]]
        assert " · ".join(f"{t} {s['counts'][t]}" for t in TIERS) in block.splitlines()[0], s["id"]
        for tier, rows in s["rows"].items():
            for row in rows:
                line = next(ln for ln in block.splitlines() if f"(`{row['key']}`)" in ln)
                assert gen.EVIDENCE_WORDS[row["evidence"]] in line, f"{s['id']}/{row['key']}: evidence confidence on every row"
                assert any(w in line for w in gen.AVAILABILITY_WORDS.values()), f"{s['id']}/{row['key']}: an availability state"
                for alias in row["folded"]:
                    assert f"`{alias}`" in line, f"{alias}: a folded alias is named on its canonical's line"
    assert len(by_id) == len(REVIEW["hypertrophy"]) + len(REVIEW["objectives"])


def test_the_header_says_what_the_ratings_rest_on_and_implies_no_trial():
    rc = REVIEW["row_confidence"]
    assert sum(rc.values()) == sum(LIB["_provenance"]["hypertrophy_rows_by_tier"][t] for t in TIERS)
    assert f"{rc['none_reviewed']} of {sum(rc.values())} rated hypertrophy rows" in TEXT
    assert "biomechanical and practical judgment" in TEXT and "No trial was reviewed, and none is implied" in TEXT
    assert "never demoted for lacking a trial" in TEXT and "Why there is no D" in TEXT
    assert REVIEW["hypertrophy_rows_by_tier"]["D"] == 0 and REVIEW["score_range"]["by_tier"]["D"] is None
    for key, e in MV.items():  # no generated basis line implies a trial for an unreviewed rating
        for r in e["hypertrophy"]:
            if r.get("evidence_confidence") == "none_reviewed":
                loud = [
                    b for b in r.get("basis") or [] if re.search(r"trial|study|studies|proven|research", b) and "untested form" not in b
                ]
                assert loud == [], f"{key}: {loud}"
    assert set(qr.EVIDENCE_MEANING) == set(qr.EVIDENCE_CONFIDENCE) == set(gen.EVIDENCE_WORDS)
    assert "claims no trial" in LIB["quality_rubric"]["evidence"]["meaning"]["none_reviewed"]


def test_flags_show_anchor_gate_template_and_variant():
    def flags(key):
        return gen.flags(LIB, key, CHARTER)

    assert "anchor" in flags("squat_barbell")
    assert "gated (locked)" in flags("pull_up") and "gated (locked)" in flags("kettlebell_swing")
    assert "needs a Hevy template" in flags("landmine_squat") and "needs a Hevy template" in flags("kettlebell_deadlift")
    assert "logged as suitcase_carry" in flags("kettlebell_suitcase_carry")
    assert "variant of pull_up" in flags("pull_up_assisted")
    assert "confirmed unavailable" in flags("preacher_curl_machine")
    assert all(any(w in flags(k) for w in gen.AVAILABILITY_WORDS.values()) for k in MV), "every row names its availability state"


def test_the_review_reads_nothing_private():
    src = (REPO / "scripts" / "gen_tier_review_5861.py").read_text()
    assert not re.search(r"boto3|private|overlay|scratchpad|get_object|dynamodb", src.split('"""', 2)[2], re.I)


# ── must-fail controls ───────────────────────────────────────────────────────────────────────────────────────────────
def test_must_fail_a_hand_list_that_drops_a_target():
    dropped = copy.deepcopy(REVIEW)
    dropped["hypertrophy"] = [s for s in dropped["hypertrophy"] if s["id"] != "hip_abductors"]
    assert any("target hip_abductors: rated in the library, no section" in o for o in _offenders(dropped, LIB))


def test_must_fail_a_row_under_the_wrong_tier_or_missing():
    wrong = copy.deepcopy(REVIEW)
    chest = next(s for s in wrong["hypertrophy"] if s["id"] == "chest")
    chest["rows"]["B"].append(chest["rows"]["S"].pop())
    assert any(o.startswith("hypertrophy/chest") for o in _offenders(wrong, LIB))
    gone = copy.deepcopy(REVIEW)
    next(s for s in gone["objectives"] if s["id"] == "strength")["rows"]["S"].pop()
    offenders = _offenders(gone, LIB)
    assert any(o.startswith("strength:") for o in offenders) and any("header counts" in o for o in offenders)


def test_must_fail_the_generator_refuses_counts_that_do_not_reconcile():
    drifted = copy.deepcopy(LIB)
    drifted["_provenance"]["hypertrophy_rows_by_tier"]["S"] += 1
    with pytest.raises(SystemExit, match="do not reconcile"):
        gen.review(drifted, CHARTER)
    moved = copy.deepcopy(LIB)
    moved["movements"]["squat_barbell"]["ratings"]["strength"]["tier"] = "A"  # the library's own count no longer matches
    with pytest.raises(SystemExit, match="strength does not reconcile"):
        gen.review(moved, CHARTER)
