#!/usr/bin/env python3
"""scripts/post_social.py — #1622: the manual social poster.

Interactive, one post at a time. Lists published chronicle candidates (moments
index + rss.xml), builds a deterministic caption via chronicle_share_kit.build_kit,
posts the ONE the operator selects. No AWS API; keychain credentials only.

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
    parser.add_argument("--handle", default=DEFAULT_HANDLE)
    parser.add_argument("--report", action="store_true", help="print days-used-of-last-30 and exit")
    args = parser.parse_args(argv)

    if args.report:
        print_usage_report()
        return 0

    if args.platform == "x":
        print("X posting isn't wired yet — see #1631 (gated on owner dev-account/billing setup). Nothing posted.")
        return 0

    candidates = list_candidates()
    if not candidates:
        print("No candidates found (moments index / rss.xml have no matching published chronicle).")
        return 1

    for i, c in enumerate(candidates):
        print(f"[{i}] {c['kit']['title']}  —  {c['path']}")
    choice = input("Select a candidate to post (number), or blank to cancel: ").strip()
    if not choice:
        print("Cancelled.")
        return 0

    candidate = candidates[int(choice)]
    text = truncate_for_bluesky(candidate["kit"]["caption"])
    password = get_keychain_password(args.handle)
    jwt, did = bluesky_login(args.handle, password)
    bluesky_post(jwt, did, text)
    log_usage("bluesky", candidate["path"])
    print(f"Posted to Bluesky: {candidate['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
