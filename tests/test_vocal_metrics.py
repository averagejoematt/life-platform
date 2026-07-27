"""
tests/test_vocal_metrics.py — pins the SRT -> vocal biomarkers parser (#1842, AC1).

FIXTURE_SRT below is entirely invented dummy dialogue authored for this test — never real
tape content from the studio. Every expected value is hand-computed in the comments next
to the fixture so the assertions are exact numbers, not "roughly right."

Also covers the required edge cases: empty SRT, a single cue, and overlapping/
out-of-order timestamps (AC1's unit-test requirement + the issue's explicit edge-case
list). "Missing file -> metrics absent" is a backfill-script-layer behavior (the pure
parser never touches the filesystem) and is pinned in
tests/test_backfill_vocal_metrics.py instead.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

import vocal_metrics as vm  # noqa: E402

# ── Synthetic fixture (invented dialogue) ──────────────────────────────────────────────
# Cue 1: 00:00.000 -> 10.000   "This is a simple test of the vocal biomarkers feature"
#        10 words, 0 fillers.
# gap 1->2: 11.500 - 10.000 = 1.500s  (> 0.5s threshold -> ONE qualifying pause)
# Cue 2: 11.500 -> 20.500   "Um so basically uh this is just a placeholder sentence"
#        10 words, 2 fillers ("Um", "uh").
# gap 2->3: 20.700 - 20.500 = 0.200s  (<= 0.5s threshold -> NOT a pause)
# Cue 3: 20.700 -> 30.700   "And that is the end of this fixture transcript now"
#        10 words, 0 fillers.
#
# duration_s = max(end) - min(start) = 30.700 - 0.000 = 30.700
# word_count = 30
# filler_count = 2
# duration_min = 30.700 / 60 = 0.5116666...
# wpm = 30 / 0.5116666... = 58.6319... -> round(1) = 58.6
# fillers_per_min = 2 / 0.5116666... = 3.9087... -> round(2) = 3.91
# pauses = [1.500]  -> pauses_per_min = 1 / 0.5116666... = 1.9543... -> round(2) = 1.95
# mean_pause_s = 1.500 -> round(2) = 1.5
FIXTURE_SRT = """1
00:00:00,000 --> 00:00:10,000
This is a simple test of the vocal biomarkers feature

2
00:00:11,500 --> 00:00:20,500
Um so basically uh this is just a placeholder sentence

3
00:00:20,700 --> 00:00:30,700
And that is the end of this fixture transcript now
"""


def test_fixture_srt_exact_values():
    result = vm.parse_srt(FIXTURE_SRT)
    assert result is not None
    assert result["duration_s"] == 30.7
    assert result["word_count"] == 30
    assert result["wpm"] == 58.6
    assert result["fillers_per_min"] == 3.91
    assert result["pauses_per_min"] == 1.95
    assert result["mean_pause_s"] == 1.5


def test_empty_srt_returns_none():
    assert vm.parse_srt("") is None
    assert vm.parse_srt("   \n\n   \n") is None


def test_srt_with_no_parseable_cues_returns_none():
    # No timestamp line anywhere -> nothing to parse.
    assert vm.parse_srt("1\nthis is not a timed cue\n\n2\nneither is this\n") is None


def test_single_cue_no_pauses():
    srt = "1\n00:00:00,000 --> 00:00:05,000\nHello world testing\n"
    result = vm.parse_srt(srt)
    assert result is not None
    assert result["duration_s"] == 5.0
    assert result["word_count"] == 3
    # duration_min = 5/60 -> wpm = 3 / (5/60) = 36.0 exactly
    assert result["wpm"] == 36.0
    assert result["fillers_per_min"] == 0.0
    assert result["pauses_per_min"] == 0.0
    # No pause exists at all with a single cue -> absent, not zero.
    assert result["mean_pause_s"] is None


def test_zero_length_single_cue_is_degenerate_and_absent():
    # start == end -> duration_s == 0 -> nothing computable, must be None (ADR-104:
    # absent, not a divide-by-zero or a fabricated 0/0 metric).
    srt = "1\n00:00:05,000 --> 00:00:05,000\nHello\n"
    assert vm.parse_srt(srt) is None


def test_overlapping_and_out_of_order_cues():
    # Written out of chronological order in the file itself, and cue C overlaps both
    # cue A and cue B. Sorted by start: B(0-5, 3 words), C(4-12, 4 words), A(10-15, 3
    # words). No gap ever goes positive past the running "covered through" watermark,
    # so there must be ZERO qualifying pauses despite three cues and two "gaps" in file
    # order.
    srt = (
        "1\n00:00:10,000 --> 00:00:15,000\nfour five six\n\n"
        "2\n00:00:00,000 --> 00:00:05,000\none two three\n\n"
        "3\n00:00:04,000 --> 00:00:12,000\nseven eight nine ten\n"
    )
    result = vm.parse_srt(srt)
    assert result is not None
    # start=min(10,0,4)=0, end=max(15,5,12)=15
    assert result["duration_s"] == 15.0
    assert result["word_count"] == 10
    assert result["wpm"] == 40.0  # 10 / (15/60) = 40.0
    assert result["pauses_per_min"] == 0.0
    assert result["mean_pause_s"] is None


def test_filler_words_are_whole_token_case_insensitive():
    # "uh" inside "shuh" must NOT match (word-boundary requirement); "UM"/"Uh" must.
    srt = "1\n00:00:00,000 --> 00:00:10,000\nUM this shuh is UH a test hmm\n"
    result = vm.parse_srt(srt)
    assert result is not None
    # UM + UH match (2); "shuh" does not; "hmm" is not in FILLER_WORDS by design.
    duration_min = 10.0 / 60.0
    expected_fillers_per_min = round(2 / duration_min, 2)
    assert result["fillers_per_min"] == expected_fillers_per_min


# ── AC3: the exploratory / low-n floor helper ──────────────────────────────────────────


def test_vocal_metrics_state_empty_low_n_reported():
    assert vm.vocal_metrics_state(0) == "empty"
    assert vm.vocal_metrics_state(1) == "low_n"
    assert vm.vocal_metrics_state(vm.MIN_N_FOR_VOCAL_STATS - 1) == "low_n"
    assert vm.vocal_metrics_state(vm.MIN_N_FOR_VOCAL_STATS) == "reported"
    assert vm.vocal_metrics_state(vm.MIN_N_FOR_VOCAL_STATS + 50) == "reported"


def test_filler_words_set_is_exactly_documented():
    # The set IS the metric definition (module docstring) — pin it so a silent edit
    # doesn't quietly change what counts as a filler.
    assert vm.FILLER_WORDS == {"um", "umm", "uh", "uhh", "erm"}
