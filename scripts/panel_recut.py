#!/usr/bin/env python3
"""scripts/panel_recut.py — re-cut ONE published Panel episode from a corrected transcript (#5949).

OWNER ACT. Dry-run is the default and writes nothing to AWS; ``--apply`` re-voices the episode and republishes it.

Why this exists: the only other path that voices a transcript from a file is ``scripts/season_promote.py``, and its
panel step rebuilds episodes.json from the weeks it is given and re-seeds the Panel's state and show memory — run for
one week it would drop every other episode from the index. A re-cut changes the words of one episode and nothing else.

What ``--apply`` does, in order, every write through a function the Panel already owns:

  1. GATE     every line of the corrected transcript goes through the Panel's own fail-closed safety gate
              (``coach_panel_podcast_lambda._safety_gate`` — the spoken-weight rule included). One hit refuses the run.
  2. SHAPE    the corrected transcript must have the live one's turns and speakers: a re-cut edits lines, it does not
              restructure the episode. The changed turns are printed.
  3. BACKUP   the live audio, both transcripts and episodes.json → ``--backup-dir``.
  4. VOICE    ``gemini_tts.synthesize_dialogue`` with the Panel's own voices and style.
  5. PUBLISH  ``_publish_episode_audio`` (brand open, encode, PUT). The new audio must land on the SAME key as the old
              cut — ``generated/*`` is delete-protected, so an old file left at its own URL stays public. A different
              extension stops the run before anything is written.
  6. TEXT     wk<N>.transcript.txt and wk<N>.transcript.json.
  7. INDEX    this week's row gets the new byte count and duration; every other row, and the retired list, is carried
              over as it is. ``_write_indexes`` rewrites episodes.json + feed.xml and invalidates /panelcast/*.

It never touches DynamoDB: the series state, the bet ledger and the show memory stay as they are.

    python3 scripts/panel_recut.py --week 0 --transcript <corrected.json>            # the plan, nothing written
    python3 scripts/panel_recut.py --week 0 --transcript <corrected.json> --apply    # owner-approved re-cut

The corrected transcript is the published shape: ``{"week": N, "turns": [{"speaker": "<label>", "line": "..."}]}``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

REGION = "us-west-2"
TABLE = "life-platform"
BUCKET = "matthew-life-platform"
PANEL_PREFIX = "generated/panelcast"


def load_transcript(path: str, week: int) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or doc.get("week") != week:
        raise SystemExit(f"{path}: not the week {week} transcript (week={doc.get('week') if isinstance(doc, dict) else None!r})")
    turns = [{"speaker": str(t.get("speaker") or ""), "line": str(t.get("line") or "").strip()} for t in doc.get("turns") or []]
    if not turns or any(not t["speaker"] or not t["line"] for t in turns):
        raise SystemExit(f"{path}: every turn needs a speaker and a line")
    return turns


def gate_findings(turns: List[Dict[str, str]], safety_gate: Any) -> List[str]:
    """Each line through the Panel's own safety gate. Empty = clean."""
    return [
        f"turn {i} ({t['speaker']}): {', '.join(reasons)}" for i, t in enumerate(turns) for reasons in [safety_gate(t["line"])] if reasons
    ]


def shape_findings(live: List[Dict[str, Any]], new: List[Dict[str, str]]) -> List[str]:
    """A re-cut keeps the episode's turns and speakers. Empty = same shape."""
    if len(live) != len(new):
        return [f"the live transcript has {len(live)} turns, the corrected one has {len(new)}"]
    return [
        f"turn {i}: speaker {b['speaker']!r} is {a.get('speaker')!r} in the live transcript"
        for i, (a, b) in enumerate(zip(live, new))
        if a.get("speaker") != b["speaker"]
    ]


def changed_turns(live: List[Dict[str, Any]], new: List[Dict[str, str]]) -> List[int]:
    return [i for i, (a, b) in enumerate(zip(live, new)) if str(a.get("line") or "").strip() != b["line"]]


def recut_row(row: Dict[str, Any], published: Dict[str, Any]) -> Dict[str, Any]:
    """The week's index row after the re-cut: the new audio's size and length, everything else as it was."""
    return {**row, "bytes": published["bytes"], "duration_sec": published["duration_sec"]}


def _same_key_encoder(audio_encode: Any, ext: str) -> Any:
    """Wrap the encoder so the publish lands on the old cut's key, or stops before the PUT."""
    original = audio_encode.compress_wav

    def compress(wav_bytes: bytes, *a: Any, **k: Any) -> tuple:
        if ext == "wav":
            return (wav_bytes, "wav", "audio/wav")
        out = original(wav_bytes, *a, **k)
        if out[1] != ext:
            raise SystemExit(
                f"the encoder produced .{out[1]} but the published cut is .{ext} — nothing was written. The old file would "
                "stay public at its own URL (generated/* is delete-protected). Install the encoder (pip install lameenc) and re-run."
            )
        return out

    return compress


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--transcript", required=True, help="the corrected transcript, in the published wk<N>.transcript.json shape")
    ap.add_argument("--backup-dir", default=None, help="default: <transcript dir>/backup")
    ap.add_argument("--apply", action="store_true", help="OWNER ACT: re-voice and republish")
    args = ap.parse_args(argv)
    wk = args.week
    for k, v in {
        "TABLE_NAME": TABLE,
        "S3_BUCKET": BUCKET,
        "USER_ID": "matthew",
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
    }.items():
        os.environ.setdefault(k, v)

    import boto3
    import coach_panel_podcast_lambda as panel
    from ai import audio_encode, gemini_tts

    s3 = boto3.client("s3", region_name=REGION)
    turns = load_transcript(args.transcript, wk)
    index = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{PANEL_PREFIX}/episodes.json")["Body"].read())
    episodes = index.get("episodes") or []
    row = next((e for e in episodes if e.get("week") == wk), None)
    if not row:
        raise SystemExit(f"week {wk} is not a published episode in episodes.json — there is nothing to re-cut")
    audio_key = f"{PANEL_PREFIX}/{row['url'].rsplit('/', 1)[-1]}"
    ext = audio_key.rsplit(".", 1)[-1]
    live = json.loads(s3.get_object(Bucket=BUCKET, Key=f"{PANEL_PREFIX}/wk{wk}.transcript.json")["Body"].read()).get("turns") or []

    refusals = gate_findings(turns, panel._safety_gate) + shape_findings(live, turns)
    labels = sorted({t["speaker"] for t in turns})
    if set(labels) != {"Elena", row.get("guest_name")}:
        refusals.append(f"speakers {labels} are not Elena and the episode's guest {row.get('guest_name')!r}")
    changed = changed_turns(live, turns)
    print(
        json.dumps({"week": wk, "title": row.get("title"), "audio_key": audio_key, "turns": len(turns), "changed_turns": changed}, indent=1)
    )
    for i in changed:
        print(f"\n--- turn {i} ({turns[i]['speaker']}) live\n{live[i].get('line')}\n+++ turn {i} re-cut\n{turns[i]['line']}")
    for r in refusals:
        print(f"REFUSING: {r}")
    if refusals:
        return 3
    if not changed:
        print("\nThe corrected transcript is the live one — nothing to re-cut.")
        return 0
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply (owner act).")
        return 0

    dest = args.backup_dir or os.path.join(os.path.dirname(os.path.abspath(args.transcript)), "backup")
    os.makedirs(dest, exist_ok=True)
    for key in (
        audio_key,
        f"{PANEL_PREFIX}/wk{wk}.transcript.json",
        f"{PANEL_PREFIX}/wk{wk}.transcript.txt",
        f"{PANEL_PREFIX}/episodes.json",
    ):
        s3.download_file(BUCKET, key, os.path.join(dest, f"wk{wk}_before_{key.rsplit('/', 1)[-1]}"))
    print(f"BACKUP → {dest}")

    voices = {"Elena": panel._gemini_voice(panel.ELENA), row["guest_name"]: panel._gemini_voice(row["guest_id"])}
    audio = None
    for attempt in range(3):  # the TTS vendor read can time out on a long episode
        try:
            audio = gemini_tts.synthesize_dialogue(turns, voices, panel.WEEKLY_STYLE)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"wk{wk}: synthesis attempt {attempt + 1} failed: {exc}")
    if audio is None:
        raise SystemExit(f"wk{wk}: synthesis failed 3 times — nothing was written; re-run")
    audio_encode.compress_wav = _same_key_encoder(audio_encode, ext)
    published = panel._publish_episode_audio(wk, audio)
    if published["url"] != row["url"]:
        raise SystemExit(
            f"the re-cut published to {published['url']}, not {row['url']} — the old cut is still public; stop and fix by hand"
        )
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{PANEL_PREFIX}/wk{wk}.transcript.txt",
        Body="\n\n".join(f"{t['speaker']}: {t['line']}" for t in turns).encode(),
        ContentType="text/plain; charset=utf-8",
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{PANEL_PREFIX}/wk{wk}.transcript.json",
        Body=json.dumps({"week": wk, "turns": turns}).encode(),
        ContentType="application/json",
    )
    panel._write_indexes([recut_row(e, published) if e.get("week") == wk else e for e in episodes])
    print(f"wk{wk} RE-CUT → {published['url']} ({published['bytes']} bytes, {published['duration_sec']}s); transcripts and index rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
