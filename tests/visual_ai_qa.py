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
budget_guard feature "visual_ai_qa" (OPERATOR-TRUTH band — pauses at tier 3 only since
the ADR-125 2026-08-03 amendment, #1927; it was tier >= 1 and therefore dark 26 of 30
days) UPFRONT and reports an explicit SKIPPED-BY-BUDGET status + CloudWatch metric — the
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
AI-vision: "high" → FAIL, "med"/"low" → warning. Budget-aware: the gate pauses at
tier 3 only (budget_guard feature "reader_truth_qa" — operator-truth band, ADR-125 as
amended by #1927) with an honest printed/warned skip, never silent green.
"""

import base64
import io
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import truth_baseline_audit  # the reader-truth debt ledger (#2956) — same dir

# Haiku cross-region profile (vision-capable, cheap). bedrock_client maps the short name.
_VISION_MODEL = os.environ.get("VISUAL_AI_MODEL", "claude-haiku-4-5-20251001")
_MAX_IMAGES_PER_PAGE = int(os.environ.get("VISUAL_AI_MAX_IMAGES", "3"))

# Bedrock/Anthropic vision hard limits (#2973): an image over 8000px in EITHER
# dimension — or over ~5MB decoded — is rejected outright with a
# ValidationException on messages.*.content.*.image.source. Tall full-page
# captures cross the dimension cap routinely: in run 32580634729 home.png was
# 1440x11827 and protocols.png 1440x9200, and both pages went silently
# unevaluated. _prepare_image downscales to fit BEFORE the call; the model's
# own input pipeline resizes far below 8000px anyway, so the downscale loses
# nothing the oracle would have seen.
_BEDROCK_MAX_DIM = 8000
_BEDROCK_MAX_BYTES = 5 * 1024 * 1024

# budget_guard._FEATURE_CUTOFF key (#1428) — operator-truth band, pauses at tier 3
# only (ADR-125 as amended by #1927), same posture as reader_truth_qa below.
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
design; or a chart simply having few points. An "as of <date> — refresh paused (budget guard)" \
kicker under a coach's read is CORRECT and REQUIRED honesty (#802/#1971): when the budget \
guard holds AI regeneration, a held board read must carry that paused note — it is a \
deliberate disclosure, never stale-content breakage.

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

# #2383 — per-page semantic rules, appended verbatim to the generic prompt for
# the matching harness path. Written with a "med" ceiling so a model misread can
# warn but never single-handedly block the pipeline (prompt rules alone can't
# guarantee structure — reference_prompt_structural_guarantees; _parse_verdict
# still caps stated severity at what the issues support).
_PAGE_RULES = {
    "/coaching/": (
        "PAGE-SPECIFIC RULE (honest dating, ADR-104): every AI-authored band on this page — each "
        'coach\'s read card, the "where the board disagrees" tensions band (including "the '
        "integrator's call\" inside it), and any narrative attributed to a coach — must carry a "
        'visible as-of date: an "as of <date>" kicker or an equivalent dated stamp (e.g. "held '
        'since <date>", a dated week label). If a band presents AI-authored argument or narrative '
        'prose with NO visible date, add an issue of type "undated_ai_band" at severity "med", '
        'naming the band. Honest empty states ("No live disagreements right now…") need no date.'
    ),
}


def _import_bedrock():
    """Import the shared Bedrock client from lambdas/ (added to sys.path)."""
    try:
        lam = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas")
        if lam not in sys.path:
            sys.path.insert(0, lam)
        from ai import bedrock_client  # noqa: E402

        return bedrock_client
    except Exception as e:  # pragma: no cover
        print(f"  ⚠ AI-QA unavailable — could not import bedrock_client: {e}")
        return None


def _png_dims(data):
    """(width, height) from a PNG's IHDR header, or None if `data` isn't a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def _prepare_image(path):
    """Return PNG bytes guaranteed inside Bedrock's per-image limits (#2973).

    A capture over the per-dimension cap (tall full-page screenshots) or the
    byte cap is downscaled via Pillow. Raises RuntimeError with a NAMED reason
    when a valid payload cannot be produced — the caller records the page as
    UNEVALUATED and FAILS it. Silently sending a payload Bedrock will reject,
    or silently skipping the page, is the #2973 defect class.
    """
    with open(path, "rb") as f:
        data = f.read()
    dims = _png_dims(data)
    if dims is None:
        raise RuntimeError(f"{os.path.basename(path)} is not a valid PNG — cannot submit to Bedrock")
    w, h = dims
    if w <= _BEDROCK_MAX_DIM and h <= _BEDROCK_MAX_DIM and len(data) <= _BEDROCK_MAX_BYTES:
        return data
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            f"{os.path.basename(path)} is {w}x{h}px / {len(data) / 1e6:.1f}MB — over the Bedrock image limit "
            f"({_BEDROCK_MAX_DIM}px, {_BEDROCK_MAX_BYTES // (1024 * 1024)}MB) and Pillow is not installed to downscale it"
        )
    scale = min(_BEDROCK_MAX_DIM / w, _BEDROCK_MAX_DIM / h, 1.0)
    for _ in range(4):  # the byte cap can demand more shrink than the dimension cap alone
        with Image.open(io.BytesIO(data)) as im:
            buf = io.BytesIO()
            im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS).save(buf, format="PNG", optimize=True)
        out = buf.getvalue()
        if len(out) <= _BEDROCK_MAX_BYTES:
            return out
        scale *= 0.7
    raise RuntimeError(f"{os.path.basename(path)} still exceeds {_BEDROCK_MAX_BYTES // (1024 * 1024)}MB after repeated downscaling")


def _image_block(path):
    b64 = base64.b64encode(_prepare_image(path)).decode()
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
    # Drop zero/near-empty captures (a zero-height element crop produces an
    # empty PNG that Bedrock rejects with a ValidationException — seen on the
    # labs chart crop 2026-06-12). If NOTHING usable remains, that used to
    # return a fabricated "ok" verdict — a page the oracle never saw counted
    # as fine. #2973: it is now a loud, named failure like any other
    # cannot-evaluate condition.
    shots = [s for s in shots if os.path.getsize(s["path"]) > 256]
    if not shots:
        raise RuntimeError("no usable screenshots — every capture for this page is empty/near-empty")
    content = [_image_block(s["path"]) for s in shots]
    prompt = _PROMPT.format(name=name, path=path)
    if path in _PAGE_RULES:  # #2383 — page-specific semantic rule (not .format-ed: rules may carry literal braces)
        prompt += "\n\n" + _PAGE_RULES[path]
    content.append({"type": "text", "text": prompt})
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": 700}
    resp = bedrock.invoke(body, model_name=_VISION_MODEL)
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return _parse_verdict(text)


def assess_results(results):
    """Run Claude-vision QA over each page's captured screenshots; mutate `results` in place.

    Adds `ai_verdict` per page. High-severity → issue + status FAIL; med/low → warning.

    A page the oracle CANNOT evaluate is a FAILURE, not a warning (#2973): any
    per-page error (Bedrock ValidationException on the payload, no usable
    captures, …) marks the result `ai_unevaluated`, appends a gating issue, and
    flips it to FAIL. Until 2026-08-22 that path was `⚠ AI-QA error` + continue,
    so run 32580634729 reported "91 passed, 2 failed" while Home and the
    Protocols hub — 2 of the 6 tier-1 doors — were never looked at. Same defect
    class as #2938 (`⚠ unavailable` + exit 0), one level down.

    Budget-aware (#1428): checks budget_guard.allow("visual_ai_qa") UPFRONT — the
    operator-truth band pauses at tier 3 only (ADR-125 as amended by #1927), same band
    as reader_truth_qa.
    A paused run emits the QAPausedByBudget CloudWatch metric (shared with #1440's
    reader-truth hook — one alarm catches either) and returns an explicit
    {"status": "skipped_by_budget", "tier": N} so the caller can render SKIPPED-BY-BUDGET
    rather than have the pause surface only as a per-page "AI-QA error" from the
    bedrock_client Tier-3 hard-stop backstop (silent-by-accident before this fix).
    A mid-run BudgetExceeded (tier flipped to 3 while the sweep was running) gets the
    SAME sanctioned-pause treatment — a deliberate budget pause must never red the
    deploy path as fabricated page failures.

    Returns a status dict `{"status": "ok"|"unavailable"|"skipped_by_budget", ...}` —
    mirroring assess_reader_truth's contract; the "ok" form carries the #2973
    accounting: {"status": "ok", "evaluated": E, "unevaluated": U, "no_shots": S}.
    `results` is still mutated in place.
    """
    bedrock = _import_bedrock()
    if not bedrock:
        for r in results:
            r.setdefault("warnings", []).append("AI-QA skipped — bedrock_client unavailable")
        return {"status": "unavailable", "detail": "bedrock_client unavailable"}

    try:
        from ai import budget_guard  # lambdas/ is on sys.path after _import_bedrock()

        if not budget_guard.allow(_BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            try:
                from operational import reader_truth_qa

                reader_truth_qa.emit_budget_pause_metric("visual_ai_qa", tier)
            except Exception:
                pass  # metric emission is best-effort; the pause itself must still be honest
            print(f"  ⏸ SKIPPED-BY-BUDGET — AI-vision QA paused at budget tier {tier} (operator-truth band, ADR-125/#1927)")
            for r in results:
                r.setdefault("warnings", []).append(f"SKIPPED-BY-BUDGET: AI-vision QA — budget tier {tier} (ADR-125)")
            return {"status": "skipped_by_budget", "tier": tier}
    except ImportError:
        pass  # fail-open, same posture as the guard itself

    try:
        from ai.budget_guard import BudgetExceeded as _BudgetExceeded  # lambdas/ on sys.path
    except Exception:  # pragma: no cover — bedrock imported fine, so this should too

        class _BudgetExceeded(Exception):
            pass

    evaluated, unevaluated, no_shots = 0, [], 0
    for r in results:
        shots = [s for s in r.get("screenshots", []) if s.get("kind") in ("page", "chart")][:_MAX_IMAGES_PER_PAGE]
        if not shots:
            # No page/chart capture at all: only synthetic results or pages whose
            # navigation/screenshot already FAILED deterministically land here
            # (an --ai-qa run force-enables screenshots). Counted + printed so
            # partial coverage is visible, never silent.
            no_shots += 1
            continue
        try:
            verdict = _assess_page(bedrock, r["page"], r["path"], shots)
        except _BudgetExceeded:
            # Tier flipped to 3 MID-run — the same sanctioned pause the upfront
            # check reports, discovered late. Honest skip for this + remaining
            # pages, never fabricated page failures on the deploy path (#1440).
            try:
                tier = budget_guard.current_tier()
            except Exception:
                tier = 3
            print(f"  ⏸ SKIPPED-BY-BUDGET (mid-run) — AI-vision QA paused at budget tier {tier} after {evaluated} page(s)")
            for rr in results:
                if "ai_verdict" not in rr and not rr.get("ai_unevaluated"):
                    rr.setdefault("warnings", []).append(f"SKIPPED-BY-BUDGET: AI-vision QA — budget tier {tier} (ADR-125)")
            return {"status": "skipped_by_budget", "tier": tier, "evaluated": evaluated, "unevaluated": len(unevaluated)}
        except Exception as e:
            # #2973: a page the oracle could not look at has NO coverage — that
            # is a gating failure with a named reason, never a ⚠-and-continue.
            msg = str(e)[:200]
            r["ai_unevaluated"] = msg
            r.setdefault("issues", []).append(f"AI-vision UNEVALUATED (#2973): {msg}")
            r["status"] = "FAIL"
            unevaluated.append(r["page"])
            print(f"  ❌ {r['page']}: AI-vision could NOT evaluate this page — {msg}")
            continue

        evaluated += 1
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

    # #2973: the evaluated-page count printed next to the verdicts — a check that
    # measures nothing returns clean, so say out loud how much WAS measured.
    targeted = evaluated + len(unevaluated)
    line = f"  AI-vision: evaluated {evaluated}/{targeted} captured page(s)"
    if unevaluated:
        line += f"; {len(unevaluated)} UNEVALUATED → FAIL: {', '.join(unevaluated[:6])}"
    if no_shots:
        line += f"; {no_shots} result(s) carried no page/chart capture (deterministic-only)"
    print(line)
    return {"status": "ok", "evaluated": evaluated, "unevaluated": len(unevaluated), "no_shots": no_shots}


def _truth_line(f):
    # #3003: the FULL note — this line is stored in report.json (issues/warnings),
    # the artifact a human adjudicates a finding from without re-running the sweep.
    # It used to cut at 140 chars, so the stored evidence for every finding ended
    # mid-word; truncation belongs at print time only (the console prints below
    # slice their own copies).
    return f"Reader-truth ({f['severity']}) [{f['category']}]: {f['note']}"


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
        from operational import reader_truth_qa  # lambdas/ is on sys.path after _import_bedrock()
    except Exception as e:  # pragma: no cover
        print(f"  ⚠ Reader-truth QA unavailable — could not import reader_truth_qa: {e}")
        for r in results:
            r.setdefault("warnings", []).append(f"Reader-truth QA skipped — reader_truth_qa unavailable: {str(e)[:100]}")
        return {"status": "unavailable", "detail": f"reader_truth_qa unavailable: {str(e)[:100]}"}

    # Budget gate — operator-truth band, tier 3 only (ADR-125/#1927). Honest skip, never silent.
    # #1440: emit the QAPausedByBudget metric + tag every warning SKIPPED-BY-BUDGET
    # (not just "skipped") so a paused run can never be mistaken for a clean one.
    try:
        from ai import budget_guard

        if not budget_guard.allow(reader_truth_qa.BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            reader_truth_qa.emit_budget_pause_metric("visual_ai_qa", tier)
            print(f"  ⏸ SKIPPED-BY-BUDGET — Reader-truth QA paused at budget tier {tier} (operator-truth band, ADR-125/#1927)")
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

    # The debt ledger (#2956): a high finding on a baselined (page, category)
    # is standing, triaged debt — surfaced every run with its issue ref, never
    # gating. Only NEW high findings FAIL. See tests/truth_baseline_audit.py
    # for why (the #2941 aftermath: 16 pre-existing content findings blocked
    # every site deploy regardless of its diff).
    truth_baseline = truth_baseline_audit.load_baseline()

    for f in findings:
        r = by_path.get(f["page"])
        if r is None:
            # model mangled the path — keep the finding visible on the first surface
            r = by_path[surfaces[0]["path"]]
            f = dict(f, note=f"(claimed page {f['page']!r}) {f['note']}")  # full note — #3003
        r.setdefault("truth_findings", []).append(f)
        line = _truth_line(f)
        verdict = truth_baseline_audit.gate_finding(f, truth_baseline)
        if verdict == "new":
            print(f"  {_ICON.get(f['severity'], '?')} truth · {f['page']}: [{f['category']}] {f['note'][:96]}")
            r.setdefault("issues", []).append(line)
            r["status"] = "FAIL"
        elif verdict == "baselined":
            issue_ref = truth_baseline_audit.baselined_issue(f, truth_baseline)
            print(f"  🟡 truth · {f['page']}: BASELINED debt ({issue_ref}) [{f['category']}] {f['note'][:80]}")
            r.setdefault("warnings", []).append(f"BASELINED truth debt ({issue_ref}): {line}")
        else:
            print(f"  {_ICON.get(f['severity'], '?')} truth · {f['page']}: [{f['category']}] {f['note'][:96]}")
            r.setdefault("warnings", []).append(line)

    # Shrink report (#1990's lesson): baselined entries not observed this run,
    # scoped to the pages this sweep drove so a --page run never claims fixes.
    swept = {s["path"] for s in surfaces}
    shrink = {p: cats for p, cats in truth_baseline_audit.shrink_candidates(findings, truth_baseline).items() if p in swept}
    if shrink:
        n = sum(len(c) for c in shrink.values())
        print(
            f"  📉 truth ledger: {n} shrink candidate(s) — baselined but not observed: "
            + "; ".join(f"{p} ({', '.join(c)})" for p, c in sorted(shrink.items()))
        )

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
    data["unevaluated"] = sum(1 for r in data["results"] if r.get("ai_unevaluated"))
    with open(report, "w") as f:
        json.dump(data, f, indent=2)
    # #2973: unevaluated pages are inside `failed` (they gate) — named separately
    # so the tally never reads as "everything was looked at" when it wasn't.
    print(f"\n{data['passed']} passed, {data['failed']} failed ({data['unevaluated']} of those UNEVALUATED) after AI-vision pass.")
    sys.exit(0 if data["failed"] == 0 else 1)
