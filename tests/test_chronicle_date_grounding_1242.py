"""#1242 — the LIVE wednesday-chronicle installment gate now catches a fabricated date.

`installment_grounding_findings` is the exact findings function the chronicle's live
regen-once loop applies to each installment. Before #1242 it grounded numbers and
weekday↔date pairs but was structurally blind to a wholly invented calendar date
(an ISO date decomposes into benign small ints + a benign year, so the number gate
never saw it). This wires the shared `allowed_dates` / fabricated_date check into that
gate: a full date Elena cites that was NOT in her prompt or data packet is now a
fabricated_date finding — mirroring the existing number contract exactly.

Non-vacuity: `test_installment_gate_flags_fabricated_date` FAILS against the pre-#1242
installment_grounding_findings (no allowed_dates passed → the fabricated date is
invisible) and passes once the wiring lands. Verified by swapping the pre-wiring
lambda file — see the PR description for the recorded pre/post run.

Only stdlib + boto3 (a standard dev dep, imported by the chronicle lambda itself and
already collected clean by test_chronicle_weekday_grounding.py) — no layer-only imports.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import wednesday_chronicle_lambda as chron  # noqa: E402

# Elena's system prompt + the weekly data packet — exactly what she was given. The
# only full dates present are 2026-07-08 and 2026-07-14 (week ending). 2026-06-30
# below is NOT in either — a wholly invented date.
ELENA_PROMPT = "You are Elena Voss. Write in present tense, propulsive, a touch wry."
USER_MESSAGE = "=== WEEKLY DATA PACKET ===\nWeek ending: 2026-07-14\nWeigh-in on 2026-07-08 anchored the week."


def _date_findings(text, elena_prompt=ELENA_PROMPT, user_message=USER_MESSAGE):
    return [f for f in chron.installment_grounding_findings(elena_prompt, user_message, text) if f.get("type") == "fabricated_date"]


def test_installment_gate_flags_fabricated_date():
    """A date Elena cites that is in neither her prompt nor the packet is flagged.

    FAILS on the pre-#1242 gate (no allowed_dates arg → the invented date is invisible);
    passes once the wiring lands. This is the live, non-vacuous protection."""
    text = "The real turning point came on 2026-06-30, weeks before anyone noticed."
    fab = _date_findings(text)
    assert len(fab) == 1, chron.installment_grounding_findings(ELENA_PROMPT, USER_MESSAGE, text)
    assert fab[0]["claimed"] == "2026-06-30"


def test_installment_gate_flags_fabricated_longform_date():
    """Long-form fabricated dates are caught by the same live gate, normalized to ISO."""
    text = "It all shifted on June 30, 2026, a quiet Tuesday."
    fab = _date_findings(text)
    assert fab and fab[0]["claimed"] == "2026-06-30", chron.installment_grounding_findings(ELENA_PROMPT, USER_MESSAGE, text)


def test_installment_gate_passes_grounded_date():
    """A date that IS in the packet (2026-07-08) passes the live gate — no false positive."""
    text = "The week's anchor was the 2026-07-08 weigh-in, and the arc built from there."
    assert _date_findings(text) == []


def test_installment_gate_passes_grounded_date_across_formats():
    """An ISO date in the packet grounds a long-form restatement in Elena's prose."""
    text = "Everything traced back to July 8, 2026, the morning of the weigh-in."
    assert _date_findings(text) == []


def test_installment_gate_no_dates_is_silent():
    """A dateless installment produces no fabricated_date finding (nothing to check)."""
    text = "Recovery held steady all week and the training volume climbed."
    assert _date_findings(text) == []
