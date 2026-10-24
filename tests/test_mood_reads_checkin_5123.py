"""tests/test_mood_reads_checkin_5123.py — the mood read falls back to the evening check-in, owner channel only (#5123).

Pins: journal-rich, journal-dark and both-dark days; the named source on every read; the published orchestrator
brief never carries the owner-only check-in (fail-closed), and the owner's Telegram mind thread never carries the
check-in word or journal text.
"""

import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_narrative_orchestrator as orch  # noqa: E402
from coach import coach_domain_facts as cdf  # noqa: E402
from health import mood_read as mr  # noqa: E402

TODAY = "2026-10-24"


def _journal(n, mood=3.0):
    return [
        {
            "pk": mr.JOURNAL_PK,
            "sk": f"DATE#2026-10-{10 + i:02d}#journal#evening",
            "date": f"2026-10-{10 + i:02d}",
            "enriched_at": "x",
            "enriched_mood": Decimal(str(mood)),
            "enriched_stress": Decimal("2"),
            "enriched_social_quality": "meaningful",
            "enriched_values_lived": ["honesty"],
            "enriched_notable_quote": "a line he wrote",
        }
        for i in range(n)
    ]


def _checkins(stresses, word="exhausted"):
    return [
        {
            "pk": mr.CHECKIN_PK,
            "sk": f"DATE#2026-10-{10 + i:02d}",
            "date": f"2026-10-{10 + i:02d}",
            "stress": Decimal(s),
            "hunger": Decimal(2),
            "cravings": Decimal(1),
            "word": word,
        }
        for i, s in enumerate(stresses)
    ]


class Table:
    def __init__(self, journal=(), checkins=(), fail=False):
        self.rows = {mr.JOURNAL_PK: list(journal), mr.CHECKIN_PK: list(checkins)}
        self.fail, self.pks = fail, []

    def query(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        pk = kw["ExpressionAttributeValues"][":pk"]
        self.pks.append(pk)
        lo, hi = kw["ExpressionAttributeValues"][":lo"], kw["ExpressionAttributeValues"][":hi"]
        return {"Items": [r for r in self.rows.get(pk, []) if lo <= r["sk"] <= hi]}


# ── the three days ─────────────────────────────────────────────────────────────────────────────────


def test_journal_rich_day_reads_the_journal_and_ignores_the_checkin():
    read = mr.resolve(_journal(6), _checkins([4, 4, 4, 4, 4, 4]))
    assert read["source"] == "journal"
    assert read["entries_analyzed"] == 6 and read["mood_trend"]["avg"] == 3.0
    assert "evenings_answered" not in read


def test_journal_dark_day_falls_back_to_the_checkin_and_says_so():
    read = mr.resolve(_journal(2), _checkins([1, 1, 1, 3, 3, 3]))
    assert read["source"] == "evening_checkin"
    assert read["journal_scored_entries"] == 2 and read["evenings_answered"] == 6
    assert read["stress_trend"] == {"direction": "rising", "avg": 2.0, "delta": 2.0, "n": 6}
    # The check-in asks nothing about mood, connection or flourishing: absent with the reason, never borrowed.
    assert read["mood_trend"] is None and read["social_quality"] is None and read["flourishing"] is None
    assert "nothing about this" in read["not_measured"]
    assert "word" not in read and "exhausted" not in repr(read)


def test_both_dark_reports_unavailable_never_a_default_number():
    read = mr.resolve(_journal(2), _checkins([2, 2]))
    assert read["source"] == "unavailable"
    assert read["journal_scored_entries"] == 2 and read["checkin_stress_evenings"] == 2
    assert not {"mood_trend", "stress_trend", "social_quality_distribution", "flourishing"} & set(read)
    (line,) = mr.owner_lines(read)
    assert line.startswith("Mood read: unavailable") and "do not supply one" in line
    assert mr.resolve([], [])["source"] == "unavailable"


def test_a_checkin_without_enough_stress_ratings_is_not_a_fallback():
    rows = _checkins([2, 2, 2, 2, 2, 2])
    for r in rows[2:]:
        del r["stress"]
    assert mr.resolve([], rows)["source"] == "unavailable"


# ── the published path (the orchestrator brief is served on the site) ───────────────────────────────


def test_published_path_has_no_checkin_door_and_drops_an_owner_only_read():
    import inspect

    assert list(inspect.signature(mr.published_signal).parameters) == ["journal_entries", "window_days"]
    assert mr.for_published(mr.resolve(_journal(2), _checkins([1, 1, 1, 3, 3, 3]))) is None
    assert mr.for_published({"source": "unavailable"}) is None
    assert mr.for_published({"source": "something_new"}) is None  # fail-closed on an unknown source
    assert mr.for_published(mr.resolve(_journal(6), []))["source"] == "journal"


def test_orchestrator_brief_never_carries_the_checkin_and_names_its_journal_source():
    assert orch._journal_mood_for_brief(mr.resolve(_journal(2), _checkins([1, 1, 1, 3, 3, 3]))) is None
    out = orch._journal_mood_for_brief(mr.resolve(_journal(6), []))
    assert out["source"] == "journal" and out["entries_analyzed"] == 6
    legacy = orch._journal_mood_for_brief({"mood_trend": {}, "stress_trend": {}})  # a pre-#5123 cached signal
    assert legacy["source"] == "journal"


def test_orchestrator_gather_reads_only_the_journal(monkeypatch):
    seen = []

    class T:
        def query(self, **kw):
            seen.append(kw)
            return {"Items": _journal(6)}

    monkeypatch.setattr(orch, "table", T())
    signal = orch._gather_journal_mood_signal()
    assert signal["source"] == "journal"
    assert len(seen) == 1 and "evening_checkin" not in repr(seen)


# ── the owner channel (his Telegram mind thread) ───────────────────────────────────────────────────


def test_owner_read_falls_back_and_the_lines_never_carry_the_word_or_journal_text():
    table = Table(journal=_journal(1), checkins=_checkins([1, 1, 1, 3, 3, 3]))
    read = mr.owner_read(table, TODAY)
    assert read["source"] == "evening_checkin"
    assert set(table.pks) == {mr.JOURNAL_PK, mr.CHECKIN_PK}
    text = "\n".join(mr.owner_lines(read))
    assert "the evening check-in" in text and "Reported stress: rising" in text
    assert "exhausted" not in text and "a line he wrote" not in text


def test_owner_read_journal_rich_carries_flourishing_through_the_one_aggregate():
    read = mr.owner_read(Table(journal=_journal(6), checkins=_checkins([4] * 6)), TODAY)
    assert read["source"] == "journal"
    assert read["flourishing"]["values_lived_count"] == 1 and read["flourishing"]["social_quality_score"] == 6.67
    text = "\n".join(mr.owner_lines(read))
    assert "his journal (6 entries" in text and "Flourishing in the journal" in text
    assert "a line he wrote" not in text  # the notable quote stays on the journal path's own gate


def test_owner_read_failure_is_an_honest_absence():
    assert mr.owner_read(Table(fail=True), TODAY) is None
    assert "could not be read" in mr.owner_lines(None)[0]


def test_the_mind_thread_gets_the_pack():
    assert cdf._PACKS["mind"] is cdf._mind_pack
    assert cdf._persona_id("mind_coach")[0] == "mind"
    lines = cdf._mind_pack(Table(checkins=_checkins([2] * 5)), TODAY)
    assert lines[0].startswith("Mood read source: the evening check-in")
