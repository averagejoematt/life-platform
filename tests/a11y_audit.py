#!/usr/bin/env python3
"""
a11y_audit.py — axe-core accessibility audit for the Playwright sweep (#1433).

Runs the vendored axe-core bundle (tests/vendor/axe.min.js, pinned — see its
header for version/provenance/license) against each page tests/visual_qa.py
drives, and gates on NEW serious/critical violations versus a committed
baseline (tests/a11y_baseline.json):

  - NEW serious/critical violation (rule id not baselined for that page)
      → a GATING issue: the page FAILs the sweep, same as any render break.
  - Baselined violation (any impact)
      → recorded honestly in the result + a per-page warning — visible on
        every run, never hidden, never gating. The baseline is the triaged
        debt ledger, not an excuse file.
  - New minor/moderate violation
      → advisory warning only (recorded; the gate is scoped to the
        serious/critical impacts by the issue's acceptance criteria).
  - Baselined rule no longer observed ("fixed")
      → reported so the baseline can SHRINK — see the update path below.

Granularity is (page path, axe rule id): node counts and CSS targets are
recorded for context but deliberately NOT part of the gate key — daily data
changes move node counts around, and gating on them would make the sweep
flaky in exactly the way pixel-diffing was (#1428's lesson).

Theme dimension (#1991): every function below takes a `theme` param ("dark"
default, or "light") selecting which top-level baseline ledger it reads/writes
— "pages" for dark (the original, unchanged #1433 ledger) or the sibling
"pages_light" for light. This is additive: a baseline file with no
"pages_light" key (every pre-#1991 file) loads as an empty light ledger, and
every pre-#1991 call site — which never passes `theme` — reads/writes "pages"
exactly as before, byte-for-byte. axe's rendered-contrast check is the one
layer that can see opacity/color-mix composite failures that differ per
theme, so a page can be clean in one ledger and carry debt in the other; the
two ledgers are independent per-page, per-rule sets, not a shared one.

Viewport dimension (#3277): every function below ALSO takes a `viewport` param
("desktop" default, or "mobile") — the second axis of the same additive scheme.
Before #3277 the audit ran exactly once per page, at the desktop context, so a
violation that only exists at 390px (the `scrollable-region-focusable` class:
tables and code blocks that become horizontally-scrolling boxes below the
tablet breakpoint and were keyboard-unreachable) was measured by no gate at all
— 15 reader pages carried it live (33 nodes; chromium, 390x844, 2026-08-31 live
re-measurement over all 92 sweep paths — webkit 14/32, the class is viewport-driven,
not engine-driven), and the rule appeared nowhere in this
ledger, because absence-from-the-ledger and never-measured are indistinguishable
from outside. The four ledgers are:

    theme  × viewport →  "pages"        (dark,  desktop — the #1433 original)
                          "pages_light"  (light, desktop — #1991)
                          "pages_mobile" (dark,  mobile  — #3277)
                          "pages_light_mobile" (light, mobile — #3277)

Same contract as the theme axis: a baseline with no mobile keys loads as empty
mobile ledgers, and every pre-#3277 call site — which never passes `viewport` —
reads/writes the desktop ledgers byte-for-byte as before.

Baseline update path (DELIBERATE, REVIEWED — never auto-regenerated):
    python3 tests/visual_qa.py --update-baseline
rewrites tests/a11y_baseline.json from what the sweep just observed, for the
pages it swept (a --page/--max-tier run touches only those pages' entries;
the rest of the baseline is preserved). The run still reports NEW violations
red so nothing is silently absorbed — the committed baseline diff is the
review surface: added entries are new accepted debt (should be rare and
argued for in the PR), removed entries are fixes shrinking the ledger.

This module has NO Playwright import — run_axe() takes an already-open page
object, and the gate/baseline logic is pure so tests/test_a11y_audit.py can
exercise it offline (a Playwright import at module scope would red the whole
unit suite at collection — memory: reference_test_layer_dep_import_collection_red).
"""

import json
import os
import re
import sys
from datetime import date, datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
AXE_JS_PATH = os.path.join(_HERE, "vendor", "axe.min.js")
BASELINE_PATH = os.path.join(_HERE, "a11y_baseline.json")

# Pinned vendored version — must match the /*! axe vX.Y.Z */ header in
# AXE_JS_PATH (test_a11y_audit asserts this so a bump can't be half-done).
AXE_VERSION = "4.12.1"

# The gate is scoped to these axe impact levels (#1433 acceptance criteria).
GATING_IMPACTS = ("critical", "serious")

# #3548: a fresh serious/critical row lands with this placeholder `issue` value
# (mirrors tests/truth_baseline_audit.py's UNTRIAGED) — the unit suite reds the
# committed file on any UNTRIAGED entry, so an --update-baseline run can never
# be committed without a human naming the tracking issue.
UNTRIAGED = "UNTRIAGED"

# The viewport the mobile pass runs at — the SAME 390×844 every existing mobile
# check in tests/visual_qa.py (overflow, stuck reveals, app-bar, tap targets) and
# the weekly WebKit context already use. Reused, not invented (#3277).
MOBILE_VIEWPORT = {"width": 390, "height": 844}

# Per-ledger `_meta` notes — written by update_baseline so the file states its
# own contract next to each capture timestamp.
_LEDGER_NOTES = {
    "pages": (
        "Committed a11y debt ledger (#1433) — honest capture of current axe violations per page. "
        "The visual-qa gate reds only on NEW serious/critical violations vs this file. "
        "Update DELIBERATELY via `python3 tests/visual_qa.py --update-baseline` and review the diff in the PR; "
        "added entries are newly accepted debt, removed entries are fixes. Never hand-edit, never auto-regenerate."
    ),
    "pages_light": (
        "Light-theme sibling ledger (#1991) — same honest-capture contract as 'pages'/note above, scoped to "
        "axe findings observed under a Playwright color_scheme='light' context. Update DELIBERATELY via "
        "`python3 tests/visual_qa.py --color-scheme light --update-baseline`; the weekly standalone sweep "
        "alternates dark/light by ISO-week parity so both ledgers stay current without a dedicated job."
    ),
    "pages_mobile": (
        "Mobile-viewport sibling ledger (#3277) — same honest-capture contract as 'pages'/note above, scoped to "
        "axe findings observed at 390x844 after the mobile scroll/reveal pass (dark theme). Written by the SAME "
        "`python3 tests/visual_qa.py --update-baseline` run that writes 'pages' (one sweep captures both viewports); "
        "seeded 2026-08-31 from all 92 sweep paths against live production. Two things it states out loud: (1) "
        "`scrollable-region-focusable` is deliberately ABSENT — #3277 drove it from 15 pages / 33 nodes to zero "
        "(the motion.js scroll-region focus primitive), so a reappearance is a NEW serious violation and reds the "
        "gate; (2) the serious debt it DOES carry (color-contrast on the chart labels of "
        "/data/{vitals,training,character,badges}/, svg-img-alt on /method/build/) is PRE-EXISTING — re-measured "
        "unpatched on live at 390px, node-for-node identical, and the same rule set the desktop ledger already "
        "accepts. It is dated debt seen for the first time at this viewport, not a pass."
    ),
    "pages_light_mobile": (
        "Light-theme mobile-viewport ledger (#3277) — the light sibling of 'pages_mobile', captured at 390x844 under "
        "color_scheme='light'. Written by `python3 tests/visual_qa.py --color-scheme light --update-baseline`; the "
        "weekly standalone alternates dark/light by ISO-week parity, so this is the ledger the light run gates "
        "against. Same two statements as 'pages_mobile': no `scrollable-region-focusable` anywhere, and its serious "
        "rows (19 pages of color-contrast + svg-img-alt) are the SAME set 'pages_light' already accepts on desktop — "
        "light theme simply carries more contrast debt than dark, at either viewport."
    ),
}

_RUN_AXE_JS = """async () => {
    const r = await axe.run(document, {resultTypes: ['violations']});
    return r.violations.map(v => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 3).map(n => (n.target || []).join(' ')),
    }));
}"""


def run_axe(page):
    """Inject the vendored axe bundle (once per page) and return its violations.

    Returns a list of {id, impact, help, helpUrl, nodes, targets} dicts.
    Injection is page.evaluate(<bundle source>) — CDP Runtime.evaluate, which
    the page's CSP does not govern. It must NOT be add_script_tag(content=…):
    that creates a real inline <script> element, which the hardened site CSP
    (script-src 'self', no 'unsafe-inline' — #3048/DIL-015) blocks, and the
    audit would raise "audit did not run" on every page. Same approach as
    @axe-core/playwright. Raises on injection/run failure (never a silent pass).
    """
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        with open(AXE_JS_PATH, encoding="utf-8") as f:
            page.evaluate(f.read())
        if not page.evaluate("() => typeof window.axe !== 'undefined'"):
            raise RuntimeError("axe bundle evaluated but window.axe is undefined — audit did not run")
    return page.evaluate(_RUN_AXE_JS)


VIEWPORTS = ("desktop", "mobile")

# The four ledgers, in the order they were added — load_baseline setdefault's
# every one so a file predating an axis loads with that axis empty, not missing.
LEDGER_KEYS = ("pages", "pages_light", "pages_mobile", "pages_light_mobile")


def _baseline_key(theme, viewport="desktop"):
    """Which top-level baseline dict a (theme, viewport) pair reads/writes.

    "dark" (the default — every pre-#1991 call site) → "pages", the original
    #1433 ledger; anything else → "pages_light" (#1991). `viewport="mobile"`
    (#3277) appends "_mobile" to either: "pages_mobile" / "pages_light_mobile".
    """
    key = "pages" if theme == "dark" else "pages_light"
    if viewport == "mobile":
        key += "_mobile"
    return key


def _meta_suffix(theme, viewport="desktop"):
    """Suffix for the per-ledger `_meta` capture fields ("" for the dark-desktop
    original, "_light", "_mobile", "_light_mobile") — mirrors _baseline_key."""
    return _baseline_key(theme, viewport)[len("pages") :]


def load_baseline(path=None):
    """Load the committed baseline; a missing file is an empty baseline.

    Every ledger in LEDGER_KEYS is setdefault'd so a legacy baseline file with
    no light (#1991) or mobile (#3277) entries yet — or a missing file — loads
    with those ledgers empty rather than KeyError-ing.
    """
    path = path or BASELINE_PATH
    if not os.path.exists(path):
        return {"_meta": {}, **{k: {} for k in LEDGER_KEYS}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key in LEDGER_KEYS:
        data.setdefault(key, {})
    return data


_ISSUE_REF_RE = re.compile(r"^#\d+$")


def untriaged_serious_entries(baseline):
    """(ledger_key, page_path, rule_id) for every SERIOUS/CRITICAL baseline row
    with no valid `issue` field, across all four theme/viewport ledgers (#3548).

    Mirrors `tests/truth_baseline_audit.py::untriaged_entries` (#2956): the
    baseline is the triaged debt ledger, not an excuse file, so a serious a11y
    finding may not sit here with no one accountable for it. Deliberately
    scoped to serious/critical only — moderate/minor debt stays advisory and
    untracked by design (this file's own module docstring), the same line
    `test_a11y_audit.py`'s gate itself draws via `GATING_IMPACTS`. Pure — reads
    the dict it is given, no I/O.
    """
    out = []
    for key in LEDGER_KEYS:
        for page_path, rows in (baseline.get(key) or {}).items():
            for r in rows:
                if r.get("impact") not in GATING_IMPACTS:
                    continue
                issue = str(r.get("issue") or "")
                if not _ISSUE_REF_RE.match(issue):
                    out.append((key, page_path, r.get("id")))
    return out


def gate_findings(page_path, violations, baseline, theme="dark", viewport="desktop"):
    """Classify one page's observed violations against the baseline.

    Pure (no I/O). `theme` (#1991) selects which ledger ("pages" for dark,
    "pages_light" for light) the observed violations are compared against —
    defaults to "dark" so every pre-#1991 call site is unchanged. `viewport`
    (#3277) selects the desktop ledger (default) or its "_mobile" sibling, so
    the 390px pass gates against what was captured at 390px. Returns:
        {"new":       [violation, …]   # serious/critical, NOT baselined → GATES
         "baselined": [violation, …]   # rule id in the baseline (any impact)
         "advisory":  [violation, …]   # new minor/moderate — recorded, no gate
         "fixed":     [rule_id, …]     # baselined but no longer observed
         "observed":  [violation, …]}  # everything found, for --update-baseline
    """
    key = _baseline_key(theme, viewport)
    base_ids = {v["id"] for v in baseline.get(key, {}).get(page_path, [])}
    observed_ids = {v["id"] for v in violations}
    return {
        "new": [v for v in violations if v.get("impact") in GATING_IMPACTS and v["id"] not in base_ids],
        "baselined": [v for v in violations if v["id"] in base_ids],
        "advisory": [v for v in violations if v.get("impact") not in GATING_IMPACTS and v["id"] not in base_ids],
        "fixed": sorted(base_ids - observed_ids),
        "observed": violations,
    }


def update_baseline(observed_by_path, path=None, theme="dark", viewport="desktop", day_n=None):
    """Rewrite the baseline from a sweep's observations — the DELIBERATE path.

    observed_by_path: {page_path: [violation, …]} for the pages the sweep
    actually drove. Only those pages' entries are replaced (a page observed
    clean is removed); pages the run did not sweep are preserved untouched,
    so a --page or --max-tier run can never silently wipe the rest of the
    ledger. Entries are trimmed to the stable gate-relevant fields and sorted
    for reviewable diffs. `theme` (#1991) selects "pages" vs "pages_light" and
    `viewport` (#3277) selects the desktop ledger vs its "_mobile" sibling —
    only that ONE ledger is touched; every other ledger's entries and `_meta`
    fields are preserved untouched (each ledger gets its own captured_at/note
    pair in `_meta` — see below — so alternating updates never clobber each
    other's capture record). Returns the written baseline dict.

    `day_n` (#3546, default None = pre-#3546 behaviour exactly): the running
    cycle's 1-indexed day. Supplied, rows that vanished from a phase-dependent
    page inside the thin window are carried forward instead of harvested.
    """
    path = path or BASELINE_PATH
    baseline = load_baseline(path)
    key = _baseline_key(theme, viewport)
    for page_path, violations in observed_by_path.items():
        # #3548: a serious/critical row's `issue` field must survive a re-sweep.
        # Without this, the very next --update-baseline would silently wipe
        # every triage annotation this file's own ownership rule requires —
        # mirrors truth_baseline_audit.update_baseline's UNTRIAGED carry-forward.
        prior_issue_by_id = {r["id"]: r.get("issue") for r in baseline.get(key, {}).get(page_path, []) if r.get("issue")}

        def _row(v):
            out = {
                "id": v["id"],
                "impact": v.get("impact"),
                "help": v.get("help", ""),
                "nodes": v.get("nodes", 0),
            }
            if v.get("impact") in GATING_IMPACTS:
                out["issue"] = prior_issue_by_id.get(v["id"], UNTRIAGED)
            return out

        rows = sorted((_row(v) for v in violations), key=lambda r: r["id"])
        # #3546, the "not harvestable" half of the phase flag: inside the thin
        # window a phase-dependent page's DISAPPEARED rows are carried forward
        # rather than harvested. A chart that has not drawn yet emits no
        # contrast violation; removing the row here is what turns the chart
        # drawing on Day 3 into a red "NEW serious" a few days later. Rows still
        # observed are rewritten normally, so this is a floor, not a freeze.
        if phase_excluded(page_path, day_n):
            observed_ids = {r["id"] for r in rows}
            rows = sorted(
                rows + [dict(r) for r in baseline.get(key, {}).get(page_path, []) if r["id"] not in observed_ids],
                key=lambda r: r["id"],
            )
        if rows:
            baseline[key][page_path] = rows
        else:
            baseline[key].pop(page_path, None)
    baseline[key] = {k: baseline[key][k] for k in sorted(baseline[key])}

    suffix = _meta_suffix(theme, viewport)
    ts_field = "captured_at" + suffix
    note_field = "note" + suffix
    meta = dict(baseline.get("_meta") or {})
    meta["axe_version"] = AXE_VERSION
    meta[ts_field] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta[note_field] = _LEDGER_NOTES[key]
    baseline["_meta"] = meta
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, sort_keys=False)
        f.write("\n")
    return baseline


# ── #3546: the shrink path's dead-man + phase flag ────────────────────────────
#
# `shrink_candidates` below has surfaced its list on every run since #1990, and
# for a year nobody harvested it: 5 (08-24) → 7 (08-29) → 11 (09-04) → 50 across
# 48 pages (09-19). Each unharvested key is a live (page, rule) pair that has
# stopped gating — `gate_findings` keys the gate on the baseline id, so a rule
# sitting in the ledger for a page that no longer violates it will classify a
# genuinely NEW violation of that rule as "baselined — recorded, not gating".
# Stale-in-the-good-direction is the most expensive kind of stale.
#
# Two things were missing and both are here:
#   1. a CONSUMER with a clock — the shrink list is persisted to a committed
#      sidecar with a `first_seen` date per (page, rule), and
#      `stale_shrink_entries` reds once any entry has sat there a week. A
#      printed line nobody is accountable for is not a consumer.
#   2. a PHASE FLAG — an `--update-baseline` taken in the first days of a cycle
#      bakes that cycle's data thinness into the baseline: a chart that has not
#      drawn yet emits no contrast violation, the entry gets harvested, and the
#      sweep reds "NEW serious" a few days later when the chart fills. So
#      entries on pages backed by an EXPERIMENT_SCOPED partition are neither
#      shrink candidates NOR harvestable while day_n < PHASE_THIN_DAYS.
SHRINK_LEDGER_PATH = os.path.join(_HERE, "a11y_shrink_ledger.json")

# A shrink candidate may sit unharvested this long. Load-bearing: at 10,000 the
# planted 30-day control in tests/test_a11y_shrink_deadman_3546.py goes green.
SHRINK_MAX_AGE_DAYS = 7

# Below this day_n the cycle's data is too thin for a harvest to be honest —
# 7 is the issue's own number (#3546 acceptance) and the same week the
# dead-man's age budget uses.
PHASE_THIN_DAYS = 7

SHRINK_LEDGER_NOTE = (
    "a11y shrink dead-man (#3546) — one row per (page, rule) that tests/visual_qa.py observed as "
    "baselined-but-no-longer-live, with the date it was FIRST seen that way. Written by the sweep, "
    "read by tests/test_a11y_shrink_deadman_3546.py, which reds once any row is older than "
    "SHRINK_MAX_AGE_DAYS. A row leaves this file exactly one way: the ledger entry it names is "
    "harvested via `python3 tests/visual_qa.py --update-baseline` (or the violation comes back). "
    "Rows flagged phase_dependent are excluded from both the candidate list and the harvest while "
    "the cycle's day_n < PHASE_THIN_DAYS. Generated — do not hand-edit."
)

# The suffix tests/visual_qa.py appends to a page path for the 390px ledger.
_MOBILE_KEY_SUFFIX = " @" + str(MOBILE_VIEWPORT["width"]) + "px"


def _page_of(shrink_key):
    """The bare page path behind a shrink-candidate key ("/x/ @390px" → "/x/")."""
    return shrink_key[: -len(_MOBILE_KEY_SUFFIX)] if shrink_key.endswith(_MOBILE_KEY_SUFFIX) else shrink_key


def experiment_day_n(today_iso):
    """1-indexed Day-N of the running cycle for an ISO date — the SAME number
    `/api/journey` serves, from the same genesis constant its handler reads.

    `/api/journey` computes `pacific_day_n(EXPERIMENT_START)`; both sides bottom
    out on `EXPERIMENT_START_DATE` in `lambdas/common/constants.py`, which ships
    in every bundle. Reading the constant rather than the endpoint keeps this
    pure (the unit suite has no network) and removes a live dependency from a
    decision about a committed file. Returns 0 pre-genesis.
    """
    from constants import day_n as _day_n  # lambdas/common — see _ensure_lambda_path

    return _day_n(today_iso)


def _ensure_lambda_path():
    """Put lambdas/common + lambdas on sys.path (sibling-import style, as the
    rest of the tests/ layer does). Idempotent."""
    repo = os.path.dirname(_HERE)
    for p in (os.path.join(repo, "lambdas"), os.path.join(repo, "lambdas", "common"), _HERE):
        if p not in sys.path:
            sys.path.insert(0, p)


def phase_dependent_page(page_path):
    """True when this page's data partition resets with the experiment cycle.

    THE DERIVATION, stated because `phase_taxonomy` classifies DynamoDB SOURCE
    names and `qa_manifest` describes PAGES — there is no committed page→source
    map, and inventing one would be a second registry to keep in sync. So the
    two facets that already exist are composed:

        1. `qa_manifest.PAGES_BY_PATH[path]["api_deps"]` — the endpoints the
           page renders from (the manifest's own rule is that under-claiming is
           safe, over-claiming is not).
        2. `phase_taxonomy.SOURCE_CLASS[<endpoint leaf>]` — for the endpoints
           that are named for their partition (`/api/labs`, `/api/experiments`,
           `/api/field_notes`, `/api/protocols`, `/api/calibration`, …), an
           exact key match gives the real class with no guessing.

    A page is phase-dependent iff its `content_class` is "live-data" AND either
    some dep resolves to EXPERIMENT_SCOPED, or NO dep resolves at all. That
    second clause is the deliberate default for the aggregate endpoints
    (`/api/pulse`, `/api/character`, `/api/training_overview`, …) which are
    named for the view, not the partition: they are computed_metrics-family
    reads that DO reset, and the failure this flag exists to prevent — harvest
    a thin-day entry, red the sweep as "NEW serious" when the chart draws — is
    caused by under-flagging, so the unresolved case errs toward flagging.
    Narrative/static/utility pages are never phase-dependent; their content does
    not come from a cycle partition at all. A page absent from the manifest
    (an in-page anchor like "/coaching/by-coach/#eli_marsh") is not flagged.

    The flag only changes behaviour while day_n < PHASE_THIN_DAYS — from Day 7
    a phase-dependent entry is an ordinary candidate — so an over-flag costs at
    most a six-day harvest delay, while an under-flag costs a red sweep.
    """
    _ensure_lambda_path()
    import qa_manifest
    from experiment import phase_taxonomy

    entry = qa_manifest.PAGES_BY_PATH.get(page_path)
    if entry is None or entry.get("content_class") != "live-data":
        return False
    resolved = [
        phase_taxonomy.SOURCE_CLASS[d[len("/api/") :]]
        for d in (entry.get("api_deps") or [])
        if d[len("/api/") :] in phase_taxonomy.SOURCE_CLASS
    ]
    if not resolved:
        return True
    return phase_taxonomy.EXPERIMENT_SCOPED in resolved


def phase_excluded(page_path, day_n):
    """True when `page_path`'s ledger entries must be left alone right now —
    phase-dependent AND the cycle is still inside its thin window.

    `day_n=None` means "no cycle clock supplied" and excludes nothing, so every
    pre-#3546 call site behaves byte-for-byte as it did.
    """
    return day_n is not None and day_n < PHASE_THIN_DAYS and phase_dependent_page(page_path)


def load_shrink_ledger(path=None):
    """Load the committed shrink dead-man sidecar; a missing file is empty."""
    path = path or SHRINK_LEDGER_PATH
    if not os.path.exists(path):
        return {"_meta": {}, "entries": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", [])
    data.setdefault("_meta", {})
    return data


def merge_shrink_ledger(candidates, today_iso, prior=None, swept_pages=None):
    """The pure half of the dead-man: fold today's shrink list into the prior
    ledger, CARRYING FORWARD each surviving row's original `first_seen`.

    candidates:  {shrink key: [rule id, …]} — `shrink_candidates()`'s return.
    swept_pages: page paths this run actually drove. Rows for pages outside it
                 are preserved untouched (a --page or --max-tier run must not
                 silently clear the rest of the dead-man, the same contract
                 `update_baseline` keeps for the baseline itself).
    A row whose (page, rule) is no longer a candidate on a page that WAS swept
    is dropped — the debt is gone, so its clock is gone with it. Returns the
    new ledger dict; no I/O.
    """
    prior_first_seen = {(r["page"], r["rule"]): r.get("first_seen") for r in (prior or {}).get("entries", [])}
    today_keys = {(k, rule) for k, rules in candidates.items() for rule in rules}

    rows = []
    for key, rule in sorted(today_keys):
        rows.append(
            {
                "page": key,
                "rule": rule,
                "first_seen": prior_first_seen.get((key, rule)) or today_iso,
                "phase_dependent": phase_dependent_page(_page_of(key)),
            }
        )
    # Preserve rows for pages this run never drove.
    for r in (prior or {}).get("entries", []):
        if (r["page"], r["rule"]) in today_keys:
            continue
        if swept_pages is not None and _page_of(r["page"]) not in swept_pages:
            rows.append(dict(r))
    rows.sort(key=lambda r: (r["page"], r["rule"]))
    meta = dict((prior or {}).get("_meta") or {})
    meta["updated_at"] = today_iso
    meta["max_age_days"] = SHRINK_MAX_AGE_DAYS
    meta["note"] = SHRINK_LEDGER_NOTE
    return {"_meta": meta, "entries": rows}


def write_shrink_ledger(candidates, today_iso, swept_pages=None, path=None):
    """merge_shrink_ledger() + commit it to disk. Returns the written dict."""
    path = path or SHRINK_LEDGER_PATH
    ledger = merge_shrink_ledger(candidates, today_iso, prior=load_shrink_ledger(path), swept_pages=swept_pages)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=False)
        f.write("\n")
    return ledger


def stale_shrink_entries(ledger, today_iso, max_age_days=None):
    """[(page, rule, first_seen, age_days), …] for every row older than the
    budget — the dead-man's verdict. Pure.

    Rows with an unparseable/absent `first_seen` are returned too (age -1): a
    row that cannot be aged is not a row that is young.
    """
    max_age_days = SHRINK_MAX_AGE_DAYS if max_age_days is None else max_age_days
    today = date.fromisoformat(today_iso)
    out = []
    for r in ledger.get("entries", []):
        try:
            age = (today - date.fromisoformat(r.get("first_seen") or "")).days
        except ValueError:
            out.append((r.get("page"), r.get("rule"), r.get("first_seen"), -1))
            continue
        if age > max_age_days:
            out.append((r.get("page"), r.get("rule"), r.get("first_seen"), age))
    return sorted(out)


def shrink_candidates(gate_results_by_path, day_n=None):
    """{page_path: [rule_id, …]} for pages whose gate_findings() reported
    "fixed" rules — baselined but no longer observed live (#1990).

    `gate_findings` computes "fixed" on EVERY run, not just --update-baseline
    ones, but before #1990 that signal only ever surfaced folded into each
    page's free-text `warnings` list in tests/visual_qa.py, where it scrolled
    by untriaged — the root cause the debt ledger went stale in the good
    direction (real gating quietly off on pages that were actually clean)
    with nobody the wiser. This gives it an explicit consumer: callers render
    it as its own section (CI step summary, console tally) instead of one
    line among many.

    gate_results_by_path: {page_path: gate_findings() result dict}, e.g.
    {r["path"]: r["a11y"] for r in results if r.get("a11y")} from a
    tests/visual_qa.py sweep. Pure — no I/O.

    `day_n` (#3546, default None = pre-#3546 behaviour exactly): the running
    cycle's 1-indexed day. Supplied, it drops candidates on phase-dependent
    pages while the cycle is still inside its thin window — see
    `phase_dependent_page` for the derivation and why that window exists.
    """
    return {path: g["fixed"] for path, g in gate_results_by_path.items() if g.get("fixed") and not phase_excluded(_page_of(path), day_n)}


def summarize(baseline, theme="dark", viewport="desktop"):
    """{impact: total violation entries} across the baseline — honest numbers.

    `theme` (#1991) selects "pages" (default, dark) vs "pages_light"; `viewport`
    (#3277) selects the desktop ledger (default) vs its "_mobile" sibling."""
    key = _baseline_key(theme, viewport)
    counts = {}
    for rows in baseline.get(key, {}).values():
        for r in rows:
            counts[r.get("impact") or "unknown"] = counts.get(r.get("impact") or "unknown", 0) + 1
    return counts
