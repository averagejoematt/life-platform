"""brief_budget.py — the Morning Brief's attention budget, checked on the RENDERED email (#6240, owner ruling 2026-11-23 §7).

``check(html, text, ...)`` reads what would be sent — the html part and the plain-text part — and returns every
violation. Production records them on the send row and, when any is HARD, sends the short failure notice instead
(``emails.brief_trial``); the tests fail on them. ``measure`` is the same reading as numbers for the send row.

What it reads is structure the compact renderer writes (``content.brief_compact``): ``data-metric`` rows (with
``data-source``/``data-as-of``/``data-q``/``data-v``), ``data-rec`` recommendations, ``data-alert`` verified alerts,
``data-lead``, ``data-unknown`` lines and one ``data-detail-link``. A legacy-shaped email carries none of that and
fails on words, legacy sections and voices — the negative control the tests hold.

Pure module: no AWS, no clock, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from content import brief_compact as bc

# Every legacy section is wrapped in an `<!-- S:name -->` marker (html_builder, the hybrid block); the compact email has
# none. The headings are the long report's own, for a legacy body that lost its markers.
LEGACY_MARKERS = ("<!-- S:", "FULL DETAIL", "THE COMPLETE BRIEF", "HABITS DEEP-DIVE", "TRAINING REPORT", "COACH ANALYSIS")
CATEGORICAL_RE = re.compile(
    r"\bnothing (?:important )?(?:changed|needs)\b|\bnothing to do\b|\ball (?:of yesterday's )?data (?:has )?arrived\b", re.I
)
_WORD = re.compile(r"[A-Za-z0-9][\w'’.,%/:+−-]*")
# The height estimate: the compact card's content column at a 390 px phone (390 − 2×8 outer − 2×22 inner padding),
# at 15 px text ≈ 7.6 px per character, so ≈ 43 characters a line at 22.5 px line height; block margins on top.
_EST_CHARS_PER_LINE = 43
_EST_LINE_PX = 22.5
_EST_BLOCK_PX = 10
_EST_FRAME_PX = 64
HEIGHT_BUDGET_PX = 900  # a busy day: about 1.35 phone screens; the rendered test holds a quiet day to one screen
PHONE_SCREEN_PX = 664  # the usable iPhone mail viewport at 390 px wide (844 minus status and toolbar chrome)

# Hard violations send the failure notice in production; soft ones are recorded only.
HARD = frozenset(
    {
        "words_over",
        "text_words_over",
        "text_missing",
        "metrics_over",
        "recs_over",
        "voice",
        "legacy_section",
        "detail_link",
        "missed_wording",
        "categorical_with_unknowns",
        "clearance",
        "contradiction",
        "attribution",
        "unchanged_repeat",
        "trend_dismissed",
    }
)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    @property
    def hard(self) -> bool:
        return self.code in HARD


class _Reader(HTMLParser):
    """Visible text (split into alert / non-alert) and the data-* elements, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list = []
        self.elements: list = []  # (tag, attrs dict, text parts list)
        self.text, self.alert_text = [], []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in ("style", "script", "title", "head"):
            self.skip += 1
        el = (tag, a, [])
        self.stack.append(el)
        if any(k.startswith("data-") for k in a):
            self.elements.append(el)

    def handle_endtag(self, tag):
        if tag in ("style", "script", "title", "head"):
            self.skip = max(0, self.skip - 1)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.skip:
            return
        in_alert = any("data-alert" in el[1] for el in self.stack)
        (self.alert_text if in_alert else self.text).append(data)
        for el in self.stack:
            el[2].append(data)


def _read(html: str) -> _Reader:
    r = _Reader()
    r.feed(html or "")
    r.close()
    return r


def words(s: str) -> int:
    return len(_WORD.findall(s or ""))


def _els(r: _Reader, attr: str) -> list:
    return [el for el in r.elements if attr in el[1]]


def _text_of(el) -> str:
    return " ".join("".join(el[2]).split())


def estimate_height_px(html: str) -> int:
    """A rough 390 px height from text length (recorded on the send row; the Playwright test measures the real one)."""
    r = _read(html)
    blocks = [_text_of(el) for el in r.elements] or [" ".join(r.text)]
    lines = sum(max(1, -(-len(b) // _EST_CHARS_PER_LINE)) for b in blocks if b)
    return int(_EST_FRAME_PX + lines * _EST_LINE_PX + len(blocks) * _EST_BLOCK_PX)


def measure(html: str, text: str = "") -> dict:
    """The send row's attention numbers (owner ruling §9): words outside alerts, reading seconds, counts."""
    r = _read(html)
    w = words(" ".join(r.text))
    leads = _els(r, "data-lead")
    return {
        "words": w,
        "alert_words": words(" ".join(r.alert_text)),
        "read_seconds_est": int(round(w * 60 / bc.READING_WPM)),
        "n_metrics": len(_els(r, "data-metric")),
        "n_recs": len(_els(r, "data-rec")),
        "n_critical_alerts": len(_els(r, "data-alert")),
        "n_unknown": len(_els(r, "data-unknown")),
        "quiet_day": bool(leads and leads[0][1].get("data-lead") == "quiet"),
        "height_est_px": estimate_height_px(html),
        "text_words": _text_words(text),
    }


def _text_words(text: str) -> int:
    return words("\n".join(x for x in (text or "").splitlines() if not x.startswith("ALERT ")))


def check(html: str, text: str, *, persona_names: tuple = (), pending_inputs: tuple = ()) -> list:
    """Every violation of the compact budget in one rendered email (html + text)."""
    out: list = []
    r = _read(html)
    visible = " ".join(" ".join(r.text).split())
    m = measure(html, text)

    def v(code, detail):
        out.append(Violation(code, detail))

    if m["words"] > bc.WORD_CEILING:
        v("words_over", f"{m['words']} words outside alerts > {bc.WORD_CEILING}")
    if not (text or "").strip():
        v("text_missing", "no plain-text part")
    elif m["text_words"] > bc.WORD_CEILING:
        v("text_words_over", f"text part {m['text_words']} words > {bc.WORD_CEILING}")
    if m["n_metrics"] > bc.METRIC_CEILING:
        v("metrics_over", f"{m['n_metrics']} metric rows > {bc.METRIC_CEILING}")
    if m["n_recs"] > bc.REC_CEILING:
        v("recs_over", f"{m['n_recs']} recommendations > {bc.REC_CEILING}")
    if not persona_names:
        v("voice_unchecked", "the persona registry could not be read")
    for name in persona_names:
        if bc.names_a_persona(visible + "\n" + (text or ""), (name,)):
            v("voice", f"names {name!r}")
    for marker in LEGACY_MARKERS:
        if marker in (html or ""):
            v("legacy_section", f"carries {marker!r}")
    links = _els(r, "data-detail-link")
    if len(links) != 1 or "/data/day/" not in links[0][1].get("href", ""):
        v("detail_link", f"{len(links)} detail links (exactly one /data/day/ link expected)")
    if pending_inputs and bc.MISSED_RE.search(visible + "\n" + (text or "")):
        v("missed_wording", "absence worded as missed behaviour while " + ",".join(pending_inputs) + " is pending")
    leads = _els(r, "data-lead")
    unknowns = _els(r, "data-unknown")
    trends = _els(r, "data-trend")
    if (pending_inputs or unknowns or _els(r, "data-alert") or trends) and CATEGORICAL_RE.search(visible):
        v("categorical_with_unknowns", "a categorical 'nothing' while data is unknown or an alert stands")
    clear = bc.CLEARANCE_RE.search(visible + "\n" + (text or ""))
    if clear:
        v("clearance", "a score read as clearance: " + clear.group(0))
    seen: dict = {}
    for el in _els(r, "data-q"):
        q, val = el[1]["data-q"], el[1].get("data-v", "")
        if q in seen and seen[q] != val:
            v("contradiction", f"{q} shown as {seen[q]} and {val}")
        seen.setdefault(q, val)
    if (
        leads
        and leads[0][1].get("data-lead") == "quiet"
        and (_els(r, "data-changed") or _els(r, "data-rec") or unknowns or _els(r, "data-alert") or trends)
    ):
        v("contradiction", "the quiet lead sits above a change, a recommendation, an unknown or an alert")
    # #6241 §3: an open multi-week trend or concern may not sit under a headline that ignores it
    open_items = [el for el in trends if el[1].get("data-trend") in ("trend", "concern")]
    lead_kind = leads[0][1].get("data-lead") if leads else ""
    if open_items and lead_kind not in ("alert", "decision", "trend"):
        v("trend_dismissed", "an open multi-week item under a '" + str(lead_kind) + "' lead")
    for el in _els(r, "data-metric"):
        src, as_of = el[1].get("data-source", ""), el[1].get("data-as-of", "")
        if not src or not as_of or src.split(" and ")[0] not in _text_of(el):
            v("attribution", f"metric {el[1]['data-metric']!r} lacks a visible source or its day")
    for el in _els(r, "data-rec"):
        if el[1].get("data-status") == "REPEAT" and "data-changed-because" not in el[1]:
            v("unchanged_repeat", f"repeat {el[1].get('data-rec-key')!r} shown with no change")
    if m["quiet_day"] and not (bc.QUIET_WORDS[0] <= m["words"] <= bc.QUIET_WORDS[1]):
        v("quiet_length", f"a quiet day of {m['words']} words (50–100 expected)")
    if m["height_est_px"] > HEIGHT_BUDGET_PX:
        v("height_est", f"estimated {m['height_est_px']} px at 390 px > {HEIGHT_BUDGET_PX}")
    return out
