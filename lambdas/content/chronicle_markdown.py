"""content/chronicle_markdown.py — the chronicle's markdown → HTML renderer, the ONE copy (#6193).

Moved out of ``emails/chronicle_render.py`` (which re-exports it, so every existing caller is unchanged) so that a pure
consumer — the second-edition record (``content.chapter_editions``) and the snapshot exporter that re-checks an
edition's bytes — renders exactly as the journal page and the mailed copy do without importing the chronicle Lambda's
helpers. Standard library only.
"""

import re


def markdown_to_html(md_text):
    """Convert Elena's markdown prose to clean HTML for email and journal."""
    lines = md_text.strip().split("\n")
    html_parts = []
    in_blockquote = False
    bq_buffer = []

    for line in lines:
        stripped = line.strip()

        # Blockquotes (Board interviews). #2221: the marker is ">" — the space after
        # it is OPTIONAL in markdown. Requiring "> " rendered an interview written as
        # ">Park said..." as ordinary prose with a stray ">" in front of it.
        if stripped.startswith(">"):
            if not in_blockquote:
                in_blockquote = True
                bq_buffer = []
            bq_buffer.append(stripped[1:].lstrip())
            continue
        elif in_blockquote:
            # End of blockquote
            bq_text = " ".join(bq_buffer)
            # Convert **bold** and *italic*
            bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
            bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
            html_parts.append(f"<blockquote>{bq_text}</blockquote>")
            in_blockquote = False
            bq_buffer = []

        # Horizontal rule
        if stripped == "---":
            html_parts.append("<hr>")
            continue

        # Empty line
        if not stripped:
            continue

        # Italic line (closing signature like *Week N of The Measured Life*)
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            inner = stripped[1:-1]
            html_parts.append(f'<p class="signature"><em>{inner}</em></p>')
            continue

        # Regular paragraph — apply inline formatting
        text = stripped
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        html_parts.append(f"<p>{text}</p>")

    # Flush any remaining blockquote
    if in_blockquote and bq_buffer:
        bq_text = " ".join(bq_buffer)
        bq_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", bq_text)
        bq_text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", bq_text)
        html_parts.append(f"<blockquote>{bq_text}</blockquote>")

    return "\n".join(html_parts)
