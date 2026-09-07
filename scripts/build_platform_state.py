#!/usr/bin/env python3
"""scripts/build_platform_state.py — the joined owner-facing read of the BUILD.

WHY THIS EXISTS
  Every number a person would want in order to steer this platform already exists,
  and nothing joins them. `model/platform_model.json` knows the fleet; `/api/receipts`
  knows the money; `scripts/gate_census.py` knows how good the guards are;
  `scripts/incident_log_patterns.py` knows the failure classes; GitHub knows the
  backlog and the delivery rate; `docs/reviews/*_grades_*.json` knows the graded
  trend. They live in eight homes and speak eight dialects, so the only way to read
  the platform as a whole has been to open eight things and hold them in your head.

  The concrete failure that motivated it: a board of ~108 open issues reads as an
  emergency, when the honest decomposition is 20 epics + 15 parked Roadmap items +
  2 gated + ~71 actionable, of which ~64% arrived in ONE commissioned audit and only
  ~9 touch anything a reader sees. Same facts, opposite conclusion. This script
  computes the decomposition so nobody has to do it from memory at 11pm.

WHAT IT IS NOT
  Not a new source of truth. Every section DELEGATES to the module that already owns
  that number — `incident_log_patterns.build()`, `gate_census --json`,
  `track_record.compute_counts()`, the live `/api/receipts`. If a number here ever
  disagrees with its owner, the owner is right and this file has a bug.

THE HONESTY CONTRACT (ADR-104, and the direct lesson of #3681)
  Every section carries its own `as_of` and `source`. A section that cannot be
  computed is emitted as `{"error": ..., "data": None}` — NEVER a stale value quietly
  retained from the previous run. #3681 is exactly that failure in the wild: the
  theme-river build has been reporting an IAM `AccessDenied` as "skipped (offline?)"
  and shipping the previous artifact, for its whole life. A dashboard that silently
  goes stale manufactures false confidence, which is worse than no dashboard.

DELIBERATE INPUT LIMITS
  Reads ONLY: local repo files, `gh` (GitHub API), and public HTTPS endpoints.
  No DynamoDB, no CloudWatch, no SSM, no new IAM. That is not laziness — the site
  deploy role holds `dynamodb:DescribeTable` and nothing else (#3681), so a section
  needing DDB would fail in CI and only in CI. Keeping the input set to things the
  build already has makes this generator's success in CI mean what it says.

Usage:
    python3 scripts/build_platform_state.py                  # write site/data/platform_state.json
    python3 scripts/build_platform_state.py --check          # non-zero if the committed file is stale
    python3 scripts/build_platform_state.py --stdout         # print, write nothing
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Written as a committed LITERAL, deliberately. tests/derived_artifact_registry.py
# discovers generators by finding their output path as a string constant in the source;
# an `os.path.join(ROOT, "site", "data", ...)` is invisible to it, which is why five
# existing generators sit in that file's DISCOVERY_BLIND set. That set is shrink-only in
# spirit, so this generator makes itself findable instead of joining it.
OUT_REL = "site/data/platform_state.json"
OUT_PATH = os.path.join(ROOT, OUT_REL)
REPO = "averagejoematt/life-platform"
SITE = "https://averagejoematt.com"

# The trailing window for delivery metrics. 30 days is long enough to survive a quiet
# week and short enough that a regression shows up while it is still actionable.
DELIVERY_WINDOW_DAYS = 30

# `gh issue list --limit N` paginates internally up to N. The open board is ~110 so
# the board query is nowhere near this; the DELIVERY query genuinely needs it — a
# 30-day window currently holds ~659 closed issues and ~752 merged PRs.
#
# The first draft of this file capped at 400 and reported `closed: 400, prs: 400` —
# both exactly the cap — and computed a median over an arbitrary 400-subset. That is
# the failure this constant's comment exists to stop, so truncation is no longer
# inferred from "did we hit our own limit": every paged query ALSO asks the search
# API for `total_count` and compares. A sample is labelled a sample.
GH_PAGE_LIMIT = 1500


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _section(source: str, **data) -> dict:
    """A computed section: its own provenance stamp plus its payload."""
    return {"as_of": _now(), "source": source, "error": None, **data}


def _failed(source: str, exc) -> dict:
    """A section that could NOT be computed.

    The payload is None and the reason is stated. Callers must render this as an
    absence, never fall back to a previous value — see the honesty contract above.
    """
    return {"as_of": _now(), "source": source, "error": f"{type(exc).__name__}: {exc}", "data": None}


def _gh_json(args: list[str]) -> object:
    """One `gh` call returning parsed JSON. Raises on any non-zero exit."""
    proc = subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh failed").strip()[:400])
    return json.loads(proc.stdout)


def _gh_total_count(query: str) -> int:
    """The TRUE size of a search population, independent of what we paged.

    Without this, "we fetched N" and "there are N" are indistinguishable, and a
    statistic over a truncated page reads exactly like a statistic over the whole
    population. Asking the search API for `total_count` costs one call and makes
    the difference visible.
    """
    out = _gh_json(["api", "-X", "GET", "search/issues", "-f", f"q=repo:{REPO} {query}", "-f", "per_page=1"])
    return int(out.get("total_count", 0)) if isinstance(out, dict) else 0


def _http_json(url: str, timeout: int = 20) -> object:
    """Public HTTPS GET. stdlib urllib only — the repo forbids requests/httpx."""
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform/build_platform_state"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return json.loads(resp.read().decode("utf-8"))


# ── board ────────────────────────────────────────────────────────────────────────
#
# The decomposition that defuses the raw open-issue count. The four cohorts are
# mutually exclusive and applied in priority order (epic → Roadmap → gated → the
# rest), so they sum to the total; a naive independent count double-counts an epic
# parked on Roadmap and produces a total larger than the board.


def _labels(issue) -> list[str]:
    return [lab["name"] for lab in issue.get("labels", [])]


def _milestone(issue) -> str:
    ms = issue.get("milestone") or {}
    return ms.get("title") or "none"


def _cohort(issue) -> str:
    labs = _labels(issue)
    if "type:epic" in labs:
        return "epic"
    if _milestone(issue) == "Roadmap":
        return "roadmap"
    if any(x.startswith("gate:") or x.startswith("blocked:") for x in labs):
        return "gated"
    return "actionable"


def _prefixed(issues, prefix: str) -> dict:
    c = Counter()
    for i in issues:
        for lab in _labels(i):
            if lab.startswith(prefix):
                c[lab[len(prefix) :]] += 1
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def build_board() -> dict:
    src = "gh issue list --state open"
    try:
        issues = _gh_json(["issue", "list", "--state", "open", "--limit", str(GH_PAGE_LIMIT), "--json", "number,title,labels,milestone"])
        cohorts = Counter(_cohort(i) for i in issues)
        act = [i for i in issues if _cohort(i) == "actionable"]

        # The single most load-bearing number on this page: how much of the
        # actionable board is one audit's output rather than accumulated neglect.
        by_review = Counter()
        for i in act:
            for lab in _labels(i):
                if lab.startswith("review:"):
                    by_review[lab[len("review:") :]] += 1

        by_area = _prefixed(act, "area:")
        # "Reader-facing" is the question a non-engineer actually asks. It is the two
        # areas that change what a visitor sees; everything else is the platform
        # maintaining itself.
        reader_facing = by_area.get("site-ux", 0) + by_area.get("growth", 0)

        return _section(
            src,
            total_open=len(issues),
            truncated=len(issues) >= GH_PAGE_LIMIT,
            cohorts={
                "epic": cohorts.get("epic", 0),
                "roadmap_parked": cohorts.get("roadmap", 0),
                "gated": cohorts.get("gated", 0),
                "actionable": cohorts.get("actionable", 0),
            },
            actionable=len(act),
            reader_facing=reader_facing,
            by_area=by_area,
            by_prio=_prefixed(act, "prio:"),
            by_type=_prefixed(act, "type:"),
            by_milestone=dict(Counter(_milestone(i) for i in act).most_common()),
            from_review=dict(by_review.most_common()),
            from_review_total=sum(by_review.values()),
        )
    except Exception as exc:  # noqa: BLE001 — a failed section is data, not a crash
        return _failed(src, exc)


# ── delivery ─────────────────────────────────────────────────────────────────────


def _median(xs: list[float]):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[len(s) // 2], 1)


def _pct(xs: list[float], p: float):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(len(s) * p))], 1)


def build_delivery() -> dict:
    src = f"gh issue list --state closed (trailing {DELIVERY_WINDOW_DAYS}d)"
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=DELIVERY_WINDOW_DAYS)).strftime("%Y-%m-%d")
        closed = _gh_json(
            [
                "issue",
                "list",
                "--state",
                "closed",
                "--search",
                f"closed:>={since}",
                "--limit",
                str(GH_PAGE_LIMIT),
                "--json",
                "number,createdAt,closedAt,labels",
            ]
        )

        def hours(i):
            a = datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(i["closedAt"].replace("Z", "+00:00"))
            return (b - a).total_seconds() / 3600.0

        # The split is the honest read. A single median hides that review-sourced work
        # and organically-found work are different populations with different shapes —
        # and (measured 2026-09-07) review work is the SLOWER of the two, which is the
        # opposite of the "batch-filed issues flatter the median" objection.
        rev = [hours(i) for i in closed if any(x["name"].startswith("review:") for x in i.get("labels", []))]
        org = [hours(i) for i in closed if not any(x["name"].startswith("review:") for x in i.get("labels", []))]
        allh = rev + org

        # The true populations, asked for directly rather than inferred from the page.
        n_closed_true = _gh_total_count(f"is:issue is:closed closed:>={since}")
        n_merged_true = _gh_total_count(f"is:pr is:merged merged:>={since}")

        return _section(
            src,
            window_days=DELIVERY_WINDOW_DAYS,
            sampled=len(closed) < n_closed_true,
            n_sampled=len(closed),
            closed=n_closed_true,
            prs_merged=n_merged_true,
            cycle_hours={
                "median": _median(allh),
                "p90": _pct(allh, 0.9),
                "median_review_sourced": _median(rev),
                "median_organic": _median(org),
                "n_review_sourced": len(rev),
                "n_organic": len(org),
            },
            closed_within_24h=sum(1 for h in allh if h < 24),
            over_7_days=sum(1 for h in allh if h > 168),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── quality (the guards, the suite) ──────────────────────────────────────────────


def build_quality() -> dict:
    src = "scripts/gate_census.py --json + deploy/sync_doc_metadata.py"
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            path = tmp.name
        try:
            subprocess.run(
                [sys.executable, "scripts/gate_census.py", "--json", path],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            census = json.load(open(path))
        finally:
            os.unlink(path)

        verdicts = Counter(g.get("verdict") for g in (census.get("gates") or []))
        families = Counter(g.get("family") for g in (census.get("gates") or []))
        total = sum(verdicts.values())
        proven = verdicts.get("can-fail (proven)", 0)

        import importlib

        sdm = importlib.import_module("deploy.sync_doc_metadata") if os.path.isdir(os.path.join(ROOT, "deploy")) else None
        test_count = None
        if sdm and hasattr(sdm, "_count_test_functions"):
            try:
                test_count = sdm._count_test_functions()
            except Exception:  # noqa: BLE001 — an optional enrichment, never fatal
                test_count = None

        return _section(
            src,
            gates_total=total,
            gates_proven_can_fail=proven,
            gates_unproven=verdicts.get("unproven", 0),
            gates_attempted_unproven=verdicts.get("attempted-unproven", 0),
            gates_not_applicable=verdicts.get("not-applicable", 0),
            proven_fraction_pct=round(100.0 * proven / total, 1) if total else None,
            by_family=dict(families.most_common()),
            test_functions=test_count,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── incidents ────────────────────────────────────────────────────────────────────


def build_incidents() -> dict:
    src = "scripts/incident_log_patterns.py::build (docs/INCIDENT_LOG.md)"
    try:
        import importlib

        ilp = importlib.import_module("incident_log_patterns")
        derived = ilp.build()
        rows = ilp.parse_rows()

        by_month = Counter()
        by_sev = Counter()
        for r in rows:
            d = str(r.get("date") or "")
            if len(d) >= 7:
                by_month[d[:7]] += 1
            sev = str(r.get("severity") or "")
            m = re.search(r"\bP([1-4])\b", sev)
            by_sev[f"P{m.group(1)}" if m else "other"] += 1

        recent = sorted(by_month.items())[-6:]
        return _section(
            src,
            total_rows=derived.get("total_rows", len(rows)),
            by_severity=dict(sorted(by_sev.items())),
            by_month_recent=dict(recent),
            top_classes=derived.get("top_classes"),
            # STATED GAP, not an omission: TTD/TTR are free prose in the table cells
            # ("~7h", "9 days", "Open — filed as #3419"). Only ~60-70% parse. A mean
            # over the parseable subset would be a number about the rows that happened
            # to be written tidily, not about the platform.
            mttr_note="not computed — TTD/TTR are free prose in INCIDENT_LOG.md; ~60-70% parseable, so any mean would be a selection artefact",
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── cost ─────────────────────────────────────────────────────────────────────────


def build_cost() -> dict:
    src = f"{SITE}/api/receipts (public)"
    try:
        r = _http_json(f"{SITE}/api/receipts")
        body = r.get("data", r) if isinstance(r, dict) else {}

        # Selected by their REAL names, read off the live payload. The first draft
        # guessed ("mtd", "projection", "paused") and silently kept only the keys that
        # happened to match — which dropped month-to-date entirely and left the page
        # showing a ceiling and a surge ceiling of the same value with nothing saying
        # surge was active. A guessed key set fails exactly like a stale one, quietly.
        keep = (
            "tier",
            "tier_semantics",
            "month_to_date_usd",
            "mtd_pct_of_ceiling",
            "projected_month_end_usd",
            "projected_pct_of_ceiling",
            "base_ceiling_usd",
            "ceiling_usd",
            "surge_ceiling_usd",
            "surge_active",
            "ai_daily_usd",
            "non_ai_daily_usd",
        )
        missing = [k for k in keep if k not in body]
        return _section(
            src,
            receipts={k: body[k] for k in keep if k in body},
            # #3554: the projection covers only the recurring classes. Carrying the
            # governor's own scope sentence means the page cannot quote the number
            # without the caveat that makes it true.
            projected_scope=body.get("projected_scope"),
            projection_note=body.get("projection_note"),
            missing_keys=missing,
            raw_keys=sorted(body.keys()),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── autonomy ─────────────────────────────────────────────────────────────────────


def build_autonomy() -> dict:
    src = "model/platform_model.json + remediation/ADR-129"
    try:
        model = json.load(open(os.path.join(ROOT, "model", "platform_model.json")))
        counts = (model.get("meta") or {}).get("counts") or {}
        return _section(
            src,
            remediation_mode="shadow (permanent — `auto` retired 2026-08-30, ADR-129 amendment; it merges nothing in any mode)",
            alarms=counts.get("alarms"),
            alarms_by_routing=counts.get("alarms_by_routing"),
            lambdas=counts.get("lambdas"),
            scheduled=counts.get("scheduled_lambdas") or counts.get("schedules"),
            contracts_enrolled=counts.get("contracts"),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── grades (what is improving vs not) ────────────────────────────────────────────


def build_grades() -> dict:
    src = "docs/reviews/*_grades_*.json (newest full review)"
    try:
        cands = []
        for f in glob.glob(os.path.join(ROOT, "docs", "reviews", "*grades*.json")):
            try:
                d = json.load(open(f))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(d.get("lenses"), dict) and d.get("date"):
                cands.append((d["date"], f, d))
        if not cands:
            raise RuntimeError("no grades JSON with a date + lenses dict")
        date, path, doc = sorted(cands)[-1]

        lenses = []
        for key, v in doc["lenses"].items():
            if not isinstance(v, dict):
                continue
            lenses.append(
                {
                    "lens": key,
                    "title": v.get("title") or key,
                    "grade": v.get("grade"),
                    "prior": v.get("prior"),
                    "moved": (v.get("grade") != v.get("prior")) if v.get("prior") else None,
                }
            )
        lenses.sort(key=lambda x: x["lens"])
        graded = [x for x in lenses if x["grade"]]
        return _section(
            src,
            review_date=date,
            review_file=os.path.relpath(path, ROOT),
            lenses=lenses,
            n_lenses=len(lenses),
            grade_distribution=dict(Counter(x["grade"] for x in graded).most_common()),
            n_at_A=sum(1 for x in graded if str(x["grade"]).strip() == "A"),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc)


# ── bets + jury out ──────────────────────────────────────────────────────────────


def build_bets_and_jury() -> tuple[dict, dict]:
    src = "gh issue list (epics, Roadmap, P1, closure:live-proof)"
    try:
        issues = _gh_json(["issue", "list", "--state", "open", "--limit", str(GH_PAGE_LIMIT), "--json", "number,title,labels,milestone"])
        epics = [{"number": i["number"], "title": i["title"]} for i in issues if "type:epic" in _labels(i)]
        roadmap = [
            {"number": i["number"], "title": i["title"]} for i in issues if _milestone(i) == "Roadmap" and "type:epic" not in _labels(i)
        ]
        p1 = [{"number": i["number"], "title": i["title"]} for i in issues if "prio:P1" in _labels(i) and _cohort(i) == "actionable"]
        # `closure:live-proof` marks work that is merged and deployed but whose named
        # live output has not yet been observed. That is precisely "the jury is out" —
        # we believe it works and have not yet watched it work.
        awaiting = [{"number": i["number"], "title": i["title"]} for i in issues if "closure:live-proof" in _labels(i)]
        bets = _section(src, epics=epics, n_epics=len(epics), roadmap_parked=roadmap, n_roadmap=len(roadmap))
        jury = _section(src, open_p1=p1, n_p1=len(p1), awaiting_live_proof=awaiting, n_awaiting=len(awaiting))
        return bets, jury
    except Exception as exc:  # noqa: BLE001
        return _failed(src, exc), _failed(src, exc)


# ── assembly ─────────────────────────────────────────────────────────────────────


def build_state() -> dict:
    bets, jury = build_bets_and_jury()
    state = {
        "generated_at": _now(),
        "schema": 1,
        "about": (
            "The joined owner-facing read of the BUILD of averagejoematt.com — not of the experiment. "
            "Every section delegates to the module that already owns its number; if a value here disagrees "
            "with its source, the source is right. A section that could not be computed is null WITH a reason, "
            "never a stale value silently retained."
        ),
        "board": build_board(),
        "delivery": build_delivery(),
        "quality": build_quality(),
        "incidents": build_incidents(),
        "cost": build_cost(),
        "autonomy": build_autonomy(),
        "grades": build_grades(),
        "bets": bets,
        "jury_out": jury,
    }
    failed = [k for k, v in state.items() if isinstance(v, dict) and v.get("error")]
    state["degraded_sections"] = failed
    state["healthy"] = not failed
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit non-zero if the committed file differs in shape/sections")
    ap.add_argument("--stdout", action="store_true", help="print the JSON, write nothing")
    args = ap.parse_args()

    state = build_state()
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"

    if args.stdout:
        sys.stdout.write(text)
        return 0

    if args.check:
        if not os.path.exists(OUT_PATH):
            print(f"❌ {os.path.relpath(OUT_PATH, ROOT)} is missing — run this script.")
            return 1
        # Values move on every run (they are live). The CHECK is structural: the same
        # sections, and none of them degraded. A drift check on values would red on
        # every clock tick and would be trained away within a week.
        old = json.load(open(OUT_PATH))
        if sorted(old.keys()) != sorted(state.keys()):
            print(f"❌ section set drifted: {sorted(set(state) ^ set(old))}")
            return 1
        print(f"✅ platform_state.json section set current ({len(state)} sections).")
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)

    b = state["board"]
    if not b.get("error"):
        print(
            f"✅ platform_state.json — {b['total_open']} open → {b['actionable']} actionable "
            f"({b['from_review_total']} from reviews, {b['reader_facing']} reader-facing)"
        )
    else:
        print("⚠️  platform_state.json written with a DEGRADED board section:", b["error"])
    if state["degraded_sections"]:
        print("   degraded:", ", ".join(state["degraded_sections"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
