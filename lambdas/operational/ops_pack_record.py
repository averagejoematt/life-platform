"""operational/ops_pack_record.py — the Monday ops pack as readable text for its log record (#6176, item 6c).

While the outbound trial's ``OPS_MONDAY_PACK`` item is on, ``traffic_digest_lambda`` writes the pack to its own log
group (``[traffic-digest] ops_pack_record``) instead of emailing it; this turns the pack's HTML into that text. Kept
beside the digest so the digest stays under the 1,000-line module ceiling (#1665). Pure.
"""

from __future__ import annotations


def pack_text(html_body: str, limit: int = 200_000) -> str:
    """#6176: the ops pack's HTML as readable text for its log record (tags dropped, entities decoded, blank runs folded)."""
    import html as _html_mod
    import re as _re

    text = _re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", html_body or "")
    text = _re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = _html_mod.unescape(_re.sub(r"<[^>]+>", " ", text))
    lines = [" ".join(ln.split()) for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)[:limit]
