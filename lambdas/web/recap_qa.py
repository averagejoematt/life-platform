"""recap_qa.py — the check every card passes AFTER it is drawn and BEFORE it is stored (#3741).

THE QUESTION THAT PRODUCED THIS

The owner, 2026-09-19: *"is there a QA/validation step for each daily image to make sure
its not got bugs and is accurate?"* The honest answer was no. The pipeline screened the
card's INPUT (the privacy gate), pinned the null rules in code (a template with nothing to
say draws nothing), and tested the layouts on fixtures — and not one of those looks at the
frame that was actually drawn. The first instrumented pass over the live set found three
strings running off the right edge of the canvas that thirteen days of green tests and a
contact-sheet review had missed, because a contact sheet is 360 px wide and the eye fills
in the edge.

WHAT IT CHECKS, AND WHAT IT CANNOT

The layouts draw through a recording proxy (`RecordingDraw`) that remembers every string
with the bounding box Pillow measured for it. `audit()` then asks, of the drawn frame:

  HARD — the card is held, never stored, never sent:
    clipped     a string's box crosses the canvas edge — the reader sees half a word
    below-floor a string sits under the footer band — two things drawn on top of each other
    overlap     two strings share more than a sliver of pixels
    glyph       a character outside the set the bundled fonts carry — it renders as a box
    placeholder `None`, `nan`, `Decimal(` — a formatter drew its own failure

  SOFT — recorded on the row, the card ships:
    gutter      a string's box crosses the content margin but not the canvas edge. Two
                marks do this by design (component-bar scores sit in the gutter; the
                sparkline's last-value label hugs the right edge) and the note is how a
                reviewer sees a new one appear.

What it cannot do is judge ACCURACY — whether "−12.2 lb" is the right number. That is
ADR-104's domain and it is enforced upstream: every number on a card is formatted from a
`DayFacts` field the compute cron wrote, and the captions are assembled from the same
fields (the tests assert that). A wrong number here is a wrong number in the table, which
this gate cannot see and should not pretend to. The semantic pass — a vision model reading
the PNG — is the site's `visual_ai_qa` shape and is deliberately NOT wired here yet: it
costs a Bedrock call per card and the deterministic layer had to exist first (ADR-105).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Bounding boxes closer than this to the frame are "clipped"; boxes past the content
#: margin by more than this are "gutter". Pillow's textbbox includes a pixel of bearing.
EDGE_SLACK = 2
#: Between these two lines nothing may draw: the layouts' floor (recap_layouts.FLOOR_Y)
#: and the top of the footer band (recap_layouts.FOOTER_Y, less a few px of bearing).
#: Kept as literals here, not imported, so a layout change cannot move the goalposts.
FLOOR_Y = 1262
FOOTER_TOP_Y = 1290
#: Two strings may touch; more than this much shared area is an overlap.
OVERLAP_PX = 4

#: What a formatter draws when it was handed nothing — the ADR-104 failure, as text.
_PLACEHOLDER = re.compile(r"\bNone\b|\bnan\b|\bnull\b|Decimal\(|[{}]")
#: The characters the bundled Fraunces / Plex Mono subsets carry beyond ASCII: the
#: typographic marks the layouts use on purpose. Anything else outside printable ASCII
#: is a box on the card.
_ALLOWED_NON_ASCII = set("·—–…°×’‘“”−")
#: Fixed strings a layout draws that are NOT values and must not trip the placeholder
#: rule: the exercise-list bullet.
_LITERAL_MARKS = {"—"}


@dataclass
class DrawnString:
    text: str
    bbox: tuple[int, int, int, int]
    font: str = ""


class RecordingDraw:
    """An ImageDraw proxy that remembers every string it is asked to draw, with its box."""

    def __init__(self, draw):
        self._draw = draw
        self.records: list[DrawnString] = []

    def text(self, xy, text, *args, **kwargs):
        if text:
            try:
                box = self._draw.textbbox(xy, str(text), font=kwargs.get("font"), anchor=kwargs.get("anchor"))
                fp = getattr(kwargs.get("font"), "path", "") or ""
                self.records.append(DrawnString(str(text), tuple(int(round(v)) for v in box), fp))
            except Exception:  # noqa: BLE001 — a default font cannot measure; record the text alone
                self.records.append(DrawnString(str(text), (0, 0, 0, 0)))
        return self._draw.text(xy, text, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._draw, name)


@dataclass
class QaResult:
    hard: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)
    strings: int = 0

    @property
    def may_store(self) -> bool:
        return not self.hard

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "cleared" if self.may_store else "held", "strings": self.strings}
        if self.hard:
            out["hard"] = self.hard[:12]
        if self.soft:
            out["soft"] = self.soft[:12]
        return out


def _bad_glyphs(text: str) -> list[str]:
    out = []
    for c in text:
        if c.isascii() and (c.isprintable() or c == "\n"):
            continue
        if c in _ALLOWED_NON_ASCII:
            continue
        # Accented Latin letters are in the subsets; symbols, emoji and the like are not.
        if unicodedata.category(c).startswith("L") and ord(c) < 0x0250:
            continue
        out.append(c)
    return out


def audit(
    records: list[DrawnString], *, size: tuple[int, int], margin: int, floor_y: int = FLOOR_Y, footer_y: int = FOOTER_TOP_Y
) -> QaResult:
    """Judge one drawn frame. Pure: the same records always give the same verdict."""
    w, h = size
    res = QaResult(strings=len(records))
    for r in records:
        x0, y0, x1, y1 = r.bbox
        t = r.text
        if r.bbox == (0, 0, 0, 0):
            continue
        if x1 > w - EDGE_SLACK or x0 < EDGE_SLACK or y1 > h - EDGE_SLACK:
            res.hard.append(f"clipped [{x0},{x1}] {t!r}")
        elif x1 > w - margin + EDGE_SLACK or x0 < margin - EDGE_SLACK:
            res.soft.append(f"gutter [{x0},{x1}] {t!r}")
        if floor_y < y0 < footer_y:
            # Starts under the floor but above the footer band: two things in one place.
            res.hard.append(f"below-floor y={y0} {t!r}")
        glyphs = _bad_glyphs(t)
        if glyphs:
            res.hard.append(f"glyph {''.join(sorted(set(glyphs)))!r} in {t!r}")
        if t not in _LITERAL_MARKS and _PLACEHOLDER.search(t):
            res.hard.append(f"placeholder {t!r}")
    boxes = [r.bbox for r in records if r.bbox != (0, 0, 0, 0)]
    texts = [r.text for r in records if r.bbox != (0, 0, 0, 0)]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix > OVERLAP_PX and iy > OVERLAP_PX:
                res.hard.append(f"overlap {texts[i]!r} × {texts[j]!r} ({ix}×{iy}px)")
    return res


def audit_image(img, *, margin: int) -> QaResult:
    """Audit a card rendered through `recap_layouts._canvas()` — its records ride on `img.info`."""
    records = img.info.get("recap_strings") or []
    return audit(list(records), size=img.size, margin=margin)
