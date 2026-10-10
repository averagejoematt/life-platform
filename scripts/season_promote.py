#!/usr/bin/env python3
"""scripts/season_promote.py — publish a rebuilt season from staging, in order (#4537).

OWNER ACT. Dry-run is the default and writes nothing; ``--apply`` performs the publish the
owner approved. Every write goes through a path the platform already owns:

  1. BACKUP   every chronicle row, Panel state row, Panel S3 object and hold this run will
              touch → a local dir and the private s3://…/story-desk/backups/<ts>/ prefix.
  2. CHRONICLE  update each rebuilt installment's row in place (same sk, same URL slot):
              body, title, stats line, word count, a dated correction line on posts that
              had already published, and the stale draft_* fields + approval token removed
              so an old approve link can never republish a superseded draft. The prologue
              lead-in that described an earlier launch is marked ``unlisted`` (its URL stays
              alive; it leaves the reading list).
  3. LEDGER   one LEDGER#{date} row per installment — the season memory the next week reads.
  4. PAGES    deploy/restart_leadin_pages.run(apply=True) re-renders every journal page and
              the manifest from DDB through the live template (+ CloudFront invalidation).
  4b. EFFECTS  chronicle-approve's publish-time side effects through its OWN function
              (chronicle_approve_lambda.publish_side_effects, #4593): the share kit built from the rebuilt row and the
              recall index run; recap/ledger/panel/mark-published are declined because a step here owns them; delivery
              is declined — with a no-send decision stamped on the row — unless the owner passes --deliver.
              ``--effects-only --weeks N --apply`` re-runs just this for already-published rows (the week-4 repair).
  5. PANEL    synthesize each episode with the Panel's own voices and style, publish through
              its own audio publisher, write transcripts, rewrite episodes.json + feed.xml
              through its own index writer, delete the holds and the July placeholder stubs,
              and seed a cycle-17 STATE#current + SHOW#memory so the next live run picks up
              this season's last bet instead of a tombstoned July one.
  6. RECAP    invoke wednesday-chronicle {"recap_only": true} so RECAP#latest (the site's
              "story so far") is rebuilt from the corrected installments.

    python3 scripts/season_promote.py --staging <dir>                # the plan, nothing written
    python3 scripts/season_promote.py --staging <dir> --apply        # owner-approved publish
    python3 scripts/season_promote.py --staging <dir> --apply --only chronicle,pages
    python3 scripts/season_promote.py --staging <dir> --audit-hashes    # the map the auditor records

THE AUDIT GATE (#4549). ``--apply`` refuses (exit 5, before the backup or any write) unless
``<staging>/audit.json`` — written by the story-auditor agent (.claude/agents/story-auditor.md) —
is a JSON object with an empty ``blocking`` list, verdict ``publishable``, the per-week floors on
``items_checked`` / ``raw_verified``, and a ``staged_sha256`` map whose hash for every file that
publishes (``AUDITED_FILES`` for each promoted week) matches the staging folder now.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

REGION = "us-west-2"
TABLE = "life-platform"
BUCKET = "matthew-life-platform"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
PANEL_PK = "USER#matthew#SOURCE#panelcast"
PANEL_PREFIX = "generated/panelcast"
HOLD_PREFIX = "panelcast-holds"
STEPS = ("backup", "chronicle", "ledger", "pages", "effects", "panel", "recap")

# #4593: what the promote declines of chronicle-approve's publish-time side effects, and why. Every other effect in
# chronicle_approve_lambda.SIDE_EFFECTS RUNS (today: s3_artifacts — the share kit this script builds from the rebuilt
# row — and recall_index). A new side effect added there runs here too unless it is named below with a reason.
PROMOTE_DECLINES = {
    "recap": "the promote's recap step rebuilds RECAP#latest from every corrected installment",
    "ledger": "the promote's ledger step wrote LEDGER# from the audited staging; the row's desk ledger predates the rebuild",
    "mark_published": "the promote's chronicle step wrote status=published in place",
    "elena_state": "a multi-week promote would fire her updater out of order; re-run elena-state-updater for the newest week by hand",
    "panel_podcast": "the promote's panel step publishes this season's episodes itself",
}
NO_DELIVER_REASON = "season promote without --deliver: a rebuilt or corrected installment is not mailed unless the owner passes --deliver"

# week → the chronicle row it rebuilds (the sk never moves: the URL slot is sequenced over sks)
ROWS = {0: "DATE#2026-02-28", 1: "DATE#2026-09-08", 2: "DATE#2026-09-15", 3: "DATE#2026-09-22", 4: "DATE#2026-09-29"}
UNLIST = ["DATE#2026-07-21"]  # "The Night Before Everything" — the eve of an earlier launch
EPISODE_DATES = {0: "2026-09-05", 1: "2026-09-10", 2: "2026-09-17", 3: "2026-09-24", 4: "2026-10-01"}
PLACEHOLDER_STUBS = ["wk1.wav", "wk2.wav", "wk4.wav", "wk1.transcript.txt", "wk2.transcript.txt", "wk4.transcript.txt"]
SUPERSEDED_AUDIO = ["wk0.wav", "wk0.draft.transcript.txt"]
STALE_HOLDS = ["wk1.json", "wk2.json", "wk3.json"]

CORRECTION = (
    "*Editor's note, October 2026 — Margaret Calloway: this installment was rewritten after a review of the season found it "
    "stated the plan's nutrition targets incorrectly and drew conclusions from them. It now reports the week from the full data.*"
)


PROLOGUE_NOTE = (
    "*Editor's note, October 2026 — Margaret Calloway: this prologue was rewritten with the plan's final figures. The earlier "
    "version quoted working numbers from before the plan was frozen.*"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _staged(staging: str, week: int) -> Dict[str, Any]:
    def load(name: str) -> Any:
        with open(os.path.join(staging, f"wk{week}_{name}"), encoding="utf-8") as fh:
            return fh.read() if name.endswith(".md") else json.load(fh)

    return {
        "md": load("chronicle.md"),
        "episode": load("episode.json"),
        "ledger": load("ledger.json"),
        "dossier": load("dossier.json"),
        "report": load("report.json"),
    }


def _stats_line(week: int, dossier: Dict[str, Any]) -> str:
    if week == 0:
        return "Prologue | Before Day 1 | Seattle, WA"
    w = dossier.get("weight") or {}
    t = dossier.get("training") or {}
    days = (dossier.get("window") or {}).get("experiment_days", "")
    parts = [days]
    if w.get("available"):
        if w.get("week_change_lbs"):
            parts.append(f"{w['week_end']['lbs']} lbs ({w['week_change_lbs']:+} this week)")
        else:
            parts.append(f"{w['week_end']['lbs']} lbs at the first weigh-in")
    parts.append(f"{t.get('session_count', 0)} training sessions")
    return " · ".join(p for p in parts if p)


def _row_update(week: int, st: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    import chronicle_render
    from content import chronicle_schema
    from content.story_writers import split_title

    title, body = split_title(st["md"])
    was_published = existing.get("status") == "published"
    if was_published and week > 0:
        body = CORRECTION + "\n\n" + body
    elif week == 0:
        body = PROLOGUE_NOTE + "\n\n" + body
    body_md = chronicle_schema.body_markdown(f'"{title}"\n\n{body}', title)
    return {
        "title": title,
        "content_markdown": f'"{title}"\n\n{body}',
        "content_html": chronicle_render.markdown_to_html(body_md),
        "stats_line": _stats_line(week, st["dossier"]),
        "word_count": len(body_md.split()),
        "has_board_interview": "\n> " in ("\n" + body),
        "status": "published",
        "phase": existing.get("phase") or "experiment",  # every renderer filters on phase; never leave it unset (#4537)
        "rebuilt_at": _now(),
        "rebuilt_by": "story-desk season rebuild (#4537)",
        "previous_title": existing.get("title"),
        **({"corrected_at": _now()} if was_published and week > 0 else {}),
        **({"approved_at": _now(), "approved_via": "owner season approval (#4537)"} if not was_published else {}),
    }


DRAFT_FIELDS = [
    "draft_journal_post_html",
    "draft_journal_posts_json",
    "draft_email_html",
    "draft_recap_json",
    "draft_share_kit_json",
    "draft_journal_post_key",
    "approval_token",
    "_confidence_badge_html",
    "_confidence_level",
    "held_reason",
    "held_at",
    "editors_note",
]


def plan(staging: str, weeks: List[int]) -> Dict[str, Any]:
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    out: Dict[str, Any] = {"chronicle": [], "unlist": [], "ledger": [], "panel": [], "staging_findings": []}
    for wk in weeks:
        st = _staged(staging, wk)
        rep = st["report"]
        allf = (rep.get("post_findings") or []) + (rep.get("episode_findings") or [])
        review_classes = ("fact:", "craft:")  # judgement calls a person adjudicates; everything else blocks
        blocking = [f for f in allf if not f.startswith(review_classes)]
        review = [f for f in allf if f.startswith(review_classes)]
        if blocking:
            out["staging_findings"].append({"week": wk, "blocking": blocking})
        if review:
            out.setdefault("fact_findings_for_review", []).append({"week": wk, "review": review})
        existing = table.get_item(Key={"pk": CHRONICLE_PK, "sk": ROWS[wk]}).get("Item") or {}
        upd = _row_update(wk, st, existing)
        out["chronicle"].append(
            {
                "week": wk,
                "sk": ROWS[wk],
                "from_title": existing.get("title"),
                "from_status": existing.get("status"),
                "to_title": upd["title"],
                "words": upd["word_count"],
                "stats_line": upd["stats_line"],
                "drops": [f for f in DRAFT_FIELDS if f in existing],
            }
        )
        out["ledger"].append({"week": wk, "sk": f"LEDGER#{st['ledger']['date']}", "threads": len(st["ledger"].get("threads", []))})
        ep = st["episode"]
        out["panel"].append(
            {
                "week": wk,
                "title": ep.get("title"),
                "guest": (ep.get("guest") or {}).get("name"),
                "turns": len(ep.get("turns", [])),
                "date": EPISODE_DATES[wk],
            }
        )
    for sk in UNLIST:
        it = table.get_item(Key={"pk": CHRONICLE_PK, "sk": sk}).get("Item") or {}
        out["unlist"].append({"sk": sk, "title": it.get("title")})
    out["panel_deletes"] = [f"{PANEL_PREFIX}/{k}" for k in PLACEHOLDER_STUBS + SUPERSEDED_AUDIO] + [
        f"{HOLD_PREFIX}/{k}" for k in STALE_HOLDS
    ]
    return out


# ── apply steps ──────────────────────────────────────────────────────────────


def backup(dest: str) -> str:
    import boto3

    os.makedirs(dest, exist_ok=True)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = {sk: table.get_item(Key={"pk": CHRONICLE_PK, "sk": sk}).get("Item") for sk in list(ROWS.values()) + UNLIST + ["RECAP#latest"]}
    rows.update({f"panel:{sk}": table.get_item(Key={"pk": PANEL_PK, "sk": sk}).get("Item") for sk in ("STATE#current", "SHOW#memory")})
    blob = json.dumps(rows, default=str, indent=1).encode()
    with open(os.path.join(dest, f"ddb_rows_{ts}.json"), "wb") as fh:
        fh.write(blob)
    s3.put_object(Bucket=BUCKET, Key=f"story-desk/backups/{ts}/ddb_rows.json", Body=blob)
    keys = (
        ["episodes.json", "feed.xml"]
        + PLACEHOLDER_STUBS
        + SUPERSEDED_AUDIO
        + [f"wk{n}.transcript.txt" for n in range(0, 5)]
        + [f"wk{n}.mp3" for n in range(0, 5)]
    )
    for k in keys:
        src = f"{PANEL_PREFIX}/{k}"
        try:
            s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": src}, Key=f"story-desk/backups/{ts}/{src}")
        except s3.exceptions.ClientError:
            pass
    for k in STALE_HOLDS + ["../generated/journal/posts.json"]:
        src = f"{HOLD_PREFIX}/{k}" if not k.startswith("..") else "generated/journal/posts.json"
        try:
            s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": src}, Key=f"story-desk/backups/{ts}/{src}")
        except s3.exceptions.ClientError:
            pass
    print(f"BACKUP → {dest} and s3://{BUCKET}/story-desk/backups/{ts}/")
    return ts


def apply_chronicle(staging: str, weeks: List[int]) -> None:
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    for wk in weeks:
        st = _staged(staging, wk)
        existing = table.get_item(Key={"pk": CHRONICLE_PK, "sk": ROWS[wk]}).get("Item")
        if not existing:
            raise SystemExit(f"row {ROWS[wk]} is missing — refusing to create a new slot (it would shift every URL)")
        upd = _row_update(wk, st, existing)
        names = {f"#a{i}": k for i, k in enumerate(upd)}
        values = {f":v{i}": v for i, v in enumerate(upd.values())}
        expr = "SET " + ", ".join(f"#a{i} = :v{i}" for i in range(len(upd)))
        drops = [f for f in DRAFT_FIELDS if f in existing]
        if drops:
            names.update({f"#d{i}": f for i, f in enumerate(drops)})
            expr += " REMOVE " + ", ".join(f"#d{i}" for i in range(len(drops)))
        table.update_item(
            Key={"pk": CHRONICLE_PK, "sk": ROWS[wk]},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        print(
            f"CHRONICLE wk{wk} {ROWS[wk]}: {existing.get('title')!r} → {upd['title']!r} ({upd['word_count']} words){' · dropped ' + ', '.join(drops) if drops else ''}"
        )
    for sk in UNLIST:
        table.update_item(
            Key={"pk": CHRONICLE_PK, "sk": sk},
            UpdateExpression="SET unlisted = :t, unlisted_at = :n, unlisted_reason = :r",
            ExpressionAttributeValues={
                ":t": True,
                ":n": _now(),
                ":r": "the eve of an earlier launch — kept at its URL, off the reading list (#4537)",
            },
        )
        print(f"UNLISTED {sk}")


def apply_ledger(staging: str, weeks: List[int]) -> None:
    import boto3
    from content import story_ledger

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    for wk in weeks:
        led = _staged(staging, wk)["ledger"]
        from experiment.phase_taxonomy import experiment_stamp_for

        row = story_ledger.ledger_row(CHRONICLE_PK, led, cycle="17")
        row.update(experiment_stamp_for(row["pk"], row["sk"]))  # #3599
        table.put_item(Item=row)
        print(f"LEDGER LEDGER#{led['date']} ({len(led.get('threads', []))} threads)")


def apply_pages() -> None:
    import restart_leadin_pages

    restart_leadin_pages.run(apply=True)


def share_kit_json(row: Dict[str, Any], installments: List[Dict[str, Any]]) -> str:
    """#4593: the week's share kit built from the REBUILT row — the draft kit the approve path would write was built
    from the superseded draft and is dropped with the other draft_* fields. Slug and label come from the same
    (date, sk) sequence restart_leadin_pages renders the pages at, so the kit lands at the post's own week-NN."""
    import restart_leadin_pages as rlp
    from content import chronicle_share_kit
    from privacy import privacy_guard

    date_str = str(row.get("date") or str(row.get("sk", "")).replace("DATE#", ""))
    week = int(row.get("week_number", 0) or 0)
    all_dates = sorted(x.get("date", "") for x in installments if x.get("date", ""))
    all_keys = rlp.installment_keys(installments)
    listed_keys = rlp.installment_keys([x for x in installments if not x.get("unlisted")])
    sk = str(row.get("sk", ""))
    seq = rlp.seq_for(date_str, all_dates, week, sk=sk, all_keys=all_keys)
    label = "From the archive" if row.get("unlisted") else rlp.series_label(date_str, all_dates, week, sk=sk, all_keys=listed_keys)
    kit = chronicle_share_kit.build_kit(
        title=row.get("title", ""),
        stats_line=rlp.display_stats_line(row.get("stats_line", ""), date_str),
        label=label,
        date_str=date_str,
        canonical_url=rlp.CANONICAL_URL_FMT.format(seq=seq),
        excerpt_source=rlp.body_markdown_from_record(row),
        week_number=week,
    )
    privacy_guard.assert_clean(kit.get("caption", ""), context=f"share kit {sk}")  # parity with the Wednesday writer
    return json.dumps(kit)


def effects_plan(deliver: bool) -> Dict[str, str]:
    """The decline map this promote passes to publish_side_effects."""
    decline = dict(PROMOTE_DECLINES)
    if not deliver:
        decline["delivery"] = NO_DELIVER_REASON
    return decline


def apply_effects(sks: List[str], deliver: bool = False) -> Dict[str, Dict[str, str]]:
    """#4593: run — or decline by name, with a reason — every publish-time side effect chronicle-approve runs, through
    the SAME function (chronicle_approve_lambda.publish_side_effects). Before this, the promote wrote the row and ran
    none of them: week 4 shipped with no share kit and no email and no recorded decision not to send one."""
    import boto3
    import chronicle_approve_lambda as approve
    import restart_leadin_pages as rlp

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    installments = rlp.fetch_visible_installments(table)
    decline = effects_plan(deliver)
    results: Dict[str, Dict[str, str]] = {}
    for sk in sks:
        row = table.get_item(Key={"pk": CHRONICLE_PK, "sk": sk}).get("Item")
        if not row or row.get("status") != "published":
            raise SystemExit(f"EFFECTS {sk}: row is {'missing' if not row else row.get('status')!r}, not published — refusing")
        fresh = next((x for x in installments if x.get("sk") == sk), row)
        item = dict(row)
        for f in DRAFT_FIELDS:  # only the kit is written: never a superseded draft page or manifest
            item.pop(f, None)
        item["draft_share_kit_json"] = share_kit_json(fresh, installments)
        date_str = str(row.get("date") or sk.replace("DATE#", ""))
        results[sk] = approve.publish_side_effects(item, date_str, decline=decline)
        print(f"EFFECTS {sk}: " + ", ".join(f"{k}={v}" for k, v in results[sk].items()))
    return results


def apply_panel(staging: str, weeks: List[int]) -> None:
    import boto3
    import coach_panel_podcast_lambda as panel
    from ai import gemini_tts

    s3 = boto3.client("s3", region_name=REGION)
    episodes: List[Dict[str, Any]] = []
    bet_ledger: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for wk in weeks:
        st = _staged(staging, wk)
        ep = st["episode"]
        guest = ep.get("guest") or {}
        gid = guest.get("persona_id") or guest.get("coach_id")
        label_of = {"elena": "Elena", "coach": guest.get("name") or "Coach"}
        voices = {"Elena": panel._gemini_voice(panel.ELENA), label_of["coach"]: panel._gemini_voice(gid)}
        label_turns = [{"speaker": label_of.get(t["speaker"], "Elena"), "line": t["line"]} for t in ep["turns"]]
        done_path = os.path.join(staging, "panel_published.json")
        done = json.load(open(done_path)) if os.path.exists(done_path) else {}
        if str(wk) in done:  # resumable: an episode already published in this promote is reused, not re-synthesized
            published = done[str(wk)]
        else:
            audio = None
            for attempt in range(3):  # the TTS vendor read can time out on a long episode
                try:
                    audio = gemini_tts.synthesize_dialogue(label_turns, voices, panel.WEEKLY_STYLE)
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"PANEL wk{wk}: synthesis attempt {attempt + 1} failed: {exc}")
            if audio is None:
                raise SystemExit(f"PANEL wk{wk}: synthesis failed 3 times — re-run to resume; published weeks are kept")
            published = panel._publish_episode_audio(wk, audio)
            done[str(wk)] = published
            with open(done_path, "w", encoding="utf-8") as fh:
                json.dump(done, fh, indent=1)
        transcript = "\n\n".join(f"{t['speaker']}: {t['line']}" for t in label_turns)
        s3.put_object(
            Bucket=BUCKET, Key=f"{PANEL_PREFIX}/wk{wk}.transcript.txt", Body=transcript.encode(), ContentType="text/plain; charset=utf-8"
        )
        s3.put_object(
            Bucket=BUCKET,
            Key=f"{PANEL_PREFIX}/wk{wk}.transcript.json",
            Body=json.dumps({"week": wk, "turns": label_turns}).encode(),
            ContentType="application/json",
        )
        title = f"EP{wk} · {ep.get('title')}"
        rec = {
            "week": wk,
            "title": title,
            "date": EPISODE_DATES[wk],
            **published,
            "byline": f"Elena + {label_of['coach']}",
            "guest_id": gid,
            "guest_name": label_of["coach"],
            "excerpt": (ep.get("excerpt") or "")[:240],
            "transcript_url": f"/panelcast/wk{wk}.transcript.json",
            "image_url": "",
            "image_credit": "",
        }
        episodes.append(rec)
        bet = st["ledger"].get("bets") or []
        bet_ledger = [
            {
                "week": b.get("week"),
                "bet": b.get("claim"),
                "outcome": {"right": "won", "wrong": "lost"}.get(str(b.get("result")), str(b.get("result") or "open")),
                "date": EPISODE_DATES.get(int(b.get("week") or 0)),
            }
            for b in bet
        ]
        last = rec
        print(
            f"PANEL wk{wk}: {title!r} with {label_of['coach']} → {published['url']} ({published['bytes']} bytes, {published['duration_sec']}s)"
        )
    # generated/* is delete-protected by the bucket policy (ADR-032/033/046) — never delete there. The placeholder stubs
    # are restart tombstones that media_tombstone already reads as "not an episode" (#4396), and each published week's
    # audio and transcript overwrite their keys. Only the private holds are cleared.
    for k in STALE_HOLDS:
        try:
            s3.delete_object(Bucket=BUCKET, Key=f"{HOLD_PREFIX}/{k}")
        except Exception as exc:  # noqa: BLE001 — a hold that cannot be cleared is reported, never fatal to the publish
            print(f"PANEL hold {k} not cleared: {exc}")
    episodes.sort(key=lambda e: e["week"], reverse=True)
    panel._write_indexes(episodes)
    from experiment.phase_taxonomy import experiment_stamp_for

    open_bet = next((b["bet"] for b in reversed(bet_ledger) if b["outcome"] == "open"), None)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    table.put_item(
        Item={
            "pk": PANEL_PK,
            "sk": "STATE#current",
            **experiment_stamp_for(PANEL_PK, "STATE#current"),  # #3599
            "updated": _now()[:10],
            "state_json": json.dumps(
                {
                    "episode_count": len(episodes),
                    "last_episode": last,
                    "open_bet": open_bet,
                    "recent_topics": [e["title"] for e in episodes[:5]],
                    "bet_ledger": bet_ledger[-20:],
                }
            ),
        }
    )
    table.put_item(
        Item={
            "pk": PANEL_PK,
            "sk": "SHOW#memory",
            "record_type": "show_memory",
            **experiment_stamp_for(PANEL_PK, "SHOW#memory"),  # #3599
            "callbacks": [
                {"week": e["week"], "title": e["title"], "pull_quote": e["excerpt"], "open_bet": ""}
                for e in sorted(episodes, key=lambda x: x["week"])
            ][-6:],
            "guest_history": [
                {"week": e["week"], "coach_id": e["guest_id"], "name": e["guest_name"]} for e in sorted(episodes, key=lambda x: x["week"])
            ],
            "updated_at": _now(),
        }
    )
    print(
        f"PANEL state seeded for cycle 17 (open bet: {open_bet!r}); deleted {len(PLACEHOLDER_STUBS + SUPERSEDED_AUDIO)} stale objects and {len(STALE_HOLDS)} holds"
    )


def apply_recap() -> None:
    import boto3

    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(FunctionName="wednesday-chronicle", Payload=json.dumps({"recap_only": True}).encode())
    print("RECAP", resp["Payload"].read().decode()[:400])


for _k, _v in {"TABLE_NAME": TABLE, "S3_BUCKET": BUCKET, "USER_ID": "matthew", "AWS_REGION": REGION, "AWS_DEFAULT_REGION": REGION}.items():
    os.environ.setdefault(_k, _v)


# #4549: the staged files whose content reaches a reader on --apply — the post, the episode, the ledger (LEDGER rows and
# the Panel's bet record) and the dossier (the stats line). The audit names each one by content hash, so an audit of an
# earlier draft can never pass a later one: a re-stage, a --repair or a hand edit changes a hash and the gate refuses.
AUDITED_FILES = ("chronicle.md", "episode.json", "ledger.json", "dossier.json")
# Floors from .claude/agents/story-auditor.md §Method: 8 claims per week; 15 raw-verified per five-week season (3/week).
ITEMS_PER_WEEK = 8
RAW_VERIFIED_PER_WEEK = 3


def staged_hashes(staging: str, weeks: List[int]) -> Dict[str, Optional[str]]:
    """sha256 of every staged file that publishes for ``weeks`` (None = the file is missing). The auditor records this
    map as ``staged_sha256`` in audit.json (``--audit-hashes`` prints it)."""
    import hashlib

    out: Dict[str, Optional[str]] = {}
    for w in weeks:
        for k in AUDITED_FILES:
            name = f"wk{w}_{k}"
            try:
                with open(os.path.join(staging, name), "rb") as fh:
                    out[name] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                out[name] = None
    return out


def _count(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def audit_gate(staging: str, weeks: List[int]) -> List[str]:
    """#4549: an adversarial raw-data audit (the story-auditor agent) must have read THIS staging — every file that would
    publish, by content hash — and left zero blocking items. Fails closed: a missing, unreadable, malformed, stale,
    under-sized or blocking audit refuses. Returns the reasons it refuses (empty = pass)."""
    path = os.path.join(staging, "audit.json")
    if not os.path.exists(path):
        return ["no audit.json — run the story-auditor agent on this staging folder first"]
    try:
        with open(path, encoding="utf-8") as fh:
            audit = json.load(fh)
    except (OSError, ValueError) as exc:
        return [f"audit.json is unreadable ({exc.__class__.__name__}) — re-audit"]
    if not isinstance(audit, dict):
        return [f"audit.json is malformed — a JSON object is required, found {type(audit).__name__}"]
    reasons: List[str] = []

    blocking = audit.get("blocking")
    if not isinstance(blocking, list):
        reasons.append("audit.json is malformed — `blocking` must be a list (empty when nothing blocks); absent is not zero")
    elif blocking:
        reasons.append(f"audit.json lists {len(blocking)} blocking item(s)")
    if audit.get("verdict") != "publishable":
        reasons.append(f"audit.json verdict is {audit.get('verdict')!r}, not 'publishable'")

    items, raw = _count(audit.get("items_checked")), _count(audit.get("raw_verified"))
    if items is None or items < ITEMS_PER_WEEK * len(weeks):
        reasons.append(
            f"audit.json items_checked={audit.get('items_checked')!r} — at least {ITEMS_PER_WEEK * len(weeks)} for {len(weeks)} week(s)"
        )
    if raw is None or raw < RAW_VERIFIED_PER_WEEK * len(weeks):
        reasons.append(
            f"audit.json raw_verified={audit.get('raw_verified')!r} — at least {RAW_VERIFIED_PER_WEEK * len(weeks)} claims checked "
            f"against raw DynamoDB for {len(weeks)} week(s)"
        )

    recorded = audit.get("staged_sha256")
    if not isinstance(recorded, dict):
        reasons.append(
            "audit.json has no `staged_sha256` map — it does not name the content it read; re-audit "
            "(`season_promote.py --staging <dir> --weeks <w> --audit-hashes` prints the map)"
        )
        return reasons
    for name, digest in staged_hashes(staging, weeks).items():
        if digest is None:
            reasons.append(f"{name} is missing from staging")
        elif name not in recorded:
            reasons.append(f"audit.json does not cover {name} — the audit did not read it; re-audit")
        elif recorded[name] != digest:
            reasons.append(f"{name} changed after the audit (sha256 mismatch) — the audit did not read what would publish; re-audit")
    return reasons


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--staging", default=None, help="the staging folder (required except with --effects-only)")
    ap.add_argument("--weeks", default="0-4")
    ap.add_argument(
        "--deliver",
        action="store_true",
        help="#4593: OWNER DECISION — let the effects step invoke chronicle-email-sender (one week only). Without it, "
        "delivery is declined and a no-send decision is stamped on each row.",
    )
    ap.add_argument(
        "--effects-only",
        action="store_true",
        help="#4593 repair: run only the publish-time side effects for already-published rows (no staging, no audit "
        "gate — nothing is republished). Dry-run unless --apply.",
    )
    ap.add_argument("--apply", action="store_true", help="OWNER ACT: perform the publish")
    ap.add_argument("--only", default=",".join(STEPS), help=f"comma list of steps from {STEPS}")
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--accept-reviewed", action="store_true", help="the remaining fact-read findings were adjudicated by a person")
    ap.add_argument(
        "--audit-hashes",
        action="store_true",
        help="print the staged_sha256 map the story-auditor records in audit.json, and exit (no AWS)",
    )
    args = ap.parse_args(argv)
    os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
    a, _, b = args.weeks.partition("-")
    weeks = list(range(int(a), int(b or a) + 1))
    if args.deliver and len(weeks) != 1:
        # chronicle-email-sender mails the newest installment of the last 7 days, not a named one
        raise SystemExit("--deliver takes exactly one week (the sender mails the newest installment, not a named one)")
    if args.effects_only:
        sks = [ROWS[w] for w in weeks]
        print(json.dumps({"effects_for": sks, "decline": effects_plan(args.deliver)}, indent=1))
        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply (owner act).")
            return 0
        apply_effects(sks, deliver=args.deliver)
        return 0
    if not args.staging:
        raise SystemExit("--staging is required (except with --effects-only)")
    if args.audit_hashes:
        hashes = staged_hashes(args.staging, weeks)
        print(json.dumps(hashes, indent=1))
        return 0 if all(hashes.values()) else 2
    steps = [s for s in args.only.split(",") if s]
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown steps {unknown}")
    p = plan(args.staging, weeks)
    print(json.dumps(p, indent=1, default=str))
    if p["staging_findings"]:
        print("\nREFUSING: the staging bundle carries unresolved deterministic gate findings (above). Fix or re-stage those weeks first.")
        return 3
    if p.get("fact_findings_for_review") and not args.accept_reviewed:
        print(
            "\nREFUSING: the fact read left findings (above) that a person has not adjudicated. The fact read is a model and can be"
            " wrong; once each is resolved or overruled on the record, re-run with --accept-reviewed."
        )
        return 4
    refusals = audit_gate(args.staging, weeks)
    for r in refusals:
        print(f"AUDIT GATE: {r}")
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply (owner act).")
        return 0
    if refusals:
        print("\nREFUSING: the audit gate is not satisfied (#4549).")
        return 5
    if "backup" in steps:
        backup(args.backup_dir or os.path.join(args.staging, "backup"))
    if "chronicle" in steps:
        apply_chronicle(args.staging, weeks)
    if "ledger" in steps:
        apply_ledger(args.staging, weeks)
    if "pages" in steps:
        apply_pages()
    if "effects" in steps:
        apply_effects([ROWS[w] for w in weeks], deliver=args.deliver)
    if "panel" in steps:
        apply_panel(args.staging, weeks)
    if "recap" in steps:
        apply_recap()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
