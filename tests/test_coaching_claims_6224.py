"""tests/test_coaching_claims_6224.py — two claims the coaching pages served must not be publicly served (#6224).

Owner ruling 2026-11-23: /coaching/ carried (1) an unsupported medical milestone claim and (2) a food day whose
export had not arrived described as nothing logged. Both came from the morning brief's AI lines, which the brief publishes to
public_stats.json (the daily line on /coaching/, /coaching/read/, /cockpit/, the legacy home) and pulse.json.

The texts below are FICTIONAL stand-ins for the claim classes (other conditions, numbers and wording). The exact
served originals are private: a local-only test reads them from the evidence folder when the file is there.

What is pinned:
  1. the screen (``content.public_claim_screen``) withholds each claim shape and serves clean lines — reusing the
     Morning Brief's screen, not a fork of it;
  2. the food-log rule follows ``food_log_state.arrival``: pending or unknown -> withheld; arrived -> served;
  3. the real writer (``site_writer.write_public_stats`` / ``write_pulse_json``) on a Decimal-typed fake table
     writes neither claim, keeps a clean line, and the pulse falls back to its own computed narrative;
  4. the Site API wire screen (``web.coach_read_screen``) empties a tripping coach read on a coaching route and only
     there, and the wire tail calls it;
  5. the /coaching/ no-JS copy no longer says the board has not published when it has.
Each rule has a must-fail control.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from content import brief_rec_screen, public_claim_screen as P, site_writer  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import coach_read_screen as C  # noqa: E402

# Fictional paraphrase-equivalents of the served claims (never the originals).
MILESTONE = "Recovery held at 72 and you dipped under 250 lb, the line where your diabetes risk falls off."
GENOMIC = "Your genetic results say this kind of progress matters more for you than for most people."
ZERO_FOOD = "Sleep was solid at 7.9 hours, but no food logged means the day's real story is still missing."
LOW_FOOD = "Plenty of steps, but only 20g protein logged — the training has no nutrition under it yet."
CLEAN = ["Sleep was solid at 7.9 hours and recovery 72 — a good base for today.", "A walk after dinner would lift the step count."]

DATA_DAY = "2026-03-10"
PRIVATE_FIXTURE = Path(os.path.expanduser("~/Documents/Claude/public-review-2026-11-23/fix_evidence/private_claims_6224.json"))


# ── 1. the screen ────────────────────────────────────────────────────────────────────────────


def test_the_medical_claims_are_withheld_and_clean_lines_pass():
    assert "disease" in P.medical_classes(MILESTONE)
    assert "genomic" in P.medical_classes(GENOMIC)
    for text in (MILESTONE, GENOMIC):
        assert P.publishable(text, data_day=DATA_DAY, last_arrival_day="2026-03-11") is None
    for text in CLEAN:
        assert P.withheld_reasons(text, data_day=DATA_DAY, last_arrival_day="2026-03-11") == []
        assert P.publishable(text, data_day=DATA_DAY, last_arrival_day="2026-03-11") == text
    # Reuse, not a fork: the classes are the Morning Brief screen's own, sentence by sentence.
    assert P.medical_classes(MILESTONE) == brief_rec_screen.screen(MILESTONE, "")[1]
    # A unit is withheld whole: a clean sentence beside a tripping one does not survive on its own.
    assert P.publishable(CLEAN[0] + " " + GENOMIC) is None


def test_must_fail_control_the_screen(monkeypatch):
    monkeypatch.setattr(brief_rec_screen, "screen", lambda text, source: (True, []))
    with pytest.raises(AssertionError):
        assert P.publishable(MILESTONE) is None


def test_a_food_log_claim_follows_the_shared_arrival_rule():
    for text in (ZERO_FOOD, LOW_FOOD):
        assert P.withheld_reasons(text, data_day=DATA_DAY, last_arrival_day=DATA_DAY) == [P.FOOD_LOG_PENDING]  # not arrived
        assert P.withheld_reasons(text, data_day=DATA_DAY, last_arrival_day=None) == [P.FOOD_LOG_PENDING]  # unknown
        assert P.withheld_reasons(text, data_day=None, last_arrival_day="2026-03-11") == [P.FOOD_LOG_PENDING]  # no day
        assert P.withheld_reasons(text, data_day=DATA_DAY, last_arrival_day="2026-03-11") == []  # arrived: a real zero
    # Mutation control: an arrival rule that always says "arrived" lets the pending claim through.
    from common import food_log_state

    real = food_log_state.arrival
    try:
        food_log_state.arrival = lambda day, last: food_log_state.ARRIVED
        with pytest.raises(AssertionError):
            assert P.withheld_reasons(ZERO_FOOD, data_day=DATA_DAY, last_arrival_day=DATA_DAY) == [P.FOOD_LOG_PENDING]
    finally:
        food_log_state.arrival = real


@pytest.mark.skipif(not PRIVATE_FIXTURE.exists(), reason="local-only: the exact served originals live outside the repo")
def test_the_exact_served_originals_are_withheld_local_only():
    fx = json.loads(PRIVATE_FIXTURE.read_text(encoding="utf-8"))
    assert fx["units"]
    for unit in fx["units"]:
        # Withheld while its day's export is pending (each one also trips the medical screen or makes a food-log claim).
        assert P.publishable(unit, data_day=fx["data_day"], last_arrival_day=fx["data_day"]) is None
        assert P.medical_classes(unit) or P.food_log_claim(unit)


# ── 2. the real writer, on a Decimal-typed fake table ─────────────────────────────────────────


class _S3:
    def __init__(self):
        self.puts: dict = {}

    def put_object(self, **kw):
        self.puts[kw["Key"]] = kw["Body"]


def _cond_strings(cond, out):
    for v in getattr(cond, "_values", ()) or ():
        if isinstance(v, str):
            out.append(v)
        else:
            _cond_strings(v, out)
    return out


def _table(last_export_landed: str) -> FakeDdbTable:
    """macrofactor rows as the table stores them (Decimal numbers, an ISO arrival stamp); everything else empty."""
    rows = [
        {
            "pk": "USER#matthew#SOURCE#macrofactor",
            "sk": "DATE#2026-03-09",
            "total_calories_kcal": Decimal("2140"),
            "protein_g": Decimal("161.5"),
            "ingested_at": f"{last_export_landed}T18:00:00+00:00",
        }
    ]

    def hook(_t, **kw):
        pk = next((s for s in _cond_strings(kw.get("KeyConditionExpression"), []) if s.startswith("USER#")), "")
        return {"Items": list(rows) if pk.endswith("macrofactor") else []}

    return FakeDdbTable(query_hook=hook)


def _write(hero, excerpt, landed):
    s3 = _S3()
    ok = site_writer.write_public_stats(
        s3,
        vitals={"weight_lbs": 250.0},
        journey={"current_weight_lbs": 250.0},
        training={},
        table_client=_table(landed),
        brief_excerpt=excerpt,
        group_narratives={"platform": excerpt[:160] if excerpt else None, "body": "Currently at 250.0 lbs."},
        elena_hero_line=hero,
        elena_hero_line_as_of=DATA_DAY,
        brief_data_day=DATA_DAY,
    )
    assert ok
    return json.loads(s3.puts[site_writer.PUBLIC_STATS_KEY])


def test_public_stats_never_carries_either_claim():
    out = _write(ZERO_FOOD, ZERO_FOOD + " " + GENOMIC, landed="2026-03-10")  # the export has not arrived for DATA_DAY
    assert out["elena_hero_line"] is None and out["elena_hero_line_as_of"] is None
    assert out["brief_excerpt"] is None
    assert "platform" not in out["group_narratives"] and out["group_narratives"]["body"] == "Currently at 250.0 lbs."
    blob = json.dumps(out).lower()
    assert "genetic" not in blob and "food logged" not in blob


def test_public_stats_keeps_a_clean_line_and_a_real_zero():
    out = _write(CLEAN[0], CLEAN[0] + " " + CLEAN[1], landed="2026-03-10")
    assert out["elena_hero_line"] == CLEAN[0] and out["elena_hero_line_as_of"] == DATA_DAY
    out = _write(ZERO_FOOD, ZERO_FOOD, landed="2026-03-12")  # the export arrived after the day ended: a real zero
    assert out["elena_hero_line"] == ZERO_FOOD


def test_must_fail_control_the_writer(monkeypatch):
    monkeypatch.setattr(site_writer, "screen_public_lines", lambda h, b, g, **_k: (h, b, g))
    out = _write(MILESTONE, MILESTONE, landed="2026-03-12")
    with pytest.raises(AssertionError):
        assert out["elena_hero_line"] is None


def test_the_pulse_narrative_falls_back_when_the_excerpt_is_withheld():
    s3 = _S3()
    assert site_writer.write_pulse_json(
        s3, vitals={}, journey={}, training={}, brief_excerpt=GENOMIC, table_client=_table("2026-03-12"), brief_data_day=DATA_DAY
    )
    narrative = json.loads(s3.puts[site_writer.PULSE_KEY])["pulse"]["narrative"]
    assert narrative and "genetic" not in narrative.lower()


def test_the_stats_refresh_rescreens_what_it_preserves():
    """The refresh keeps the morning's lines; it must pass them through the same screen on the way back out."""
    src = (ROOT / "lambdas" / "web" / "site_stats_refresh_lambda.py").read_text(encoding="utf-8")
    assert "screen_public_lines(" in src and src.index("screen_public_lines(") < src.index("Key=STATS_KEY,\n        Body=")


# ── 3. the Site API wire, coaching routes ─────────────────────────────────────────────────────


def _resp(body):
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def test_the_wire_empties_a_tripping_coach_read_on_a_coaching_route_only():
    body = {
        "lead_daily": {"text": MILESTONE, "coach_name": "Eli Marsh", "cited": [{"value": Decimal("250.0")}]},
        "coaches": [{"name": "Lisa Park", "position_summary": CLEAN[0]}],
        "dispute": {"turns": [{"kind": "position", "line": GENOMIC}, {"kind": "reply", "line": CLEAN[1]}]},
        "explanation": MILESTONE,  # engine copy under a non-read key is not a coach read
    }
    out = json.loads(C.screen_response("/api/coaching-dashboard", {"statusCode": 200, "body": json.dumps(body, default=str)})["body"])
    assert out["lead_daily"]["text"] == "" and out["lead_daily"]["coach_name"] == "Eli Marsh"
    assert out["coaches"][0]["position_summary"] == CLEAN[0]
    assert [t["line"] for t in out["dispute"]["turns"]] == ["", CLEAN[1]]
    assert out["explanation"] == MILESTONE
    per_coach = json.loads(C.screen_response("/api/coach/sleep_coach", _resp({"stance": {"read_of_him": GENOMIC}}))["body"])
    assert per_coach["stance"]["read_of_him"] == ""
    untouched = _resp({"text": MILESTONE})
    assert C.screen_response("/api/journey", untouched) is untouched


def test_must_fail_control_the_wire(monkeypatch):
    monkeypatch.setattr(C, "READ_KEYS", frozenset())
    out = json.loads(C.screen_response("/api/coaching-dashboard", _resp({"lead_daily": {"text": MILESTONE}}))["body"])
    with pytest.raises(AssertionError):
        assert out["lead_daily"]["text"] == ""


def test_the_wire_tail_runs_the_coach_screen_before_the_last_guard():
    src = (ROOT / "lambdas" / "web" / "site_api_lambda.py").read_text(encoding="utf-8")
    tail = src[src.index("def publication_wire(") :]
    assert tail.index("result = coach_read_screen.screen_response(path, result)") < tail.index("return guard_api_response(")


# ── 4. the /coaching/ no-JS copy and the dispute block ────────────────────────────────────────


def test_the_static_core_does_not_say_unpublished_when_the_board_has_read(monkeypatch):
    import v4_proof

    monkeypatch.setattr(v4_proof, "pre_start_date", lambda: "")
    monkeypatch.setattr(v4_proof, "_snapshot", lambda: {})
    monkeypatch.setattr(
        v4_proof,
        "_fetch_json",
        lambda path, timeout=8: {"weekly_priority": {"text": ""}, "coaches": [{"position_summary": ""}], "lead_daily": {"text": CLEAN[0]}},
    )
    read = v4_proof.load_coaching_read()
    html = v4_proof.coaching_read_block_html(read)
    assert read.get("lead_read") is True and "hasn't published its first read" not in html
    assert "load with the page" in html and CLEAN[0] not in html  # no AI words baked into the static copy


def test_the_dispute_block_never_prints_labels_over_empty_lines():
    js = (ROOT / "site" / "assets" / "js" / "coaching.js").read_text(encoding="utf-8")
    block = js[js.index("const dp = d.dispute;") : js.index("function docketHTML(")]
    assert "spoken.length < 2" in block and "are not published" in block
    assert "spoken.map(" in block and "dp.turns.map(" not in block
