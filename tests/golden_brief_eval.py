"""golden_brief_eval.py — the falsifiable-honesty eval harness (#742, R21 epic #720/E6).

The platform sells "N checks, 0 flags" on every AI narrative surface. Until now
nothing PROVED the flags could ever fire — "0 flags" was unfalsifiable. This
harness makes it falsifiable by replaying a frozen golden set of coach generation
briefs through the SAME deterministic honesty gate the live pipeline uses
(`grounded_generation.grounding_findings` + `grounding_guard`), and asserting two
things a real gate must satisfy:

  1. GOLDEN (no false positives): ~30 known-good outputs across the 8 coaches draw
     ZERO deterministic findings — the gate does not flag honest, grounded voice.
     If a prompt/model/gate change starts false-positiving on real voice, the run
     goes red before it can ship.

  2. CANARIES (mutation testing): five fault-injected outputs — each an induced
     fabricated number, a hard vital contradiction, or a forbidden anti-pattern —
     are CAUGHT. A canary the gate fails to catch fails the whole run. This is what
     turns "0 flags" from a claim into a tested property: we can demonstrate the
     flags firing on demand.

Plus a deterministic cross-coach DISTINCTIVENESS check (content-word similarity)
so the golden voices can't silently converge into one generic voice.

Design invariant (mirrors `ai_quality_canary_lambda`, ADR-076): the DETERMINISTIC
checks alone drive the pass/fail verdict. The optional Haiku voice-rubric judge
(`--judge`) is ADVISORY — it trends a weekly voice number and never gates. The
harness is hermetic and free by default: no AWS, no network, no Bedrock spend
unless `--judge`/`--emit` is passed.

Run:
    python3 tests/golden_brief_eval.py            # deterministic verdict, exit non-zero on fail
    python3 tests/golden_brief_eval.py --json     # machine-readable report
    python3 tests/golden_brief_eval.py --judge    # + advisory Haiku voice rubric (Bedrock)
    python3 tests/golden_brief_eval.py --emit      # + CloudWatch metrics (LifePlatform/GoldenBrief)

`tests/test_golden_brief_eval.py` runs the deterministic verdict in the unit suite;
CI additionally runs it on any change to the gate/prompt surface (see the workflow).
"""

import argparse
import json
import os
import re
import sys

# ── path setup: work both under pytest (conftest sets paths) and standalone ──
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Keep any incidental boto3 client construction hermetic (only reached under --judge/--emit).
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import grounded_generation as gg  # noqa: E402

# The tight vital-contradiction detector — import it directly so a broken import
# is a loud harness failure (a self-test asserts it is wired), never a silently
# skipped canary.
try:
    import grounding_guard  # noqa: E402
except ImportError:  # pragma: no cover
    grounding_guard = None

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "golden_briefs")
COACHES_CONFIG_DIR = os.path.join(_REPO, "config", "coaches")

ALL_COACH_IDS = (
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
)

# ── verdict levels ───────────────────────────────────────────────────────────
OK = "OK"
FAIL = "FAIL"

# Cross-coach distinctiveness: two DIFFERENT coaches' outputs whose content-word
# Jaccard exceeds this are "too similar" — a voice-convergence regression. Set
# loose enough that domain overlap (both mention "recovery") never false-fires;
# the authored golden voices sit well under it.
DISTINCTIVENESS_MAX_JACCARD = 0.55

# Universal fourth-wall / vendor guardrail — a coach naming the underlying vendor
# or model is a hard anti-pattern on every surface (regression guard for #356),
# independent of any per-coach blacklist. Bare "AI" is intentionally allowed.
_VENDOR_PATTERNS = [
    re.compile(r"\banthropic\b", re.I),
    re.compile(r"\bopen\s?ai\b", re.I),
    re.compile(r"\bchat\s?gpt\b", re.I),
    re.compile(r"\bgpt-?[0-9]\b", re.I),
    re.compile(r"\bclaude\b", re.I),
    re.compile(r"\bhaiku\b", re.I),
    re.compile(r"\bsonnet\b", re.I),
    re.compile(r"\bbedrock\b", re.I),
    re.compile(r"\b(?:large\s+)?language\s+model\b", re.I),
]

_STOPWORDS = frozenset(
    """
    a an the and or but if then so as of to in on at by for with from into over under
    is are was were be been being do does did has have had will would can could should
    this that these those it its your you his her their our we he she they i me my
    not no yes what which who whom when where why how than about up down out off more
    most less least very just also too still yet even much many few some any all each
    """.split()
)


# ── fixture loading ──────────────────────────────────────────────────────────
def load_fixtures():
    """Load the frozen golden set and the fault-injected canaries.

    Returns (golden: list[dict], canaries: list[dict]).
    """
    with open(os.path.join(FIXTURE_DIR, "golden.json"), encoding="utf-8") as f:
        golden = json.load(f)
    with open(os.path.join(FIXTURE_DIR, "canaries.json"), encoding="utf-8") as f:
        canaries = json.load(f)
    return golden, canaries


_voice_spec_cache = {}


def voice_spec(coach_id):
    """Load a coach's voice spec from config/coaches/. Fail-soft to {} — the
    per-coach phrase blacklist is one input to the anti-pattern check, never the
    only one (the universal vendor guardrail always applies)."""
    if coach_id in _voice_spec_cache:
        return _voice_spec_cache[coach_id]
    spec = {}
    path = os.path.join(COACHES_CONFIG_DIR, f"{coach_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError):
        spec = {}
    _voice_spec_cache[coach_id] = spec
    return spec


# ── deterministic checks ─────────────────────────────────────────────────────
def allowed_for(fixture):
    """The numeric allow-list the gate would build for this fixture — every number
    in the authoritative facts + the generation brief + the rendered facts block.
    Mirrors ai_calls' live `allowed_numbers(system_prompt, user_message)`, whose
    inputs are derived from exactly those sources."""
    facts = fixture.get("authoritative_facts") or {}
    brief = fixture.get("generation_brief") or {}
    return gg.allowed_numbers(facts, brief, gg.authoritative_facts_block(facts))


def anti_pattern_hits(text, coach_id):
    """Deterministic anti-pattern findings: the coach's own phrase blacklist
    (substring, case-insensitive) plus the universal vendor/fourth-wall guardrail.
    Structural-blacklist items are prose descriptions, not string-detectable, so
    they are the LLM judge's domain, not this deterministic gate's."""
    hits = []
    low = (text or "").lower()
    blacklist = ((voice_spec(coach_id).get("anti_pattern_detection") or {}).get("phrase_blacklist")) or []
    for phrase in blacklist:
        if phrase.lower() in low:
            hits.append({"type": "anti_pattern", "phrase": phrase, "detail": f'forbidden phrase "{phrase}" present'})
    for pat in _VENDOR_PATTERNS:
        if pat.search(text or ""):
            hits.append({"type": "anti_pattern", "phrase": pat.pattern, "detail": f"fourth-wall/vendor leak: /{pat.pattern}/"})
    return hits


def evaluate_output(coach_id, output_text, facts, allowed):
    """Run every deterministic honesty check on one output. Returns a flat list of
    finding dicts, each with a `check` label and a `type`. Empty list = clean.

    - `grounding_contradiction`: a stated RHR/recovery/HRV number hard-contradicts
      the canonical facts (grounding_guard, tight per-metric tolerances).
    - `evidence_ceiling`: a number in the narrative appears nowhere in the input —
      the invented trend/range/vital class (grounded_generation number gate).
    - `anti_pattern`: a forbidden phrase or vendor/fourth-wall leak.
    """
    findings = []
    for f in gg.grounding_findings(output_text, facts=facts, allowed=allowed):
        if f.get("type") == "contradiction":
            findings.append({"check": "grounding_contradiction", **f})
        else:  # fabricated_number
            findings.append({"check": "evidence_ceiling", **f})
    for f in anti_pattern_hits(output_text, coach_id):
        findings.append({"check": "anti_pattern", **f})
    return findings


def _content_words(text):
    toks = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {t for t in toks if t not in _STOPWORDS}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def distinctiveness_violations(golden, threshold=DISTINCTIVENESS_MAX_JACCARD):
    """Pairs of DIFFERENT-coach golden outputs whose content-word similarity is
    above threshold — a voice-convergence signal. Same-coach pairs are expected to
    be similar and are excluded."""
    words = [(fx["id"], fx["coach_id"], _content_words(fx["reference_output"])) for fx in golden]
    out = []
    for i in range(len(words)):
        for j in range(i + 1, len(words)):
            id_a, coach_a, wa = words[i]
            id_b, coach_b, wb = words[j]
            if coach_a == coach_b:
                continue
            sim = _jaccard(wa, wb)
            if sim > threshold:
                out.append({"a": id_a, "b": id_b, "coach_a": coach_a, "coach_b": coach_b, "jaccard": round(sim, 3)})
    return out


# ── the run ──────────────────────────────────────────────────────────────────
def run(judge=False):
    """Execute the deterministic verdict (and optionally the advisory judge).

    Returns a report dict. `verdict` is FAIL iff any golden output drew a finding,
    any canary was NOT caught, or any cross-coach distinctiveness pair tripped —
    the advisory judge NEVER affects it.
    """
    golden, canaries = load_fixtures()

    # (1) Golden: expect ZERO findings on every known-good output.
    golden_defects = []
    for fx in golden:
        facts = fx.get("authoritative_facts") or {}
        findings = evaluate_output(fx["coach_id"], fx["reference_output"], facts, allowed_for(fx))
        if findings:
            golden_defects.append({"id": fx["id"], "coach_id": fx["coach_id"], "findings": findings})

    # (2) Canaries: expect each induced fault to be CAUGHT by the expected check.
    canary_results = []
    for cn in canaries:
        facts = cn.get("authoritative_facts") or {}
        findings = evaluate_output(cn["coach_id"], cn["mutated_output"], facts, allowed_for(cn))
        caught_checks = {f["check"] for f in findings}
        expected = set(cn.get("expect_checks") or [])
        caught = expected.issubset(caught_checks)
        canary_results.append(
            {
                "id": cn["id"],
                "coach_id": cn["coach_id"],
                "mutation": cn.get("mutation"),
                "expect_checks": sorted(expected),
                "caught_checks": sorted(caught_checks),
                "caught": caught,
            }
        )
    canary_misses = [c for c in canary_results if not c["caught"]]

    # (3) Distinctiveness.
    distinct = distinctiveness_violations(golden)

    verdict = OK if (not golden_defects and not canary_misses and not distinct) else FAIL

    report = {
        "verdict": verdict,
        "golden_count": len(golden),
        "canary_count": len(canaries),
        "coaches_covered": sorted({fx["coach_id"] for fx in golden}),
        "golden_defects": golden_defects,
        "canary_results": canary_results,
        "canary_misses": canary_misses,
        "distinctiveness_violations": distinct,
    }

    if judge:
        report["judge"] = _run_voice_judge(golden)  # advisory only

    return report


# ── advisory Haiku voice rubric (opt-in, never gates) ────────────────────────
_VOICE_RUBRIC = (
    "You are a voice-fidelity auditor for a roster of AI health coaches, each with a "
    "distinct persona. Given one coach's output, rate 0-100 how strongly it reads as a "
    "DISTINCT, consistent professional voice (not generic AI filler), and note any "
    "generic/hedging tells. Respond ONLY as JSON: "
    '{"voice_score": 0-100, "generic_tells": ["..."]}'
)


def _run_voice_judge(golden, sample_per_coach=1):
    """Advisory: one Haiku pass scoring per-coach voice distinctiveness, trended as
    a single number. Never affects the verdict. Fail-soft — any Bedrock error
    returns a null score rather than failing the harness."""
    try:
        import bedrock_client
    except Exception as e:  # pragma: no cover
        return {"available": False, "reason": f"bedrock_client import failed: {e}"}

    # one representative output per coach (first seen), to bound cost
    seen, samples = set(), []
    for fx in golden:
        if fx["coach_id"] in seen:
            continue
        seen.add(fx["coach_id"])
        samples.append(fx)

    scores = []
    per_coach = {}
    for fx in samples:
        try:
            body = {
                "system": _VOICE_RUBRIC,
                "messages": [{"role": "user", "content": f"Coach: {fx['coach_id']}\n\nOutput:\n{fx['reference_output']}"}],
                "max_tokens": 200,
                "temperature": 0.0,
            }
            resp = bedrock_client.invoke(body, model_name="haiku")
            txt = resp.get("content", [{}])[0].get("text", "") if isinstance(resp, dict) else str(resp)
            m = re.search(r"\{.*\}", txt, re.S)
            parsed = json.loads(m.group(0)) if m else {}
            score = parsed.get("voice_score")
            if isinstance(score, (int, float)):
                scores.append(float(score))
                per_coach[fx["coach_id"]] = {"voice_score": score, "generic_tells": parsed.get("generic_tells", [])}
        except Exception as e:  # pragma: no cover — advisory, never fatal
            per_coach[fx["coach_id"]] = {"error": str(e)}

    mean = round(sum(scores) / len(scores), 1) if scores else None
    return {"available": True, "mean_voice_score": mean, "n": len(scores), "per_coach": per_coach}


# ── metrics + ops line ───────────────────────────────────────────────────────
CW_NAMESPACE = "LifePlatform/GoldenBrief"


def emit_metrics(report):
    """Emit the falsifiability gauges to CloudWatch. Fail-open — a metric error
    never changes the verdict. Mirrors ai_quality_canary_lambda._emit."""
    try:
        import boto3

        cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))
        data = [
            {"MetricName": "CanaryMissed", "Value": float(len(report["canary_misses"])), "Unit": "Count"},
            {"MetricName": "GoldenFalsePositive", "Value": float(len(report["golden_defects"])), "Unit": "Count"},
            {"MetricName": "DistinctivenessViolation", "Value": float(len(report["distinctiveness_violations"])), "Unit": "Count"},
            {"MetricName": "OverallFail", "Value": 1.0 if report["verdict"] == FAIL else 0.0, "Unit": "Count"},
        ]
        judge = report.get("judge") or {}
        if judge.get("mean_voice_score") is not None:
            data.append({"MetricName": "MeanVoiceScore", "Value": float(judge["mean_voice_score"]), "Unit": "None"})
        for i in range(0, len(data), 20):
            cw.put_metric_data(Namespace=CW_NAMESPACE, MetricData=data[i : i + 20])
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[golden-brief] metric emit failed (non-fatal): {e}", file=sys.stderr)
        return False


def ops_line(report):
    """One line for the ops email / digest."""
    v = report["verdict"]
    mark = "✓" if v == OK else "✗"
    judge = report.get("judge") or {}
    voice = f", voice={judge['mean_voice_score']}" if judge.get("mean_voice_score") is not None else ""
    return (
        f"{mark} Golden-brief evals: {v} — {report['golden_count']} golden across "
        f"{len(report['coaches_covered'])}/8 coaches (0 false flags), "
        f"{report['canary_count'] - len(report['canary_misses'])}/{report['canary_count']} canaries caught{voice}"
    )


def _text_report(report):
    lines = [ops_line(report), ""]
    if report["golden_defects"]:
        lines.append(f"{len(report['golden_defects'])} GOLDEN false-positive(s) — the gate flagged known-good voice:")
        for d in report["golden_defects"]:
            for f in d["findings"]:
                lines.append(f"   ✗ {d['id']} ({d['coach_id']}): [{f['check']}] {f.get('detail')}")
    if report["canary_misses"]:
        lines.append(f"\n{len(report['canary_misses'])} CANARY miss(es) — an induced fault slipped the gate:")
        for c in report["canary_misses"]:
            lines.append(f"   ✗ {c['id']} ({c['coach_id']}): expected {c['expect_checks']}, caught {c['caught_checks']}")
    if report["distinctiveness_violations"]:
        lines.append(f"\n{len(report['distinctiveness_violations'])} distinctiveness violation(s):")
        for d in report["distinctiveness_violations"]:
            lines.append(f"   ~ {d['a']} vs {d['b']} ({d['coach_a']}/{d['coach_b']}): jaccard {d['jaccard']}")
    if report["verdict"] == OK:
        lines.append("\nAll golden outputs grounded, all canaries caught, voices distinct.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Golden-brief eval harness + seeded-fault canaries (#742)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--judge", action="store_true", help="+ advisory Haiku voice rubric (Bedrock spend)")
    ap.add_argument("--emit", action="store_true", help="+ CloudWatch metrics (LifePlatform/GoldenBrief)")
    args = ap.parse_args(argv)

    report = run(judge=args.judge)
    if args.emit:
        report["metrics_emitted"] = emit_metrics(report)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_text_report(report))

    return 0 if report["verdict"] == OK else 1


if __name__ == "__main__":
    sys.exit(main())
