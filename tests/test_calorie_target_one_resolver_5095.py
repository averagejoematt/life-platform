"""tests/test_calorie_target_one_resolver_5095.py — ONE calorie target (#5095, epic #5091).

# premerge-gate: a repo-shape ratchet — sweeps lambdas/, mcp/, deploy/ and scripts/ for the retired calorie constant's name and for a new 1,500 kcal literal

Before #5095 six readers held three targets: a generated 1,500 kcal constant (scoring, the
character sheet, the daily brief, the weekly/monthly/nutrition/partner emails, the insight and
hypothesis engines), the redlines' prescribed band (the nutrition critics only) and TDEE - 500
(the macros tool and the coach's domain facts). Every one now resolves through
`health.calorie_target`. Four legs:

  (a) the resolver: titration record > charter `nutrition.calories`, provenance named, the
      any-day floor clamps, an unreadable charter is an absence (never a remembered number);
  (b) the SET guard: no module under lambdas/ mcp/ deploy/ scripts/ names the retired
      constant, and no code line carries a 1,500 NUMBER beside a calorie word — every
      offender is reported, with a positive and a negative control for the detector;
  (c) the cross-surface contract: scoring, the email builders, the coach's domain facts, the
      macros tool and the critics state the SAME kcal for one fixture date, fed the stored
      MacroFactor row as boto3 returns it (Decimal, `total_calories_kcal`);
  (d) the character engine reads the row's MacroFactor-app target by its STORED name
      (`target_calories_kcal`, was misspelt `target_calories`) — as a drift signal only.

NOT SEEN, stated: a calorie target written in prose ("1,500 kcal" inside a string — the
sealed pre-registration and the redlines' history notes say it legitimately); a target
computed at runtime from other literals; the sealed plan root `config/user_goals.json`
`daily_calories_target` (hash-stamped in the frozen pre-registration — the genesis figure,
history, read by story_dossier as "the sealed plan"); and the site's published energy budget
(lambdas/web/site_api_nutrition.py), a published surface this lane does not re-point.
"""

from __future__ import annotations

import io
import logging
import os
import pathlib
import re
import sys
import tokenize
from decimal import Decimal
from typing import List

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
for _p in (_REPO / "lambdas", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("AWS_REGION", "us-west-2"),
    ("EMAIL_RECIPIENT", "reader@example.invalid"),
    ("EMAIL_SENDER", "sender@example.invalid"),
    ("S3_BUCKET", "test-bucket"),
    ("AI_VALIDATOR_AUTOLOAD", "off"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)

from health import calorie_target as ct  # noqa: E402
from training import training_charter as tc  # noqa: E402

FIXTURE_DAY = "2026-10-17"
# The stored MacroFactor day row as boto3 returns it (the #4580 wire fixture's shape), plus the
# app's own target the ingest writes as `target_calories_kcal` (macrofactor_lambda.py).
MF_ROW = {
    "pk": "USER#matthew#SOURCE#macrofactor",
    "sk": f"DATE#{FIXTURE_DAY}",
    "date": FIXTURE_DAY,
    "schema_version": Decimal("1"),
    "total_calories_kcal": Decimal("1561"),
    "total_protein_g": Decimal("133"),
    "total_carbs_g": Decimal("162"),
    "total_fat_g": Decimal("37"),
    "target_calories_kcal": Decimal("1500"),
}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """No live S3 probe and no laptop twin: the tracked charter file is the only input."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _charter(**over):
    block = {
        "target_kcal": 2100,
        "prescribed_band_kcal": [2000, 2100],
        "floor_any_day_kcal": 1600,
        "floor_lifting_day_kcal": 1900,
    }
    block.update(over)
    data = {"version": "9.9.9", ct.CHARTER_PATH: block}
    return lambda dotted: data.get(dotted)


# ── (a) the resolver ──────────────────────────────────────────────────────────────────────
def test_the_charter_block_is_the_target_with_its_provenance():
    r = ct.resolve(FIXTURE_DAY, charter_reader=_charter())
    assert (r["kcal"], r["band_low"], r["band_high"], r["source"]) == (2100, 2000, 2100, "charter")
    assert r["charter_version"] == "9.9.9" and "nutrition.calories.target_kcal" in r["provenance"]
    assert (r["floor_any_day_kcal"], r["floor_lifting_day_kcal"]) == (1600, 1900)


def test_a_titration_record_for_the_week_outranks_the_charter():
    seen: List[str] = []

    def reader(week):
        seen.append(week)
        return {"kcal": Decimal("1950"), "band_low": 1900, "band_high": 2000, "reason": "two out-of-band reads"}

    r = ct.resolve(FIXTURE_DAY, titration_reader=reader, charter_reader=_charter())
    assert seen == ["2026-10-12"], "the reader is asked for the ISO Monday of the day's week"
    assert (r["kcal"], r["band_low"], r["band_high"], r["source"]) == (1950, 1900, 2000, "titration")
    assert r["provenance"].startswith("titration record WEEK#2026-10-12") and "two out-of-band reads" in r["provenance"]


def test_an_absent_or_empty_titration_record_falls_through_to_the_charter():
    for record in (None, {}, {"kcal": None}, {"kcal": 0}):
        r = ct.resolve(FIXTURE_DAY, titration_reader=lambda week, rec=record: rec, charter_reader=_charter())
        assert (r["kcal"], r["source"]) == (2100, "charter"), record


def test_the_any_day_floor_clamps_whatever_was_resolved():
    r = ct.resolve(FIXTURE_DAY, titration_reader=lambda week: {"kcal": 1400}, charter_reader=_charter())
    assert r["kcal"] == 1600 and r["source"] == "titration"
    assert "clamped up to the any-day floor 1600 kcal (resolved 1400)" in r["provenance"]
    r = ct.resolve(FIXTURE_DAY, charter_reader=_charter(target_kcal=1200))
    assert r["kcal"] == 1600 and "clamped" in r["provenance"]


def test_an_unreadable_charter_is_an_absence_never_a_remembered_number():
    r = ct.resolve(FIXTURE_DAY, charter_reader=lambda dotted: None)
    assert (r["kcal"], r["source"]) == (None, "unavailable")
    assert ct.target_kcal(FIXTURE_DAY, charter_reader=lambda dotted: None) is None
    assert ct.target_phrase(FIXTURE_DAY, charter_reader=lambda dotted: None) == "no calorie target resolved"


def test_the_record_shape_is_the_schema_row():
    assert ct.TITRATION_PK == "USER#matthew#SOURCE#nutrition_titration"
    assert ct.titration_sk("2026-10-18") == "WEEK#2026-10-12"  # a Sunday belongs to the week that began Monday
    assert ct.titration_sk("2026-10-19") == "WEEK#2026-10-19"
    schema = (_REPO / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    assert "nutrition_titration" in schema and "WEEK#<iso-monday>" in schema


def test_the_public_charter_carries_the_block_and_the_redlines_read_it():
    from training import owner_redlines

    block = tc.charter_value(ct.CHARTER_PATH)
    assert block and ct.target_kcal(FIXTURE_DAY) == block["target_kcal"]
    lo, hi = block["prescribed_band_kcal"]
    assert lo <= block["target_kcal"] <= hi, "panel default R1: the target sits in the prescribed band"
    energy = owner_redlines.REDLINES["energy_floor_kcal"]
    assert energy["prescribed"] == block["prescribed_band_kcal"] and energy["opening_kcal"] == block["target_kcal"]
    assert (energy["floor_any_day"], energy["floor_lifting_day"]) == (block["floor_any_day_kcal"], block["floor_lifting_day_kcal"])


def test_a_dated_resolve_reads_no_clock(monkeypatch):
    """#4848: the resolver reads the clock only when no day is given."""
    import common.pacific_time as pt

    monkeypatch.setattr(pt, "pacific_today", lambda: (_ for _ in ()).throw(AssertionError("clock read")))
    assert ct.resolve(FIXTURE_DAY, titration_reader=lambda w: None)["kcal"] == ct.target_kcal(FIXTURE_DAY)
    assert ct.resolve(None)["week"] is None  # no day and no reader: no week needed, no clock


# ── (b) the SET guard ─────────────────────────────────────────────────────────────────────
SWEPT_DIRS = ("lambdas", "mcp", "deploy", "scripts")
RETIRED_NAME = "PLAN_DAILY_CALORIES_TARGET"
_CAL_WORD = re.compile(r"(?<![a-z])k?cal(?:orie|ories|s)?(?![a-z])", re.IGNORECASE)  # `cal_target`, `kcal`, not `_call_`
_RETIRED_FIGURES = {1500.0}


def literal_findings(src: str, rel: str = "<src>") -> List[str]:
    """Every code line carrying a 1,500 NUMBER token beside a calorie word in its code (names and
    strings — comments are dropped), and every mention of the retired constant's name anywhere."""
    out: List[str] = []
    if RETIRED_NAME in src:
        out += [f"{rel}:{i}: names {RETIRED_NAME}" for i, ln in enumerate(src.splitlines(), 1) if RETIRED_NAME in ln]
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return out
    by_line: dict[int, list] = {}
    for t in toks:
        if t.type != tokenize.COMMENT:
            by_line.setdefault(t.start[0], []).append(t)
    for line, ts in sorted(by_line.items()):
        nums = [t for t in ts if t.type == tokenize.NUMBER]
        if not nums:
            continue
        try:
            hit = any(float(t.string.replace("_", "")) in _RETIRED_FIGURES for t in nums)
        except ValueError:
            continue
        if hit and any(_CAL_WORD.search(t.string) for t in ts if t.type in (tokenize.NAME, tokenize.STRING)):
            out.append(f"{rel}:{line}: a 1,500 calorie literal")
    return out


def _swept() -> List[pathlib.Path]:
    return sorted(p for d in SWEPT_DIRS for p in (_REPO / d).rglob("*.py") if "__pycache__" not in p.parts)


def test_no_module_reads_the_retired_constant_or_retypes_the_1500_target():
    """THE SET guard: one test over the four trees, every offender reported."""
    found: List[str] = []
    files = _swept()
    for path in files:
        found += literal_findings(path.read_text(encoding="utf-8"), path.relative_to(_REPO).as_posix())
    assert len(files) > 800, f"the sweep walked only {len(files)} modules — a tree moved"
    assert (
        not found
    ), "the calorie target is health.calorie_target's (#5095) — never the retired constant, never a literal:\n  " + "\n  ".join(found)


def test_the_detector_sees_each_shape_and_passes_the_clean_ones():
    shapes = {
        "PLAN_DAILY_CALORIES_TARGET = 1500": 2,  # the name AND the literal
        "from common.constants import PLAN_DAILY_CALORIES_TARGET": 1,
        "cal_target = 1500": 1,
        'x = p.get("calorie_target", 1500)': 1,
        "target_kcal = 1_500": 1,
        "kcal_floor = 1500.0": 1,
    }
    for src, n in shapes.items():
        assert len(literal_findings(src)) == n, (src, literal_findings(src))
    clean = [
        "max_tokens = 1500",  # a token cap, not calories
        "cal_target = target_kcal(day)  # was 1500",  # a comment is not code
        'note = "1,500 kcal reproduces 3.5 only at today\'s walking"',  # prose is not a literal
        "delay_ms = 1500\ncalories = row['kcal']",  # the figure and the word on DIFFERENT lines
        "_call_haiku(prompt, max_tokens=1500)",  # `call` is not a calorie word
    ]
    for src in clean:
        assert literal_findings(src) == [], src


# ── (c) the cross-surface contract ────────────────────────────────────────────────────────
class _NoRowsTable:
    """A DynamoDB table with nothing in it: the coach pack's TDEE path reports absence."""

    def query(self, **_kw):
        return {"Items": []}

    def get_item(self, **_kw):
        return {}


def test_every_surface_states_the_same_kcal_for_one_day(monkeypatch):
    want = ct.target_kcal(FIXTURE_DAY)
    assert want, "the bundled charter must resolve a target"
    got: dict[str, object] = {}

    from health import nutrition_critics, scoring_engine

    got["scoring"] = scoring_engine.score_nutrition({"date": FIXTURE_DAY, "macrofactor": MF_ROW}, {})[1]["cal_target"]
    energy = nutrition_critics._energy({"window_end": FIXTURE_DAY})
    got["critics"] = energy["target_kcal"]
    r = ct.resolve(FIXTURE_DAY)
    assert energy["prescribed"] == [r["band_low"], r["band_high"]], "the critics grade the resolver's band"

    from emails import monthly_digest_lambda, weekly_digest_extractors, weekly_plate_lambda

    got["weekly_digest"] = weekly_digest_extractors.ex_macrofactor({FIXTURE_DAY: MF_ROW}, {})["calorie_target"]
    got["monthly_digest"] = monthly_digest_lambda.ex_macrofactor([MF_ROW])["calorie_target"]
    plate = weekly_plate_lambda.build_system_prompt({"calorie_target": 1800}, {})
    got["weekly_plate"] = want if f"{want} cal/day" in plate else plate

    from coach import coach_domain_facts

    pack = "\n".join(coach_domain_facts._nutrition_pack(_NoRowsTable(), FIXTURE_DAY))
    m = re.search(r"Calorie target: (\d+) kcal/day", pack)
    got["coach_facts"] = int(m.group(1)) if m else pack

    from mcp import tools_nutrition as tn

    monkeypatch.setattr(tn, "query_source_cross_phase", lambda src, *a, **k: [MF_ROW] if src == "macrofactor" else [])
    monkeypatch.setattr(tn, "_energy_budget", lambda *a, **k: None)
    monkeypatch.setattr(tn, "_shared_loss_rate", lambda *a, **k: None)
    got["macros_tool"] = tn.tool_get_nutrition({"view": "macros", "start_date": FIXTURE_DAY, "end_date": FIXTURE_DAY})["targets"][
        "calories_kcal"
    ]

    assert {k: v for k, v in got.items() if v != want} == {}, f"surfaces disagree with the resolver's {want}: {got}"


# ── (d) the character engine's field fix ──────────────────────────────────────────────────
def test_the_character_engine_reads_the_app_target_by_its_stored_name_as_drift_only(caplog):
    from common import macrofactor_fields as mff
    from health import character_engine

    assert mff.APP_TARGET_CALORIES_FIELD == "target_calories_kcal"
    assert mff.app_target_kcal(MF_ROW) == 1500.0
    src = (_REPO / "lambdas" / "health" / "character_engine.py").read_text(encoding="utf-8")
    assert '"target_calories"' not in src and '"calorie_target"' not in src, "the misspelt / profile names are gone"

    data = {"date": FIXTURE_DAY, "macrofactor": MF_ROW, "macrofactor_14d": [], "latest_weight": None}
    with caplog.at_level(logging.WARNING, logger=character_engine.logger.name):
        _, details = character_engine.compute_nutrition_raw(data, {"pillars": {"nutrition": {"components": {}}}})
    assert any("MacroFactor app target 1500 kcal" in rec.getMessage() for rec in caplog.records), "drift signal on the stored name"

    # the score is graded against the ONE target, not the app's 1,500: |1561 - 2100| / 2100 > 20 % -> 0
    want = ct.target_kcal(FIXTURE_DAY)
    expected = max(0.0, min(100.0, round(100 - (abs(1561 - want) / want / 0.20) * 100, 1)))
    _, d2 = character_engine.compute_nutrition_raw(data, {"pillars": {"nutrition": {"components": {"calorie_adherence": {"weight": 1.0}}}}})
    assert d2["calorie_adherence"]["score"] == expected

    # mutation control: the pre-fix spelling finds nothing on the stored row
    assert MF_ROW.get("target_calories") is None
