#!/usr/bin/env python3
"""demo_development_profile.py — #6294: a full private development profile, assembled from in-memory data.

The subject is fictional and every record is synthetic (the repo is public). The data is built so that each kind of
reading appears at least once:

  physical capacity        measured: three lifts up and more zone 2 minutes per observed week -> improving
  behavioural consistency  measured: training days steady, habit completion up, a sick week excluded -> improving
  learning                 counted: more experiments and answered advice than the window before -> improving
  self-understanding       counted: two views on hypotheses, below the margin -> not_enough_to_say; one open
                           hypothesis listed as an open question, not evidence
  emotional wellbeing      his own ratings: mood up, stress up -> mixed (an AI interpretation planted beside them
                           and a model score on unrated entries change nothing)
  social connection        his statements point both ways -> mixed, both shown
  meaning, confidence,     one or two statements, or none -> not_enough_to_say (the honest result)
  coping

It prints every domain's status, basis, evidence and what was not observed, then checks the invariants: no domain
reads harder from missing data, no roll-up key, and the planted interpretation is not evidence.

Pure: no AWS client is created. Usage:  python3 scripts/demo_development_profile.py   (exit 0 when the checks hold)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ.pop("AWS_PROFILE", None)
sys.path[:0] = [os.path.join(_REPO, "lambdas"), _REPO]

from health import development_profile as dp  # noqa: E402

TODAY = "2027-03-31"
T = date.fromisoformat(TODAY)


def d(ago: int) -> str:
    return (T - timedelta(days=ago)).isoformat()


def record(ago: int, domain: str, direction: str, text: str, kind: str = "owner_statement") -> dict:
    return {
        "sk": f"MEMORY#personal_record#{d(ago)}#demo{ago:06d}",
        "category": "personal_record",
        "summary": text,
        "evidence_kind": kind,
        "event_date": d(ago),
        "event_date_precision": "day",
        "owner_reviewed_at": f"{d(ago)}T20:00:00+00:00",
        "life_domains": [domain],
        "life_direction": direction,
    }


def build() -> dict:
    days = range(56)
    sick = [d(a) for a in range(14, 19)]
    zone2 = [{"date": d(a), "minutes": 35} for a in days if a % 7 < (4 if a < 28 else 3)]
    training = sorted({z["date"] for z in zone2} | {d(a) for a in days if a % 7 == 5})
    lifts = []
    for name, prior, recent in (("Demo Press", 120, 126), ("Demo Row", 150, 158), ("Demo Hinge", 200, 211)):
        lifts += [{"date": d(40), "identity": name, "name": name, "best_e1rm_lb": prior}]
        lifts += [{"date": d(6), "identity": name, "name": name, "best_e1rm_lb": recent}]
    social = [
        record(4, "social_connection", "better", "Calmer on the days I go to the community garden."),
        record(12, "social_connection", "harder", "Skipped the Friday dinner; felt cut off afterwards."),
        record(30, "social_connection", "same", "A normal week with the neighbours."),
        record(100, "social_connection", "same", "Saw the old team once."),
        record(110, "social_connection", "same", "Phone call with a cousin."),
        record(130, "social_connection", "better", "Joined the garden rota."),
    ]
    others = [
        record(20, "meaning_and_fulfilment", "better", "Teaching the new volunteer felt worthwhile."),
        record(25, "confidence_and_agency", "better", "Asked for the schedule change and got it."),
        # planted: a model's reading, tagged by mistake — never evidence (the write path would refuse the tag)
        record(3, "emotional_wellbeing", "harder", "The model thinks he is withdrawing.", kind="ai_interpretation"),
    ]
    journal = [{"date": d(a), "morning_mood": 4 if a < 28 else 3, "stress_level": 3 if a < 28 else 2} for a in days if a % 3 == 0]
    journal += [{"date": d(a), "enriched_mood": 1} for a in days]  # unrated entries carrying only a model score
    return {
        "observed_days": [d(a) for a in days],
        "excluded_days": {"sick": sick, "travel": []},
        "zone2_sessions": zone2,
        "training_days": training,
        "lift_sessions": lifts,
        "weight": [{"date": d(a), "weight_lbs": 180.0} for a in (2, 9, 33, 47)],
        "habit_days": [{"date": d(a), "completion_pct": 0.85 if a < 28 else 0.7} for a in days],
        "experiments": [{"experiment_id": f"e{i}", "start_date": d(5 + 7 * i), "end_date": None, "status": "active"} for i in range(5)]
        + [{"experiment_id": "old", "start_date": d(70), "end_date": d(60), "status": "completed"}],
        "recommendations": [{"response": "accepted", "response_recorded_at": f"{d(9)}T08:00:00Z", "outcome": None}],
        "decisions": [],
        "hypotheses": [
            {
                "hypothesis_id": "ph_000000demo1",
                "question": "Why does the demo subject sleep worse on garden days?",
                "status": "exploratory",
                "open": True,
                "history": [{"kind": "owner_view", "view": "correct", "recorded_at": f"{d(8)}T08:00:00Z"}],
            },
            {
                "hypothesis_id": "ph_000000demo2",
                "question": "Is the Friday skip about the venue?",
                "status": "exploratory",
                "open": False,
                "history": [{"kind": "owner_view", "view": "reject", "recorded_at": f"{d(11)}T08:00:00Z"}],
            },
        ],
        "personal_records": social + others,
        "journal_entries": journal,
        "evening_checkins": [],
        "profile_corrections": [
            {
                "sk": f"CORRECTION#{d(2)}#demo0001",
                "created_at": f"{d(2)}T19:00:00+00:00",
                "item_ref": {"surface": dp.PROFILE_SURFACE, "signal": dp.signal_for("social_connection")},
                "correction_text": "Mixed is right for this month.",
                "error_class": dp.AGREE_ERROR_CLASS,
            }
        ],
    }


def main() -> int:
    profile = dp.assemble_profile(build(), today=TODAY)
    print(f"DEVELOPMENT PROFILE (SYNTHETIC) as of {profile['as_of']} — no overall score; each domain stands alone")
    print(profile["reading_this"])
    for dom in profile["domains"]:
        print()
        print(f"[{dom['domain']}] {dom['name']}")
        print(f"  status: {dom['status']}   basis: {dom['basis']}")
        print(f"  why:    {dom['status_reason']}")
        for ev in dom["evidence"]:
            print(f"  - {ev.get('date')}  [{ev.get('evidence_kind')}] {ev.get('statement')}")
        for q in dom.get("open_questions") or []:
            print(f"  ? open question (not evidence): {q['question']}")
        for miss in dom["not_observed"]:
            print(f"  · not observed: {miss}")
        view = dom["last_owner_view"]
        print(f"  last view: {view['date'] + ' ' + view['view'] if view else '—'}")
        print(f"  disagree:  {json.dumps(dom['how_to_disagree']['arguments'])}")

    by = {x["domain"]: x for x in profile["domains"]}
    checks = {
        "physical capacity improving": by["physical_capacity"]["status"] == dp.IMPROVING,
        "behavioural consistency improving": by["behavioural_consistency"]["status"] == dp.IMPROVING,
        "learning improving": by["learning_and_experimentation"]["status"] == dp.IMPROVING,
        "self-understanding not enough": by["self_understanding"]["status"] == dp.NOT_ENOUGH,
        "emotional wellbeing mixed": by["emotional_wellbeing"]["status"] == dp.MIXED,
        "social connection mixed, both shown": by["social_connection"]["status"] == dp.MIXED
        and {"better", "harder"} <= {e.get("his_direction") for e in by["social_connection"]["evidence"]},
        "thin domains not enough": all(
            by[k]["status"] == dp.NOT_ENOUGH for k in ("meaning_and_fulfilment", "confidence_and_agency", "coping_and_flexibility")
        ),
        "the planted interpretation is not evidence": not any(
            e.get("evidence_kind") == "ai_interpretation" for x in profile["domains"] for e in x["evidence"]
        ),
        "no roll-up key": not any(k in profile for k in ("score", "overall", "level", "total")),
        "his view shown": (by["social_connection"]["last_owner_view"] or {}).get("view") == "agree",
    }
    print()
    for name, ok in checks.items():
        print(f"check: {name}: {'ok' if ok else 'FAILED'}")
    ok = all(checks.values())
    print("RESULT: PASS" if ok else "RESULT: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
