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

Degrades cleanly: if Bedrock/`bedrock_client` is unavailable or the $75 budget guard is at
tier 3, AI-QA is skipped with a warning — the deterministic checks still stand.

Entry point: `assess_results(results)` — mutates the list in place. Called by
visual_qa.run_sweep when `--ai-qa` is passed; also runnable standalone on a report.json.
"""

import base64
import json
import os
import re
import sys

# Haiku cross-region profile (vision-capable, cheap). bedrock_client maps the short name.
_VISION_MODEL = os.environ.get("VISUAL_AI_MODEL", "claude-haiku-4-5-20251001")
_MAX_IMAGES_PER_PAGE = int(os.environ.get("VISUAL_AI_MAX_IMAGES", "3"))

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

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"renders_ok": true|false, "charts_populated": "yes"|"no"|"n/a", \
"issues": [{{"type": "string", "severity": "low"|"med"|"high", "note": "string"}}], \
"severity": "ok"|"low"|"med"|"high", "summary": "one sentence"}}
Set top-level "severity" to the maximum of the issue severities, or "ok" if there are none."""

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
    if v.get("severity") not in ("ok", "low", "med", "high"):
        # derive from issue list if the model omitted/garbled the top-level field
        sevs = [i.get("severity") for i in v.get("issues", []) if i.get("severity") in ("low", "med", "high")]
        order = {"low": 1, "med": 2, "high": 3}
        v["severity"] = max(sevs, key=lambda s: order[s]) if sevs else "ok"
    return v


def _assess_page(bedrock, name, path, shots):
    content = [_image_block(s["path"]) for s in shots]
    content.append({"type": "text", "text": _PROMPT.format(name=name, path=path)})
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": 700}
    resp = bedrock.invoke(body, model_name=_VISION_MODEL)
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    return _parse_verdict(text)


def assess_results(results):
    """Run Claude-vision QA over each page's captured screenshots; mutate `results` in place.

    Adds `ai_verdict` per page. High-severity → issue + status FAIL; med/low → warning.
    No-ops gracefully (per page) on any Bedrock error or if the budget guard is at tier 3.
    """
    bedrock = _import_bedrock()
    if not bedrock:
        for r in results:
            r.setdefault("warnings", []).append("AI-QA skipped — bedrock_client unavailable")
        return results

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

    return results


if __name__ == "__main__":
    # Standalone: re-assess an existing qa-screenshots/report.json (paths must still exist).
    report = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "qa-screenshots", "report.json")
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
