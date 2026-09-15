"""tests/test_training_notes_degrade_reason_3699.py — #3699: every degrade path names itself.

THE SET (#3699's own `## Set` section — fail-soft paths in the training-note extractor that
degrade output without recording a cause, enumerated by
`grep -n "except\\|return \\[\\]" lambdas/training/training_notes.py lambdas/training/training_notes_llm.py`):

  1. `training_notes.py` `except Exception` around the llm call — set the flag, recorded no reason
  2. `training_notes_llm.py::_parse_signals` — no `[...]` span → `return []`, NO flag, no reason
  3. `training_notes_llm.py::_parse_signals` — `json.loads` failed → `return []`, NO flag, no reason

1 of 3 set the flag; 0 of 3 recorded why. Members 2 and 3 are the worse half: a truncated or
unparseable response was recorded as a SUCCESSFUL extraction that found nothing
(`used_llm=True`, `degraded=False`, `extracted_by="hybrid"`), which made `degraded` an
UNDERCOUNT and `extractor_dark` a floor rather than the number.

A fourth site was found while covering the three and is pinned here too: the array parsed but
every element was dropped as off-taxonomy — "0 of N kept" is a schema violation, and returning
[] there would rebuild the same undercount one layer down.

Every test below is a POSITIVE CONTROL that forces one real failure mode and asserts the
reason DISTINGUISHES it from the others, plus negative controls that a healthy extraction (and
a genuinely empty `[]`) still reads clean — a reason field that is always set says nothing.

No Bedrock call anywhere: `ai.bedrock_client.invoke` is monkeypatched (patched at its OWN
module, because `_haiku_call` imports it inside the function body) with real Messages response
shapes (including `stop_reason: "max_tokens"`, which is what a truncation actually looks like
on the wire).
"""

import logging
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

# mcp.config reads these at import time (same shape as tests/test_mcp_list_available_tools.py).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    training_notes as tn,  # noqa: E402
    training_notes_llm as tnl,  # noqa: E402
)
from training.training_notes import TAXONOMY  # noqa: E402

NOTE = "Level 9 for 20 and then level 6 for 10 - more of a flush - despite green recovery - i felt tired today"


def _code(rec):
    """The machine token a consumer keys on: the first `:`-separated field."""
    return (rec.get("degraded_reason") or "").split(":")[0].strip()


# ── The Set, member by member ────────────────────────────────────────────────


def test_set_member_1_an_exception_records_its_class_and_message():
    def boom(_n, _t):
        raise PermissionError("An error occurred (AccessDeniedException) when calling the InvokeModel operation")

    rec = tn.extract_signals(NOTE, llm_fn=boom)
    assert rec["degraded"] is True
    assert _code(rec) == "llm_error"
    assert "PermissionError" in rec["degraded_reason"]
    assert "AccessDeniedException" in rec["degraded_reason"]


def test_set_member_2_no_json_array_span_degrades_with_reason(monkeypatch):
    """Was: `return []` → degraded stayed False and the record read as hybrid/healthy."""
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke("I could not find anything structured here."))
    rec = tn.extract_signals(NOTE, llm_fn=lambda n, t: tnl._haiku_call(n, t))
    assert rec["degraded"] is True, "an unreadable response is still being recorded as a healthy extraction"
    assert _code(rec) == "unparseable"
    assert "no JSON array span" in rec["degraded_reason"]


def test_set_member_3_unparseable_json_degrades_with_reason(monkeypatch):
    # A real cut-off-mid-object array WITH a closing bracket: the span is found, the parse fails.
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke('[{"class": "limiter", "summary": "grip first",}]'))
    rec = tn.extract_signals(NOTE, llm_fn=lambda n, t: tnl._haiku_call(n, t))
    assert rec["degraded"] is True
    assert _code(rec) == "unparseable"
    assert "json.loads failed" in rec["degraded_reason"]


def test_fourth_site_every_element_off_taxonomy_degrades(monkeypatch):
    """Not in #3699's Set of three; the same shape one layer down."""
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke('[{"class":"vibes","summary":"x","confidence":0.9}]'))
    rec = tn.extract_signals(NOTE, llm_fn=lambda n, t: tnl._haiku_call(n, t))
    assert rec["degraded"] is True
    assert _code(rec) == "unparseable"
    assert "0 in taxonomy" in rec["degraded_reason"]


def test_the_three_reasons_are_distinguishable():
    """The acceptance's own words: 'assert the reason distinguishes them'."""
    seen = set()
    for exc in (
        tnl.TruncatedResponse("stop_reason=max_tokens at max_tokens=384"),
        tnl.UnparseableResponse("no JSON array span in a 12-char response"),
        tnl.CapExceeded("training-notes Haiku monthly cap 300 reached"),
        RuntimeError("bedrock threw"),
    ):
        seen.add(tn.degrade_reason(exc).split(":")[0].strip())
    assert seen == {"truncated", "unparseable", "cap_exceeded", "llm_error"}
    assert seen == set(tn.DEGRADE_CODES)


# ── The positive control the issue asks for by name: TRUNCATION ──────────────


def _fake_invoke(text, stop_reason="end_turn", output_tokens=120):
    def _invoke(body, model_name=None):
        return {
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": model_name or "haiku",
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 400, "output_tokens": output_tokens},
        }

    return _invoke


TRUNCATED_TEXT = '[{"class": "progression", "summary": "level 9 for 20 then level 6", "confidence": 0.9}, {"class": "sentim'


def test_truncation_sets_degraded_and_says_so(monkeypatch):
    """POSITIVE CONTROL for the issue's second, worse defect.

    A real max_tokens truncation: a partial array, no closing `]`, `stop_reason=max_tokens`.
    Before #3699 this produced `llm = []`, NO exception, `degraded: False`,
    `extracted_by: "hybrid"` — a record that looked healthy and carried only the
    deterministic signals.
    """
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke(TRUNCATED_TEXT, stop_reason="max_tokens", output_tokens=384))
    rec = tn.extract_signals(NOTE, llm_fn=lambda n, t: tnl._haiku_call(n, t))

    assert rec["degraded"] is True, "a truncated response is STILL being recorded as a successful extraction"
    assert _code(rec) == "truncated"
    assert "stop_reason=max_tokens" in rec["degraded_reason"]
    assert f"max_tokens={tnl.MAX_TOKENS}" in rec["degraded_reason"]
    assert "output_tokens=384" in rec["degraded_reason"]
    # Invariant 4 holds: the note and its deterministic signals survive.
    assert rec["note_raw"] == NOTE
    assert any(s["class"] == "progression" for s in rec["signals"])
    assert rec["extracted_by"] == "deterministic"


def test_truncation_is_read_from_stop_reason_not_inferred_from_the_text(monkeypatch):
    """The acceptance says 'check stop_reason where Bedrock supplies it rather than inferring
    from the text'. A cut-off array that happens to end on a `]` parses fine and would look
    complete to any text heuristic — stop_reason is the only witness."""
    text = '[{"class": "progression", "summary": "level 9", "confidence": 0.9}]'
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke(text, stop_reason="max_tokens"))
    with pytest.raises(tnl.TruncatedResponse):
        tnl._haiku_call(NOTE, TAXONOMY)
    # NEGATIVE CONTROL — same text, normal stop: parses, no degrade.
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke(text, stop_reason="end_turn"))
    assert [s["class"] for s in tnl._haiku_call(NOTE, TAXONOMY)] == ["progression"]


# ── Negative controls: the reason must be able to be absent ──────────────────


def test_a_healthy_extraction_carries_no_reason(monkeypatch):
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke('[{"class":"rpe_caveat","summary":"level 9 felt easy","confidence":0.8}]'))
    rec = tn.extract_signals(NOTE, llm_fn=lambda n, t: tnl._haiku_call(n, t))
    assert rec["degraded"] is False
    assert rec["degraded_reason"] is None
    assert rec["extracted_by"] == "hybrid"


def test_a_genuinely_empty_array_is_not_a_degrade(monkeypatch):
    """'The model read this note and found nothing semantic' is a legitimate answer. Only an
    UNREADABLE response degrades — otherwise the fix would trade an undercount for an
    overcount and `degraded` would still not be the number."""
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke("[]"))
    rec = tn.extract_signals("Level 9 flat", llm_fn=lambda n, t: tnl._haiku_call(n, t))
    assert rec["degraded"] is False and rec["degraded_reason"] is None
    assert rec["extracted_by"] == "hybrid"


def test_the_reason_never_carries_the_note_text(caplog):
    """Raw notes are owner-private (ADR-104 / Tier-2). The reason rides a WARNING log line."""
    secret = "left knee felt sharp on the last rep and i hid it from the coach"

    def leaky(note, _t):
        raise ValueError(f"model refused: {note}")

    with caplog.at_level(logging.WARNING, logger="training.training_notes"):
        rec = tn.extract_signals(secret, llm_fn=leaky)
    assert secret not in (rec["degraded_reason"] or ""), "the persisted reason leaked the note text"
    for r in caplog.records:
        assert secret not in r.getMessage(), "the degrade log leaked the note text"
    assert "<note redacted>" in rec["degraded_reason"]


def test_the_reason_is_logged_at_warning_never_info(caplog):
    with caplog.at_level(logging.INFO, logger="training.training_notes"):
        tn.extract_signals(NOTE, llm_fn=lambda n, t: (_ for _ in ()).throw(RuntimeError("boom")))
    degrade_records = [r for r in caplog.records if "llm degraded" in r.getMessage()]
    assert degrade_records, "the degrade was not logged at all"
    assert all(r.levelno >= logging.WARNING for r in degrade_records)


# ── MAX_TOKENS is derived from a measurement, not a round number ─────────────


def test_max_tokens_is_derived_from_a_recorded_measurement():
    """#3678/#3403 class: a budget set from a stale observation. 256 was a guess, and a breach
    of it was invisible. The derivation must travel WITH the number."""
    d = tnl.MAX_TOKENS_DERIVATION
    for key in ("metric", "window", "n", "p95", "max", "rule", "re_derive_when"):
        assert d.get(key), f"MAX_TOKENS_DERIVATION is missing {key!r} — the number is unsourced again"
    assert isinstance(d["n"], int) and d["n"] >= 10, "a p95 from fewer than 10 samples is not a p95"
    assert d["p95"] <= d["max"]
    assert tnl.MAX_TOKENS >= 2 * d["max"], "the cap no longer clears 2x the measured max — re-derive it"
    assert tnl.MAX_TOKENS != 256, "back to the un-derived default"


# ── The cap counter counts BILLED calls (the issue's own evidence channel) ───


class _FakeTable:
    def __init__(self):
        self.store = {}

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        it = self.store.setdefault((Key["pk"], Key["sk"]), {"pk": Key["pk"], "sk": Key["sk"]})
        it["calls"] = int(it.get("calls", 0)) + 1


def test_a_degraded_call_still_counts_against_the_month_and_is_never_cached(monkeypatch):
    """#3699 read the missing July/August rows of the USAGE counter as evidence the tail was
    down. That reading only holds if a failed-but-billed call counts: `_bump_calls` used to
    run only AFTER a clean return, so a truncated (billed in full) call recorded nothing.
    And the old silent [] was WRITTEN TO THE HASH CACHE — one bad response impoverished that
    note for as long as its text was unchanged."""
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke(TRUNCATED_TEXT, stop_reason="max_tokens"))
    t = _FakeTable()
    fn = tnl.make_llm_fn(t, monthly_cap=300)
    with pytest.raises(tnl.TruncatedResponse):
        fn(NOTE, TAXONOMY)
    assert tnl.monthly_calls(t) == 1, "a billed-but-degraded call is invisible to the usage counter"
    assert tnl.cache_get(t, tn.note_hash(NOTE)) is None, "the degrade was cached — it would replay forever"


def test_a_cap_breach_does_not_count_a_call_it_never_made(monkeypatch):
    """NEGATIVE CONTROL for the bump above: CapExceeded raises before any spend."""
    monkeypatch.setattr("ai.bedrock_client.invoke", _fake_invoke("[]"))
    t = _FakeTable()
    t.put_item({"pk": tnl._USAGE_PK, "sk": f"MONTH#{tnl._month()}", "calls": 300})
    fn = tnl.make_llm_fn(t, monthly_cap=300)
    with pytest.raises(tnl.CapExceeded):
        fn("a brand new note never seen", TAXONOMY)
    assert tnl.monthly_calls(t) == 300
    rec = tn.extract_signals("a brand new note never seen", llm_fn=fn)
    assert rec["degraded"] is True and _code(rec) == "cap_exceeded"


# ── The layer's health block, and every consumer that reads it ──────────────


class _HealthTable:
    """Raw hevy sweep, then the per-record probe — told apart by the projection."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, **kw):
        proj = kw.get("ProjectionExpression", "")
        if "exercises" in proj:
            return {"Items": [{"date": tn.pacific_today(), "exercises": [{"template_id": "ABC123", "name": "Cycling", "notes": "x"}]}]}
        assert "degraded_reason" in proj, "the health probe does not read the reason — it can only report THAT, never WHY"
        return {"Items": self._rows}


def test_health_tallies_the_reasons_and_says_them():
    h = tn.training_notes_health(
        _HealthTable([{"degraded": True, "degraded_reason": "truncated: TruncatedResponse: stop_reason=max_tokens"}])
    )
    assert h["degraded"] == 1
    assert h["degraded_reasons"] == {"truncated": 1}
    assert "truncated x1" in h["degraded_reasons_note"]
    assert "truncated x1" in h["note"]


def test_a_pre_3699_record_is_reported_as_unrecorded_never_as_unknown():
    """The two historical specimens (2026-06-22, 2026-06-25) carry `degraded: true` with NO
    reason field. They are NOT re-extracted — a re-derived signal in a measured partition is
    indistinguishable from an original one forever (attest, never backfill). They are LABELLED."""
    h = tn.training_notes_health(_HealthTable([{"degraded": True}]))
    assert h["degraded_reasons"] == {tn.DEGRADE_UNRECORDED: 1}
    assert "before #3699" in h["degraded_reasons_note"]


def test_the_layer_status_sentence_carries_the_reason():
    """ADR-104: a consumer told 'the layer is degraded' and not why goes back to hypotheses —
    which is exactly what #3699's reporter had to do."""
    from mcp.core import LAYER_DEGRADED, derived_layer_status

    status, reason = derived_layer_status(
        {
            "checked": True,
            "records_found": 3,
            "degraded": 2,
            "extractor_dark": False,
            "degraded_reasons_note": "truncated x1, unrecorded x1",
        }
    )
    assert status == LAYER_DEGRADED
    assert "truncated x1" in reason

    _, dark_reason = derived_layer_status(
        {
            "checked": True,
            "extractor_dark": True,
            "noted_exercise_sessions": 5,
            "lookback_days": 14,
            "degraded": 5,
            "missing_records": 0,
            "degraded_reasons_note": "llm_error x5",
        }
    )
    assert "llm_error x5" in dark_reason

    # NEGATIVE CONTROL — a healthy layer says nothing about reasons.
    ok_status, ok_reason = derived_layer_status({"checked": True, "records_found": 3, "degraded": 0, "extractor_dark": False})
    assert ok_reason == "" and ok_status != LAYER_DEGRADED


class _ToolTable:
    def __init__(self, rows):
        self._rows = rows

    def query(self, **kw):
        return {"Items": self._rows}


def _read_tool(monkeypatch, rows, health):
    import mcp.tools_training_notes as ttn

    monkeypatch.setattr(ttn, "table", _ToolTable(rows))
    monkeypatch.setattr("training.training_notes.training_notes_health", lambda *_a, **_k: health)
    return ttn.tool_get_exercise_notes({"template_id": "D8F7F851", "lookback_days": 180})


_HEALTH_DEGRADED = {
    "checked": True,
    "extractor_dark": False,
    "degraded": 2,
    "records_found": 5,
    "lookback_days": 14,
    "degraded_reasons_note": "truncated x1, unrecorded x1",
}


def test_the_read_tool_carries_the_reason_per_row(monkeypatch):
    """The coaching surface reads this tool. A row that says `degraded: true` and nothing
    else sends the reader to hypotheses (#3699's reporter had to do exactly that)."""
    rows = [
        {
            "sk": "DATE#2026-09-07#WORKOUT#a",
            "date": "2026-09-07",
            "note_raw": "Level 9 - 5.6 miles",
            "signals": [],
            "degraded": True,
            "degraded_reason": "truncated: TruncatedResponse: stop_reason=max_tokens at max_tokens=384",
        },
    ]
    out = _read_tool(monkeypatch, rows, _HEALTH_DEGRADED)
    assert out["timeline"][0]["degraded_reason"].startswith("truncated:")
    assert "truncated x1" in out["layer_reason"]


def test_the_two_historical_rows_are_labelled_not_re_extracted(monkeypatch):
    """LIVE SPECIMENS — 2026-06-22 and 2026-06-25 (`USER#matthew#SOURCE#training_notes#
    EXERCISE#D8F7F851`), still `degraded: true`, `extracted_by: deterministic`, `progression`
    only, NO reason field, `extracted_at` 2026-06-22 / 2026-07-06.

    They are NOT re-run through the extractor. A signal re-derived in September and written
    into a June record is indistinguishable from an original one forever; the honest outcome
    is that those two rows stay impoverished and SAY SO. The read surface labels them
    `unrecorded` with the reason it is unrecorded.
    """
    rows = [
        {
            "sk": "DATE#2026-06-22#WORKOUT#1a06d0c8",
            "date": "2026-06-22",
            "note_raw": "Level 9 for 20 and then level 6 for 10 - more of a flush - despite green recovery - i felt tired today",
            "signals": [{"class": "progression", "summary": "level 9", "confidence": 0.9}],
            "degraded": True,
            "extracted_by": "deterministic",
        },
    ]
    out = _read_tool(monkeypatch, rows, _HEALTH_DEGRADED)
    entry = out["timeline"][0]
    assert entry["degraded_reason"].startswith(tn.DEGRADE_UNRECORDED + ":")
    assert "before #3699" in entry["degraded_reason"]
    assert entry["note_raw"] == rows[0]["note_raw"], "the raw note is sovereign and unchanged"


def test_a_healthy_row_carries_no_reason_in_the_read_tool(monkeypatch):
    """NEGATIVE CONTROL — the field must be able to be null, or it says nothing."""
    rows = [
        {
            "sk": "DATE#2026-09-12#WORKOUT#a5",
            "date": "2026-09-12",
            "note_raw": "Level 9 flat",
            "signals": [{"class": "progression", "summary": "level 9", "confidence": 0.9}],
            "degraded": False,
        },
    ]
    out = _read_tool(monkeypatch, rows, {"checked": True, "extractor_dark": False, "degraded": 0, "records_found": 5, "lookback_days": 14})
    assert out["timeline"][0]["degraded_reason"] is None


def test_the_freshness_alert_names_the_reason():
    """The alert that actually pages read 'Check the Bedrock grant and the Haiku cap' — a
    guess, printed to the operator, every time, for three months."""
    src = (REPO / "lambdas" / "emails" / "freshness_checker_lambda.py").read_text()
    idx = src.index("training_notes_health(table)")
    window = src[idx : idx + 1200]
    assert "degraded_reasons_note" in window, "the paging alert still cannot say why the layer degraded"
