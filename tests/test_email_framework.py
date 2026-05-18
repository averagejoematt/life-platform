"""tests/test_email_framework.py — Phase 4.10 shared email scaffolding."""

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import email_framework as ef  # noqa: E402


def test_envelope_has_doctype_head_body():
    html = ef.email_envelope("T", "S", "<p>x</p>")
    assert html.startswith("<!DOCTYPE html>")
    assert "<head>" in html
    assert "<body" in html
    assert "</body></html>" in html


def test_envelope_includes_title_and_subtitle():
    html = ef.email_envelope("Weekly Report", "May 12 → May 18", "<p>x</p>")
    assert "Weekly Report" in html
    assert "May 12 → May 18" in html


def test_envelope_includes_body():
    html = ef.email_envelope("T", "S", "<div id='unique-marker'>OK</div>")
    assert "unique-marker" in html


def test_envelope_dark_mode_opt_in():
    plain = ef.email_envelope("T", "S", "<p>x</p>")
    dark = ef.email_envelope("T", "S", "<p>x</p>", include_dark_mode=True)
    assert "prefers-color-scheme" not in plain
    assert "prefers-color-scheme" in dark


def test_section_includes_emoji_and_title():
    s = ef.section("Sleep", "😴", "<p>content</p>")
    assert "😴 Sleep" in s
    assert "<p>content</p>" in s


def test_row_label_value_delta():
    r = ef.row("Avg duration", "7h 12m", "+0:18")
    assert "Avg duration" in r
    assert "7h 12m" in r
    assert "+0:18" in r
    assert "<tr" in r and "</tr>" in r


def test_row_highlight_changes_background():
    plain = ef.row("x", "1")
    highlight = ef.row("x", "1", highlight=True)
    assert plain != highlight
    # highlight uses warm background; plain uses container white
    assert "#fff8e7" in highlight
    assert "#fff8e7" not in plain


def test_kv_table_wraps_rows():
    rows = [ef.row("a", "1"), ef.row("b", "2")]
    t = ef.kv_table(rows)
    assert t.startswith("<table")
    assert "a" in t and "b" in t
    assert "1" in t and "2" in t


def test_info_box_amber_default():
    box = ef.info_box("<p>warning</p>")
    assert "warning" in box
    assert "#f59e0b" in box  # amber border


def test_info_box_info_variant():
    box = ef.info_box("<p>note</p>", variant="info")
    assert "#4a6cf7" in box  # info border


def test_paragraph_bold():
    p_plain = ef.paragraph("hello")
    p_bold = ef.paragraph("hello", bold=True)
    assert "font-weight:400" in p_plain
    assert "font-weight:700" in p_bold


def test_dark_mode_css_has_media_query():
    css = ef.dark_mode_css()
    assert "@media" in css
    assert "prefers-color-scheme: dark" in css
    assert "<style>" in css


def test_full_email_assembles_cleanly():
    """End-to-end smoke: compose a small email and verify it parses as HTML."""
    body = (
        ef.section("Test Section", "📊", ef.kv_table([
            ef.row("Metric A", "100", "+5"),
            ef.row("Metric B", "200", "-3"),
        ]))
        + ef.info_box(ef.paragraph("Important callout", bold=True))
    )
    html = ef.email_envelope("Test Email", "test subtitle", body, include_dark_mode=True)
    # Should be well-formed-ish
    assert html.count("<!DOCTYPE html>") == 1
    assert html.count("<body") == 1
    assert html.count("</body>") == 1
    # Tags should balance (rough check)
    open_divs = html.count("<div")
    close_divs = html.count("</div>")
    assert open_divs == close_divs, f"div balance: {open_divs} open, {close_divs} close"
