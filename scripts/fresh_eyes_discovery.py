#!/usr/bin/env python3
"""
fresh_eyes_discovery.py — weekly unattended fresh-eyes discovery routine (#823).

Pre-computes the /uplevel Phase-1 "fresh-eyes lens" so a session doesn't have to
spend its first ~30 minutes re-surveying the live site. Runs as
`.github/workflows/fresh-eyes.yml` (weekly cron) on the EXISTING
github-actions-remediation-role — Bedrock + SSM read + SES are already granted
there (see deploy/setup_remediation_role.sh); this routine adds no new IAM.

Pipeline:
  1. Gate on SSM /life-platform/budget-tier — skip the whole run at tier >= 2.
  2. Screenshot the three doors + home (/, /cockpit/, /story/, /data/) desktop+mobile,
     reusing tests/visual_qa.py's capture_page() (the same harness the gating
     CI visual-qa job uses). NB: the issue text says "/evidence/" — that's the
     pre-v5 door name; it 301s to /data/ live (checked 2026-07-08), so /data/ is
     used directly to avoid an extra redirect hop.
  3. One Bedrock Haiku vision read PER SCREENSHOT, prompted with the 4 north-star
     audiences from docs/PLATFORM_NORTH_STAR.md (the same lens uplevel.md Phase 1
     describes: "browse the live site as each north-star audience... where does
     the loop break, what's the first moment of boredom/confusion, what would
     make them come back").
  4. Deterministic dedup (difflib, no LLM) against `gh issue list --state open`
     titles, then deterministic ranking that rewards findings echoed by more than
     one audience. Both are pure functions — unit-tested offline in
     tests/test_fresh_eyes_discovery.py — so the board's size/dedup invariants
     don't depend on a model behaving.
  5. One Sonnet synthesis pass over the ranked, deduped survivors writes the final
     <=5-item board (title/why/audience/first step). Falls back to an unpolished
     board built straight from the ranked list if Sonnet is unavailable/unparsable.
  6. Emails the board the same way the remediation agent reports (SES, same
     sender/recipient) and writes an audit record under the S3 prefix the role's
     policy already allows (remediation-log/*).

Cost: ~8 Haiku vision calls (4 doors x desktop+mobile) + 1 Sonnet synthesis call
per run, per week — a few cents (see #823 evidence).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
BUDGET_PARAM = "/life-platform/budget-tier"
SENDER = RECIPIENT = "awsdev@mattsusername.com"
LOG_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")

# The three doors + home (issue #823's literal scope).
DOOR_PATHS = ["/", "/cockpit/", "/story/", "/data/"]

# tests/visual_qa.py + lambdas/bedrock_client.py (and its budget_guard import)
# aren't installed packages — add their directories to sys.path like
# tests/visual_ai_qa.py already does for bedrock_client.
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

# The 4 north-star audiences (docs/PLATFORM_NORTH_STAR.md) — the same lens
# .claude/commands/uplevel.md Phase 1 asks a human session to apply.
AUDIENCES = {
    "reddit_newcomer": "A Reddit newcomer landing for the first time. Comprehension first, "
    "fascination second — does the causal loop (data -> coaching -> protocols -> story) click "
    "in one screen?",
    "matthew_daily": "Matthew, the N=1 subject, returning to this as his daily instrument — "
    "today's read, what changed, the one thing that matters, his coaches' honest take.",
    "friends_family": "A friend or family member checking in on the human story — is he okay, " "is it working, what's the journey.",
    "qs_enthusiast": "A health / quantified-self enthusiast wanting depth and credibility — "
    "every source, every method, the correlations, the failures shown honestly.",
}

# ── dedup / ranking thresholds (tuned for difflib SequenceMatcher ratios) ──
DEDUP_THRESHOLD = 0.55  # candidate note vs. an open GH issue title -> already tracked
GROUP_THRESHOLD = 0.60  # two candidate notes close enough to be "the same finding"
_SEVERITY_WEIGHT = {"high": 3, "med": 2, "low": 1}
MAX_BOARD_ITEMS = 5

_VISION_PROMPT = """You are doing a "fresh eyes" pass of one screenshot from a personal health \
platform's public site ("{page}", path {path}, {viewport} viewport). The site's causal loop is: \
THE DATA -> THE COACHING -> THE PROTOCOLS -> THE STORY -> (shifts) THE DATA. Judge this ONE \
screenshot through each of these audiences:

{audiences}

For each audience, note ANY of: where the loop breaks (the page can't answer "which part of the \
loop am I"), the first moment of boredom or confusion, or what would make them come back \
tomorrow/next week. Skip an audience if the screenshot gives it nothing notable — don't force a \
finding. Do NOT flag honest sparse-data states, normal daily data variation, or restrained/minimal \
design as problems — the ethos here is "restraint over gloss."

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"findings": [{{"audience": "<one of: {audience_keys}>", "severity": "low"|"med"|"high", \
"note": "one concrete sentence"}}]}}
An empty "findings" list is a valid, honest answer."""


def _read_budget_tier() -> int:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name=BUDGET_PARAM)["Parameter"]["Value"])
    except Exception as e:
        print(f"[warn] budget tier read failed, treating as tier 0 (fail-open): {e}")
        return 0


def should_skip_for_budget(tier: int) -> bool:
    """Pure predicate: skip the whole run at tier >= 2 (#823's literal gate).

    Stricter than budget_guard.py's reader-facing ladder (hard stop at tier 3) —
    this is an internal discovery routine, not a reader promise, so it's the
    first thing to pause when spend is elevated.
    """
    return tier >= 2


def _import_bedrock():
    try:
        import bedrock_client

        return bedrock_client
    except Exception as e:  # pragma: no cover — exercised for real only in CI
        print(f"[warn] fresh-eyes AI unavailable — could not import bedrock_client: {e}")
        return None


def _image_block(path):
    import base64

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}


# ── screenshot capture (reuses tests/visual_qa.py) ──────────────────────────


def capture_screenshots(screenshot_dir):
    """Screenshot the 4 doors (desktop full-page + mobile 390px) against the live
    site, reusing tests/visual_qa.py's capture_page() — the same harness the
    gating CI visual-qa job drives. Returns visual_qa's per-page result dicts."""
    import visual_qa
    from playwright.sync_api import sync_playwright

    os.makedirs(screenshot_dir, exist_ok=True)
    door_defs = [d for d in visual_qa.PAGES if d["path"] in DOOR_PATHS]
    door_defs.sort(key=lambda d: DOOR_PATHS.index(d["path"]))

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        for d in door_defs:
            results.append(visual_qa.capture_page(context, d, screenshot_dir, save_screenshots=True))
        browser.close()
    return results


# ── vision read (one Bedrock Haiku call per screenshot) ─────────────────────


def parse_findings(text, page, path, viewport):
    """Pure: extract the fenced/raw JSON findings block, tolerant of stray prose.
    Drops anything with an unknown audience key or empty note — a model typo
    must never crash the run or silently fabricate an audience."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):
            continue
        audience = f.get("audience")
        note = (f.get("note") or "").strip()
        if audience not in AUDIENCES or not note:
            continue
        severity = f.get("severity") if f.get("severity") in _SEVERITY_WEIGHT else "low"
        out.append({"page": page, "path": path, "viewport": viewport, "audience": audience, "severity": severity, "note": note})
    return out


def vision_read(bedrock, page_name, path, screenshot_path, viewport, model_name="claude-haiku-4-5-20251001"):
    """One Bedrock Haiku vision call for one screenshot. Fail-soft: any error or
    an empty/near-empty image (zero-height crop) yields no findings, never a
    crash — matches tests/visual_ai_qa.py's degrade pattern."""
    try:
        if not os.path.exists(screenshot_path) or os.path.getsize(screenshot_path) <= 256:
            return []
    except OSError:
        return []
    audiences_text = "\n".join(f"- {k}: {v}" for k, v in AUDIENCES.items())
    prompt = _VISION_PROMPT.format(
        page=page_name, path=path, viewport=viewport, audiences=audiences_text, audience_keys=", ".join(AUDIENCES)
    )
    body = {"messages": [{"role": "user", "content": [_image_block(screenshot_path), {"type": "text", "text": prompt}]}], "max_tokens": 800}
    try:
        resp = bedrock.invoke(body, model_name=model_name)
    except Exception as e:
        print(f"[warn] vision read failed for {page_name} ({viewport}): {e}")
        return []
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return parse_findings(text, page_name, path, viewport)


def extract_candidates(vision_results):
    """Pure: flatten the list-of-lists of per-screenshot findings into one list."""
    out = []
    for findings in vision_results:
        out.extend(findings)
    return out


# ── dedup + ranking (pure, offline-testable) ────────────────────────────────


def _normalize(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def similarity(a, b) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def dedup_against_backlog(candidates, open_titles, threshold: float = DEDUP_THRESHOLD):
    """Pure: drop any candidate whose note text closely matches an already-open
    GitHub issue title — the backlog already tracks it, so fresh discovery must
    not re-propose it. No open_titles -> nothing is filtered (fail-open, not
    fail-silent: a gh outage must not make the board look emptier than reality)."""
    if not open_titles:
        return list(candidates)
    survivors = []
    for c in candidates:
        best = max((similarity(c["note"], t) for t in open_titles), default=0.0)
        if best >= threshold:
            continue
        survivors.append(c)
    return survivors


def rank_candidates(candidates, max_items: int = MAX_BOARD_ITEMS):
    """Pure: group near-duplicate findings (same theme raised by >1 audience or
    >1 screenshot), score each group by max severity + a bonus per distinct
    audience that echoed it, and return the top `max_items` groups sorted
    highest-leverage first. A finding echoed by two audiences outranks a
    single-audience finding of the same severity — the whole point of surveying
    multiple personas is that agreement across them IS the signal."""
    groups = []
    for c in candidates:
        placed = False
        for g in groups:
            if similarity(c["note"], g["members"][0]["note"]) >= GROUP_THRESHOLD:
                g["members"].append(c)
                g["audiences"].add(c["audience"])
                g["pages"].add(c["path"])
                placed = True
                break
        if not placed:
            groups.append({"members": [c], "audiences": {c["audience"]}, "pages": {c["path"]}})

    ranked = []
    for g in groups:
        sev = max(_SEVERITY_WEIGHT.get(m["severity"], 1) for m in g["members"])
        score = sev + 0.5 * (len(g["audiences"]) - 1)
        ranked.append(
            {
                "note": g["members"][0]["note"],
                "audiences": sorted(g["audiences"]),
                "pages": sorted(g["pages"]),
                "severity": max((m["severity"] for m in g["members"]), key=lambda s: _SEVERITY_WEIGHT.get(s, 1)),
                "count": len(g["members"]),
                "score": score,
            }
        )
    ranked.sort(key=lambda g: g["score"], reverse=True)
    return ranked[:max_items]


# ── backlog dedup source ─────────────────────────────────────────────────────


def fetch_open_issue_titles(limit: int = 200):
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", str(limit), "--json", "title", "--repo", REPO],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=60,
        )
        if out.returncode == 0:
            return [i["title"] for i in json.loads(out.stdout or "[]") if i.get("title")]
        print(f"[warn] gh issue list exited {out.returncode}: {out.stderr[:300]}")
    except Exception as e:
        print(f"[warn] gh issue list failed: {e}")
    return []


# ── Sonnet synthesis pass ───────────────────────────────────────────────────

_SYNTH_PROMPT = """You are doing the Phase-1 "fresh-eyes" survey pass of the /uplevel session \
driver for averagejoematt.com (a personal health platform; see the causal loop: THE DATA -> THE \
COACHING -> THE PROTOCOLS -> THE STORY -> shifts THE DATA). Below is this week's ranked, deduped \
raw discovery — already filtered against the open GitHub backlog, so none of it should restate \
already-tracked work.

## Ranked raw findings (highest-leverage first, from this week's screenshot sweep)
```json
{ranked_json}
```

## Open backlog titles (already excluded above — for your awareness only, to avoid re-wording one)
{open_titles}

Write the final board: at most {max_items} items, ranked highest-leverage first. For each item \
weigh which causal-loop station it strengthens, which of the 4 north-star audiences feels it, and \
whether it's a real returnability lever — kill anything that's decorative, causal-sounding, or not \
grounded in the raw findings above.

Respond with ONLY a JSON array (no prose, no markdown fences), each item:
{{"title": "short imperative title", "why": "1-2 sentences tying it to the loop + an audience", \
"audience": "which of the 4 audiences", "suggested_first_step": "one concrete next action"}}
Return an empty array if nothing above clears the bar."""


def parse_board(text):
    """Pure: extract the JSON array from Sonnet's reply, tolerant of stray prose."""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("title")][:MAX_BOARD_ITEMS]


def fallback_board(ranked):
    """Defense in depth: if Sonnet is unavailable/unparsable, ship an honest,
    unpolished board straight from the deterministic ranking rather than nothing."""
    return [
        {
            "title": r["note"][:100],
            "why": f"Raised by {', '.join(r['audiences'])} across {', '.join(r['pages'])} ({r['count']}x)",
            "audience": ", ".join(r["audiences"]),
            "suggested_first_step": "(see raw finding — no synthesis available this run)",
        }
        for r in ranked[:MAX_BOARD_ITEMS]
    ]


def synthesize_board(bedrock, ranked, open_titles, model_name="claude-sonnet-4-6"):
    if not ranked:
        return []
    prompt = _SYNTH_PROMPT.format(
        ranked_json=json.dumps(ranked, indent=2),
        open_titles="\n".join(f"- {t}" for t in open_titles[:200]) or "(none)",
        max_items=MAX_BOARD_ITEMS,
    )
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 1200}
    try:
        resp = bedrock.invoke(body, model_name=model_name)
    except Exception as e:
        print(f"[warn] synthesis call failed, using the unpolished ranked board: {e}")
        return fallback_board(ranked)
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    board = parse_board(text)
    return board if board else fallback_board(ranked)


# ── reporting ────────────────────────────────────────────────────────────────


def email_board(board):
    ses = boto3.client("sesv2", region_name=REGION)
    if not board:
        subj = "Fresh-eyes discovery: clean run, nothing new"
        html = "<p>Weekly fresh-eyes sweep found nothing that survived dedup against the open backlog this week.</p>"
    else:
        subj = f"Fresh-eyes discovery: {len(board)}-item board pre-computed for /uplevel"
        items = "".join(
            f"<li><b>{b.get('title', '')}</b> — {b.get('why', '')} <br><i>Audience: {b.get('audience', '')}</i>"
            f"<br>Next: {b.get('suggested_first_step', '')}</li>"
            for b in board
        )
        html = (
            f"<p>Pre-computed /uplevel Phase-1 board — {datetime.now(timezone.utc):%Y-%m-%d} UTC. "
            f"Fresh-eyes lens over the 4 north-star audiences, deduped against the open backlog.</p><ol>{items}</ol>"
        )
    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {"Subject": {"Data": subj[:99]}, "Body": {"Html": {"Data": html}}}},
        )
        print(f"fresh-eyes board emailed: {subj}")
    except Exception as e:
        print(f"[warn] SES send failed: {e}")


def audit_log(ranked, board):
    """Fail-soft audit record under remediation-log/ — the role's S3Log policy
    (deploy/setup_remediation_role.sh) already allows remediation-log/*, so this
    needs no new IAM grant."""
    try:
        s3 = boto3.client("s3", region_name=REGION)
        key = f"remediation-log/fresh-eyes/{datetime.now(timezone.utc):%Y/%m/%d-%H%M%S}.json"
        s3.put_object(
            Bucket=LOG_BUCKET, Key=key, Body=json.dumps({"ranked": ranked, "board": board}, indent=2), ContentType="application/json"
        )
    except Exception as e:
        print(f"[warn] fresh-eyes audit log write failed: {e}")


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Weekly fresh-eyes discovery routine (#823)")
    ap.add_argument("--screenshot-dir", default=os.path.join(ROOT, "qa-screenshots-fresh-eyes"))
    args = ap.parse_args()

    tier = _read_budget_tier()
    if should_skip_for_budget(tier):
        print(f"budget tier {tier} >= 2 — skipping fresh-eyes discovery run this week")
        return 0

    bedrock = _import_bedrock()
    if not bedrock:
        print("bedrock_client unavailable — aborting fresh-eyes run (no AI, nothing useful to email)")
        return 0

    pages = capture_screenshots(args.screenshot_dir)
    vision_results = []
    for p in pages:
        for shot in p.get("screenshots", []):
            if shot.get("kind") not in ("page", "mobile"):
                continue  # desktop full-page + mobile only — the issue's literal scope
            vision_results.append(vision_read(bedrock, p["page"], p["path"], shot["path"], shot["kind"]))

    candidates = extract_candidates(vision_results)
    open_titles = fetch_open_issue_titles()
    survivors = dedup_against_backlog(candidates, open_titles)
    ranked = rank_candidates(survivors)
    board = synthesize_board(bedrock, ranked, open_titles)

    audit_log(ranked, board)
    email_board(board)
    return 0


if __name__ == "__main__":
    sys.exit(main())
