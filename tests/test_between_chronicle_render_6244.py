"""#6244 — the subscriber between-chapters note: held until the owner releases it, and a render a reader can read.

Owner ruling 2026-11-23: hold the note until its rendering is repaired; no raw grader JSON, unexplained precision,
stale coach commentary or unsupported conclusions to subscribers; resume only on his go after a representative render.

What these pin, on the REAL builder (``build_email``) from wire-shaped fixtures (Decimal-typed, the grader's JSON
notes, undated and October-dated calls, a correlation with no metric named — every shape the inventory found):

  * the acceptance check (``_acceptance_problems``) passes on the repaired render: no ``{``/``[`` structure, no
    ``None``/``nan``, no figure past one decimal place (a correlation's r is read to two), every correlation names
    both measures, every dated item carries its day and none is older than the window, the footer and the
    unsubscribe link are present;
  * NEGATIVE CONTROL: the same check FAILS on the current broken shape (the pre-#6244 template, rebuilt here from
    its own format strings with the inventory's synthetic values) — so the check can see what it is meant to see;
  * the hold: ``OWNER_RELEASE`` ships as ``None``; a held run never reads the subscriber list and never reaches SES;
    a malformed release holds; only a complete owner record releases;
  * the final guard: a render that still carries a machine fragment raises ``RenderRefused`` and nothing is sent.

Fixtures are synthetic. The clock is pinned (``_today``), never read (#4848).
"""

import io
import json
import logging
import os
import re
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import between_chronicle_lambda as bc  # noqa: E402

TODAY = "2026-11-29"
WINDOW_DAYS = bc.RECENCY_DAYS
_RELEASE = {"by": "owner", "released_on": "2026-11-28", "reviewed_render": "fixture render"}

#: The grader's notes exactly as the wire stores them (a JSON string; synthetic values in the inventory's shape).
_GRADER_JSON = json.dumps(
    {
        "actual_value": 37.0,
        "reason": "recovery_score=37.00 on 2026-11-24 vs predicted 65 ±12.4894 (±1 SD of the trailing 30-day "
        "personal series (n=31 readings, SD=12.4894)); |Δ|=28.00",
        "beats_null": None,
    }
)


def _wire_digest() -> dict:
    """Every broken shape at once, typed as the wire types it (DynamoDB numbers are Decimal)."""
    return {
        "deltas": [
            {
                "label": "Recovery",
                "this_month_avg": Decimal("67.93"),
                "prior_month_avg": Decimal("77.3"),
                "delta": Decimal("-9.37"),
                "unit": "%",
            },
            {
                "label": "Steps",
                "this_month_avg": Decimal("10066.37"),
                "prior_month_avg": Decimal("8937.93"),
                "delta": Decimal("1128.44"),
                "unit": "/day",
            },
            {
                "label": "Sleep",
                "this_month_avg": Decimal("7.74"),
                "prior_month_avg": Decimal("8.28"),
                "delta": Decimal("-0.54"),
                "unit": "h",
            },
            {"label": "Odd", "this_month_avg": Decimal("NaN"), "prior_month_avg": Decimal("3"), "delta": Decimal("1"), "unit": "%"},
            {
                "label": "Day grade",
                "this_month_avg": Decimal("71.004"),
                "prior_month_avg": Decimal("70.1"),
                "delta": Decimal("0.9"),
                "unit": "zz",
            },
        ],
        "window_start": "2026-10-29",
        "window_end": "2026-11-27",
        "unlocked": [
            # named, in the window: shown
            {
                "metric_a": "sleep_duration",
                "metric_b": "recovery_score",
                "r": Decimal("0.3632"),
                "n": Decimal("90"),
                "first_seen": "2026-11-22",
                "interpretation": "weak",
            },
            # no metric named (the inventory's "weak (r=0.36)"): dropped
            {"interpretation": "weak", "r": Decimal("0.29"), "first_seen": "2026-11-22", "n": Decimal("79")},
            # a measure with no reader words: dropped
            {"metric_a": "tier0_streak", "metric_b": "recovery_score", "r": Decimal("0.4"), "n": Decimal("50"), "first_seen": "2026-11-22"},
            # named but first held before the window: dropped
            {"metric_a": "protein_g", "metric_b": "recovery_score", "r": Decimal("0.35"), "n": Decimal("89"), "first_seen": "2026-10-25"},
        ],
        "decided": [
            # in the window, the grader's raw JSON as its reason: the claim shows, the working never does
            {
                "coach": "sleep",
                "claim": "Recovery score will be 65% tomorrow",
                "status": "refuted",
                "reason": _GRADER_JSON,
                "decided_at": "2026-11-25",
            },
            # in the window with reader words
            {
                "coach": "training",
                "claim": "Recovery holds above 60",
                "status": "confirmed",
                "reason": "Morning recovery score came in at 64 against a call of 60 — within its usual day-to-day range",
                "decided_at": "2026-11-26",
            },
            # graded in October (the inventory: "nearly all from October"): dropped
            {"coach": "sleep", "claim": "Recovery tomorrow will be 90.6%", "status": "confirmed", "reason": "", "decided_at": "2026-10-04"},
            # undated (the old read's blind spot): dropped
            {"coach": "sleep", "claim": "Recovery will be around 75.8% tomorrow", "status": "refuted", "reason": "", "decided_at": ""},
            # a claim with a four-decimal figure: dropped whole, never re-worded
            {"coach": "labs", "claim": "HRV will hold at 57.1734 ms", "status": "confirmed", "reason": "", "decided_at": "2026-11-27"},
        ],
        "stance_shifts": [
            {"coach": "sleep", "shift": "The short nights matter more than I first read.", "stage": "Foundation", "as_of": "2026-11-27"},
            {"coach": "mind", "shift": "An October read nobody revisited.", "stage": "", "as_of": "2026-10-11"},  # stale: dropped
            {"coach": "labs", "shift": "No date on this one.", "stage": "", "as_of": ""},  # undated: dropped
        ],
        "elena_note": "None",  # a serialized null where a sentence should be: dropped
        "elena_as_of": "2026-11-27",
    }


_DAY_WORDS = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}\b")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1
    )
}


def _paragraphs(html: str) -> list:
    return [bc.visible_text(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", html, flags=re.S)]


def _acceptance_problems(subject: str, html: str, today: str = TODAY) -> list:
    """Every way a rendered note fails the owner's bar ([] = acceptable)."""
    from datetime import date

    text = bc.visible_text(html)
    problems = [f"machine fragment {p}" for p in bc.machine_fragments(text) + bc.machine_fragments(subject)]
    if re.search(r"\bnan\b|\bNone\b|\bnull\b", text, flags=re.I):
        problems.append("a null word reached the reader")
    for m in re.finditer(r"(?<![\d.])(?<!r = )\d+\.(\d+)", text):
        if len(m.group(1)) > 1:
            problems.append(f"figure past one decimal place: {m.group(0)}")
    t = date.fromisoformat(today)
    for para in _paragraphs(html):
        if re.search(r"\br\s*=", para):
            named = sum(1 for w in bc.CORRELATION_WORDS.values() if w.lower() in para.lower())
            if named < 2:
                problems.append(f"a correlation without both measures named: {para[:80]!r}")
        dated_kinds = ("graded", "called it", "missed", "got it wrong", "first significant", " coach on ", "elena, where")
        if any(k in para.lower() for k in dated_kinds) and not _DAY_WORDS.search(para):
            problems.append(f"an item with no date: {para[:80]!r}")
        for dm in _DAY_WORDS.finditer(para):
            month, day = dm.group(0).split()
            d = date(t.year if _MONTHS[month] <= t.month else t.year - 1, _MONTHS[month], int(day))
            # a correlation's "week ending" and the averages' span are windows, checked against the same bound
            if (t - d).days > WINDOW_DAYS + 31 or ((t - d).days > WINDOW_DAYS and "Daily averages" not in para):
                problems.append(f"an item older than the {WINDOW_DAYS}-day window: {para[:80]!r}")
    if "unsubscribe" not in text.lower() or not re.search(r'href="[^"]+"[^>]*>unsubscribe<', html):
        problems.append("no unsubscribe link")
    if "No open tracking on this email" not in text:
        problems.append("no footer")
    return problems


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    monkeypatch.setattr(bc, "_today", lambda: TODAY)


# ── the render ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_repaired_render_passes_acceptance_on_the_wire_shape():
    subject, html = bc.build_email(_wire_digest(), "reader@example.com", TODAY)
    assert _acceptance_problems(subject, html) == []
    text = bc.visible_text(html)
    # what survives, in reader words
    assert "Recovery: 68%, down from 77%" in text
    assert "Steps: 10,066 a day, up from 8,938 a day" in text
    assert "Sleep: 7.7 hours, down from 8.3 hours" in text
    assert "Daily averages for October 29 to November 27, against the 30 days before." in text
    assert "Sleep time and morning recovery score rose and fell together: a weak correlation (r = 0.36 across 90 days)" in text
    assert "first significant in the week ending November 22" in text
    assert "“Recovery score will be 65% tomorrow” (graded November 25)" in text
    assert "Recovery holds above 60" in text and "(graded November 26)" in text
    assert "The sleep coach (Foundation) on November 27: The short nights matter more than I first read." in text
    # what is dropped
    for gone in (
        "12.4894",
        "recovery_score",
        "actual_value",
        "90.6%",
        "75.8%",
        "57.1734",
        "October read",
        "No date on this one",
        "Odd",
        "Day grade",
        "tier",
    ):
        assert gone not in text, gone
    assert subject == "Between chronicles: 4 things the machine found"


def test_negative_control_the_current_broken_shape_fails_acceptance():
    """The pre-#6244 template, rebuilt from its own format strings with the inventory's synthetic values. If the
    acceptance check passed this, it would be blind to the defect it exists to catch."""
    d = _wire_digest()
    parts = ['<div><p style="x">since the last installment · what the machine found</p>', "<h2>The month moved</h2>"]
    for x in d["deltas"][:2]:
        parts.append(f'<p>▼ {x["label"]}: {x["this_month_avg"]} {x["unit"]} vs {x["prior_month_avg"]} prior 30d (declined)</p>')
    parts.append("<h2>Newly significant</h2>")
    parts.append(f'<p>weak (r={round(float(d["unlocked"][1]["r"]), 2)}) — correlative, not causal.</p>')
    parts.append("<h2>Calls that graded</h2>")
    for p in d["decided"][2:4]:
        parts.append(f'<p><strong>✗ got it wrong</strong> — the {p["coach"]} coach: “{p["claim"]}” <span>{_GRADER_JSON[:200]}</span></p>')
    parts.append('<p>No open tracking on this email. <a href="https://example.com/u">unsubscribe</a></p></div>')
    problems = _acceptance_problems("Between chronicles: 6 things the machine found", "".join(parts))
    joined = " | ".join(problems)
    assert "machine fragment structure" in joined
    assert "past one decimal place" in joined
    assert "without both measures named" in joined
    assert "with no date" in joined


def test_each_acceptance_rule_can_fail():
    """One planted defect per rule — each must be reported on its own (the check is not one blunt regex)."""
    base = bc.build_email(_wire_digest(), "reader@example.com", TODAY)[1]
    plants = {
        "structure": "<p>{'a': 1}</p>",
        "null": "<p>Level 3 · None</p>",
        "decimal": "<p>Recovery: 67.93%</p>",
        "unnamed correlation": "<p>weak (r = 0.36) — correlative.</p>",
        "undated": "<p><strong>Missed</strong> — the sleep coach said “x”.</p>",
        "stale": "<p><strong>Missed</strong> — the sleep coach said “x” (graded October 4).</p>",
    }
    for name, plant in plants.items():
        html = base.replace("<h2", plant + "<h2", 1)
        assert _acceptance_problems("s", html), f"the acceptance check missed a planted {name}"
    no_unsub = re.sub(r'<a href="[^"]+"[^>]*>unsubscribe</a>', "", base)
    assert any("unsubscribe" in p for p in _acceptance_problems("s", no_unsub))


def test_decimal_wire_numbers_and_nan_never_render():
    d = {
        "deltas": [{"label": "HRV", "this_month_avg": Decimal("Infinity"), "prior_month_avg": Decimal("55.59"), "unit": "ms"}],
        "window_start": "2026-10-29",
        "window_end": "2026-11-27",
        "decided": [{"coach": "sleep", "claim": "c holds", "status": "confirmed", "decided_at": "2026-11-27"}],
    }
    subject, html = bc.build_email(d, "r@example.com", TODAY)
    assert "HRV" not in bc.visible_text(html) and _acceptance_problems(subject, html) == []


def test_stale_averages_are_dropped_not_shown_undated():
    d = _wire_digest()
    d["window_end"] = "2026-11-01"  # the what-changed snapshot stopped refreshing
    d["window_start"] = "2026-10-03"
    text = bc.visible_text(bc.build_email(d, "r@example.com", TODAY)[1])
    assert "Daily averages" not in text and "Recovery: 68%" not in text


def test_a_quiet_week_renders_nothing_worth_sending():
    """Everything in the broken shape that is stale, undated or unnamed — after curation nothing is news."""
    d = _wire_digest()
    d["unlocked"] = d["unlocked"][1:]
    d["decided"] = d["decided"][2:4]
    d["stance_shifts"] = d["stance_shifts"][1:]
    assert bc.has_real_content(bc.curate(d, TODAY)) is False


def test_curate_is_idempotent_and_the_hash_is_stable():
    once = bc.curate(_wire_digest(), TODAY)
    assert bc.curate(once, TODAY) is once
    assert bc.digest_hash(once) == bc.digest_hash(bc.curate(_wire_digest(), TODAY))


def test_gather_reads_outcome_date_and_reader_reason_from_wire_rows(monkeypatch):
    """End to end from wire rows: the grade day is ``outcome_date`` (the old read used ``evaluated_at``, which the
    grader does not write — so every call read as undated and none was ever too old), and the reason is the
    reader sentence ``web.prediction_reason`` writes, never the grader's JSON."""
    from web import call_publication

    rows = {
        "COACH#sleep_coach": [
            {
                "pk": "COACH#sleep_coach",
                "sk": "PREDICTION#a",
                "status": "refuted",
                "claim_natural": "Recovery score will be 65% tomorrow",
                "outcome_date": "2026-11-25",
                "evaluated_at": None,
                "outcome_notes": _GRADER_JSON,
                "evaluation": {"type": "point", "metric": "recovery_score", "threshold": Decimal("65"), "tolerance": Decimal("12.4894")},
            },
            {
                "pk": "COACH#sleep_coach",
                "sk": "PREDICTION#b",
                "status": "confirmed",
                "claim_natural": "Recovery tomorrow will be 90.6%",
                "outcome_date": "2026-10-04",
                "outcome_notes": "{}",
                "evaluation": {"type": "point", "metric": "recovery_score", "threshold": Decimal("90.6")},
            },
        ]
    }

    class _T:
        def get_item(self, Key):
            return {}

        def query(self, **kw):
            return {"Items": []}

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setattr(bc, "pacific_now", lambda: __import__("datetime").datetime(2026, 11, 29, 10, 0))
    monkeypatch.setattr(call_publication, "make_lookup", lambda table: None)
    monkeypatch.setattr(call_publication, "query", lambda table, kw, pk, lookup: {"Items": rows.get(pk, [])})
    monkeypatch.setattr(bc, "_gated", lambda item, pk: item)  # the gate's own decision is pinned below
    d = bc.gather_digest()
    assert [p["decided_at"] for p in d["decided"]] == ["2026-11-25"]
    assert d["decided"][0]["reason"] == "Morning recovery score came in at 37 against a call of 65 — outside its usual day-to-day range"
    subject, html = bc.build_email(d, "r@example.com", TODAY)
    assert _acceptance_problems(subject, html) == []
    assert "came in at 37 against a call of 65" in bc.visible_text(html)


def test_a_row_the_publication_gate_withholds_never_renders(monkeypatch):
    from web import call_publication, narrative_publication

    row = {
        "pk": "COACH#sleep_coach",
        "sk": "PREDICTION#a",
        "status": "confirmed",
        "claim_natural": "A withheld fixture claim",
        "outcome_date": "2026-11-25",
        "evaluation": {"type": "point", "metric": "recovery_score", "threshold": Decimal("65")},
    }

    class _T:
        def get_item(self, Key):
            return {}

        def query(self, **kw):
            return {"Items": []}

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setattr(bc, "pacific_now", lambda: __import__("datetime").datetime(2026, 11, 29, 10, 0))
    monkeypatch.setattr(call_publication, "make_lookup", lambda table: None)
    monkeypatch.setattr(call_publication, "query", lambda table, kw, pk, lookup: {"Items": [row] if pk == "COACH#sleep_coach" else []})
    # the real gate, deciding "withheld" (a row with no provenance record is unrecorded — fail closed)
    assert narrative_publication.is_withheld(narrative_publication.gate_item(dict(row), row["pk"], strict=True))
    assert bc.gather_digest()["decided"] == []


# ── the final guard ──────────────────────────────────────────────────────────────────────────────────────────────


def test_a_machine_fragment_past_curation_refuses_the_render_and_nothing_is_sent(monkeypatch):
    bad = bc.curate({"decided": [{"coach": "sleep", "claim": "fine", "status": "confirmed", "decided_at": "2026-11-27"}]}, TODAY)
    bad["decided"][0]["claim"] = '{"actual_value": 37.0}'  # what a curation regression would let through
    monkeypatch.setattr(bc, "gather_digest", lambda: {})
    monkeypatch.setattr(bc, "curate", lambda d, today=None: bad)
    monkeypatch.setattr(bc, "OWNER_RELEASE", dict(_RELEASE))
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    sent = []
    monkeypatch.setattr(bc.ses, "send_email", lambda **kw: sent.append(kw))
    monkeypatch.setattr(bc, "_get_confirmed_subscribers", lambda: [{"email": "r@example.com"}])

    class _T:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            raise AssertionError("no marker on a refused render")

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setattr(bc.send_ledger, "should_skip_replay", lambda *a, **k: False)
    with pytest.raises(bc.RenderRefused):
        bc.lambda_handler({}, None)
    assert sent == []


def test_machine_fragments_names_each_shape():
    for text in ('{"a": 1}', "[1, 2]", "None", "nan", "12.4894", "recovery_score", "x=3", "2026-11-10", "\\u00b1", "Decimal('1')", "|Δ|"):
        assert bc.machine_fragments(text), text
    for text in ("Recovery: 68%, down from 77%", "a weak correlation (r = 0.36 across 90 days)", "r = -0.41", "N=1", "[redacted]"):
        assert bc.machine_fragments(text) == [], text


# ── the hold ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_hold_ships_on():
    """Merging this file must not cause a send: the committed release is None."""
    src = open(os.path.join(_REPO, "lambdas", "emails", "between_chronicle_lambda.py")).read()
    assert re.search(r"^OWNER_RELEASE: Optional\[dict\] = None$", src, flags=re.M), "OWNER_RELEASE must ship as None (held)"
    assert bc.is_released() is False


def test_anything_but_a_complete_owner_record_holds():
    for release in (
        None,
        {},
        "yes",
        {"by": "driver", "released_on": "2026-11-28", "reviewed_render": "x"},
        {"by": "owner", "released_on": "soon", "reviewed_render": "x"},
        {"by": "owner", "released_on": "2026-02-30", "reviewed_render": "x"},
        {"by": "owner", "released_on": "2026-11-28", "reviewed_render": "  "},
    ):
        assert bc.release_problems(release), release


def test_a_complete_owner_record_releases():
    assert bc.release_problems(dict(_RELEASE)) == [] and bc.is_released(dict(_RELEASE)) is True


def test_a_held_run_reads_no_subscriber_and_sends_nothing(monkeypatch):
    d = {"decided": [{"coach": "sleep", "claim": "Recovery holds above 60", "status": "confirmed", "decided_at": "2026-11-27"}]}
    monkeypatch.setattr(bc, "gather_digest", lambda: d)
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    monkeypatch.setattr(
        bc, "_get_confirmed_subscribers", lambda: (_ for _ in ()).throw(AssertionError("a held run must not read the list"))
    )
    monkeypatch.setattr(bc.ses, "send_email", lambda **kw: (_ for _ in ()).throw(AssertionError("a held run must not send")))
    monkeypatch.setattr(bc.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(bc.send_ledger, "record_sent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ledger row while held")))

    class _T:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            raise AssertionError("no marker while held")

    monkeypatch.setattr(bc, "table", _T())
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    bc.logger.addHandler(h)
    try:
        out = bc.lambda_handler({}, None)
    finally:
        bc.logger.removeHandler(h)
    assert out["sent"] == 0 and out["skipped"] == "held"
    assert bc.HELD_TOKEN in buf.getvalue()


def test_a_released_run_sends_the_repaired_render(monkeypatch):
    monkeypatch.setattr(bc, "OWNER_RELEASE", dict(_RELEASE))
    monkeypatch.setattr(bc, "gather_digest", _wire_digest)
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "true")
    monkeypatch.setattr(bc, "_get_confirmed_subscribers", lambda: [{"email": "r@example.com"}])
    monkeypatch.setattr(bc.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(bc.send_ledger, "record_sent", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(bc.ses, "send_email", lambda **kw: sent.append(kw) or {"MessageId": "m"})

    class _T:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            return {}

    monkeypatch.setattr(bc, "table", _T())
    assert bc.lambda_handler({}, None)["sent"] == 1
    simple = sent[0]["Content"]["Simple"]
    assert _acceptance_problems(simple["Subject"]["Data"], simple["Body"]["Html"]["Data"]) == []
