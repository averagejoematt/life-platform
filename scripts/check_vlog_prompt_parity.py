#!/usr/bin/env python3
"""check_vlog_prompt_parity.py — is the phone running the same interview as Claude Code? (#1571)

`.claude/commands/vlog.md` is upstream; the claude.ai Project prompt inside the
PRIVATE studio kit (`s3://matthew-life-platform/config/studio/VLOG_STUDIO_KIT.md`)
is a Matthew-side condensation of it. `docs/coaching/CHAT_MODES.md` §"claude.ai vs.
Claude Code" already says those two surfaces CAN drift and that the drift is only
caught by eye. This script is the eye.

Why it matters: #1571 AC1 is about the PHONE ("one sentence starts a session in
claude.ai (phone) or Claude Code"). When the condensation goes stale, the phone
— the surface that actually sits next to the Luna — silently runs a weaker
interview than the repo file promises. That is invisible to every existing gate,
because the kit is deliberately not in git (the repo is public).

Split of duties, so nothing private lands in git:
  - the CHECKLIST below (rule names + the keywords a condensation must carry)
    lives here, in the public repo — it is a list of rule NAMES, no content;
  - the prompt text itself stays in private S3 and is only ever read, never
    written, never echoed in full.

Usage (owner, needs AWS read creds — S3 GetObject only):

    python3 scripts/check_vlog_prompt_parity.py
    python3 scripts/check_vlog_prompt_parity.py --kit /path/to/local/kit.md
    python3 scripts/check_vlog_prompt_parity.py --json

Exit 0 = the condensation covers every load-bearing rule. Exit 1 = drift: it
names which rules the phone is missing so the re-condensation is a five-minute
edit rather than a re-read of the whole mode file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


def _skill_registry():
    """The ONE registry for Claude Code skills + agents (scripts/skill_registry.py)."""
    import importlib.util
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    _cands = [_os.path.join(_here, "skill_registry.py"), _os.path.join(_here, "..", "scripts", "skill_registry.py")]
    for _p in _cands:
        if _os.path.isfile(_p):
            spec = importlib.util.spec_from_file_location("_skill_registry", _p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("scripts/skill_registry.py not found")


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODE_FILE = str(_skill_registry().require_skill("vlog"))

KIT_BUCKET = "matthew-life-platform"
KIT_KEY = "config/studio/VLOG_STUDIO_KIT.md"


# ── The parity contract ───────────────────────────────────────────────────────
# Each rule is (id, anchor, keywords, why).
#
#   anchor   — a substring that MUST appear in .claude/commands/vlog.md. This is
#              what stops the checklist from rotting: if a rule is reworded or
#              dropped upstream, the anchor stops matching and the test reds, so
#              the checklist has to be updated deliberately rather than silently
#              describing a mode that no longer exists.
#   keywords — every one must appear (case-insensitively) somewhere in the
#              condensed Project prompt for the rule to count as carried.
#
# Rules are listed in the order a session encounters them.
CHECKLIST: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "zero-setup-open",
        "Open with ZERO questions asked of Matthew",
        ("get_capture_queues", "question one"),
        "AC1: the friction budget — the first response proposes a format AND asks question one.",
    ),
    (
        "diary-memory",
        "Also load the diary's own memory",
        ("manage_diary_claims",),
        "Step 0 reads the previous entry, due on-tape claims and pending coach reactions (#1841).",
    ),
    (
        "day-number-curve",
        "The day-number risk curve overrides the format library",
        ("micro", "bad day"),
        "The named failure mode: 'more day ones than I've had the twos'. Days 1-7 default to micro.",
    ),
    (
        "camera-protocol",
        "the priming happens in TEXT before the camera rolls",
        ("text", "voice", "push-to-talk"),
        "Prime in text, interview in voice; push-to-talk is load-bearing, not a preference.",
    ),
    (
        "engagement-blind",
        "The interview is engagement-blind",
        ("engagement",),
        "#1845 Goodhart rule: how a clip performed may pick a cut, never a question.",
    ),
    (
        "one-question",
        "One question at a time.",
        ("one question",),
        "Interview discipline: follow-ups on what he actually said, never a scripted list.",
    ),
    (
        "notion-close",
        '"date:Date:start"',
        ("date:Date:start", "Video Diary"),
        "AC3: the expanded date key and the exact Template select value.",
    ),
    (
        "footage-pointer",
        "`Footage:` pointer line",
        ("footage",),
        "AC3: the entry carries a private pointer to where the video went — never the video.",
    ),
    (
        "offer-never-assume",
        "offer, never assume",
        ("log_coach_checkin", "save_insight"),
        "The route-the-takeaways contract is an offer, not an autosave.",
    ),
    (
        "tape-note",
        "Emit the TAPE NOTE",
        ("tape note", "verbatim"),
        "3-5 VERBATIM moments the post-production desk string-matches into the whisper SRT.",
    ),
    (
        "on-tape-claims",
        "Register 0–3 on-tape claims",
        ("manage_diary_claims", "consent"),
        "#1841: consent PER CLAIM, silence means no, zero is a good number.",
    ),
    (
        "abort-writes-nothing",
        "Aborted/skipped session writes NOTHING",
        ("nothing", "failure"),
        "AC2 + ADR-104: a skipped session writes nothing and is never framed as a failure.",
    ),
)


def load_mode_text() -> str:
    with open(MODE_FILE, encoding="utf-8") as fh:
        return fh.read()


def formats_in_mode(mode_text: str) -> list[str]:
    """The format library's ids, derived from the mode file's own table.

    Derived, never hand-listed: adding an eighth format to the table
    automatically makes the phone prompt responsible for it.
    """
    table = re.findall(r"^\|\s*\*\*(\w+)\*\*\s*—", mode_text, re.MULTILINE)
    return list(dict.fromkeys(table))


def fetch_kit_from_s3() -> str:
    import boto3

    body = boto3.client("s3", region_name="us-west-2").get_object(Bucket=KIT_BUCKET, Key=KIT_KEY)["Body"]
    return body.read().decode("utf-8")


def check(mode_text: str, kit_text: str) -> dict:
    """Compare the condensed prompt against the contract. Returns a report dict."""
    haystack = kit_text.lower()

    missing_rules = []
    for rule_id, anchor, keywords, why in CHECKLIST:
        if anchor not in mode_text:
            # The checklist itself is stale — that is a harder failure than drift,
            # because it means this script is describing a mode that changed.
            missing_rules.append({"rule": rule_id, "kind": "stale_anchor", "detail": anchor, "why": why})
            continue
        absent = [k for k in keywords if k.lower() not in haystack]
        if absent:
            missing_rules.append({"rule": rule_id, "kind": "not_condensed", "detail": ", ".join(absent), "why": why})

    missing_formats = [f for f in formats_in_mode(mode_text) if f.lower() not in haystack]

    return {
        "formats_expected": formats_in_mode(mode_text),
        "formats_missing": missing_formats,
        "rules_checked": len(CHECKLIST),
        "rules_missing": missing_rules,
        "ok": not missing_rules and not missing_formats,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the claude.ai vlog Project prompt against .claude/commands/vlog.md")
    ap.add_argument("--kit", help="read the studio kit from a local path instead of private S3")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable report")
    args = ap.parse_args()

    mode_text = load_mode_text()
    try:
        kit_text = open(args.kit, encoding="utf-8").read() if args.kit else fetch_kit_from_s3()
    except Exception as e:  # noqa: BLE001 — an unreadable kit is a reportable state, not a traceback
        print(f"could not read the studio kit: {e}", file=sys.stderr)
        print("(needs AWS read creds, or pass --kit <path>)", file=sys.stderr)
        return 2

    report = check(mode_text, kit_text)

    if args.as_json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if report["ok"]:
        print(
            f"vlog Project prompt parity OK — {report['rules_checked']} rules, " f"{len(report['formats_expected'])} formats all carried."
        )
        return 0

    print("vlog Project prompt has DRIFTED from .claude/commands/vlog.md (the repo file is upstream).\n")
    if report["formats_missing"]:
        print(f"  formats not in the phone prompt: {', '.join(report['formats_missing'])}")
    for m in report["rules_missing"]:
        label = "checklist anchor no longer in vlog.md" if m["kind"] == "stale_anchor" else "missing from the phone prompt"
        print(f"  [{m['rule']}] {label}: {m['detail']}")
        print(f"      why it matters: {m['why']}")
    print("\nRe-condense the Project prompt in the private studio kit, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
