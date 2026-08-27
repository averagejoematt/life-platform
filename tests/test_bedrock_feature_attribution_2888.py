"""
Per-feature Bedrock attribution outside Lambda (#2888, epic #2801).

WHY
---
`bedrock_client`'s `LambdaFunction` metric dimension came straight from
`AWS_LAMBDA_FUNCTION_NAME`, defaulting to the literal `"unknown"`. Measured
2026-08-27 (`LifePlatform/AI`, trailing 30d, `scripts/ai_spend_attribution.py`),
`unknown` was the LARGEST row in the per-feature ranking — 17.9M input tokens,
$33.19, 46% of all self-reported AI spend — so #2888's first acceptance box
("features ranked by uncached input volume") could not be satisfied at the top of
its own ranking.

WHAT IS PINNED HERE
-------------------
Three properties, each of which has a way to be wrong:

  1. The Lambda runtime's own name always OUTRANKS a context label. Without this
     the mechanism becomes a way for any caller to book its spend under someone
     else's name, which is the misattribution #2892 exists to prevent.
  2. The label allowlist BOUNDS the dimension's cardinality. A CloudWatch custom
     metric is ~$0.30/metric/month against six metric names on this dimension, so
     an unbounded label would add recurring cost to a cost-reduction change.
  3. The two AI CI gates run in ONE process and are labelled SEPARATELY —
     the whole point, since `sys.argv[0]` is `tests/visual_qa.py` for both.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas"))

from ai import bedrock_client  # noqa: E402


@pytest.fixture(autouse=True)
def _no_lambda_env(monkeypatch):
    """Default every case to the NON-Lambda context (CI/laptop)."""
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)


def test_unlabelled_non_lambda_call_stays_in_the_unknown_residual():
    """The residual bucket keeps its historic name so the series stays continuous."""
    assert bedrock_client.feature_name() == "unknown"


def test_allowlisted_label_names_the_spend():
    with bedrock_client.attributed_to("visual-ai-qa"):
        assert bedrock_client.feature_name() == "visual-ai-qa"
    # and the label is scoped — it does not leak past the block
    assert bedrock_client.feature_name() == "unknown"


def test_the_two_ci_gates_are_labelled_separately():
    """Both run inside one `tests/visual_qa.py` process; argv cannot split them."""
    seen = []
    for label in ("visual-ai-qa", "reader-truth-qa"):
        with bedrock_client.attributed_to(label):
            seen.append(bedrock_client.feature_name())
    assert seen == ["visual-ai-qa", "reader-truth-qa"]
    assert len(set(seen)) == 2


def test_unallowlisted_label_is_ignored_not_emitted():
    """Cardinality is bounded BY CONSTRUCTION, not by call-site discipline.

    NEGATIVE CONTROL for property 2. This case must FAIL if `feature_name()` ever
    returns the raw label — verified by mutation: making the resolver
    `return label or "unknown"` turns this assertion red.
    """
    with bedrock_client.attributed_to("scratch-script-" + "x" * 40):
        assert bedrock_client.feature_name() == "unknown"


def test_lambda_runtime_name_outranks_any_label(monkeypatch):
    """NEGATIVE CONTROL for property 1 — spend cannot be booked to another name.

    Verified by mutation: swapping the precedence in `feature_name()` (label
    first, env second) turns this assertion red.
    """
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-qa-smoke")
    with bedrock_client.attributed_to("reader-truth-qa"):
        assert bedrock_client.feature_name() == "life-platform-qa-smoke"


def test_blank_lambda_env_is_not_a_function_name(monkeypatch):
    """An empty/whitespace env var must not become the dimension value."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "   ")
    assert bedrock_client.feature_name() == "unknown"


def test_metric_emit_uses_the_resolved_feature_name(monkeypatch):
    """The wiring, not just the resolver: the dimension the emit puts on the wire.

    Guards the SET of emitted datapoints, not one instance — every per-feature
    datapoint must carry the same resolved name, so a partially-converted emit
    (one of the three `fn_dim` sites left on the old constant) fails here.
    """
    captured = {}

    class _FakeCW:
        def put_metric_data(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(bedrock_client, "_CW", _FakeCW())
    with bedrock_client.attributed_to("visual-ai-qa"):
        bedrock_client._emit_usage_metrics({"input_tokens": 100, "output_tokens": 10}, "us.anthropic.claude-haiku-4-5-20251001-v1:0")

    assert captured, "telemetry emit produced no datapoints"
    named = [m for m in captured["MetricData"] if m.get("Dimensions") and m["Dimensions"][0]["Name"] == "LambdaFunction"]
    assert named, "no per-feature datapoints emitted"
    assert {m["Dimensions"][0]["Value"] for m in named} == {"visual-ai-qa"}


def test_ci_gate_call_sites_are_actually_wired():
    """The instrument must be attached, not merely available (#2578 class).

    A resolver that works and is never called is the failure mode this whole
    issue is about, so assert the two gates' call sites reference it.
    """
    harness = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual_ai_qa.py")
    with open(harness, encoding="utf-8") as fh:
        src = fh.read()
    assert '_attributed(bedrock, "visual-ai-qa")' in src, "the vision judge no longer labels its spend"
    assert '_attributed_invoke(bedrock, "reader-truth-qa")' in src, "the reader-truth pass no longer labels its spend"
    assert "reader_truth_qa.assess_prose(surfaces, truth_invoke" in src, "assess_prose is back on the unlabelled invoke"


def test_allowlist_matches_the_wired_labels():
    """Registry and call sites cannot drift apart (charter primitive 1)."""
    assert bedrock_client.ATTRIBUTABLE_FEATURES == frozenset({"visual-ai-qa", "reader-truth-qa"})
