"""tests/test_chronicle_prologue_order_1988.py — #1988: the chronicle feed's "newest
first" list must not scramble same-date multi-part installments.

Root cause (measured against the live posts.json + DDB chronicle records, not
assumed from the issue text): publish_to_journal's manifest loop sorts
all_installments by `date` alone (`sorted(..., key=lambda x: x.get("date", ""),
reverse=True)`). Python's sort is stable, so two installments sharing a `date`
keep whatever relative order they arrived in from the all_installments list —
which is DDB scan/insertion order, not narrative part order. The real-world
trigger: a "rolling prologue" installment can be re-dated onto the eve of a new
genesis while KEEPING its original `sk` (e.g. Part II carries
date=2026-08-02 / sk=DATE#2026-07-21 after a restart re-anchor), so date-only
sorting can no longer disambiguate it from a same-date Part III whose sk equals
its date. The fix must tie-break by the SAME (date, sk)-derived sequence
ordinal already used to compute the "Prologue · Part N" label and the week-NN
URL (`_seq_for`) — not by insertion order — and expose it as an explicit
`sequence` field on each manifest record (AC1), consumed by story.js too.

This test also pins AC2: a Prologue-dated record's manifest `week` is always 0,
regardless of what raw `week_number` happens to be stored on the DDB item
(reconciles the live inconsistency: Part II carried week_number=1 while Parts
I/III carried 0 — nothing downstream should read a raw week off a Prologue
record; the genesis-anchored `label` is the only truthful series marker
pre-genesis).
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

from datetime import datetime, timedelta  # noqa: E402

import wednesday_chronicle_lambda as chron  # noqa: E402

_GENESIS = chron.EXPERIMENT_START_DATE


def _minus(days):
    return (datetime.strptime(_GENESIS, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


# Three prologue installments, dates derived from the live genesis constant (not
# hardcoded — a future restart re-anchors EXPERIMENT_START_DATE and this test must
# not become a wall-clock time bomb). Shape mirrors the ACTUAL live DDB records
# measured 2026-08-04: Part II was re-dated onto genesis-minus-1 by a restart but
# kept its original (older) sk; Part III's sk equals its own date.
_PART_I = {
    "title": "Before the Numbers",
    "week_number": 0,
    "date": _minus(6),
    "sk": f"DATE#{_minus(6)}",
    "stats_line": "Prologue",
    "word_count": 1242,
    "content_markdown": "Filed in the days before Day 1.",
    "has_board_interview": False,
}
_PART_II = {
    "title": "The Night Before Everything",
    "week_number": 1,  # the live inconsistency AC2 must reconcile
    "date": _minus(1),
    "sk": f"DATE#{_minus(13)}",  # re-dated by a restart; original authoring sk kept
    "stats_line": "Prologue",
    "word_count": 1129,
    "content_markdown": "The habit tracker logged a 2 out of 100.",
    "has_board_interview": True,
}
_PART_III = {
    "title": "The Plan, On the Record",
    "week_number": 0,
    "date": _minus(1),  # SAME date as Part II — the tie
    "sk": f"DATE#{_minus(1)}",
    "stats_line": "Prologue",
    "word_count": 1578,
    "content_markdown": "This morning a scale in a quiet bathroom recorded the first number.",
    "has_board_interview": False,
}


class _NoS3:
    """publish_to_journal(write_to_s3=False) never writes; it only reads
    generated/journal/posts.json to carry covers forward. Force that read to
    miss so the test is hermetic regardless of live AWS creds."""

    def get_object(self, *a, **k):
        raise RuntimeError("offline")


def _build_manifest(monkeypatch, all_installments, date_str, title, week_num=0):
    """Call publish_to_journal exactly like the live Wednesday publish does
    (DDB query order feeds `all_installments`; this loop only rebuilds the
    manifest from it) and return the parsed posts.json manifest list."""
    from content import editorial_image

    monkeypatch.setattr(chron, "s3", _NoS3())
    monkeypatch.setattr(editorial_image, "enabled", lambda: False)
    _post_key, _html, posts_json_str = chron.publish_to_journal(
        title=title,
        stats_line="Prologue",
        body_html="<p>body</p>",
        week_num=week_num,
        date_str=date_str,
        all_installments=all_installments,
        write_to_s3=False,
    )
    return json.loads(posts_json_str)["posts"]


def test_1988_same_date_parts_order_by_sequence_not_insertion_order(monkeypatch):
    """AC1 + regression guard: feed the installments in DDB scan order (Part III,
    then Part II, then Part I — the order a ScanIndexForward=False/ascending-sk
    query actually returns for this exact live shape), publishing Part III as the
    current post. "Newest first" must read Part III above Part II (the finale
    above the earlier same-date part), then Part I last.

    This is the case that fails against the PRE-FIX code: a bare
    `sorted(all_installments, key=lambda x: x.get("date", ""), reverse=True)`
    is stable, so a same-date tie keeps insertion order — Part II would stay
    above Part III as delivered here."""
    installments = [_PART_III, _PART_II, _PART_I]
    posts = _build_manifest(monkeypatch, installments, date_str=_PART_III["date"], title=_PART_III["title"])

    titles = [p["title"] for p in posts]
    assert titles == [
        "The Plan, On the Record",  # Part III — the finale, reads first
        "The Night Before Everything",  # Part II — same date, earlier part
        "Before the Numbers",  # Part I — earliest date
    ], titles


def test_1988_order_is_stable_even_if_the_scramble_arrives_the_other_way(monkeypatch):
    """Same three records, fed in the OPPOSITE same-date sub-order (Part II
    before Part III) to prove the fix reads the true part sequence rather than
    just reversing whatever order it was handed."""
    installments = [_PART_II, _PART_III, _PART_I]
    posts = _build_manifest(monkeypatch, installments, date_str=_PART_III["date"], title=_PART_III["title"])

    titles = [p["title"] for p in posts]
    assert titles[:2] == ["The Plan, On the Record", "The Night Before Everything"], titles


def test_1988_manifest_carries_an_explicit_sequence_field(monkeypatch):
    """AC1: each manifest record carries an explicit numeric `sequence` used as
    the tie-break, so story.js can apply the identical rule client-side."""
    posts = _build_manifest(monkeypatch, [_PART_III, _PART_II, _PART_I], date_str=_PART_III["date"], title=_PART_III["title"])
    by_title = {p["title"]: p for p in posts}
    assert isinstance(by_title["The Plan, On the Record"]["sequence"], int)
    assert isinstance(by_title["The Night Before Everything"]["sequence"], int)
    # the finale's sequence must sort ABOVE the earlier same-date part
    assert by_title["The Plan, On the Record"]["sequence"] > by_title["The Night Before Everything"]["sequence"]


def test_1988_prologue_week_field_reconciled_to_zero(monkeypatch):
    """AC2: a Prologue-dated record's manifest `week` is always 0 — never the raw
    (and, live, inconsistent) DDB week_number attribute."""
    posts = _build_manifest(monkeypatch, [_PART_III, _PART_II, _PART_I], date_str=_PART_III["date"], title=_PART_III["title"])
    for p in posts:
        assert p["week"] == 0, p


def test_1988_label_still_reads_part_ii_then_part_iii(monkeypatch):
    """Guard against a fix that reorders the list but breaks the pre-existing
    (already-correct) "Prologue · Part N" numbering."""
    posts = _build_manifest(monkeypatch, [_PART_III, _PART_II, _PART_I], date_str=_PART_III["date"], title=_PART_III["title"])
    by_title = {p["title"]: p["label"] for p in posts}
    assert by_title["The Night Before Everything"] == "Prologue · Part II"
    assert by_title["The Plan, On the Record"] == "Prologue · Part III"
    assert by_title["Before the Numbers"] == "Prologue · Part I"
