#!/usr/bin/env python3
"""
publish_board_answer.py — answer a reader's "ask the board" question and publish it.

The capture side (POST /api/board_question) drops reader questions into the S3
moderation queue at generated/board_questions/{YYYY-MM}_{id}.json. This is the
human-in-the-loop publish side: pick a question, attach the board's answer, and
append it to the public Reader Q&A feed (generated/board_answers/answers.json) that
the coaching page renders. No AI is called here — you supply the board's answer
(write it, or generate it via /api/board_ask separately and paste it in).

Usage:
  # see what's waiting
  python3 scripts/publish_board_answer.py --list

  # publish a single-voice answer
  python3 scripts/publish_board_answer.py --answer <id> \
      --text "The short version: it's the sleep, not the supplement. ..." \
      --note "Great question — this is exactly the confound we test for."

  # publish a multi-voice board answer (the personas, like /api/board_ask)
  python3 scripts/publish_board_answer.py --answer <id> \
      --responses '[{"name":"Dr. Elena Vasquez","text":"..."},{"name":"Dr. James Okafor","text":"..."}]'

After publishing, sync the site (the feed is static) is NOT required — the feed is
read live from S3 via CloudFront — but run an invalidation if you want it instant:
  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/board_answers/*'
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone

import boto3

BUCKET = "matthew-life-platform"
REGION = "us-west-2"
QUEUE_PREFIX = "generated/board_questions/"
FEED_KEY = "generated/board_answers/answers.json"

s3 = boto3.client("s3", region_name=REGION)


def _list_questions():
    """Pending (and answered) reader questions in the queue, newest first."""
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=QUEUE_PREFIX):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".json"):
                continue
            try:
                rec = json.loads(s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read())
            except Exception as e:
                print(f"  ! skip {obj['Key']}: {e}", file=sys.stderr)
                continue
            rec["_key"] = obj["Key"]
            out.append(rec)
    out.sort(key=lambda r: r.get("submitted_at", ""), reverse=True)
    return out


def _load_feed():
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=FEED_KEY)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {"answers": []}
    except Exception:
        return {"answers": []}


def _put_json(key, body):
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
        CacheControl="max-age=300",
    )


def cmd_list():
    qs = _list_questions()
    if not qs:
        print("No questions in the queue.")
        return
    for r in qs:
        status = r.get("status", "?")
        mark = "✓ answered" if status == "answered" else "· pending "
        q = (r.get("question") or "").replace("\n", " ")
        print(f"  {mark}  {r.get('id', '?'):14s}  {r.get('submitted_at', '')[:10]}  {q[:80]}")
    print(f"\n{sum(1 for r in qs if r.get('status') != 'answered')} pending · {len(qs)} total")


def cmd_answer(args):
    qs = {r.get("id"): r for r in _list_questions()}
    rec = qs.get(args.answer)
    if not rec:
        sys.exit(f"No queued question with id {args.answer!r}. Run --list to see ids.")

    if args.responses:
        try:
            responses = json.loads(args.responses)
            assert isinstance(responses, list) and all("text" in r for r in responses)
        except Exception as e:
            sys.exit(f"--responses must be a JSON list of {{name,text}} objects: {e}")
        answer_payload = {"responses": responses}
    elif args.text:
        answer_payload = {"answer": args.text}
    else:
        sys.exit("Provide either --text or --responses.")

    feed = _load_feed()
    # idempotent: replace any existing published answer for this id
    feed["answers"] = [a for a in feed.get("answers", []) if a.get("id") != rec["id"]]
    entry = {
        "id": rec["id"],
        "question": rec.get("question", ""),
        "asked_at": (rec.get("submitted_at") or "")[:10],
        "answered_at": date.today().isoformat(),
        **answer_payload,
    }
    if args.note:
        entry["note"] = args.note
    feed["answers"].append(entry)
    _put_json(FEED_KEY, feed)
    print(f"✅ published answer for {rec['id']} → s3://{BUCKET}/{FEED_KEY} ({len(feed['answers'])} total)")

    # mark the queue item answered (we can't delete generated/* — bucket policy — but we
    # can overwrite it with status=answered so --list shows it's handled).
    rec.pop("_key", None)
    rec["status"] = "answered"
    rec["answered_at"] = datetime.now(timezone.utc).isoformat()
    _put_json(f"{QUEUE_PREFIX}{(rec.get('submitted_at') or '')[:7]}_{rec['id']}.json", rec)
    print("   marked the queued question as answered.")
    print("   (optional) bust the edge cache:")
    print("   aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/board_answers/*'")


def main():
    ap = argparse.ArgumentParser(description="Answer + publish a reader 'ask the board' question.")
    ap.add_argument("--list", action="store_true", help="list queued questions")
    ap.add_argument("--answer", metavar="ID", help="publish an answer for this question id")
    ap.add_argument("--text", help="single-voice answer text")
    ap.add_argument("--responses", help="multi-voice answer as a JSON list of {name,text}")
    ap.add_argument("--note", help="optional framing line shown above the answer")
    args = ap.parse_args()
    if args.list:
        cmd_list()
    elif args.answer:
        cmd_answer(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
