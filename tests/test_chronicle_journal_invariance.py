"""tests/test_chronicle_journal_invariance.py — the public chronicle's generators never see journal activity.

Owner ruling 2026-11-05: "Apply the same privacy rules to the full Chronicle ... Remove or revise explicit
journal-activity disclosures." The installments that disclosed it were written from two packets:
``emails.chronicle_data`` (the Wednesday writer, the Panel podcast, the fallback writer) fed the journal's
text, its signals, a "no journal entries this week" line, the State of Mind check-ins and their absence; and
``content.story_dossier`` (the Story Desk) fed an entry count with a caveat about journal presence. Both are
public generators' inputs, so the fix is at the input, through the policy modules:
``common.narrative_provenance`` (the journal and State of Mind families are PRIVATE) and
``common.activity_publication`` (the journal habits are private activity; habits classify by identity).

The check is INVARIANCE, not a keyword list: build each packet over the same week, vary ONLY journal inputs
(entries and their text, the mood check-ins on the apple_health row, the journal habits' statuses and the
stored tier counts that include them, the engagement record's private channels), and the packet must be
byte-identical. A keyword list would pass a paraphrase; an invariance check cannot be paraphrased past.

The mutation controls prove the check can fail: a builder that leaks the entry count, and the real builder
with the habit policy switched off, are both caught by the same helper.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from decimal import Decimal

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import test_story_dossier_4532 as dossier_fixture  # noqa: E402 — the dossier's wire-shaped fake table
from common import (
    activity_publication as ap,  # noqa: E402
    narrative_provenance as NP,  # noqa: E402
)
from content import story_dossier  # noqa: E402
from emails import chronicle_data as cd  # noqa: E402

GENESIS = "2026-08-03"
JOURNAL_IDS = {name: hid for hid, (name, fam) in ap.HABIT_FAMILIES.items() if fam == "journal_presence"}
PUBLIC_IDS = sorted(ap.PUBLIC_HABIT_IDS)[:3]
PUBLIC_HABITS = dict(zip(("Walk", "Protein Breakfast", "Lights Out"), PUBLIC_IDS))


# ── the Wednesday packet ─────────────────────────────────────────────────────────────────


def _registry():
    reg = {n: {"tier": Decimal("1"), "status": "active"} for n in JOURNAL_IDS}
    reg.update({n: {"tier": Decimal("0"), "status": "active"} for n in PUBLIC_HABITS})
    return reg


def _statuses(journal_state):
    st = {n: {"habit_id": i, "status": "completed", "group": "Movement", "scheduled_today": True} for n, i in PUBLIC_HABITS.items()}
    if journal_state is not None:
        st.update({n: {"habit_id": i, "status": journal_state, "group": "Growth", "scheduled_today": True} for n, i in JOURNAL_IDS.items()})
    return st


def _week(journal):
    """One week of public data; `journal` decides ONLY the journal inputs."""
    days = ["2026-08-05", "2026-08-06", "2026-08-07"]
    wrote = journal["wrote"]
    data = {
        "profile": {"journey_start_date": GENESIS, "habit_registry": _registry()},
        "dates": {"start": "2026-08-05", "end": "2026-08-11"},
        "whoop": {d: {"recovery_score": Decimal("71"), "hrv": Decimal("48"), "sleep_duration_hours": Decimal("7.4")} for d in days},
        "eightsleep": {},
        "garmin": {},
        "strava": {
            "2026-08-06": {"activities": [{"name": "Walk", "sport_type": "Walk", "moving_time_seconds": 3600, "distance_meters": 5200}]}
        },
        "withings": {"2026-08-05": {"weight_lbs": Decimal("318.4")}, "2026-08-11": {"weight_lbs": Decimal("316.9")}},
        "macrofactor": {d: {"total_calories_kcal": Decimal("1520"), "total_protein_g": Decimal("172")} for d in days},
        # the mood check-ins ride on the apple_health row as som_* fields
        "apple_health": {
            d: {
                "steps": Decimal("7400"),
                **({"som_avg_valence": Decimal("-0.4"), "som_top_labels": "SYNTHETIC-MOOD"} if journal["mood"] else {}),
            }
            for d in days
        },
        "day_grades": {d: {"total_score": Decimal("74"), "letter_grade": "C"} for d in days},
        # the stored tier counts include the journal habits: a written day moves tier1_done
        "habit_scores": {
            d: {
                "tier0_done": 3,
                "tier0_total": 3,
                "tier1_done": 2 if wrote else 0,
                "tier1_total": 2,
                "vices_held": 2,
                "vices_total": 2,
                "missed_tier0": [] if wrote else ["Morning Journal"],
            }
            for d in days
        },
        "habitify": {d: {"habit_statuses": _statuses(journal["habits"])} for d in days},
        "supplements": {},
        "experiments": [],
        "anomalies": {},
        "weather": {},
        "character_sheet": {},
        "prev_installments": [],
        "conversation_refs": [],
        "field_notes": None,
    }
    if journal["entries"]:
        data["journal_entries"] = [
            {
                "sk": f"DATE#{d}#journal#evening#{i}",
                "template": "evening",
                "raw_text": "SYNTHETIC-JOURNAL-TEXT",
                "enriched_mood": 2,
                "enriched_themes": ["SYNTHETIC-THEME"],
            }
            for i, d in enumerate(days)
        ]
        data["state_of_mind"] = {d: {"som_avg_valence": Decimal("-0.4")} for d in days}
    return data


JOURNAL_VARIANTS = [
    {"wrote": False, "entries": False, "mood": False, "habits": None},  # no journal anywhere
    {"wrote": False, "entries": False, "mood": False, "habits": "missed"},
    {"wrote": True, "entries": True, "mood": True, "habits": "completed"},  # wrote every day, checked in every day
    {"wrote": True, "entries": True, "mood": False, "habits": "completed"},
    {"wrote": False, "entries": False, "mood": True, "habits": "missed"},
]


def _distinct_packets(build, variants=JOURNAL_VARIANTS):
    """{packet text} over the journal-only variants — one element means the packet is journal-invariant."""
    return {build(_week(v))[0] for v in variants}


def test_the_wednesday_packet_is_byte_identical_whatever_the_journal_holds():
    packets = _distinct_packets(cd.build_data_packet)
    assert len(packets) == 1, "the public chronicle packet moved with journal-only inputs"
    (text,) = packets
    for needle in ("SYNTHETIC-JOURNAL-TEXT", "SYNTHETIC-THEME", "SYNTHETIC-MOOD", "Morning Journal", "Evening Journal"):
        assert needle not in text
    assert "journal" not in text.lower()
    # the public picture is still there: public habits, the week's numbers
    assert "=== HABIT PERFORMANCE ===" in text and "T0 3/3" in text and "Vices 2/2" in text
    assert "T1 " not in text  # the tier that holds a journal habit carries no count at all


def test_mutation_control_a_packet_that_leaks_the_entry_count_is_caught():
    def leaky(data):
        text, n = cd.build_data_packet(data)
        return text + f"\nentries: {len(data.get('journal_entries') or [])}", n

    assert len(_distinct_packets(leaky)) > 1


def test_mutation_control_switching_off_the_habit_policy_is_caught(monkeypatch):
    monkeypatch.setattr(ap, "habit_is_public", lambda *a, **k: True)
    monkeypatch.setattr(ap, "habit_family", lambda *a, **k: ap.PUBLIC_HABIT_FAMILY)
    assert len(_distinct_packets(cd.build_data_packet)) > 1


def test_the_families_the_packet_omits_are_private_in_the_policy():
    """The packet omits these because the policy says PRIVATE. If the owner ever publishes one, the omission
    becomes a decision to revisit, not a silent drift."""
    for fam in ("notion", "journal", "journal_presence", "state_of_mind", "mood_read"):
        assert NP.classify(fam) == NP.PRIVATE, fam
    for name in JOURNAL_IDS:
        assert ap.habit_family(name) == "journal_presence"


# ── the gather and the presence block ───────────────────────────────────────────────────


class _Table:
    def __init__(self, items=None):
        self.items = items or {}

    def get_item(self, Key, **_):
        return {"Item": self.items.get((Key["pk"], Key["sk"]))} if (Key["pk"], Key["sk"]) in self.items else {}

    def query(self, **_):
        return {"Items": []}


def test_the_gather_never_reads_the_journal_partition(monkeypatch):
    calls = []

    def q(source, s, e):
        calls.append(source)
        return {}

    def ql(source, s, e):
        calls.append(source)
        return [{"sk": "DATE#2026-08-06#journal#evening#a", "raw_text": "SYNTHETIC-JOURNAL-TEXT"}]

    class _Log:
        def info(self, *a, **k):
            pass

        warning = error = info

    g = {
        "query_range": q,
        "query_range_list": ql,
        "fetch_profile": lambda: {"journey_start_date": GENESIS},
        "table": _Table(),
        "USER_ID": "matthew",
        "USER_PREFIX": "USER#matthew#SOURCE#",
        "EXPERIMENT_START_DATE": GENESIS,
        "logger": _Log(),
    }
    out = cd.gather_chronicle_data(_g=g)
    assert "notion" not in calls
    assert "SYNTHETIC-JOURNAL-TEXT" not in repr(out)


def test_the_presence_signal_moves_only_with_public_channels():
    """Two engagement records that differ only in a private channel's quiet stretch give the chronicle the
    same signal; the mutation control (the full record) does not."""
    pk = ("USER#matthew#SOURCE#engagement_state", "STATE#current")
    public = {"presence_class": "present", "gap_days": Decimal("0")}
    quiet_private = {"presence_class": "quiet", "quiet_channels": ["journal"], "gap_days": Decimal("9"), "public": dict(public)}
    all_present = {"presence_class": "present", "quiet_channels": [], "gap_days": Decimal("0"), "public": dict(public)}

    def sig(rec):
        g = {"table": _Table({pk: rec}), "USER_PREFIX": "USER#matthew#SOURCE#", "logger": None}
        return cd._load_engagement_signal(_g=g)

    assert sig(quiet_private) == sig(all_present) == public
    assert quiet_private != all_present  # the control: the full records do differ


# ── the Story Desk's dossier ─────────────────────────────────────────────────────────────


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(story_dossier, "load_prereg", lambda: {})
    story_dossier._PLAN_FACTS_CACHE.clear()
    yield
    story_dossier._PLAN_FACTS_CACHE.clear()


def _dossier_rows(journal):
    rows = dossier_fixture._wire_rows(False)
    public_status = {
        n: {"habit_id": i, "status": "completed", "group": "Movement", "scheduled_today": True} for n, i in PUBLIC_HABITS.items()
    }
    for r in rows:
        src = r.get("source")
        d = r.get("date")
        if src == "habitify":
            st = dict(public_status)
            if journal["habits"] is not None:
                st.update(
                    {
                        n: {"habit_id": i, "status": journal["habits"], "group": "Growth", "scheduled_today": True}
                        for n, i in JOURNAL_IDS.items()
                    }
                )
            r["habit_statuses"] = st
        elif src == "habit_scores":
            r["missed_tier0"] = ["Morning Journal"] if not journal["wrote"] else []
        elif src == "apple_health" and journal["mood"]:
            r["som_avg_valence"] = Decimal("-0.4")
            r["som_top_labels"] = "SYNTHETIC-MOOD"
        if journal["entries"] and src == "whoop" and r["sk"] == f"DATE#{d}":
            rows_extra = {
                "pk": "USER#matthew#SOURCE#notion",
                "sk": f"DATE#{d}#journal#evening#{d}",
                "date": d,
                "source": "notion",
                "raw_text": "SYNTHETIC-JOURNAL-TEXT",
            }
            r.setdefault("_extra", rows_extra)
    extra = [r.pop("_extra") for r in rows if "_extra" in r]
    return rows + extra


def _dossier(journal):
    d, _nye = story_dossier.week_dossier(dossier_fixture.FakeTable(_dossier_rows(journal)), dict(dossier_fixture.WEEK3))
    return json.dumps(d, sort_keys=True, default=str)


def test_the_story_desk_dossier_is_byte_identical_whatever_the_journal_holds(no_network):
    dossiers = {_dossier(v) for v in JOURNAL_VARIANTS}
    assert len(dossiers) == 1, "the Story Desk dossier moved with journal-only inputs"
    (text,) = dossiers
    for needle in ("SYNTHETIC-JOURNAL-TEXT", "SYNTHETIC-MOOD", "Morning Journal", "Evening Journal", "entries_in_window"):
        assert needle not in text
    assert '"journal"' not in text and "journal" not in text.lower()


def test_mutation_control_the_dossier_check_catches_a_journal_habit_let_through(no_network, monkeypatch):
    monkeypatch.setattr(ap, "habit_is_public", lambda *a, **k: True)
    assert len({_dossier(v) for v in JOURNAL_VARIANTS}) > 1


def test_the_dossier_and_packet_sources_name_no_journal_read():
    """A structural backstop for the two read paths the invariance check cannot vary: neither module may
    query the journal partition again."""
    for rel in ("lambdas/content/story_dossier.py", "lambdas/emails/chronicle_data.py"):
        src = open(os.path.join(_REPO, rel), encoding="utf-8").read()
        assert "SOURCE#notion" not in src, rel
        assert 'query_range_list("notion"' not in src and 'query_range("notion"' not in src, rel
        assert "som_avg_valence" not in src, rel


def test_the_fixture_variants_really_differ():
    """The invariance is only meaningful if the variants differ where the journal lives."""
    weeks = [_week(v) for v in JOURNAL_VARIANTS]
    assert len({json.dumps(w, sort_keys=True, default=str) for w in weeks}) == len(JOURNAL_VARIANTS)
    rows = [_dossier_rows(v) for v in JOURNAL_VARIANTS]
    assert len({json.dumps(r, sort_keys=True, default=str) for r in rows}) == len(JOURNAL_VARIANTS)
    assert copy.deepcopy(weeks[0]) == weeks[0]
