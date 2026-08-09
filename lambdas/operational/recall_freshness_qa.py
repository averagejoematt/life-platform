"""recall_freshness_qa.py — is the semantic-recall corpus still being written?

#1384 shipped a retrieval index whose only writer was an operator-run script. When the
runs stopped, nothing said so. Measured on the live table 2026-08-08: the newest embedded
installment was 2026-07-21 while a later, reader-visible week (2026-08-02) had published
and never been indexed — an 18-day gap that no alarm, no test and no dashboard reported,
because a retrieval index that stops growing does not error. It returns fewer precedents,
and fewer precedents is exactly what "there is no precedent" looks like. Under ADR-104
that is manufactured absence, and the whole point of the honest-numbers standard is that
the platform must not be able to produce it silently.

`recall_indexer` closes the write loop at publish time. This is the sensor that proves it
stayed closed — the pairing the platform keeps re-learning: the mechanism does the work,
a separate check proves the work happened. A hook with no detector is one silent
regression away from being the old outage again.

WHAT IT COMPARES. Every phase-visible chronicle installment should have a row in the
recall partition. The check names the specific missing dates rather than reporting a
count, because "3 missing" sends someone to query the table and a list does not.

WHY A BUDGET PAUSE IS NOT A FAILURE. Recall indexing is band-2 gated (ADR-125) — it
pauses with the reader narrative it decorates. At a paused tier the corpus is SUPPOSED to
stop advancing, so reporting red would train the reader of this report to ignore it, and
an accuracy gate that reds on honest data is worse than no gate. Paused reports ⏸ with
the reason, which is visible and is not a fault.

Split out of qa_smoke_lambda rather than appended to it: that module sits 2 lines under
the 1,200-line hard ceiling (#1665), and the established shape there is a cohesive
`operational/*_qa.py` module owning the logic while the handler owns the AWS clients and
the wiring — see `raw_archive_qa`, `weight_truth_qa`, `qa_check_outputs`.

Pure core (`missing_dates`, `assess`) — no AWS, no clock, unit-testable directly.
"""

from __future__ import annotations

CATEGORY = "Semantic Recall"

OK = "ok"
FAIL = "fail"
PAUSED = "paused"

# How many missing dates to name before eliding. Enough to see the shape of the gap
# (a single miss vs. "the writer has been dead for months") without an unreadable check line.
_MAX_NAMED = 6


def published_installment_dates(installments) -> list:
    """The dates of chronicle installments that a reader can actually open.

    Phase-visible only, matching `recall_indexer.published_post_links`: a wiped
    prior-cycle installment has no page and is not something this check can require an
    embedding for. Status-gated too — a draft is deliberately not indexed.

    KEYED ON THE SORT KEY, NOT THE `date` ATTRIBUTE. Those two disagree on live records:
    a reset's carry-forward re-stamps `date` while the sk keeps the original, so
    `DATE#2026-07-21` currently carries `date = 2026-08-02`. The corpus sk is
    `DOC#chronicle#<sk-date>` (`recall_indexer.chronicle_doc` derives it with
    `date_from_sk`), so comparing against the `date` attribute would report an installment
    that IS indexed as missing, and report the same date twice when two records claim it.
    Measured: doing it the other way red-flagged "2026-08-02, 2026-08-02" on the live
    table — one week double-counted and an already-indexed week (`DATE#2026-07-21`)
    accused — where the true answer is the single reader-visible 2026-08-02. The
    comparison must use the key the writer actually wrote.
    """
    from ai.recall_indexer import date_from_sk
    from experiment.phase_filter import singleton_visible

    return sorted(
        date_from_sk(str(i.get("sk", "")))
        for i in installments
        if singleton_visible(i) and date_from_sk(str(i.get("sk", ""))) and str(i.get("status", "")) == "published"
    )


def missing_dates(published, embedded) -> list:
    """Published installment dates with no embedding row. Pure set arithmetic.

    Deliberately a SET difference, not a max() comparison: a newest-vs-newest check would
    pass the moment the latest week indexed, hiding every older hole behind it — and holes
    are exactly what a writer that has been failing intermittently leaves.
    """
    have = {str(d) for d in (embedded or [])}
    return [d for d in sorted(str(p) for p in (published or [])) if d not in have]


def assess(published, embedded, *, indexing_paused=False):
    """(state, message) for the corpus-freshness check. Pure."""
    if not published:
        # Genesis week, or a fresh reset: nothing has published yet, so an empty corpus
        # is the correct state and not evidence of a broken writer.
        return OK, "no published installments yet — nothing to index"

    gaps = missing_dates(published, embedded)
    if not gaps:
        return OK, f"all {len(published)} published installment(s) are in the recall corpus"

    if indexing_paused:
        return PAUSED, (
            f"{len(gaps)} published installment(s) not indexed — recall indexing is budget-paused "
            f"at this tier (band 2, ADR-125), so the corpus is intentionally not advancing"
        )

    named = ", ".join(gaps[:_MAX_NAMED]) + (f" (+{len(gaps) - _MAX_NAMED} more)" if len(gaps) > _MAX_NAMED else "")
    return FAIL, (
        f"{len(gaps)} published installment(s) MISSING from the recall corpus: {named}. "
        f"The publish-time indexer did not write them, so 'when did I feel like this before?' "
        f"cannot cite these weeks — and returns silence rather than an error."
    )


def _indexing_paused() -> bool:
    """Band-2 budget state. An absent guard means a test harness, not a paused platform."""
    try:
        from ai.budget_guard import allow

        return not allow("semantic_recall")
    except ImportError:
        return False


def _embedded_chronicle_dates(table) -> list:
    """`doc_date` of every chronicle row in the recall partition."""
    from ai import semantic_recall as sr
    from boto3.dynamodb.conditions import Key

    dates, kwargs = [], {"KeyConditionExpression": Key("pk").eq(sr.RECALL_PK)}
    while True:
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            if it.get("kind") == sr.KIND_CHRONICLE and it.get("doc_date"):
                dates.append(str(it["doc_date"]))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return dates
        kwargs["ExclusiveStartKey"] = lek


def checks(table, chronicle_pk, Check, partition):  # noqa: N803 — `Check` is the injected class
    """The nightly check. Returns a one-element list, matching the sweep's contract."""
    from boto3.dynamodb.conditions import Key

    c = Check("recall:corpus_freshness", CATEGORY, partition)
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(chronicle_pk) & Key("sk").begins_with("DATE#"))
        published = published_installment_dates(resp.get("Items", []))
        state, msg = assess(published, _embedded_chronicle_dates(table), indexing_paused=_indexing_paused())
    except Exception as e:  # noqa: BLE001 — an unreadable table is a warn, not a false accusation
        return [c.warn(f"could not assess recall-corpus freshness: {e}")]

    return [{OK: c.ok, FAIL: c.fail, PAUSED: c.pause}[state](msg)]
