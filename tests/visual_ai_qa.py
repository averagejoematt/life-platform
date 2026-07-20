#!/usr/bin/env python3
"""
visual_ai_qa.py — Claude (Bedrock) semantic vision QA over the visual_qa.py screenshots.

The companion to tests/visual_qa.py. The deterministic harness answers "did the
elements/APIs/interactions work"; this layer answers the question pixel-diff can't on a
data-driven site: **does each page actually LOOK right** — charts populated, no broken/garbled
renders, no clipped/overlapping text, no raw tokens (undefined/NaN/[object Object]) — while
NOT flagging legitimate sparse-data states ("N readings so far") that change daily.

It feeds each page's screenshots (full-page + chart crops) to Claude via the existing
`lambdas/bedrock_client.invoke()` (Haiku-primary, vision-capable, ~$0.001/image) and asks for
a structured JSON verdict. Verdicts merge back into the harness `results`:
  - severity "high"  → adds an issue + flips the page to FAIL
  - severity "med"/"low" → adds a warning (advisory)

Degrades cleanly: if Bedrock/`bedrock_client` is unavailable, AI-QA is skipped with a
warning — the deterministic checks still stand. Budget-aware (#1428): checks
budget_guard feature "visual_ai_qa" (internal QA band, pauses at tier >= 1, ADR-125)
UPFRONT and reports an explicit SKIPPED-BY-BUDGET status + CloudWatch metric — the
same honest-pause contract #1440 gave reader_truth_qa, not a per-page "AI-QA error"
from the bedrock_client Tier-3 hard-stop backstop.

Tiered by page (#1428): visual_qa.run_sweep can restrict WHICH captured pages get
handed to assess_results via its `ai_qa_max_tier` param — CI's deploy-time gate passes
tier 1 only (the 6 flagship doors); the weekly standalone schedule passes no filter
(full surface). assess_results itself has no tier logic — it assesses whatever list of
results it's given; the caller does the filtering.

Entry point: `assess_results(results)` — mutates the list in place, returns a status dict.
Called by visual_qa.run_sweep when `--ai-qa` is passed; also runnable standalone on a
report.json.

Second entry point (#1095): `assess_reader_truth(results)` — the PHASE-AWARE truth
pass over the harness's rendered-prose dumps (visual_qa.py --reader-truth). Where
the vision prompt above deliberately judges rendering only, this one judges whether
the words/numbers CAN BE TRUE at the current experiment day (temporal contradictions,
impossible numbers, duplicated narratives across surfaces, audience violations).
The rubric lives in lambdas/reader_truth_qa.py — shared with the nightly qa_smoke
hook (#1096) so the two nets can never drift apart. Verdicts merge exactly like
AI-vision: "high" → FAIL, "med"/"low" → warning. Budget-aware: internal QA pauses
first (budget_guard feature "reader_truth_qa", tier >= 1 per ADR-125) with an
honest printed/warned skip, never silent green.
"""

import base64
import json
import os
import re
import sys

# Haiku cross-region profile (vision-capable, cheap). bedrock_client maps the short name.
_VISION_MODEL = os.environ.get("VISUAL_AI_MODEL", "claude-haiku-4-5-20251001")
_MAX_IMAGES_PER_PAGE = int(os.environ.get("VISUAL_AI_MAX_IMAGES", "3"))

# budget_guard._FEATURE_CUTOFF key (#1428) — internal QA band, pauses at tier >= 1
# (ADR-125), same posture as reader_truth_qa/coherence_semantic below.
_BUDGET_FEATURE = "visual_ai_qa"

_PROMPT = """You are a meticulous UI QA reviewer looking at screenshot(s) of ONE page of a \
personal health dashboard ("{name}", path {path}). The site is data-driven — charts and \
numbers legitimately change every day — so judge whether the page RENDERED CORRECTLY, not \
whether the data matches any baseline.

FLAG as problems: a chart frame drawn but blank/empty; broken or garbled SVG/graphics; \
overlapping, clipped, or truncated text; missing or visually-collapsed sections; raw template \
tokens or the literal text "undefined" / "NaN" / "null" / "[object Object]" visible; obvious \
layout breakage or content overflowing its container; unreadable contrast.

DO NOT flag (these are CORRECT): honest sparse-data states such as "N readings so far", \
"awaiting data", or an empty-but-shaped section; normal data variation; intentionally minimal \
design; or a chart simply having few points.

SEPARATELY (advisory lens, #1466 — NOT a rendering issue, never put it in "issues"): note \
whether the page has drifted toward generic AI-template gloss — purple-blue gradients, \
glassmorphism, stock SaaS-template geometry (centered hero over a three-card grid), \
decoration with no data behind it, or "unlock your journey"-style SaaS copy. The site's own \
aesthetic (warm paper/ink, ember accents, mono numbers, editorial type) is CORRECT and is \
not gloss.

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"renders_ok": true|false, "charts_populated": "yes"|"no"|"n/a", \
"issues": [{{"type": "string", "severity": "low"|"med"|"high", "note": "string"}}], \
"template_gloss": {{"flagged": true|false, "note": "string"}}, \
"severity": "ok"|"low"|"med"|"high", "summary": "one sentence"}}
Set top-level "severity" to the maximum of the issue severities, or "ok" if there are none; \
"template_gloss" NEVER counts toward severity."""

_ICON = {"ok": "✅", "low": "🔵", "med": "🟡", "high": "🔴"}


def _import_bedrock():
    """Import the shared Bedrock client from lambdas/ (added to sys.path)."""
    try:
        lam = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas")
        if lam not in sys.path:
            sys.path.insert(0, lam)
        import bedrock_client  # noqa: E402

        return bedrock_client
    except Exception as e:  # pragma: no cover
        print(f"  ⚠ AI-QA unavailable — could not import bedrock_client: {e}")
        return None


def _image_block(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}


def _parse_verdict(text):
    """Pull the JSON verdict out of Claude's reply, tolerating stray prose/fences."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"severity": "ok", "renders_ok": True, "summary": "(no structured verdict)", "raw": text[:200]}
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"severity": "ok", "renders_ok": True, "summary": "(unparseable verdict)", "raw": text[:200]}
    # #1466: the template-gloss lens is advisory BY CONSTRUCTION — if the model
    # (mis)files it inside issues[], strip it before severity ever computes, so the
    # lens can never flip a page to FAIL (prompt rules alone can't guarantee
    # structure — memory: reference_prompt_structural_guarantees).
    _gloss_markers = ("template_gloss", "template-gloss", "ai-template", "slop")
    v["issues"] = [i for i in v.get("issues", []) if not any(m in str(i.get("type", "")).lower() for m in _gloss_markers)]
    if v.get("severity") not in ("ok", "low", "med", "high"):
        # derive from issue list if the model omitted/garbled the top-level field
        sevs = [i.get("severity") for i in v.get("issues", []) if i.get("severity") in ("low", "med", "high")]
        order = {"low": 1, "med": 2, "high": 3}
        v["severity"] = max(sevs, key=lambda s: order[s]) if sevs else "ok"
    else:
        # never let a stated severity exceed what the (gloss-stripped) issues support
        sevs = [i.get("severity") for i in v.get("issues", []) if i.get("severity") in ("low", "med", "high")]
        order = {"ok": 0, "low": 1, "med": 2, "high": 3}
        supported = max(sevs, key=lambda s: order[s]) if sevs else "ok"
        if order[v["severity"]] > order[supported]:
            v["severity"] = supported
    return v


def _assess_page(bedrock, name, path, shots):
    # Skip zero/near-empty captures (a zero-height element crop produces an
    # empty PNG that Bedrock rejects with a ValidationException — seen on the
    # labs chart crop 2026-06-12).
    shots = [s for s in shots if os.path.getsize(s["path"]) > 256]
    if not shots:
        return {"severity": "ok", "renders_ok": True, "summary": "(no usable screenshots — skipped)"}
    content = [_image_block(s["path"]) for s in shots]
    content.append({"type": "text", "text": _PROMPT.format(name=name, path=path)})
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": 700}
    resp = bedrock.invoke(body, model_name=_VISION_MODEL)
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return _parse_verdict(text)


def assess_results(results):
    """Run Claude-vision QA over each page's captured screenshots; mutate `results` in place.

    Adds `ai_verdict` per page. High-severity → issue + status FAIL; med/low → warning.
    No-ops gracefully (per page) on any Bedrock error.

    Budget-aware (#1428): checks budget_guard.allow("visual_ai_qa") UPFRONT — internal
    QA pauses at tier >= 1 (ADR-125), same band as reader_truth_qa/coherence_semantic.
    A paused run emits the QAPausedByBudget CloudWatch metric (shared with #1440's
    reader-truth hook — one alarm catches either) and returns an explicit
    {"status": "skipped_by_budget", "tier": N} so the caller can render SKIPPED-BY-BUDGET
    rather than have the pause surface only as a per-page "AI-QA error" from the
    bedrock_client Tier-3 hard-stop backstop (silent-by-accident before this fix).

    Returns a status dict `{"status": "ok"|"unavailable"|"skipped_by_budget", ...}` —
    mirroring assess_reader_truth's contract. `results` is still mutated in place exactly
    as before; no caller relied on the old (implicit None) return value.
    """
    bedrock = _import_bedrock()
    if not bedrock:
        for r in results:
            r.setdefault("warnings", []).append("AI-QA skipped — bedrock_client unavailable")
        return {"status": "unavailable", "detail": "bedrock_client unavailable"}

    try:
        import budget_guard  # lambdas/ is on sys.path after _import_bedrock()

        if not budget_guard.allow(_BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            try:
                import reader_truth_qa

                reader_truth_qa.emit_budget_pause_metric("visual_ai_qa", tier)
            except Exception:
                pass  # metric emission is best-effort; the pause itself must still be honest
            print(f"  ⏸ SKIPPED-BY-BUDGET — AI-vision QA paused at budget tier {tier} (internal QA pauses first, ADR-125)")
            for r in results:
                r.setdefault("warnings", []).append(f"SKIPPED-BY-BUDGET: AI-vision QA — budget tier {tier} (ADR-125)")
            return {"status": "skipped_by_budget", "tier": tier}
    except ImportError:
        pass  # fail-open, same posture as the guard itself

    for r in results:
        shots = [s for s in r.get("screenshots", []) if s.get("kind") in ("page", "chart")][:_MAX_IMAGES_PER_PAGE]
        if not shots:
            continue
        try:
            verdict = _assess_page(bedrock, r["page"], r["path"], shots)
        except Exception as e:
            msg = str(e)[:140]
            r.setdefault("warnings", []).append(f"AI-QA error: {msg}")
            print(f"  ⚠ {r['page']}: AI-QA error — {msg}")
            continue

        r["ai_verdict"] = verdict
        sev = verdict.get("severity", "ok")
        summary = (verdict.get("summary") or "").strip()
        print(f"  {_ICON.get(sev, '?')} AI · {r['page']}: {summary[:96]}")

        if sev == "high":
            r.setdefault("issues", []).append(f"AI-vision (high): {summary[:140]}")
            r["status"] = "FAIL"
        elif sev in ("med", "low"):
            r.setdefault("warnings", []).append(f"AI-vision ({sev}): {summary[:140]}")

        gloss = verdict.get("template_gloss") or {}
        if gloss.get("flagged"):
            note = (gloss.get("note") or "").strip()[:140]
            r.setdefault("warnings", []).append(f"AI-vision (advisory slop-lens, #1466 — never gating): {note}")
            print(f"  🎭 slop-lens · {r['page']}: {note[:96]}")

    return {"status": "ok"}


def _truth_line(f):
    return f"Reader-truth ({f['severity']}) [{f['category']}]: {f['note'][:140]}"


def assess_reader_truth(results):
    """Phase-aware reader-truth QA (#1095) over the harness's prose captures; mutates `results`.

    Reads each page's rendered-innerText dump (kind == "prose", written by
    visual_qa.capture_page(capture_prose=True)), batches 4-6 surfaces per Bedrock
    call (so duplicated-narrative is checkable), and merges findings like the
    vision pass: high → issue + FAIL, med/low → warning. Fail-soft on every
    dependency (Bedrock, budget tier, missing prose) with an explicit skip.

    Returns a status dict `{"status": ..., ...}` — NOT the mutated `results` (no
    caller used the old return value; `results` is still mutated in place exactly
    as before). #1440: `status` is one of "ok" | "unavailable" | "skipped_by_budget" |
    "no_surfaces" so the caller (visual_qa.run_sweep) can report a budget pause as an
    explicit SKIPPED-BY-BUDGET state — never as an indistinguishable pass.
    """
    bedrock = _import_bedrock()
    if not bedrock:
        for r in results:
            r.setdefault("warnings", []).append("Reader-truth QA skipped — bedrock_client unavailable")
        return {"status": "unavailable", "detail": "bedrock_client unavailable"}
    try:
        import reader_truth_qa  # lambdas/ is on sys.path after _import_bedrock()
    except Exception as e:  # pragma: no cover
        print(f"  ⚠ Reader-truth QA unavailable — could not import reader_truth_qa: {e}")
        for r in results:
            r.setdefault("warnings", []).append(f"Reader-truth QA skipped — reader_truth_qa unavailable: {str(e)[:100]}")
        return {"status": "unavailable", "detail": f"reader_truth_qa unavailable: {str(e)[:100]}"}

    # Budget gate — internal QA pauses FIRST (ADR-125). Honest skip, never silent.
    # #1440: emit the QAPausedByBudget metric + tag every warning SKIPPED-BY-BUDGET
    # (not just "skipped") so a paused run can never be mistaken for a clean one.
    try:
        import budget_guard

        if not budget_guard.allow(reader_truth_qa.BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            reader_truth_qa.emit_budget_pause_metric("visual_ai_qa", tier)
            print(f"  ⏸ SKIPPED-BY-BUDGET — Reader-truth QA paused at budget tier {tier} (internal QA pauses first, ADR-125)")
            for r in results:
                r.setdefault("warnings", []).append(f"SKIPPED-BY-BUDGET: Reader-truth QA — budget tier {tier} (ADR-125)")
            return {"status": "skipped_by_budget", "tier": tier}
    except ImportError:
        pass  # fail-open, same posture as the guard itself

    surfaces, by_path = [], {}
    for r in results:
        shot = next((s for s in r.get("screenshots", []) if s.get("kind") == "prose"), None)
        if not shot:
            continue
        try:
            with open(shot["path"]) as f:
                prose = f.read()
        except Exception:
            continue
        if not prose.strip():
            continue
        surfaces.append({"name": r["page"], "path": r["path"], "prose": prose})
        by_path[r["path"]] = r
    if not surfaces:
        print("  ⚠ Reader-truth QA: no prose captures found — run visual_qa.py with --reader-truth")
        return {"status": "no_surfaces"}

    findings, errors = reader_truth_qa.assess_prose(surfaces, bedrock.invoke)
    for err in errors:
        print(f"  ⚠ Reader-truth batch error (fail-soft): {err}")

    for f in findings:
        r = by_path.get(f["page"])
        if r is None:
            # model mangled the path — keep the finding visible on the first surface
            r = by_path[surfaces[0]["path"]]
            f = dict(f, note=f"(claimed page {f['page']!r}) {f['note']}"[:300])
        r.setdefault("truth_findings", []).append(f)
        line = _truth_line(f)
        print(f"  {_ICON.get(f['severity'], '?')} truth · {f['page']}: [{f['category']}] {f['note'][:96]}")
        if f["severity"] == "high":
            r.setdefault("issues", []).append(line)
            r["status"] = "FAIL"
        else:
            r.setdefault("warnings", []).append(line)

    if not findings:
        phase = reader_truth_qa.phase_context()
        day = f"{phase['days_until_start']}d pre-start" if phase["pre_start"] else f"Day {phase['day_n']}"
        print(f"  ✅ Reader-truth: {len(surfaces)} surfaces clean at {day}")
    return {"status": "ok", "findings": len(findings)}


if __name__ == "__main__":
    # Standalone: re-assess an existing qa-screenshots/report.json (paths must still exist).
    report = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "qa-screenshots", "report.json")
    with open(report) as f:
        data = json.load(f)
    print(f"AI-vision QA over {report}\n{'=' * 56}")
    assess_results(data["results"])
    data["failed"] = sum(1 for r in data["results"] if r["status"] == "FAIL")
    data["passed"] = sum(1 for r in data["results"] if r["status"] == "PASS")
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n{data['passed']} passed, {data['failed']} failed after AI-vision pass.")
    sys.exit(0 if data["failed"] == 0 else 1)
