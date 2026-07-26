"""tests/test_coach_nudge_1382.py — "the coach who texts first" (#1382).

Hermetic (FakeDdbTable + injected callers, no AWS, no Bedrock). Pins the
issue's acceptance criteria:
  AC1 — trigger evaluation is pure/deterministic; fire AND no-fire per trigger.
  AC2 — hard rails: ≤1/day, quiet hours, budget tier ≥2 silences, SDT lint.
  AC3 — every sent nudge is logged verbatim to the coach's COACH# partition
        and outcome-graded (hit/miss, never left pending) into a Brier record.
  AC4 — gate-blocked copy is dropped silently: no send, NO regeneration.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import coach_nudge_engine as eng  # noqa: E402
import emails.coach_nudge_lambda as shell  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")


def _pt(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=PT)


# 18:30 PT on 2026-07-24 (PDT) — inside the send window, past the 6pm gate.
NOW_PT = _pt(2026, 7, 24, 18, 30)


def _ctx(**over):
    ctx = {
        "now_pt": NOW_PT,
        "yesterday_pt": "2026-07-23",
        "nutrition_logged_yesterday": False,
        "active_nutrition_experiments": ["Cut v3"],
        "acwr_latest": None,
        "acwr_previous": None,
        "verdicts_resolving_tomorrow": [],
    }
    ctx.update(over)
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — per-trigger fire / no-fire (pure, no I/O, no LLM anywhere)
# ══════════════════════════════════════════════════════════════════════════════


def test_nutrition_gap_fires_after_6pm_with_active_experiment():
    firing = eng.evaluate_nutrition_log_gap(_ctx())
    assert firing is not None
    assert firing["trigger_type"] == eng.TRIGGER_NUTRITION_LOG_GAP
    assert firing["coach_id"] == "nutrition_coach"
    assert firing["payload"]["missing_date"] == "2026-07-23"
    assert firing["payload"]["active_experiments"] == ["Cut v3"]
    assert firing["probe"] == {
        "kind": "item_exists",
        "pk": "USER#matthew#SOURCE#macrofactor",
        "sk": "DATE#2026-07-23",
    }


def test_nutrition_gap_no_fire_before_6pm():
    assert eng.evaluate_nutrition_log_gap(_ctx(now_pt=_pt(2026, 7, 24, 17, 59))) is None


def test_nutrition_gap_no_fire_when_yesterday_logged():
    assert eng.evaluate_nutrition_log_gap(_ctx(nutrition_logged_yesterday=True)) is None


def test_nutrition_gap_no_fire_without_active_nutrition_experiment():
    assert eng.evaluate_nutrition_log_gap(_ctx(active_nutrition_experiments=[])) is None


def test_acwr_fires_on_cross_into_caution():
    firing = eng.evaluate_acwr_band_cross(
        _ctx(
            acwr_latest={"date": "2026-07-23", "acwr": 1.34, "zone": "caution"},
            acwr_previous={"date": "2026-07-22", "acwr": 1.21, "zone": "safe"},
        )
    )
    assert firing is not None
    assert firing["trigger_type"] == eng.TRIGGER_ACWR_BAND_CROSS
    assert firing["coach_id"] == "training_coach"
    assert firing["payload"] == {"date": "2026-07-23", "acwr": 1.34, "zone": "caution", "previous_zone": "safe"}


def test_acwr_fires_on_cross_into_detraining():
    firing = eng.evaluate_acwr_band_cross(
        _ctx(
            acwr_latest={"date": "2026-07-23", "acwr": 0.71, "zone": "detraining"},
            acwr_previous={"date": "2026-07-22", "acwr": 0.85, "zone": "safe"},
        )
    )
    assert firing is not None
    assert firing["payload"]["zone"] == "detraining"


def test_acwr_no_fire_when_zone_unchanged():
    assert (
        eng.evaluate_acwr_band_cross(
            _ctx(
                acwr_latest={"date": "2026-07-23", "acwr": 1.42, "zone": "caution"},
                acwr_previous={"date": "2026-07-22", "acwr": 1.35, "zone": "caution"},
            )
        )
        is None
    )


def test_acwr_no_fire_on_recovery_into_safe():
    # Crossing back into safe is not a decision moment — nudging it is noise.
    assert (
        eng.evaluate_acwr_band_cross(
            _ctx(
                acwr_latest={"date": "2026-07-23", "acwr": 1.1, "zone": "safe"},
                acwr_previous={"date": "2026-07-22", "acwr": 1.6, "zone": "danger"},
            )
        )
        is None
    )


def test_acwr_no_fire_on_missing_data():
    assert eng.evaluate_acwr_band_cross(_ctx()) is None
    assert eng.evaluate_acwr_band_cross(_ctx(acwr_latest={"date": "2026-07-23", "acwr": 1.4, "zone": "caution"})) is None


def test_verdict_fires_when_resolving_tomorrow_and_picks_deterministically():
    verdicts = [
        {"coach_id": "sleep_coach", "prediction_id": "pred_20260710_zzz", "claim": "B", "resolution_date": "2026-07-25", "confidence": 0.7},
        {"coach_id": "mind_coach", "prediction_id": "pred_20260710_aaa", "claim": "A", "resolution_date": "2026-07-25", "confidence": 0.6},
    ]
    firing = eng.evaluate_verdict_resolving_tomorrow(_ctx(verdicts_resolving_tomorrow=verdicts))
    assert firing is not None
    assert firing["trigger_type"] == eng.TRIGGER_VERDICT_TOMORROW
    # Lexicographically smallest prediction_id wins — stable across runs.
    assert firing["payload"]["prediction_id"] == "pred_20260710_aaa"
    assert firing["coach_id"] == "mind_coach"


def test_verdict_no_fire_when_none_resolving():
    assert eng.evaluate_verdict_resolving_tomorrow(_ctx()) is None


def test_trigger_priority_is_deterministic():
    ctx = _ctx(
        acwr_latest={"date": "2026-07-23", "acwr": 1.55, "zone": "danger"},
        acwr_previous={"date": "2026-07-22", "acwr": 1.2, "zone": "safe"},
        verdicts_resolving_tomorrow=[
            {"coach_id": "sleep_coach", "prediction_id": "p1", "claim": "x", "resolution_date": "2026-07-25", "confidence": 0.5}
        ],
    )
    firings = eng.evaluate_triggers(ctx)
    assert [f["trigger_type"] for f in firings] == [
        eng.TRIGGER_ACWR_BAND_CROSS,
        eng.TRIGGER_NUTRITION_LOG_GAP,
        eng.TRIGGER_VERDICT_TOMORROW,
    ]


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — hard rails
# ══════════════════════════════════════════════════════════════════════════════


def _one_firing():
    return eng.evaluate_triggers(_ctx())


def test_rails_budget_tier_2_and_3_silence():
    for tier in (2, 3):
        chosen, reason = eng.apply_rails(_one_firing(), budget_tier=tier, sent_today=False, now_pt=NOW_PT)
        assert chosen is None
        assert reason == f"budget_tier_{tier}"


def test_rails_tier_1_still_sends():
    chosen, reason = eng.apply_rails(_one_firing(), budget_tier=1, sent_today=False, now_pt=NOW_PT)
    assert chosen is not None
    assert reason == "ok"


def test_rails_quiet_hours():
    for hh, mm in ((7, 59), (19, 0), (21, 30), (2, 0)):
        chosen, reason = eng.apply_rails(_one_firing(), budget_tier=0, sent_today=False, now_pt=_pt(2026, 7, 24, hh, mm))
        assert chosen is None
        assert reason == "quiet_hours"
    # Boundary hours INSIDE the window: quiet_hours must never be the reason.
    for hh, mm in ((8, 0), (18, 59)):
        chosen, reason = eng.apply_rails(_one_firing(), budget_tier=0, sent_today=False, now_pt=_pt(2026, 7, 24, hh, mm))
        assert chosen is not None and reason == "ok"
        _, reason = eng.apply_rails([], budget_tier=0, sent_today=False, now_pt=_pt(2026, 7, 24, hh, mm))
        assert reason == "no_trigger"


def test_rails_daily_cap():
    chosen, reason = eng.apply_rails(_one_firing(), budget_tier=0, sent_today=True, now_pt=NOW_PT)
    assert chosen is None
    assert reason == "daily_cap"


def test_rails_no_trigger():
    chosen, reason = eng.apply_rails([], budget_tier=0, sent_today=False, now_pt=NOW_PT)
    assert chosen is None
    assert reason == "no_trigger"


def test_budget_cutoff_registered_and_matches_engine():
    import budget_guard

    assert budget_guard._FEATURE_CUTOFF["coach_nudge"] == eng.BUDGET_SILENCE_TIER == 2


def test_nutrition_domain_tags_pinned_to_orchestrator():
    from coach.coach_narrative_orchestrator import COACH_DOMAINS

    assert shell.NUTRITION_DOMAIN_TAGS == COACH_DOMAINS["nutrition_coach"]


# ── SDT lint (deterministic — prompt rules are not structural guarantees) ────


def test_sdt_lint_flags_loss_streak_and_command_language():
    assert eng.sdt_violations("Don't break your 12-day streak!")
    assert eng.sdt_violations("You must log dinner tonight.")
    assert eng.sdt_violations("You need to get back on track — no excuses.")
    assert eng.sdt_violations("Skipping this would be a failure.")
    assert eng.sdt_violations("You're slipping and falling behind.")


def test_sdt_lint_passes_informational_skippable_copy():
    copy = (
        "Yesterday's food day isn't in the record yet, and the Cut v3 experiment is live — "
        "tonight's upload is the moment that decides whether the day counts. Totally fine to let it go, too."
    )
    assert eng.sdt_violations(copy) == []


def test_phrasing_prompt_carries_sdt_rules_and_only_payload_facts():
    firing = eng.evaluate_nutrition_log_gap(_ctx())
    system, user = eng.build_phrasing_prompt("Dr. Marcus Webb", firing)
    # The model is told it does NOT decide — phrasing only (ADR-105).
    assert "your ONLY job is to phrase it" in system
    assert "INFORMATION, never command" in system
    assert "NO loss-streak language" in system
    assert "ONLY the facts in the trigger payload" in system
    # The user message is the payload and nothing but the payload facts.
    assert "2026-07-23" in user
    assert "Cut v3" in user
    assert firing["invited_action"] in user


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — grading math (pure)
# ══════════════════════════════════════════════════════════════════════════════


def test_grade_due_boundary():
    sent = "2026-07-25T01:30:00Z"
    just_before = datetime(2026, 7, 25, 3, 29, 59, tzinfo=timezone.utc)
    exactly = datetime(2026, 7, 25, 3, 30, 0, tzinfo=timezone.utc)
    assert eng.grade_due(sent, just_before) is False
    assert eng.grade_due(sent, exactly) is True


def test_probe_key_range_bounds_are_string_sortable():
    lo, hi = eng.probe_key_range("2026-07-25T01:30:00Z", eng._decisions_probe())
    assert lo == "DECISION#2026-07-25T01:30:00"
    assert hi == "DECISION#2026-07-25T03:30:00~"
    # Real DECISION# sks carry milliseconds + Z — same-second sends and
    # end-of-window items must sort INSIDE the range.
    assert lo <= "DECISION#2026-07-25T01:30:00.123Z" <= hi
    assert lo <= "DECISION#2026-07-25T03:30:00.900Z" <= hi
    assert not (lo <= "DECISION#2026-07-25T03:31:00.000Z" <= hi)
    assert not (lo <= "DECISION#2026-07-25T01:29:59.999Z" <= hi)


def test_brier_math():
    assert eng.brier_for(0.4, eng.OUTCOME_HIT) == 0.36
    assert eng.brier_for(0.4, eng.OUTCOME_MISS) == 0.16
    assert eng.grade_outcome(True) == eng.OUTCOME_HIT
    assert eng.grade_outcome(False) == eng.OUTCOME_MISS


def test_proactivity_summary_counts_and_brier():
    items = [
        {"status": "sent", "outcome": "hit", "prior": "0.4", "sent_at": "2026-07-20T01:00:00Z"},
        {"status": "sent", "outcome": "miss", "prior": "0.2", "sent_at": "2026-07-21T01:00:00Z"},
        {"status": "sent", "outcome": "pending", "prior": "0.2", "sent_at": "2026-07-24T01:00:00Z"},
        {"status": "blocked", "prior": "0.4"},
    ]
    s = eng.proactivity_summary(items)
    assert s["sent"] == 3 and s["blocked"] == 1
    assert s["hit"] == 1 and s["miss"] == 1 and s["pending"] == 1
    assert s["graded"] == 2
    assert s["hit_rate_pct"] == 50.0
    # ((0.4-1)^2 + (0.2-0)^2) / 2 = (0.36 + 0.04) / 2 = 0.2
    assert s["brier"] == 0.2
    assert s["last_nudge_at"] == "2026-07-24T01:00:00Z"
    assert eng.proactivity_summary([]) is None


# ══════════════════════════════════════════════════════════════════════════════
# Shell — end-to-end with a fake table (send, gates, cap, grading)
# ══════════════════════════════════════════════════════════════════════════════


class ConditionalCheckFailedException(Exception):
    pass


def _key_filters(cond, out=None):
    out = {} if out is None else out
    op = getattr(cond, "expression_operator", "").upper()
    vals = getattr(cond, "_values", ())
    if op == "AND":
        for v in vals:
            _key_filters(v, out)
        return out
    if vals and hasattr(vals[0], "name"):
        out[vals[0].name] = (op, *vals[1:])
    return out


def _pk_dispatch_query_hook(table, **kwargs):
    f = _key_filters(kwargs["KeyConditionExpression"])
    pk = f.get("pk", (None, None))[1]
    items = [it for it in table.store.values() if it.get("pk") == pk]
    sk_op = f.get("sk")
    if sk_op and sk_op[0] == "BEGINS_WITH":
        items = [it for it in items if str(it.get("sk", "")).startswith(sk_op[1])]
    elif sk_op and sk_op[0] == "BETWEEN":
        items = [it for it in items if sk_op[1] <= it.get("sk", "") <= sk_op[2]]
    items = sorted(items, key=lambda it: it.get("sk", ""), reverse=kwargs.get("ScanIndexForward") is False)
    limit = kwargs.get("Limit")
    return {"Items": items[:limit] if limit else items}


def _conditional_put_hook(table, item, **kwargs):
    if kwargs.get("ConditionExpression") and table._key_of(item) in table.store:
        raise ConditionalCheckFailedException("The conditional request failed")
    table.store[table._key_of(item)] = item


def _fake_table(rows=None):
    return FakeDdbTable(rows=rows or [], query_hook=_pk_dispatch_query_hook, put_item_hook=_conditional_put_hook)


class _FakeSes:
    def __init__(self):
        self.sends = []

    def send_email(self, **kwargs):
        self.sends.append(kwargs)
        return {"MessageId": "fake"}


class _FixedDT(datetime):
    _fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls._fixed.astimezone(tz) if tz else cls._fixed


def _wire(monkeypatch, fake, *, now_utc, tier=0, copy_text=None, gate_result="pass"):
    """Stand the shell up against the fake table at a fixed instant."""
    import ai_calls
    import budget_guard
    import coach_checkin

    _FixedDT._fixed = now_utc
    monkeypatch.setattr(shell, "datetime", _FixedDT)
    monkeypatch.setattr(shell, "_table_ref", fake)
    ses = _FakeSes()
    monkeypatch.setattr(shell, "_ses_ref", ses)
    monkeypatch.setattr(shell, "_lambda_ref", object())
    monkeypatch.setattr(shell, "_coach_name", lambda cid: "Dr. Marcus Webb")
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    monkeypatch.setattr(coach_checkin, "_cycle_cache", {"value": 10, "read": True})

    calls = {"phrase": 0}

    def _fake_call_anthropic(prompt, api_key="", **kwargs):
        calls["phrase"] += 1
        return copy_text if copy_text is not None else "[AI_UNAVAILABLE]"

    monkeypatch.setattr(ai_calls, "call_anthropic", _fake_call_anthropic)

    def _fake_quality_gate(lambda_client, coach_id, text, brief, regenerate_fn, max_regenerations=0):
        assert max_regenerations == 0  # AC4: never regenerated
        if gate_result == "pass":
            return text, {"passed": True, "score": 88}
        return None, {"passed": False, "score": 41}

    monkeypatch.setattr(ai_calls, "_enforce_quality_gate", _fake_quality_gate)
    return ses, calls


# 18:30 PT 2026-07-24 == 01:30Z 2026-07-25 (PDT).
NOW_UTC = datetime(2026, 7, 25, 1, 30, 0, tzinfo=timezone.utc)

ACTIVE_EXPERIMENT = {
    "pk": "USER#matthew#SOURCE#experiments",
    "sk": "EXP#cut-v3_2026-07-20",
    "name": "Cut v3",
    "status": "active",
    "tags": ["nutrition"],
}

CLEAN_COPY = (
    "Yesterday's food day isn't in the record yet, and Cut v3 is live — tonight's upload is "
    "the moment that decides whether the day counts. Completely fine to let it go, too."
)


def test_handler_sends_and_logs_verbatim_nudge(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, calls = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=CLEAN_COPY)

    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "sent"
    assert out["trigger"] == eng.TRIGGER_NUTRITION_LOG_GAP
    assert len(ses.sends) == 1
    assert calls["phrase"] == 1

    # AC3: verbatim record in the sending coach's COACH# partition.
    nudges = [it for it in fake.store.values() if str(it.get("sk", "")).startswith("NUDGE#")]
    assert len(nudges) == 1
    n = nudges[0]
    assert n["pk"] == "COACH#nutrition_coach"
    assert n["copy"] == CLEAN_COPY  # stored exactly as produced (ADR-104)
    assert n["status"] == "sent"
    assert n["outcome"] == "pending"
    assert n["prior"] == "0.4"
    assert n["cycle"] == 10
    # Ledger row claims the day and points at the record for the grading pass.
    ledger = fake.store.get((eng.LEDGER_PK, "DAY#2026-07-24"))
    assert ledger and ledger["status"] == "sent" and ledger["graded"] is False
    assert (ledger["nudge_pk"], ledger["nudge_sk"]) == (n["pk"], n["sk"])


def test_handler_daily_cap_second_run_is_silent(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, calls = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    shell.lambda_handler({}, None)
    out2 = shell.lambda_handler({}, None)
    assert out2["nudge"] is None
    assert out2["reason"] == "daily_cap"
    assert len(ses.sends) == 1
    assert calls["phrase"] == 1  # no second model call either


def test_handler_reserve_race_stands_down(monkeypatch):
    # A racing invocation claimed the day between the sent_today check and the
    # conditional put — the put raises and the handler stands down silently.
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, _ = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    original = fake._put_item_hook

    def _racing_hook(table, item, **kwargs):
        if kwargs.get("ConditionExpression"):
            raise ConditionalCheckFailedException("The conditional request failed")
        original(table, item, **kwargs)

    fake._put_item_hook = _racing_hook
    out = shell.lambda_handler({}, None)
    assert out["nudge"] is None
    assert out["reason"] == "daily_cap_race"
    assert ses.sends == []


def test_handler_budget_tier_2_silences_before_any_read(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, calls = _wire(monkeypatch, fake, now_utc=NOW_UTC, tier=2, copy_text=CLEAN_COPY)
    out = shell.lambda_handler({}, None)
    assert out["nudge"] is None
    assert out["reason"] == "budget_tier_2"
    assert ses.sends == [] and calls["phrase"] == 0


def test_handler_quiet_hours_silent(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    # 05:30Z 2026-07-25 = 22:30 PT 2026-07-24 — outside the send window.
    ses, _ = _wire(monkeypatch, fake, now_utc=datetime(2026, 7, 25, 5, 30, tzinfo=timezone.utc), copy_text=CLEAN_COPY)
    out = shell.lambda_handler({}, None)
    assert out["nudge"] is None
    assert out["reason"] == "quiet_hours"
    assert ses.sends == []


# ── AC4: gates block ⇒ dropped silently, stored for audit, never regenerated ──


def test_handler_grounding_violation_blocks_silently(monkeypatch):
    fabricated = "You averaged 512 calories at dinner this week — log tonight by 9pm."
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, calls = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=fabricated)
    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "blocked"
    assert ses.sends == []
    assert calls["phrase"] == 1  # exactly ONE generation — no regen into vagueness
    nudges = [it for it in fake.store.values() if str(it.get("sk", "")).startswith("NUDGE#")]
    assert len(nudges) == 1
    assert nudges[0]["status"] == "blocked"
    assert nudges[0]["copy"] == fabricated  # audit trail keeps the verbatim draft
    assert any(f.startswith("grounding:fabricated_number") for f in nudges[0]["gate_findings"])
    assert "outcome" not in nudges[0]  # blocked nudges never enter the Brier
    # The day is consumed — anti-nag: no later retry.
    assert fake.store.get((eng.LEDGER_PK, "DAY#2026-07-24"))["status"] == "blocked"


def test_handler_sdt_violation_blocks_silently(monkeypatch):
    bossy = "Don't break your streak — you must upload yesterday's log."
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, _ = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=bossy)
    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "blocked"
    assert ses.sends == []
    nudges = [it for it in fake.store.values() if str(it.get("sk", "")).startswith("NUDGE#")]
    assert any(f.startswith("sdt:") for f in nudges[0]["gate_findings"])


def test_handler_quality_gate_hold_blocks_silently(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, calls = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=CLEAN_COPY, gate_result="hold")
    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "blocked"
    assert ses.sends == [] and calls["phrase"] == 1
    nudges = [it for it in fake.store.values() if str(it.get("sk", "")).startswith("NUDGE#")]
    assert any(f.startswith("quality_gate:held") for f in nudges[0]["gate_findings"])


def test_handler_ai_unavailable_blocks_silently(monkeypatch):
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    ses, _ = _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=None)  # sentinel
    out = shell.lambda_handler({}, None)
    assert out["nudge"] == "blocked"
    assert out["reason"] == "ai_unavailable"
    assert ses.sends == []


# ── AC3: the grading pass — a sent nudge NEVER stays ungraded ────────────────


def _sent_nudge_rows(sent_at="2026-07-25T01:30:00Z", probe=None):
    probe = probe or eng._decisions_probe()
    nudge = {
        "pk": "COACH#training_coach",
        "sk": "NUDGE#2026-07-24#abcd1234",
        "status": "sent",
        "outcome": "pending",
        "prior": "0.2",
        "probe": probe,
        "sent_at": sent_at,
        "copy": "x",
        "trigger_type": eng.TRIGGER_ACWR_BAND_CROSS,
        "coach_id": "training_coach",
    }
    ledger = {
        "pk": eng.LEDGER_PK,
        "sk": "DAY#2026-07-24",
        "status": "sent",
        "graded": False,
        "sent_at": sent_at,
        "nudge_pk": nudge["pk"],
        "nudge_sk": nudge["sk"],
        "trigger_type": nudge["trigger_type"],
        "coach_id": "training_coach",
    }
    return nudge, ledger


def test_grading_pass_hit_when_decision_logged_inside_window(monkeypatch):
    nudge, ledger = _sent_nudge_rows()
    decision = {"pk": "USER#matthew#SOURCE#decisions", "sk": "DECISION#2026-07-25T02:10:00.123Z", "decision": "easy day"}
    fake = _fake_table(rows=[nudge, ledger, decision])
    monkeypatch.setattr(shell, "_table_ref", fake)

    graded = shell.run_grading_pass(datetime(2026, 7, 25, 3, 40, tzinfo=timezone.utc))
    assert graded == 1
    upd = fake.updates[-1]
    assert upd["Key"] == {"pk": nudge["pk"], "sk": nudge["sk"]}
    assert upd["ExpressionAttributeValues"][":o"] == "hit"
    assert upd["ExpressionAttributeValues"][":b"] == str(eng.brier_for(0.2, "hit"))
    assert fake.store[(eng.LEDGER_PK, "DAY#2026-07-24")]["graded"] is True


def test_grading_pass_miss_when_no_action_appeared(monkeypatch):
    nudge, ledger = _sent_nudge_rows()
    # A decision AFTER the window must not count.
    late = {"pk": "USER#matthew#SOURCE#decisions", "sk": "DECISION#2026-07-25T05:00:00.000Z"}
    fake = _fake_table(rows=[nudge, ledger, late])
    monkeypatch.setattr(shell, "_table_ref", fake)

    graded = shell.run_grading_pass(datetime(2026, 7, 25, 5, 40, tzinfo=timezone.utc))
    assert graded == 1
    upd = fake.updates[-1]
    assert upd["ExpressionAttributeValues"][":o"] == "miss"
    assert upd["ExpressionAttributeValues"][":b"] == str(eng.brier_for(0.2, "miss"))


def test_grading_pass_waits_for_window_to_elapse(monkeypatch):
    nudge, ledger = _sent_nudge_rows()
    fake = _fake_table(rows=[nudge, ledger])
    monkeypatch.setattr(shell, "_table_ref", fake)
    graded = shell.run_grading_pass(datetime(2026, 7, 25, 2, 30, tzinfo=timezone.utc))  # +1h only
    assert graded == 0
    assert fake.updates == []
    assert fake.store[(eng.LEDGER_PK, "DAY#2026-07-24")]["graded"] is False


def test_grading_pass_item_exists_probe(monkeypatch):
    probe = {"kind": "item_exists", "pk": "USER#matthew#SOURCE#macrofactor", "sk": "DATE#2026-07-23"}
    nudge, ledger = _sent_nudge_rows(probe=probe)
    upload = {"pk": "USER#matthew#SOURCE#macrofactor", "sk": "DATE#2026-07-23", "total_calories_kcal": 1900}
    fake = _fake_table(rows=[nudge, ledger, upload])
    monkeypatch.setattr(shell, "_table_ref", fake)
    graded = shell.run_grading_pass(datetime(2026, 7, 25, 4, 0, tzinfo=timezone.utc))
    assert graded == 1
    assert fake.updates[-1]["ExpressionAttributeValues"][":o"] == "hit"


def test_sent_nudge_is_always_graded_end_to_end(monkeypatch):
    """The AC3 invariant: send at T, run the schedule tick at T+3h with no
    action anywhere — the nudge MUST land on a graded outcome (miss), never
    stay pending."""
    fake = _fake_table(rows=[ACTIVE_EXPERIMENT])
    _wire(monkeypatch, fake, now_utc=NOW_UTC, copy_text=CLEAN_COPY)
    assert shell.lambda_handler({}, None)["nudge"] == "sent"

    later = NOW_UTC + timedelta(hours=3)
    _FixedDT._fixed = later
    graded = shell.run_grading_pass(later)
    assert graded == 1
    assert fake.updates[-1]["ExpressionAttributeValues"][":o"] == "miss"
    assert fake.store[(eng.LEDGER_PK, "DAY#2026-07-24")]["graded"] is True


# ── record/key shapes ─────────────────────────────────────────────────────────


def test_nudge_keys_and_builder_shapes():
    assert eng.nudge_pk("nutrition_coach") == "COACH#nutrition_coach"
    sk = eng.new_nudge_sk("2026-07-24", "abcd1234")
    assert sk == "NUDGE#2026-07-24#abcd1234"
    assert eng.ledger_sk("2026-07-24") == "DAY#2026-07-24"

    firing = eng.evaluate_nutrition_log_gap(_ctx())
    item = eng.build_nudge_item(firing, "hello", eng.STATUS_SENT, date_pt="2026-07-24", now_utc=NOW_UTC, uid="abcd1234")
    assert item["outcome"] == eng.OUTCOME_PENDING
    blocked = eng.build_nudge_item(firing, "hello", eng.STATUS_BLOCKED, date_pt="2026-07-24", now_utc=NOW_UTC, gate_findings=["sdt:x"])
    assert "outcome" not in blocked
    ledger = eng.build_ledger_item("2026-07-24", item)
    assert ledger["graded"] is False and ledger["nudge_sk"] == item["sk"]
    ledger_blocked = eng.build_ledger_item("2026-07-24", blocked)
    assert ledger_blocked["graded"] is True  # nothing to grade — never delivered


# ── #1793: phase filter on computed_metrics + PREDICTION# reads ───────────────
# A cycle reset tags prior-cycle rows phase=pilot (often tombstoned). Unfiltered,
# _acwr_readings served a discarded cycle's training load as today's fact and
# _verdicts_resolving_tomorrow surfaced wiped predictions for weeks (the daily
# nudge cap burned on dead intelligence — fired live on 2026-07-26).


def test_1793_acwr_read_carries_phase_filter(monkeypatch):
    fake = _fake_table(rows=[])
    monkeypatch.setattr(shell, "_table_ref", fake)
    shell._acwr_readings()
    assert fake.query_calls, "expected a computed_metrics query"
    for c in fake.query_calls:
        assert "FilterExpression" in c and "#phase" in str(c["FilterExpression"]), "#1793: computed_metrics read must be phase-filtered"


def test_1793_prediction_read_carries_phase_filter(monkeypatch):
    fake = _fake_table(rows=[])
    monkeypatch.setattr(shell, "_table_ref", fake)
    shell._verdicts_resolving_tomorrow("2026-07-27")
    assert len(fake.query_calls) >= 2, "expected one PREDICTION# query per operational coach"
    for c in fake.query_calls:
        assert "FilterExpression" in c and "#phase" in str(c["FilterExpression"]), "#1793: PREDICTION# reads must be phase-filtered"
