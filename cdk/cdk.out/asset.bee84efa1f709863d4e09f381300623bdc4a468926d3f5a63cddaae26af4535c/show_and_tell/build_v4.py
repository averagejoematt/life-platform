#!/usr/bin/env python3
"""
Life Platform — Corporate Show & Tell  v4
Fully restructured:
  PART ONE  — The Solution  (what it does, why it matters, practical analysis)
  PART TWO  — The Build     (technical architecture, AWS, security, ops)

Key fixes from v3:
  - Removed "14 months" — project started Feb 22 2026 (~80 sessions)
  - Architecture rendered as matplotlib PNG (visually verified) — no more canvas guesswork
  - New section: "Why 100+ Tools" — explains cross-source insight architecture
  - New section: "What You Can't Get from the Apps Alone" — solution framing
  - Removed all "production-grade" phrasing
  - Removed expert quotes section
  - Removed MCP explainer, Google Calendar, demo pipeline appendix
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Image as RLImage
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor
from PIL import Image as PILImage
import os

# ── Colours ──────────────────────────────────────────────────────────────────
NAVY      = HexColor("#0D1B2A")
NAVY2     = HexColor("#1B2A3B")
ACCENT    = HexColor("#2DD4BF")
ACCENT2   = HexColor("#6366F1")
GOLD      = HexColor("#F59E0B")
WHITE     = HexColor("#FFFFFF")
GREY_L    = HexColor("#F1F5F9")
GREY_M    = HexColor("#94A3B8")
GREY_D    = HexColor("#334155")
RED_S     = HexColor("#F87171")
GREEN_S   = HexColor("#4ADE80")
ORANGE    = HexColor("#FB923C")
PURPLE    = HexColor("#A78BFA")

IMG_DIR = "/home/claude/demo_processed"
W, H = letter


# ── Screenshot helper ─────────────────────────────────────────────────────────
def screenshot(name, max_w, max_h, caption=None):
    path = os.path.join(IMG_DIR, f"{name}.png")
    if not os.path.exists(path):
        return [Paragraph(f"[{name}]",
                ParagraphStyle("m", fontSize=8, textColor=GREY_M))]
    img = PILImage.open(path)
    iw, ih = img.size
    ratio = min(max_w / iw, max_h / ih)
    dw, dh = iw * ratio, ih * ratio

    class SS(Flowable):
        def wrap(self, aw, ah): return dw + 8, dh + 8
        def draw(self):
            c = self.canv
            c.setStrokeColor(NAVY2); c.setLineWidth(1)
            c.roundRect(2, 2, dw + 4, dh + 4, 4, stroke=1, fill=0)
            c.drawImage(path, 4, 4, dw, dh, preserveAspectRatio=True)

    els = [SS()]
    if caption:
        st = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=8,
                            textColor=GREY_M, leading=11, spaceAfter=4,
                            alignment=TA_CENTER)
        els.append(Paragraph(caption, st))
    return els


def two_col(name_a, cap_a, name_b, cap_b, max_w=3.3*inch, max_h=2.8*inch):
    l = screenshot(name_a, max_w, max_h, cap_a)
    r = screenshot(name_b, max_w, max_h, cap_b)
    t = Table([[l, r]], colWidths=[3.55*inch, 3.55*inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 2),
        ("RIGHTPADDING", (0,0), (-1,-1), 2),
    ]))
    return t


# ── Styles ────────────────────────────────────────────────────────────────────
def S():
    def ps(name, **kw): return ParagraphStyle(name, **kw)
    return {
        "title":    ps("title",  fontName="Helvetica-Bold",    fontSize=34, textColor=WHITE,  leading=42, alignment=TA_CENTER),
        "subtitle": ps("sub",    fontName="Helvetica",         fontSize=14, textColor=ACCENT, leading=20, alignment=TA_CENTER),
        "meta":     ps("meta",   fontName="Helvetica",         fontSize=10, textColor=GREY_M, leading=16, alignment=TA_CENTER),
        "h2":       ps("h2",     fontName="Helvetica-Bold",    fontSize=15, textColor=NAVY,   leading=20, spaceBefore=8, spaceAfter=5),
        "h3":       ps("h3",     fontName="Helvetica-Bold",    fontSize=12, textColor=NAVY2,  leading=16, spaceBefore=6, spaceAfter=3),
        "h3a":      ps("h3a",    fontName="Helvetica-Bold",    fontSize=12, textColor=ACCENT2,leading=16, spaceBefore=6, spaceAfter=3),
        "body":     ps("body",   fontName="Helvetica",         fontSize=9.5,textColor=GREY_D, leading=14, spaceAfter=4),
        "sm":       ps("sm",     fontName="Helvetica",         fontSize=8.5,textColor=GREY_D, leading=13, spaceAfter=3),
        "bul":      ps("bul",    fontName="Helvetica",         fontSize=9,  textColor=GREY_D, leading=14, spaceAfter=3,  leftIndent=14, bulletText="•"),
        "bulsm":    ps("bulsm",  fontName="Helvetica",         fontSize=8.5,textColor=GREY_D, leading=13, spaceAfter=2,  leftIndent=12, bulletText="–"),
        "cap":      ps("cap",    fontName="Helvetica-Oblique", fontSize=8.5,textColor=GREY_M, leading=12, spaceAfter=4),
        "disc":     ps("disc",   fontName="Helvetica-Oblique", fontSize=8,  textColor=RED_S,  alignment=TA_CENTER),
        "part":     ps("part",   fontName="Helvetica-Bold",    fontSize=11, textColor=ACCENT, leading=16, alignment=TA_CENTER),
    }


def th(bg=NAVY2, fg=WHITE):
    return [
        ("BACKGROUND",    (0,0), (-1,0),  bg),
        ("TEXTCOLOR",     (0,0), (-1,0),  fg),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0),  8.5),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("GRID",          (0,0), (-1,-1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, GREY_L]),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,1), (-1,-1), 8),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]


def para_table(data, col_widths, bg=NAVY2, fg=WHITE):
    """Build a Table where every cell is a Paragraph so text wraps within columns."""
    hdr_s = ParagraphStyle("_pth", fontName="Helvetica-Bold", fontSize=8.5,
                           textColor=fg, leading=12)
    cel_s = ParagraphStyle("_ptd", fontName="Helvetica", fontSize=8,
                           textColor=GREY_D, leading=12)
    rows = []
    for r_idx, row in enumerate(data):
        st = hdr_s if r_idx == 0 else cel_s
        rows.append([Paragraph(str(cell), st) for cell in row])
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  bg),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("GRID",          (0,0), (-1,-1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, GREY_L]),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    return t


def pt(text, style, bold=False):
    """Wrap a string in a Paragraph so ReportLab wraps it within column bounds."""
    if bold:
        text = f"<b>{text}</b>"
    return Paragraph(text, style)


def para_rows(data, hs, bs):
    """Convert a list-of-lists table where row 0 is headers, rest are body rows,
    wrapping every cell in a Paragraph with the appropriate style."""
    out = []
    for i, row in enumerate(data):
        s = hs if i == 0 else bs
        out.append([pt(str(cell), s) for cell in row])
    return out


# Module-level cell paragraph styles — created once, used by all para_rows calls
_CS_H = ParagraphStyle("csh", fontName="Helvetica-Bold",  fontSize=8.5, textColor=WHITE,  leading=12, spaceAfter=0)
_CS_B = ParagraphStyle("csb", fontName="Helvetica",       fontSize=8,   textColor=GREY_D, leading=12, spaceAfter=0)
_CS_S = ParagraphStyle("css", fontName="Helvetica",       fontSize=7.5, textColor=GREY_D, leading=11, spaceAfter=0)

def PR(data):  return para_rows(data, _CS_H, _CS_B)   # normal body
def PRS(data): return para_rows(data, _CS_H, _CS_S)   # small body


def on_page(c, doc):
    if doc.page == 1: return
    c.saveState()
    c.setStrokeColor(GREY_M); c.setLineWidth(0.4)
    c.line(0.75*inch, 0.55*inch, W - 0.75*inch, 0.55*inch)
    c.setFont("Helvetica", 7.5); c.setFillColor(GREY_M)
    c.drawString(0.75*inch, 0.35*inch, "Life Platform — Health Intelligence System  |  INTERNAL")
    c.drawRightString(W - 0.75*inch, 0.35*inch, f"Page {doc.page}")
    c.restoreState()


class Banner(Flowable):
    def __init__(self, title, sub="", bg=NAVY2, acc=ACCENT, h=48):
        Flowable.__init__(self)
        self.title = title; self.sub = sub
        self.bg = bg; self.acc = acc; self.h = h
    def wrap(self, aw, ah): self.width = aw; return aw, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(self.bg); c.roundRect(0, 0, self.width, self.h, 8, stroke=0, fill=1)
        c.setFillColor(self.acc); c.roundRect(0, 0, 5, self.h, 2, stroke=0, fill=1)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 13)
        c.drawString(16, self.h - 26, self.title)
        if self.sub:
            c.setFont("Helvetica", 8.5); c.setFillColor(GREY_M)
            c.drawString(16, 10, self.sub)


class PartDivider(Flowable):
    def __init__(self, num, title, desc, color=ACCENT):
        Flowable.__init__(self)
        self.num = num; self.title = title
        self.desc = desc; self.color = color
    def wrap(self, aw, ah): self.aw = aw; return aw, 120
    def draw(self):
        c = self.canv
        c.setFillColor(NAVY); c.roundRect(0, 0, self.aw, 116, 12, stroke=0, fill=1)
        c.setFillColor(self.color)
        c.roundRect(0, 0, 6, 116, 3, stroke=0, fill=1)
        c.setFillColor(self.color); c.setFont("Helvetica", 10)
        c.drawCentredString(self.aw/2, 90, self.num)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(self.aw/2, 62, self.title)
        c.setFillColor(GREY_M); c.setFont("Helvetica", 9)
        c.drawCentredString(self.aw/2, 38, self.desc)


# ══════════════════════════════════════════════════════════════════════════════
# COVER
# ══════════════════════════════════════════════════════════════════════════════
def cover(s):
    els = []

    class CoverBG(Flowable):
        def wrap(self, aw, ah): return aw, 3.4*inch
        def draw(self):
            c = self.canv
            c.setFillColor(NAVY)
            c.rect(-0.75*inch, -0.15*inch, W, 3.55*inch, stroke=0, fill=1)
            c.setFillColor(ACCENT)
            c.rect(-0.75*inch, -0.15*inch, 0.16*inch, 3.55*inch, stroke=0, fill=1)

    class KPIRow(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 86
        def draw(self):
            c = self.canv
            stats = [
                ("30",     "Lambdas",       ACCENT2),
                ("124",    "MCP Tools",     ACCENT),
                ("19",     "Data Sources",  GOLD),
                ("9",      "Emails / Week", GREEN_S),
                ("~$3/mo", "AWS Cost",      ORANGE),
                ("v2.80",  "Version",       PURPLE),
            ]
            bw = (self.aw - 5*6) / 6
            x = 0
            for val, lbl, col in stats:
                c.setFillColor(NAVY2); c.roundRect(x, 8, bw, 72, 8, stroke=0, fill=1)
                c.setFillColor(col); c.setFont("Helvetica-Bold", 17)
                c.drawCentredString(x + bw/2, 48, val)
                c.setFillColor(GREY_M); c.setFont("Helvetica", 7.5)
                c.drawCentredString(x + bw/2, 22, lbl.upper())
                x += bw + 6

    els.append(Spacer(1, 0.5*inch))
    els.append(CoverBG())
    els.append(Spacer(1, -3.2*inch))
    els.append(Paragraph("Life Platform", s["title"]))
    els.append(Spacer(1, 0.08*inch))
    els.append(Paragraph("Personal Health Intelligence System", s["subtitle"]))
    els.append(Spacer(1, 0.18*inch))
    els.append(Paragraph(
        "19 health apps. All excellent. None of them talking to each other. So I built the layer that joins them.",
        ParagraphStyle("hook", fontName="Helvetica-Oblique", fontSize=11,
                       textColor=ACCENT, leading=17, alignment=TA_CENTER)))
    els.append(Spacer(1, 1.9*inch))
    els.append(KPIRow())
    els.append(Spacer(1, 0.28*inch))
    els.append(HRFlowable(width="100%", thickness=0.5, color=GREY_M))
    els.append(Spacer(1, 0.1*inch))
    els.append(Paragraph("M. Walker  ·  2026  ·  Built across ~80 AI-assisted development sessions", s["meta"]))
    els.append(Paragraph("INTERNAL USE — Sensitive data obfuscated throughout", s["disc"]))
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# TABLE OF CONTENTS
# ══════════════════════════════════════════════════════════════════════════════
def toc(s):
    els = []
    els.append(Banner("Contents"))
    els.append(Spacer(1, 0.15*inch))

    items = [
        ("—",     "The Story",                       "Origin · the problem · why custom-built · dual-purpose", None),
        ("PART ONE", "THE SOLUTION", None, ACCENT),
        ("01", "A Week in the Life",              "Monday to Sunday — how everything connects", None),
        ("02", "Why Apps Aren't Enough",           "The problem with siloed data", None),
        ("03", "What No Single App Can Tell You",  "Cross-source analysis you can't get elsewhere", None),
        ("04", "Why 124 Tools",                    "The architecture of inquiry", None),
        ("05", "Features in Action",               "Screenshots: emails, dashboard, blog, gamification", None),
        ("PART TWO", "THE BUILD", None, PURPLE),
        ("06", "System Architecture",              "Full AWS infrastructure diagram", None),
        ("07", "AWS Components",                   "Lambdas, DynamoDB, S3, CloudFront, SES", None),
        ("08", "Security & Ops",                   "IAM, secrets, auth, deployment, data governance", None),
        ("09", "Data Model",                       "Single-table DynamoDB — 21 sources", None),
        ("10", "AI Integration",                   "Board of Directors · MCP · 124 tools · OAuth 2.1", None),
        ("11", "Resiliency",                       "DLQs, alarms, gap-aware backfill", None),
        ("12", "Documentation System",             "Changelog · handovers · incident log · RCA", None),
        ("13", "Roadmap",                          "What's next", None),
        ("14", "Key Learnings",                    "Patterns that generalise — personal and enterprise", None),
    ]

    data = []
    for row in items:
        n, t = row[0], row[1]
        d = row[2]
        col = row[3] if len(row) > 3 else None
        if d is None:  # Part header
            data.append([
                Paragraph(f'<font color="{col.hexval()}"><b>{n} — {t}</b></font>', s["sm"]),
                Paragraph("", s["sm"]),
            ])
        elif n == "—":  # Story intro — no section number
            data.append([
                Paragraph(f'<font color="#2DD4BF"><b>{t}</b></font>', s["body"]),
                Paragraph(d, s["sm"]),
            ])
        else:
            data.append([
                Paragraph(f'<font color="#2DD4BF"><b>{n}</b></font>  <b>{t}</b>', s["body"]),
                Paragraph(d, s["sm"]),
            ])

    t = Table(data, colWidths=[2.8*inch, 4.3*inch])
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [WHITE, GREY_L]),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E2E8F0")),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
    ]))
    els.append(t)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# THE STORY — Origin, problem, dual-purpose hypothesis
# ══════════════════════════════════════════════════════════════════════════════
def the_story(s):
    els = []
    els.append(Banner("The Story", "Why this exists — and why it matters beyond personal health", acc=ACCENT))
    els.append(Spacer(1, 0.12*inch))

    # Left column: personal origin
    left = []
    left.append(Paragraph("The Problem", ParagraphStyle("h3c", fontName="Helvetica-Bold", fontSize=12,
        textColor=ACCENT, leading=16, spaceAfter=4)))
    left.append(Paragraph(
        "I like data. Over time I had accumulated 19 health and wellness apps — "
        "Whoop, Eight Sleep, CGM, Garmin, Withings, MacroFactor, Notion, Habitify, and more. "
        "Each one excellent at its job. None of them talking to each other.",
        s["sm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph(
        "The problem wasn't lack of data — it was lack of synthesis. "
        "<b>What does all of this actually mean, together?</b> "
        "Each app reported its number in isolation. "
        "The real insights — the ones that cross sources, apply personal baselines, "
        "and produce actionable answers — lived in the gaps between them. "
        "No tool on the market filled those gaps. So I built one.",
        s["sm"]))
    left.append(Spacer(1, 0.08*inch))
    left.append(Paragraph("Why Not Buy a Solution?", ParagraphStyle("h3c2", fontName="Helvetica-Bold", fontSize=12,
        textColor=GOLD, leading=16, spaceAfter=4)))
    left.append(Paragraph(
        "No existing platform crosses all 19 sources, applies personal baselines, "
        "runs custom algorithms (PhenoAge from my actual blood draws, TSB from my "
        "actual training load), and delivers results as AI-coached narrative. "
        "The closest consumer tools integrate 3–4 sources at best. "
        "The closest enterprise tools cost $50k+/year and aren't designed for individuals.",
        s["sm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph(
        "The only path was to build it. And building it from scratch meant every "
        "architectural decision, every AI pattern, every ops failure was <i>mine to own</i>.",
        s["sm"]))

    # Right column: dual-purpose / enterprise angle
    right = []

    class DualBox(Flowable):
        def __init__(self, aw):
            Flowable.__init__(self)
            self._aw = aw
        def wrap(self, aw, ah): self.aw = aw; return aw, 195
        def draw(self):
            c = self.canv
            c.setFillColor(NAVY); c.roundRect(0, 0, self.aw, 191, 8, stroke=0, fill=1)
            c.setFillColor(PURPLE); c.roundRect(0, 0, 5, 191, 3, stroke=0, fill=1)
            c.setFillColor(PURPLE); c.setFont("Helvetica-Bold", 9)
            c.drawString(14, 173, "DUAL PURPOSE")
            c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 12)
            c.drawString(14, 153, "Personal lab.")
            c.setFont("Helvetica", 9); c.setFillColor(GREY_M)
            lines1 = [
                "Real stakes. Real data. Real consequences.",
                "The platform isn't a prototype — it runs",
                "every morning against live health data.",
            ]
            y = 133
            for ln in lines1:
                c.drawString(14, y, ln); y -= 13
            c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 12)
            c.drawString(14, 83, "Enterprise stress-test.")
            c.setFont("Helvetica", 9); c.setFillColor(GREY_M)
            lines2 = [
                "Every AI feature — personas, extraction,",
                "adaptive emails, error handling — mirrors",
                "a pattern relevant to enterprise Claude",
                "adoption. The learning transfers directly.",
            ]
            y = 63
            for ln in lines2:
                c.drawString(14, y, ln); y -= 13

    right.append(DualBox(3.2*inch))
    right.append(Spacer(1, 0.08*inch))

    t = Table([[left, right]], colWidths=[3.9*inch, 3.2*inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(t)
    els.append(Spacer(1, 0.12*inch))

    # Stats strip at bottom
    class StatsStrip(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 58
        def draw(self):
            c = self.canv
            items = [
                ("19 sources", "unified into one"),
                ("4 years", "of health data"),
                ("~80 sessions", "with Claude to build"),
                ("$3/month", "fully operational"),
                ("0 days", "manual data entry"),
                ("v2.80", "current version"),
            ]
            bw = (self.aw - 5*6) / 6
            x = 0
            for val, sub in items:
                c.setFillColor(NAVY2); c.roundRect(x, 4, bw, 50, 6, stroke=0, fill=1)
                c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 10)
                c.drawCentredString(x + bw/2, 34, val)
                c.setFillColor(GREY_M); c.setFont("Helvetica", 7)
                c.drawCentredString(x + bw/2, 14, sub)
                x += bw + 6

    els.append(StatsStrip())
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# PART ONE DIVIDER
# ══════════════════════════════════════════════════════════════════════════════
def part_one(s):
    return [
        Spacer(1, 2*inch),
        PartDivider("PART ONE", "The Solution",
                    "What it does · how it fits into daily life · what it tells you", ACCENT),
        Spacer(1, 0.5*inch),
        Paragraph(
            "This section is about the experience — what the platform actually does for you, "
            "day-to-day, and what kinds of analysis it makes possible that no single app can provide.",
            ParagraphStyle("pi", fontName="Helvetica", fontSize=10, textColor=GREY_M,
                           leading=16, alignment=TA_CENTER)),
        PageBreak(),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 01 A WEEK IN THE LIFE
# ══════════════════════════════════════════════════════════════════════════════
def week_in_life(s):
    els = []
    els.append(Banner("01 — A Week in the Life",
        "Monday to Sunday — how everything connects into daily progress", acc=ACCENT))
    els.append(Spacer(1, 0.12*inch))
    els.append(Paragraph(
        "The platform doesn't require anything different from your day. "
        "Every device you're already wearing syncs automatically. The only thing that changes "
        "is what's waiting in your inbox when you wake up.",
        s["body"]))
    els.append(Spacer(1, 0.1*inch))

    class Timeline(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 295
        def draw(self):
            c = self.canv
            aw = self.aw
            c.setFillColor(NAVY); c.roundRect(0, 0, aw, 292, 10, stroke=0, fill=1)

            days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
            dcolors = [ACCENT2, ACCENT2, PURPLE, ACCENT2, GOLD, NAVY2, ACCENT]
            dw = (aw - 14) / 7; x0 = 7

            for i, (d, dc) in enumerate(zip(days, dcolors)):
                bx = x0 + i * dw
                c.setFillColor(dc); c.roundRect(bx, 261, dw - 4, 24, 5, stroke=0, fill=1)
                c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 8.5)
                c.drawCentredString(bx + (dw-4)/2, 270, d)

            rows = [
                # y, height, items by day_index: (di, title, line2, color)
                (222, 32, [
                    (0,"Morning Brief","10 AM daily",ACCENT),
                    (1,"Morning Brief","10 AM daily",ACCENT),
                    (2,"Morning Brief","10 AM daily",ACCENT),
                    (3,"Morning Brief","10 AM daily",ACCENT),
                    (4,"Morning Brief","10 AM daily",ACCENT),
                    (5,"Morning Brief","10 AM daily",ACCENT),
                    (6,"Morning Brief","10 AM daily",ACCENT),
                ]),
                (182, 32, [
                    (0,"Day Grade","A–F + context",ACCENT2),
                    (1,"Day Grade","A–F + context",ACCENT2),
                    (2,"Day Grade","A–F + context",ACCENT2),
                    (3,"Day Grade","A–F + context",ACCENT2),
                    (4,"Day Grade","A–F + context",ACCENT2),
                    (5,"Day Grade","A–F + context",ACCENT2),
                    (6,"Day Grade","A–F + context",ACCENT2),
                ]),
                (142, 32, [
                    (0,"Anomaly?","conditional alert",RED_S),
                    (2,"Chronicle","Elena publishes",PURPLE),
                    (3,"Levelled up?","XP + reward",GOLD),
                    (4,"The Plate","food col + list",GOLD),
                    (6,"Weekly Digest","7-pillar review",ACCENT),
                ]),
                (102, 32, [
                    (6,"Brittany Email","partner update",GREEN_S),
                ]),
                (62, 32, [
                    (0,"API Sync","background",HexColor("#1E3A5F")),
                    (1,"API Sync","background",HexColor("#1E3A5F")),
                    (2,"API Sync","background",HexColor("#1E3A5F")),
                    (3,"API Sync","background",HexColor("#1E3A5F")),
                    (4,"API Sync","background",HexColor("#1E3A5F")),
                    (5,"API Sync","background",HexColor("#1E3A5F")),
                    (6,"API Sync","background",HexColor("#1E3A5F")),
                ]),
                (22, 32, [
                    (0,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (1,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (2,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (3,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (4,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (5,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                    (6,"Dashboard","2 PM + 6 PM",HexColor("#0F3050")),
                ]),
            ]

            for (ry, rh, items) in rows:
                for (di, title, line2, ec) in items:
                    bx = x0 + di * dw + 2
                    bw2 = dw - 8
                    c.setFillColor(ec); c.roundRect(bx, ry, bw2, rh - 2, 4, stroke=0, fill=1)
                    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 6.5)
                    c.drawCentredString(bx + bw2/2, ry + rh - 12, title)
                    c.setFont("Helvetica", 5.8)
                    c.drawCentredString(bx + bw2/2, ry + rh - 22, line2)

    els.append(Timeline())
    els.append(Spacer(1, 0.12*inch))

    callouts = [
        ("Every morning", ACCENT,
         "The Daily Brief lands before the first coffee. Sleep architecture, yesterday's scores, "
         "training detail, nutrition gaps, habit streaks, readiness signal, and an AI coaching note "
         "from the Board of Directors — all from data that collected itself overnight."),
        ("If something's off", RED_S,
         "The anomaly detector runs at 8:05 AM across 15 metrics and 7 sources. "
         "If two or more metrics diverge from your personal baseline on the same morning, "
         "you get an alert with a root-cause hypothesis — before the daily brief even fires."),
        ("Wednesday", PURPLE,
         "Elena Voss — an AI persona — publishes 'The Measured Life' as a weekly health narrative. "
         "It draws on journal entries, key metrics, and coaching moments to tell a story about what actually happened. "
         "It exists because numbers don't create behaviour change — narrative does. "
         "The blog also has a voice section: an audio version where Elena actually speaks the column, "
         "so you can listen to your week rather than just read it."),
        ("Friday", GOLD,
         "The Weekly Plate: a food column reviewing the week's meals, recipe riffs on what worked, "
         "and a personalised grocery list for the local supermarket built from the actual MacroFactor nutrition log."),
        ("Sunday", GREEN_S,
         "Two accountability outputs land. First: the Weekly Digest — a full 7-pillar health review. "
         "Second: two accountability signals. The Brittany email is a warm, narrative update written by "
         "Dr. Murthy (relationships) and Coach Rodriguez (behaviour) — it answers 'how is he actually doing?' "
         "for a partner who cares but doesn't track metrics. "
         "Separately, an accountability dashboard sends signals to close friends who are on their own health journeys — "
         "green/yellow/red indicators based on key metrics, so if texting goes quiet they know whether to "
         "check in or whether things are on track and no nudge is needed."),
    ]
    for day, col, text in callouts:
        row = Table(
            [[Paragraph(f'<font color="{col.hexval()}"><b>{day}</b></font>', s["body"]),
              Paragraph(text, s["sm"])]],
            colWidths=[0.95*inch, 6.1*inch])
        row.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        els.append(row)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 02 WHY APPS AREN'T ENOUGH
# ══════════════════════════════════════════════════════════════════════════════
def why_not_apps(s):
    els = []
    els.append(Banner("02 — Why Apps Aren't Enough",
        "The problem with siloed data — and what unified analysis actually gives you", acc=ACCENT))
    els.append(Spacer(1, 0.1*inch))
    els.append(Paragraph(
        "Every app you use gives you one answer. Whoop tells you your recovery score. "
        "MacroFactor tells you your calories. Eight Sleep tells you your sleep score. "
        "Notion holds your journal. They don't talk to each other — so none of them can answer "
        "the only question that actually matters:",
        s["body"]))
    els.append(Spacer(1, 0.05*inch))
    els.append(Paragraph(
        "<b><i>\"My HRV is down, my sleep score is off, and my recovery is low. Why — and what should I actually do about it?\"</i></b>",
        ParagraphStyle("q", fontName="Helvetica-BoldOblique", fontSize=11,
                       textColor=ACCENT, alignment=TA_CENTER, leading=18,
                       spaceBefore=6, spaceAfter=10)))
    els.append(Paragraph(
        "Answering that question properly requires pulling from Whoop (HRV baseline), "
        "Eight Sleep (bed temperature, restlessness), MacroFactor (alcohol, caloric deficit, meal timing), "
        "Garmin (training load from yesterday), Notion (journal entry — were you stressed?), "
        "Habitify (sleep hygiene habits), and Apple Health (late-night phone use proxy). "
        "That's seven sources. No app does that join. This platform does.",
        s["body"]))
    els.append(Spacer(1, 0.1*inch))

    # Cell styles for wrapped text
    hdr  = ParagraphStyle("th2", fontName="Helvetica-Bold", fontSize=8.5, textColor=WHITE,  leading=12)
    cell = ParagraphStyle("td2", fontName="Helvetica",      fontSize=8.5, textColor=GREY_D, leading=13)
    neg  = ParagraphStyle("neg", fontName="Helvetica-Oblique", fontSize=8.5, textColor=RED_S, leading=13)

    def row(q, w, p, q_bold=False):
        qs = ParagraphStyle("qb", fontName="Helvetica-Bold" if q_bold else "Helvetica",
                            fontSize=8.5, textColor=NAVY if q_bold else GREY_D, leading=13)
        return [Paragraph(q, qs), Paragraph(w, neg), Paragraph(p, cell)]

    examples = [
        [Paragraph("Question", hdr), Paragraph("What Whoop says", hdr), Paragraph("What this platform can say", hdr)],
        row("Why was my sleep poor?", "Sleep score: 54",
            "Bed temp was +2°F, you ate within 90 min of sleep, alcohol logged in MacroFactor, and your journal noted stress"),
        row("Should I train hard today?", "Recovery: 42% (yellow)",
            "TSB is -18 (fresh), HRV within 5% of baseline, no anomalies flagged, yesterday was rest — train hard"),
        row("Why is my glucose elevated?", "No glucose data",
            "CGM: high-carb meal last night (MacroFactor), sleep was fragmented (Eight Sleep), possible cortisol signal"),
        row("Is my training improving my fitness?", "VO2 max estimate",
            "Zone 2 HRV trend over 8 weeks, pace-at-HR regression, lactate threshold proxy from Strava + Garmin"),
        row("What's affecting my mood most?", "No mood data",
            "Journal enrichment × HRV × sleep × training load — which variable has the highest Pearson r with mood score"),
    ]
    col_w = [2.1*inch, 1.45*inch, 3.45*inch]
    t = Table(examples, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  ACCENT2),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("GRID",          (0,0), (-1,-1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, GREY_L]),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    els.append(t)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 03 WHAT THE PLATFORM SURFACES
# ══════════════════════════════════════════════════════════════════════════════
def what_it_surfaces(s):
    els = []
    els.append(Banner("03 — What No Single App Can Tell You",
        "Cross-source analysis, personal baselines, and derived insights that require joining all 19 sources", acc=ACCENT))
    els.append(Spacer(1, 0.1*inch))
    els.append(Paragraph(
        "Each domain below represents a cluster of analysis that goes beyond what any single "
        "app provides — because it crosses sources, applies personal baselines, or derives "
        "a metric that no app computes for you.",
        s["body"]))
    els.append(Spacer(1, 0.06*inch))

    class CustomCalcBox(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 62
        def draw(self):
            c = self.canv
            c.setFillColor(HexColor("#0A1F0A")); c.roundRect(0, 0, self.aw, 58, 8, stroke=0, fill=1)
            c.setFillColor(GREEN_S); c.roundRect(0, 0, 5, 58, 3, stroke=0, fill=1)
            c.setFillColor(GREEN_S); c.setFont("Helvetica-Bold", 8)
            c.drawString(14, 44, "WHY CUSTOM CALCULATIONS MATTER")
            c.setFillColor(WHITE); c.setFont("Helvetica", 8)
            c.drawString(14, 30,
                "Whoop's recovery score uses population averages. MacroFactor's calorie target uses "
                "estimated TDEE. Garmin's")
            c.drawString(14, 18,
                "fitness age is a model, not your data. Every metric below is computed against your "
                "personal baseline,")
            c.drawString(14, 6,
                "your actual lab draws, your real glucose response curves — not generalised population stats.")

    els.append(CustomCalcBox())
    els.append(Spacer(1, 0.08*inch))

    domains = [
        ("Sleep — the full picture", ACCENT, [
            "<b>Sleep efficiency vs bed environment:</b> does your Eight Sleep set-point actually correlate with better sleep for you, specifically?",
            "<b>Alcohol → sleep architecture:</b> your personal dose-response curve across 100+ nights — not population averages",
            "<b>Fasting glucose validation:</b> CGM overnight nadir vs. lab draws — are your morning blood tests actually fasting values?",
            "<b>Circadian consistency:</b> sleep onset standard deviation — are your 1 AM nights actually costing you next-day HRV?",
        ]),
        ("Training — what's actually working", GOLD, [
            "<b>Zone 2 aerobic base trend:</b> pace-at-same-HR over time. Improving fitness = same pace, lower HR.",
            "<b>Lactate threshold proxy:</b> cardiac efficiency curve from steady-state Garmin + Strava sessions — closest consumer proxy to a lab test",
            "<b>Heart rate recovery trend:</b> 1-minute and 2-minute HR drop post-workout — strongest exercise-derived mortality predictor (Cole et al., NEJM)",
            "<b>Training load vs. readiness:</b> TSB from CTL/ATL, Whoop recovery, Garmin Body Battery — synthetic recommendation rather than three separate scores",
            "<b>Exercise variety:</b> Shannon diversity index across movement patterns — staleness detection, missing category identification",
        ]),
        ("Nutrition — beyond macro tracking", ORANGE, [
            "<b>Meal-level glucose response:</b> CGM × MacroFactor food log — which specific foods cause spikes for you (not population data)",
            "<b>Energy balance:</b> Apple Watch TDEE (measured) vs. MacroFactor intake — actual daily surplus/deficit, not estimated",
            "<b>Protein distribution score:</b> how many meals hit the MPS threshold (30g)? Timing matters as much as total",
            "<b>Micronutrient sufficiency:</b> fiber, potassium, magnesium, vitamin D, omega-3 — surfaced daily, not just macros",
            "<b>Genome × nutrition:</b> FADS2 ALA conversion, VKORC1 vitamin K sensitivity, choline demand — your specific gene panel informs food priorities",
        ]),
        ("Mental & emotional health", PURPLE, [
            "<b>Mood × physiology:</b> journal mood scores correlated with HRV, sleep, training load — which physical variable predicts your mood best?",
            "<b>Defense mechanism detection:</b> 11 patterns (intellectualization, avoidance, displacement) identified in journal text by Claude, trending over time",
            "<b>Social connection quality:</b> meaningful-vs-surface interaction ratio, isolation risk detection, Murthy threshold assessment (3–5 close relationships)",
            "<b>Emotional depth index:</b> journal vocabulary richness, flow state indicators, values-lived alignment — week-on-week",
        ]),
        ("Longevity & metabolic health", GREEN_S, [
            "<b>Biological age (PhenoAge):</b> Levine algorithm from 9 blood biomarkers across all 7 lab draws — with genome context for longevity SNPs",
            "<b>Metabolic health score:</b> composite (0–100) from CGM 30%, labs 35%, weight/BMI 20%, blood pressure 15% — one number, not four dashboards",
            "<b>ASCVD 10-year risk:</b> Pooled Cohort Equations from actual blood draws — tracked across 6 years (2019–2025)",
            "<b>Health trajectory:</b> forward projection across weight, biomarkers, Zone 2 fitness, recovery, metabolic trends",
        ]),
        ("Gamification — keeping the loop closed", ACCENT2, [
            "<b>Character Level (1–100):</b> 7 weighted pillars composited into a persistent level score — not a number to minimise, but one to genuinely improve",
            "<b>Cross-pillar effects:</b> Sleep Drag (-3 to Metabolism when sleep <6hr), Training Boost (+2 when Zone 2 >150 min/wk), Synergy Bonus",
            "<b>Pixel art avatar:</b> body frame morphs with physical milestone events; tier aura evolves from Foundation to Elite",
            "<b>Rewards system:</b> user-defined rewards triggered by milestone events — seeded by Matthew and Brittany together",
            "See next page for screenshots of the avatar, radar chart, and tier progression system",
        ]),
    ]

    for title, color, items in domains:
        els.append(Paragraph(f'<font color="{color.hexval()}"><b>{title}</b></font>', s["h3a"]))
        for item in items:
            els.append(Paragraph(item, s["bulsm"]))
        els.append(Spacer(1, 0.08*inch))

    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 04 WHY 124 TOOLS
# ══════════════════════════════════════════════════════════════════════════════
def why_tools(s):
    els = []
    els.append(Banner("04 — Why 124 Tools",
        "The architecture of inquiry — one question, many sources", acc=ACCENT))
    els.append(Spacer(1, 0.1*inch))
    els.append(Paragraph(
        "The number looks large. It makes sense when you understand the structure.",
        s["body"]))
    els.append(Spacer(1, 0.06*inch))
    els.append(Paragraph(
        "Every meaningful health question crosses multiple data sources. Each source needs "
        "its own read tool. Each cross-source analysis needs its own correlation or synthesis tool. "
        "Each derived metric (biological age, metabolic score, lactate proxy) needs its own "
        "compute tool. Add write tools for logging (supplements, travel, life events) and "
        "operation tools (experiments, rewards, board management) — and 124 is actually compact "
        "for what it covers.",
        s["body"]))
    els.append(Spacer(1, 0.08*inch))

    class NoMemoryBox(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 76
        def draw(self):
            c = self.canv
            c.setFillColor(HexColor("#0F2030")); c.roundRect(0, 0, self.aw, 72, 8, stroke=0, fill=1)
            c.setFillColor(GOLD); c.roundRect(0, 0, 5, 72, 3, stroke=0, fill=1)
            c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 8.5)
            c.drawString(14, 56, "THE KEY ARCHITECTURAL CONSTRAINT")
            c.setFillColor(WHITE); c.setFont("Helvetica", 8.5)
            c.drawString(14, 40,
                "Claude has no memory between sessions. Every conversation starts from zero.")
            c.setFillColor(GREY_M); c.setFont("Helvetica", 8)
            c.drawString(14, 24,
                "This is why there are 124 tools — not because the data is complex, but because each question")
            c.drawString(14, 12,
                "requires discrete retrievals across multiple sources. Fewer tools = less precise answers.")

    els.append(NoMemoryBox())
    els.append(Spacer(1, 0.08*inch))

    breakdown = [
        ["Category",                      "Tools", "Examples"],
        ["Source read tools",             "38",    "get_sleep_analysis · get_training_load · get_cgm_dashboard · get_mood_trend"],
        ["Cross-source correlations",     "22",    "alcohol → sleep · exercise → glucose · mood × HRV · meal → spike"],
        ["Derived analytics",             "18",    "biological_age · metabolic_score · lactate_threshold · hr_recovery"],
        ["Gamification / tracking",       "12",    "character_sheet · pillar_detail · experiment_results · habit_tier_report"],
        ["Write / logging tools",         "16",    "log_supplement · log_travel · log_ruck · log_temptation · save_insight"],
        ["Platform / config management",  "18",    "board_of_directors · update_member · adaptive_mode · get_profile"],
    ]
    t = para_table(breakdown, [1.8*inch, 0.55*inch, 4.75*inch], bg=ACCENT2)
    els.append(t)
    els.append(Spacer(1, 0.1*inch))
    els.append(Paragraph(
        "The other reason: Claude has no memory between sessions. "
        "Every tool call is a discrete retrieval. If Claude needs to answer "
        "\"how does your sleep change when you train in the evening?\" it issues four tool calls: "
        "get_sleep_analysis, get_exercise_sleep_correlation, get_training_load, get_day_type_analysis. "
        "Fewer tools would mean less precise answers — or no answer at all.",
        s["body"]))
    els.append(Spacer(1, 0.08*inch))

    modules = [
        ["Module",               "Tools", "Domain"],
        ["tools_sleep",          "8",     "Sleep quality, environment, onset consistency, nap tracking"],
        ["tools_activity",       "10",    "Zone 2, training load, HR recovery, lactate proxy, periodization"],
        ["tools_nutrition",      "9",     "Food log, macro targets, meal glucose, energy balance, micronutrients"],
        ["tools_character",      "4",     "Character sheet, pillar detail, level history, effects"],
        ["tools_habits",         "8",     "Habit registry, tier report, vice streaks, synergy groups"],
        ["tools_journal",        "6",     "Entries, search, mood trend, correlations, insights, defense patterns"],
        ["tools_social",         "12",    "Life events, interaction log, temptation, cold/heat exposure"],
        ["tools_longevity",      "8",     "Biological age, metabolic score, health risk, genome, food response DB"],
        ["tools_correlation",    "8",     "Alcohol × sleep, exercise × glucose, mood × vitals, jet lag"],
        ["tools_health",         "10",    "Readiness, blood pressure, gait, body comp, trajectory, day type"],
        ["tools_labs",           "8",     "Lab results, trends, out-of-range history, DEXA, biomarker search"],
        ["tools_board",          "3",     "Board of directors CRUD — add/update/remove expert personas"],
        ["(14 more modules)",    "30",    "cgm · genome · supplements · weather · travel · adaptive mode · ops …"],
    ]
    t2 = para_table(modules, [1.45*inch, 0.45*inch, 5.2*inch])
    els.append(t2)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 05 FEATURES IN ACTION
# ══════════════════════════════════════════════════════════════════════════════
def features(s):
    els = []
    els.append(Banner("05 — Features in Action",
        "Screenshots from the running system — obfuscated for sharing", acc=ACCENT))
    els.append(Spacer(1, 0.1*inch))

    els.append(Paragraph("Daily Brief — every morning at 10 AM", s["h3a"]))
    els.append(two_col(
        "shot02_daily_brief",
        "Top of the Daily Brief: day grade, Character Sheet level + radar, 8-pillar scorecard",
        "shot03_training",
        "Training report section: set-level workout data + AI sports scientist commentary"))
    els.append(Spacer(1, 0.1*inch))

    els.append(Paragraph("Brittany Email (Sunday 9:30 AM) · Habits Deep-Dive", s["h3a"]))
    els.append(two_col(
        "shot07_brittany1",
        "Partner email: Rodriguez on behavioural state, Dr. Murthy on how to show up",
        "shot05_habits",
        "Habits deep-dive: 65 habits across 3 tiers with AI coaching note per habit"))
    els.append(PageBreak())

    els.append(Banner("The Weekly Plate · Buddy Page · CGM + Board",
        "Food column · accountability beacon · data intelligence", acc=GOLD))
    els.append(Spacer(1, 0.1*inch))

    els.append(two_col(
        "shot10_plate1",
        "The Weekly Plate: reviewing the week's meals + recipe riffs on what actually worked",
        "shot12_grocery",
        "The Grocery Run: grocery list generated from the MacroFactor nutrition log"))
    els.append(Spacer(1, 0.1*inch))

    els.append(two_col(
        "shot14_buddy1",
        "Buddy page: green/yellow/red accountability beacon for Tom (Singapore) to check",
        "shot06_cgm_board",
        "CGM spotlight + gait + weight phase + Board of Directors coaching card"))
    els.append(PageBreak())

    els.append(Banner("Dashboard · Blog · Clinical Summary",
        "Live web properties — all generated automatically", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    els.append(two_col(
        "shot16_dashboard",
        "Web dashboard: readiness, sleep, glucose, training TSB, character avatar — updates 2×/day",
        "shot13_blog",
        "'The Measured Life' — weekly health narrative by AI persona Elena Voss, auto-published"))
    els.append(Spacer(1, 0.1*inch))

    els.append(two_col(
        "shot11_plate2",
        "Recipe suggestions tuned to personal macro history and local supermarket availability",
        "shot17_clinical",
        "Clinical Summary: 30-day report formatted for a doctor visit (name field redacted)"))
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 05b GAMIFICATION — Avatar, Radar, Tier Progression
# ══════════════════════════════════════════════════════════════════════════════
def gamification_page(s):
    els = []
    els.append(Banner("Gamification — Avatar · Radar · Tier Progression",
        "The Character Sheet lives on the web dashboard, the buddy page, and in every daily brief",
        acc=ACCENT2))
    els.append(Spacer(1, 0.1*inch))

    # ── Top row: avatar+radar (left) + character sheet pillar bars (right) ──
    els.append(Paragraph("How it looks in the running system", s["h3a"]))
    els.append(Spacer(1, 0.06*inch))

    left_shots = screenshot("shot21_char_radar", 3.3*inch, 3.0*inch,
        "Web dashboard: Level 1 Foundation avatar + 7-pillar radar chart (Sleep, Move, Habits, Social, Nutrition, Mind, Meta)")
    right_shots = screenshot("shot19_buddy_character", 3.3*inch, 3.0*inch,
        "Buddy page character sheet: pixel art avatar + 7 pillar bars — what Tom sees in Singapore")

    t = Table([[left_shots, right_shots]], colWidths=[3.55*inch, 3.55*inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 2),
        ("RIGHTPADDING", (0,0), (-1,-1), 2),
    ]))
    els.append(t)
    els.append(Spacer(1, 0.12*inch))

    # ── Tier progression diagram ──
    els.append(Paragraph("Five Tiers — Foundation to Elite", s["h3a"]))
    els.append(Spacer(1, 0.04*inch))
    els.append(Paragraph(
        "Level progresses through five tiers. Each tier changes the avatar's aura, "
        "unlocks new pillar effects, and shifts the coaching tone. The XP bar fills "
        "based on weighted pillar improvement using a 21-day EMA. Tier transitions "
        "take 7 days up and 10 days down — preventing gaming and rewarding consistency.",
        s["sm"]))
    els.append(Spacer(1, 0.06*inch))

    tier_path = "/home/claude/tier_progression.png"
    tier_img = PILImage.open(tier_path)
    iw, ih = tier_img.size
    max_w = 7.1 * inch
    ratio = max_w / iw
    dw, dh = iw * ratio, ih * ratio
    els.append(RLImage(tier_path, width=dw, height=dh))
    els.append(Spacer(1, 0.08*inch))

    # ── Mechanics table ──
    mech = [
        ["Mechanic",                 "Detail"],
        ["Level range",              "1–100 · baseline Feb 22 2026 · EMA λ=0.85 over 21 days"],
        ["Tier bands",               "Foundation (1–20) · Momentum (21–40) · Discipline (41–60) · Mastery (61–80) · Elite (81–100)"],
        ["Transition speed",         "5 consecutive days above threshold to move up · 7 to move down"],
        ["XP calculation",           "Weighted pillar scores: Sleep 20% · Movement 18% · Nutrition 18% · Mind 15% · Metabolic 12% · Consistency 10% · Relationships 7%"],
        ["Cross-pillar effects",     "Sleep Drag (-3 pts when sleep <6hr) · Training Boost (+2 pts when Zone 2 >150 min/wk) · Nutrition Synergy · Habit Streak Bonus"],
        ["Avatar body frames",       "4 milestone frames composited via CSS — reflects physical progress milestones"],
        ["Pillar badge overlays",    "7 badge PNGs overlay on the avatar sprite — one per pillar, glow on high scores"],
        ["Pixel art tier aura",      "5 aura variants (none → grey → gold → red → teal → purple) — rendered on dashboard + buddy page"],
        ["Reward examples (Ph.4)",   "Weekend away · Spa day · New gear (fitness equipment, clothing) · Dinner out · Concert tickets · Experience-based events · Seeded together by Matthew + Brittany"],
    ]
    t2 = para_table(mech, [1.9*inch, 5.2*inch], bg=ACCENT2)
    els.append(t2)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# PART TWO DIVIDER
# ══════════════════════════════════════════════════════════════════════════════
def part_two(s):
    return [
        Spacer(1, 2*inch),
        PartDivider("PART TWO", "The Build",
                    "Architecture · AWS · security · data model · resiliency", PURPLE),
        Spacer(1, 0.5*inch),
        Paragraph(
            "This section covers how it's built — the AWS infrastructure, deployment patterns, "
            "data model, and operational practices that keep it running reliably for ~$3/month.",
            ParagraphStyle("pi", fontName="Helvetica", fontSize=10, textColor=GREY_M,
                           leading=16, alignment=TA_CENTER)),
        PageBreak(),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 06 SYSTEM ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════════════
def architecture(s):
    els = []
    els.append(Banner("06 — System Architecture",
        "Ingest → Store → Serve · matplotlib-rendered, not guessed", acc=PURPLE))
    els.append(Spacer(1, 0.08*inch))

    arch_path = "/home/claude/arch_diagram.png"
    img = PILImage.open(arch_path)
    iw, ih = img.size
    max_w = 7.1 * inch
    max_h = 5.8 * inch
    ratio = min(max_w / iw, max_h / ih)
    dw, dh = iw * ratio, ih * ratio

    rl_img = RLImage(arch_path, width=dw, height=dh)
    els.append(rl_img)
    els.append(Spacer(1, 0.08*inch))
    els.append(Paragraph(
        "Five layers: Data Sources (19 sources) → Ingest (EventBridge + 30 Lambdas + API Gateway + SQS DLQs) "
        "→ Store (DynamoDB + S3 + Secrets Manager + CloudWatch + CloudTrail) "
        "→ Serve/Intelligence (MCP Lambda + 7 Email Lambdas + Anthropic API + Dashboard Refresh + Ops) "
        "→ Outputs (SES · 3 CloudFront sites · Claude Desktop/Mobile · AWS Budget).",
        s["sm"]))
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 07 AWS COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════
def aws_components(s):
    els = []
    els.append(Banner("07 — AWS Components", "What's running and why", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))
    comp = [
        ["Service",         "Usage",                                      "Count",    "Notes"],
        ["Lambda",          "Ingest + compute + email + MCP + ops",       "30",       "Python 3.12 · 128–1024 MB"],
        ["DynamoDB",        "Single-table health data store",             "1 table",  "On-demand · PITR · deletion protection"],
        ["S3",              "Raw archive + static site + config JSON",    "1 bucket", "~2.5 GB · 4 path prefixes"],
        ["EventBridge",     "Cron scheduler for all Lambdas",             "22 rules", "UTC crons; DST shift documented in RUNBOOK"],
        ["API Gateway",     "Inbound webhook from iPhone (HAE)",          "1 HTTP",   "Route POST /ingest → Lambda"],
        ["CloudFront",      "CDN for 3 web properties",                  "3 distros","Lambda@Edge auth on dash + buddy"],
        ["SES",             "Outbound email + inbound insight capture",   "1 domain", "9 email types/week"],
        ["Secrets Manager", "API keys + OAuth tokens",                   "6 secrets","90-day auto-rotation on MCP key"],
        ["CloudWatch",      "Monitoring + alerting",                      "35 alarms","→ SNS → email"],
        ["SQS",             "Dead-letter queues on async Lambdas",        "20+ DLQs", "Async failure capture"],
        ["ACM",             "TLS certificates",                           "2 certs",  "us-east-1 required for CloudFront"],
        ["AWS Budget",      "Cost guardrail",                             "$20/mo",   "Alerts at 25% / 50% / 100% · current: ~$3/mo"],
    ]
    t = para_table(comp, [1.15*inch, 2.6*inch, 0.9*inch, 2.45*inch])
    els.append(t)
    els.append(Spacer(1, 0.12*inch))
    els.append(two_col(
        "shot09_alarm",
        "CloudWatch alarm email (account ID redacted) — real production alert, resolved < 1hr",
        "shot01_freshness",
        "Freshness checker: daily staleness report — catches data gaps before the morning brief"))
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 08 SECURITY & OPS
# ══════════════════════════════════════════════════════════════════════════════
def security_ops(s):
    els = []
    els.append(Banner("08 — Security & Ops",
        "IAM · secrets · auth · git deployment · cost guardrails", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    left = []
    left.append(Paragraph("IAM — Least-Privilege Roles", s["h3a"]))
    iam = [
        ["Role",             "Permissions"],
        ["Ingestion (×13)",  "DynamoDB PutItem · S3 PutObject · SecretsMgr (own secret) · SQS DLQ"],
        ["MCP server",       "DynamoDB GetItem/Query/PutItem (cache) · S3 GetObject (cgm/* only)"],
        ["Email / digest",   "DynamoDB read/write · SES SendEmail (own domain) · S3 dashboard/*"],
        ["CloudFront auth",  "SecretsMgr GetSecretValue · CF viewer request only"],
    ]
    t = para_table(iam, [1.2*inch, 2.15*inch], bg=ACCENT2)
    left.append(t)
    left.append(Spacer(1, 0.08*inch))
    left.append(Paragraph("Secrets Management", s["h3a"]))
    for it in [
        "6 secrets (consolidated from 12 — saves $2.40/mo)",
        "OAuth tokens: self-healing refresh on each Lambda invocation",
        "MCP API key: 90-day auto-rotation via dedicated rotator Lambda",
    ]:
        left.append(Paragraph(it, s["bulsm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph("Cost Controls", s["h3a"]))
    for it in [
        "$20/month hard cap · 3-tier alerts (25% / 50% / 100%)",
        "On-demand DynamoDB — no reserved capacity",
        "Lambda memory right-sized: 128–256 MB for ingestion",
        "<b>Current: ~$3/month</b> for full workload",
    ]:
        left.append(Paragraph(it, s["bulsm"]))

    right = []
    right.append(Paragraph("Auth Layers", s["h3a"]))
    auth = [
        ["Surface",        "Method"],
        ["dash.[domain]",  "Lambda@Edge HMAC cookie"],
        ["buddy.[domain]", "Separate Lambda@Edge + secret"],
        ["blog.[domain]",  "Public / no auth"],
        ["MCP endpoint",   "Bearer token (HMAC-SHA256)"],
        ["HAE webhook",    "Bearer + Secrets Manager"],
        ["Insight email",  "ALLOWED_SENDERS whitelist"],
    ]
    t2 = para_table(auth, [1.35*inch, 1.9*inch])
    right.append(t2)

    row = Table([[left, right]], colWidths=[3.55*inch, 3.55*inch])
    row.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(row)
    els.append(Spacer(1, 0.1*inch))
    els.append(HRFlowable(width="100%", thickness=0.4, color=GREY_M))
    els.append(Spacer(1, 0.08*inch))

    els.append(Paragraph("Git-Driven Deployment", s["h3a"]))
    els.append(Paragraph(
        "The entire platform lives in a single git repository (v2.80.1 — 555 objects, ~80 sessions "
        "of commits). Every Lambda, every config file, every deploy script is versioned.",
        s["sm"]))
    els.append(Spacer(1, 0.06*inch))

    gl = []
    gl.append(Paragraph("Deploy Pattern", s["h3"]))
    for step in [
        "<b>1. Write</b> — Claude edits files via Filesystem tools",
        "<b>2. Commit</b> — git commit -m 'v2.X.X: feature description'",
        "<b>3. Deploy</b> — deploy/deploy_lambda.sh auto-reads handler config from AWS",
        "<b>4. Verify</b> — CloudWatch logs checked before sign-off",
        "<b>5. Push</b> — git push; GitHub is source of truth",
    ]:
        gl.append(Paragraph(step, s["bulsm"]))

    gr = []
    gr.append(Paragraph("Why This Matters", s["h3"]))
    for pt in [
        "deploy_lambda.sh never hardcodes zip filenames — handler config read live from AWS to avoid mismatch",
        "10s wait between sequential Lambda deploys prevents ResourceConflictException",
        "Deploy success ≠ execution success — CloudWatch log verification is required",
        "Session close ritual: write handover → update CHANGELOG → git add -A && commit && push",
    ]:
        gr.append(Paragraph(pt, s["bulsm"]))

    t3 = Table([[gl, gr]], colWidths=[3.55*inch, 3.55*inch])
    t3.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(t3)
    els.append(Spacer(1, 0.1*inch))
    els.append(HRFlowable(width="100%", thickness=0.4, color=GREY_M))
    els.append(Spacer(1, 0.08*inch))
    els.append(Paragraph("Data Governance & Privacy", s["h3a"]))
    els.append(Paragraph(
        "All health data remains in a single AWS account (us-west-2) under exclusive control. "
        "No third-party analytics, no data sharing, no advertising. "
        "Data flows: device APIs → Lambda (ephemeral, no persistent storage) → DynamoDB/S3 (encrypted at rest). "
        "Sensitive values (API keys, OAuth tokens) never appear in Lambda environment variables — "
        "all retrieved from Secrets Manager at invocation time and held only in memory. "
        "The obfuscation pipeline (demo mode) removes or replaces all PII and health values "
        "before any data leaves the system for sharing.",
        s["sm"]))
    els.append(PageBreak())
    return els
# ══════════════════════════════════════════════════════════════════════════════
def data_model(s):
    els = []
    els.append(Banner("09 — Data Model",
        "Single-table DynamoDB · 21 source partitions · one clean pattern", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    left = []
    left.append(Paragraph("Key Pattern", s["h3a"]))

    class KD(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 80
        def draw(self):
            c = self.canv; aw = self.aw
            c.setFillColor(NAVY2); c.roundRect(0, 6, aw, 70, 6, stroke=0, fill=1)
            c.setFillColor(ACCENT);  c.setFont("Helvetica-Bold", 8)
            c.drawString(10, 60, "PK — Partition Key")
            c.setFillColor(WHITE); c.setFont("Courier-Bold", 8)
            c.drawString(10, 46, "USER#[id]#SOURCE#<source>")
            c.setFillColor(ACCENT2); c.setFont("Helvetica-Bold", 8)
            c.drawString(10, 28, "SK — Sort Key")
            c.setFillColor(WHITE); c.setFont("Courier-Bold", 8)
            c.drawString(10, 14, "DATE#YYYY-MM-DD")

    left.append(KD())
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph(
        "No GSI by design. All access patterns served by PK+SK range queries. "
        "Monthly aggregation for date windows >90 days.",
        s["sm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph("Special Partitions", s["h3a"]))
    sp = [
        ["Pattern",                       "Purpose"],
        ["PROFILE#v1",                    "User settings, habit registry, demo rules"],
        ["CACHE#[id] / TOOL#<key>",       "Pre-computed tool results (TTL 26h)"],
        ["SOURCE#day_grade",              "Daily composite scores — 948+ records"],
        ["SOURCE#character_sheet",        "RPG level + 7 pillars (computed nightly)"],
        ["SOURCE#insights / INSIGHT#<ts>","Coaching insights captured via email reply"],
    ]
    t = para_table(sp, [2.1*inch, 1.25*inch], bg=ACCENT2)
    left.append(t)

    right = []
    right.append(Paragraph("21 Source Partitions", s["h3a"]))
    src = [
        ["Source",         "Domain",          "Type"],
        ["whoop",          "sleep / HRV",     "Wearable API"],
        ["eightsleep",     "bed environment", "Smart bed API"],
        ["garmin",         "biometrics",      "Wearable API"],
        ["strava",         "cardio",          "Activity API"],
        ["withings",       "body comp",       "Scale API"],
        ["macrofactor",    "nutrition",       "CSV/Dropbox"],
        ["apple_health",   "steps/gait/cgm",  "Webhook 4h"],
        ["habitify",       "habits",          "API"],
        ["notion",         "journal",         "Notion API"],
        ["labs",           "biochemical",     "Manual seed"],
        ["dexa",           "body comp",       "Manual seed"],
        ["genome",         "genetic",         "Manual seed"],
        ["supplements",    "supplements",     "MCP write"],
        ["weather",        "environment",     "Open-Meteo"],
        ["state_of_mind",  "emotional",       "Webhook"],
        ["character_sheet","gamification",    "Computed"],
        ["day_grade",      "meta score",      "Computed"],
        ["habit_scores",   "habits meta",     "Computed"],
        ["anomalies",      "monitoring",      "Computed"],
        ["travel",         "context",         "MCP write"],
    ]
    t2 = para_table(src, [1.1*inch, 1.1*inch, 0.85*inch])
    right.append(t2)

    t3 = Table([[left, right]], colWidths=[3.7*inch, 3.4*inch])
    t3.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(t3)
    els.append(Spacer(1, 0.08*inch))

    # Source-of-truth callout
    _sot_title = ParagraphStyle("sot_t", fontName="Helvetica-Bold", fontSize=8,
                                 textColor=ACCENT, leading=11)
    _sot_body  = ParagraphStyle("sot_b", fontName="Helvetica", fontSize=8,
                                 textColor=WHITE, leading=11, spaceBefore=3)
    sot_inner = [
        Paragraph("SOURCE-OF-TRUTH DOMAIN MODEL", _sot_title),
        Paragraph(
            "When the same signal arrives from multiple sources, a single source is declared authoritative "
            "per domain. <b>Whoop</b> = sleep metrics and HRV (wrist sensor, location-independent). "
            "<b>Eight Sleep</b> = bed environment only (temperature, mattress score). "
            "<b>Garmin</b> = active biometrics during workouts. "
            "<b>Strava</b> = canonical activity record (synced from Garmin). "
            "<b>MacroFactor</b> = nutrition (TDEE-adjusted). "
            "This prevents conflicting scores and eliminates double-counting in aggregated metrics.",
            _sot_body),
    ]
    sot_table = Table([[sot_inner]], colWidths=[7.1*inch])
    sot_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY2),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LINEBEFORE",    (0,0), (0,-1), 3, ACCENT),
    ]))
    els.append(sot_table)
    els.append(PageBreak())
    return els
# ══════════════════════════════════════════════════════════════════════════════
def ai_integration(s):
    els = []
    els.append(Banner("10 — AI Integration",
        "Claude MCP · 124 tools · OAuth 2.1 · Sonnet 4.6 for synthesis · Haiku for extraction",
        acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    left = []
    left.append(Paragraph("MCP Architecture", s["h3a"]))
    for a in [
        "Lambda Function URL + OAuth 2.1 auto-approve flow",
        "HMAC-SHA256 Bearer token validation in handler",
        "Streamable HTTP transport (MCP spec 2025-06-18)",
        "Claude Desktop · claude.ai · Claude mobile — all connected",
        "Cold start: ~700–800ms  /  Warm: ~25ms",
        "12 tools pre-computed nightly (cache hit <100ms)",
        "5-min in-memory cache for Board of Directors config",
    ]:
        left.append(Paragraph(a, s["bulsm"]))
    left.append(Spacer(1, 0.08*inch))
    left.append(Paragraph("AI Model Standards", s["h3a"]))
    mods = [
        ["Task",                 "Model"],
        ["Synthesis / narrative","Claude Sonnet 4.6"],
        ["Daily coaching email", "Claude Sonnet 4.6"],
        ["Extraction / classify","Claude Haiku 4.5"],
        ["Anomaly hypothesis",   "Claude Haiku 4.5"],
        ["Cost per brief",       "~$0.02"],
        ["Plate email / week",   "~$0.04"],
    ]
    t = para_table(mods, [1.6*inch, 1.65*inch], bg=NAVY2)
    left.append(t)

    right = []
    right.append(Paragraph("AI Calls Per Daily Brief", s["h3a"]))
    ai_calls = [
        ["Call",                  "Model",  "Output"],
        ["Board of Directors",    "Sonnet", "Expert persona coaching from health data"],
        ["Training + Nutrition",  "Sonnet", "Commentary from sports scientist + nutritionist"],
        ["Journal Coach",         "Sonnet", "Reflection + action from raw journal text"],
        ["TL;DR + Guidance",      "Haiku",  "2-sentence summary + top 3 recommendations"],
    ]
    t2 = para_table(ai_calls, [1.3*inch, 0.6*inch, 1.35*inch])
    right.append(t2)
    right.append(Spacer(1, 0.08*inch))
    right.append(Paragraph("Board of Directors — The Concept", s["h3a"]))

    # Paragraph-based concept box — text wraps correctly in the column
    _bod_bg   = ParagraphStyle("bod_bg",  fontName="Helvetica-Bold", fontSize=8,
                                textColor=PURPLE,  leading=12)
    _bod_body = ParagraphStyle("bod_body",fontName="Helvetica",       fontSize=8,
                                textColor=WHITE,   leading=12, spaceBefore=3)
    _bod_cfg  = ParagraphStyle("bod_cfg", fontName="Helvetica-Bold",  fontSize=8,
                                textColor=GOLD,    leading=12, spaceBefore=4)

    bod_inner = [
        Paragraph("WHY PERSONAS, NOT PROMPTS?", _bod_bg),
        Paragraph(
            "A recovery score of 42 means different things depending on who you ask. "
            "To a sleep scientist it's a HRV signal. To a behavioural coach it's a stress response. "
            "To a nutritionist it's a refuelling window.",
            _bod_body),
        Spacer(1, 4),
        Paragraph(
            "Personas force the AI to frame the same data through different lenses — "
            "each with different expertise, vocabulary, and priorities. The result is "
            "richer, more actionable coaching than any single prompt can produce.",
            _bod_body),
        Spacer(1, 4),
        Paragraph("Config-driven: edit any persona in S3 without redeploying a Lambda.", _bod_cfg),
    ]

    bod_table = Table([[bod_inner]], colWidths=[3.5*inch])
    bod_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), HexColor("#0D0020")),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING",   (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ("LINEAFTER",    (0,0), (0,-1), 4, PURPLE),  # left accent bar via left border trick
    ]))
    right.append(bod_table)
    right.append(Spacer(1, 0.06*inch))
    right.append(Paragraph(
        "13 expert AI personas: Dr. Lisa Park (sleep), Dr. Sarah Chen (training), "
        "Dr. Marcus Webb (nutrition), Dr. Peter Attia (metabolic), Coach Rodriguez (behavioral), "
        "Dr. Paul Conti (psychiatry), Dr. Vivek Murthy (social), Elena Voss (narrator).",
        s["sm"]))

    t3 = Table([[left, right]], colWidths=[3.4*inch, 3.7*inch])
    t3.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(t3)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 11 RESILIENCY
# ══════════════════════════════════════════════════════════════════════════════
def resiliency(s):
    els = []
    els.append(Banner("11 — Resiliency",
        "DLQs · alarms · gap-aware backfill · 3 incidents resolved <1hr each", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    left = []
    left.append(Paragraph("Dead-Letter Queues", s["h3a"]))
    left.append(Paragraph(
        "20 of 30 Lambdas have SQS DLQs on async invocations. "
        "Failed runs are captured — not silently lost.",
        s["sm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph("Gap-Aware Self-Healing Backfill", s["h3a"]))
    for st in [
        "On each run: query DDB for last 7 days of records",
        "Identify any missing DATE# keys for each source",
        "Fetch only those specific days from upstream API",
        "Normal run: 1 DDB query, 0 extra API calls",
        "Applied to all 6 API-based ingestion Lambdas",
    ]:
        left.append(Paragraph(st, s["bulsm"]))
    left.append(Spacer(1, 0.06*inch))
    left.append(Paragraph("Hard-Won Operational Notes", s["h3a"]))
    for l in [
        "<b>Deploy success ≠ execution success.</b> CloudWatch log verification required",
        "<b>S3 AccessDenied can mask NoSuchKey.</b> Without ListBucket, root cause is obscured",
        "<b>DynamoDB 'date' is reserved.</b> Requires expression attribute name substitution",
        "<b>ACM certs for CloudFront must be in us-east-1</b> regardless of bucket region",
        "<b>MCP tool functions must come before TOOLS={} dict</b> — order matters at import",
    ]:
        left.append(Paragraph(l, s["bulsm"]))

    right = []
    right.append(Paragraph("CloudWatch Alarms (35)", s["h3a"]))
    ad = [
        ["Type",                    "Count"],
        ["Lambda Error rate",        "30 (1 per Lambda)"],
        ["SQS DLQ depth > 0",        "3"],
        ["Lambda duration > 80%",    "2"],
    ]
    t = para_table(ad, [2.0*inch, 1.1*inch], bg=ACCENT2)
    right.append(t)
    right.append(Paragraph("All alarms → SNS → email. 24hr window, TreatMissingData=notBreaching.", s["sm"]))
    right.append(Spacer(1, 0.08*inch))
    right.append(Paragraph("3 Production Incidents — All Resolved <1hr", s["h3a"]))
    for inc in [
        "<b>Secrets consolidation:</b> stale SECRET_NAME env var on 2 Lambdas — CloudWatch surfaced immediately, env var patched",
        "<b>CloudFront double-pathing:</b> origin path '/dashboard' caused 403 on avatar assets — URL path analysis resolved in <20 min",
        "<b>Handler filename mismatch:</b> Weekly Digest used wrong zip entry — CloudWatch import error on first invocation, corrected in one redeploy",
    ]:
        right.append(Paragraph(inc, s["bulsm"]))

    t2 = Table([[left, right]], colWidths=[3.55*inch, 3.55*inch])
    t2.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(t2)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 12 DOCUMENTATION SYSTEM
# ══════════════════════════════════════════════════════════════════════════════
def documentation(s):
    els = []
    els.append(Banner("12 — Documentation System",
        "Changelog · handovers · incident log · RCA · runbooks — all version-controlled", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    # Intro
    els.append(Paragraph(
        "An AI-dependent system that restarts from zero each session needs a different kind of documentation. "
        "Every doc in this repo serves a specific function — not bureaucracy, but continuity infrastructure.",
        s["sm"]))
    els.append(Spacer(1, 0.1*inch))

    # Two-column layout
    left = []

    # Doc types table
    left.append(Paragraph("Document Registry", s["h3a"]))
    docs = [
        ["Document",          "Purpose"],
        ["HANDOVER_LATEST.md","Current state snapshot: version, open threads, last decisions. Read at session start."],
        ["CHANGELOG.md",      "Every version bump with what changed, what was fixed, and why. 80+ entries."],
        ["INCIDENT_LOG.md",   "All production incidents with severity, TTD, TTR, data loss status, and root cause."],
        ["docs/rca/",         "Full Root Cause Analysis per incident. Structured: timeline, contributing factors, fix, prevention."],
        ["RUNBOOK.md",        "Step-by-step ops: deploy a Lambda, rotate secrets, trigger backfill, reset alarms."],
        ["ARCHITECTURE.md",   "System design, data flow diagrams, source-of-truth domain model."],
        ["SCHEMA.md",         "DynamoDB key patterns, field names, reserved word workarounds."],
        ["MCP_TOOL_CATALOG.md","All 124 MCP tools: description, inputs, source data, last updated."],
        ["FEATURES.md",       "Every shipped feature with status, version, and design notes."],
    ]
    t = para_table(docs, [1.6*inch, 2.5*inch], bg=ACCENT2)
    left.append(t)

    right = []

    # Handover count visual
    right.append(Paragraph("The Handover System", s["h3a"]))
    right.append(Paragraph(
        "~80 Claude sessions, ~80 context resets. The handover file is the continuity layer — "
        "written at the end of every session, read at the start of the next. "
        "Without it, every session restarts from zero. With it, each session builds on the last.",
        s["sm"]))
    right.append(Spacer(1, 0.07*inch))

    # Stats boxes
    stat_data = [
        ("80+", "handover files"),
        ("80+", "CHANGELOG entries"),
        ("20+", "incidents logged"),
        ("3",   "full RCAs written"),
    ]
    stat_cells = []
    for val, lbl in stat_data:
        cell = [
            Paragraph(f'<font color="{ACCENT.hexval()}"><b>{val}</b></font>',
                      ParagraphStyle("sv", fontName="Helvetica-Bold", fontSize=14,
                                     leading=17, alignment=1)),
            Paragraph(lbl, ParagraphStyle("sl", fontName="Helvetica", fontSize=7,
                                          textColor=GREY_M, leading=9, alignment=1)),
        ]
        stat_cells.append(cell)

    stat_row = Table([stat_cells[:2], stat_cells[2:]], colWidths=[1.55*inch, 1.55*inch])
    stat_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY2),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    right.append(stat_row)
    right.append(Spacer(1, 0.08*inch))

    right.append(Paragraph("Incident Discipline", s["h3a"]))
    right.append(Paragraph(
        "Every production incident is logged with severity (P1–P4), time to detect, "
        "time to resolve, and whether data was lost. P1/P2 incidents get a full RCA document "
        "with contributing factors, timeline, fix applied, and prevention added.",
        s["sm"]))
    right.append(Spacer(1, 0.07*inch))

    # Severity mini table
    sev = [
        ["Level", "Definition"],
        ["P1",    "System broken — no data flowing, MCP completely down"],
        ["P2",    "Major feature broken, data loss risk, or multi-day gap"],
        ["P3",    "Single source affected — degraded but functional"],
        ["P4",    "Cosmetic, minor data quality, or transient error"],
    ]
    t2 = para_table(sev, [0.35*inch, 2.8*inch], bg=NAVY2)
    right.append(t2)
    right.append(Spacer(1, 0.07*inch))

    right.append(Paragraph(
        "<b>Enterprise lens:</b> AI pipelines fail silently — output looks plausible even when broken. "
        "Incident logging + structured RCA is the discipline that catches it.",
        ParagraphStyle("elens", fontName="Helvetica-Oblique", fontSize=7.5,
                       textColor=GREY_M, leading=11, leftIndent=6)))

    outer = Table([[left, right]], colWidths=[4.3*inch, 3.2*inch])
    outer.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    els.append(outer)
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 13 ROADMAP
# ══════════════════════════════════════════════════════════════════════════════
def roadmap(s):
    els = []
    els.append(Banner("13 — Roadmap", "What's next", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    els.append(Paragraph("Near-Term", s["h3a"]))
    near = [
        ["Feature",               "Status",     "What it adds"],
        ["Monarch Money",         "Auth done",  "Financial data as health input: spend, savings rate, net worth alongside health scores"],
        ["Reward System (Ph. 4)", "Partial",    "User-defined rewards triggered by Character Sheet milestones — weekend away, spa day, new gear, experience events"],
        ["Conversational Coach",  "Designed",   "iOS Shortcut → voice check-in → Lambda → Claude → structured journal entry"],
        ["Google Calendar",       "Designed",   "Demand-side context: meeting load, travel days, and schedule density as health inputs"],
        ["LLM Failover Router",   "Planned",    "If Anthropic API is unavailable, a router Lambda retries with OpenAI GPT-4o as fallback — keeps all 9 weekly emails firing even during outages"],
    ]
    t = para_table(near, [1.5*inch, 0.85*inch, 4.75*inch])
    els.append(t)
    els.append(Spacer(1, 0.1*inch))

    els.append(Paragraph("Intelligence Layer", s["h3a"]))
    h2 = [
        ["Feature",                  "Description"],
        ["Predictive Anomaly",       "Prophet/scikit-learn personal forecasting: 'HRV is 15% lower than expected given training load'"],
        ["Causal Inference Engine",  "Bayesian causal graph — does exercise cause better sleep, or vice versa? (DoWhy library)"],
        ["Digital Twin / Simulation","'What if I increased Zone 2 to 4hr/week?' Projects outcomes from personal response curves"],
        ["Semantic Search",          "Embeddings across journal, Chronicle, Board commentary — find every mention of a topic"],
    ]
    t2 = para_table(h2, [1.8*inch, 5.3*inch], bg=ACCENT2)
    els.append(t2)
    els.append(Spacer(1, 0.1*inch))

    els.append(Paragraph("Open-Source Framework", s["h3a"]))
    for o in [
        "Config-driven Lambda ingest templates (any OAuth2 API → same pattern)",
        "Single-table DynamoDB health schema with source-of-truth domain model",
        "MCP tool scaffolding + Board of Directors persona pattern",
        "Character Sheet engine (any weighted pillar set, any domain)",
        "The Chronicle blog engine (any AI narrator persona)",
    ]:
        els.append(Paragraph(o, s["bulsm"]))
    els.append(PageBreak())
    return els


# ══════════════════════════════════════════════════════════════════════════════
# 13 KEY LEARNINGS
# ══════════════════════════════════════════════════════════════════════════════
def key_learnings(s):
    els = []
    els.append(Banner("14 — Key Learnings",
        "Patterns from ~80 sessions of building with AI", acc=PURPLE))
    els.append(Spacer(1, 0.1*inch))

    learnings = [
        ("One person can go end-to-end", ACCENT,
         "Design, infrastructure, code, testing, deployment, documentation — all with Claude "
         "as the engineering partner. For greenfield builds, AI-assisted development doesn't "
         "just speed things up — it changes what's feasible for one person.",
         "Enterprise lens: Small-team AI pilots are more viable than you think. "
         "The bottleneck isn't headcount — it's context and iteration speed."),
        ("Handover docs are infrastructure", ACCENT2,
         "~80 sessions means ~80 context resets. HANDOVER_LATEST.md is the most important file "
         "in the repo. Without it, every session restarts from zero. Writing it consistently "
         "compounds — by v2.80 it contains a precise snapshot of every open thread.",
         "Enterprise lens: AI-assisted teams need session continuity protocols. "
         "The equivalent of a handover doc is a standard your org should define before scaling."),
        ("Configuration over code", GOLD,
         "Board of Directors personas, Character Sheet weights, source-of-truth domains — all S3 "
         "JSON config. No Lambda redeploy to change an expert voice or adjust a pillar weight. "
         "The right default for anything policy-like.",
         "Enterprise lens: AI persona and prompt governance should be config, not code — "
         "so non-engineers can tune model behaviour without touching a deployment pipeline."),
        ("Observability from day one", GREEN_S,
         "35 alarms, 30 DLQs, structured logging, and a freshness checker — all built alongside "
         "features, not retrofitted. All 3 production incidents resolved <1hr because the signal "
         "was already there.",
         "Enterprise lens: AI pipelines need the same instrumentation discipline as any "
         "service. Silent AI failures are worse than silent code failures — the output looks plausible."),
        ("$3/month is a design constraint, not a side effect", ORANGE,
         "Every resource choice evaluated against a $20/month hard cap. "
         "Serverless + on-demand is the right default for this invocation class. "
         "The constraint made the architecture better.",
         "Enterprise lens: Cost ceilings force good serverless design. "
         "A $20/mo personal project and a $200k/yr enterprise workload share the same patterns."),
        ("The dual-use value was unplanned", PURPLE,
         "Every AI feature — personas, adaptive emails, gamification — also tested something "
         "enterprise-relevant: prompt engineering under real constraints, structured extraction "
         "at scale, graceful error handling under uncertainty. The overlap wasn't designed in. "
         "It's just what building real things with AI looks like.",
         "Enterprise lens: The best AI training for your team is building something real — "
         "not a workshop, not a sandbox. Real stakes surface the real problems."),
    ]

    ent_style = ParagraphStyle("ent", fontName="Helvetica-Oblique", fontSize=7.5,
                                textColor=GREY_M, leading=11, leftIndent=8,
                                spaceBefore=3, spaceAfter=0)
    ent_label = ParagraphStyle("entl", fontName="Helvetica-Bold", fontSize=7.5,
                                textColor=ACCENT2, leading=11, leftIndent=8)

    for title, color, body, enterprise in learnings:
        content = [
            Paragraph(f'<b>{title}</b>', s["h3"]),
            Paragraph(body, s["sm"]),
            Paragraph(enterprise, ent_style),
        ]
        row = Table(
            [[Paragraph(f'<font color="{color.hexval()}">●</font>', s["body"]), content]],
            colWidths=[0.2*inch, 6.85*inch])
        row.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        els.append(row)

    els.append(Spacer(1, 0.1*inch))
    els.append(HRFlowable(width="100%", thickness=0.5, color=GREY_M))
    els.append(Spacer(1, 0.12*inch))

    class CTA(Flowable):
        def wrap(self, aw, ah): self.aw = aw; return aw, 74
        def draw(self):
            c = self.canv
            c.setFillColor(NAVY2); c.roundRect(0, 0, self.aw, 70, 10, stroke=0, fill=1)
            c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(self.aw/2, 46, "The system is live right now.")
            c.setFillColor(WHITE); c.setFont("Helvetica", 9)
            c.drawCentredString(self.aw/2, 26,
                "Everything in this presentation came from a live system. "
                "Ask anything — I can query it via Claude right now.")

    els.append(CTA())
    els.append(Spacer(1, 0.15*inch))
    els.append(Paragraph("M. Walker  ·  2026",
        ParagraphStyle("end", fontName="Helvetica", fontSize=9,
                       textColor=GREY_M, alignment=TA_CENTER)))
    return els


# ══════════════════════════════════════════════════════════════════════════════
# BUILD
# ══════════════════════════════════════════════════════════════════════════════
def build(out):
    doc = SimpleDocTemplate(
        out, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.6*inch,   bottomMargin=0.75*inch,
        title="Life Platform — Health Intelligence System",
        author="M. Walker", subject="AI-Assisted Development")

    s = S()
    story = []
    story += cover(s)
    story += toc(s)
    story += the_story(s)
    story += part_one(s)
    story += week_in_life(s)
    story += why_not_apps(s)
    story += what_it_surfaces(s)
    story += why_tools(s)
    story += features(s)
    story += gamification_page(s)
    story += part_two(s)
    story += architecture(s)
    story += aws_components(s)
    story += security_ops(s)
    story += data_model(s)
    story += ai_integration(s)
    story += resiliency(s)
    story += documentation(s)
    story += roadmap(s)
    story += key_learnings(s)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"✓ PDF built → {out}")


if __name__ == "__main__":
    build("/mnt/user-data/outputs/LifePlatform_ShowAndTell_v4.pdf")
