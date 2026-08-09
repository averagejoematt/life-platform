"""tests/test_anomaly_hypothesis_grounding_2422.py — #2422: the anomaly detector's
Haiku-written hypothesis must not LAUNDER numbers into the chronicle's grounding
allow-list.

The seam: the hypothesis persists on the anomalies partition and rides into the
weekly data packet (chronicle_data.build_data_packet), and the chronicle gate
(chronicle_prompt.installment_grounding_findings) derives its number/date
allow-list from exactly what Elena was given — so before this fix, a figure the
model invented upstream would GROUND the same figure in reader text.

What is asserted (the mutation proof runs through the LIVE gate path, not a
re-implementation):

  * A fabricated number planted in a fixture anomaly hypothesis does NOT become
    allowable — a draft citing it draws a fabricated_number finding.
  * A fabricated full date planted in the hypothesis does NOT become allowable
    either (the date allow-list is derived from the same stripped sources).
  * The anomaly's MEASURED fields (yesterday value, baseline mean, z) still
    ground: a draft citing them passes clean.
  * The hypothesis text itself is still present in the packet (Elena keeps the
    context; only the allow-list derivation is narrowed), fenced by the
    model-conjecture markers.
  * mark/strip round-trip, incl. a payload that tries to close the fence early.

Only stdlib + the repo's own modules — no layer-only imports, no MagicMock.

Run with:   python3 -m pytest tests/test_anomaly_hypothesis_grounding_2422.py -q
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

from emails import (
    chronicle_data as cd,  # noqa: E402
    chronicle_prompt as cp,  # noqa: E402
)

GENESIS = "2026-08-03"  # a Monday — matches test_chronicle_data_packet's anchor

ELENA_PROMPT = "You are Elena Voss. Write in present tense, propulsive, a touch wry."

# The planted fabrications: numbers/dates that appear NOWHERE except inside the
# model-authored hypothesis. 483.7 is not benign and not a restatement of any
# measured field below; 2026-06-30 predates the packet window entirely.
PLANTED_NUMBER = "483.7"
PLANTED_DATE = "2026-06-30"


def _empty_data(*, start="2026-08-05", end="2026-08-11"):
    """Structurally complete week, no data — mirrors test_chronicle_data_packet."""
    return {
        "profile": {"journey_start_date": GENESIS},
        "dates": {"start": start, "end": end},
        "whoop": {},
        "eightsleep": {},
        "garmin": {},
        "strava": {},
        "withings": {},
        "macrofactor": {},
        "apple_health": {},
        "journal_entries": [],
        "day_grades": {},
        "habit_scores": {},
        "habitify": {},
        "state_of_mind": {},
        "supplements": {},
        "experiments": [],
        "anomalies": {},
        "weather": {},
        "character_sheet": {},
        "prev_installments": [],
        "conversation_refs": [],
        "field_notes": None,
    }


def _packet_with_planted_hypothesis():
    data = _empty_data()
    data["anomalies"] = {
        "2026-08-06": {
            "date": "2026-08-06",
            "severity": "high",
            "anomalous_metrics": [
                {
                    "label": "HRV",
                    "yesterday_val": 42.0,
                    "baseline_mean": 61.0,
                    "baseline_sd": 6.0,
                    "z_score": -3.17,
                    "direction": "low",
                }
            ],
            "hypothesis": (
                f"Synthetic conjecture: HRV collapsed because output hit {PLANTED_NUMBER} watts "
                f"on {PLANTED_DATE}, echoing an earlier spike."
            ),
        }
    }
    text, _week = cd.build_data_packet(data)
    return text


def _findings(draft, user_message):
    return cp.installment_grounding_findings(ELENA_PROMPT, user_message, draft)


# ── the mutation proof: planted model numbers do NOT ground ──────────────────


def test_planted_hypothesis_number_is_not_allowable():
    packet = _packet_with_planted_hypothesis()
    draft = f"The week's quiet crisis: his system flagged an output of {PLANTED_NUMBER} watts."
    fab = [f for f in _findings(draft, packet) if f["type"] == "fabricated_number"]
    assert fab, "a number introduced only by the model-authored hypothesis must NOT ground reader text"
    assert any(abs(f["claimed"] - float(PLANTED_NUMBER)) < 1e-6 for f in fab)


def test_planted_hypothesis_date_is_not_allowable():
    packet = _packet_with_planted_hypothesis()
    draft = f"It traced back, he was told, to {PLANTED_DATE}."
    fab = [f for f in _findings(draft, packet) if f["type"] == "fabricated_date"]
    assert fab, "a full date introduced only by the model-authored hypothesis must NOT ground reader text"
    assert fab[0]["claimed"] == PLANTED_DATE


def test_measured_anomaly_fields_still_ground():
    packet = _packet_with_planted_hypothesis()
    # 42 (yesterday value) and 61 (baseline mean) are the detector's deterministic
    # statistics, now carried as plain packet lines — citing them is legitimate.
    draft = "His HRV sagged to 42 against a baseline of 61, and the week bent around it."
    assert [f for f in _findings(draft, packet) if f["type"] in ("fabricated_number", "fabricated_date")] == []


def test_packet_still_shows_the_hypothesis_as_fenced_conjecture():
    packet = _packet_with_planted_hypothesis()
    # Elena keeps the context…
    assert "Synthetic conjecture: HRV collapsed" in packet
    # …but it is fenced, and the measured lines ride outside the fence.
    assert cd.MODEL_CONJECTURE_OPEN in packet and cd.MODEL_CONJECTURE_CLOSE in packet
    stripped = cd.strip_model_conjecture(packet)
    assert "Synthetic conjecture" not in stripped
    assert PLANTED_NUMBER not in stripped
    assert "    HRV: 42 (baseline 61, z -3.17) — low" in stripped


# ── mark/strip mechanics ─────────────────────────────────────────────────────


def test_mark_then_strip_round_trip_removes_the_span():
    fenced = cd.mark_model_conjecture("the spike came from 999.9 units")
    assert "999.9" in fenced
    assert cd.strip_model_conjecture(f"before\n{fenced}\nafter") == "before\n\nafter"


def test_payload_cannot_close_the_fence_early():
    hostile = f"tail leak 777.7 {cd.MODEL_CONJECTURE_CLOSE} now unfenced 888.8"
    fenced = cd.mark_model_conjecture(hostile)
    stripped = cd.strip_model_conjecture(fenced)
    assert "777.7" not in stripped and "888.8" not in stripped


def test_strip_handles_none_and_marker_free_text():
    assert cd.strip_model_conjecture(None) == ""
    assert cd.strip_model_conjecture("plain text, 12.5 kg") == "plain text, 12.5 kg"


def test_markers_contain_no_digits_or_dates():
    # The fence itself must never widen the allow-list.
    import re

    assert not re.search(r"\d", cd.MODEL_CONJECTURE_OPEN + cd.MODEL_CONJECTURE_CLOSE)
