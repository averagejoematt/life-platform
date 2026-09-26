#!/usr/bin/env python3
"""
comprehension_qa.py — the newcomer-comprehension judge (advisory, M4, #4182).

A blind reader per flagship door, graded against the page's stated intent. Where
`visual_ai_qa.py` judges whether a page RENDERS and `reader_truth_qa.py` judges
whether its prose CAN BE TRUE, this module judges something neither of them asks:
does a first-time reader, shown nothing but the fold and its own text, come away
knowing what the page is for and what to click?

TWO Bedrock calls per door, never one:
  1. the BLIND reader — a 390x844 fold screenshot + the page's `main` innerText
     (first 1500 chars), asked one question with no intent shown:
     "In one sentence: what is this page for, and what would you click?"
  2. the text-only grader — sees the reader's one-sentence answer plus the page's
     own `intent` (a fact declared in `tests/qa_manifest.py`, never shown to the
     reader), and scores it 0/1/2:
       2 = names the purpose AND a click that serves it
       1 = partial (one of the two, or a vague miss)
       0 = wrong or too generic to show comprehension of THIS page

Reuses `visual_ai_qa.py`'s Bedrock plumbing rather than re-deriving it:
`_attributed`/`_attributed_invoke` (spend attribution, #2888), `_prepare_image`
(the Bedrock image-size guard), `_verdict_retry` (the shared one-retry-on-unreadable
chokepoint, #3688), and the `unevaluated` third state (#3540) — a reply that cannot
be read as an answer is recorded as unevaluated, never silently scored.

ADVISORY, not gating (#4182 M4): a low score never fails a deploy or a CI job. It
runs as a `continue-on-error` step in `.github/workflows/visual-qa.yml`, after the
sweep, and writes `qa-screenshots/comprehension.json`. The step itself fails ONLY
when that artifact could not be written — a judge that produced no output is a
worse failure than a judge that scored low, and must never look like a clean skip.

Budget-gated (#1428 lineage): `budget_guard.allow("comprehension_qa")` is checked
FIRST, before any capture or Bedrock call — a paused run costs nothing and is
reported as `skipped_by_budget`, never as a silent zero. Band 1 (pauses with
internal/dev AI, ADR-125): this judge is a triage signal for a human to read later,
not a reader-facing surface and not the operator-truth deploy gate, so it has no
claim to outlive coach narratives or the two CI truth judges.

The floor ratchet this issue's plan describes (a `COMPREHENSION` gate + proofs) is
NOT built yet — day 14 is 2026-10-10. Until then this module only measures and
reports; nothing consumes the score as a gate.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import qa_manifest  # noqa: E402 — the six doors' `intent` facet lives here
import visual_ai_qa as _vqa  # noqa: E402 — the shared Bedrock plumbing this module reuses

# The six flagship doors, in a fixed reporting order (not qa_manifest's own order —
# this is the reader's front-to-back path through the site, home first).
DOORS = ("/", "/cockpit/", "/data/", "/coaching/", "/protocols/", "/story/")

# budget_guard._FEATURE_CUTOFF key (band 1 — pauses with internal/dev AI, #4182 M4).
_BUDGET_FEATURE = "comprehension_qa"

# Haiku — structured judgement task (ADR-049 tiering); override for local runs.
_MODEL = os.environ.get("COMPREHENSION_MODEL", "claude-haiku-4-5-20251001")

_BASE_URL = os.environ.get("COMPREHENSION_BASE_URL", "https://averagejoematt.com")
_VIEWPORT = {"width": 390, "height": 844}

_SCREENSHOT_DIR = os.environ.get("COMPREHENSION_SCREENSHOT_DIR", os.path.join(_HERE, "..", "qa-screenshots"))
_ARTIFACT_PATH = os.environ.get("COMPREHENSION_ARTIFACT_PATH", os.path.join(_SCREENSHOT_DIR, "comprehension.json"))

_MAIN_TEXT_CHARS = 1500

# The exact prompt (#4182 M4) — sent verbatim, with no intent shown to the reader.
READER_PROMPT = "In one sentence: what is this page for, and what would you click?"

_READER_MAX_TOKENS = 200
_GRADER_MAX_TOKENS = 200

_GRADER_PROMPT = (
    "You are grading a blind reader's one-sentence answer to the question \"what is this page "
    "for, and what would you click?\" The reader saw ONLY a screenshot of the page's fold and its "
    "visible text — never this page's stated purpose below.\n\n"
    "The page's real, stated purpose:\n{intent}\n\n"
    "The reader's answer:\n{answer}\n\n"
    "Score the answer against the real purpose:\n"
    "  2 = the answer names the page's real purpose AND a click that serves it\n"
    "  1 = the answer is PARTIALLY right — it names the purpose OR a plausible click, not both, "
    "or is a vague near-miss\n"
    "  0 = the answer is wrong, or too generic to show it understood THIS specific page\n\n"
    'Respond with ONLY a JSON object, no prose, no markdown fences: {{"score": 0|1|2, "note": '
    '"one short sentence explaining the score"}}'
)

# CloudWatch metric — the dead-man's numeric twin to the printed ::notice:: line.
# Same lazy-import, fail-soft posture as reader_truth_qa.emit_budget_pause_metric: a
# metrics hiccup must never break an already-advisory judge.
_METRIC_NAMESPACE = "LifePlatform/QA"
_METRIC_NAME = "ComprehensionScored"


def _door_intent(path):
    """The page's declared `intent` from tests/qa_manifest.py, or None if unset."""
    entry = qa_manifest.PAGES_BY_PATH.get(path)
    return (entry or {}).get("intent")


def _capture_fold(path, base_url=None):
    """(png_path, main_text) for one door — a FRESH 390x844 page, fold only (no
    full-page scroll), plus `main`'s (or the body's, if there is no `main`) innerText
    sliced to `_MAIN_TEXT_CHARS`. Imports Playwright lazily so this module stays
    importable (and unit-testable) without it — every test in
    tests/test_comprehension_qa.py monkeypatches this function rather than launching
    a real browser."""
    from playwright.sync_api import sync_playwright

    base_url = base_url or _BASE_URL
    os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
    slug = path.strip("/").replace("/", "-") or "home"
    png_path = os.path.join(_SCREENSHOT_DIR, f"comprehension-{slug}.png")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport=_VIEWPORT)
            page.goto(base_url.rstrip("/") + path, wait_until="networkidle", timeout=30000)
            page.screenshot(path=png_path)  # viewport only — full_page defaults False
            text = page.evaluate(
                "() => { const m = document.querySelector('main'); " "return ((m ? m.innerText : document.body.innerText) || '').trim(); }"
            )
        finally:
            browser.close()
    return png_path, (text or "")[:_MAIN_TEXT_CHARS]


def _reader_unreadable_kind(resp):
    """The #3540 unevaluated-third-state check for the reader's free-text answer —
    no JSON is expected here, so "unreadable" means truncated or empty, not unparseable."""
    if isinstance(resp, dict) and (resp.get("stop_reason") or "") == "max_tokens":
        return _vqa._KIND_TRUNCATED
    text = (_vqa._response_text(resp) or "").strip()
    return _vqa._KIND_NO_VERDICT if not text else None


def _ask_reader(invoke_fn, png_path, main_text, path):
    """One blind-reader call. Returns the reader's answer text, or None if the judge
    returned nothing readable (#3540) after the shared one-retry chokepoint (#3688)."""
    payload = _vqa._prepare_image(png_path)
    content = [
        _vqa._png_block(payload),
        {"type": "text", "text": f"This page's visible text (may be truncated):\n{main_text}"},
        {"type": "text", "text": READER_PROMPT},
    ]
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": _READER_MAX_TOKENS}
    resp, unread, _attempts = _vqa._verdict_retry()(
        invoke_fn, body, unreadable=_reader_unreadable_kind, model_name=_MODEL, label=f"comprehension reader ({path})"
    )
    if unread:
        return None
    return _vqa._response_text(resp).strip()


def _parse_grade(text):
    """{"score": 0|1|2, "note": str} from the grader's reply, or the #3540 unevaluated
    marker (`_vqa._UNEVALUATED_FIELD`) when the reply cannot be read as a grade. Its
    OWN schema — not visual_ai_qa's issues/severity shape, which does not apply here —
    but the SAME tolerant-extraction idea and the SAME three-kind vocabulary."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"score": None, "note": "", _vqa._UNEVALUATED_FIELD: _vqa._KIND_NO_VERDICT}
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"score": None, "note": "", _vqa._UNEVALUATED_FIELD: _vqa._KIND_UNPARSEABLE}
    score = v.get("score")
    if isinstance(score, bool) or score not in (0, 1, 2):
        return {"score": None, "note": str(v.get("note") or "")[:200], _vqa._UNEVALUATED_FIELD: _vqa._KIND_UNPARSEABLE}
    return {"score": int(score), "note": str(v.get("note") or "")[:200]}


def _grade_unreadable_kind(resp):
    if isinstance(resp, dict) and (resp.get("stop_reason") or "") == "max_tokens":
        return _vqa._KIND_TRUNCATED
    return _parse_grade(_vqa._response_text(resp)).get(_vqa._UNEVALUATED_FIELD)


def _ask_grader(invoke_fn, intent, answer):
    """One grader call. Returns (score_or_None, note)."""
    prompt = _GRADER_PROMPT.format(intent=intent or "(no intent registered for this page)", answer=answer)
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}], "max_tokens": _GRADER_MAX_TOKENS}
    resp, unread, _attempts = _vqa._verdict_retry()(
        invoke_fn, body, unreadable=_grade_unreadable_kind, model_name=_MODEL, label="comprehension grader"
    )
    if unread:
        return None, f"grader returned no readable verdict ({unread})"
    parsed = _parse_grade(_vqa._response_text(resp))
    return parsed["score"], parsed["note"]


def _assess_door(invoke_fn, path, intent, base_url):
    """One door end to end: capture -> blind reader -> grader. Every failure mode
    (a capture exception, an unreadable reader reply, an unreadable grade) becomes a
    NAMED unevaluated page row — never a raised exception and never a fabricated
    score, matching #2973's rule for the vision judge."""
    try:
        png_path, main_text = _capture_fold(path, base_url=base_url)
    except Exception as e:  # noqa: BLE001 — any capture failure is this page's unevaluated reason
        return {"path": path, "answer": None, "score": None, "grader_note": f"capture failed: {str(e)[:160]}"}

    try:
        answer = _ask_reader(invoke_fn, png_path, main_text, path)
    except Exception as e:  # noqa: BLE001
        return {"path": path, "answer": None, "score": None, "grader_note": f"reader call failed: {str(e)[:160]}"}
    if answer is None:
        return {"path": path, "answer": None, "score": None, "grader_note": "the blind reader returned no readable answer"}

    try:
        score, note = _ask_grader(invoke_fn, intent, answer)
    except Exception as e:  # noqa: BLE001
        return {"path": path, "answer": answer, "score": None, "grader_note": f"grader call failed: {str(e)[:160]}"}
    return {"path": path, "answer": answer, "score": score, "grader_note": note}


def _emit_scored_metric(scored):
    """CloudWatch custom metric — the numeric twin of the printed ::notice:: dead-man
    line (same lazy-import, fail-soft shape as
    lambdas/operational/reader_truth_qa.emit_budget_pause_metric)."""
    try:
        import boto3

        boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=[{"MetricName": _METRIC_NAME, "Value": float(scored), "Unit": "Count"}],
        )
    except Exception as e:  # noqa: BLE001 — a metrics hiccup must not affect an advisory judge
        print(f"  ⚠ {_METRIC_NAME} metric emit failed (non-fatal): {str(e)[:140]}")


def _write_artifact(doc, out_path):
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def assess_doors(base_url=None, out_path=None):
    """Run the comprehension judge over the six flagship doors. ALWAYS writes the
    artifact (budget-paused, bedrock-unavailable, and fully-scored all write it) and
    ALWAYS prints the `::notice::comprehension scored=N/6` dead-man line — the one
    thing this function must never do is answer silently.

    Returns the same dict written to `out_path`.
    """
    base_url = base_url or _BASE_URL
    out_path = out_path or _ARTIFACT_PATH
    run_at = datetime.now(timezone.utc).isoformat()

    pages = []
    scored = 0
    unevaluated = 0
    skipped_by_budget = False

    bedrock = _vqa._import_bedrock()
    if bedrock is None:
        unevaluated = len(DOORS)
    else:
        # The budget check runs FIRST — before any capture or Bedrock spend (#4182 M4).
        try:
            from ai import budget_guard  # lambdas/ is on sys.path after _import_bedrock()

            if not budget_guard.allow(_BUDGET_FEATURE):
                skipped_by_budget = budget_guard.current_tier()
                print(
                    f"  ⏸ SKIPPED-BY-BUDGET — comprehension judge paused at budget tier " f"{skipped_by_budget} (band 1, advisory, #4182)"
                )
            else:
                invoke_fn = _vqa._attributed_invoke(bedrock, _BUDGET_FEATURE)
                for path in DOORS:
                    intent = _door_intent(path)
                    result = _assess_door(invoke_fn, path, intent, base_url)
                    pages.append(result)
                    if result.get("score") in (0, 1, 2):
                        scored += 1
                    else:
                        unevaluated += 1
        except ImportError:
            print("  ⚠ comprehension judge — budget_guard unavailable, skipping (fail-soft)")
            unevaluated = len(DOORS)

    doc = {
        "run_at": run_at,
        "expected": len(DOORS),
        "scored": scored,
        "unevaluated": unevaluated,
        "skipped_by_budget": skipped_by_budget,
        "pages": pages,
    }
    _write_artifact(doc, out_path)

    for p in pages:
        if p.get("score") in (0, 1):
            print(f"::warning::comprehension judge — {p['path']} scored {p['score']}/2: {(p.get('grader_note') or '')[:140]}")
        elif p.get("score") is None:
            print(f"::warning::comprehension judge — {p['path']} UNEVALUATED: {(p.get('grader_note') or '')[:140]}")
    print(f"::notice::comprehension scored={scored}/{len(DOORS)}")
    _emit_scored_metric(scored)
    return doc


def main():
    try:
        assess_doors()
    except Exception as e:  # noqa: BLE001 — a crash must still be judged by artifact presence, never propagate raw
        print(f"::error::comprehension judge crashed before writing its artifact: {str(e)[:300]}")
    if not os.path.exists(_ARTIFACT_PATH):
        print(f"::error::comprehension judge — {_ARTIFACT_PATH} was not written")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
