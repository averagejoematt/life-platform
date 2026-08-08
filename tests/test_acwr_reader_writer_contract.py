"""#2243 derived guard: the reader/writer field-name contract for ACWR data.

This is the ~21st instance (across three coverage tranches) of the same bug
shape: a compute Lambda writes prefixed field names onto `computed_metrics`
and a downstream reader asks for the bare, un-prefixed name — which is never
written by anything, so the read is always empty/False and the feature is
permanently dark with no error anywhere.

Rather than hand-list "the reader must ask for acwr_zone/acwr_alert/..." (which
would happily keep passing if BOTH sides drifted to agree on a NEW wrong name),
this derives the writer's actual emitted field set from `_write_acwr`'s source
and asserts each reader's ACWR-related reads are a subset of it. A future rename
on either side that breaks the contract fails here instead of shipping a dark
feature again.
"""

from __future__ import annotations

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")

ACWR_COMPUTE_SRC = open(os.path.join(LAMBDAS, "compute", "acwr_compute_lambda.py"), encoding="utf-8").read()
HTML_BUILDER_SRC = open(os.path.join(LAMBDAS, "content", "html_builder.py"), encoding="utf-8").read()
DAILY_BRIEF_SRC = open(os.path.join(LAMBDAS, "emails", "daily_brief_lambda.py"), encoding="utf-8").read()


def _write_acwr_body(src: str) -> str:
    """Isolate the `_write_acwr` function body, up to the next top-level def."""
    m = re.search(r"\ndef _write_acwr\(.*?(?=\n\ndef |\Z)", src, re.S)
    assert m, "acwr_compute_lambda._write_acwr not found by name — has it been renamed or moved?"
    return m.group(0)


def _writer_fields() -> set:
    """The set of DynamoDB attribute names `_write_acwr` can SET, derived from its
    UpdateExpression string literals (e.g. "acwr_zone            = :zone") — not
    hand-typed, so a rename in the writer is picked up automatically."""
    body = _write_acwr_body(ACWR_COMPUTE_SRC)
    fields = set(re.findall(r'"(\w+)\s*=\s*:\w+"', body))
    assert fields, "regex found no SET-clause fields in _write_acwr — has the UpdateExpression style changed?"
    return fields


def _acwr_reads(block: str) -> set:
    """computed_metrics/_cm .get("KEY", ...) reads for ACWR-shaped keys in `block`."""
    keys = set(re.findall(r'(?:computed_metrics|_cm)\.get\(\s*"(\w+)"', block))
    return {k for k in keys if k == "acwr" or k.startswith("acwr_")}


def test_html_builder_training_load_alert_reads_are_a_subset_of_the_writers_fields():
    writer_fields = _writer_fields()
    idx = HTML_BUILDER_SRC.index("# BS-09: ACWR training load alert")
    block = HTML_BUILDER_SRC[idx : idx + 900]
    reader_fields = _acwr_reads(block)
    assert len(reader_fields) >= 3, f"expected zone/alert/alert_reason (+ acwr) reads in the ACWR block, found {reader_fields}"
    unknown = reader_fields - writer_fields
    assert not unknown, (
        f"html_builder's TRAINING LOAD ALERT block reads {sorted(unknown)}, which "
        "acwr_compute_lambda._write_acwr never writes — the reader/writer contract "
        "has drifted (this is the #2243 bug class: the block will render/colour "
        "nothing and no error will fire)."
    )


def test_daily_brief_log_line_reads_are_a_subset_of_the_writers_fields():
    writer_fields = _writer_fields()
    idx = DAILY_BRIEF_SRC.index("# BS-09: ACWR training load (written by acwr-compute Lambda")
    block = DAILY_BRIEF_SRC[idx : idx + 500]
    reader_fields = _acwr_reads(block)
    assert len(reader_fields) >= 2, f"expected zone + alert reads in the ACWR log line, found {reader_fields}"
    unknown = reader_fields - writer_fields
    assert not unknown, f"daily_brief_lambda's ACWR log line reads {sorted(unknown)}, which the writer never writes."


def test_daily_brief_public_stats_training_block_reads_are_a_subset_of_the_writers_fields():
    writer_fields = _writer_fields()
    idx = DAILY_BRIEF_SRC.index("training={")
    block = DAILY_BRIEF_SRC[idx : idx + 1400]
    reader_fields = _acwr_reads(block)
    assert len(reader_fields) >= 2, f"expected zone + alert reads feeding form_status/injury_risk, found {reader_fields}"
    unknown = reader_fields - writer_fields
    assert not unknown, (
        f"daily_brief_lambda's public_stats training block reads {sorted(unknown)}, which "
        "the writer never writes — form_status/injury_risk would silently fabricate a default "
        "again (the #2243 bug class)."
    )
