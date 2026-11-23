"""tests/test_brief_compact_safeguards_6240.py — the two safeguards required before the compact brief activates
(#6240, owner ruling 2026-11-23 on #6241, §2 and §3).

§2 UNSUPPORTED MEDICAL RECOMMENDATIONS. A model-written recommendation that makes a high-stakes health claim
(clearance, disease, diagnosis, medication, genomic, physiological threshold, lab interpretation, body mechanism) is
HELD unless grounded in a platform-computed source; genomic content is never shown. The fixtures are structural
paraphrases with FICTIONAL values of the claims the 23 November brief carried — the exact originals stay private and
are read only by the local-only test at the bottom (env `BRIEF_6240_PRIVATE_CLAIMS`, a JSON list; skipped when unset).

§3 DAILY VARIATION VS SUSTAINED TRENDS. Four states (ordinary, trend, concern, unknown) from verdicts the platform
already computes; the lead never sits silent over an open trend; the full sentence follows a cadence (opens, changes,
weekly), a few-word pointer otherwise; nothing changes a target; the plan band's value is never printed.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

import pytest
import test_brief_compact_6240 as base
from content import brief_budget as bb, brief_compact as bc, brief_rec_screen as rs, brief_trends as bt_
from emails import brief_trial as bt

# ══════════════════════════════════════════════════════════════════════════════
# §2 the screen
# ══════════════════════════════════════════════════════════════════════════════

# Paraphrases of the 23 November high-stakes claims (fictional numbers), each with the class it must trip.
HELD = [
    ("🏆 At 291.6 lb you are now below 293, the point where your genome flag says sleep apnea risk drops substantially.", "genomic"),
    ("Crossing 293 is a real biological shift — apnoea risk falls right here.", "disease"),
    ("Late autumn is the peak window for slower T4-to-T3 conversion in a long deficit, so ease the deficit this week.", "lab"),
    ("This month is when thyroid adaptation risk peaks during a deficit — keep an eye on it.", "disease"),
    ("Book a CMP, CBC, fasting insulin and TSH this week; your kidney markers cannot support more protein yet.", "lab"),
    ("With the log patchy, your body will pull from lean tissue to cover the shortfall — add a shake.", "physiology"),
    ("Recovery is green — you're cleared to push hard today.", "clearance"),
    ("Take 200 mg of magnesium tonight and ask about your beta blocker dose.", "medication"),
    ("A low reading like this can be a sign of a deficiency; worth checking.", "diagnosis"),
    ("Once you are under 250 lb the risk threshold for joint load drops sharply, so add a run.", "threshold"),
]
CLEAN = [
    "🚶 A 20-minute walk after dinner tonight is the simplest move.",
    "🥚 Aim for about 40 g of protein at breakfast tomorrow.",
    "😴 Your last three nights averaged 6.2 hours; aim to be in bed by 10:15 tonight.",
    "📋 If you logged food yesterday, export MacroFactor when convenient.",
    "Keep steps above 8,000 today.",
    "Try a goblet squat variant on leg day.",
    "💧 Keep a water bottle at your desk this afternoon.",
    "Stretch your hips for five minutes after the session.",
]


def test_every_high_stakes_paraphrase_is_held_with_its_class():
    missed = [(t, cls, rs.claim_classes(t)) for t, cls in HELD if cls not in rs.claim_classes(t) or rs.screen(t, "ai_guidance")[0]]
    assert not missed, missed


def test_clean_legitimate_recommendations_still_pass():
    caught = [(t, rs.claim_classes(t)) for t in CLEAN if not rs.screen(t, "ai_guidance")[0]]
    assert not caught, caught


def test_grounding_passes_a_platform_computed_source_but_never_genomic_content():
    assert rs.screen("Your thyroid panel is due per the platform's lab schedule.", "food_export")[0] is True
    assert rs.screen("Your thyroid panel is due.", "ai_guidance")[0] is False  # the model's text carries no provenance
    assert rs.screen("Your genome suggests a slower caffeine clearance.", "readiness") == (False, ["genomic"])


def test_a_held_recommendation_is_not_shown_and_is_kept_privately_with_its_reason():
    genomic = HELD[0][0].replace("🏆 ", "")  # a non-observation phrasing reaches the screen as an ask
    ask = "Book a CMP and TSH this week before raising protein."
    view = base._view(data=base._quiet_data(), guidance=[ask, CLEAN[0]])
    html, text = base._render(view)
    assert "CMP" not in html and "CMP" not in text and "walk after dinner" in html
    assert view.held_recs == [{"key": view.held_recs[0]["key"], "classes": ["lab"], "text": ask}]
    view2 = base._view(data=base._quiet_data(), guidance=["Keep going: " + genomic])
    assert [h["classes"][0] for h in view2.held_recs] and "genome" not in base._render(view2)[0]


def test_the_held_text_rides_the_private_send_row_and_never_a_log_line(env, monkeypatch, caplog):
    from unittest.mock import MagicMock

    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    for name in ("call_board_of_directors", "call_journal_coach"):
        monkeypatch.setattr(base.brief.ai_calls, name, MagicMock(return_value="note"))
    monkeypatch.setattr(base.brief.ai_calls, "call_training_nutrition_coach", MagicMock(return_value={"training": "t", "nutrition": "n"}))
    claim = "Ask your doctor to start a statin; your lipid panel says so."
    monkeypatch.setattr(base.brief.ai_calls, "call_tldr_and_guidance", MagicMock(return_value={"tldr": "A day.", "guidance": [claim]}))
    caplog.set_level("DEBUG")
    sent = base._run(env, "compact")["Content"]["Simple"]
    row = base._sends(env)[-1]
    assert "statin" not in sent["Body"]["Html"]["Data"] and "statin" not in sent["Body"]["Text"]["Data"]
    assert row["n_held_medical"] == 1 and row["held_recs"][0]["text"] == claim
    assert set(row["held_recs"][0]["classes"]) >= {"medication", "lab"}
    assert "statin" not in caplog.text


env = base.env
frozen_clock, _every_day_is_a_narrative_day, handler_env, ses, table = (
    base.frozen_clock,
    base._every_day_is_a_narrative_day,
    base.handler_env,
    base.ses,
    base.table,
)


def test_local_only_the_exact_23_november_claims_are_held():
    """Reads the PRIVATE originals when the owner's machine provides them; nothing private is in the repo."""
    path = os.environ.get("BRIEF_6240_PRIVATE_CLAIMS")
    if not path or not os.path.exists(path):
        pytest.skip("private claim fixture not provided (local-only check)")
    with open(path, encoding="utf-8") as fh:
        claims = json.load(fh)
    passed = [c for c in claims if rs.screen(c, "ai_guidance")[0]]
    assert not passed, f"{len(passed)} of {len(claims)} private claims would be shown"


# ══════════════════════════════════════════════════════════════════════════════
# §3 the four states
# ══════════════════════════════════════════════════════════════════════════════


class _Log:
    def warning(self, *a, **k):
        pass

    info = error = warning


BAND = {"floor_lb_wk": 2.0, "ceiling_lb_wk": 2.5, "governs": True}  # fictional plan band


def _st(rate, lo, hi, provisional=False):
    return {"weekly_rate_lbs": rate, "rate_ci_low": lo, "rate_ci_high": hi, "rate_provisional": provisional}


def test_the_four_states():
    assert bt_.weight_rate_item(_st(-2.2, -2.6, -1.9), BAND, False) is None  # inside the band: ordinary
    assert bt_.state([]) == "ordinary"
    firm = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)
    possible = bt_.weight_rate_item(_st(-2.7, -3.0, -2.3), BAND, False)
    slow = bt_.weight_rate_item(_st(-1.2, -1.5, -0.9), BAND, False)
    assert (firm.kind, firm.sig) == ("trend", "faster:firm") and "has run faster" in firm.full
    assert possible.sig == "faster:possible" and "may be running faster" in possible.full
    assert slow.sig == "slower:firm" and bt_.state([slow]) == "trend"
    prov = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8, provisional=True), BAND, False)
    unread = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), None, False)
    cap_unread = bt_.weight_rate_item(_st(-2.2, -2.6, -1.9), BAND, True)
    assert {prov.kind, unread.kind, cap_unread.kind} == {"unknown"} and bt_.state([prov]) == "unknown"
    concern = bt_.sustained_items(
        {"sustained_metrics": [{"metric": "hrv", "label": "HRV", "streak_days": Decimal("4"), "direction": "low"}]},
        bc.ANOMALY_PHYSIOLOGICAL_FIELDS,
    )
    assert [c.kind for c in concern] == ["concern"] and bt_.state(concern + [firm]) == "concern"
    goal_side = {"sustained_metrics": [{"metric": "weight_lbs", "label": "Weight", "streak_days": 3, "direction": "low"}]}
    assert bt_.sustained_items(goal_side, bc.ANOMALY_PHYSIOLOGICAL_FIELDS) == []


def test_trend_wording_never_changes_a_target_never_prints_the_band_and_is_never_clearance():
    for it in (bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False), bt_.weight_rate_item(_st(-1.2, -1.5, -0.9), BAND, False)):
        assert "Nothing here changes your targets" in it.full
        for n in ("2.0", "2.5"):
            assert n not in it.full and n not in it.pointer and n not in it.lead
        assert not bc.CLEARANCE_RE.search(it.full + it.pointer + it.lead)


def test_a_reassuring_headline_never_sits_over_an_open_trend():
    item = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)
    view = base._view(data=base._quiet_data(), guidance=[])
    assert view.lead_kind == "quiet"  # the same day without the trend is genuinely quiet
    view = bt.compact_view(
        data=base._quiet_data(),
        status=base._status(base._quiet_data()),
        guidance_items=[],
        history={},
        alerts=[],
        previous_weight=("2026-11-07", 291.9),
        previous_acwr=1.02,
        site_url=base.SITE,
        persona=base.PERSONA,
        trends=tuple(bt_.apply_cadence([item], [], base.DAY)),
    )
    html, text = base._render(view)
    assert view.lead_kind == "trend" and item.lead in view.lead and bc.QUIET_LEAD not in html
    assert view.changed == bc.DAY_ONLY_NO_CHANGE and 'data-trend="trend"' in html
    assert bb.check(html, text, persona_names=base.PERSONA) == []
    assert bb.measure(html, text)["words"] <= bc.WORD_CEILING  # the trend counts inside the 250


def _sends_for(days_and_items):
    return [{"sk": "SEND#" + d, "trend_notes": bt_.notes(items)} for d, items in days_and_items]


def test_the_full_sentence_follows_its_cadence_never_daily():
    history, modes = [], []
    for i in range(16):
        day = "2026-11-%02d" % (10 + i)
        sig = (-3.1, -3.4, -2.8) if i < 12 else (-3.6, -3.9, -3.3)  # same pattern for 12 days, then it moves
        item = bt_.weight_rate_item(_st(*sig), BAND if i < 12 else {**BAND, "ceiling_lb_wk": 2.5}, False)
        if i >= 12:
            item.sig = "faster:firm:steeper"  # a material change of the open item
        bt_.apply_cadence([item], history, day)
        modes.append(item.mode)
        history = history + _sends_for([(day, [item])])
    assert modes[0] == "full"  # opens
    assert modes[1:7] == ["pointer"] * 6  # no daily nagging
    assert modes[7] == "full"  # the weekly reminder while unresolved
    assert modes[8:12] == ["pointer"] * 4
    assert modes[12] == "full" and modes[13] == "pointer"  # a material change is said once, then points again


def test_a_closed_item_that_reopens_is_said_in_full_again():
    item = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)
    hist = _sends_for([("2026-11-10", [item]), ("2026-11-11", [])])
    again = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)
    assert bt_.apply_cadence([again], hist, "2026-11-12")[0].mode == "full"


def test_the_pointer_is_a_few_words_and_names_when_it_was_first_said():
    first = bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)
    hist = _sends_for([("2026-11-10", bt_.apply_cadence([first], [], "2026-11-10"))])
    nxt = bt_.apply_cadence([bt_.weight_rate_item(_st(-3.1, -3.4, -2.8), BAND, False)], hist, "2026-11-11")[0]
    assert nxt.mode == "pointer" and bb.words(nxt.pointer) <= 14 and "said in full November 11" in nxt.pointer  # read the morning after


def test_below_the_landing_weight_the_band_does_not_govern(monkeypatch):
    from training import rate_band

    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table: None)
    monkeypatch.setattr(rate_band, "band_view", lambda w, r, c: {**BAND, "governs": False})
    items = bt._trend_items(None, {}, {"weight_lbs": 230.0, "weekly_rate_lbs": -3.1, "rate_ci_low": -3.4, "rate_ci_high": -2.8}, _Log())
    assert items == []

    def boom(table):
        raise rate_band.GuidanceReadError("x")

    monkeypatch.setattr(rate_band, "guidance_cap_for", boom)
    monkeypatch.setattr(rate_band, "band_view", lambda w, r, c: dict(BAND))
    inside = {"weight_lbs": 280.0, "weekly_rate_lbs": -2.2, "rate_ci_low": -2.6, "rate_ci_high": -1.9}
    assert [i.kind for i in bt._trend_items(None, {}, inside, _Log())] == ["unknown"]
