#!/usr/bin/env python3
"""scripts/transcribe_solo.py — local-Whisper solo-recording transcription leg (#1573).

For a recording made WITHOUT Claude in the room (a raw solo voice memo or solo
video diary — no live interviewer), this script transcribes the audio **locally**
and lands the transcript in the EXISTING journal pipeline as a "Solo Recording"
Notion page (channel=solo_recording). No second pipeline (epic #1564 / #1572
principle): once the page exists, the hourly notion-data-ingestion lambda picks it
up and it flows enrichment → flourishing → character → hypothesis exactly like a
typed journal entry.

Why local Whisper (AC1):
  - $0 — no cloud API bill against the $85 ceiling (ADR-063).
  - Private — the AUDIO NEVER LEAVES THE DEVICE. Only the resulting TEXT transcript
    is posted to Notion. The video/audio file itself is never uploaded; a pointer
    (filename, where it lives, duration) is recorded on the page instead (#1573
    AC2 — Matthew separately decides if/when full video ever goes to S3).

Local dependency (owner installs on their machine — this is NOT a deployed lambda,
NOT a cloud API call):

    # Preferred — openai-whisper (pure-Python, pip):
    pip install -U openai-whisper        # also needs ffmpeg on PATH
    #   brew install ffmpeg

    # Alternative — whisper.cpp (a compiled binary + a .bin model):
    #   https://github.com/ggerganov/whisper.cpp
    #   point --engine whisper.cpp --binary /path/to/whisper-cli --model /path/to/ggml-base.en.bin

Usage:

    # Transcribe only (prints transcript, writes nothing to Notion):
    python3 scripts/transcribe_solo.py ~/Recordings/2026-07-25-solo.m4a

    # Transcribe + create the Solo Recording Notion page (needs the Notion key):
    python3 scripts/transcribe_solo.py ~/Recordings/2026-07-25-solo.m4a --post-to-notion

    # Preview the exact Notion payload without posting (no network):
    python3 scripts/transcribe_solo.py ~/Recordings/2026-07-25-solo.m4a --post-to-notion --dry-run

Watched-folder / launchd note (the TCC ~/Documents trap, memory
reference_launchd_tcc_documents): stage the launchd wrapper + this script to
~/.local/bin, NOT under ~/Documents — a LaunchAgent reading ~/Documents exits 126.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

# The Notion Template label + channel this script lands under. MUST match
# lambdas/ingestion/notion_lambda.py TEMPLATE_SK and lambdas/flourishing.py
# so the ingestion lambda keys channel="solo_recording" off it (#1573).
SOLO_TEMPLATE = "Solo Recording"
SOLO_CHANNEL = "solo_recording"

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion rich_text / paragraph blocks cap at 2000 chars per text object; chunk the
# transcript so a long recording still posts cleanly.
_NOTION_TEXT_LIMIT = 2000


# ── Engine selection + transcription ──────────────────────────────────────────


def probe_duration_seconds(path: str) -> Optional[float]:
    """Best-effort media duration via ffprobe (local). None if unavailable — a
    pointer without a duration is still a valid pointer (never blocks the leg)."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return round(float(out.stdout.strip()), 1)
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return None


def transcribe_openai_whisper(path: str, model: str) -> str:
    """Transcribe locally with the openai-whisper package (lazy import — the
    dependency is owner-installed and never imported at module load)."""
    import whisper  # type: ignore  # local dependency, not in requirements

    wmodel = whisper.load_model(model)
    result = wmodel.transcribe(path)
    return str(result.get("text", "")).strip()


def transcribe_whisper_cpp(path: str, binary: str, model: str) -> str:
    """Transcribe locally by shelling out to a whisper.cpp CLI binary. Expects the
    binary to print the transcript to stdout (`-nt`/no-timestamps, `-otxt` off)."""
    out = subprocess.run(
        [binary, "-m", model, "-f", path, "-nt"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def transcribe(path: str, engine: str, model: str, binary: Optional[str] = None) -> str:
    """Dispatch to the selected LOCAL engine. Raises on an unknown engine."""
    if engine == "openai-whisper":
        return transcribe_openai_whisper(path, model)
    if engine == "whisper.cpp":
        if not binary:
            raise ValueError("--binary is required for --engine whisper.cpp")
        return transcribe_whisper_cpp(path, binary, model)
    raise ValueError(f"unknown engine {engine!r} (expected 'openai-whisper' or 'whisper.cpp')")


# ── Notion landing (same path as a typed journal page) ────────────────────────


def _chunk(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def build_notion_page_payload(
    database_id: str,
    date_str: str,
    transcript: str,
    source_file: str,
    duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """The Notion create-page body for a Solo Recording transcript.

    - Template = "Solo Recording" so ingestion stamps channel="solo_recording".
    - The transcript is the page BODY (same shape journal enrichment reads).
    - A POINTER to the source recording (filename + duration) is recorded as page
      properties — the audio/video file itself is NEVER uploaded here (#1573 AC2).
    """
    props: dict[str, Any] = {
        "Date": {"date": {"start": date_str}},
        "Template": {"select": {"name": SOLO_TEMPLATE}},
        # Pointer only — where the recording lives, not the recording itself.
        "Source File": {"rich_text": [{"text": {"content": os.path.basename(source_file)}}]},
    }
    if duration_seconds is not None:
        props["Duration (s)"] = {"number": duration_seconds}

    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        }
        for chunk in _chunk(transcript, _NOTION_TEXT_LIMIT)
    ]
    return {"parent": {"database_id": database_id}, "properties": props, "children": children}


def post_to_notion(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Create the page via the Notion REST API (urllib — no requests, per repo
    convention). Returns the parsed response JSON."""
    req = urllib.request.Request(
        f"{NOTION_API}/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 — fixed https Notion host
        return json.loads(resp.read().decode("utf-8"))


# ── CLI ───────────────────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Locally transcribe a solo recording and land it as a Solo Recording journal entry (#1573)."
    )
    parser.add_argument("audio_file", help="Path to the local audio/video file (never uploaded — transcribed on-device).")
    parser.add_argument("--engine", choices=["openai-whisper", "whisper.cpp"], default="openai-whisper", help="Local Whisper engine.")
    parser.add_argument("--model", default="base", help="Whisper model (openai-whisper name, or a whisper.cpp .bin path).")
    parser.add_argument("--binary", help="Path to the whisper.cpp CLI binary (required for --engine whisper.cpp).")
    parser.add_argument("--date", default=None, help="Entry date YYYY-MM-DD (default: today, UTC).")
    parser.add_argument("--out", help="Also write the transcript text to this file.")
    parser.add_argument("--post-to-notion", action="store_true", help="Create the Solo Recording Notion page.")
    parser.add_argument("--dry-run", action="store_true", help="With --post-to-notion, print the payload instead of posting.")
    parser.add_argument(
        "--database-id", default=os.environ.get("NOTION_DATABASE_ID"), help="Notion journal database id (or env NOTION_DATABASE_ID)."
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.audio_file):
        print(f"error: no such file: {args.audio_file}", file=sys.stderr)
        return 2

    date_str = args.date or _today()
    print(
        f"[transcribe_solo] transcribing {args.audio_file} locally via {args.engine} ({args.model}) — audio stays on-device...",
        file=sys.stderr,
    )
    transcript = transcribe(args.audio_file, args.engine, args.model, binary=args.binary)
    if not transcript:
        print("error: empty transcript (nothing to land)", file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(transcript + "\n")
        print(f"[transcribe_solo] wrote transcript → {args.out}", file=sys.stderr)

    if not args.post_to_notion:
        print(transcript)
        return 0

    database_id = args.database_id
    if not database_id:
        print("error: --database-id (or NOTION_DATABASE_ID) required to post", file=sys.stderr)
        return 2

    duration = probe_duration_seconds(args.audio_file)
    payload = build_notion_page_payload(database_id, date_str, transcript, args.audio_file, duration_seconds=duration)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        print("error: NOTION_API_KEY env var required to post to Notion", file=sys.stderr)
        return 2
    resp = post_to_notion(payload, api_key)
    print(f"[transcribe_solo] created Notion page {resp.get('id', '?')} (channel={SOLO_CHANNEL}, date={date_str})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
