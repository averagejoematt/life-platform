#!/usr/bin/env python3
"""scripts/post_social.py — #1622: the manual social poster.

Interactive, one post at a time. Lists published candidates, builds a deterministic
caption, posts the ONE the operator selects. Credentials come from the keychain, not
AWS. The single exception (#1679) is the provenance write AFTER a successful post: the
BROADCAST_ORIGIN# ledger row (#1670) that lets the membrane recognise the platform's
own words if they later come back through an inbound channel. It is fail-soft — see
record_outbound — so a provenance miss warns rather than failing an already-sent post.

Two candidate kinds (`--kind`):
  chronicle   (#1622, default) — a published installment, from the moments index +
              rss.xml, captioned by chronicle_share_kit.build_kit.
  fingerprint (#1402)          — today's dated Daily Fingerprint card, captioned by
              content.fingerprint_broadcast. This is the ONLY sanctioned path for that
              artifact: the mark is a pure function of Matthew's vitals, and ADR-140
              rule 5 permanently forbids an AUTOMATED surface from posting it. The
              human selecting it here IS the gate, and the full caption is printed for
              approval before the choice.

Platform scope (2026-08-02 owner decision): Bluesky posts live (#1629 gate:owner
removed same day). X does not post — #1631 stays gated on dev-account/billing;
`--platform x` points at #1631 and exits, no network call. strip_links() is
groundwork for #1631 (X bills $0.20/post for any URL vs $0.015 link-free).

The 30-day usage-trial gate was REMOVED 2026-08-02 — ships unconditionally. The
usage log + --report readout are instrumentation only; they gate nothing.

Setup: security add-generic-password -s life-platform-bluesky -a <handle> -w '<app-password>'
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
from content import fingerprint_broadcast as fb  # noqa: E402
from content.chronicle_share_kit import SITE_BASE, build_kit  # noqa: E402

MOMENTS_INDEX_URL = f"{SITE_BASE}/moments/index.json"  # CloudFront VIEWER path, not the S3 generated/ key
RSS_URL = f"{SITE_BASE}/rss.xml"
BSKY_XRPC = "https://bsky.social/xrpc"
KEYCHAIN_SERVICE = "life-platform-bluesky"
DEFAULT_HANDLE = "averagejoematt.bsky.social"
USAGE_LOG_PATH = Path.home() / ".life-platform" / "post_social_usage.log"
BSKY_LIMIT = 300
_URL_RE = re.compile(r"https?://\S+")


def strip_links(text):
    """Remove any http(s):// URL. Forward groundwork for #1631 (X bills link posts)."""
    return re.sub(r"[ \t]{2,}", " ", _URL_RE.sub("", text or "")).strip()


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "post_social.py/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def list_candidates():
    chronicles = (json.loads(_get(MOMENTS_INDEX_URL)) or {}).get("chronicles", {}) or {}
    if not chronicles:
        return []
    rss = {}
    # noqa justification: stdlib-only (no defusedxml dep); source is our own site's
    # own-produced rss.xml, not third-party input — same pattern as panelcast_zeitgeist.py
    for item in ET.fromstring(_get(RSS_URL)).findall(".//item"):  # noqa: S314
        guid = item.findtext("guid") or item.findtext("link") or ""
        path = re.sub(r"\?.*$", "", guid).replace(SITE_BASE, "")
        rss[path] = {
            "title": item.findtext("title") or "",
            "description": item.findtext("description") or "",
            "pub_date": item.findtext("pubDate") or "",
        }
    candidates = []
    for path, asset in chronicles.items():
        entry = rss.get(path)
        if not entry:
            continue
        kit = build_kit(
            title=entry["title"],
            stats_line="",
            label="",
            date_str=entry["pub_date"],
            canonical_url=SITE_BASE + path,
            excerpt_source=entry["description"],
            cover_url=SITE_BASE + asset,
        )
        candidates.append({"path": path, "kit": kit})
    return candidates


def list_fingerprint_candidates():
    """#1402: today's Daily Fingerprint, if the sweep published a postable one.

    At most one candidate — the day's mark. Three things are re-checked HERE rather than
    trusted from the fetched index, because this is the last point before an irreversible
    public post and the index arrived over the network:

      1. `syndicatable` — a warming-up mark is published but never offered.
      2. the caption carries no body claim and no engagement bait (ADR-140 rule 5 and the
         no-gloss rule), re-run locally against the same assertions the builder used.
      3. the card and permalink are allowlisted public /moments/ artifacts.

    Any of the three failing drops the candidate silently rather than posting something
    that half-passed.
    """
    payload = (json.loads(_get(MOMENTS_INDEX_URL)) or {}).get("fingerprint") or None
    if not payload or not payload.get("syndicatable"):
        return []
    try:
        fb.assert_no_body_claims(payload.get("caption"))
        fb.assert_no_engagement_bait(payload.get("caption"))
        fb.assert_public_artifact(payload.get("card_url"))
        fb.assert_public_artifact(payload.get("permalink"))
    except fb.BroadcastContentError as e:
        print(f"Fingerprint candidate rejected: {e}")
        return []
    kit = {"title": f"The daily fingerprint — {payload.get('date')}", "caption": payload["caption"], "card_url": payload["card_url"]}
    return [{"path": payload["permalink"], "kit": kit}]


def truncate_for_bluesky(caption, limit=BSKY_LIMIT):
    if len(caption) <= limit:
        return caption
    parts = caption.split("\n\n")
    link = parts[-1]
    budget = limit - len(link) - 2
    kept, used = [], 0
    for part in parts[:-1]:
        sep = 2 if kept else 0
        if used + sep + len(part) <= budget:
            kept.append(part)
            used += sep + len(part)
        else:
            room = budget - used - sep
            if room > 10:
                kept.append(part[: room - 1].rstrip() + "…")
            break
    return "\n\n".join(kept + [link])


def get_keychain_password(handle):
    cmd = ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", handle, "-w"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"No Bluesky app password found.\nRun: security add-generic-password -s {KEYCHAIN_SERVICE} -a '{handle}' -w '<app-password>'")
        sys.exit(1)
    return out.stdout.strip()


def _bsky_post_json(path, body_dict, extra_headers=None):
    body = json.dumps(body_dict).encode("utf-8")
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    req = urllib.request.Request(f"{BSKY_XRPC}/{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bluesky_login(handle, app_password):
    data = _bsky_post_json("com.atproto.server.createSession", {"identifier": handle, "password": app_password})
    return data["accessJwt"], data["did"]


def bluesky_post(jwt, did, text):
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": created}
    body = {"repo": did, "collection": "app.bsky.feed.post", "record": record}
    return _bsky_post_json("com.atproto.repo.createRecord", body, {"Authorization": f"Bearer {jwt}"})


def bluesky_post_id(resp):
    """The record key of a created post — the last segment of its at:// URI.

    `com.atproto.repo.createRecord` returns {"uri": "at://<did>/app.bsky.feed.post/<rkey>"}.
    The rkey is the stable per-post identifier that also appears in the public web URL,
    so it is what the provenance ledger keys on."""
    uri = str((resp or {}).get("uri") or "")
    return uri.rsplit("/", 1)[-1] if uri else ""


def record_outbound(channel, post_id, url):
    """#1679: write the post's BROADCAST_ORIGIN# provenance row (#1670).

    Why this exists. `social_provenance.record_broadcast_origin` was written for "the
    outbound syndication path, when it lands" — and this script IS that path now: it is
    the only surface that posts under the platform's name. Without this write the
    membrane has no record of what the platform said, so a later inbound read cannot
    recognise the platform's own words coming back (the "spanning tree of posting new
    tweets to the website" the epic exists to prevent), and /api/membrane's outbound
    side would stay permanently empty no matter how much was posted.

    FAIL-SOFT and strictly after the fact. The post has already happened by the time
    this runs and cannot be unsent, so a missing ledger row is reported and never
    raised — a provenance write must not turn a successful post into a failure. This is
    the script's only AWS call; everything else still runs on keychain credentials.
    """
    try:
        import boto3  # local import: --report and the candidate listing need no AWS
        from privacy.social_provenance import record_broadcast_origin

        table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
        record_broadcast_origin(table, channel, post_id, url=url)
        return True
    except Exception as e:  # noqa: BLE001 — provenance must never fail an already-sent post
        print(f"WARNING: posted, but the broadcast-origin ledger row was NOT written ({e}).")
        print("  The membrane cannot recognise this post as the platform's own if it comes back inbound.")
        print(f"  Channel {channel}, post id {post_id or '(unknown)'} — see /story/membrane/.")
        return False


def log_usage(platform, path):
    USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG_PATH.open("a") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()}\t{platform}\t{path}\n")


def print_usage_report():
    if not USAGE_LOG_PATH.exists():
        print("No posts logged yet. Days used in the last 30: 0/30")
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    days = set()
    for line in USAGE_LOG_PATH.read_text().splitlines():
        try:
            ts = datetime.fromisoformat(line.split("\t", 1)[0])
        except (ValueError, IndexError):
            continue
        if ts >= cutoff:
            days.add(ts.date())
    print(f"Days used in the last 30: {len(days)}/30")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="bluesky", choices=["bluesky", "x"])
    parser.add_argument(
        "--kind",
        default="chronicle",
        choices=["chronicle", "fingerprint"],
        help="chronicle: a published installment (#1622). fingerprint: today's dated day-mark card (#1402).",
    )
    parser.add_argument("--handle", default=DEFAULT_HANDLE)
    parser.add_argument("--report", action="store_true", help="print days-used-of-last-30 and exit")
    args = parser.parse_args(argv)

    if args.report:
        print_usage_report()
        return 0

    if args.platform == "x":
        print("X posting isn't wired yet — see #1631 (gated on owner dev-account/billing setup). Nothing posted.")
        return 0

    candidates = list_fingerprint_candidates() if args.kind == "fingerprint" else list_candidates()
    if not candidates:
        if args.kind == "fingerprint":
            print("No fingerprint candidate (today's mark is warming up, or the sweep has not published it yet).")
        else:
            print("No candidates found (moments index / rss.xml have no matching published chronicle).")
        return 1

    for i, c in enumerate(candidates):
        print(f"[{i}] {c['kit']['title']}  —  {c['path']}")
    # The caption is shown in full before the choice: the human approves the exact words
    # that will be posted, not a title standing in for them.
    for c in candidates:
        print(f"\n--- caption for {c['path']} ---\n{truncate_for_bluesky(c['kit']['caption'])}\n")
    choice = input("Select a candidate to post (number), or blank to cancel: ").strip()
    if not choice:
        print("Cancelled.")
        return 0

    candidate = candidates[int(choice)]
    text = truncate_for_bluesky(candidate["kit"]["caption"])
    password = get_keychain_password(args.handle)
    jwt, did = bluesky_login(args.handle, password)
    resp = bluesky_post(jwt, did, text)
    log_usage(f"bluesky:{args.kind}", candidate["path"])
    print(f"Posted to Bluesky: {candidate['path']}")
    # #1679: record the post in the provenance ledger the membrane reads. Fail-soft —
    # the post is already sent; a ledger miss warns, it never fails the run.
    rkey = bluesky_post_id(resp)
    if record_outbound("bluesky", rkey, f"https://bsky.app/profile/{args.handle}/post/{rkey}" if rkey else ""):
        print("Recorded in the broadcast-origin ledger (/story/membrane/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
