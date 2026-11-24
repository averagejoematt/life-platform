"""tests/test_nutrition_review_compact_6245.py — the Saturday Nutrition Review as a three-minute read (#6245).

Owner ruling 2026-11-23 (outbound priority 1): shorten the review to about three minutes; keep the practical menu
and the shopping list; reduce repeated coach commentary, historical explanation and redundant metrics; keep the
detail on demand; and stop the subject treating a partly imported day as a full day's intake.

Every test here drives the REAL builder — `nutrition_review_lambda.lambda_handler` with its own `build_email_html` /
`nutrition_review_compact.build` — over a synthetic, Decimal-typed week (the shape DynamoDB returns). Mail is never
sent (`ses` is a fake), no model is called (the panel call is a fake that returns a three-voice edition), and nothing
reaches AWS (the table is a fake; the menu read is injected).

THE ACCEPTANCE CHECK is one function, `compact_offenders`, applied to the rendered email. It is proved able to fail
twice over: a NEGATIVE CONTROL (today's long email, which it must reject on every count that matters) and MUTATION
PROOFS (each fix undone in-process, and the check names the defect that comes back).

Clock: frozen at Saturday 2026-06-13 17:00 UTC (the review's fire slot), through the module's own Pacific seam.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import nutrition_review_lambda as m  # noqa: E402
from emails import nutrition_review_compact as nrc  # noqa: E402
from health import titration, weekly_menu_feed  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402

FROZEN_NOW = datetime(2026, 6, 13, 17, 0, 0, tzinfo=timezone.utc)  # Saturday, 10:00 PT
W1_START, W1_END = "2026-06-06", "2026-06-12"
DATES = {"this_start": W1_START, "this_end": W1_END, "prior_start": "2026-05-30", "prior_end": "2026-06-05"}
SWITCH_PK = f"USER#{m.USER_ID}#SOURCE#outbound_format"


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# ── fakes ────────────────────────────────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """GetItem by (pk, sk) for the format switch and the titration record; every query returns nothing."""

    def __init__(self):
        self.items: dict = {}
        self.get_error = None
        self.puts: list = []

    def get_item(self, Key=None, **_kw):
        if self.get_error and Key.get("pk") == SWITCH_PK:
            raise self.get_error
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **_kw):
        return {"Items": []}

    def put_item(self, Item=None, **_kw):
        self.puts.append(Item)


class FakeSES:
    def __init__(self):
        self.sent: list = []

    def send_email(self, **kw):
        self.sent.append(kw)
        return {"MessageId": "fake"}


class FakeInsightWriter:
    def build_insights_context(self, **_kw):
        return ""

    def write_insight(self, **_kw):
        pass


# ── the synthetic week (Decimal-typed, as DynamoDB serves it) ────────────────────────────────────────────────────


def _food(name, cal, protein):
    return {"food_name": name, "time": "12:00", "calories_kcal": Decimal(cal), "protein_g": Decimal(protein)}


def _row(day, cal, protein, **extra):
    rec = {
        "sk": f"DATE#{day}",
        "date": day,
        "total_calories_kcal": Decimal(str(cal)),
        "total_protein_g": Decimal(str(protein)),
        "total_carbs_g": Decimal("90"),
        "total_fat_g": Decimal("40"),
        "total_fiber_g": Decimal("30.5"),
        "entries_count": Decimal("6"),
        "ingested_at": f"{day}T05:00:00Z",
        "food_log": [_food("Flank steak", "420", "52"), _food("Edamame", "190", "17")],
    }
    rec.update(extra)
    return rec


# Six complete days (Sat 06-06 .. Thu 06-11) and Friday 06-12 exported while it was still being logged (95 kcal).
COMPLETE = {"2026-06-06": (1500, 160), "2026-06-07": (1300, 150), "2026-06-08": (1400, 170), "2026-06-09": (1200, 140),
            "2026-06-10": (1600, 180), "2026-06-11": (1100, 120)}  # fmt: skip
PARTIAL_DAY = "2026-06-12"
AVG_KCAL = int(sum(c for c, _ in COMPLETE.values()) / len(COMPLETE))  # 1350
AVG_PRO = int(sum(p for _, p in COMPLETE.values()) / len(COMPLETE))  # 153
OLD_AVG_KCAL = int((sum(c for c, _ in COMPLETE.values()) + 95) / 7)  # the partial day averaged in (the defect)


def _week_rows():
    rows = {d: _row(d, c, p) for d, (c, p) in COMPLETE.items()}
    rows[PARTIAL_DAY] = _row(PARTIAL_DAY, 95, 15, partial_at_export=True, entries_count=Decimal("1"))
    return rows


def _gathered():
    return {
        # the newest export landed Friday 06-12 (Pacific): Friday has not ended in it, so Friday cannot be whole
        "food_freshness": {"last_arrival_day": "2026-06-12", "last_intake_day": "2026-06-12"},
        "macrofactor_this": _week_rows(),
        "macrofactor_prior": {},
        "withings": {"2026-05-14": {"weight_lbs": Decimal("300.0")}, "2026-06-12": {"weight_lbs": Decimal("296.4")}},
        "strava": {},
        "cgm": {},
        "genome_snps": [],
        "latest_lab": None,
        "latest_dexa": None,
        "supplements": {},
        "habitify": {},
        "prev_review": None,
        "profile": {"goal_weight_lbs": 185, "journey_start_date": "2026-06-01", "journey_start_weight_lbs": 300},
        "dates": dict(DATES),
    }


# ── the code-built menu ahead (this week's Sunday + the coming week, the shop on the coming week) ────────────────

FIXED = {"label": "Prepared dinner", "fibre_known": False}
ANCHORS = [("Chicken breast", "Tortilla"), ("Flank steak", "Olive oil"), ("Greek yogurt", "Berries")]


def _menu_day(day, weekday, fits=True):
    feedings = []
    for i, (a, b) in enumerate(ANCHORS, start=1):
        feedings.append({"name": f"feeding {i}", "window_offset_h": Decimal(2 * (i - 1)),
                         "items": [{"servings": Decimal("1"), "label": f"{a} {day[-2:]}"}, {"servings": Decimal("2"), "label": b}]})  # fmt: skip
    feedings.append({"name": "feeding 4 (fixed dinner)", "window_offset_h": Decimal("6"), "slot": "dinner", "fixed": FIXED,
                     "kcal": Decimal("587"), "protein_g": Decimal("64"), "fibre_g": Decimal("0"), "items": []})  # fmt: skip
    return {
        "date": day, "weekday": weekday, "day_type": "rest", "service": "cook" if weekday in ("Saturday", "Sunday") else "meal_service",
        "targets": {"kcal": Decimal("1600")}, "fits": fits, "misses": [] if fits else ["fibre_g 31 under 35"],
        "totals": {"kcal": Decimal("1650"), "protein_g": Decimal("201.5"), "fat_g": Decimal("65"), "carb_g": Decimal("94"), "fibre_g": Decimal("36")},
        "feedings": feedings,
    }  # fmt: skip


COMING = [("2026-06-15", "Monday"), ("2026-06-16", "Tuesday"), ("2026-06-17", "Wednesday"), ("2026-06-18", "Thursday"),
          ("2026-06-19", "Friday"), ("2026-06-20", "Saturday", False), ("2026-06-21", "Sunday")]  # fmt: skip
GROCERY = [{"label": "Chicken breast", "servings": 4, "serving": "1 breast", "packages": 2, "package": None, "section": "meat"},
           {"label": "Tortilla", "servings": 8, "serving": "1 tortilla", "packages": 1, "package": "pack of 8", "section": None}]  # fmt: skip


def _menu(week_start, days, grocery):
    return {
        "built": True, "week_start": week_start, "days": days, "grocery_list": grocery,
        "lines": ["Food quality: MISSED: fibre_daily: 1 of 7 day(s) under the 35 g fibre floor (2026-06-20 31.0 g)"],
        "quality": {"met": False, "misses": ["fibre_daily: 1 of 7 day(s) under the 35 g fibre floor (2026-06-20 31.0 g)"], "problems": []},
    }  # fmt: skip


def _ahead():
    sunday = _menu_day("2026-06-14", "Sunday")
    coming = [_menu_day(*c) for c in COMING]
    return {
        "version": weekly_menu_feed.VERSION, "today": "2026-06-13", "calendar_basis": weekly_menu_feed.CALENDAR_BASIS,
        "weeks": [{"week_start": "2026-06-08", "menu": _menu("2026-06-08", [sunday], []), "days": [sunday], "shop": False},
                  {"week_start": "2026-06-15", "menu": _menu("2026-06-15", coming, GROCERY), "days": coming, "shop": True}],
    }  # fmt: skip


# ── the panel: three voices + the unified section (the shape the prompt orders) ──────────────────────────────────

VOICE_MARK = "VOICE-OF-AN-EXPERT-CARD"
PRIORITY_TEXT = [
    "Front-load the first feeding: the flank steak bowl is already the best-built meal of the week.",
    "Add the edamame to the two cook days so fibre clears the floor without new foods.",
    "Keep the prepared dinner as logged; it is carrying the evenings.",
]


def _panel():
    card = lambda who: f'<div style="border-left:3px solid #10b981;"><h3>{who}</h3><p>{VOICE_MARK} {"word " * 300}</p></div>'  # noqa: E731
    items = "".join(f"<li>{t}</li>" for t in PRIORITY_TEXT)
    return (
        card("Marcus Webb - Macros")
        + card("Amara Patel - Micronutrients")
        + card("James Okafor - Metabolic Health")
        + f'<div style="border-left:3px solid #4cc9f0;"><h3>Top 3 Nutrition Priorities This Week</h3><ol>{items}</ol>'
        + f"<h3>Metropolitan Market Grocery List</h3><p>{'grocery ' * 200}</p><h3>Meal Ideas (3-4)</h3><p>{'meal ' * 150}</p>"
        + f"<h3>Supplement Check</h3><p>{'supplement ' * 100}</p></div>"
    )


# ── the harness ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(m, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, m, _FrozenDatetime)
    table, ses = FakeTable(), FakeSES()
    table.items[(titration.TITRATION_PK, f"{titration.TITRATION_SK_PREFIX}2026-06-15")] = {
        "kcal": Decimal("1600"), "action": "hold", "step_kcal": Decimal("0"), "reason": "the trend is inside the band",
    }  # fmt: skip
    calls = []
    monkeypatch.setattr(m, "table", table)
    monkeypatch.setattr(m, "ses", ses)
    monkeypatch.setattr(m, "insight_writer", FakeInsightWriter())
    monkeypatch.setattr(m, "_HAS_INSIGHT_WRITER", True)
    monkeypatch.setattr(m, "_build_nutrition_prompt_from_config", lambda cal, pro: None)
    monkeypatch.setattr(m, "gather_nutrition_data", _gathered)
    monkeypatch.setattr(m.weekly_menu_feed, "menus_ahead", lambda **_kw: _ahead())
    monkeypatch.setattr(m.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(m.send_ledger, "record_sent", lambda *a, **k: None)

    def _call(system, user):
        calls.append(user)
        return _panel()

    monkeypatch.setattr(m, "call_anthropic", _call)
    return {"table": table, "ses": ses, "calls": calls, "mp": monkeypatch}


def _send(env, switch=None):
    """Run the handler once with the format switch at `switch` (None = no item); return (subject, html)."""
    env["ses"].sent.clear()
    env["table"].items.pop((SWITCH_PK, nrc.SWITCH_SK), None)
    if switch is not None:
        env["table"].items[(SWITCH_PK, nrc.SWITCH_SK)] = {"value": switch}
    m.lambda_handler({}, None)
    msg = env["ses"].sent[-1]["Content"]["Simple"]
    return msg["Subject"]["Data"], msg["Body"]["Html"]["Data"]


def _text(html):
    return re.sub(r"\s+", " ", nrc.visible_text(html)).strip()


# ── THE acceptance check ─────────────────────────────────────────────────────────────────────────────────────────


def compact_offenders(subject: str, html: str) -> list:
    """Every way the rendered email falls short of the ruling, by name. Empty = acceptable."""
    text = _text(html)
    out = []
    words = nrc.word_count(html)
    if words > nrc.WORD_BUDGET:
        out.append(f"budget: {words} words > {nrc.WORD_BUDGET}")
    # the menu and the shop, intact: every day, every anchor serving, the fixed meal, every grocery line
    fd = weekly_menu_feed.feed(_ahead())
    for d in ["2026-06-14"] + [c[0] for c in COMING]:
        if d[5:] not in text:
            out.append(f"menu: day {d} missing")
        for a, b in ANCHORS:
            if f"{a} {d[-2:]}" not in text:
                out.append(f"menu: {a} on {d} missing")
    if "2 x Tortilla" not in text or "Prepared dinner" not in text:
        out.append("menu: a serving count or the fixed meal is missing")
    for line in fd["grocery"]:
        if line not in text:
            out.append(f"shop: line missing: {line[:40]}")
    # one voice, capped
    if VOICE_MARK in text or re.search(r"\b(Webb|Patel|Okafor)\b", text):
        out.append("voice: an expert card is printed")
    if not all(t in text for t in PRIORITY_TEXT):
        out.append("voice: the panel's priorities are not printed")
    # no seven-day table
    if "<table" in html or re.search(r"\bAVG\b", text) or re.search(r"\b(Sat|Sun|Mon|Tue|Wed|Thu|Fri) \d\d/\d\d\b", text):
        out.append("table: the seven-day table is printed")
    # a partial day is excluded from the averages, and the count is said
    if f"{AVG_KCAL} kcal" not in text or "6 complete days" not in text or f"{AVG_KCAL} kcal" not in subject:
        out.append("partial: the averages are not over the six complete days, or the count is not stated")
    if "partly imported" not in text:
        out.append("partial: the partly imported day is not named")
    # nothing pending or planned is 'missed'
    if re.search(r"\bmissed\b", text, re.I) or re.search(r"\bmissed\b", subject, re.I):
        out.append("missed: a pending or future item is called missed")
    # no number stated twice with different values: one stated average, the same as the subject's
    kcal_avgs = set(re.findall(r"(\d+) kcal a day on average|(\d+) kcal and", text))
    stated = {a or b for a, b in kcal_avgs}
    subject_avg = re.search(r"- (\d+) kcal -", subject)
    if len(stated) != 1 or not subject_avg or stated != {subject_avg.group(1)}:
        out.append(
            f"numbers: the average is stated as {sorted(stated)} in the body and {subject_avg and subject_avg.group(1)} in the subject"
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the switch: explicit activation only
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_the_switch_selects_compact_only_on_the_exact_word():
    t = FakeTable()
    cases = {None: "long", "": "long", "long": "long", "compact": "compact", " COMPACT ": "compact", "compactx": "long",
             "hybrid": "long", "on": "long", "true": "long"}  # fmt: skip
    wrong = []
    for value, want in cases.items():
        t.items.pop((SWITCH_PK, nrc.SWITCH_SK), None)
        if value is not None:
            t.items[(SWITCH_PK, nrc.SWITCH_SK)] = {"value": value}
        got = nrc.read_format(t, f"USER#{m.USER_ID}#SOURCE#")
        if got != want:
            wrong.append((value, got, want))
    t.get_error = RuntimeError("AccessDenied")
    if nrc.read_format(t, f"USER#{m.USER_ID}#SOURCE#") != "long":
        wrong.append(("read failure", "compact", "long"))
    assert not wrong, wrong


def test_merging_changes_nothing_absent_invalid_or_unreadable_is_the_long_email_byte_for_byte(env):
    absent = _send(env)
    variants = {"long": _send(env, "long"), "garbage": _send(env, "compactx"), "empty": _send(env, "")}
    env["table"].get_error = RuntimeError("AccessDenied")
    variants["read failure"] = _send(env, "compact")
    env["table"].get_error = None
    differ = [k for k, v in variants.items() if v != absent]
    assert not differ, differ
    assert _send(env, "compact") != absent  # and the switch does select something else
    assert _send(env, "long") == absent  # rollback is the one item back to 'long'


def test_the_compact_email_makes_the_same_model_calls_as_the_long_one(env):
    _send(env, "long")
    long_calls = len(env["calls"])
    _send(env, "compact")
    assert len(env["calls"]) - long_calls == long_calls == 1


def test_a_compact_build_failure_sends_the_long_email_never_nothing(env):
    absent = _send(env)

    def boom(*_a, **_k):
        raise ValueError("render")

    env["mp"].setattr(m.nr_compact, "menu_section", boom)
    assert _send(env, "compact") == absent


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# rendered-output acceptance (the real builder)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_the_compact_email_passes_every_acceptance_check(env):
    subject, html = _send(env, "compact")
    assert compact_offenders(subject, html) == []
    size = nrc.measure(html, nrc.menu_section(_ahead(), weekly_menu_feed.feed(_ahead())))
    assert size["words"] <= nrc.WORD_BUDGET and size["prose_words"] <= nrc.PROSE_WORD_CAP, size
    assert size["read_minutes_est"] <= 3.1, size


def test_negative_control_the_long_email_fails_the_acceptance_check(env):
    """Today's shape must FAIL — on length, voices and the table at least. A check that passed it would prove nothing."""
    subject, html = _send(env, "long")
    found = compact_offenders(subject, html)
    for must in ("budget:", "voice: an expert card", "table:"):
        assert any(f.startswith(must) for f in found), (must, found)


def test_the_panel_prose_is_one_voice_and_capped():
    long_items = "".join(f"<li>{'word ' * 80}number {i}.</li>" for i in range(5))
    html = f"<h3>Marcus Webb</h3><p>card</p><h3>Top 3 Nutrition Priorities This Week</h3><ol>{long_items}</ol><h3>Meal Ideas</h3><p>x</p>"
    got = nrc.panel_priorities(html)
    assert sum(len(t.split()) for t in got) <= nrc.PANEL_WORD_CAP
    assert not any("card" in t or "Webb" in t for t in got)
    assert nrc.panel_priorities("<h3>Marcus Webb</h3><p>no unified section</p>") == []


def test_the_menu_keeps_every_day_feeding_serving_and_grocery_line():
    ahead = _ahead()
    fd = weekly_menu_feed.feed(ahead)
    text = _text(nrc.menu_section(ahead, fd))
    missing = [g for g in fd["grocery"] if g not in text]
    for d in ahead["weeks"][0]["days"] + ahead["weeks"][1]["days"]:
        for f in d["feedings"]:
            for i in f["items"]:
                label = i["label"] if i["servings"] == 1 else f"{i['servings']:g} x {i['label']}"
                if label not in text:
                    missing.append(f"{d['date']}: {label}")
        if f"{d['totals']['kcal']:g} kcal" not in text:
            missing.append(f"{d['date']}: kcal")
    assert "Every day's dinner: Prepared dinner — fixed, planned at 587 kcal, 64 g protein" in text
    assert "does not fit: fibre_g 31 under 35" in text
    assert not missing, missing


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the bug fixes — both formats
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_the_long_subject_and_table_average_complete_days_only_and_say_how_many(env):
    subject, html = _send(env, "long")
    assert subject == f"Nutrition Review - {W1_END} - {AVG_KCAL} kcal - {AVG_PRO}g protein (6 complete days)"
    text = _text(html)
    assert f"AVG {AVG_KCAL} {AVG_PRO}g" in text
    assert "Fri 06/12 (partly imported)" in text and "AVG = 6 complete days; 1 incomplete day shown, not averaged" in text
    # the partial day is shown in grey, never graded green as a deficit day
    row = re.search(r"Fri 06/12 \(partly imported\)</td>(.*?)</tr>", html, re.S).group(1)
    assert "#10b981" not in row and "#6b7280" in row


def test_a_week_of_complete_days_keeps_the_old_subject_and_table_exactly(env):
    """No partial day, all seven days: nothing about the averages changes (the fix only bites on an incomplete week)."""
    rows = {d: _row(d, 1400, 150) for d in [W1_START, "2026-06-07", "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", W1_END]}
    data = dict(_gathered(), macrofactor_this=rows, food_freshness={"last_arrival_day": "2026-06-13"})
    env["mp"].setattr(m, "gather_nutrition_data", lambda: data)
    subject, html = _send(env)
    assert subject == f"Nutrition Review - {W1_END} - 1400 kcal - 150g protein"
    assert "complete day" not in html and "partly imported" not in html


def test_a_day_whose_export_has_not_arrived_is_pending_never_averaged_or_missed(env):
    """A row for Friday exists but no export has landed since Friday ended, and Thursday has no row at all."""
    rows = _week_rows()
    rows[PARTIAL_DAY] = _row(PARTIAL_DAY, 300, 40)  # no partial flag: the arrival alone makes it partial
    del rows["2026-06-11"]
    data = dict(_gathered(), macrofactor_this=rows, food_freshness={"last_arrival_day": "2026-06-11"})
    env["mp"].setattr(m, "gather_nutrition_data", lambda: data)
    subject, html = _send(env, "compact")
    text = _text(html)
    assert "(5 complete days)" in subject
    assert "Not counted: Fri Jun 12 partly imported." in text and "Not arrived yet: Thu Jun 11." in text
    assert not re.search(r"\bmissed\b|not logged|no food log", text, re.I), text


def test_no_complete_day_states_no_average(env):
    rows = {PARTIAL_DAY: _row(PARTIAL_DAY, 95, 15, partial_at_export=True)}
    data = dict(_gathered(), macrofactor_this=rows)
    env["mp"].setattr(m, "gather_nutrition_data", lambda: data)
    subject, html = _send(env, "compact")
    assert subject == f"Nutrition Review - {W1_END} - no complete day of food data yet"
    assert "no average is stated" in _text(html) and "95 kcal" not in _text(html)


def test_a_future_menu_is_never_labelled_missed_in_either_format(env):
    for switch in ("long", "compact"):
        subject, html = _send(env, switch)
        assert "MISSED" not in html, switch
    assert weekly_menu_feed.plan_quality_line("Food quality: MISSED: fibre_daily: x") == (
        "Food quality: the planned menu falls short: fibre_daily: x"
    )
    assert weekly_menu_feed.plan_quality_line("Food quality: every target met") == "Food quality: every target met"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# mutation proofs: undo each fix in-process; the acceptance check names the defect that comes back
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_mutation_proofs_the_acceptance_check_catches_each_regression(env):
    survived = []

    def expect(name, prefix):
        subject, html = _send(env, "compact")
        if not any(f.startswith(prefix) for f in compact_offenders(subject, html)):
            survived.append(name)

    with pytest.MonkeyPatch.context() as mm:  # M1: the partial day averaged back in (the defect)
        mm.setattr(m, "day_completeness", lambda *a, **k: m.DAY_COMPLETE)
        expect("M1 partial day averaged", "partial:")
    with pytest.MonkeyPatch.context() as mm:  # M2: every panel block printed (all voices, no cap)
        mm.setattr(m.nr_compact, "panel_priorities", lambda html, cap=0: [b[0] for b in _blocks(html)])
        expect("M2 all voices", "voice: an expert card")
    with pytest.MonkeyPatch.context() as mm:  # M3: the shop dropped from the compact menu
        orig = m.nr_compact.menu_section
        mm.setattr(m.nr_compact, "menu_section", lambda ahead, fd: orig(ahead, dict(fd, grocery=[])))
        expect("M3 shop dropped", "shop:")
    with pytest.MonkeyPatch.context() as mm:  # M4: the plan's shortfall worded as MISSED again
        mm.setattr(weekly_menu_feed, "plan_quality_line", lambda ln: ln)
        expect("M4 future MISSED", "missed:")
    with pytest.MonkeyPatch.context() as mm:  # M5: the seven-day table appended to the compact email
        orig_build = m.nr_compact.build
        mm.setattr(m.nr_compact, "build", lambda **k: orig_build(**k) + m.build_summary_table(m.extract_daily_nutrition(_week_rows()), {}))
        expect("M5 table back", "table:")
    with pytest.MonkeyPatch.context() as mm:  # M6: the panel's prose uncapped (length)
        mm.setattr(m.nr_compact, "PANEL_WORD_CAP", 10_000)
        mm.setattr(m.nr_compact, "panel_priorities", lambda html, cap=0: [_text(html)])
        expect("M6 uncapped panel prose", "budget:")
    with pytest.MonkeyPatch.context() as mm:  # M7: the body's average computed over every row while the subject is not
        orig_line = m.nr_compact.week_line
        mm.setattr(m.nr_compact, "week_line", lambda *a, **k: orig_line(*a, **k) + f" {OLD_AVG_KCAL} kcal a day on average.")
        expect("M7 two different averages", "numbers:")
    assert not survived, survived


def _blocks(html):
    p = nrc._Blocks()
    p.feed(html)
    p.close()
    return p.blocks
