"""chronicle_share_kit.py — #405: the per-chronicle "ready-to-post" share kit.

When a chronicle publishes, the pipeline additionally produces a machine-made kit so
posting is a 60-second paste (or skipped guilt-free) rather than a recurring content
chore. The kit is text + JSON only — no Pillow, no AI — so it builds inside the email
stack (which has neither). The honest-stats OG CARD is drawn separately by the daily
og-image sweep through the #595 card engine (`og_moments._sweep_chronicles`); the kit
just references its stable URL.

Honesty contract (matches the chronicle's own gates):
  - Every field is derived from values ALREADY on the published installment — the
    title, the honest stats line (e.g. "Weight: 300.8 lbs | Week Grade: avg 57 | T0
    Streak: 0 days"), an excerpt of the published prose, the canonical post URL. No new
    numbers, no new claims, nothing narrated here.
  - The honest-stats line IS the creative: a week graded 57 with a broken streak is the
    point. Never sanitized.
  - One channel only, no auto-posting — the human step stays optional by design.

This module is pure/deterministic (re-runnable, byte-stable for a given installment) so
it is trivially unit-testable and safe to call on both the publish and approve paths.
"""

import re
from datetime import datetime, timezone

from utm import with_utm  # #1621 — the ONE canonical outbound UTM tagger

SITE_BASE = "https://averagejoematt.com"
# The single channel the kit is shaped for (no auto-post; one paste). Kept as data so a
# future channel switch is a one-line change, not a rewrite.
CHANNEL = "x"

# Where the kit + its card live under the already-CloudFront-routed /moments/* prefix
# (S3GeneratedOrigin). The card slug matches og_moments._post_slug(canonical_url).
KIT_PREFIX = "generated/moments/share-kits"


def _excerpt(markdown_or_html, limit=280):
    """First paragraph of the published prose, plain-text, capped. Strips markdown
    heading/emphasis marks and any HTML tags so the excerpt is paste-clean."""
    text = str(markdown_or_html or "")
    # Drop a leading stats line / title block: take the first substantial paragraph.
    text = re.sub(r"<[^>]+>", " ", text)  # strip HTML tags if body_html was passed
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    para = ""
    for b in blocks:
        cleaned = re.sub(r"^[#>*_\-\s]+", "", b).strip()
        # Skip a bracketed/stats-only or title-only line; want real prose.
        if len(cleaned) >= 60 and "|" not in cleaned[:40]:
            para = cleaned
            break
    if not para and blocks:
        para = re.sub(r"^[#>*_\-\s]+", "", blocks[0]).strip()
    para = re.sub(r"\s+", " ", para).strip()
    if len(para) > limit:
        para = para[: limit - 1].rstrip() + "…"
    return para


def _slug(canonical_url):
    """https://…/journal/posts/week-05/ -> week-05 (matches the OG card slug)."""
    path = str(canonical_url or "").rstrip("/")
    return (path.split("/") or ["post"])[-1] or "post"


def build_kit(*, title, stats_line, label, date_str, canonical_url, excerpt_source, week_number=None, cover_url=""):
    """Build the ready-to-post kit dict from already-published installment fields.

    excerpt_source: the installment's content_markdown (preferred) or body_html.
    cover_url: the post's existing og:image (editorial cover or the site default) — an
      immediate fallback image; the honest-stats card at `card_url` is filled in by the
      next daily og sweep.
    """
    slug = _slug(canonical_url)
    stats_line = str(stats_line or "").strip()
    title = str(title or "The Measured Life").strip()
    label = str(label or "").strip()
    excerpt = _excerpt(excerpt_source)

    card_url = f"{SITE_BASE}/moments/assets/chronicle-{slug}.png"

    # The paste-ready caption — only published values, honest framing, the link last.
    caption_bits = [f"“{title}”" + (f" — {label}" if label else "")]
    if stats_line:
        caption_bits.append(stats_line)
    if excerpt:
        caption_bits.append(excerpt)
    # #1621: the pasted caption link is UTM-tagged so a signup arriving from the
    # manual share is attributable. `canonical_url` itself is returned UNTAGGED in the
    # kit dict below — it's the post's identity (used for the card slug and the S3 key),
    # not a click target, and tagging it would fork the slug.
    caption_bits.append(
        "The honest week, every failure included → " + with_utm(canonical_url, source=CHANNEL, medium="social", campaign="chronicle")
    )
    caption = "\n\n".join(caption_bits)

    return {
        "week": week_number,
        "label": label,
        "title": title,
        "date": date_str,
        "channel": CHANNEL,
        "canonical_url": canonical_url,
        "excerpt": excerpt,
        "stats_line": stats_line,
        "cover_url": cover_url or f"{SITE_BASE}/assets/images/og-home.png",
        "card_url": card_url,
        "caption": caption,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def kit_s3_key(canonical_url):
    """The stable generated location for the kit JSON (served via /moments/*)."""
    return f"{KIT_PREFIX}/{_slug(canonical_url)}/kit.json"


def kit_email_block(kit):
    """A copy-paste HTML block for the approval/preview email — the caption in a
    selectable box, the card + canonical URLs, and the honest-stats line. Zero extra
    generation steps: the whole kit is right there to copy or ignore."""
    caption = (kit.get("caption") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    stats = (kit.get("stats_line") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""
  <div style="background:#0f1512;border-radius:8px;border:1px solid rgba(230,237,243,0.10);padding:24px 28px;margin-bottom:16px;">
    <p style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#22c55e;margin:0 0 12px;">Share kit — one paste, or skip</p>
    <p style="font-size:12px;color:#8b949e;margin:0 0 10px;">Machine-made from this week's published numbers only. Posting is optional by design.</p>
    <pre style="white-space:pre-wrap;font-family:-apple-system,sans-serif;font-size:13px;line-height:1.6;color:#e8f0e8;background:#161b22;border-radius:6px;padding:14px 16px;margin:0 0 12px;">{caption}</pre>
    <p style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#f0b429;margin:0 0 6px;">{stats}</p>
    <p style="font-size:11px;color:#8b949e;margin:0;line-height:1.7;">
      Card: <a href="{kit.get('card_url', '')}" style="color:#8aaa90;">{kit.get('card_url', '')}</a><br>
      Post: <a href="{kit.get('canonical_url', '')}" style="color:#8aaa90;">{kit.get('canonical_url', '')}</a>
    </p>
  </div>"""
