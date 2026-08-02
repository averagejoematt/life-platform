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

    def ok(self, msg=""):
        self.passed = True
        self.message = msg
        return self

    def fail(self, msg=""):
        self.passed = False
        self.message = msg
        return self

    def warn(self, msg="", chronic=False):
        """Yellow. `chronic=True` is RESERVED for the enumerated known-recurring
        timing conditions (#1958: an OPTIONAL registry source with no record
        yesterday, and the MCP cache-warm partial) — warns that recur on a
        healthy platform by the source's own event-driven nature. A chronic
        warn stays fully visible (email, logs, ChronicWarnCount metric) but
        does NOT increment the alarmed WarnCount, so qa-smoke-warnings can
        reach green and a NOVEL warn class is unmissable again. The default is
        deliberately False: a new warn call site is alarmed unless it
        explicitly opts out, and tests/test_qa_smoke_chronic_warns.py
        AST-guards the full set of chronic=True call sites — extending the set
        means updating that test's enumerated registry, never a silent drift.
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
