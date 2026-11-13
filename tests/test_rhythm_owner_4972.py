"""tests/test_rhythm_owner_4972.py — the owner-only heart-rhythm READ (#4972 part 2, folded from #4977).

What this holds:
  * the read-back (`rhythm_channel.read_events`) hands out NEUTRAL events — never the medication name or dose
    text, a device name or a reading — and a failed read is None (render nothing), never "zero events";
  * the summary counts each family/kind in the current window against the window before it, and every rendered
    count carries its n and window (ADR-104/105); no events in either window is an ABSENCE line, not a zero claim;
  * THE PROMPT TEST (box 3): the coach block always carries the no-advice instruction, the one advice string is
    "discuss with your clinician", and no rendered line interprets, diagnoses, reassures or comments on a dose;
  * the burden-rise reader (`burden_change`) states n, both windows, coverage and the confounders, and decides
    nothing;
  * PRIVACY (box 4): the renderer's importer set is the channel privacy gate's leg 4
    (`tests/test_rhythm_channel_privacy_4972.py`); here, inside the daily brief the lines go to
    the email renderer alone (never `data`, an AI prompt, a generated file, a log line or a demo brief), the
    email's HTML goes to SES alone, addressed to the one recipient; and the clinical block every published prompt
    reads carries none of the channel.

Every date is fixed and passed in; nothing here reads the clock (#4848). Values are synthetic placeholders.
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from emails import brief_lines  # noqa: E402
from health import (
    clinical_facts,  # noqa: E402
    rhythm_channel as rc,  # noqa: E402
    rhythm_owner as ro,  # noqa: E402
)

TODAY = "2026-11-20"
PK = "USER#matthew#SOURCE#clinical"
MED_SENTINEL = "MEDNAMESENTINEL"
DOSE_SENTINEL = "DOSESENTINEL"
DEVICE_SENTINEL = "DEVICESENTINEL"
RESULT_SENTINEL = "RESULTSENTINEL"


class FakeTable:
    def __init__(self, items=(), page=0, fail=False):
        self.items = sorted((dict(i) for i in items), key=lambda i: (i["pk"], i["sk"]))
        self.page = page
        self.fail = fail
        self.queries = 0

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExclusiveStartKey=None, **_kw):
        self.queries += 1
        if self.fail:
            raise RuntimeError("boom " + MED_SENTINEL)
        pk, prefix = ExpressionAttributeValues[":pk"], ExpressionAttributeValues.get(":p", "")
        rows = [i for i in self.items if i["pk"] == pk and i["sk"].startswith(prefix)]
        start = ExclusiveStartKey["n"] if ExclusiveStartKey else 0
        if self.page and start + self.page < len(rows):
            return {"Items": rows[start : start + self.page], "LastEvaluatedKey": {"n": start + self.page}}
        return {"Items": rows[start:]}


def _ecg_row(at, result=RESULT_SENTINEL):
    return {
        "pk": PK,
        "sk": f"{rc.ECG_PREFIX}{at}#{DEVICE_SENTINEL.lower()}",
        "event_date": at[:10],
        "rhythm_ecg_classification": result,
        "rhythm_ecg_device": DEVICE_SENTINEL,
        "rhythm_ecg_avg_hr_bpm": 71,
    }


def _notif_row(at, kind="irregular", inferred=False):
    return {
        "pk": PK,
        "sk": f"{rc.NOTIF_PREFIX}{at}#{kind}",
        "event_date": at[:10],
        "rhythm_notification_kind": kind,
        "rhythm_notification_kind_inferred": inferred,
        "rhythm_notification_bpm": 131,
        "rhythm_notification_device": DEVICE_SENTINEL,
    }


def _med_row(at, status="taken"):
    return {
        "pk": PK,
        "sk": f"{rc.MEDLOG_PREFIX}{at}#abc123def0",
        "event_date": at[:10],
        "rhythm_med_name": MED_SENTINEL,
        "rhythm_med_dose_text": DOSE_SENTINEL,
        "rhythm_med_status": status,
    }


def _rows():
    """Current window (11-14..11-20): 3 irregular, 1 high (inferred), 2 ECGs, 2 med entries.
    Prior window (11-07..11-13): 1 irregular, 1 ECG, 3 med entries. Outside both: 1 irregular (11-01)."""
    return [
        _notif_row("2026-11-20T07:00:00"),
        _notif_row("2026-11-18T23:10:00"),
        _notif_row("2026-11-14T00:05:00"),
        _notif_row("2026-11-16T12:00:00", kind="high", inferred=True),
        _ecg_row("2026-11-19T08:12:03", "result_a"),
        _ecg_row("2026-11-15T09:00:00", "result_b"),
        _med_row("2026-11-19T08:00:00"),
        _med_row("2026-11-20T08:00:00", status="skipped"),
        _notif_row("2026-11-10T03:00:00"),
        _ecg_row("2026-11-07T10:00:00", "result_a"),
        _med_row("2026-11-08T08:00:00"),
        _med_row("2026-11-09T08:00:00"),
        _med_row("2026-11-13T08:00:00"),
        _notif_row("2026-11-01T03:00:00"),
        # A row in another family of the partition is never read here.
        {"pk": PK, "sk": "MED#placeholder", "name": MED_SENTINEL},
    ]


def _summary():
    return ro.summarize(rc.read_events(FakeTable(_rows())), TODAY)


# ── the read-back is neutral ──────────────────────────────────────────────────


def test_read_events_hands_out_neutral_events_only():
    events = rc.read_events(FakeTable(_rows(), page=4))  # paginated
    assert len(events) == 14
    blob = repr(events)
    for sentinel in (MED_SENTINEL, DOSE_SENTINEL, DEVICE_SENTINEL, "131", "71"):
        assert sentinel not in blob, sentinel
    assert {e["family"] for e in events} == {"ecg", "notification", "medication"}
    for e in events:
        assert set(e) <= {"family", "day", "at", "result", "kind", "kind_inferred", "status"}


def test_a_failed_read_is_none_never_zero_and_logs_no_value(caplog):
    with caplog.at_level(logging.DEBUG):
        assert rc.read_events(FakeTable(fail=True)) is None
        assert ro.read_summary(FakeTable(fail=True), TODAY) is None
        assert ro.read_summary(None, TODAY) is None
        assert ro.owner_lines(None) == [] and ro.coach_block(None) == ""
    assert MED_SENTINEL not in caplog.text
    assert "RuntimeError" in caplog.text


def test_an_unreadable_row_is_dropped_not_guessed():
    bad = {"pk": PK, "sk": rc.NOTIF_PREFIX + "not-a-time#irregular", "event_date": "garbage"}
    odd_kind = _notif_row("2026-11-19T01:00:00", kind="sideways")
    events = rc.read_events(FakeTable([bad, odd_kind]))
    assert events == [
        {"family": "notification", "day": "2026-11-19", "at": "2026-11-19T01:00:00", "kind": "unknown", "kind_inferred": False}
    ]


# ── the summary and the owner lines ──────────────────────────────────────────


def test_the_summary_counts_each_window_by_family_and_kind():
    s = _summary()
    cur, pri = s["current"], s["prior"]
    assert (cur["start"], cur["end"], pri["start"], pri["end"]) == ("2026-11-14", "2026-11-20", "2026-11-07", "2026-11-13")
    assert cur["notifications"] == {"irregular": 3, "high": 1} and cur["inferred"] == 1
    assert pri["notifications"] == {"irregular": 1}
    assert (cur["ecg"], pri["ecg"]) == (2, 1)
    assert cur["ecg_results"] == {"result_a": 1, "result_b": 1}
    assert (cur["medication_log"], pri["medication_log"]) == (2, 3)
    assert cur["medication_status"] == {"taken": 1, "skipped": 1}
    # Episodes: ECGs + notifications of the current window, newest first.
    assert [e["at"] for e in s["episodes"]][:2] == ["2026-11-20T07:00:00", "2026-11-19T08:12:03"]
    assert len(s["episodes"]) == 6


def test_owner_lines_report_counts_with_n_and_window():
    lines = ro.owner_lines(_summary())
    text = "\n".join(lines)
    assert "Irregular-rhythm notifications: 3 in the 7 days to 2026-11-20, up from 1 in the 7 days before." in lines
    assert "High heart-rate notifications: 1 in the 7 days to 2026-11-20, up from 0 in the 7 days before." in lines
    assert "1 of this window's notification kinds were inferred from the reading, not named by the device." in lines
    assert (
        "ECG recordings: 2 in the 7 days to 2026-11-20, up from 1 in the 7 days before; device results: 'result_a' x1, 'result_b' x1."
        in lines
    )
    assert "Medication log: 2 entries in the 7 days to 2026-11-20, down from 3 in the 7 days before (skipped 1, taken 1)." in lines
    assert lines[-1] == ro.CLINICIAN_LINE
    assert "2026-11-01" not in text  # outside both windows
    for sentinel in (MED_SENTINEL, DOSE_SENTINEL, DEVICE_SENTINEL):
        assert sentinel not in text


def test_no_events_is_an_absence_line_with_its_window_and_no_advice():
    lines = ro.owner_lines(ro.summarize([], TODAY))
    assert lines == ["No heart-rhythm records stored in the 14 days to 2026-11-20 — an absence of records, not a measurement."]


def test_the_episode_list_is_capped_and_says_how_many_more():
    rows = [_notif_row(f"2026-11-{d:02d}T01:00:00") for d in range(14, 21)] + [_notif_row("2026-11-20T02:00:00", kind="low")]
    lines = ro.owner_lines(ro.summarize(rc.read_events(FakeTable(rows)), TODAY))
    ep = [ln for ln in lines if ln.startswith("Events ")][0]
    assert f"(+{8 - ro.MAX_EPISODES} more)" in ep and ep.count(";") == ro.MAX_EPISODES - 1


# ── THE PROMPT TEST (box 3): no clinical advice beyond "discuss with your clinician" ──

# Words that would turn a data line into interpretation, diagnosis, reassurance or dose advice.
_FORBIDDEN = (
    "diagnos",
    "normal",
    "abnormal",
    "benign",
    "reassur",
    "worry",
    "concern",
    "safe",
    "danger",
    "risk",
    "should",
    "recommend",
    "advise",
    "consider",
    "dose",
    "dosage",
    "increase your",
    "reduce your",
    "stop taking",
    "atrial",
    "fibrillation",
    "arrhythmia",
    "likely",
    "suggest",
    "indicat",
    "means",
    "emergency",
    "doctor",
)


def _all_rendered_lines():
    fixtures = [_rows(), [], [_med_row("2026-11-19T08:00:00")], [_notif_row("2026-11-12T01:00:00", kind="hypertension")]]
    fixtures.append([_notif_row("2026-11-19T01:00:00", kind=k, inferred=True) for k in rc.NOTIFICATION_KINDS + ("unknown",)])
    out = []
    for rows in fixtures:
        out.extend(ro.owner_lines(ro.summarize(rc.read_events(FakeTable(rows)), TODAY)))
    return out


def test_no_rendered_line_carries_advice_or_interpretation():
    lines = _all_rendered_lines()
    assert len(lines) >= 12
    for line in lines:
        low = line.lower()
        hits = [w for w in _FORBIDDEN if w in low]
        assert not hits, f"{hits} in {line!r}"
        if "clinician" in low:
            assert line == ro.CLINICIAN_LINE, line


def test_the_one_advice_string_is_discuss_with_your_clinician():
    assert ro.ADVICE == "discuss with your clinician"
    assert ro.CLINICIAN_LINE.lower().endswith(ro.ADVICE + ".")
    assert ro.COACH_INSTRUCTION.endswith("The only advice you may give about them is: discuss with your clinician.")
    for word in ("interpret", "diagnose", "reassure", "medication or dose"):
        assert word in ro.COACH_INSTRUCTION


def test_the_coach_block_always_carries_the_instruction_with_the_data():
    block = ro.coach_block(_summary())
    head, instruction, *body = block.split("\n")
    assert head == ro.HEADER and "never repeat them in anything that may be published" in head
    assert instruction == ro.COACH_INSTRUCTION
    assert body and all(b.startswith("- ") for b in body)
    assert body[-1] == "- " + ro.CLINICIAN_LINE
    # The absence form still carries the instruction; an unread channel is no block at all.
    assert ro.coach_block(ro.summarize([], TODAY)).split("\n")[1] == ro.COACH_INSTRUCTION
    assert ro.coach_block(None) == ""


# ── the burden-rise reader (box 2's input; the alert itself is a follow-up) ──


def test_burden_change_states_n_windows_coverage_and_confounders():
    events = rc.read_events(FakeTable(_rows()))
    worn = ["2026-11-14", "2026-11-15", "2026-11-20", "2026-11-08", "2026-10-01"]
    b = ro.burden_change(events, TODAY, worn_days=worn)
    assert b["family"] == "notification" and b["kind"] == "irregular" and b["window_days"] == 7
    assert b["current"] == {"start": "2026-11-14", "end": "2026-11-20", "n": 3, "medication_log": 2, "worn_days": 3}
    assert b["prior"] == {"start": "2026-11-07", "end": "2026-11-13", "n": 1, "medication_log": 3, "worn_days": 1}
    assert (b["n"], b["delta"], b["rose"], b["medication_log_changed"]) == (4, 2, True, True)
    assert b["confounders"] == list(ro.CONFOUNDERS) and len(b["confounders"]) >= 5
    assert any("wear" in c for c in b["confounders"]) and any("medication" in c for c in b["confounders"])
    # Every notification kind, ECGs, and no coverage key without a worn-day input.
    assert ro.burden_change(events, TODAY, kind=None)["current"]["n"] == 4
    ecg = ro.burden_change(events, TODAY, family="ecg")
    assert (ecg["current"]["n"], ecg["prior"]["n"]) == (2, 1) and "worn_days" not in ecg["current"]
    assert ro.burden_change(None, TODAY) is None


# ── PRIVACY (box 4): never reachable from a public route or a public AI context ──


def _handler(src: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _brief_src() -> str:
    return (ROOT / "lambdas" / "emails" / "daily_brief_lambda.py").read_text(encoding="utf-8")


def test_in_the_daily_brief_the_lines_reach_the_email_renderer_alone_and_never_a_demo_brief():
    fn = _handler(_brief_src())
    parents = _parents(fn)
    uses = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "_rhythm_lines"]
    stores = [n for n in uses if isinstance(n.ctx, ast.Store)]
    loads = [n for n in uses if isinstance(n.ctx, ast.Load)]
    assert len(stores) == 1 and len(loads) == 1, (len(stores), len(loads))
    assign = parents[stores[0]]
    value = assign.value
    # `None if demo_mode else brief_lines.rhythm_lines(...)` — a demo brief (made to be shown) never computes it.
    assert isinstance(value, ast.IfExp) and isinstance(value.test, ast.Name) and value.test.id == "demo_mode"
    assert isinstance(value.body, ast.Constant) and value.body.value is None
    assert ast.unparse(value.orelse.func) == "brief_lines.rhythm_lines"
    kw = parents[loads[0]]
    assert isinstance(kw, ast.keyword) and kw.arg == "rhythm_lines"
    assert ast.unparse(parents[kw].func) == "html_builder.build_html"
    # The section helper is called once, only here.
    calls = [n for n in ast.walk(ast.parse(_brief_src())) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("rhythm_lines")]
    assert len(calls) == 1


def test_the_email_html_goes_to_ses_alone_addressed_to_the_one_recipient():
    """The rendered HTML (which carries the section) is read only to sanitise, banner, measure and SEND — never
    by a writer, a generated file or a prompt; every send goes To the one recipient with no Cc/Bcc."""
    fn = _handler(_brief_src())
    parents = _parents(fn)
    allowed = {"output_writers.sanitize_for_demo", "_re.sub", "len", "ses.send_email"}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "html" and isinstance(node.ctx, ast.Load):
            up = parents[node]
            while not isinstance(up, ast.Call):
                up = parents[up]
            assert ast.unparse(up.func) in allowed, ast.unparse(up)[:160]
    sends = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "ses.send_email"]
    assert sends
    for call in sends:
        dest = next(k.value for k in call.keywords if k.arg == "Destination")
        assert ast.unparse(dest) == "{'ToAddresses': [RECIPIENT]}", ast.unparse(dest)


def test_the_brief_renders_the_section_inside_its_markers_and_a_demo_rule_can_hide_it():
    from content import html_builder as hb, output_writers

    kw = dict(
        data={"date": "2026-06-10", "hrv": {"hrv_7d": None, "hrv_30d": None}},
        profile={"calorie_target": 1500, "journey_start_date": "2024-01-01", "habit_registry": {}},
        day_grade_score=None,
        grade="C",
        component_scores={},
        component_details={},
        readiness_score=None,
        readiness_colour="gray",
        tldr_guidance=None,
        bod_insight=None,
        training_nutrition=None,
        journal_coach_text=None,
        mvp_streak=0,
        full_streak=0,
    )
    plain = hb.build_html(**kw)
    assert "Heart rhythm (owner-only)" not in plain and "S:rhythm" not in plain
    html = hb.build_html(rhythm_lines=["SECTIONSENTINEL <b>x</b>", ro.CLINICIAN_LINE], **kw)
    start, end = html.index("<!-- S:rhythm -->"), html.index("<!-- /S:rhythm -->")
    assert start < html.index("SECTIONSENTINEL &lt;b&gt;x&lt;/b&gt;") < end  # escaped, inside the markers
    hidden = output_writers.sanitize_for_demo(html, kw["data"], {"demo_mode_rules": {"hide_sections": ["rhythm"]}})
    assert "SECTIONSENTINEL" not in hidden


def test_brief_lines_never_raise_and_never_log_a_value(caplog):
    log = logging.getLogger("t4972")
    with caplog.at_level(logging.DEBUG):
        lines = brief_lines.rhythm_lines(FakeTable(_rows()), TODAY, log)
        assert lines and lines[-1] == ro.CLINICIAN_LINE
        assert brief_lines.rhythm_lines(FakeTable(fail=True), TODAY, log) is None

        class Exploding:
            def query(self, **_kw):
                raise ValueError(MED_SENTINEL)

        assert brief_lines.rhythm_lines(Exploding(), TODAY, log) is None
    for sentinel in (MED_SENTINEL, DOSE_SENTINEL, DEVICE_SENTINEL, "result_a"):
        assert sentinel not in caplog.text


def test_the_clinical_block_every_ai_prompt_reads_carries_none_of_the_channel():
    """The published prompts (coach_input_facts, the analyzer, the brief's coaches) and the owner thread both read
    `clinical_facts`; neither form renders a RHYTHM row, so no prompt gets the channel through that door."""
    rows = _rows() + [{"pk": PK, "sk": "GUIDANCE#current", "rules": ["rule one"], "public_rules": ["public rule one"]}]
    leaks = {}
    for published in (True, False):
        block = clinical_facts.render_clinical_block(rows, published=published)
        assert block, published  # non-vacuous: the guidance rendered
        hits = [s for s in (MED_SENTINEL, DOSE_SENTINEL, DEVICE_SENTINEL, "result_a", "result_b") if s in block]
        hits += [w for w in ("rhythm", "irregular") if w in block.lower()]
        if hits:
            leaks[published] = hits
    assert leaks == {}, leaks
