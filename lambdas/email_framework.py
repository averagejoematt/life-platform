"""
email_framework.py — Phase 4.10 (2026-05-16): shared HTML scaffolding for
Life Platform email Lambdas (weekly_digest, monthly_digest, monday_compass,
wednesday_chronicle, weekly_plate, brittany_email, evening_nudge, etc.).

Each email Lambda historically reimplemented:
  - The `<!DOCTYPE html><head>…</head><body>…</body>` envelope
  - The `section(title, emoji, content)` helper
  - The `row(label, value, delta)` table-row helper
  - The `tbl(rows)` wrapper
  - The `info_box(content)` highlighted box (used for insights, tips, etc.)
  - The font-family, base colors, container max-width

These were duplicated across 5+ files (60-70% of identical scaffolding).
This module is the single source of truth. Lambdas can opt in module-by-
module without a forced cutover (helpers are pure functions; existing
local definitions keep working until migrated).

Usage:
    from email_framework import (
        email_envelope, section, row, kv_table, info_box, dark_mode_css
    )

    html = email_envelope(
        title="Weekly Report",
        subtitle="May 12 → May 18, 2026 · Deltas vs prior week",
        body_html=section("Sleep", "😴", kv_table([
            row("Avg duration", "7h 12m", "+0:18"),
            row("Avg score",    "82",     "+3"),
        ])),
    )

Phase 8.8 will add dark-mode CSS — already stubbed via `dark_mode_css` so
callers can opt in early.
"""

from __future__ import annotations


# ── Design tokens ──────────────────────────────────────────────────────────

_FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
_COLORS = {
    "page_bg":    "#f4f4f8",
    "container":  "#ffffff",
    "header_bg":  "linear-gradient(135deg,#1a1a2e 0%,#16213e 100%)",
    "header_fg":  "#ffffff",
    "subhead_fg": "#8892b0",
    "text":       "#333333",
    "muted":      "#666666",
    "heading":    "#1a1a2e",
    "border":     "#e8e8f0",
    "row_alt":    "#fafafa",
    "highlight":  "#fff8e7",
    "amber_bg":   "#fffbeb",
    "amber_brdr": "#f59e0b",
    "amber_fg":   "#92400e",
    "amber_body": "#78350f",
    "info_bg":    "#f0f4ff",
    "info_brdr":  "#4a6cf7",
}


# ── Dark mode CSS (Phase 8.8 placeholder, opt-in) ──────────────────────────

def dark_mode_css() -> str:
    """Return a <style> block that flips key colors under prefers-color-scheme.

    Emit this inside the <head> if the caller wants dark-mode support.
    Most email clients honor prefers-color-scheme; some (Outlook) ignore it.
    """
    return (
        "<style>"
        "@media (prefers-color-scheme: dark) {"
        " body { background:#1a1a1f !important; color:#e5e5e5 !important; }"
        " div[style*='background:#fff'] { background:#22222a !important; color:#e5e5e5 !important; }"
        " div[style*='background:#fafafa'] { background:#2a2a32 !important; }"
        " h1,h2,h3 { color:#f5f5f5 !important; }"
        " td { color:#d5d5d5 !important; }"
        "}"
        "</style>"
    )


# ── Scaffolding helpers ────────────────────────────────────────────────────

def email_envelope(title: str, subtitle: str, body_html: str,
                   include_dark_mode: bool = False) -> str:
    """Wrap content in the standard Life Platform email shell.

    Args:
        title:    Heading shown in the dark gradient header (e.g. "Weekly Report").
        subtitle: Smaller line under the heading (e.g. date range + deltas).
        body_html: The inner content (use section() / kv_table() / row() / info_box() to build).
        include_dark_mode: Add the dark-mode CSS opt-in (Phase 8.8 ready).
    """
    head = "<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    if include_dark_mode:
        head += dark_mode_css()
    head += "</head>"
    return (
        f"<!DOCTYPE html>\n<html>{head}\n"
        f"<body style=\"margin:0;padding:0;background:{_COLORS['page_bg']};"
        f"font-family:{_FONT_STACK};\">\n"
        f"<div style=\"max-width:660px;margin:32px auto;background:{_COLORS['container']};"
        f"border-radius:14px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.09);\">\n"
        f"<div style=\"background:{_COLORS['header_bg']};padding:28px 32px;\">\n"
        f"<h1 style=\"color:{_COLORS['header_fg']};font-size:22px;margin:0 0 4px;\">{title}</h1>\n"
        f"<p style=\"color:{_COLORS['subhead_fg']};font-size:13px;margin:0;\">{subtitle}</p>\n"
        f"</div>\n"
        f"<div style=\"padding:28px 32px;\">\n{body_html}\n</div>\n"
        f"</div>\n</body></html>"
    )


def section(title: str, emoji: str, content: str) -> str:
    """Single content section: emoji + bold underlined title + body."""
    return (
        f"<div style=\"margin-bottom:28px;\">"
        f"<h2 style=\"font-size:15px;font-weight:700;color:{_COLORS['heading']};"
        f"margin:0 0 8px;border-bottom:2px solid {_COLORS['border']};padding-bottom:6px;\">"
        f"{emoji} {title}</h2>"
        f"{content}</div>"
    )


def kv_table(rows: list[str]) -> str:
    """Wrap a list of row() outputs in a styled <table>."""
    return (
        f"<table style=\"width:100%;border-collapse:collapse;"
        f"background:{_COLORS['row_alt']};border-radius:8px;overflow:hidden;\">"
        f"{''.join(rows)}</table>"
    )


def row(label: str, value: str, delta: str = "", highlight: bool = False) -> str:
    """Two-column table row: label + value (+ optional delta indicator)."""
    bg = _COLORS["highlight"] if highlight else _COLORS["container"]
    return (
        f"<tr style=\"background:{bg}\">"
        f"<td style=\"padding:6px 12px;color:{_COLORS['muted']};font-size:13px;\">{label}</td>"
        f"<td style=\"padding:6px 12px;font-size:13px;font-weight:600;\">{value}{delta}</td></tr>"
    )


def info_box(content: str, variant: str = "amber") -> str:
    """Highlighted callout box. variant: 'amber' (default warm) or 'info' (cool)."""
    if variant == "info":
        return (
            f"<div style=\"background:{_COLORS['info_bg']};border-left:4px solid {_COLORS['info_brdr']};"
            f"padding:16px;border-radius:0 8px 8px 0;\">{content}</div>"
        )
    return (
        f"<div style=\"background:{_COLORS['amber_bg']};border:2px solid {_COLORS['amber_brdr']};"
        f"border-radius:10px;padding:16px 20px;margin-bottom:24px;\">{content}</div>"
    )


def paragraph(text: str, bold: bool = False, color: str = None) -> str:
    """Body paragraph with default platform styling."""
    weight = "700" if bold else "400"
    color = color or _COLORS["text"]
    return (
        f"<p style=\"font-size:13px;font-weight:{weight};color:{color};"
        f"line-height:1.6;margin:0 0 8px;\">{text}</p>"
    )
