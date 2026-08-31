"""tests/visual_qa_verdict.py — #3352: which SURFACE failed, and can a `site/**`
rollback even reach it?

WHY THIS EXISTS
---------------
`site-deploy.yml`'s `rollback-site-on-failure` reverts `site/**` whenever the smoke
or visual-QA gate reds. The gates judge far more than `site/**`:

  * `/api/*` payloads served from DynamoDB by the site-api Lambda,
  * the hashed asset graph the deploy script itself writes,
  * and — measured 2026-08-31 — the deploy script's own *metadata* behaviour.

Two live incidents, both with every step green:

  * **2026-08-31 P1** — PR #3349's assets-first reorder put the "Data JSON" sync
    (``--content-type application/json``, no ``*.html`` exclude) ahead of the HTML
    sync, so all 20 `/data/*` reader pages were uploaded as JSON. The visual-QA gate
    read 20 pages with no ``<title>``, no ``lang``, no viewport meta and ``js_bytes 0``.
    The auto-rollback then **re-ran the same script** and re-broke the door identically,
    and reported success.
  * **2026-08-27 (Session G)** — the same rollback reverted a wanted, published build
    beat over a DynamoDB-sourced narrative defect it was structurally incapable of
    fixing. It reported success on every step while the defect stayed live.

A rollback that reports success without reaching the defect is the silent-failure
floor. This module is the scope check: a pure function over the sweep's own
``report.json`` that names the surface and answers ONE question — *is this defect
`site/**`-reachable?*

THE FOUR SURFACES
-----------------
``deploy-script``  The page SHELL is not HTML (Content-Type says so), or the
                   no-title/no-lang/no-viewport + ``js_bytes 0`` cluster appears across
                   several pages. The bytes in `site/` are fine; the *sync* is wrong.
                   NOT reachable — re-running the sync re-runs the defect (the P1).
``hashed-asset``   A hashed asset (``name.deadbeef.js``) 404s, or the browser refuses a
                   script because it was served ``text/html`` (the 2026-08-31 P3 asset
                   race). REACHABLE, deliberately: a rollback re-syncs the PRIOR tree,
                   whose HTML and whose hashed assets are internally consistent, so the
                   dangling reference genuinely goes away. (The argument the other way —
                   "the race is a deploy-script ordering bug" — is true about the CAUSE
                   and wrong about the CURE; #3349 fixed the cause, and declining a
                   rollback here would leave a half-shipped build live.)
``api``            Broken `/api/*` calls, stale or empty data-bound text, reader-truth
                   findings about served prose, an accuracy-audit red. All of it is
                   DynamoDB/site-api content. NOT reachable — this is the Session G case.
``site-shell``     Everything else: a11y regressions, horizontal overflow, a missing
                   viewport meta on a real HTML shell, a missing selector, JS code
                   errors. REACHABLE — the bytes came out of `site/` and the previous
                   build's bytes are the fix.

THE NEGATIVE CONTROL, AND WHY IT POINTS WHERE IT DOES
-----------------------------------------------------
An issue string this module does not recognise classifies as ``site-shell`` — i.e. the
rollback still runs, exactly as it does today. That is the deliberate direction: this
change may only ever REMOVE a rollback we can prove is futile, never suppress one on a
shape we have not thought about. A silent widening of the decline set would convert a
useful-but-blunt instrument into a dark one, which is the class the platform keeps
paying for. ``test_visual_qa_verdict_3352.py`` pins the control.

PRECEDENCE WITHIN ONE PAGE
--------------------------
A page usually fails for several reasons at once. Its surface is the LEAST reachable of
its matches (``deploy-script`` > ``api`` > ``hashed-asset`` > ``site-shell``) and the
reason string names every match. This is the honest direction: if a page carries both an
a11y regression and a broken API call, a `site/**` revert cannot make that page pass, so
the answer is "alert a human", not "revert and hope". The reason string is what tells the
human the a11y half is still theirs.

OUTPUT
------
``qa-screenshots/verdict.json``::

    {"rule_version": …, "reachable": bool, "surfaces": {surface: count},
     "pages": [{"path": …, "surface": …, "reason": …}], "summary": …, "note": …}

``reachable`` is the AND over every failed page: one unreachable surface declines the
whole rollback (a partial revert of a mixed failure is the worst of both). No failures,
a missing report, or an unparseable one all yield ``reachable: true`` — the gate may have
died before it wrote anything, and the fail-safe is today's behaviour.

This module is an INSTRUMENT, not a gate: the CLI always exits 0. The visual-QA job's
own pass/fail verdict is already decided by ``visual_qa.py``; adding a second failure
mode here would only give the rollback a new way to not happen.
"""

import argparse
import json
import os
import re
import sys

# Bump when a classification RULE changes (not when prose changes) so a verdict.json
# pulled from an old run artifact can be read against the rules that produced it.
RULE_VERSION = "3352.1"

DEPLOY_SCRIPT = "deploy-script"
HASHED_ASSET = "hashed-asset"
API = "api"
SITE_SHELL = "site-shell"

# Least-reachable first — this IS the per-page precedence order.
SURFACE_PRECEDENCE = (DEPLOY_SCRIPT, API, HASHED_ASSET, SITE_SHELL)

#: The surfaces a `site/**` revert can actually change. Everything else must alert.
REACHABLE_SURFACES = frozenset({SITE_SHELL, HASHED_ASSET})

#: How many pages must carry the "shell is not HTML" SHAPE before the shape alone
#: (no Content-Type evidence) is enough to call it a deploy-script defect. The
#: 2026-08-31 P1 hit 20 pages at once, because a sync step's include set is never
#: one page wide. One page with a missing title is a page bug; twenty is a deploy.
SHELL_SHAPE_CLUSTER_MIN = 2

# ── issue-string vocabulary (grep `issues.append` in visual_qa.py / visual_ai_qa.py) ──

_HASHED_ASSET_RE = re.compile(r"[./][0-9a-f]{8}\.(?:js|mjs|css)\b")
_MIME_REFUSAL_RE = re.compile(r"refused to execute|refused to apply|mime type", re.IGNORECASE)

_API_MARKERS = (
    "broken api call(s)",  # visual_qa.py ~1136
    "stale text:",  # visual_qa.py ~990 — data-bound text that stopped moving
    "empty/placeholder",  # visual_qa.py ~948 — the data-bound selector rendered nothing
    "empty section:",  # visual_qa.py ~988 — a whole data section came back blank
    "reader-truth (",  # visual_ai_qa.py ~842 — the prose judge, on stored narrative
)
# The accuracy gate (`tests/accuracy_audit.py --live`) is a SEPARATE workflow step with no
# entry in report.json, so it is folded in from its step outcome — see classify_report's
# `accuracy_audit_failed`. It is not in the marker list above because no issue string
# carries it; a marker nothing can ever match is a dead rule.

# axe rule ids that mean "this document is not an HTML document at all".
_SHELL_AXE_IDS = ("document-title", "html-has-lang", "html-lang-valid")
_VIEWPORT_MARKER = "missing width=device-width viewport meta"


def _text(result):
    return [str(i) for i in result.get("issues") or []]


def _is_html_content_type(ct):
    """None/'' means the sweep did not record one (older report, or the response was
    never seen) — unknown is NOT evidence of a defect, so it reads as HTML."""
    if not ct:
        return True
    return str(ct).split(";")[0].strip().lower() in ("text/html", "application/xhtml+xml")


def _shell_shape(result):
    """The 2026-08-31 P1 fingerprint WITHOUT the Content-Type header: a document that
    axe says has no title and no lang, and/or no viewport meta, and that loaded zero
    bytes of JavaScript. A real HTML page of this site always ships JS."""
    blob = " ".join(_text(result)).lower()
    markers = sum(1 for rule in _SHELL_AXE_IDS if f"axe: {rule}" in blob)
    if _VIEWPORT_MARKER in blob:
        markers += 1
    js_bytes = (result.get("perf") or {}).get("js_bytes")
    return markers >= 2 and js_bytes == 0


def page_matches(result):
    """Every surface this page's evidence supports, least-reachable first.

    Pure and total: a FAILing page with no recognised marker returns [SITE_SHELL]
    (the negative control — today's behaviour).
    """
    matched = []
    reasons = {}

    ct = result.get("shell_content_type")
    if not _is_html_content_type(ct):
        matched.append(DEPLOY_SCRIPT)
        reasons[DEPLOY_SCRIPT] = f"page shell served as {str(ct).split(';')[0].strip()!r}, not text/html"

    # Per ISSUE, not per page: a page that fails for two reasons must record BOTH, or
    # the verdict a human reads would hide the half the rollback could have fixed.
    api_hits, asset_hits, unexplained = [], [], []
    for text in _text(result):
        hits = [m for m in _API_MARKERS if m in text.lower()]
        is_asset = bool(_MIME_REFUSAL_RE.search(text) or _HASHED_ASSET_RE.search(text))
        api_hits.extend(hits)
        if is_asset:
            asset_hits.append(text)
        if not hits and not is_asset:
            unexplained.append(text)

    if api_hits:
        matched.append(API)
        reasons[API] = "data-bound failure (" + ", ".join(sorted(set(api_hits))) + ")"

    if asset_hits:
        matched.append(HASHED_ASSET)
        reasons[HASHED_ASSET] = f"hashed-asset reference failed: {asset_hits[0][:120]}"

    # The negative control lives here: anything unrecognised is a site/** rendering
    # defect, which is exactly today's behaviour (roll back).
    if unexplained or not matched:
        matched.append(SITE_SHELL)
        first = (unexplained or _text(result) or ["(no issue text recorded)"])[0]
        reasons[SITE_SHELL] = f"site/** rendering defect: {first[:120]}"

    ordered = [s for s in SURFACE_PRECEDENCE if s in matched]
    return ordered, reasons


def classify_report(report, *, accuracy_audit_failed=False):
    """The whole verdict for one sweep. ``report`` is a parsed report.json dict."""
    results = list((report or {}).get("results") or [])
    failed = [r for r in results if str(r.get("status", "")).upper() == "FAIL"]

    provisional = []
    shell_shape_paths = []
    for r in failed:
        ordered, reasons = page_matches(r)
        shape = _shell_shape(r)
        if shape:
            shell_shape_paths.append(r.get("path"))
        provisional.append((r, ordered, reasons, shape))

    # The cluster promotion: the no-title/no-lang/no-viewport + js_bytes 0 SHAPE only
    # names a deploy-script defect when it appears across pages. One page like that is
    # a page bug and stays site-shell — the fail-safe direction (rollback still runs).
    clustered = len(shell_shape_paths) >= SHELL_SHAPE_CLUSTER_MIN

    pages = []
    for r, ordered, reasons, shape in provisional:
        if shape and clustered and DEPLOY_SCRIPT not in ordered:
            ordered = [DEPLOY_SCRIPT] + ordered
            reasons[DEPLOY_SCRIPT] = (
                f"non-HTML page shell shape (no title/lang/viewport, js_bytes 0) on {len(shell_shape_paths)} pages "
                f"— a sync step's include set, not one page"
            )
        surface = ordered[0]
        pages.append(
            {
                "path": r.get("path"),
                "page": r.get("page"),
                "surface": surface,
                "surfaces": ordered,
                "reason": reasons[surface],
                "injected": bool(r.get("injected")),
            }
        )

    if accuracy_audit_failed:
        pages.append(
            {
                "path": "(accuracy_audit --live)",
                "page": "Accuracy gate",
                "surface": API,
                "surfaces": [API],
                "reason": "the accuracy gate judges served /api/* numbers — a site/** revert cannot change them",
                "injected": False,
            }
        )

    surfaces = {}
    for p in pages:
        surfaces[p["surface"]] = surfaces.get(p["surface"], 0) + 1

    unreachable = sorted({p["surface"] for p in pages if p["surface"] not in REACHABLE_SURFACES})
    reachable = not unreachable

    if not pages:
        summary = "no failed page in the report — rollback scope unchanged (reachable)"
        note = "No FAIL result was found. The gate may have died before writing a verdict; the fail-safe is today's behaviour."
    elif reachable:
        summary = "all {} failed page(s) are site/**-reachable ({})".format(
            len(pages), ", ".join(f"{k}={v}" for k, v in sorted(surfaces.items()))
        )
        note = "A rollback to the previous build can change these bytes."
    else:
        summary = "{} of {} failed page(s) are NOT site/**-reachable (surface={}; all: {})".format(
            sum(surfaces.get(s, 0) for s in unreachable),
            len(pages),
            ",".join(unreachable),
            ", ".join(f"{k}={v}" for k, v in sorted(surfaces.items())),
        )
        note = (
            "A site/** revert cannot reach "
            + ",".join(unreachable)
            + " — re-running the deploy re-runs it (2026-08-31 P1) or reverts an innocent build (2026-08-27 Session G)."
        )

    return {
        "rule_version": RULE_VERSION,
        "reachable": reachable,
        "surfaces": surfaces,
        "pages": pages,
        "summary": summary,
        "note": note,
    }


# ── the live-proof injection (#3352 box 3; the #3200 lesson) ─────────────────────
#
# A fail-closed path with green unit tests can be completely non-functional (#3200
# shipped verdict-closed and never fired). The only proof that the DECLINE path works is
# watching it decline on a real gated run. These synthetic results make a `workflow_dispatch`
# run red on a chosen surface against the real site, with a harmless same-tree redeploy.
#
# They are deliberately classified through the SAME string rules as a real failure — the
# `[INJECTED]` label rides inside the issue text rather than short-circuiting the
# classifier, so the live proof exercises the production rule path, not a bypass.

_INJECTED_SURFACES = {
    API: {
        "page": "[INJECTED] live-proof probe",
        "path": "(injected — VISUAL_QA_INJECT_SURFACE=api)",
        "issues": ["[INJECTED #3352 live proof — not a real defect] 1 broken API call(s): 503 /api/vitals"],
    },
    DEPLOY_SCRIPT: {
        "page": "[INJECTED] live-proof probe",
        "path": "(injected — VISUAL_QA_INJECT_SURFACE=deploy-script)",
        "issues": ["[INJECTED #3352 live proof — not a real defect] page shell Content-Type is application/json"],
        "shell_content_type": "application/json",
    },
}


def injection_choices():
    return ["none"] + sorted(_INJECTED_SURFACES)


def injected_result(surface):
    """One synthetic FAIL result of the requested class, or None for `none`/unknown."""
    spec = _INJECTED_SURFACES.get((surface or "").strip().lower())
    if not spec:
        return None
    result = {
        "status": "FAIL",
        "warnings": [],
        "screenshots": {},
        "perf": {"lcp_ms": None, "cls": None, "js_bytes": 0},
        "injected": True,
    }
    result.update(spec)
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────────


def load_report(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"{path} not found"
    except (OSError, ValueError) as e:
        return None, f"{path} unreadable: {e}"


def _write_github_output(verdict):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"site_reachable={'true' if verdict['reachable'] else 'false'}\n")
        f.write("surfaces=" + ",".join(f"{k}:{v}" for k, v in sorted(verdict["surfaces"].items())) + "\n")
        f.write("summary=" + verdict["summary"].replace("\n", " ") + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify a visual-QA report by failing surface (#3352).")
    ap.add_argument("--report", default="qa-screenshots/report.json")
    ap.add_argument("--out", default="qa-screenshots/verdict.json")
    ap.add_argument(
        "--accuracy-audit-result",
        default="",
        help="the accuracy-audit step's outcome (success/failure/skipped) — 'failure' adds an api-surface entry",
    )
    ap.add_argument("--github-output", action="store_true", help="append site_reachable/surfaces/summary to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)

    report, err = load_report(args.report)
    verdict = classify_report(report or {}, accuracy_audit_failed=args.accuracy_audit_result.strip().lower() == "failure")
    if err:
        verdict["note"] = f"{err} — {verdict['note']}"

    print(f"── Rollback scope check (#3352, rules {RULE_VERSION}) ──")
    print(f"  site/**-reachable: {verdict['reachable']}")
    print(f"  {verdict['summary']}")
    print(f"  {verdict['note']}")
    for p in verdict["pages"][:25]:
        print(f"    · {p['surface']:<14} {p['path']} — {p['reason']}")
    if len(verdict["pages"]) > 25:
        print(f"    … and {len(verdict['pages']) - 25} more (see {args.out})")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2)
    if args.github_output:
        _write_github_output(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
