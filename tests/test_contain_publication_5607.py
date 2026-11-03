"""tests/test_contain_publication_5607.py — no public route serves the coaches' owner-register
weekly analysis or their private confidence posteriors (#5607, owner ruling 2026-11-03,
item 5: "withhold owner-register /api/ai_analysis prose pending a reviewed public version,
and remove private stance-confidence posteriors from public responses").

THE SET, NOT THE INSTANCE. `tests/contain_publication_route_walk.py`, in a fresh
interpreter, calls EVERY site-API GET route (ROUTES + _SIMPLE_ROUTES + the inline
`_dispatch_route` branches, plus each /api/coach/<id>, /api/ai_analysis?expert=,
/api/coach_analysis?domain= and /api/coach_timeline?coach_id=) against a table holding the
ai_analysis EXPERT# rows, each coach's STANCE# rows and CONFIDENCE# Beta row, and an open
docket bet, all at their real keys with sentinel prose and a posterior-shaped number. No
response may carry a sentinel, the number, or a posterior-named key; /api/ai_analysis may
carry none of its four prose keys.

Mutation control: `--plant` re-adds each removed field (the prose on /api/ai_analysis,
`confidence_note` on the stance, the stake `confidence` on the docket) — the walk must red
on every one. Run against the pre-#5607 handlers (origin/main f7eddb2ce) the clean walk
reds on the same routes, recorded in the PR.

What stays public, deliberately: a ledger row's own `confidence` (the number a call was
filed at, which its Brier score is computed from) is part of the graded record, not a
private posterior — /api/ledger_export, /api/predictions and /api/calls are not touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "contain_publication_route_walk.py"), *args],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_no_public_route_serves_the_analysis_prose_or_a_confidence_posterior():
    out = _walk()
    # Non-vacuity: the walk reached the router and the handlers really read these rows.
    assert out["routes"] >= 100 and out["answered"] >= out["routes"] - 5, out
    assert out["unparsed_queries"] == 0, "a query the fixture table could not read — a blind spot"
    seen = out["seen"]
    assert any(r.startswith("/api/coach/") for r in seen.get("STANCEREADSENTINEL", [])), "the stance was never served — the walk is blind"
    assert "/api/coach_docket" in seen.get("0.271828", []), "the docket stake was never served — the walk is blind"
    for key, body in seen.items():
        if key.startswith("/api/ai_analysis"):
            assert body == {"state": "withheld", "data_through": "2026-10-31"}, (key, body)
    assert out["leaks"] == {}, f"routes serving owner-register prose or a private posterior: {out['leaks']}"


def test_the_walk_catches_each_removed_field_when_it_is_re_added():
    """Mutation control: each of the three removals reverted, one walk."""
    leaks = _walk("--plant")["leaks"]
    assert "key:analysis" in leaks.get("/api/ai_analysis?expert=explorer", []), leaks
    assert "AIPROSESENTINEL" in leaks.get("/api/ai_analysis", []), leaks
    assert "key:confidence_note" in leaks.get("/api/coach/explorer_coach", []), leaks
    assert "0.123457" in leaks.get("/api/coach_docket", []), leaks


def test_the_withheld_body_carries_dates_and_counts_only():
    """The kept fields are the fact that a private analysis exists and when — never words."""
    from web import site_api_coach_narrative as N

    item = {
        "analysis": "Your week",
        "key_recommendation": "Sleep earlier",
        "journaling_prompt": "What did you notice?",
        "elena_quote": "He held",
        "generated_at": "2026-11-02T10:00:00+00:00",
        "data_through": "2026-11-01",
        "week_number": 9,
        "days_in_experiment": 58,
    }
    body = N._ai_analysis_withheld("explorer", item)
    assert set(body) == {"expert_key", "state", "reason", "generated_at", "data_through", "week_number", "days_in_experiment"}
    assert body["state"] == "withheld" and body["reason"] == N.AI_ANALYSIS_WITHHELD_REASON
    assert not set(N.AI_ANALYSIS_PROSE_FIELDS) & set(body)
    assert set(N._ai_analysis_withheld("mind")) == {"expert_key", "state", "reason", "generated_at", "data_through"}


def test_the_owner_side_keeps_the_records():
    """Containment is at the public read, never the producer: the analyzer still writes the
    prose and the stance writer still asks for its confidence note (the owner's tools read both)."""
    analyzer = (ROOT / "lambdas" / "intelligence" / "ai_expert_analyzer_lambda.py").read_text(encoding="utf-8")
    summarizer = (ROOT / "lambdas" / "coach" / "coach_history_summarizer.py").read_text(encoding="utf-8")
    assert '"analysis"' in analyzer and "journaling_prompt" in analyzer
    assert '"confidence_note"' in summarizer


# premerge-gate: #5607: a route walk of every /api/* GET handler — no public route serves the owner-register ai_analysis prose or a coach's CONFIDENCE# posterior (stance confidence_note, docket stake confidence)
