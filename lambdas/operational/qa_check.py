"""qa_check.py — how a qa-smoke result is REPRESENTED and REPORTED.

Split out of qa_smoke_lambda (#1921) when that module crossed the 1200-line
ceiling. The cut is by concern, not by line count: everything here answers
"what is a check, which question does it answer, and how does a run report
itself", while qa_smoke_lambda keeps the checks themselves and the handler.

Both halves of the reporting vocabulary live together deliberately — the EMF
metrics carry the same partition split the Check class defines, and a change to
one without the other is exactly the drift that would let a content-truth
failure quietly stop being visible.

Leaf module: stdlib only, imports nothing from the operational package, so
qa_smoke_lambda and weight_truth_qa can both depend on it without a cycle.
Re-exported from qa_smoke_lambda, so `qa_smoke_lambda.Check`,
`.emf_summary_line`, `.PARTITIONS` and friends remain valid public entrypoints.
"""

import hashlib
import json

# ── #1921: the two questions this sweep answers ──────────────────────────────
# qa-smoke used to answer TWO unrelated questions with ONE verdict, and ci-cd
# wired that single verdict to fleet auto-rollback:
#
#   DEPLOY_HEALTH — "is the code that just shipped broken?"  Only this class is
#     evidence about the deploy in flight, and only this class is FIXED by
#     reverting it. The test is causal, not topical: could a deploy that landed
#     minutes ago have caused this, and would rolling it back repair it?
#
#   CONTENT_TRUTH — "is the state of the world honest right now?"  Published
#     copy, yesterday's ingestion, an artifact a cron wrote hours ago, an AI
#     read on live prose. These drift on their own schedule whether or not
#     anyone deploys, so a finding here is not evidence against the deploy —
#     and reverting code cannot un-publish a stale number, so the rollback is
#     not merely disproportionate, it is INEFFECTIVE for this class.
#
# Three fleet rollbacks fired on CONTENT_TRUTH findings and reverted healthy
# code: 2026-07-27 16:15Z (98 functions, dashboard freshness — see the FILES
# comment in check_s3_freshness), and 2026-08-01 00:18Z (100 functions,
# reader_truth on a defect that had been live for weeks). None was repaired by
# the revert; two re-published content that had already been fixed.
#
# Assignment is DELIBERATE and required at construction — `partition` has no
# default, so a new check cannot inherit a silent one, and no name/category
# convention is consulted (a convention drifts the moment someone adds a
# category). tests/test_qa_smoke_partition.py AST-scans every Check(...) call
# site in the operational package and asserts each supplies one — the set is
# derived from the source, never enumerated by hand (#1917's lesson).
DEPLOY_HEALTH = "deploy_health"
CONTENT_TRUTH = "content_truth"
PARTITIONS = (DEPLOY_HEALTH, CONTENT_TRUTH)


class Check:
    """Single assertion result.

    `partition` is REQUIRED (see PARTITIONS above) — it decides whether this
    check's failure may trigger ci-cd's fleet auto-rollback.
    """

    def __init__(self, name, category, partition):
        if partition not in PARTITIONS:
            # Loud and immediate: an unpartitioned check must never reach the
            # oracle, where it would silently inherit one side's semantics.
            raise ValueError(f"Check({name!r}) needs partition in {PARTITIONS}, got {partition!r}")
        self.name = name
        self.category = category
        self.partition = partition
        self.passed = None  # True=green, False=red, None=yellow
        self.paused = False  # intentionally-paused surface: shown ⏸, not a fault
        self.chronic = False  # #1958: known-recurring timing warn — reported, never alarmed
        self.message = ""
        # #2620: overflow for text the one-line `message` had to cut. The message
        # is the scannable summary and stays exactly as short as it is today; each
        # entry here is one additional LOG line the handler prints beneath it (see
        # qa_smoke_lambda's `_print_details`). Deliberately NOT in the failure
        # email and NOT in any metric — an email that carries every full finding
        # stops being read, and the recovery path that was missing was the log.
        self.details = []

    def ok(self, msg=""):
        self.passed = True
        self.message = msg
        return self

    def fail(self, msg=""):
        self.passed = False
        self.message = msg
        return self

    def warn(self, msg="", chronic=False):
        """Yellow. `chronic=True` is RESERVED for two enumerated classes:
        (a) known-recurring TIMING conditions (#1958: an OPTIONAL registry
        source with no record yesterday, the MCP cache-warm partial; #2378
        adds the optional-metric nulls of check_score_sanity — same class:
        the source is event-driven/sync-lagged and the null recurs on a
        healthy platform; #2670 adds check_receipt_replay's config/engine-
        drift branch — measurement + rationale in docs/alarm_citations.json),
        and (b) known-recurring
        warns PINNED TO A FILED TRACKING ISSUE (#2378: the canary-log grant
        gap #1956, the phase-stamp backfill gap #1970 — cite the issue in a
        call-site comment and un-chronic the branch when it lands; the alarm
        firing nightly over an already-filed issue carried zero marginal
        information, ADR-105). A chronic warn stays fully visible (email,
        logs, ChronicWarnCount metric) but does NOT increment the alarmed
        WarnCount, so qa-smoke-warnings can reach green and a NOVEL warn
        class is unmissable again. The default is deliberately False: a new
        warn call site is alarmed unless it explicitly opts out, and
        tests/test_qa_smoke_chronic_warns.py AST-guards the full set of
        chronic=True call sites — extending the set means updating that
        test's enumerated registry, never a silent drift.
        """
        self.passed = None
        self.chronic = bool(chronic)
        self.message = msg
        return self

    def pause(self, msg=""):
        # Surface is intentionally paused (will return later). Renders ⏸ and is
        # NOT counted as a failure or a warning — visible, but never a fault.
        self.passed = True
        self.paused = True
        self.message = msg
        return self

    def with_details(self, lines):
        """#2620: attach overflow log lines. Chainable, so a call site reads
        `det.fail(summary).with_details(details)` — the verdict and the text it
        had to cut are set in ONE expression and cannot drift apart."""
        self.details = [str(line) for line in (lines or [])]
        return self


# ── #2620: findings that survive their own summary line ──────────────────────
# A finding used to be formatted as `f"{page} [{cat}] {note[:90]}"` and that was
# the ONLY place its text ever went. Three consequences, all observed on #2613:
#
#   1. Two thirds of a 289-char note was discarded at generation time. The only
#      way back to it was re-running the live call site by hand.
#   2. Three nightly runs cut the SAME finding at three different points, so one
#      problem read as three. Nothing in the line said which finding it was.
#   3. `findings[:4]` dropped the fifth finding entirely, with no count saying so.
#
# The fix is deliberately the cheapest one that closes all three (issue option
# (a)): the summary line is unchanged in shape and length, and every finding —
# including the ones past the inline cap — also gets ONE full-text log line
# underneath. Notes are already capped at 300 chars upstream
# (reader_truth_qa._normalize_finding), and DETAIL_LINE_CAP bounds a pathological
# run, so the worst case this adds is ~10 KB of CloudWatch ingest on a night with
# findings and exactly ZERO bytes on a clean night (the common case).
SNIPPET_CHARS = 90  # the inline summary budget, unchanged from #1096
INLINE_FINDINGS = 4  # how many findings ride the summary line, unchanged
DETAIL_LINE_CAP = 25  # bound the overflow on a pathological run


def finding_group(finding):
    """A short, RUN-INVARIANT id for a finding: 6 hex chars over page+category.

    Deliberately NOT hashed over the note. The note is LLM-generated prose that
    is reworded every night, which is exactly why #2613's three runs read as
    three problems — the words moved, the problem did not. page+category is the
    part that holds still, so the same defect carries the same id across runs and
    an operator can see at a glance that last night's finding is tonight's.
    """
    page = str((finding or {}).get("page") or "?")
    category = str((finding or {}).get("category") or "-")
    # sha256, not sha1 — this is a display label, not a security boundary, but
    # ruff's S324 is right that there is no reason to reach for a broken digest.
    return hashlib.sha256(f"{page}|{category}".encode("utf-8")).hexdigest()[:6]


def _dedupe(findings, key):
    """Collapse byte-identical findings within ONE run, keeping order + a count."""
    seen, out = {}, []
    for f in findings or []:
        f = f or {}
        ident = (str(f.get("page") or ""), str(f.get("category") or ""), str(f.get("severity") or ""), str(f.get(key) or ""))
        if ident in seen:
            seen[ident][1] += 1
            continue
        entry = [f, 1]
        seen[ident] = entry
        out.append(entry)
    return out


def summarize_findings(findings, key="note", width=SNIPPET_CHARS, inline=INLINE_FINDINGS, cap=DETAIL_LINE_CAP):
    """→ (inline_summary, detail_lines) for a list of finding dicts.

    `inline_summary` is the scannable one-liner that goes in the Check message.
    `detail_lines` carry the UNTRUNCATED text of every finding, one per line, for
    the handler to print beneath it. Truncation in the summary is marked
    `…[+N chars]` — an explicit statement that text was removed, where a bare `…`
    read as prose (and, on a note that happened to end mid-sentence, as the
    model's own ellipsis).

    Shape-tolerant on purpose: `key` names the text field ("note" for the LLM and
    plausibility passes, "detail" for the frozen-artifact pass), and severity may
    be absent — the frozen-artifact findings carry no severity and must not need
    one invented for them.
    """
    entries = _dedupe(findings, key)
    parts, details = [], []
    for f, count in entries[:inline]:
        text = str(f.get(key) or "")
        snippet = text if len(text) <= width else f"{text[:width]}…[+{len(text) - width} chars]"
        dupes = f" ×{count}" if count > 1 else ""
        parts.append(f"{f.get('page') or '?'} [{f.get('category') or '-'}·{finding_group(f)}]{dupes} {snippet}")
    if len(entries) > inline:
        parts.append(f"(+{len(entries) - inline} more finding(s), all listed below)")
    for f, count in entries[:cap]:
        text = str(f.get(key) or "")
        sev = f.get("severity")
        sev_part = f"/{sev}" if sev else ""
        dupes = f" ×{count}" if count > 1 else ""
        details.append(
            f"finding {finding_group(f)} · {f.get('page') or '?'} [{f.get('category') or '-'}{sev_part}]{dupes} "
            f"— full {key} ({len(text)} chars): {text}"
        )
    if len(entries) > cap:
        details.append(f"({len(entries) - cap} further finding(s) not detailed — detail cap {cap}/run, #2620)")
    return "; ".join(parts), details


def detail_log_lines(check):
    """The `[QA] DETAIL …` log lines for one check, formatted but not printed.

    Lives here with the rest of the run's reporting vocabulary (and beside
    emf_summary_line, which is the same shape: format here, emit in the handler)
    so the emission contract is unit-testable without invoking the Lambda — the
    thing that sends mail. A check with nothing truncated yields NO lines, which
    is why a clean nightly costs zero extra CloudWatch ingest.
    """
    return [f"[QA] DETAIL [{check.partition}] {check.category} / {check.name}: {d}" for d in (getattr(check, "details", None) or ())]


# ---------------------------------------------------------------------------
# #1445: EMF summary metrics — emitted on EVERY run, including all-green
# ---------------------------------------------------------------------------
# Before this, qa-smoke only spoke by SENDING AN EMAIL, and only on a real
# FAILURE — a green run and a run that never happened at all looked
# identical from the outside (no metric, no heartbeat, nothing for the
# remediation agent to see). This EMF line is CloudWatch-extracted into
# LifePlatform/QaSmoke metrics regardless of outcome:
#   PassCount / WarnCount / FailCount / PausedCount — per-run check tallies.
#   RunCompleted=1 — the heartbeat target (monitoring_stack.py's
#     qa-smoke-heartbeat fires BREACHING if this is absent for 2 straight
#     days, i.e. the Lambda stopped running or died before reaching here).
# monitoring_stack.py also alarms FailCount>=1 and WarnCount>=1 (both
# digest-routed, matching this file's own "routine, not urgent" posture) —
# a warnings-only run now surfaces in the next daily digest email even
# though it never triggers this Lambda's own direct failure alert, and both
# alarms are ordinary CloudWatch alarms the remediation agent's existing
# `describe_alarms(StateValue="ALARM")` sweep already ingests as a source.
#
# #1958: WarnCount is the ALARMED warn count and EXCLUDES chronic warns
# (Check.warn(chronic=True) — the enumerated known-recurring timing set),
# which ride the separate, deliberately NON-alarmed ChronicWarnCount. Before
# this split WarnCount's honest daily floor was 4-11 against the >= 1
# threshold, so qa-smoke-warnings sat red 15+ consecutive nights and carried
# no information (ADR-105: a threshold must come from the metric's real
# distribution). The alarm, its threshold, and its load-bearing 86400s
# Maximum window are all UNCHANGED — only what counts into the metric moved.
QA_SMOKE_EMF_NAMESPACE = "LifePlatform/QaSmoke"


SWEEP_INTEGRITY_CATEGORY = "Sweep Integrity"


def run_isolated(label, fn):
    """Run ONE check-producing callable so a raise costs one check, not the sweep.

    #2307: qa_smoke_lambda's handler accumulated all 21 check calls inside a
    single ``try``, whose ``except`` re-raises. Any check that threw therefore
    cancelled every check after it — a null ``day_grade`` in dashboard/data.json
    raised out of ``check_score_sanity`` and took the 16 checks downstream of it
    with it. That is the self-concealing shape (#2287, #2271): a crashed sweep
    and a sweep with nothing to report look the same from outside.

    The raise is converted into an explicit ``sweep:<label>`` red rather than
    swallowed. ADR-104: a check that could not evaluate must SAY so — it is
    never counted as a pass, and never as a warn (a warn is a known-benign
    state; "the checker itself broke" is not one).

    Partition is DEPLOY_HEALTH deliberately. A check raising is evidence about
    the code that just shipped, and it is what the old behaviour already did to
    ci-cd — the handler's re-raise failed the whole invocation, which the smoke
    oracle reads as a deploy failure. Classifying it CONTENT_TRUTH would quietly
    WEAKEN the gate while this change was nominally about strengthening it.
    """
    try:
        return list(fn())
    except Exception as exc:  # noqa: BLE001 — converting a raise into a reported red IS the point
        return [
            Check(f"sweep:{label}", SWEEP_INTEGRITY_CATEGORY, DEPLOY_HEALTH).fail(
                f"{label} raised {type(exc).__name__}: {exc} — this check did not run, "
                "its result is UNKNOWN (not a pass). The rest of the sweep continued."
            )
        ]


def split_warns(checks):
    """Partition a run's warned checks into (alarmed, chronic) lists.

    The single classification chokepoint for BOTH check modules
    (qa_smoke_lambda and qa_check_reader_truth construct the same Check class,
    so every warn routes through the flag this reads): alarmed warns increment
    the WarnCount metric that qa-smoke-warnings fires on; chronic warns
    increment ChronicWarnCount, which no alarm watches (#1958). Paused checks
    set passed=True so they can never appear on either side.
    """
    warned = [c for c in checks if c.passed is None]
    return [c for c in warned if not c.chronic], [c for c in warned if c.chronic]


def emf_summary_line(
    *,
    passed: int,
    warned: int,
    failed: int,
    paused: int,
    timestamp_ms: int,
    failed_deploy_health: int = 0,
    failed_content_truth: int = 0,
    warned_chronic: int = 0,
) -> str:
    """Build the EMF log line CloudWatch extracts to LifePlatform/QaSmoke metrics.

    #1921 adds DeployHealthFailCount / ContentTruthFailCount alongside the
    unchanged FailCount total. Splitting the metric is what keeps the re-routing
    from becoming a mute: content-truth failures no longer revert a deploy, so
    they need a dimension of their own to alarm on rather than disappearing into
    an aggregate that the pipeline has stopped reacting to.

    #1958: `warned` is the ALARMED warn count (what qa-smoke-warnings fires on)
    and `warned_chronic` the known-recurring timing warns — a SEPARATE metric,
    not a component of WarnCount, so a night whose only warns are chronic emits
    WarnCount=0 and the alarm can actually clear. Callers pass the two sides of
    qa_check.split_warns() — never a recomputed subset.
    """
    doc = {
        "_aws": {
            "Timestamp": int(timestamp_ms),
            "CloudWatchMetrics": [
                {
                    "Namespace": QA_SMOKE_EMF_NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": [
                        {"Name": "PassCount"},
                        {"Name": "WarnCount"},
                        {"Name": "FailCount"},
                        {"Name": "PausedCount"},
                        {"Name": "RunCompleted"},
                        {"Name": "DeployHealthFailCount"},
                        {"Name": "ContentTruthFailCount"},
                        {"Name": "ChronicWarnCount"},
                    ],
                }
            ],
        },
        "PassCount": int(passed),
        "WarnCount": int(warned),
        "FailCount": int(failed),
        "PausedCount": int(paused),
        "RunCompleted": 1,
        "DeployHealthFailCount": int(failed_deploy_health),
        "ContentTruthFailCount": int(failed_content_truth),
        "ChronicWarnCount": int(warned_chronic),
    }
    return json.dumps(doc)
