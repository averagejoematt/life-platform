"""golden_surface_eval.py — the falsifiable-honesty harness for EVERY AI surface (#812, R22 FABLE-02, epic #720).

#742 (`tests/golden_brief_eval.py`) made "0 flags" falsifiable for ONE surface —
coach briefs. The runtime ADR-104 grounding gate also protects board_ask, the
Wednesday chronicle, coach memoirs, the State-of-Matthew brief, and field notes —
but none of those had frozen goldens + seeded-fault canaries, so their "0 flags"
was still unfalsifiable: a validator that catches nothing and a broken validator
look identical. This harness generalizes the pattern:

  1. GOLDEN (no false positives): known-good outputs per surface draw ZERO
     findings from that surface's gate. If a prompt/model/gate change starts
     false-positiving on real published voice, the run goes red before it ships.

  2. CANARIES (mutation testing): fault-injected outputs per surface — a
     fabricated number, a hard vital contradiction, a banned causal claim, a
     dodged miss — are CAUGHT by the expected check. An uncaught canary fails
     the whole run: the flags demonstrably fire on demand, on every surface.

Fidelity invariant: fixtures are replayed through each surface's ACTUAL gate
path — the same functions the live lambdas call (`board_grounding_findings`,
`installment_grounding_findings`, `gate_check`, `narration_gate`,
`note_contradiction_hits`) — never a re-implementation. A self-test asserts each
adapter is wired to the real module (the silently-disabled-gate failure mode).

Fixture provenance (honesty rule): goldens are derived from real recorded
outputs where they exist (each carries a `provenance` field naming the DDB
record); canaries are ALWAYS synthetic seeded faults and say so. Harvested
fixtures (from `scripts/harvest_eval_fixtures.py`, consuming the #744 retention
stream) use `mode: "generic"` — they carry the recorded numeric allow-list and
replay through `grounded_generation.grounding_findings` (which is exactly what
every surface path reduces to) plus the surface's extra deterministic checks.

Design invariant (ADR-105, mirrors #742): DETERMINISTIC checks alone drive the
pass/fail verdict — hermetic, free, no AWS, no Bedrock. The advisory voice judge
stays in golden_brief_eval.py (coach-brief-specific).

Run:
    python3 tests/golden_surface_eval.py            # deterministic verdict, exit non-zero on fail
    python3 tests/golden_surface_eval.py --json     # machine-readable report

`tests/test_golden_surface_eval.py` runs the verdict in the unit suite
(deploy-critical lane); the weekly golden-brief-eval workflow runs it on a schedule.
"""

import argparse
import json
import os
import sys

# ── path + env setup: work both under pytest (conftest sets paths) and standalone ──
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("", "compute", "web", "emails", "intelligence"):
    _p = os.path.join(_REPO, "lambdas", _sub) if _sub else os.path.join(_REPO, "lambdas")
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Hermetic: the surface modules build boto3 clients at import; fake creds keep
# that offline (no call is ever made on the deterministic path).
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "eval@example.com")
os.environ.setdefault("EMAIL_SENDER", "eval@example.com")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

import grounded_generation as gg  # noqa: E402

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "golden_surfaces")

OK = "OK"
FAIL = "FAIL"

SURFACES = ("board_ask", "chronicle", "memoir", "state_of_matthew", "field_notes")

# finding type (grounded_generation / adapters) → check label (fixture vocabulary)
CHECK_BY_TYPE = {
    "contradiction": "grounding_contradiction",
    "fabricated_number": "evidence_ceiling",
    "causal_language": "causal_language",
}

# The deterministic check dimensions each surface's gate actually enforces —
# canaries per surface must span these (self-test), else a whole check could rot.
SURFACE_CHECKS = {
    "board_ask": {"evidence_ceiling"},
    "chronicle": {"evidence_ceiling"},
    "memoir": {"evidence_ceiling", "miss_dodged"},
    "state_of_matthew": {"evidence_ceiling", "causal_language"},
    "field_notes": {"grounding_contradiction"},
}


def _labeled(finding):
    return {"check": CHECK_BY_TYPE.get(finding.get("type"), finding.get("type")), **finding}


# ── per-surface adapters: each calls the surface's ACTUAL gate function ───────
def _eval_board_ask(fx, output):
    from web import site_api_ai_lambda as ai

    findings = ai.board_grounding_findings(
        fx["inputs"]["system_context"], fx["inputs"]["question"], output, prior_answers=fx["inputs"].get("prior_answers", "")
    )
    return [_labeled(f) for f in findings]


def _eval_chronicle(fx, output):
    import wednesday_chronicle_lambda as chron

    findings = chron.installment_grounding_findings(fx["inputs"]["elena_prompt"], fx["inputs"]["user_message"], output)
    return [_labeled(f) for f in findings]


def _eval_memoir(fx, output):
    from compute import coach_memoir_lambda as memoir

    ok, reasons = memoir.gate_check(output, fx["inputs"]["facts"])
    if ok:
        return []
    out = []
    for r in reasons:
        if r == "empty":
            out.append({"check": "empty_output", "detail": r})
        elif r.startswith("fabricated numbers"):
            out.append({"check": "evidence_ceiling", "detail": r})
        else:  # memoir_gate.cites_a_miss verdict — the humblebrag-reel class
            out.append({"check": "miss_dodged", "detail": r})
    return out


def _eval_state_of_matthew(fx, output):
    from compute import state_of_matthew_lambda as som

    findings, causal_hits = som.narration_gate(fx["inputs"]["state"], output)
    out = [_labeled(f) for f in findings]
    out.extend({"check": "causal_language", "detail": f"banned causal connective {w!r}"} for w in causal_hits)
    return out


def _eval_field_notes(fx, output):
    # output is the note's analysis dict ({ai_present, ai_cautionary, ai_affirming})
    import field_notes_lambda as fnl

    hits = fnl.note_contradiction_hits(output, fx["inputs"]["metrics_record"])
    return [{"check": "grounding_contradiction", **h} for h in hits]


ADAPTERS = {
    "board_ask": _eval_board_ask,
    "chronicle": _eval_chronicle,
    "memoir": _eval_memoir,
    "state_of_matthew": _eval_state_of_matthew,
    "field_notes": _eval_field_notes,
}


def _eval_generic(surface, fx, output):
    """Replay for harvested fixtures (mode 'generic'): the recorded allow-list +
    facts through grounded_generation — exactly what every surface's number/
    contradiction path reduces to — plus the surface's extra deterministic checks
    (still the real functions, imported from the surface module)."""
    allowed = set(float(x) for x in fx["inputs"].get("allowed") or [])
    facts = fx["inputs"].get("facts")
    text = output if isinstance(output, str) else json.dumps(output)
    findings = [_labeled(f) for f in gg.grounding_findings(text, facts=facts, allowed=allowed)]
    if surface == "state_of_matthew":
        from compute import state_of_matthew_lambda as som

        findings.extend({"check": "causal_language", "detail": f"banned causal connective {w!r}"} for w in som._causal_language(text))
    return findings


def evaluate_fixture(surface, fx, output):
    """Run one fixture's output through its surface gate. Returns finding list."""
    if fx.get("mode") == "generic":
        return _eval_generic(surface, fx, output)
    return ADAPTERS[surface](fx, output)


# ── fixture loading ──────────────────────────────────────────────────────────
def load_fixtures(surface):
    """(golden: list, canaries: list) for one surface."""
    sdir = os.path.join(FIXTURE_ROOT, surface)
    with open(os.path.join(sdir, "golden.json"), encoding="utf-8") as f:
        golden = json.load(f)
    with open(os.path.join(sdir, "canaries.json"), encoding="utf-8") as f:
        canaries = json.load(f)
    return golden, canaries


# ── the run ──────────────────────────────────────────────────────────────────
def run(surfaces=SURFACES):
    """Execute the deterministic verdict across all surfaces.

    verdict is FAIL iff any golden output drew a finding or any canary was NOT
    caught by its expected checks."""
    per_surface = {}
    golden_defects, canary_misses = [], []
    total_golden = total_canaries = 0

    for surface in surfaces:
        golden, canaries = load_fixtures(surface)
        total_golden += len(golden)
        total_canaries += len(canaries)

        s_defects = []
        for fx in golden:
            findings = evaluate_fixture(surface, fx, fx["reference_output"])
            if findings:
                s_defects.append({"surface": surface, "id": fx["id"], "findings": findings})
        golden_defects.extend(s_defects)

        s_results = []
        for cn in canaries:
            findings = evaluate_fixture(surface, cn, cn["mutated_output"])
            caught_checks = {f["check"] for f in findings}
            expected = set(cn.get("expect_checks") or [])
            caught = bool(expected) and expected.issubset(caught_checks)
            s_results.append(
                {
                    "surface": surface,
                    "id": cn["id"],
                    "mutation": cn.get("mutation"),
                    "expect_checks": sorted(expected),
                    "caught_checks": sorted(caught_checks),
                    "caught": caught,
                }
            )
        canary_misses.extend(c for c in s_results if not c["caught"])

        per_surface[surface] = {
            "golden_count": len(golden),
            "canary_count": len(canaries),
            "golden_defects": len(s_defects),
            "canary_misses": sum(1 for c in s_results if not c["caught"]),
            "canary_results": s_results,
        }

    verdict = OK if (not golden_defects and not canary_misses) else FAIL
    return {
        "verdict": verdict,
        "surfaces": list(surfaces),
        "golden_count": total_golden,
        "canary_count": total_canaries,
        "per_surface": per_surface,
        "golden_defects": golden_defects,
        "canary_misses": canary_misses,
    }


# ── report ───────────────────────────────────────────────────────────────────
def ops_line(report):
    v = report["verdict"]
    mark = "✓" if v == OK else "✗"
    return (
        f"{mark} Golden-surface evals: {v} — {report['golden_count']} golden across "
        f"{len(report['surfaces'])} surfaces (0 false flags), "
        f"{report['canary_count'] - len(report['canary_misses'])}/{report['canary_count']} canaries caught"
    )


def _text_report(report):
    lines = [ops_line(report), ""]
    for s, info in report["per_surface"].items():
        mark = "✓" if (info["golden_defects"] == 0 and info["canary_misses"] == 0) else "✗"
        lines.append(f"  {mark} {s}: {info['golden_count']} golden, {info['canary_count']}/{info['canary_count']} canary target")
    if report["golden_defects"]:
        lines.append(f"\n{len(report['golden_defects'])} GOLDEN false-positive(s) — the gate flagged known-good output:")
        for d in report["golden_defects"]:
            for f in d["findings"]:
                lines.append(f"   ✗ {d['surface']}/{d['id']}: [{f['check']}] {f.get('detail')}")
    if report["canary_misses"]:
        lines.append(f"\n{len(report['canary_misses'])} CANARY miss(es) — an induced fault slipped the gate:")
        for c in report["canary_misses"]:
            lines.append(f"   ✗ {c['surface']}/{c['id']}: expected {c['expect_checks']}, caught {c['caught_checks']}")
    if report["verdict"] == OK:
        lines.append("\nAll golden outputs grounded, all canaries caught, on every surface.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Golden-surface eval harness + seeded-fault canaries (#812)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)

    report = run()
    print(json.dumps(report, indent=2, default=str) if args.json else _text_report(report))
    return 0 if report["verdict"] == OK else 1


if __name__ == "__main__":
    sys.exit(main())
