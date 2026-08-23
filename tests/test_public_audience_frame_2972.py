"""tests/test_public_audience_frame_2972.py — #2972: the public-audience frame is a
property of the SURFACE, enforced, not a prompt line.

THE LIVE DEFECT (reader-truth run 32580634729, two `high` audience_violation findings
on /method/board/): every coach text field is written in the coaching register — the
coach speaking TO Matthew — and the public serving paths fell through to them.
`position_summary` (the field the board blurb preferred) was empty in 175/175 OUTPUT#
rows (written to a different partition), so the blurb ALWAYS served a 200-char slice
of `content`, the owner's private channel.

Pinned here, each against the wire it rides:

  * the guard itself — the two live finding strings are rejected; honest third-person
    public prose (including "Matthew" as subject/possessive) passes;
  * /api/coaching-dashboard through the REAL handler over a fake table — an OUTPUT#
    row with owner-directed `content`/`observatory_summary` and no `public_summary`
    serves an EMPTY blurb (the old fallthrough would have served the content: this
    test fails on the pre-#2972 code), a clean `public_summary` serves, an
    owner-directed one is withheld;
  * the truncation-launder trap — a `public_summary` whose only second-person address
    sits BEYOND the 200-char cut is still rejected (guard runs on the full text,
    before truncation — `check(truncate(x))` was the unsound first attempt recorded
    in the issue);
  * /api/coach_analysis carries `public_read` (guarded, untruncated) and never
    derives it from `observatory_summary`/`content`;
  * the integrator chokepoint — `_integrator_digest` withholds an owner-directed
    weekly `analysis` (None) at the one seam all four public consumers share;
  * producer wiring — `public_summary` is in the extraction contract, in the
    recondense contract, in the ADR-104 derived-prose SET (grounded + held together),
    NOT in the owner-register serving preference, and the writer persists it through
    `audience_guard.reader_safe`;
  * the board front-end renders `an.public_read` and never `an.analysis`.

Offline: no AWS, no network — FakeDdbTable + monkeypatched module globals.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from coach import audience_guard, coach_derived_prose  # noqa: E402
from coach.coach_extraction_prompt import EXTRACTION_SYSTEM_PROMPT  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_coach as C,  # noqa: E402
    site_api_coach_stance as S,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
)

# ── The two LIVE finding texts (run 32580634729 / the #2972 baseline entry) ─────────

_ELI_MARSH = "You've logged two training sessions in the past 30 days. Start with the pull-day template when you're back in the gym."
_LISA_PARK = (
    "The habits and food channels have been quiet for three days, Matthew — and I want to name that plainly. "
    "I want to put to you directly: while you were actively logging, the picture held together. "
    "When you're ready, I'd like you to resume."
)

# Honest PUBLIC register — first person for the coach, strictly third person for the
# subject, name-as-subject and possessive both present on purpose.
_PUBLIC_OK = (
    "Matthew logged two training sessions this week, and his recovery held at 60%. "
    "I'm watching his HRV closely — the pattern I flagged on Day 3 hasn't moved. "
    "On the food side, Matthew's channels have been quiet, so I've asked him to resume logging before I read anything into the trend."
)


# ══════════════════════════════════════════════════════════════════════════════
# THE GUARD
# ══════════════════════════════════════════════════════════════════════════════


def test_the_two_live_findings_are_owner_directed():
    assert audience_guard.is_owner_directed(_ELI_MARSH)
    assert audience_guard.is_owner_directed(_LISA_PARK)


def test_vocative_matthew_is_rejected_even_without_a_you():
    # The /coaching/read/ finding shape: direct address by name alone.
    assert audience_guard.is_owner_directed(
        "The habits and food channels have been quiet for three days, Matthew — so the picture is thin."
    )


def test_third_person_public_register_passes():
    assert not audience_guard.is_owner_directed(_PUBLIC_OK)


def test_matthew_as_subject_or_possessive_is_not_an_address():
    # ", Matthew <verb>" (clause subject) and ", Matthew's" (possessive) are the
    # public register working as designed — a guard that rejects them would blank
    # every honest blurb.
    assert not audience_guard.is_owner_directed("On Day 3, Matthew hit his protein target.")
    assert not audience_guard.is_owner_directed("Against that backdrop, Matthew's plan needs one adjustment, and I've made it.")


def test_reader_safe_holds_owner_directed_text_and_passes_clean_text():
    assert audience_guard.reader_safe(_ELI_MARSH) is None
    assert audience_guard.reader_safe(None) is None
    assert audience_guard.reader_safe("   ") is None
    assert audience_guard.reader_safe(_PUBLIC_OK) == _PUBLIC_OK


# ══════════════════════════════════════════════════════════════════════════════
# THE DASHBOARD WIRE — /api/coaching-dashboard through the real handler
# ══════════════════════════════════════════════════════════════════════════════

_EVENT = {"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}


def _dashboard_coaches(monkeypatch, output_row):
    monkeypatch.setattr(L, "table", FakeDdbTable(rows=[output_row]))
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler(dict(_EVENT), None)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])["coaches"]


def _output_row(**fields):
    row = {"pk": "COACH#sleep_coach", "sk": "OUTPUT#2026-08-20#daily", "created_at": "2026-08-20T17:02:59Z"}
    row.update(fields)
    return row


def test_dashboard_never_serves_the_owner_channel_when_no_public_summary_exists(monkeypatch):
    """The exact live defect: no public field on the row, owner-directed content.

    The pre-#2972 chain served `truncate(content, 200)` here — this test fails on
    that code. The fixed slot serves EMPTY (the front-ends drop empty entries)."""
    coaches = _dashboard_coaches(monkeypatch, _output_row(content=_LISA_PARK, observatory_summary=_ELI_MARSH))
    assert coaches, "dashboard served no coach entries at all"
    for c in coaches:
        assert c["position_summary"] == "", f"{c['coach_id']}: the owner channel leaked to the public blurb: {c['position_summary']!r}"


def test_dashboard_serves_a_clean_public_summary_truncated_at_a_word(monkeypatch):
    coaches = _dashboard_coaches(monkeypatch, _output_row(content=_LISA_PARK, public_summary=_PUBLIC_OK))
    served = coaches[0]["position_summary"]
    assert served
    assert len(served) <= 201  # truncate_at_word(200) + possible ellipsis char
    assert not audience_guard.is_owner_directed(served)
    assert served.split()[0] == "Matthew"


def test_dashboard_withholds_an_owner_directed_public_summary(monkeypatch):
    coaches = _dashboard_coaches(monkeypatch, _output_row(content=_PUBLIC_OK, public_summary=_ELI_MARSH))
    for c in coaches:
        assert c["position_summary"] == ""


def test_truncation_cannot_launder_an_address_past_the_cut(monkeypatch):
    """The unsound first attempt applied the check AFTER truncate_at_word(..., 200) —
    a 200-char slice of addressing prose passed a check its source fails. The guard
    must read the FULL stored text."""
    clean_head = (
        "Matthew's week started strong: two training sessions, recovery at 60%, and his HRV steady. "
        "I'm watching the food channels, which have been quiet for three days now, and the picture is thin. "
    )
    assert len(clean_head) > 180  # the address below sits beyond the 200-char cut
    laundered = clean_head + "When you're ready, I'd like you to resume logging."
    assert not audience_guard.is_owner_directed(clean_head)
    coaches = _dashboard_coaches(monkeypatch, _output_row(public_summary=laundered))
    for c in coaches:
        assert c["position_summary"] == "", "a truncated slice passed a check its full source fails — the launder trap is back"


# ══════════════════════════════════════════════════════════════════════════════
# /api/coach_analysis — the board detail's `public_read`
# ══════════════════════════════════════════════════════════════════════════════


def _coach_analysis_body(monkeypatch, output_row):
    monkeypatch.setattr(C, "table", FakeDdbTable(rows=[output_row]))
    monkeypatch.setattr(C, "_integrator_digest", lambda: None)
    monkeypatch.setattr(C, "_latest_cycle_digest", lambda: None)
    monkeypatch.setattr(C, "_regeneration_paused", lambda feature: False)
    event = {"queryStringParameters": {"domain": "sleep"}}
    resp = C.handle_coach_analysis(event)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_coach_analysis_serves_public_read_from_public_summary_only(monkeypatch):
    body = _coach_analysis_body(monkeypatch, _output_row(content=_LISA_PARK, public_summary=_PUBLIC_OK))
    assert body["public_read"] == _PUBLIC_OK
    # `analysis` stays the coaching register pending the #2959 adjudication —
    # unchanged behavior, asserted so this test documents the split deliberately.
    assert body["analysis"] == _LISA_PARK


def test_coach_analysis_omits_public_read_when_no_safe_public_text_exists(monkeypatch):
    # No public_summary at all → absent (None-stripped), never derived from content.
    body = _coach_analysis_body(monkeypatch, _output_row(content=_LISA_PARK, observatory_summary=_ELI_MARSH))
    assert "public_read" not in body
    # Owner-directed public_summary (a pre-fix row, or a producer drift) → withheld.
    body = _coach_analysis_body(monkeypatch, _output_row(content=_PUBLIC_OK, public_summary=_LISA_PARK))
    assert "public_read" not in body


# ══════════════════════════════════════════════════════════════════════════════
# THE INTEGRATOR CHOKEPOINT — one seam, four public consumers
# ══════════════════════════════════════════════════════════════════════════════


def _integrator_item(analysis):
    return {
        "pk": "USER#matthew#SOURCE#ai_analysis",
        "sk": "EXPERT#integrator",
        "analysis": analysis,
        "generated_at": "2026-08-20T17:00:00Z",
    }


def test_integrator_digest_withholds_an_owner_directed_weekly_text():
    fake = FakeDdbTable(rows=[_integrator_item(_ELI_MARSH)])
    item = S._integrator_digest(_g={"table": fake})
    assert item is not None, "the record itself must still serve (generated_at, notes) — only the text is withheld"
    assert item["analysis"] is None


def test_integrator_digest_passes_a_public_register_weekly_text():
    fake = FakeDdbTable(rows=[_integrator_item(_PUBLIC_OK)])
    item = S._integrator_digest(_g={"table": fake})
    assert item["analysis"] == _PUBLIC_OK


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCER + FRONT-END WIRING
# ══════════════════════════════════════════════════════════════════════════════


def test_public_summary_is_in_the_extraction_and_recondense_contracts():
    assert "public_summary" in EXTRACTION_SYSTEM_PROMPT
    assert "public_summary" in coach_derived_prose.RECONDENSE_SYSTEM_PROMPT


def test_public_summary_is_grounded_and_held_with_the_derived_prose_set():
    assert "public_summary" in coach_derived_prose.DERIVED_PROSE_FIELDS
    # The ADR-104 gate grades prose_blob — the public field must be inside it.
    assert coach_derived_prose.prose_blob({"public_summary": "Matthew held his streak."}) == "Matthew held his streak."
    held = coach_derived_prose.hold({"public_summary": _PUBLIC_OK, "observatory_summary": "x"})
    assert held["public_summary"] is None and held["observatory_summary"] is None


def test_public_summary_never_joins_the_owner_register_serving_preference():
    # served_summary() feeds the profile roster, the Panel podcast and the daily
    # reflection — all owner/coach-register surfaces. The public field must not
    # outrank (or leak into) that chain, and the chain must not leak into public
    # serving: the registers stay separate by construction.
    assert "public_summary" not in coach_derived_prose.SERVED_SUMMARY_PREFERENCE


def test_the_writer_persists_public_summary_through_the_guard():
    path = os.path.join(_REPO, "lambdas", "coach", "coach_state_updater.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert (
        'audience_guard.reader_safe(extraction.get("public_summary")' in src
    ), "the write-side seam is gone — an unguarded public_summary write path"


def test_the_board_front_end_renders_only_the_public_read():
    path = os.path.join(_REPO, "site", "assets", "js", "evidence.js")
    with open(path, encoding="utf-8") as fh:
        js = fh.read()
    assert "an.public_read" in js, "the board detail no longer renders the public-audience field"
    assert "an && an.analysis" not in js, "the board detail fell back to the coaching register (an.analysis) — the #2972 defect shape"


def test_dashboard_read_path_has_no_owner_channel_fallback():
    path = os.path.join(_REPO, "lambdas", "web", "site_api_lambda.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    assert "audience_guard.public_blurb" in src
    assert 'truncate_at_word(_cd_out_item.get("content"' not in src, "the content fallthrough is back on the public blurb slot"
    assert 'truncate_at_word(_cd_out_item.get("observatory_summary"' not in src
