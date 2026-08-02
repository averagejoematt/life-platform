"""qa_check_content_cadence.py — the content-cadence regression guard (#1972).

Acceptance criterion 2: the chronicle and podcast list pages must carry either
a next-date line or an explicit honest-pending line — never neither (a served
page saying nothing about "when's the next one" is the exact defect #1972
fixes) and never BOTH a positive date AND paused=true on the same payload
(the anti-growth-1 guard: a payload can't simultaneously promise a date and
say generation is paused).

Fetches the live /api/content_cadence endpoint and asserts both the
`chronicle` and `podcast` payloads carry a non-empty `display` string plus
either `next_date` (positive case) or `paused: true` (honest-pending case).

Purely deterministic — no LLM/Bedrock call, so this check is NEVER
budget-paused (mirrors `_check_phase_plausibility`'s "always runs" framing in
qa_check_reader_truth.py: arithmetic has no budget tier). Own module (the
module-size ceiling split idiom, #1665/#1944/#1993) — `assess_content_cadence`
is the pure assessor tests exercise directly with a synthetic payload;
`check_content_cadence` is the live-fetching wrapper qa_smoke_lambda wires in.
"""

import json
import urllib.error
import urllib.request

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL


def _assess_one(name: str, payload) -> str:
    """(''  when valid) else a human-readable defect description for `name`
    ("chronicle" / "podcast")."""
    if not isinstance(payload, dict):
        return f"{name}: payload missing or not an object"
    display = payload.get("display")
    if not isinstance(display, str) or not display.strip():
        return f"{name}: no non-empty 'display' string"
    has_next_date = bool(payload.get("next_date"))
    is_paused = payload.get("paused") is True
    if not has_next_date and not is_paused:
        return f"{name}: neither 'next_date' nor 'paused: true' — no honest signal of when the next installment lands"
    if has_next_date and is_paused:
        return f"{name}: BOTH a positive next_date AND paused:true — a promise the infra can't keep (anti-growth-1)"
    return ""


def assess_content_cadence(data):
    """Pure assessor: (ok, message) for a /api/content_cadence-shaped dict.
    Never raises — a malformed `data` (None, wrong shape) is itself a finding,
    not an exception."""
    if not isinstance(data, dict):
        return False, "response is not a JSON object"
    problems = [p for p in (_assess_one("chronicle", data.get("chronicle")), _assess_one("podcast", data.get("podcast"))) if p]
    if problems:
        return False, "; ".join(problems)
    return True, "both chronicle and podcast carry a non-empty display + (next_date or paused:true)"


def _fetch_site_json(path, timeout=15):
    req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed trusted host
        return json.loads(r.read().decode("utf-8", "replace"))


def check_content_cadence():
    """CHECK — #1972 content-cadence regression guard. Fetches live
    /api/content_cadence and runs the deterministic assessor above. Fail-soft
    on fetch errors (a transient blip must never red the nightly); a real
    shape defect is an ALARMED content-truth FAIL (novel, never chronic —
    the #2025 taxonomy: a page silently saying nothing about the next
    installment is exactly the regression this guard exists to catch)."""
    check = Check("content_cadence:next_installment", "Reader Truth", CONTENT_TRUTH)
    try:
        data = _fetch_site_json("/api/content_cadence")
    except urllib.error.HTTPError as e:
        return [check.warn(f"/api/content_cadence fetch failed (fail-soft): HTTP {e.code}")]
    except Exception as e:
        return [check.warn(f"/api/content_cadence fetch failed (fail-soft): {str(e)[:120]}")]

    ok, msg = assess_content_cadence(data)
    return [check.ok(msg) if ok else check.fail(msg)]
