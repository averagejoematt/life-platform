"""#4624 backlog row: whoop's stored sleep-onset minutes are UTC-framed and now say so."""

import os
import pathlib
import sys

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))


def test_onset_minutes_are_minutes_after_utc_midnight():
    from ingestion.whoop_lambda import _sleep_onset_minutes

    # 21:44 PDT on the 18th is 04:44 UTC on the 19th
    assert _sleep_onset_minutes("2026-10-19T04:44:00.000Z") == 4 * 60 + 44
    assert _sleep_onset_minutes(None) is None


# premerge-gate: 4624: reads docs/SCHEMA.md so the field's frame label cannot be dropped from the schema row
def test_schema_row_names_the_frame():
    row = next(ln for ln in (REPO / "docs/SCHEMA.md").read_text().splitlines() if ln.startswith("| `sleep_onset_minutes`"))
    assert "UTC" in row
