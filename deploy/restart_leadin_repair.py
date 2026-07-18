#!/usr/bin/env python3
"""
restart_leadin_repair.py — one-time (but durable + idempotent) content repair for
pre-launch-calendar chronicle records whose DDB content fields are S3 POINTERS.

WHY: the cycle-5 pre-launch calendar (deploy/restart_chronicle_handler.py
PRELAUNCH_CALENDAR) resurrects DATE#2026-02-28 "Before the Numbers" — THE
introduction piece — but its DDB record's content_markdown/content_html is just
the pointer string "See S3: blog/week-00.html". restart_leadin_pages.py renders
pages from the record's content fields, so a pointer-only record would render a
three-word public page. This script pulls the real ~1470-word article from the
S3 chronicle archive, extracts the prose body, VETS it (date-agnostic rule +
privacy absolutes — see VET_EDITS), converts it to the same content_html /
content_markdown shape the other lead-in records carry, and writes it back to
the DDB record.

SAFETY: the ORIGINAL record is backed up FIRST — to
/tmp/leadin_backups/<sk>.json (LOCAL ONLY — original records are UNVETTED and must never
be committed to the public repo; the durable backup is the private S3 copy) AND
s3://matthew-life-platform/remediation-log/leadin-backups/<sk>.json — matching
the existing DATE#2026-02-22 / DATE#2026-03-03 backup pattern. An existing
backup is NEVER overwritten (the first backup is the pre-repair truth).

VET RULES applied (each edit must match EXACTLY ONCE or the run aborts —
a changed archive source means the edits need re-review, not silent skips):
  - DATE-AGNOSTIC (restart_chronicle_handler.py calendar docstring): no calendar
    dates, months, seasons, holidays — the reset re-dates the record every cycle.
  - PRIVACY: no named vices, no genome specifics, no real public figures
    (tests/test_no_real_names_in_chronicle.py; the Board passage is recast onto
    the fictional roster: Reyes/Nakamura/Webb/Park), no named private persons,
    no exact chronological age (PhenoAge Option A keeps it off the live site).

Idempotent: a record whose content is already real prose (not a pointer) is
reported "already-repaired" and left untouched; --force re-applies from S3.

Usage:
    python3 deploy/restart_leadin_repair.py            # dry-run
    python3 deploy/restart_leadin_repair.py --apply    # backup + write DDB
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
TABLE = "life-platform"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
LOCAL_BACKUP_DIR = Path("/tmp") / "leadin_backups"  # never in-repo: originals are unvetted (privacy)
S3_BACKUP_PREFIX = "remediation-log/leadin-backups/"

# A content field at/below this length (or starting "See S3:") is a pointer, not prose.
POINTER_MAX_LEN = 200

# ── The repair registry — one entry per pointer-only lead-in record ──────────
REPAIRS = {
    "DATE#2026-02-28": {
        # Archive locations for the real article HTML, tried in order.
        "s3_sources": [
            "dashboard/chronicle/archive/pilot/posts/week-00/index.html",
            "blog/archive/pilot/week-00.html",
        ],
        "title": "Before the Numbers",
        # h1 mirrors DATE#2026-02-22's "The Measured Life — <label>: "<title>"" shape.
        "h1": 'The Measured Life — Prologue: "Before the Numbers"',
        "byline": "By Elena Voss | Seattle, WA",
        # Replaces "Prologue | February 2026 | Seattle, WA" (month+year = date-bound).
        "stats_line": "Prologue | Before Day 1 | Seattle, WA",
        # #1219: a dated editor's note reconciling Part I's PRE-PLAN numbers with the
        # frozen plan in Part II ("The Plan, On the Record"). "Before the Numbers" was
        # drafted early — it quotes ~302 lb / 1,800 kcal / 190 g, the working figures at
        # the time; the plan Matthew committed to is 315.65 lb / 1,500 kcal / 170 g. Rather
        # than silently rewrite a dated artifact (ADR-104), we annotate it: honesty-preserving,
        # reusing the chronicle's Margaret-Calloway editor's-note device (a signed blockquote,
        # cf. lambdas/margaret_editor_pass.splice_editors_note). DATE-AGNOSTIC on purpose —
        # the reset re-dates this record every cycle, so the note anchors to "Day 1" and to
        # Part II's TITLE, never a calendar date (no month/year → passes _FORBIDDEN_AFTER_VET).
        "editors_note": (
            "Filed in the days before Day 1, while the plan was still taking shape. The starting "
            "weight, calorie target, and protein figure quoted below were Matthew's working numbers "
            "at the time — the figures that actually govern the experiment are the ones he put on "
            "the record days later, in “The Plan, On the Record.” This dispatch is preserved "
            "as written: an honest snapshot from before the plan was frozen."
        ),
        # (name, exact-old, new) — each must occur EXACTLY ONCE in the extracted body.
        "vet_edits": [
            (
                "date-agnostic: season+year",
                "But sometime in the fall of 2025, something shifted.",
                "But somewhere in the year before this experiment, something shifted.",
            ),
            (
                "date-agnostic: month",
                "I pitched this series to myself on a Tuesday in February after a friend",
                "I pitched this series to myself on an ordinary Tuesday after a friend",
            ),
            (
                "privacy: exact age + named private person",
                "Matthew is thirty-seven. He lives with his girlfriend, Brittany, in Seattle.",
                "Matthew is in his late thirties. He lives with his girlfriend in Seattle.",
            ),
            (
                "privacy: named vices",
                "It even tracks vices: alcohol, late-night screens, processed food. Each vice held is a streak extended.",
                "It even tracks vices — a personal short list he is trying to hold the line on. Each vice held is a streak extended.",
            ),
            (
                "privacy: real public figures → fictional Board roster",
                "He has a simulated Board of Directors — AI personas modeled after Peter Attia, Andrew Huberman, "
                "Layne Norton, Matthew, and others — who review his data and provide commentary. Attia is precise "
                "and slightly intimidating. Huberman is enthusiastic and occasionally tangential. Norton is blunt. "
                "Walker is gentle but firm about sleep debt.",
                "He has a simulated Board of Directors — fictional AI advisor personas, each configured deep into a "
                "single domain — who review his data and provide commentary. Dr. Reyes is precise and slightly "
                "intimidating. Dr. Nakamura is enthusiastic and occasionally tangential. Dr. Webb is blunt. "
                "Dr. Park is gentle but firm about sleep debt.",
            ),
        ],
    },
}


def is_pointer_record(item: dict) -> bool:
    """True when BOTH content fields are pointers/blank (short or 'See S3:')."""

    def _pointer(v: str) -> bool:
        v = (v or "").strip()
        return len(v) <= POINTER_MAX_LEN or v.startswith("See S3:")

    return _pointer(item.get("content_markdown", "")) and _pointer(item.get("content_html", ""))


def extract_prose_body(page_html: str) -> str:
    """The article body: contents of the FIRST <div class="prose"> up to its
    closing </div></article>. (The archived week-00 file carries a duplicated
    trailing shell — the first prose div is the real article.)"""
    m = re.search(r'<div class="prose">\s*(.*?)\s*</div>\s*</article>', page_html, re.DOTALL)
    if not m:
        raise RuntimeError('Could not locate the <div class="prose">…</div></article> body in the archived page')
    return m.group(1).strip()


def apply_vet_edits(body: str, vet_edits: list[tuple[str, str, str]]) -> tuple[str, list[str]]:
    """Apply each (name, old, new) edit; ABORT if an old-string doesn't occur
    exactly once (a changed source needs human re-review, not a silent partial vet)."""
    applied = []
    for name, old, new in vet_edits:
        n = body.count(old)
        if n != 1:
            raise RuntimeError(f"vet edit {name!r}: expected exactly 1 occurrence, found {n} — archive source changed, re-review needed")
        body = body.replace(old, new)
        applied.append(name)
    return body, applied


_FORBIDDEN_AFTER_VET = [
    # date-bound tokens (the calendar re-dates this record every cycle)
    "January",
    "February",
    "March",
    "April",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
    " 2025",
    " 2026",
    "spring",
    "summer",
    "autumn",
    "fall of",
    "winter",
    "Valentine",
    "Christmas",
    "Thanksgiving",
    # privacy absolutes
    "Attia",
    "Huberman",
    "Norton",
    "Brittany",
    "alcohol",
    "marijuana",
    "genome",
    "gene ",
    "thirty-seven",
]


def assert_vetted(body: str):
    hits = [t for t in _FORBIDDEN_AFTER_VET if t.lower() in body.lower()]
    if hits:
        raise RuntimeError(f"vetted body still contains forbidden token(s): {hits}")


def html_body_to_markdown(body_html: str) -> str:
    """Convert the limited chronicle tag set (<p>, <hr>, <blockquote>, <em>,
    <strong>, <p class="signature">) to the markdown shape the other lead-in
    records carry (and that restart_leadin_pages/body_markdown_from_record parses)."""
    out = []
    for m in re.finditer(r"<(p|hr|blockquote)([^>]*)>(.*?)</\1>|<hr\s*/?>", body_html, re.DOTALL):
        tag = m.group(1)
        attrs = m.group(2) or ""
        inner = (m.group(3) or "").strip()
        if tag is None or tag == "hr":
            out.append("---")
            continue
        text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", inner, flags=re.DOTALL)
        text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if tag == "blockquote":
            out.append(f"> {text}")
        elif "signature" in attrs:
            # signature already carries the *…* emphasis from the <em> conversion
            out.append(text if text.startswith("*") else f"*{text}*")
        else:
            out.append(text)
    return "\n\n".join(out)


def render_editors_note(note: str) -> tuple[str, str]:
    """(html, markdown) for a Margaret-Calloway editor's note, or ('', '') when empty.

    Reuses the chronicle's existing device (lambdas/margaret_editor_pass.splice_editors_note):
    a signed blockquote. The HTML form is a <blockquote> so restart_leadin_pages renders it
    with the same ember-rule prose styling every chronicle blockquote gets; the markdown form
    is the identical '> **Editor's note — Margaret Calloway:** …' the live weekly path emits."""
    note = (note or "").strip()
    if not note:
        return "", ""
    note_html = f'<blockquote class="editors-note"><strong>Editor\'s note — Margaret Calloway:</strong> {note}</blockquote>\n'
    note_md = f"> **Editor's note — Margaret Calloway:** {note}\n\n"
    return note_html, note_md


def build_content_fields(repair: dict, vetted_body_html: str) -> tuple[str, str, int]:
    """(content_html, content_markdown, word_count) in the DATE#2026-02-22 shape:
    html = <h1> + byline <p> + <hr> + [editor's note] + prose; markdown = # h1 + *byline*
    + --- + [editor's note] + prose. The optional editor's note (#1219) sits at the TOP of
    the body — a binge reader meets the reconciliation before the pre-plan numbers, and it
    survives the leadin-pages header strip (which removes only the h1/byline/hr chrome)."""
    note_html, note_md = render_editors_note(repair.get("editors_note", ""))
    content_html = (
        f"<h1>{repair['h1']}</h1>\n" f'<p class="byline"><em>{repair["byline"]}</em></p>\n' f"<hr>\n{note_html}{vetted_body_html}"
    )
    body_md = html_body_to_markdown(vetted_body_html)
    content_markdown = f"# {repair['h1']}\n\n*{repair['byline']}*\n\n---\n\n{note_md}{body_md}"
    # word_count is the ARTICLE body only (read-time estimate), editor's-note chrome excluded.
    word_count = len(body_md.split())
    return content_html, content_markdown, word_count


def backup_record(sk: str, raw_item_ddb_json: dict, s3, apply: bool) -> list[str]:
    """Write the pre-repair record to the local + S3 backup locations, matching the
    existing pattern ({"Item": <DynamoDB-JSON>}). NEVER overwrites an existing backup."""
    doc = json.dumps({"Item": raw_item_ddb_json}, indent=1, default=str)
    notes = []
    local = LOCAL_BACKUP_DIR / f"{sk}.json"
    if local.exists():
        notes.append(f"local backup exists, kept: {local.relative_to(REPO_ROOT)}")
    elif apply:
        LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        local.write_text(doc)
        notes.append(f"local backup written: {local.relative_to(REPO_ROOT)}")
    else:
        notes.append(f"would write local backup: {local.relative_to(REPO_ROOT)}")

    s3_key = f"{S3_BACKUP_PREFIX}{sk}.json"
    exists = True
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            exists = False
        else:
            raise
    if exists:
        notes.append(f"S3 backup exists, kept: s3://{S3_BUCKET}/{s3_key}")
    elif apply:
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=doc.encode(), ContentType="application/json")
        notes.append(f"S3 backup written: s3://{S3_BUCKET}/{s3_key}")
    else:
        notes.append(f"would write S3 backup: s3://{S3_BUCKET}/{s3_key}")
    return notes


def fetch_archive_html(s3, sources: list[str]) -> tuple[str, str]:
    for key in sources:
        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read().decode("utf-8")
            return key, body
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                continue
            raise
    raise RuntimeError(f"None of the archive sources exist: {sources}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument("--force", action="store_true", help="Re-apply even if the record no longer looks like a pointer")
    args = parser.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] lead-in pointer-record repair ({len(REPAIRS)} registered)")

    s3 = boto3.client("s3", region_name=REGION)
    ddb_client = boto3.client("dynamodb", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    now_iso = datetime.now(timezone.utc).isoformat()
    failures = 0

    for sk, repair in REPAIRS.items():
        print(f"\n── {sk} · \"{repair['title']}\" ──")
        raw = ddb_client.get_item(TableName=TABLE, Key={"pk": {"S": CHRONICLE_PK}, "sk": {"S": sk}})
        if "Item" not in raw:
            print("  ERROR: record not found")
            failures += 1
            continue
        item = table.get_item(Key={"pk": CHRONICLE_PK, "sk": sk}).get("Item", {})
        if not is_pointer_record(item) and not args.force:
            print(f"  already-repaired (content_markdown is {len(item.get('content_markdown', ''))} chars) — skipping (--force to redo)")
            continue

        # 1. Backup FIRST (original DynamoDB-JSON, never clobbered).
        for note in backup_record(sk, raw["Item"], s3, args.apply):
            print(f"  {note}")

        # 2. Pull + extract + vet + convert.
        src_key, page_html = fetch_archive_html(s3, repair["s3_sources"])
        body = extract_prose_body(page_html)
        vetted, applied = apply_vet_edits(body, repair["vet_edits"])
        assert_vetted(vetted)
        content_html, content_markdown, word_count = build_content_fields(repair, vetted)
        print(f"  source: s3://{S3_BUCKET}/{src_key}")
        print(f"  extracted {len(body.split())} words → vetted ({len(applied)} edits) → {word_count} words of markdown")
        for name in applied:
            print(f"    vet: {name}")

        # 3. Write back (content + date-agnostic stats_line; flags/date untouched —
        #    the chronicle handler owns tombstone/phase/date).
        if args.apply:
            table.update_item(
                Key={"pk": CHRONICLE_PK, "sk": sk},
                UpdateExpression=(
                    "SET content_html = :h, content_markdown = :m, stats_line = :s, "
                    "word_count = :w, repaired_at = :ts, repaired_from = :src"
                ),
                ExpressionAttributeValues={
                    ":h": content_html,
                    ":m": content_markdown,
                    ":s": repair["stats_line"],
                    ":w": word_count,
                    ":ts": now_iso,
                    ":src": f"s3://{S3_BUCKET}/{src_key}",
                },
            )
            print(f"  WROTE repaired content to {sk} (stats_line: {repair['stats_line']!r})")
        else:
            print(f"  (dry-run) would write repaired content to {sk} (stats_line: {repair['stats_line']!r})")

    if failures:
        print(f"\n{failures} repair(s) FAILED")
        sys.exit(1)
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
