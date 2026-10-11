"""#4191 — the chronicle's bracketed machine header is the model's wire format, never a
stored artifact and never read to a reader.

The mechanism this pins, reproduced 2026-10-04 before the fix: the Story Desk (#4535) hands
the writer an envelope whose header is ``[Day 4 to Day 10 · 318.9 lbs (…) · 7 training
sessions]``. It carries no ``Weight:``, and three strips keyed on that word let it through —
the store kept it in ``content_markdown``, the recall card's snippet clean left it at the
head of the quote, and the podcast narration read it aloud. The fix is at the one store
chokepoint (``chronicle_store.store_installment``): the header is dropped, the numbers
travel as ``stats_line`` plus a structured ``stats`` map.
"""

import os
import sys
from decimal import Decimal

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "emails")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import logging  # noqa: E402

import chronicle_store  # noqa: E402
from content import chronicle_schema as cs  # noqa: E402

_BODY = "Sunday morning in Seattle, the scale said something new.\n\n[He wrote one line in brackets.]\n\n---\n*Week 2 of The Measured Life*"
_LEGACY_LINE = "Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days"
_DESK_LINE = "Day 4 to Day 10 · 318.9 lbs (-8.4 this week) · 7 training sessions"
_LEGACY = f'"The Silence and the Signal"\n\n[{_LEGACY_LINE}]\n\n{_BODY}'
_DESK = f'"The Volume Problem"\n\n[{_DESK_LINE}]\n\n{_BODY}'


class _Table:
    def __init__(self):
        self.puts = []

    def put_item(self, **kw):
        self.puts.append(kw["Item"])


_ARCHIVED: list = []


def _store(raw, title, stats_line):
    from common import qa_archive

    table = _Table()
    real = qa_archive.archive_text
    qa_archive.archive_text = lambda kind, text, **kw: _ARCHIVED.append(text)  # never reach S3 from a test
    try:
        return _store_with(table, raw, title, stats_line)
    finally:
        qa_archive.archive_text = real


def _store_with(table, raw, title, stats_line):
    ok = chronicle_store.store_installment(
        "2026-09-15",
        2,
        title,
        stats_line,
        raw,
        "<p>body</p>",
        [],
        False,
        _g={"table": table, "USER_ID": "matthew", "logger": logging.getLogger("t4191")},
    )
    assert ok is True
    return table.puts[0]


def test_the_stored_markdown_carries_no_bracketed_header_for_either_writer():
    for raw, title, line in ((_LEGACY, "The Silence and the Signal", _LEGACY_LINE), (_DESK, "The Volume Problem", _DESK_LINE)):
        assert f"[{line}]" in raw  # mutation control: the envelope the writer is handed DOES carry it
        item = _store(raw, title, line)
        md = item["content_markdown"]
        assert f"[{line}]" not in md and "[Weight:" not in md and "[Day " not in md
        assert md == f'"{title}"\n\n{_BODY}'  # the shape the season rebuild already stores
        assert "[He wrote one line in brackets.]" in md  # a bracketed line in the BODY is prose
        assert item["stats_line"] == line  # the field every card and manifest reads is untouched
        assert _ARCHIVED[-1] == md  # the generation-time archive holds what was stored, not the envelope


def test_the_numbers_travel_as_a_structured_field():
    legacy = _store(_LEGACY, "The Silence and the Signal", _LEGACY_LINE)["stats"]
    assert legacy == {"weight_lbs": Decimal("315.0"), "week_grade_avg": Decimal("74"), "t0_streak_days": 0}
    assert all(not isinstance(v, float) for v in legacy.values())  # boto3 rejects float
    # the desk's line has a weight and nothing else — absent keys, never invented zeros
    assert _store(_DESK, "The Volume Problem", _DESK_LINE)["stats"] == {"weight_lbs": Decimal("318.9")}
    # a line with no numbers of this kind stores no map at all
    assert "stats" not in _store(
        '"Before"\n\n[Prologue | Before Day 1 | Seattle, WA]\n\nBody.', "Before", "Prologue | Before Day 1 | Seattle, WA"
    )
    assert cs.stats_fields("Weight: — lbs | Week Grade: — | T0 Streak: —") == {}


def test_strip_stat_header_touches_only_the_header_slot():
    assert cs.strip_stat_header(_DESK) == f'"The Volume Problem"\n\n{_BODY}'
    assert cs.strip_stat_header(cs.strip_stat_header(_DESK)) == cs.strip_stat_header(_DESK)  # idempotent
    no_header = f'"The Volume Problem"\n\n{_BODY}'
    assert cs.strip_stat_header(no_header) == no_header
    assert cs.strip_stat_header(f"[{_DESK_LINE}]\n\n{_BODY}") == _BODY  # no title line
    assert cs.strip_stat_header("") == ""
    # the header slot is the line after the FIRST line only: a bracket two paragraphs in stays
    deep = '"T"\n\nOpening sentence.\n\n[A bracketed aside.]\n\nMore.'
    assert cs.strip_stat_header(deep) == deep


def test_a_recall_snippet_indexed_from_a_desk_envelope_opens_on_the_sentence():
    snip = f'The Volume Problem Week 2 of The Measured Life "The Volume Problem" [{_DESK_LINE}] Sunday morning in Seattle, the scale'
    assert cs.clean_snippet(snip) == "Sunday morning in Seattle, the scale"
    cut = f'The Volume Problem Week 2 of The Measured Life "The Volume Problem" [{_DESK_LINE[:30]}'
    assert cs.clean_snippet(cut) == ""  # the storage cap cut inside the bracket
    # without the envelope head there is no header slot: a leading bracket is the reader's prose
    assert cs.clean_snippet("[An aside.] Then a sentence.") == "[An aside.] Then a sentence."


def test_the_podcast_never_reads_the_header_aloud():
    import chronicle_podcast_lambda as pod

    for raw, line in ((_LEGACY, _LEGACY_LINE), (_DESK, _DESK_LINE)):
        spoken = pod._markdown_to_narration(raw)
        assert line not in spoken and "training sessions" not in spoken and "T0 Streak" not in spoken
        assert "Sunday morning in Seattle" in spoken
