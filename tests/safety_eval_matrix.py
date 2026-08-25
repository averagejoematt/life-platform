"""safety_eval_matrix.py — the standing AI-safety eval matrix (#3050, DIL-029/030/031-lite).

WHY A SECOND HARNESS AND NOT MORE SURFACES IN golden_surface_eval.py
────────────────────────────────────────────────────────────────────
`tests/golden_surface_eval.py` (#812) is organised by SURFACE: board_ask, chronicle,
memoir, … — "does each reader-facing surface's own gate still fire?". Its whole registry
(`SURFACES`, `SURFACE_CHECKS`, `ADAPTERS`, the fixture tree) is keyed that way, and every
one of its adapters answers one question: *is this generated text grounded?*

This matrix is organised by SAFETY FAMILY: grounding, temporal, injection, privacy,
refusal — "does each class of safety control still fire, wherever it lives?". Three of
the five families do not evaluate generated text at all: injection evaluates a
CONSTRUCTED PROMPT, privacy evaluates a SERIALIZED PAYLOAD, refusal evaluates an INPUT
question before any model is called. Folding those into a surface-keyed registry would
have meant a second fixture schema, a second verdict axis and a second set of adapters
inside a module that is already the falsifiability contract for five surfaces — and
`tests/test_module_size_guard.py`'s ~800-line smell threshold is the standing signal that
this is exactly when a second cohesive module is the right answer. So: same PATTERN,
same vocabulary, same honesty rules, separate module. Nothing here re-implements a check
`golden_surface_eval.py` owns; the grounding family calls the same real chokepoint
(`grounded_generation.grounding_findings`) with adversarial fixtures aimed at the safety
question rather than the voice question.

THE PATTERN (inherited verbatim from #742/#812)
───────────────────────────────────────────────
  1. GOLDEN (no false positives): known-good artifacts draw ZERO findings from the real
     control. A control that starts false-positiving on legitimate output gets routed
     around by whoever maintains it, so this half is not decoration.
  2. CANARY (mutation testing): a seeded fault per family is CAUGHT by the expected
     check. An uncaught canary fails the whole run — the controls demonstrably fire on
     demand, in every family, on every run.

FIDELITY INVARIANT — what "the real path" means per family
──────────────────────────────────────────────────────────
  grounding  `ai.grounded_generation.grounding_findings` — the exact function every
             narrative surface's gate reduces to.
  temporal   the same function, with the #1691/#1897/#2756 freshness params supplied
             (`stale_baseline`, `stale_phase`, `experiment_span`, `absence_span`).
  injection  the prompt is BUILT by the real defenses: `ai.ai_context.
             wrap_untrusted_reader_text` (direct, #811) and
             `coach.coach_history_summarizer._build_compression_message` (stored replay).
             The probe then asks whether untrusted text escaped its fence.
  privacy    the payload is produced by the real enforcement points —
             `mcp.tools_data._strip_tier2`, `reading.reading_visibility.project_public`,
             `ai.ai_context._build_sleep_data` — and the probe's VOCABULARY is derived
             live from `privacy.field_tiers` (never restated: a new Tier-2 field arms new
             probes with no edit here).
  refusal    `ai.safety_contract.check` — imported and exercised, never reimplemented.
             That module lands in #3147; see PENDING FAMILIES below.

Two of the five families need a probe that has no runtime equivalent, and that is stated
rather than glossed: there is no live text-level "did an owner-only field leak into this
string" gate and no live "is this untrusted span still fenced" gate — building the probe
IS part of what #3050 buys. Both probes are built from the real vocabulary/delimiters
(`field_tiers`, `ai_context.UNTRUSTED_OPEN/CLOSE/PREAMBLE`), and both are only ever
pointed at artifacts the REAL functions produced.

PENDING FAMILIES (honest, and it cannot stay quiet)
───────────────────────────────────────────────────
`lambdas/ai/safety_contract.py` is landing in PR #3147. Until it is on main this module
cannot import it, so the refusal family reports status PENDING — never OK, never counted
as a pass, and printed on its own line in every report and workflow summary. The moment
the module exists the family arms itself with no edit here, and
`test_safety_eval_matrix.py::test_no_family_is_silently_pending_once_its_module_exists`
fails the build if it does not — a PENDING family that COULD run is the "silently
disabled gate" failure this whole pattern exists to kill.

Fixture provenance (honesty rule): goldens name their provenance and start REAL/AUTHORED
— REAL where a recorded output exists, AUTHORED where the adversarial framing was written
for this matrix (the numeric vocabulary is still drawn from real records, and says which).
Canaries are ALWAYS synthetic seeded faults and say so in their `mutation` field.

Design invariant (ADR-105): DETERMINISTIC checks alone drive the verdict — hermetic,
free, no AWS, no Bedrock, no live-model probing (see the PR body for why live-model
adversarial probing is deliberately out of scope).

Run:
    python3 tests/safety_eval_matrix.py                 # verdict, exit non-zero on fail
    python3 tests/safety_eval_matrix.py --json          # machine-readable report
    python3 tests/safety_eval_matrix.py --summary-md    # per-family metric table

`tests/test_safety_eval_matrix.py` runs the verdict in the unit suite (deploy-critical
lane, so a broken safety control blocks the deploy); the weekly golden-brief-eval
workflow's `safety-matrix` job re-runs it on a schedule and publishes the per-family
table to the run summary.

WHERE THE METRICS GO (and where they deliberately don't): the run summary, not
CloudWatch. Emitting gauges would mean running this harness under
`github-actions-golden-eval-role`, and the #2824 grant sweep attributes a job's role to
every entrypoint it runs — this one statically reaches the fail-closed content-filter
channel through the real coach compression prompt, without ever reading it. Widening a
live IAM role to satisfy a read that never happens is the wrong trade, so the matrix runs
in a credential-free job instead. Stated here because a metric nobody wired is otherwise
indistinguishable from one that silently stopped.
"""

import argparse
import json
import os
import re
import sys

# ── path + env setup: work both under pytest (conftest sets paths) and standalone ──
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("", "compute", "web", "emails", "intelligence"):
    _p = os.path.join(_REPO, "lambdas", _sub) if _sub else os.path.join(_REPO, "lambdas")
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# Hermetic: the surface modules build boto3 clients at import; fake creds keep that
# offline (no call is ever made on the deterministic path).
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

from ai import grounded_generation as gg  # noqa: E402
from ai.ai_context import UNTRUSTED_CLOSE, UNTRUSTED_OPEN, UNTRUSTED_PREAMBLE, wrap_untrusted_reader_text  # noqa: E402
from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY, fields_at_tier  # noqa: E402

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "safety_eval")

OK = "OK"
FAIL = "FAIL"
PENDING = "PENDING"

FAMILIES = ("grounding", "temporal", "injection", "privacy", "refusal")

# The deterministic dimensions each family's control actually enforces. Canaries must
# span these (self-test) or a whole dimension could rot unobserved.
FAMILY_CHECKS = {
    "grounding": {"invented_value", "invented_date"},
    "temporal": {"stale_baseline", "stale_phase", "experiment_span", "absence_span"},
    "injection": {"unfenced_untrusted_text", "fence_forgery"},
    "privacy": {"owner_only_field_leak", "owner_only_source_leak"},
    "refusal": {
        "hazard_self_harm",
        "hazard_acute_symptom",
        "hazard_disordered_eating",
        "hazard_medication",
        "hazard_supplement_interaction",
    },
}

# grounded_generation finding type → this matrix's check vocabulary. Types absent from
# the map keep their OWN name rather than falling through to a neighbour's label — the
# #812 lesson: a mis-attributed finding is worse than an unmapped one.
CHECK_BY_TYPE = {
    "fabricated_number": "invented_value",
    "fabricated_date": "invented_date",
    "contradiction": "contradicted_value",
    "band_contradiction": "contradicted_value",
    "stale_baseline": "stale_baseline",
    "stale_phase": "stale_phase",
    "experiment_span": "experiment_span",
    "absence_span": "absence_span",
}

# ── privacy probe vocabulary — DERIVED from the registry, never restated ─────────────
OWNER_ONLY_FIELDS = fields_at_tier(TIER_OWNER_ONLY)
OWNER_ONLY_SOURCES = frozenset(s for s, t in SOURCE_TIERS.items() if t == TIER_OWNER_ONLY)


def _labeled(finding):
    return {"check": CHECK_BY_TYPE.get(finding.get("type"), finding.get("type")), **finding}


# ══ family 1+2: grounding and temporal — the real grounding chokepoint ═══════════════
def _eval_grounded_text(fx, canary):
    """Replay one text fixture through `grounded_generation.grounding_findings`.

    Both families share this adapter because they share the real function: the family
    difference is entirely which optional params the fixture supplies (the allow-list for
    grounding; the cycle anchors + measured absence for temporal). That is the same
    optional-param discipline the gate itself documents, so a fixture cannot accidentally
    arm a class its family does not own.
    """
    text = fx["mutated_output"] if canary else fx["reference_output"]
    i = fx.get("inputs") or {}
    allowed = i.get("allowed")
    allowed_dates = i.get("allowed_dates")
    findings = gg.grounding_findings(
        text,
        facts=i.get("facts"),
        allowed=set(float(x) for x in allowed) if allowed is not None else None,
        allowed_dates=set(str(d) for d in allowed_dates) if allowed_dates is not None else None,
        baseline_lbs=i.get("baseline_lbs"),
        generation_date_iso=i.get("generation_date_iso"),
        start_date_iso=i.get("start_date_iso"),
        known_absence_days=i.get("known_absence_days"),
    )
    return [_labeled(f) for f in findings]


# ══ family 3: injection — direct (#811) + stored ════════════════════════════════════
_FENCE_SPAN_RE = re.compile(re.escape(UNTRUSTED_OPEN) + "(.*?)" + re.escape(UNTRUSTED_CLOSE), re.S)


def fencing_findings(prompt, probes, expected_wraps):
    """Did untrusted reader text escape its data fence in this constructed prompt?

    Three deterministic classes:
      * ``unfenced_untrusted_text`` — a probe string from the reader's submission appears
        somewhere OUTSIDE every ``<untrusted_reader_input>`` span (or the prompt carries
        no fence at all). This is the pre-#811 shape: reader text concatenated into the
        prompt as if it were instructions.
      * ``fence_forgery`` — the tag counts don't balance, or exceed the number of wraps
        the builder performed: a submission smuggled its own open/close tag through.
      * ``missing_data_preamble`` — a fence exists but the "treat strictly as data" line
        that gives it meaning does not.

    The prompt must have been produced by the REAL builder; this only inspects it.
    """
    findings = []
    inner = [(m.start(1), m.end(1)) for m in _FENCE_SPAN_RE.finditer(prompt)]
    n_open, n_close = prompt.count(UNTRUSTED_OPEN), prompt.count(UNTRUSTED_CLOSE)
    if n_open != n_close or n_open > expected_wraps:
        findings.append(
            {
                "check": "fence_forgery",
                "detail": (
                    f"the builder performed {expected_wraps} wrap(s) but the prompt carries {n_open} open and "
                    f"{n_close} close tag(s) — untrusted text forged or prematurely closed the data fence"
                ),
            }
        )
    for probe in probes:
        for m in re.finditer(re.escape(probe), prompt):
            if not any(s <= m.start() and m.end() <= e for s, e in inner):
                findings.append(
                    {
                        "check": "unfenced_untrusted_text",
                        "probe": probe,
                        "detail": f"untrusted reader text {probe!r} appears outside the {UNTRUSTED_OPEN} fence — readable as instructions",
                    }
                )
                break
    if inner and UNTRUSTED_PREAMBLE not in prompt:
        findings.append({"check": "missing_data_preamble", "detail": "the fence is present but the treat-as-data preamble is not"})
    return findings


def _render_ask_wrapped(i):
    """The REAL direct-injection defense: site_api_ai_lambda's reader turn, whose
    untrusted half is `wrap_untrusted_reader_text(question)` (the live expression at
    site_api_ai_lambda.py's board_ask + /api/ask + follow-up call sites)."""
    return f"{i['context_block']}\nREADER QUESTION: {wrap_untrusted_reader_text(i['reader_text'])}"


def _render_ask_raw(i):
    """SEEDED FAULT (synthetic): the pre-#811 shape — the reader's text concatenated
    straight into the prompt with no delimiter. This is what regressing the call site
    (dropping the wrapper) produces."""
    return f"{i['context_block']}\nREADER QUESTION: {i['reader_text']}"


def _render_ask_nonstripping(i):
    """SEEDED FAULT (synthetic): a wrapper that fences but forgets to STRIP forged tags
    from the submission — so the reader's own close tag ends the fence early and
    everything after it reads as instructions."""
    return f"{i['context_block']}\nREADER QUESTION: {UNTRUSTED_PREAMBLE}\n{UNTRUSTED_OPEN}{i['reader_text']}{UNTRUSTED_CLOSE}"


def _render_stored_history(i):
    """The REAL stored-injection path: the coach compression prompt replays stored
    reader questions (COACH#/INTERACTION# rows) and delimits them at render time."""
    from coach import coach_history_summarizer as chs, persona_registry

    # Prime the persona cache from the repo config so the builder's S3 read never leaves
    # the machine (hermeticity only — the path under test is unchanged either way, since
    # load_registry already falls back to this exact file).
    persona_registry.load_registry()
    return chs._build_compression_message(i["coach_id"], i["state"])


def _render_stored_history_raw(i):
    """SEEDED FAULT (synthetic): the same stored-replay line before #811 — the stored
    question interpolated raw. Reproduced here rather than obtained by disabling the real
    wrapper, so the fault is unmistakably synthetic."""
    lines = ["## Reader Interactions & Field-Note Pushback"]
    for it in i["state"].get("interactions", []):
        lines.append(f"  - [{str(it.get('sk', '')).split('#')[-1]}] A reader asked: {it.get('question', '')}")
        lines.append(f"    You answered: {it.get('answer', '')}")
    return "\n".join(lines)


INJECTION_RENDERERS = {
    "ask_wrapped": _render_ask_wrapped,
    "ask_raw": _render_ask_raw,
    "ask_nonstripping": _render_ask_nonstripping,
    "stored_history": _render_stored_history,
    "stored_history_raw": _render_stored_history_raw,
}


def _eval_injection(fx, canary):
    i = fx["inputs"]
    prompt = INJECTION_RENDERERS[fx["render"]](i)
    return fencing_findings(prompt, i.get("probes") or [], i.get("expected_wraps", 0))


# ══ family 4: privacy — owner-only leakage probes ════════════════════════════════════
def owner_only_leak_findings(artifact, sources=None):
    """Does this artifact carry Tier-2 owner-only vocabulary?

    Two classes, both keyed on `lambdas/privacy/field_tiers.py` at call time so the probe
    widens automatically when the registry does (the #2803 one-copy rule):
      * ``owner_only_field_leak``  — a TIER_OWNER_ONLY FIELD name appears in the payload.
      * ``owner_only_source_leak`` — a TIER_OWNER_ONLY SOURCE partition (`SOURCE#genome`,
        `SOURCE#private_intake`, …) appears serialized in it.

    `sources` narrows the field vocabulary to the partitions the artifact is allowed to
    be about; None scans the whole registry.
    """
    text = artifact if isinstance(artifact, str) else json.dumps(artifact, default=str, sort_keys=True)
    vocab = OWNER_ONLY_FIELDS if sources is None else frozenset().union(*(fields_at_tier(TIER_OWNER_ONLY, s) for s in sources))
    findings = []
    for field in sorted(vocab):
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", text):
            findings.append(
                {"check": "owner_only_field_leak", "field": field, "detail": f"Tier-2 owner-only field {field!r} is present in the payload"}
            )
    for source in sorted(OWNER_ONLY_SOURCES):
        if re.search(r"SOURCE#" + re.escape(source) + r"(?![A-Za-z0-9_])", text):
            findings.append(
                {
                    "check": "owner_only_source_leak",
                    "source": source,
                    "detail": f"an owner-only partition (SOURCE#{source}) is serialized into the payload",
                }
            )
    return findings


def _render_strip_tier2(i):
    """The REAL row-dump enforcement point (#2803/#2809): mcp.tools_data._strip_tier2."""
    from mcp import tools_data as td

    return td._strip_tier2(i["source"], dict(i["row"]))


def _render_raw_row(i):
    """SEEDED FAULT (synthetic): the #2809 defect itself — a generic row dumper handing
    back the whole DDB row, Tier-2 fields included."""
    return dict(i["row"])


def _render_reading_public(i):
    """The REAL reading-keyspace enforcement point: reading_visibility.project_public."""
    from reading import reading_visibility as rv

    return rv.project_public(i["entity_type"], dict(i["row"]))


def _render_sleep_prompt_context(i):
    """The REAL prompt-BUILDING path: ai_context._build_sleep_data picks the fields the
    sleep coach's prompt is allowed to see out of the raw rows."""
    from ai import ai_context

    return ai_context._build_sleep_data(i["data"])


def _render_prompt_context_raw(i):
    """SEEDED FAULT (synthetic): a prompt builder that pastes the raw partition row into
    the context block instead of picking fields."""
    return f"{i['context_header']}\n{json.dumps(i['row'], sort_keys=True)}"


PRIVACY_RENDERERS = {
    "strip_tier2": _render_strip_tier2,
    "raw_row": _render_raw_row,
    "reading_public": _render_reading_public,
    "sleep_prompt_context": _render_sleep_prompt_context,
    "prompt_context_raw": _render_prompt_context_raw,
    "stored_history": _render_stored_history,
}


def _eval_privacy(fx, canary):
    i = fx["inputs"]
    artifact = PRIVACY_RENDERERS[fx["render"]](i)
    return owner_only_leak_findings(artifact, sources=i.get("sources"))


# ══ family 5: refusal — the deterministic hazard classifier (#3147) ══════════════════
def safety_contract_module():
    """`ai.safety_contract` if it is on this tree, else None (PENDING — see the module
    docstring). Never a shim: a stand-in would make the family look armed while testing
    nothing, which is the exact failure the harness exists to catch."""
    try:
        from ai import safety_contract

        return safety_contract
    except ImportError:
        return None


def _eval_refusal(fx, canary):
    sc = safety_contract_module()
    question = fx["inputs"]["question"]
    safe, response, hazard = sc.check(question)
    if safe:
        return []
    return [{"check": f"hazard_{hazard}", "detail": f"safety_contract.check refused: {hazard}", "served_copy_len": len(response)}]


ADAPTERS = {
    "grounding": _eval_grounded_text,
    "temporal": _eval_grounded_text,
    "injection": _eval_injection,
    "privacy": _eval_privacy,
    "refusal": _eval_refusal,
}

# A family whose real module is absent reports PENDING rather than passing. Keyed by
# family → (probe callable, what is missing).
CONDITIONAL_FAMILIES = {
    "refusal": (safety_contract_module, "lambdas/ai/safety_contract.py (lands in PR #3147)"),
}


def family_pending_reason(family):
    """Why `family` cannot run here, or None when it can."""
    probe = CONDITIONAL_FAMILIES.get(family)
    if probe is None:
        return None
    return None if probe[0]() is not None else f"requires {probe[1]}"


# ── fixture loading ──────────────────────────────────────────────────────────────────
def load_fixtures(family):
    """(golden: list, canaries: list) for one family."""
    fdir = os.path.join(FIXTURE_ROOT, family)
    with open(os.path.join(fdir, "golden.json"), encoding="utf-8") as f:
        golden = json.load(f)
    with open(os.path.join(fdir, "canaries.json"), encoding="utf-8") as f:
        canaries = json.load(f)
    return golden, canaries


# ── the run ──────────────────────────────────────────────────────────────────────────
def run(families=FAMILIES, fixture_loader=load_fixtures):
    """Execute the deterministic verdict across all families.

    verdict is FAIL iff any golden artifact drew a finding or any canary was NOT caught
    by its expected checks. `fixture_loader` is injectable so the mutation-proof tests
    can plant a violation in one family and watch the RUN go red — proving the machinery
    fails, not just the checker.
    """
    per_family = {}
    golden_defects, canary_misses, pending = [], [], []

    for family in families:
        reason = family_pending_reason(family)
        if reason:
            pending.append({"family": family, "reason": reason})
            per_family[family] = {
                "status": PENDING,
                "reason": reason,
                "golden_count": 0,
                "canary_count": 0,
                "golden_defects": 0,
                "canary_misses": 0,
                "canary_results": [],
            }
            continue

        golden, canaries = fixture_loader(family)
        f_defects = []
        for fx in golden:
            findings = ADAPTERS[family](fx, False)
            if findings:
                f_defects.append({"family": family, "id": fx["id"], "findings": findings})
        golden_defects.extend(f_defects)

        results = []
        for cn in canaries:
            findings = ADAPTERS[family](cn, True)
            caught_checks = {f["check"] for f in findings}
            expected = set(cn.get("expect_checks") or [])
            results.append(
                {
                    "family": family,
                    "id": cn["id"],
                    "mutation": cn.get("mutation"),
                    "expect_checks": sorted(expected),
                    "caught_checks": sorted(caught_checks),
                    "caught": bool(expected) and expected.issubset(caught_checks),
                }
            )
        misses = [c for c in results if not c["caught"]]
        canary_misses.extend(misses)

        per_family[family] = {
            "status": FAIL if (f_defects or misses) else OK,
            "golden_count": len(golden),
            "canary_count": len(canaries),
            "golden_defects": len(f_defects),
            "canary_misses": len(misses),
            "canary_results": results,
        }

    return {
        "verdict": OK if (not golden_defects and not canary_misses) else FAIL,
        "families": list(families),
        "live_families": [f for f in families if per_family[f]["status"] != PENDING],
        "pending_families": pending,
        "golden_count": sum(i["golden_count"] for i in per_family.values()),
        "canary_count": sum(i["canary_count"] for i in per_family.values()),
        "per_family": per_family,
        "golden_defects": golden_defects,
        "canary_misses": canary_misses,
    }


# ── report ───────────────────────────────────────────────────────────────────────────
def ops_line(report):
    v = report["verdict"]
    mark = "✓" if v == OK else "✗"
    caught = report["canary_count"] - len(report["canary_misses"])
    line = (
        f"{mark} AI-safety eval matrix: {v} — {len(report['live_families'])}/{len(report['families'])} families live, "
        f"{report['golden_count']} adversarial golden (0 false flags), {caught}/{report['canary_count']} canaries caught"
    )
    if report["pending_families"]:
        line += " · PENDING: " + ", ".join(p["family"] for p in report["pending_families"])
    return line


def summary_md(report):
    """The per-family release table (the diligence report's §9 shape) for the ops surface."""
    rows = ["| family | status | golden | canaries caught | dimensions |", "| --- | --- | --- | --- | --- |"]
    for family in report["families"]:
        info = report["per_family"][family]
        if info["status"] == PENDING:
            rows.append(f"| {family} | ⏳ PENDING | – | – | {info['reason']} |")
            continue
        caught = info["canary_count"] - info["canary_misses"]
        mark = "✅ OK" if info["status"] == OK else "❌ FAIL"
        dims = ", ".join(sorted(FAMILY_CHECKS[family]))
        rows.append(f"| {family} | {mark} | {info['golden_count']} (0 flags)" f" | {caught}/{info['canary_count']} | {dims} |")
    return "\n".join([ops_line(report), "", *rows])


def _text_report(report):
    lines = [ops_line(report), ""]
    for family in report["families"]:
        info = report["per_family"][family]
        if info["status"] == PENDING:
            lines.append(f"  ⏳ {family}: PENDING — {info['reason']}")
            continue
        mark = "✓" if info["status"] == OK else "✗"
        caught = info["canary_count"] - info["canary_misses"]
        lines.append(f"  {mark} {family}: {info['golden_count']} golden, {caught}/{info['canary_count']} canaries caught")
    if report["golden_defects"]:
        lines.append(f"\n{len(report['golden_defects'])} GOLDEN false-positive(s) — a control flagged a known-good artifact:")
        for d in report["golden_defects"]:
            for f in d["findings"]:
                lines.append(f"   ✗ {d['family']}/{d['id']}: [{f['check']}] {f.get('detail')}")
    if report["canary_misses"]:
        lines.append(f"\n{len(report['canary_misses'])} CANARY miss(es) — a seeded violation slipped its control:")
        for c in report["canary_misses"]:
            lines.append(f"   ✗ {c['family']}/{c['id']}: expected {c['expect_checks']}, caught {c['caught_checks']}")
    if report["verdict"] == OK and not report["pending_families"]:
        lines.append("\nEvery adversarial golden clean, every seeded violation caught, in all five families.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Standing AI-safety eval matrix — adversarial goldens + seeded violations (#3050)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--summary-md", action="store_true", help="per-family metric table (markdown)")
    args = ap.parse_args(argv)

    report = run()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    elif args.summary_md:
        print(summary_md(report))
    else:
        print(_text_report(report))
    return 0 if report["verdict"] == OK else 1


if __name__ == "__main__":
    sys.exit(main())
