"""content/chronicle_revision.py — an approval binds to the exact text it was given for (owner ruling 2026-11-06).

THE RULING. "Old approval links must not authorize a different revision."

The preview email's approve link carried only the row's date and its stored token, and chronicle-approve published
whatever the row held when the link was clicked. So an edit to a stored draft (a privacy patch, a repair) left every
old link live, approving text the owner never saw.

A draft's REVISION ID is a hash of everything the approve path can publish from that row. The link carries the id it was
minted for; chronicle-approve recomputes it from the row at click time and refuses a mismatch. Nothing is stored, so
there is no second copy to fall out of step: any change to a published field retires every link minted before it. A
link with no id (every link mailed before this shipped) is refused the same way. Pure functions; no boto3.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# Every row field a publish reads: the article, its manifest, the mailed copy, the recap, the share kit, the Panel script.
REVISION_FIELDS = (
    "title",
    "stats_line",
    "content_markdown",
    "content_html",
    "draft_journal_post_html",
    "draft_journal_post_key",
    "draft_journal_posts_json",
    "draft_email_html",
    "draft_recap_json",
    "draft_share_kit_json",
    "desk_episode_json",
)
REVISION_PARAM = "rev"
ID_LENGTH = 32


def revision_id(item: Mapping[str, Any]) -> str:
    """The revision id of a stored chronicle row: stable across reads, different after any publishable field changes.
    An absent field and an empty one hash alike, so a writer that drops an empty blob does not retire a link."""
    canon = {f: str(item.get(f) or "") for f in REVISION_FIELDS}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:ID_LENGTH]
