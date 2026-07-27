"""
tests/test_backfill_vocal_metrics.py — pins the local backfill script's pure layer
(#1842): date resolution from the studio's session-directory convention, the
"missing/degenerate file -> metrics absent" contract (AC2's absent-not-zeroed rule, at
the layer that actually owns it), and the exact update_item() shape (SET-only,
attribute_exists gate, Decimal-cast numerics, no put_item, no transcript text).

Nothing here touches AWS — matching_journal_sks/write_vocal_metrics (the boto3 I/O) are
deliberately out of scope for unit tests, same posture as the rest of this codebase's
boto3-adjacent scripts.
"""

import importlib.util
import os
import sys
from decimal import Decimal
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

# scripts/ isn't a package (no __init__.py convention here) — load by path like the
# platform's other scripts/*.py tests do.
_SPEC = importlib.util.spec_from_file_location("backfill_vocal_metrics", os.path.join(_ROOT, "scripts", "backfill_vocal_metrics.py"))
bvm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bvm)


FIXTURE_SRT = "1\n00:00:00,000 --> 00:00:10,000\nHello there this is a test\n"  # 6 words, 10s


# ── find_session_date ───────────────────────────────────────────────────────────────


def test_date_from_session_md_front_matter(tmp_path: Path):
    session_dir = tmp_path / "sessions" / "2026-07-26_retro_day-zero"
    transcript_dir = session_dir / "transcript"
    transcript_dir.mkdir(parents=True)
    (session_dir / "SESSION.md").write_text("---\ndate: 2026-07-26\nday: 0\nformat: retro\n---\n\nbody\n")
    srt_path = transcript_dir / "transcript.srt"
    srt_path.write_text(FIXTURE_SRT)

    assert bvm.find_session_date(srt_path) == "2026-07-26"


def test_date_falls_back_to_directory_prefix_without_session_md(tmp_path: Path):
    session_dir = tmp_path / "sessions" / "2026-08-01_some-slug"
    transcript_dir = session_dir / "transcript"
    transcript_dir.mkdir(parents=True)
    srt_path = transcript_dir / "transcript.srt"
    srt_path.write_text(FIXTURE_SRT)

    assert bvm.find_session_date(srt_path) == "2026-08-01"


def test_date_unresolved_returns_none(tmp_path: Path):
    weird_dir = tmp_path / "sessions" / "not-a-dated-folder"
    weird_dir.mkdir(parents=True)
    srt_path = weird_dir / "clip.srt"
    srt_path.write_text(FIXTURE_SRT)

    assert bvm.find_session_date(srt_path) is None


# ── compute_metrics_for_file: the "missing file -> metrics absent" contract ────────


def test_missing_file_yields_none_not_an_exception(tmp_path: Path):
    missing = tmp_path / "does_not_exist.srt"
    assert not missing.exists()
    assert bvm.compute_metrics_for_file(missing) is None


def test_degenerate_srt_file_yields_none(tmp_path: Path):
    degenerate = tmp_path / "empty.srt"
    degenerate.write_text("")
    assert bvm.compute_metrics_for_file(degenerate) is None


def test_real_srt_file_yields_metrics(tmp_path: Path):
    srt_path = tmp_path / "real.srt"
    srt_path.write_text(FIXTURE_SRT)
    result = bvm.compute_metrics_for_file(srt_path)
    assert result is not None
    assert result["word_count"] == 6
    assert result["duration_s"] == 10.0


# ── iter_srt_files ───────────────────────────────────────────────────────────────────


def test_iter_srt_files_recursive_and_sorted(tmp_path: Path):
    (tmp_path / "a" / "transcript").mkdir(parents=True)
    (tmp_path / "b" / "transcript").mkdir(parents=True)
    f1 = tmp_path / "b" / "transcript" / "transcript.srt"
    f2 = tmp_path / "a" / "transcript" / "transcript.srt"
    f1.write_text(FIXTURE_SRT)
    f2.write_text(FIXTURE_SRT)
    (tmp_path / "a" / "notes.txt").write_text("not an srt")

    found = bvm.iter_srt_files(tmp_path)
    assert found == sorted(found)
    assert f1 in found and f2 in found
    assert len(found) == 2


def test_iter_srt_files_nonexistent_dir_returns_empty():
    assert bvm.iter_srt_files(Path("/definitely/does/not/exist/anywhere")) == []


# ── build_update_kwargs: the exact write shape (SET-only, no put_item, Decimal-cast) ──


def test_build_update_kwargs_shape():
    metrics = {
        "wpm": 58.6,
        "mean_pause_s": 1.5,
        "pauses_per_min": 1.95,
        "fillers_per_min": 3.91,
        "duration_s": 30.7,
        "word_count": 30,
    }
    kwargs = bvm.build_update_kwargs(
        "USER#matthew#SOURCE#notion", "DATE#2026-07-26#journal#video_diary#abc123", metrics, "2026-07-27T00:00:00+00:00"
    )

    assert kwargs["Key"] == {"pk": "USER#matthew#SOURCE#notion", "sk": "DATE#2026-07-26#journal#video_diary#abc123"}
    assert kwargs["UpdateExpression"].startswith("SET ")
    assert kwargs["ConditionExpression"] == "attribute_exists(#pk)"
    # Every metric value must be Decimal (DynamoDB rejects float) — never a str/float.
    for placeholder, attr in (
        (":vocal_wpm", "wpm"),
        (":vocal_mean_pause_s", "mean_pause_s"),
        (":vocal_pauses_per_min", "pauses_per_min"),
        (":vocal_fillers_per_min", "fillers_per_min"),
        (":vocal_duration_s", "duration_s"),
        (":vocal_word_count", "word_count"),
    ):
        assert isinstance(kwargs["ExpressionAttributeValues"][placeholder], Decimal)
        assert kwargs["ExpressionAttributeValues"][placeholder] == Decimal(str(metrics[attr]))
    # No transcript text or SRT content anywhere in the write payload.
    for v in kwargs["ExpressionAttributeValues"].values():
        assert not isinstance(v, str) or len(v) < 40  # only the ISO timestamp is a string


def test_build_update_kwargs_omits_absent_mean_pause():
    # mean_pause_s=None (no qualifying pauses) must NOT be written at all — absent,
    # not a zeroed/defaulted field (ADR-104).
    metrics = {"wpm": 36.0, "mean_pause_s": None, "pauses_per_min": 0.0, "fillers_per_min": 0.0, "duration_s": 5.0, "word_count": 3}
    kwargs = bvm.build_update_kwargs("pk", "sk", metrics, "2026-07-27T00:00:00+00:00")
    assert ":vocal_mean_pause_s" not in kwargs["ExpressionAttributeValues"]
    assert "#vocal_mean_pause_s" not in kwargs["ExpressionAttributeNames"]
    assert "vocal_mean_pause_s" not in kwargs["UpdateExpression"]
