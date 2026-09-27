"""
chronicle_schema.py — the chronicle installment's guaranteed output shape (#1385
AC4, epic #1080).

Bedrock Structured Outputs (GA on Bedrock, same wire format as the direct API's
``output_config.format``) lets the model's output be constrained to a JSON schema
so the shape is schema-guaranteed rather than parse-and-pray. The chronicle's
installment envelope — title, the three stat-line numbers, and the markdown body —
is the fragile part today (a hand-rolled regex in ``parse_installment``); the
prose itself stays markdown, it just rides inside the ``body_markdown`` field so
the envelope can't come out malformed.

Structured-Outputs JSON-schema limits (per the claude-api reference): every object
needs ``additionalProperties: false`` + ``required``; string length / numeric-range
constraints are NOT supported, so the schema is types + required only.

The grounding gate (ADR-104) still runs on the serialized JSON text — every number
and date the model writes appears in that text exactly as in the markdown form, so
widening to structured output does not weaken the fabrication gate.
"""

import re

# The response schema handed to Bedrock Structured Outputs (output_config.format).
INSTALLMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Elena's editorial title for the week (the quoted first line today).
        "title": {"type": "string"},
        # The three numbers of the stat line: [Weight: X lbs | Week Grade: avg X | T0 Streak: X days]
        "weight_lbs": {"type": "number"},
        "week_grade": {"type": "number"},
        "t0_streak_days": {"type": "integer"},
        # The installment body — clean markdown prose (~1,200-1,800 words).
        "body_markdown": {"type": "string"},
    },
    "required": ["title", "weight_lbs", "week_grade", "t0_streak_days", "body_markdown"],
}

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    # bool is a subclass of int — exclude it so a stray True can't pass as a number.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def validate_installment(obj, schema: dict = INSTALLMENT_SCHEMA) -> list:
    """Deterministic ($0, no AI) validation of a structured installment object
    against `schema`. Returns a list of human-readable error strings — [] means the
    object satisfies the schema (all required keys present, correctly typed, and no
    extra keys when additionalProperties is false).

    This is the safety net that makes Structured Outputs load-bearing: even if a
    future model or a hand-built fallback produces the envelope, a malformed shape is
    caught here rather than silently mis-parsed downstream.
    """
    errors: list = []
    if not isinstance(obj, dict):
        return [f"expected object, got {type(obj).__name__}"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in obj:
            errors.append(f"missing required field: {key!r}")
    for key, val in obj.items():
        if key not in props:
            if schema.get("additionalProperties") is False:
                errors.append(f"unexpected field: {key!r}")
            continue
        expected = props[key].get("type")
        check = _TYPE_CHECKS.get(expected)
        if check and not check(val):
            errors.append(f"field {key!r}: expected {expected}, got {type(val).__name__}")
    return errors


def parse_stats_line(stats_line: str) -> dict:
    """Extract the three stat numbers from the installment stat line
    ``[Weight: X lbs | Week Grade: avg X | T0 Streak: X days]``. Returns a dict with
    ``weight_lbs`` / ``week_grade`` / ``t0_streak_days`` (a key is absent — and thus
    fails the schema's `required` — when its number can't be found). This is the
    fragile parse; validating its output against INSTALLMENT_SCHEMA is what turns
    parse-and-pray into a caught error."""
    import re

    out: dict = {}
    text = stats_line or ""
    m = re.search(r"Weight:\s*([\d.]+)", text)
    if m:
        out["weight_lbs"] = float(m.group(1))
    m = re.search(r"Week Grade:\s*(?:avg\s*)?([\d.]+)", text)
    if m:
        out["week_grade"] = float(m.group(1))
    m = re.search(r"Streak:\s*(\d+)", text)
    if m:
        out["t0_streak_days"] = int(m.group(1))
    return out


def installment_from_stats(title: str, stats: dict, body_markdown: str) -> dict:
    """Assemble a schema-shaped installment dict from parsed pieces — the bridge for
    the fallback (non-structured) path so both paths produce the same validated
    envelope."""
    return {
        "title": title,
        "weight_lbs": stats.get("weight_lbs"),
        "week_grade": stats.get("week_grade"),
        "t0_streak_days": stats.get("t0_streak_days"),
        "body_markdown": body_markdown,
    }


# ── #4191: the envelope is a wire format, never prose ────────────────────────────
#
# The model returns the installment as an ENVELOPE: a quoted title line, a blank line,
# the bracketed machine header ``[Weight: X lbs | Week Grade: avg X | T0 Streak: X days]``,
# a blank line, then the body. ``parse_installment`` peels the header into the
# ``stats_line`` field at write time, and the stored ``content_markdown`` keeps the WHOLE
# envelope — the raw artifact that continuity, the recap, the podcast, the recall index
# and six deploy scripts all read in that shape. Anything that shows ``content_markdown``
# to a READER goes through ``body_markdown`` first: the manifest excerpt, the RSS
# description, the recall snippet. One derivation, here, shared by the Lambda writer
# (emails/chronicle_render.py), the restart re-renderer (deploy/restart_leadin_pages.py)
# and the site build (scripts/v4_build_rss.py) — never a second copy of the strip.
# site/assets/js/chronicle_text.js is the reader-side twin (cleanExcerpt / statsRow);
# its literals are pinned against these in tests/test_chronicle_post_template.py.

# A whole line in brackets — the machine header as the model writes it.
STAT_LINE_RE = re.compile(r"^\s*\[[^\]]*\]\s*$")
# The header flowed into whitespace-collapsed text (a recall snippet); a storage cap may
# have cut it before the closing bracket, so an unterminated tail counts too.
_STAT_LINE_INLINE_RE = re.compile(r"\[[^\]]*Weight:[^\]]*(?:\]|$)")
_QUOTED_TITLE_RE = re.compile(r"^\s*[“\"]([^”\"]+)[”\"]\s*$")
# A recall snippet's head: the indexed text is ``title + subtitle + envelope``, so it
# opens ``The X Week N of The Measured Life "The X"`` before the first sentence.
_SNIPPET_HEAD_RE = re.compile(r"^\s*(?P<t>.+?)\s+Week\s+\d+\s+of\s+The\s+Measured\s+Life\s+[“\"](?P=t)[”\"]\s*")

_WEIGHT_SEG_RE = re.compile(r"^Weight:\s*([\d.]+)\s*lbs?$", re.I)
_GRADE_SEG_RE = re.compile(r"^Week Grade:\s*avg\s*([\d.]+)$", re.I)
_STREAK_SEG_RE = re.compile(r"^T0 Streak:", re.I)


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip().strip('"“”').lower()


def body_markdown(content_markdown, title: str = "") -> str:
    """The prose of a stored installment: ``content_markdown`` minus its envelope head.

    Strips, from the HEAD only (a bracketed line deep in the body is prose and stays):
      * a quoted first line when it IS the title (or when a bracketed stat line follows
        it — the envelope shape, title unknown), or an old assembled ``# heading``;
      * then any bracketed stat line, ``*By …*`` byline or ``---`` rule that follows.
    A quoted first line that is NOT the title and has no header after it is prose.
    """
    lines = str(content_markdown or "").strip().split("\n")
    n = len(lines)

    def _next_nonblank(j: int) -> int:
        while j < n and not lines[j].strip():
            j += 1
        return j

    i = _next_nonblank(0)
    if i < n:
        first = lines[i].strip()
        nxt = _next_nonblank(i + 1)
        header_follows = nxt < n and (STAT_LINE_RE.match(lines[nxt]) is not None or lines[nxt].strip().startswith("*By "))
        m = _QUOTED_TITLE_RE.match(first)
        if first.startswith("# "):
            i += 1
        elif m and ((title and _norm(m.group(1)) == _norm(title)) or header_follows):
            i += 1
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
        elif STAT_LINE_RE.match(s) or s.startswith("*By ") or s == "---":
            i += 1
        else:
            break
    return "\n".join(lines[i:]).strip()


def stats_row_text(stats_line) -> str:
    """``Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days`` →
    ``315.0 lb that week · the engine's week score 74``.

    The reader-facing form of the machine header, segment by segment: the weight and the
    week score read as words, the builder-only ``T0 Streak`` segment is dropped, and any
    segment this does not recognise is kept verbatim so a new one is never silently lost
    (a pre-genesis dek's "Prologue — …" stamp rides through). Byte-for-byte the twin of
    ``statsRow`` in site/assets/js/chronicle_text.js — change both or neither.
    """
    raw = re.sub(r"^\[|\]$", "", str(stats_line or "").strip())
    out: list = []
    for seg in (s.strip() for s in raw.split("|")):
        if not seg:
            continue
        m = _WEIGHT_SEG_RE.match(seg)
        if m:
            out.append(f"{m.group(1)} lb that week")
            continue
        m = _GRADE_SEG_RE.match(seg)
        if m:
            out.append(f"the engine's week score {m.group(1)}")
            continue
        if _STREAK_SEG_RE.match(seg):
            continue
        out.append(seg)
    return " · ".join(out)


def clean_snippet(text) -> str:
    """A recall snippet fit to quote: the flowed envelope head (``title subtitle "title"``)
    and any bracketed stat line — terminated or cut by the storage cap — removed, the
    whitespace collapsed. Applied at RENDER time so the rows already indexed from the
    envelope read clean without a re-embed (the embedded text itself is untouched)."""
    s = " ".join(str(text or "").split())
    s = _STAT_LINE_INLINE_RE.sub(" ", s)
    s = _SNIPPET_HEAD_RE.sub("", s)
    return " ".join(s.split()).strip()
