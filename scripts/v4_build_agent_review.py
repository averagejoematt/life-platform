#!/usr/bin/env python3
"""v4_build_agent_review.py — generate /story/build/agent-review/ : the Remediation
Agent's PUBLIC performance review (#1399, epic #1367).

The self-healing remediation agent already writes every triage and every auto-merge
gate decision to the S3 audit log. This page RENDERS that log as a track record —
triages, PRs opened, gate merges/holds, and fix-survival-at-14-days grading (did the
fix hold, or did the alarm re-fire?). NO new logging path; every count is COMPUTED
from the existing records by `remediation/track_record.py`, the pure module the
tests also drive.

Two disciplines, both enforced in `track_record.py` and re-proven by
`tests/test_agent_track_record.py`:

  • R22 PRIVACY — public case files render only alarm CLASSES on a default-deny
    allowlist; anything security/exploit-shaped or unclassified is withheld (the
    page states an honest "N withheld"). This is the load-bearing control.
  • ADR-104 HONEST GRADING — a fix younger than 14 days is "not-yet-gradeable" and
    is never counted as a success; the held-rate is over the gradeable n only.

DATA SOURCE — build-time, read-only (no new /api endpoint, so no autodeploy race):
  reads the S3 audit log directly at build time and BAKES the computed track record
  into the static page. Re-run to refresh:

      python3 scripts/v4_build_agent_review.py                 # read live S3
      python3 scripts/v4_build_agent_review.py --snapshot X.json   # offline/deterministic
      python3 scripts/v4_build_agent_review.py --no-s3         # honest empty page

  If S3 is unreachable and no snapshot is given, the page renders its honest empty
  state (the agent has been in shadow mode — it proposes but does not merge, so
  there may be zero landed auto-fixes to grade yet).

CHROME NOTE (#1009/#1639): the doors nav / footer / head-chrome emitted here are the
canonical partials from `v4_chrome.py`; `scripts/v4_apply_chrome.py` re-flattens them
on deploy, so this page passes the site-chrome gate as-is. Run apply_chrome after any
build. Register once in `tests/qa_manifest.py` (the #1426 "new page = one registry"
rule).

Run from repo root.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "remediation"))
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import track_record as tr  # noqa: E402 — the pure computation module (also under test)
from v4_chrome import doors_nav, head_chrome, loop_forward, site_footer  # noqa: E402 — shared chrome (#1009/#1639)
from v4_kit import loop_ribbon  # noqa: E402 — shared .loop-ribbon (#578)

try:  # best-effort defence-in-depth on free text (the allowlist is the HARD control)
    import privacy_guard  # noqa: E402
except Exception:  # noqa: BLE001
    privacy_guard = None

SLUG = "story/build/agent-review"
CANONICAL = "/story/build/agent-review/"
TITLE = "The Agent's Performance Review — The Story — averagejoematt"
DESCRIPTION = (
    "The self-healing remediation agent's public track record — triaged alarms, PRs opened, "
    "auto-merge gate decisions, and honest fix-survival-at-14-days grading. Computed from the "
    "audit log the agent already writes; security-shaped items are withheld."
)
S3_BUCKET = "matthew-life-platform"
AGENT_PREFIX = "remediation-log/"
AUTOMERGE_PREFIX = "remediation-log/automerge/"

esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)  # noqa: E731


# ── data loading (read-only S3 at build time) ─────────────────────────────────
def _date_from_key(key: str):
    """remediation-log/2026/06/19/171018.json → '2026-06-19' (None if it doesn't match)."""
    parts = key.split("/")
    for i in range(len(parts) - 3):
        y, m, d = parts[i], parts[i + 1], parts[i + 2]
        if len(y) == 4 and y.isdigit() and len(m) == 2 and m.isdigit() and len(d) == 2 and d.isdigit():
            return f"{y}-{m}-{d}"
    return None


def _load_from_s3():
    """List + GET the agent-run and automerge records. Read-only. Returns
    (agent_records, automerge_records) or raises on any AWS failure."""
    import boto3

    s3 = boto3.client("s3", region_name="us-west-2")

    def _keys(prefix):
        out, token = [], None
        while True:
            kw = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            out.extend(o["Key"] for o in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return out

    def _get(key):
        return json.loads(s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read())

    automerge_keys = set(_keys(AUTOMERGE_PREFIX))
    agent_records, automerge_records = [], []
    for key in _keys(AGENT_PREFIX):
        if not key.endswith(".json"):
            continue
        d = _date_from_key(key)
        if d is None:
            continue
        if key in automerge_keys or "/automerge/" in key:
            rec = _get(key)
            rec["_date"], rec["_key"] = d, key
            if not rec.get("action") and key.endswith(".merged.json"):
                rec["action"] = "merged"
            elif not rec.get("action") and key.endswith(".held.json"):
                rec["action"] = "held"
            automerge_records.append(rec)
        else:
            # skip non-run artifacts (backups / latest snapshots) — real runs are HHMMSS.json
            leaf = key.rsplit("/", 1)[-1]
            if not (len(leaf) == 11 and leaf[:6].isdigit()):
                continue
            rec = _get(key)
            rec["_date"], rec["_key"] = d, key
            agent_records.append(rec)
    return agent_records, automerge_records


def _load(args):
    if args.snapshot:
        blob = json.loads(Path(args.snapshot).read_text())
        return blob.get("agent_records", []), blob.get("automerge_records", [])
    if args.no_s3:
        return [], []
    try:
        return _load_from_s3()
    except Exception as e:  # noqa: BLE001 — no creds / offline → honest empty page
        print(f"[agent-review] S3 read unavailable ({e.__class__.__name__}: {e}); rendering honest empty state", file=sys.stderr)
        return [], []


def _scrub(text: str) -> str:
    """Defence-in-depth name/vice scrub on free text (the allowlist already excluded
    security classes; this catches an incidental real name in a PR title)."""
    if not text:
        return ""
    if privacy_guard is not None:
        try:
            return privacy_guard.scrub(str(text))[0]
        except Exception:  # noqa: BLE001
            pass
    return str(text)


# ── rendering ─────────────────────────────────────────────────────────────────
CLASS_LABELS = {
    "source-freshness": "source freshness",
    "dlq-depth": "dead-letter depth",
    "ingest-liveness": "ingest liveness",
    "ingest-error": "ingestion error",
    "oauth-health": "oauth token health",
    "reconciliation": "reconciliation",
    "ai-quality": "ai quality",
    "content-cadence": "content cadence",
    "budget": "budget",
    "qa-smoke": "qa smoke",
    "ci": "ci failure",
    "iam-grant": "iam grant",
    "lambda-map": "lambda map",
    "alarm-threshold": "alarm threshold",
}
SURVIVAL_LABELS = {
    tr.GRADE_HELD: ("held", "held"),
    tr.GRADE_REGRESSED: ("regressed", "regressed"),
    tr.GRADE_NOT_YET: ("not yet gradeable", "not-yet"),
}
KIND_LABELS = {
    "auto-merge": "auto-merged fix",
    "gate-hold": "gate held for review",
    "proposed-pr": "PR opened for a human",
}

FONTS = (
    '<link rel="preload" href="/assets/fonts/v4/pxiTypc9vsFDm051Uf6KVwgkfoSxQ0GsQv8ToedPibnr0SZe1ZuWi3g.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="preload" href="/assets/fonts/v4/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2" as="font" type="font/woff2" crossorigin>'
    '<link rel="stylesheet" href="/assets/css/fonts.css">'
)
THEME = (
    '<script>(function(){try{var t=localStorage.getItem("ajm-theme");'
    'if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}})();</script>'
)
MOTION_HEAD = (
    '<script>(function(){try{if(!("IntersectionObserver" in window))return;'
    'if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;'
    'document.documentElement.classList.add("mo");'
    'window.__moFail=setTimeout(function(){document.documentElement.classList.remove("mo");},2600);}catch(e){}})();</script>'
)
MOTION_SCRIPT = '<script src="/assets/js/motion.js" defer></script>'

STYLE = """
<style>
.ar-main { max-width: var(--container); margin-inline: auto; padding: 0 var(--gutter) var(--sp-10); }
.ar-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--sp-3); margin-top: var(--sp-6); }
.ar-stat { border: 1px solid var(--border-hair); border-radius: var(--radius); padding: var(--sp-4); background: var(--surface-raised); }
.ar-stat .ar-n { font-family: var(--font-serif); font-size: var(--fs-h2); line-height: 1; color: var(--ink); }
.ar-stat .ar-k { display: block; margin-top: var(--sp-2); font-family: var(--font-mono); font-size: var(--fs-label);
  letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.section-label { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: .08em; text-transform: uppercase;
  color: var(--ink-dim); margin: var(--sp-8) 0 var(--sp-3); }
.ar-survival { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--sp-3); }
.ar-surv { border: 1px solid var(--border-hair); border-radius: var(--radius); padding: var(--sp-4); }
.ar-surv .ar-n { font-family: var(--font-serif); font-size: var(--fs-h3); }
.ar-surv[data-g="held"] .ar-n { color: var(--signal); }
.ar-surv[data-g="regressed"] .ar-n { color: var(--alert); }
.ar-surv[data-g="not-yet"] .ar-n { color: var(--ink-muted); }
.ar-surv .ar-k { display: block; margin-top: var(--sp-2); font-family: var(--font-mono); font-size: var(--fs-label);
  letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--ink-faint); }
.ar-note { color: var(--ink-muted); font-size: var(--fs-small); line-height: var(--lh-relaxed); max-width: var(--measure); margin-top: var(--sp-3); }
.ar-cases { list-style: none; margin: var(--sp-3) 0 0; padding: 0; display: grid; gap: var(--sp-3); }
.ar-case { border: 1px solid var(--border-hair); border-radius: var(--radius); padding: var(--sp-4); background: var(--surface-raised); min-width: 0; }
.ar-case-top { display: flex; align-items: baseline; gap: var(--sp-3); flex-wrap: wrap; }
.ar-badge { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase;
  color: var(--ink-faint); border: 1px solid var(--border-hair); border-radius: var(--radius-xs); padding: 2px var(--sp-2); }
.ar-grade { font-family: var(--font-mono); font-size: var(--fs-label); letter-spacing: var(--tracking-label); text-transform: uppercase; }
.ar-grade[data-g="held"] { color: var(--signal); }
.ar-grade[data-g="regressed"] { color: var(--alert); }
.ar-grade[data-g="not-yet"] { color: var(--ink-muted); }
.ar-case-title { margin: var(--sp-2) 0 0; color: var(--ink); line-height: var(--lh-snug); overflow-wrap: anywhere; }
.ar-case-foot { display: flex; align-items: baseline; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; margin-top: var(--sp-3); }
.ar-case-foot a { color: var(--ember); font-family: var(--font-mono); font-size: var(--fs-small); }
.ar-empty { border: 1px dashed var(--border-hair); border-radius: var(--radius); padding: var(--sp-6);
  color: var(--ink-muted); line-height: var(--lh-relaxed); text-align: center; }
.ar-provenance { margin-top: var(--sp-8); }
</style>
"""


def _stat(n, label):
    return f'<div class="ar-stat"><span class="ar-n">{esc(n)}</span><span class="ar-k">{esc(label)}</span></div>'


def _surv(n, label, gkey):
    return f'<div class="ar-surv" data-g="{esc(gkey)}"><span class="ar-n">{esc(n)}</span><span class="ar-k">{esc(label)}</span></div>'


def _case_html(c):
    cls_label = CLASS_LABELS.get(c["alarm_class"], c["alarm_class"])
    kind_label = KIND_LABELS.get(c["kind"], c["kind"])
    grade = c.get("survival")
    grade_html = ""
    if grade:
        glabel, gkey = SURVIVAL_LABELS.get(grade, (grade, "not-yet"))
        grade_html = f'<span class="ar-grade" data-g="{esc(gkey)}">14d: {esc(glabel)}</span>'
    title = _scrub(c.get("title") or "")
    url = c.get("url") or ""
    pr_link = ""
    if url.startswith("http"):
        pr_link = f'<a href="{esc(url)}" target="_blank" rel="noopener">view PR &rarr;</a>'
    elif url:
        pr_link = f'<span class="label">{esc(url)}</span>'
    prov = c.get("provenance") or {}
    src = prov.get("source") or ""
    log_label = "auto-merge log" if prov.get("log") == "automerge" else "agent-run log"
    when = c.get("decided_on") or ""
    return (
        '<li class="ar-case">'
        '<div class="ar-case-top">'
        f'<span class="ar-badge">{esc(cls_label)}</span>'
        f'<span class="ar-badge">{esc(kind_label)}</span>'
        f"{grade_html}"
        "</div>"
        f'<p class="ar-case-title">{esc(title)}</p>'
        '<div class="ar-case-foot">'
        f'<p class="provenance"><span class="pv-src">source: {esc(log_label)}{(" &middot; " + esc(when)) if when else ""}</span></p>'
        f"{pr_link}"
        "</div>"
        f'<p class="provenance"><span class="pv-src">{esc(src)}</span></p>'
        "</li>"
    )


def render(rec: dict) -> str:
    counts = rec["counts"]
    surv = rec["survival"]
    cases = rec["cases"]
    asof = (rec.get("generated_at") or "")[:10]

    stats = "".join(
        [
            _stat(counts["agent_runs"], "agent runs"),
            _stat(counts["signals_triaged"], "signals triaged"),
            _stat(counts["prs_opened"], "PRs opened"),
            _stat(counts["gate_merges"], "gate auto-merges"),
            _stat(counts["gate_holds"], "gate holds"),
            _stat(counts["needs_human"], "escalated to human"),
        ]
    )

    held_rate = surv["held_rate"]
    rate_line = (
        f"Held rate {round(held_rate * 100)}% over {surv['n_gradeable']} gradeable fix(es)."
        if held_rate is not None
        else f"No fix has cleared the {surv['window_days']}-day window yet — nothing gradeable, so no rate is claimed."
    )
    survival_grid = "".join(
        [
            _surv(surv["held"], "held", "held"),
            _surv(surv["regressed"], "regressed", "regressed"),
            _surv(surv["not_yet_gradeable"], "not yet gradeable", "not-yet"),
        ]
    )

    if cases:
        cases_html = '<ul class="ar-cases">' + "".join(_case_html(c) for c in cases) + "</ul>"
    else:
        cases_html = (
            '<div class="ar-empty">'
            "<p>No public case files yet. The auto-merge gate has recorded no merged or held decisions, "
            "so there is nothing to grade — which is itself the honest read on an agent that has run in "
            "<strong>shadow mode</strong> (it triages and proposes, but a human merges). When the gate "
            "resumes auto-merging, landed fixes will appear here with their 14-day survival grade.</p>"
            "</div>"
        )

    withheld_note = ""
    if rec.get("excluded_case_count"):
        withheld_note = (
            f'<p class="ar-note"><strong>{rec["excluded_case_count"]}</strong> item(s) were withheld from this page by the '
            "alarm-type allowlist — security- or exploit-adjacent classes never render here (R22 discipline). "
            "The count is shown so the omission is honest, not silent.</p>"
        )

    run_span = ""
    if rec.get("first_run") and rec.get("last_run"):
        run_span = f" spanning {esc(rec['first_run'])} → {esc(rec['last_run'])}"
    mode_line = f" It is currently in <strong>{esc(rec['mode'])}</strong> mode." if rec.get("mode") else ""

    return f"""<!DOCTYPE html>
<html lang="en" data-door="story">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(TITLE)}</title>
  <meta name="description" content="{esc(DESCRIPTION)}">
  <link rel="canonical" href="https://averagejoematt.com{CANONICAL}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="averagejoematt">
  <meta property="og:url" content="https://averagejoematt.com{CANONICAL}">
  <meta property="og:title" content="{esc(TITLE)}">
  <meta property="og:description" content="{esc(DESCRIPTION)}">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-builders.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(TITLE)}">
  <meta name="twitter:description" content="{esc(DESCRIPTION)}">
{head_chrome()}
  {FONTS}
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/story.css">
  {STYLE}
  {THEME}
  {MOTION_HEAD}
</head>
<body class="dx-page">
  <a class="skip" href="#ar">Skip to the track record</a>
  <header class="story-top">
    <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">averagejoematt</span> <span class="brand-door label">the story</span></a>
    {doors_nav("/story/")}
  </header>
  <main id="ar" class="ar-main">
    <div class="page-hero">
      <p class="ph-kicker label">the story &middot; the honesty machinery, graded</p>
      <h1 class="ph-title">The Agent's Performance Review</h1>
      <p class="ph-promise">The self-healing remediation agent gets the same treatment as the coaches: a public track record. Everything below is computed from the audit log the agent already writes &mdash; what it triaged, what it proposed, what the auto-merge gate decided, and whether each landed fix actually <em>held</em> for 14 days or the alarm re-fired.{mode_line}</p>
      {loop_ribbon("story")}
    </div>

    <p class="section-label">The record{run_span}</p>
    <div class="ar-stats">{stats}</div>

    <p class="section-label">Did the fixes hold? &mdash; survival at {surv['window_days']} days</p>
    <div class="ar-survival">{survival_grid}</div>
    <p class="ar-note">{esc(rate_line)} A fix younger than {surv['window_days']} days is <strong>not-yet-gradeable</strong> &mdash; it is never counted as a success (ADR-104). &ldquo;Regressed&rdquo; means the same alarm class re-fired inside the window; &ldquo;held&rdquo; means the window elapsed clean.</p>

    <p class="section-label">Case files</p>
    {cases_html}
    {withheld_note}

    <section class="ar-provenance">
      <p class="provenance"><span class="pv-src">Computed by <code>scripts/v4_build_agent_review.py</code> from <code>remediation-log/</code> (the agent + auto-merge-gate audit log) via <code>remediation/track_record.py</code> &middot; as of {esc(asof)}</span></p>
      <p class="ar-note">No new inference and no hand-kept numbers: this page reads records the platform wrote about itself. Case files pass an alarm-type allowlist before they render &mdash; security- or exploit-adjacent classes are excluded by design (R22), and the count withheld is shown above rather than hidden.</p>
    </section>
  </main>
  {loop_forward("/story/", CANONICAL)}
  {site_footer()}
  {MOTION_SCRIPT}
  <script type="module">import {{ initTheme }} from "/assets/js/theme.js"; initTheme();</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Build /story/build/agent-review/ from the remediation audit log.")
    ap.add_argument("--snapshot", help="build from a local JSON snapshot {agent_records, automerge_records} instead of S3")
    ap.add_argument("--no-s3", action="store_true", help="skip S3; render the honest empty state")
    ap.add_argument("--out", default=None, help="override the output directory (default site/story/build/agent-review)")
    args = ap.parse_args()

    agent_records, automerge_records = _load(args)
    rec = tr.build_track_record(agent_records, automerge_records, now=datetime.now(timezone.utc))

    out_dir = Path(args.out) if args.out else (ROOT / "site" / "story" / "build" / "agent-review")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render(rec), encoding="utf-8")
    (out_dir / "track-record.json").write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")

    c = rec["counts"]
    print(
        f"{CANONICAL}: {c['agent_runs']} runs, {c['signals_triaged']} triaged, {c['prs_opened']} PRs, "
        f"{c['gate_merges']} merges, {c['gate_holds']} holds, {len(rec['cases'])} public case(s), "
        f"{rec['excluded_case_count']} withheld"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
