"""#2676 — a narrative labelled the whole-body recovery score as "metabolic recovery".

Two distinct metrics were fused under one label, so a reader was given a figure that does
not correspond to the thing it is named after. The metabolic pillar has its own score; the
recovery score is a whole-body readiness number from HRV/RHR/sleep.

THE DEFECT IS NOT A FIELD MAPPING — the code has always kept them apart. `_ask_fetch_context`
puts the Whoop recovery score in `ctx["recovery_pct"]` and the pillar scores in
`ctx["pillars"]["metabolic"]["raw_score"]`, from different partitions. The fusion happened
in generated prose, and the prompt is why:

    CURRENT DATA:
      …
      Recovery: 62%                       <- unqualified, and the reader is an LLM
      …
      Pillars:
        metabolic: level 3, score 41.2, tier …

A bare "Recovery" sitting four lines above a pillar named "metabolic" is an invitation to
write "metabolic recovery is 62%". The model was not hallucinating a number — it was
attaching a nearby label to a real one, which is worse, because the figure is verbatim
correct and the sentence is false.

SO THE FIX IS AT THE PROMPT, in three places, and it is about NAMING rather than data:

  1. `Recovery:` → `Whoop recovery score: N% (whole-body readiness from HRV/RHR/sleep —
     NOT a pillar score, and NOT specific to any pillar)`
  2. pillar lines say `<name> pillar: … score …`, so the scale each number belongs to is
     on the line with the number
  3. a RULES entry states the prohibition directly, because the other two make fusion
     harder and this makes it wrong: "never fuse a pillar's name onto the recovery figure
     … Where both are wanted, give them as two separately labelled figures."

WHAT THIS FILE CAN AND CANNOT ASSERT, said plainly. It pins the CONTRACT — that the prompt
presents each figure with its own metric name, that the two are described as different
numbers, and that the source fields stay distinct. It cannot assert what a model will write;
no unit test can. The live check is a post-deploy probe of `/api/ask` asking specifically
about metabolic health, recorded on the issue.
"""

from __future__ import annotations

import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402
from web import site_api_ai_lambda as ai  # noqa: E402

CTX = {
    "weight_lbs": 205.4,
    "hrv_ms": 54.0,
    "rhr_bpm": 58.0,
    # The two numbers the issue is about. Deliberately DIFFERENT and both plausible, so a
    # fused sentence would be arithmetically unremarkable and only wrong about its label.
    "recovery_pct": 62.0,
    "sleep_hours": 7.2,
    "character_level": 3.0,
    "character_tier": "Foundation",
    "pillars": {
        "sleep": {"level": 3.0, "raw_score": 55.5, "tier": "Foundation"},
        "metabolic": {"level": 2.0, "raw_score": 41.2, "tier": "Foundation"},
        "mind": {"level": 3.0, "raw_score": 60.0, "tier": "Foundation"},
    },
}

RECOVERY = "62"
METABOLIC = "41.2"


@pytest.fixture
def prompt(monkeypatch):
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda *a, **k: dict(CTX))
    return ai._ask_system_prompt(dict(CTX)) if hasattr(ai, "_ask_system_prompt") else _find_prompt(dict(CTX))


def _find_prompt(ctx):
    """The prompt builder, whatever it is called — resolved rather than hardcoded so a
    rename surfaces here instead of silently skipping the whole file."""
    for name in dir(ai):
        fn = getattr(ai, name)
        if not callable(fn) or not name.startswith("_"):
            continue
        try:
            out = fn(ctx)
        except Exception:
            continue
        if isinstance(out, str) and "CURRENT DATA:" in out and "RULES:" in out:
            return out
    raise AssertionError("no prompt builder produced a CURRENT DATA/RULES block — did it get renamed?")


def test_the_prompt_is_found_and_carries_both_numbers(prompt):
    """Vacuity guard. A prompt missing either figure makes every assertion below hollow."""
    assert "CURRENT DATA:" in prompt and "RULES:" in prompt
    assert RECOVERY in prompt, "the recovery score is not in the prompt"
    assert METABOLIC in prompt, "the metabolic pillar score is not in the prompt"


# ── box 1: the label and the value come from the same field ──────────────────


def test_the_recovery_figure_names_the_metric_it_came_from(prompt):
    line = next(ln for ln in prompt.splitlines() if RECOVERY in ln and "%" in ln)
    assert "recovery score" in line.lower(), f"the recovery figure is unlabelled: {line.strip()}"
    assert "whoop" in line.lower(), "the source device is what distinguishes it from a pillar score"


def test_the_recovery_line_says_it_is_not_a_pillar_score(prompt):
    """The fusion is a category error, so the prompt states the category."""
    line = next(ln for ln in prompt.splitlines() if RECOVERY in ln and "%" in ln)
    assert "NOT a pillar score" in line, line.strip()


def test_no_bare_recovery_label_survives(prompt):
    """`  Recovery: 62%` is the exact string the model read before fusing it."""
    assert not re.search(r"^\s*Recovery:\s", prompt, re.M), "an unqualified `Recovery:` label is back"


# ── box 2: the two are separate, separately-labelled figures ─────────────────


def test_each_pillar_score_is_labelled_as_a_pillar_score(prompt):
    line = next(ln for ln in prompt.splitlines() if METABOLIC in ln)
    assert "metabolic pillar" in line, f"the pillar score does not name its scale: {line.strip()}"
    assert "score" in line


def test_the_two_figures_are_on_different_lines_with_different_labels(prompt):
    rec = next(ln for ln in prompt.splitlines() if RECOVERY in ln and "%" in ln)
    met = next(ln for ln in prompt.splitlines() if METABOLIC in ln)
    assert rec != met
    assert "metabolic" not in rec.lower(), f"the recovery line mentions a pillar: {rec.strip()}"
    assert "%" not in met.split("score")[-1], "a pillar score is not a percentage — it must not read like one"


def test_the_rules_forbid_fusing_a_pillar_name_onto_the_recovery_figure(prompt):
    rules = prompt.split("RULES:")[1]
    assert "#2676" in rules or "fuse" in rules.lower(), "the prohibition is not stated"
    assert "separately labelled figures" in rules


# ── box 3: the source fields stay distinct ───────────────────────────────────


def test_the_context_keeps_the_two_metrics_in_different_fields():
    """The code was never wrong about this, and it must stay that way — a future 'tidy-up'
    that mapped recovery_score onto a pillar would make the prompt fix meaningless."""
    assert CTX["recovery_pct"] != CTX["pillars"]["metabolic"]["raw_score"]
    import inspect

    from web import site_api_ai_context as _ctxmod  # #2667: the mapping lives in the extracted sibling

    src = inspect.getsource(_ctxmod)
    assert '("recovery_score", "recovery_pct")' in src, "recovery_pct no longer maps from Whoop's recovery_score"
    assert 'pd = rec.get(f"pillar_{p}", {})' in src, "pillar scores no longer come from the character sheet"


def test_the_short_form_context_line_is_labelled_too(monkeypatch):
    """The second render — used by other AI surfaces — carried the same bare `recovery:`."""
    monkeypatch.setattr(ai, "_ask_fetch_context", lambda *a, **k: dict(CTX))
    import inspect

    from web import site_api_ai_context as _ctxmod  # #2667: the mapping lives in the extracted sibling

    src = inspect.getsource(_ctxmod)
    assert "f\"whoop recovery score: {ctx['recovery_pct']:.0f}%\"" in src or "whoop recovery score" in src
    assert not re.search(r'f"recovery: \{ctx\[.recovery_pct.\]', src), "the bare short-form label is back"


@pytest.mark.parametrize("pillar", ["sleep", "metabolic", "mind"])
def test_every_pillar_is_labelled_the_same_way(prompt, pillar):
    """Guard the SET: fixing only `metabolic` would leave the same trap for the next pillar."""
    assert f"{pillar} pillar:" in prompt
