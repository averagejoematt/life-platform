"""qa_check_reader_truth.py — the Reader Truth check pair, extracted from qa_smoke_lambda (#1665).

Split out because qa_smoke_lambda crossed the 1200-line hard ceiling when #1922
added the deterministic phase-plausibility pass. No contract change: qa_smoke
imports `check_reader_truth` and calls it exactly as before, and both checks
still carry the CONTENT_TRUTH partition (ADR-147 — neither may revert a deploy).

The pair is cohesive and belongs together: one deterministic arithmetic pass
(#1922, never budget-paused) and one LLM rubric pass (#1096, tier-gated), over
ONE fetch of the same surfaces.
"""

import logging
import os
import urllib.request

from operational import reader_truth_qa
from operational.qa_check import CONTENT_TRUTH, Check, finding_group, summarize_findings

logger = logging.getLogger(__name__)

# A temporal contradiction ("Day 2" narrating a 30-day trend) can sit live for
# days BETWEEN deploys with nothing looking at it — the post-deploy CI pass
# (#1095) only fires on a deploy. This check fetches a small surface set over
# HTTPS and runs the SAME rubric (lambdas/reader_truth_qa.py, Haiku per ADR-049).
# Posture: budget-aware (operator-truth band, tier 3 only per ADR-125 as amended by
# #1927 — reported as an explicit ⏸ skip, never silent green) and fail-SOFT on Bedrock/
# fetch errors (a Bedrock outage must never red the nightly). Only a HIGH truth
# finding is a failure (lands in the alert email); med/low are warnings.

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://averagejoematt.com")

# Small, reader-critical set: the cockpit, home, the coaching read, data vitals —
# plus the API payloads whose narrative/numeric values those pages bind. One
# Haiku batch (<= 8 surfaces as of #1937), still pennies per night.
READER_TRUTH_SURFACES = [
    ("/", "Home"),
    ("/now/", "Cockpit"),
    ("/coaching/", "Coaching read"),
    ("/data/vitals/", "Data · vitals"),
]
READER_TRUTH_APIS = [
    ("/api/vitals", "API · vitals"),
    ("/api/coaches", "API · coaches"),
    # #1937: added once their day-frame anchors moved off UTC to Pacific — each
    # publishes a `day_n` claim or a `_window_span`-derived `actual_days`/
    # `*_window_days` span, the exact class of claim that ran a day ahead every
    # PT evening before the fix (site_api_vitals.py).
    ("/api/journey", "API · journey"),
    ("/api/glucose", "API · glucose"),
    ("/api/sleep_detail", "API · sleep detail"),
]

# #1922: API payloads swept by the DETERMINISTIC phase-plausibility pass with
# the strict "Day N"-in-prose rule. Strict is right where no prior-cycle
# narration can legitimately appear (vitals is clamped-to-genesis by ADR-077);
# narrative payloads (coaches) may narrate a labeled prior cycle, so their
# prose day-claims stay with the LLM's temporal_contradiction category.
# #1937: /api/journey, /api/glucose, /api/sleep_detail joined once their
# handlers anchored "today" in Pacific (matching vitals' contract — clamped to
# genesis, no legitimate prior-cycle narration).
# #2613: DERIVED, not restated. This is the same set whose pre-cycle-date question
# the LLM rubric no longer adjudicates, so the two passes' division of labour is one
# list — adding a strict payload here can never leave the rubric still judging it.
STRICT_PLAUSIBILITY_APIS = reader_truth_qa.CODE_OWNED_TEMPORAL_SURFACES

# #1985: FROZEN story artifacts — documents whose text is deliberately preserved
# as filed. They are allowed to quote a superseded figure; they are not allowed
# to quote it un-reconciled. Checked deterministically and never sent to the LLM
# (see _check_frozen_artifacts), so they add no tokens to the nightly batch.
FROZEN_ARTIFACT_SURFACES = [
    ("/journal/posts/week-01/", "Prologue I · Before the Numbers"),
    ("/journal/posts/week-02/", "Prologue II · The Night Before Everything"),
    ("/journal/posts/week-03/", "Prologue III · The Plan, On the Record"),
]


def _fetch_reader_truth_surfaces():
    """Fetch the reader-truth surface set. Returns (surfaces, fetch_warnings).

    Pages are tag-stripped to visible-ish text (static-HTML approximation of the
    browser innerText the CI pass sees); API payloads go in as raw JSON text.
    Every failure is a warning string, never an exception (fail-soft).
    """
    from operational import reader_truth_qa

    surfaces, warnings = [], []
    # #1985: frozen artifacts ride the SAME fetch so there is ONE network point
    # (one thing for tests to stub, one failure mode). They are tagged frozen=True
    # and filtered out of the LLM batch below — deterministic only, zero tokens.
    _fetch_set = [(p, n, False) for p, n in READER_TRUTH_SURFACES + READER_TRUTH_APIS]
    _fetch_set += [(p, n, True) for p, n in FROZEN_ARTIFACT_SURFACES]
    for path, name, frozen in _fetch_set:
        try:
            req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", "replace")
            prose = body if path.startswith("/api/") else reader_truth_qa.html_to_text(body)
            surfaces.append({"name": name, "path": path, "prose": prose, "frozen": frozen})
        except Exception as e:
            warnings.append(f"{name} ({path}) — fetch failed: {str(e)[:100]}")
    return surfaces, warnings


def _check_phase_plausibility(surfaces):
    """#1922: the deterministic half of Reader Truth. Pure arithmetic over the
    fetched API payloads (the #1917 registry + span/day rules) — zero tokens,
    so it is NEVER budget-paused: the 26-day dark window that hid drift from
    the LLM pass (#1920/ADR-147 §5) structurally cannot happen here. Runs on
    the same fetched surfaces and reports through the same Reader Truth path.
    """
    det = Check("reader_truth:plausibility", "Reader Truth", CONTENT_TRUTH)
    try:
        from operational import phase_plausibility, reader_truth_qa

        payloads = [
            {"path": p["path"], "body": p["prose"], "strict": p["path"] in STRICT_PLAUSIBILITY_APIS}
            for p in surfaces
            if p["path"].startswith("/api/")
        ]
        if not payloads:
            return [det.warn("no API payloads fetched — deterministic pass skipped this run (fail-soft)")]
        findings, warnings = phase_plausibility.sweep_payloads(payloads)
        phase = reader_truth_qa.phase_context()
        day = f"{phase['days_until_start']}d pre-start" if phase["pre_start"] else f"Day {phase['day_n']}"
        checks = []
        for w in warnings:
            checks.append(Check("reader_truth:plausibility", "Reader Truth", CONTENT_TRUTH).warn(f"{w} — NOT checked"))
        if findings:
            # #2620: same summary, plus the untruncated note beneath it.
            summary, detail_lines = summarize_findings(findings)
            det.fail(f"{len(findings)} phase-impossible claim(s) at {day} (deterministic): {summary}").with_details(detail_lines)
        else:
            det.ok(f"{len(payloads)} API payload(s) phase-plausible at {day} (deterministic, no AI)")
        checks.append(det)
        return checks
    except Exception as e:
        return [det.warn(f"phase-plausibility errored — skipped this run (fail-soft): {str(e)[:120]}")]


def _check_frozen_artifacts(surfaces):
    """#1985: a frozen story artifact quoting a superseded bodyweight must carry
    its editor's-note reconciliation.

    Fetched SEPARATELY from the reader-truth set and never sent to the LLM: the
    rule is pure arithmetic plus a marker test, so it costs zero tokens and — like
    the #1922 plausibility pass — can never be budget-paused dark. Keeping these
    pages out of READER_TRUTH_SURFACES also keeps the Haiku batch at its current
    size.

    Guarded as a SET: the baseline comes from constants, so the next supersede is
    caught without anyone remembering to add a literal here.
    """
    det = Check("reader_truth:frozen_artifacts", "Reader Truth", CONTENT_TRUTH)
    try:
        from common import constants

        from operational import weight_truth_qa

        pages = [s for s in surfaces if s.get("frozen")]
        if not pages:
            return [det.warn("no frozen artifacts fetched — check skipped this run (fail-soft)")]

        baseline = float(constants.EXPERIMENT_BASELINE_WEIGHT_LBS)
        findings = weight_truth_qa.assess_frozen_artifact_weights(pages, baseline)
        if findings:
            # #2620: these findings carry `detail`, not `note`, and no severity —
            # summarize_findings is shape-tolerant so this path gets the same
            # recoverability without inventing fields for it.
            summary, detail_lines = summarize_findings(findings, key="detail", width=110, inline=3)
            det.fail(
                f"{len(findings)} frozen artifact(s) quote a superseded weight with no editor's note "
                f"(baseline {baseline} lbs): {summary}"
            ).with_details(detail_lines)
        else:
            det.ok(f"{len(pages)} frozen artifact(s) reconcile against {baseline} lbs (deterministic, no AI)")
        return [det]
    except Exception as e:
        return [det.warn(f"frozen-artifact check errored — skipped this run (fail-soft): {str(e)[:120]}")]


def _confirm_high_findings(highs, surfaces):
    """Second opinion on the same surfaces; only findings in BOTH passes may FAIL.

    → (confirmed, unconfirmed, note_or_None)

    Identity is `finding_group` (page|category), which is run-invariant BY DESIGN —
    its docstring is explicit that the note is reworded every night and the id
    deliberately excludes it, which is what makes cross-run matching meaningful here.

    COST is bounded on purpose: this runs ONLY when the first pass produced a high,
    i.e. only on the nights that would otherwise have FAILed. A clean night pays
    nothing, so the nightly Bedrock bill is unchanged in the common case — which
    matters while #2734 has month-end projected above the ceiling.

    FAIL-CLOSED. If the confirmation pass itself errors we return every high as
    confirmed. A second opinion that cannot be obtained must never be the reason a
    genuine finding is downgraded — the failure direction has to preserve the old
    behaviour, not silence it.
    """
    try:
        from ai import bedrock_client

        from operational import reader_truth_qa

        again, _errs = reader_truth_qa.assess_prose(surfaces, bedrock_client.invoke)
    except Exception as e:  # noqa: BLE001
        return highs, [], f"confirmation pass unavailable, treating all highs as confirmed (fail-closed): {str(e)[:120]}"
    second = {finding_group(f) for f in again if (f or {}).get("severity") == "high"}
    confirmed = [f for f in highs if finding_group(f) in second]
    unconfirmed = [f for f in highs if finding_group(f) not in second]
    note = None
    if unconfirmed:
        ids = ", ".join(sorted({finding_group(f) for f in unconfirmed}))
        note = (
            f"{len(unconfirmed)} high finding(s) did not reproduce on a second pass and were demoted to WARN "
            f"(#2741 — measured 2/8 flake on identical content): {ids}"
        )
    return confirmed, unconfirmed, note


def check_reader_truth():
    checks = []
    verdict = Check("reader_truth:verdict", "Reader Truth", CONTENT_TRUTH)

    # Fetch ONCE — both the deterministic and the LLM pass read this set.
    surfaces, fetch_warnings = _fetch_reader_truth_surfaces()
    for w in fetch_warnings:
        checks.append(Check("reader_truth:fetch", "Reader Truth", CONTENT_TRUTH).warn(f"{w} (fail-soft)"))
    if not surfaces:
        checks.append(verdict.warn("no surfaces fetched — Reader Truth skipped this run (fail-soft)"))
        return checks

    # Deterministic pass FIRST, unconditionally (#1922) — arithmetic has no
    # budget tier. Only the LLM half below is subject to the pause ladder.
    checks.extend(_check_phase_plausibility(surfaces))

    # #1985: frozen artifacts — deterministic and token-free like the pass above.
    checks.extend(_check_frozen_artifacts(surfaces))

    # Frozen artifacts are checked deterministically ONLY; they must not enlarge
    # the Haiku batch (cost) nor be judged by prose rules written for live pages.
    surfaces = [s for s in surfaces if not s.get("frozen")]

    # Budget gate — operator-truth band, tier 3 only (ADR-125/#1927). Explicit ⏸, never silent.
    try:
        from ai import budget_guard

        from operational import reader_truth_qa

        if not budget_guard.allow(reader_truth_qa.BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            # #1440: emit the QAPausedByBudget metric — a daily CloudWatch alarm on
            # it (monitoring_stack.py, to_digest=True) reaches the alerts-digest
            # email even on a day where check_reader_truth is the ONLY paused/failed
            # check (lambda_handler only emails on a real FAILURE; a pause alone
            # would otherwise never leave CloudWatch Logs).
            reader_truth_qa.emit_budget_pause_metric("qa_smoke", tier)
            checks.append(verdict.pause(f"Reader Truth AI skipped — budget tier {tier} (operator-truth band, ADR-125/#1927)"))
            return checks
    except Exception as e:
        # Import/SSM blip: same fail-open posture as budget_guard itself — but if
        # the shared module is missing the sweep below can't run either, so warn.
        logger.warning("reader-truth budget gate degraded: %s", e)

    try:
        from ai import bedrock_client

        from operational import reader_truth_qa

        findings, errors = reader_truth_qa.assess_prose(surfaces, bedrock_client.invoke)
        phase = reader_truth_qa.phase_context()
        day = f"{phase['days_until_start']}d pre-start" if phase["pre_start"] else f"Day {phase['day_n']}"
    except Exception as e:
        # Bedrock outage / missing module / AccessDenied — an explicit soft skip.
        checks.append(verdict.warn(f"Reader Truth AI unavailable — skipped this run (fail-soft): {str(e)[:120]}"))
        return checks

    for err in errors:
        checks.append(Check("reader_truth:batch", "Reader Truth", CONTENT_TRUTH).warn(f"AI batch error (fail-soft): {err}"))

    # #2620: BOTH severities get the detail treatment, not just the failing one.
    # The low/med path is the one nobody reproduces by hand — a warn that cannot
    # be read is a warn that is never triaged, which is how a low finding stays
    # low forever. Same helper, same guarantees, one call each.
    highs = [f for f in findings if f["severity"] == "high"]
    lower = [f for f in findings if f["severity"] != "high"]

    # #2741: a `high` is what makes this a FAIL, and a FAIL is what reddens
    # qa-smoke-failures — so a single non-deterministic call must not be the whole
    # basis for it. Measured 2026-08-15: the same durable-design-copy finding
    # appeared in 2 of 8 runs against byte-identical content, at two different
    # severities (low/med, then high) with two different rationales. `high` maps
    # to fail() below, so the alarm's FAIL boundary was a coin flip.
    if highs:
        highs, unconfirmed, conf_note = _confirm_high_findings(highs, surfaces)
        if conf_note:
            checks.append(Check("reader_truth:confirm", "Reader Truth", CONTENT_TRUTH).warn(conf_note))
        # An unconfirmed high is NOT dropped — flaky is not the same as absent, and
        # silently discarding it would be the #2640 pattern this file exists to police.
        # It is demoted to the WARN bucket, still named, still carrying its detail.
        lower = lower + unconfirmed

    if highs:
        summary, detail_lines = summarize_findings(highs)
        verdict.fail(f"{len(highs)} high truth finding(s) at {day}, confirmed on a second pass: {summary}").with_details(detail_lines)
    elif lower:
        summary, detail_lines = summarize_findings(lower)
        verdict.warn(f"{len(lower)} low/med truth finding(s) at {day}: {summary}").with_details(detail_lines)
    elif errors:
        verdict.warn(f"no verdict at {day} — all {len(errors)} AI batch(es) errored (fail-soft)")
    else:
        verdict.ok(f"{len(surfaces)} surfaces clean at {day} — no truth findings")
    checks.append(verdict)
    return checks
