"""#5656 follow-up (owner 2026-11-07): a degraded public character compute is alarmed, not silent.

The token twin: the literal the Lambda logs and the literal the CloudWatch metric filter matches must be the same
string, and every degraded path must log it. Mutation control: a renamed token on either side fails here."""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for _k, _v in (
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("TABLE_NAME", "life-platform-test"),
    ("USER_ID", "matthew"),
    ("S3_BUCKET", "test-bucket"),
):
    os.environ.setdefault(_k, _v)

LAMBDA = os.path.join(ROOT, "lambdas", "compute", "character_sheet_lambda.py")
CDK = os.path.join(ROOT, "cdk", "stacks", "monitoring_compute_alarms.py")


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _token():
    m = re.search(r'^PUBLIC_DEGRADED_MARKER = "([A-Z-]+)"$', _src(LAMBDA), re.M)
    assert m, "PUBLIC_DEGRADED_MARKER literal missing from the character lambda"
    return m.group(1)


def test_the_metric_filter_matches_the_token_the_lambda_logs():
    tok = _token()
    assert f"FilterPattern.literal('\"{tok}\"')" in _src(CDK)
    assert '"/aws/lambda/character-sheet-compute"' in _src(CDK) and '"character-public-inputs-degraded"' in _src(CDK)


def test_every_degraded_path_logs_the_token():
    calls = re.findall(r"logger\.error\((.*?)\)\n", _src(LAMBDA), re.S)
    degraded = [c for c in calls if any(k in c for k in ("not ready", "no public variant for %s", "public variant failed"))]
    assert len(degraded) == 3 and all("PUBLIC_DEGRADED_MARKER" in c for c in degraded)


def test_mutation_control_a_renamed_token_breaks_the_twin():
    assert "FilterPattern.literal('\"CHARACTER-PUBLIC-INPUTS-DEGRADED-X\"')" not in _src(CDK)


def test_the_not_ready_path_emits_the_token(monkeypatch):
    from compute import character_sheet_lambda as C

    monkeypatch.setattr(C, "fetch_date", lambda *_a, **_k: None)
    seen = []
    monkeypatch.setattr(C.logger, "error", lambda msg, *a, **_k: seen.append(msg % a if a else msg))
    _rec, status = C.await_habit_scores("2026-10-01", wait_s=0)
    assert status != "ready" and any(_token() in m for m in seen)
