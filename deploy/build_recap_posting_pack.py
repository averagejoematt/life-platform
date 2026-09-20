"""build_recap_posting_pack.py — the Instagram posting pack, on the Desktop (#3741).

WHAT IT IS

The recap cards are rendered by `recap-card-generator` and STORED — the PNG under
`recap/` in S3, the row under `USER#matthew#SOURCE#recap_cards` in DynamoDB. This script
turns that stored set into a folder the owner can post from by hand, one sub-folder per
post, in posting order:

    ~/Desktop/averagejoematt-cards/
      00-day-00/     card.png        caption.txt
      01-day-01/     card-1of2.png   card-2of2.png   caption-1of2.txt  caption-2of2.txt
      ...
      08-week-01/    card.png        caption.txt              (after every 7th day)
      CHECKLIST.md   one line per post, to tick as he posts
      airdrop/       the same PNGs flattened + captions.txt   (one AirDrop to the phone)

It READS ONLY. Nothing here renders, re-renders, stores or posts — the cards must already
exist, and a date whose row is missing or unrendered is reported in the checklist as a
gap rather than silently skipped. Nothing here talks to Instagram.

WHY IT LIVES IN THE REPO

It was written in a session scratchpad under /private/tmp on 2026-09-19 and came within a
tmp purge of being lost with the session that wrote it. The cards themselves are always
regenerable from the stored rows; this script was the only unique artefact in that
directory.

THE ONE BEHAVIOUR THAT CHANGED ON THE WAY IN

The original opened with an unconditional `shutil.rmtree(OUT)`. Re-running it over an
existing pack therefore destroyed a ticked CHECKLIST.md and anything else added by hand
alongside it. It now refuses a non-empty target, and `--force` MOVES the old pack aside
to a timestamped sibling rather than deleting it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
import pathlib
import shutil
import sys

import boto3
from boto3.dynamodb.conditions import Key

BUCKET = "matthew-life-platform"
TABLE = "life-platform"
REGION = "us-west-2"
PARTITION = "USER#matthew#SOURCE#recap_cards"

#: The owner writes the one human sentence on every post; the generated caption carries
#: the numbers under it. The placeholder is deliberately impossible to post by accident.
YOUR_LINE = "[your one line here — the only sentence on the post that is yours]\n\n"

HASHTAGS = "#themeasuredlife #proofnotpromises #quantifiedself #weightlossjourney #buildinpublic"


def _num(v):
    """DynamoDB hands back Decimal; captions want a plain number."""
    return float(v) if isinstance(v, decimal.Decimal) else v


def _weekly_caption(week: int, totals: dict) -> str:
    t = {k: _num(v) for k, v in (totals or {}).items()}
    bits = [f"Week {week} · the experiment"]
    delta = t.get("weight_delta")
    line = ""
    if delta is not None:
        line += f"{abs(delta):.1f} lb {'down' if delta < 0 else 'up'} this week, scale to scale. "
    line += f"{t.get('sessions', 0):g} sessions, {t.get('sets', 0):g} sets, habits {t.get('habit_pct', 0):g}%."
    if t.get("misses"):
        line += f" Biggest miss: {t['misses']}."
    bits += [line, "averagejoematt.com", HASHTAGS]
    return "\n".join(bits) + "\n"


def _prepare(out: pathlib.Path, force: bool) -> None:
    """Never destroy a pack in place — a ticked CHECKLIST.md is the owner's own work."""
    if not out.exists() or not any(out.iterdir()):
        out.mkdir(parents=True, exist_ok=True)
        return
    if not force:
        sys.exit(
            f"refusing: {out} already exists and is not empty.\n"
            f"  Pass --force to move it aside to a timestamped sibling and rebuild,\n"
            f"  or pass --out with a new path."
        )
    aside = out.with_name(f"{out.name}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}")
    shutil.move(str(out), str(aside))
    print(f"moved the existing pack aside -> {aside}")
    out.mkdir(parents=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="~/Desktop/averagejoematt-cards", help="pack directory (default: %(default)s)")
    ap.add_argument("--force", action="store_true", help="move an existing pack aside and rebuild")
    ap.add_argument("--no-airdrop", action="store_true", help="skip the flattened airdrop/ folder")
    ap.add_argument("dates", nargs="+", metavar="YYYY-MM-DD", help="PT dates, in posting order")
    args = ap.parse_args()

    out = pathlib.Path(args.out).expanduser()
    _prepare(out, args.force)

    s3 = boto3.client("s3", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    rows = {i["sk"][5:]: i for i in table.query(KeyConditionExpression=Key("pk").eq(PARTITION)).get("Items", [])}

    check: list[str] = []
    n = 0

    def folder(slug: str) -> pathlib.Path:
        nonlocal n
        d = out / f"{n:02d}-{slug}"
        d.mkdir()
        n += 1
        return d

    def pull(key: str, dest: pathlib.Path) -> None:
        s3.download_file(BUCKET, key, str(dest))

    for date in args.dates:
        r = rows.get(date)
        if not r or r.get("outcome") not in ("rendered", "sent"):
            # A gap is reported, never skipped — a missing day the owner cannot see is a
            # day he assumes posted.
            check.append(f"[!] {date}: no stored card ({(r or {}).get('outcome')})")
            continue
        day_n = int(r.get("day_n") or 0)
        f = folder(f"day-{day_n:02d}")
        if r.get("detail_s3_key"):
            pull(r["s3_key"], f / "card-1of2.png")
            pull(r["detail_s3_key"], f / "card-2of2.png")
            (f / "caption-1of2.txt").write_text(YOUR_LINE + (r.get("caption") or "") + "\n")
            (f / "caption-2of2.txt").write_text((r.get("detail_caption") or "") + "\n")
            check.append(f"[ ] {f.name}  ·  1 of 2 = {r.get('beat')}  ·  2 of 2 = the detail  " f"(post as ONE carousel: slide 1, slide 2)")
        else:
            pull(r["s3_key"], f / "card.png")
            (f / "caption.txt").write_text(YOUR_LINE + (r.get("caption") or "") + "\n")
            check.append(f"[ ] {f.name}  ·  {r.get('beat')}")

        wk = r.get("weekly") or {}
        if wk.get("s3_key"):
            week = int(wk["week"])
            g = folder(f"week-{week:02d}")
            pull(wk["s3_key"], g / "card.png")
            (g / "caption.txt").write_text(YOUR_LINE + _weekly_caption(week, wk.get("totals") or {}))
            check.append(f"[ ] {g.name}  ·  the reckoning (single post)")

    (out / "CHECKLIST.md").write_text(
        "# @AverageJoeMatt — posting checklist\n\n"
        "Post in folder order. Each daily folder is ONE carousel (slide 1, slide 2). "
        "Tick as you post; nothing here posts itself.\n\n" + "\n".join(check) + "\n"
    )

    if not args.no_airdrop:
        drop = out / "airdrop"
        drop.mkdir()
        caps: list[str] = []
        for d in sorted(p for p in out.iterdir() if p.is_dir() and p.name != "airdrop"):
            for png in sorted(d.glob("*.png")):
                suffix = "" if png.stem == "card" else png.stem.removeprefix("card")
                shutil.copy2(png, drop / f"{d.name}{suffix}.png")
            for txt in sorted(d.glob("*.txt")):
                caps.append(f"───── {d.name} · {txt.name} " + "─" * 20 + "\n" + txt.read_text())
        (drop / "captions.txt").write_text("\n".join(caps))

    print(f"{n} folders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
