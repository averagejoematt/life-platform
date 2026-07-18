"""
reader_truth_qa.py — the shared phase-aware "reader truth" rubric (#1095/#1096).

The visual AI-QA layer (tests/visual_ai_qa.py) judges whether pages RENDER; this
module judges whether their PROSE can be TRUE at the current experiment phase.
Matthew's 2026-07-11 manual review found ~10 truth-class items by hand (week-long
trends narrated on day 0, numbers that could not exist yet, the same paragraph
pasted across lenses) — this rubric turns that read-through into a machine gate.

ONE prompt, TWO hooks (both import this module so the rubric can never fork):
  - CI post-deploy: tests/visual_ai_qa.assess_reader_truth() over the harness's
    rendered-prose dumps (visual_qa.py --reader-truth), gating like AI-vision.
  - Nightly: lambdas/operational/qa_smoke_lambda.check_reader_truth() over a
    small HTTPS-fetched surface set, so truth regressions surface between
    deploys too. Fail-soft there — a Bedrock outage must never red the nightly.

Phase ground truth is computed at runtime from constants.EXPERIMENT_START_DATE
(never hardcoded — it moves on every experiment reset, ADR-058/077).

Model: Haiku (structured task per ADR-049/063 tiering), override via
READER_TRUTH_MODEL. Budget: feature "reader_truth_qa" in budget_guard's ladder —
internal QA, pauses FIRST (tier >= 1, ADR-125); both hooks report the skip
honestly, never silent green.

Lives at lambdas/ root so it ships in every function bundle (#781) AND is
importable by the CI-side harness (tests/ already puts lambdas/ on sys.path).
Stdlib-only — safe to import anywhere.
"""

import json
import os
import re
from datetime import date, datetime
from html.parser import HTMLParser

# Haiku by default — structured verdict task (ADR-049 tiering, ADR-063 budget).
DEFAULT_MODEL = os.environ.get("READER_TRUTH_MODEL", "claude-haiku-4-5-20251001")

# budget_guard._FEATURE_CUTOFF key — internal QA band, pauses at tier >= 1 (ADR-125).
BUDGET_FEATURE = "reader_truth_qa"

# The four rubric categories (#1095). parse/normalize coerce anything else to "other".
CATEGORIES = (
    "temporal_contradiction",
    "impossible_number",
    "duplicated_narrative",
    "audience_violation",
)

SEVERITIES = ("low", "med", "high")

# Batch 4-6 surfaces per call so the duplicated-narrative check sees pages
# side-by-side (a single-page call structurally cannot catch duplication).
DEFAULT_BATCH_SIZE = 5

# Per-surface prose cap — bounds tokens (~1.5k tokens/page at 6k chars) so a
# 6-surface batch stays comfortably inside a Haiku context + pennies per run.
MAX_PROSE_CHARS = 6000


# ── phase ground truth ─────────────────────────────────────────────────────────


def phase_context(today_iso=None):
    """The experiment phase, computed at runtime from constants.EXPERIMENT_START_DATE.

    Returns {"today", "start_date", "day_n", "pre_start", "days_until_start"}.
    day_n is 1-indexed (constants.day_n); 0 == pre-genesis countdown state.
    `today_iso` is injectable for tests (derive fixtures from EXPERIMENT_START_DATE,
    never wall-clock literals); default is today in the site's Pacific timezone.
    """
    from constants import EXPERIMENT_START_DATE, day_n

    if today_iso is None:
        from zoneinfo import ZoneInfo

        today_iso = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    n = day_n(today_iso)
    days_until = 0
    if n == 0:
        days_until = (date.fromisoformat(EXPERIMENT_START_DATE) - date.fromisoformat(today_iso)).days
    return {
        "today": today_iso,
        "start_date": EXPERIMENT_START_DATE,
        "day_n": n,
        "pre_start": n == 0,
        "days_until_start": days_until,
    }


def _phase_line(phase):
    if phase["pre_start"]:
        return (
            f"The experiment has NOT started yet — Day 1 is {phase['start_date']}, "
            f"{phase['days_until_start']} day(s) away (today is {phase['today']}). The site runs an honest "
            f"pre-start countdown; ZERO days of current-experiment data can exist yet."
        )
    return (
        f"Today ({phase['today']}) is Day {phase['day_n']} of the experiment (Day 1 = {phase['start_date']}). "
        f"At most {phase['day_n']} day(s) of current-experiment data can exist; any claim of a longer "
        f"in-experiment history (trends, streaks, averages, counts) is impossible unless it is explicitly "
        f"labeled lifetime / all-time / a previous cycle / the pilot."
    )


# ── prompt ─────────────────────────────────────────────────────────────────────

_PROMPT_HEADER = """You are a meticulous editorial truth reviewer for a public "measured life" \
experiment site. Below is the RENDERED TEXT of {k} of its surfaces (page prose and/or API payloads — \
no images). The site's data legitimately changes daily; you are judging whether the WORDS AND NUMBERS \
CAN BE TRUE at the current experiment phase, not whether they match any baseline.

EXPERIMENT PHASE (ground truth, computed from the codebase — trust this over anything the pages say):
{phase_line}

FLAG findings in exactly these four categories (with severity low|med|high):
1. "temporal_contradiction" — text asserting a history the phase makes impossible: e.g. "Day 2" \
alongside "your 30-day trend", "over the past three weeks" early in the experiment, a day number or \
date inconsistent with the phase above, or two surfaces disagreeing about what day it is.
2. "impossible_number" — a number that cannot plausibly exist yet at this phase: e.g. "21 workouts \
this cycle" on Day 2, a streak or in-experiment average spanning more days than have occurred.
3. "duplicated_narrative" — the SAME substantive narrative paragraph (or a near-identical one) \
appearing on two or more of the surfaces below. Shared navigation, footers, taglines, and short \
labels do NOT count — only real narrative/analysis prose.
4. "audience_violation" — copy that assumes the reader saw private context: unexplained internal \
jargon, references to private conversations or sessions ("as discussed", "like I told you"), or \
second-person notes clearly addressed to the site's owner rather than a public reader.

Severity: "high" = a first-time reader would conclude the site is lying or broken; "med" = \
noticeably wrong but survivable; "low" = borderline/cosmetic.

DO NOT flag (these are CORRECT):
- lifetime / all-time / cross-cycle / "pilot" / previous-cycle stats labeled as such — history from \
before Day 1 legitimately exists and may be large;
- the pre-start countdown copy itself, and honest sparse/empty states ("awaiting data", "N readings \
so far", "no data yet");
- story/archive/chronicle content clearly dated before the current cycle;
- the same header/nav/footer chrome appearing on every page;
- API field names or JSON structure — judge only human-readable narrative values inside them.

SURFACES ({k}):
"""

_PROMPT_FOOTER = """
Respond with ONLY a JSON object, no prose, no markdown fences:
{{"findings": [{{"page": "<path of the surface, exactly as given>", \
"category": "temporal_contradiction"|"impossible_number"|"duplicated_narrative"|"audience_violation", \
"severity": "low"|"med"|"high", "note": "string"}}], \
"severity": "ok"|"low"|"med"|"high", "summary": "one sentence"}}
Set top-level "severity" to the maximum finding severity, or "ok" if there are no findings."""


def build_prompt(pages, phase, max_chars=MAX_PROSE_CHARS):
    """Build the reader-truth prompt for one batch of surfaces.

    `pages`: [{"name": str, "path": str, "prose": str}, ...] (4-6 per batch so the
    duplicated-narrative check sees the surfaces side-by-side).
    """
    parts = [_PROMPT_HEADER.format(k=len(pages), phase_line=_phase_line(phase))]
    for i, p in enumerate(pages, 1):
        prose = (p.get("prose") or "").strip()
        if len(prose) > max_chars:
            prose = prose[:max_chars] + "\n…[truncated]"
        parts.append(f"\n--- SURFACE {i}: {p.get('name', '?')} ({p.get('path', '?')}) ---\n{prose}\n")
    parts.append(_PROMPT_FOOTER)
    return "".join(parts)


# ── verdict parsing ────────────────────────────────────────────────────────────


def parse_verdict(text):
    """Pull the JSON verdict out of the model reply, tolerating stray prose/fences.

    Unparseable output degrades to a no-findings verdict (never raises) — the
    hooks treat a missing verdict as advisory, not as a pass OR a fail.
    """
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"findings": [], "severity": "ok", "summary": "(no structured verdict)", "raw": (text or "")[:200]}
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"findings": [], "severity": "ok", "summary": "(unparseable verdict)", "raw": (text or "")[:200]}
    if not isinstance(v.get("findings"), list):
        v["findings"] = []
    return v


def _normalize_finding(f, batch_paths):
    """Coerce one model finding into the canonical shape; never raises."""
    if not isinstance(f, dict):
        return None
    sev = f.get("severity")
    if sev not in SEVERITIES:
        sev = "low"  # an unrecognized severity must never gate
    cat = f.get("category")
    if cat not in CATEGORIES:
        cat = "other"
    page = str(f.get("page") or "")
    if page not in batch_paths:
        # tolerate missing/extra slashes from the model
        norm = "/" + page.strip("/") + "/" if page.strip("/") else page
        if norm in batch_paths:
            page = norm
    return {"page": page, "category": cat, "severity": sev, "note": str(f.get("note") or "")[:300]}


# ── assessment loop ────────────────────────────────────────────────────────────


def _batches(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def assess_prose(pages, invoke, model_name=None, today_iso=None, batch_size=DEFAULT_BATCH_SIZE, max_chars=MAX_PROSE_CHARS):
    """Run the reader-truth rubric over `pages` in 4-6 surface batches.

    Args:
        pages: [{"name", "path", "prose"}, ...] — surfaces with rendered text.
        invoke: a bedrock_client.invoke-compatible callable (injectable for tests).
        model_name: model override; default Haiku (DEFAULT_MODEL).
        today_iso: phase anchor override (tests derive it from EXPERIMENT_START_DATE).

    Returns (findings, errors):
        findings: normalized dicts {"page", "category", "severity", "note"}.
        errors: per-batch error strings — a failed batch is reported, never raised
                (fail-soft: a Bedrock outage degrades to "no verdict", not a crash).
    """
    phase = phase_context(today_iso)
    pages = [p for p in pages if (p.get("prose") or "").strip()]
    findings, errors = [], []
    for batch in _batches(pages, max(1, batch_size)):
        prompt = build_prompt(batch, phase, max_chars=max_chars)
        batch_paths = {p.get("path") for p in batch}
        try:
            resp = invoke(
                {"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}], "max_tokens": 1500},
                model_name=model_name or DEFAULT_MODEL,
            )
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            for raw in parse_verdict(text).get("findings", []):
                f = _normalize_finding(raw, batch_paths)
                if f:
                    findings.append(f)
        except Exception as e:
            errors.append(f"batch [{', '.join(str(p.get('path')) for p in batch)}]: {str(e)[:140]}")
    return findings, errors


# ── HTML → text (for the nightly hook's HTTPS-fetched pages) ──────────────────


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._chunks.append(data.strip())

    def text(self):
        return "\n".join(self._chunks)


def html_to_text(html):
    """Visible-ish text from an HTML document (stdlib only; script/style stripped).

    Static-HTML approximation of the browser's innerText — good enough for the
    nightly hook (server-rendered prose + labels); the CI hook gets the real
    rendered innerText from the Playwright harness.
    """
    try:
        p = _TextExtractor()
        p.feed(html or "")
        return re.sub(r"\n{3,}", "\n\n", p.text())
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")  # crude fallback, never raises


# ── deterministic vitals-freshness rule (#1226 / recurrence of #787) ─────────────
#
# The LLM rubric above judges prose narratively; this rule is DETERMINISTIC (no
# Bedrock) so it gates the same way every run and is unit-testable offline. It
# encodes the #1226 defect directly: the "EACH COACH'S READ" digest cards quoted
# Day-1 vitals ("recovery dip 60% → 44%", "resting heart rate 62 bpm") with no
# as-of date, one click from a cockpit showing recovery 96% / RHR 57. #787's fix
# added an as-of stamp only to the by-coach surface; this rule guards the digest
# surface it missed. Rule: any coach narrative quoting recovery/HRV/RHR must
# carry an as-of date; a DATED quote diverging > divergence_pct from that date's
# true vitals is a stale-as-current read.

# Divergence threshold — a recovery of 44 vs a true 96 is ~54% off, well over this.
VITALS_DIVERGENCE_PCT = 20.0

# (metric, window regex from the metric word, value regex inside that window).
# Windowed so "resting heart rate 62 bpm ... 315.6 lbs" only reads the 62, and a
# "60% → 44%" dip yields BOTH endpoints for the divergence check.
_VITALS_WINDOWS = (
    ("recovery", re.compile(r"recovery[^.]{0,40}", re.I), re.compile(r"(\d{1,3})\s*%")),
    ("hrv", re.compile(r"\bhrv\b[^.]{0,30}", re.I), re.compile(r"(\d{1,3})\s*ms", re.I)),
    ("rhr", re.compile(r"(?:resting heart rate|\brhr\b)[^.]{0,30}", re.I), re.compile(r"(\d{1,3})\s*bpm", re.I)),
)

# Any of these markers anywhere in a surface's prose counts as an as-of stamp —
# matches every string coachAsOf() can emit ("as of Jul 13", "… refresh paused",
# "… next refresh pending") plus the ISO/"read on" forms.
_AS_OF_MARKER = re.compile(r"\b(?:as of|as-of|read on|refresh paused|next refresh pending)\b", re.I)


def quoted_vitals(prose):
    """{metric: [int, ...]} for every recovery %/HRV ms/RHR bpm quoted in `prose`."""
    text = prose or ""
    out = {}
    for metric, win_re, num_re in _VITALS_WINDOWS:
        vals = []
        for w in win_re.finditer(text):
            for n in num_re.findall(w.group(0)):
                try:
                    vals.append(int(n))
                except (TypeError, ValueError):
                    pass
        if vals:
            out[metric] = vals
    return out


def _has_as_of(prose):
    return bool(_AS_OF_MARKER.search(prose or ""))


def _diverges(quoted, actual, pct):
    """True if `quoted` is more than `pct`% away from `actual`."""
    try:
        actual = float(actual)
    except (TypeError, ValueError):
        return False
    if actual == 0:
        return quoted != 0
    return abs(quoted - actual) / abs(actual) * 100.0 > pct


def check_vitals_freshness(surfaces, vitals_by_date=None, divergence_pct=VITALS_DIVERGENCE_PCT):
    """Deterministic reader-truth rule (#1226): flag coach narratives that quote
    recovery/HRV/RHR without an as-of date, and dated quotes that diverge from the
    known vitals of their as-of date.

    Args:
        surfaces: [{"name", "path", "prose", optional "as_of": "YYYY-MM-DD"}, ...].
        vitals_by_date: {"YYYY-MM-DD": {"recovery": float, "hrv": float, "rhr": float}}
            — optional; enables the divergence sub-check for surfaces carrying an
            explicit ISO `as_of`.
        divergence_pct: percentage tolerance before a dated quote is flagged.

    Returns normalized findings [{"page", "category", "severity", "note"}] in the
    same shape as the LLM path (category "temporal_contradiction"). Never raises.
    """
    vitals_by_date = vitals_by_date or {}
    findings = []
    for s in surfaces or []:
        prose = s.get("prose") or ""
        quoted = quoted_vitals(prose)
        if not quoted:
            continue
        page = s.get("path") or s.get("name") or "?"
        metrics = ", ".join(sorted(quoted))
        if not (s.get("as_of") or _has_as_of(prose)):
            findings.append(
                {
                    "page": page,
                    "category": "temporal_contradiction",
                    "severity": "high",
                    "note": (
                        f"coach narrative quotes {metrics} with no as-of date (#1226/#787) — "
                        "a reader can't tell these from the current cockpit vitals"
                    ),
                }
            )
            continue
        # Dated — check quoted values against that date's true vitals when known.
        truth = vitals_by_date.get(s.get("as_of")) if s.get("as_of") else None
        if not truth:
            continue
        for metric, vals in quoted.items():
            actual = truth.get(metric)
            if actual in (None, ""):
                continue
            for v in vals:
                if _diverges(v, actual, divergence_pct):
                    findings.append(
                        {
                            "page": page,
                            "category": "temporal_contradiction",
                            "severity": "med",
                            "note": f"quoted {metric} {v} diverges >{divergence_pct:.0f}% from the {s['as_of']} value {actual}",
                        }
                    )
    return findings
