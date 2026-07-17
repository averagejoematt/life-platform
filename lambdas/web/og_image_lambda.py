"""
HP-13: OG Image Generator Lambda

Generates 6 data-driven 1200x630 PNG OG images from public_stats.json.
Runs daily at 11:30am PT (19:30 UTC) after the daily brief updates stats.

Images:  og-home.png, og-sleep.png, og-glucose.png,
         og-training.png, og-character.png, og-nutrition.png
Output:  s3://matthew-life-platform/site/assets/images/
"""

import io
import json
import os
import time

import boto3

# #595 (ADR-114): the shared card engine is the single place brand cards are drawn.
# The daily page cards delegate their chrome to it so every off-site card — daily,
# moment (og_moments), character (#420), chronicle (#405) — shares one template.
from web import card_engine

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
CF_DIST_ID = os.environ.get("CF_DISTRIBUTION_ID", "E3S424OXQZ8NBE")

s3 = boto3.client("s3", region_name=REGION)

# Design tokens + fonts + primitives now live in card_engine. Re-exported here under
# the historic names so the daily cards below (and og_moments, which imports this
# module) render byte-identically to before the extraction.
_font = card_engine.font
BG = card_engine.BG
TEXT = card_engine.TEXT
MUTED = card_engine.MUTED
FAINT = card_engine.FAINT
GREEN = card_engine.GREEN
BORDER = card_engine.BORDER
FONT_DISPLAY = card_engine.FONT_DISPLAY
FONT_MONO = card_engine.FONT_MONO
FONT_MONO_BOLD = card_engine.FONT_MONO_BOLD
W, H = card_engine.W, card_engine.H


def _base_image():
    return card_engine.base_canvas()


def _draw_header(draw, page_label):
    card_engine.draw_header(draw, page_label)


def _draw_metric(draw, x, y, value, label, color=TEXT):
    card_engine.draw_metric(draw, x, y, value, label, color=color)


def _draw_footer(draw, stats):
    days_in = stats.get("platform", {}).get("days_in", 0)
    card_engine.draw_footer(draw, left_text=f"Day {days_in}", right_text="updated daily by life-platform")


def _fmt(val, decimals=0, suffix=""):
    return card_engine.fmt(val, decimals, suffix)


def build_home(stats):
    img, draw = _base_image()
    _draw_header(draw, "The Measured Life")

    journey = stats.get("journey", {})
    vitals = stats.get("vitals", {})
    platform = stats.get("platform", {})

    # Title
    draw.text((48, 100), "AVERAGEJOEMATT", fill=TEXT, font=_font(FONT_DISPLAY, 72))

    # Subtitle
    draw.text((48, 180), "One man. 25 data sources. Total transparency.", fill=MUTED, font=_font(FONT_MONO, 14))

    # Metrics row
    lost = journey.get("lost_lbs")
    _draw_metric(draw, 48, 260, _fmt(lost, 0, " lbs"), "LOST", GREEN)
    _draw_metric(draw, 320, 260, _fmt(vitals.get("hrv_ms"), 0, " ms"), "HRV")
    _draw_metric(draw, 580, 260, _fmt(platform.get("days_in"), 0), "DAYS IN")
    _draw_metric(draw, 820, 260, _fmt(platform.get("tier0_streak"), 0), "STREAK")

    _draw_footer(draw, stats)
    return img


def build_sleep(stats):
    img, draw = _base_image()
    _draw_header(draw, "Sleep Intelligence")

    vitals = stats.get("vitals", {})

    draw.text((48, 100), "SLEEP", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Eight Sleep x Whoop cross-referenced.", fill=MUTED, font=_font(FONT_MONO, 14))

    _draw_metric(draw, 48, 260, _fmt(vitals.get("sleep_hours"), 1, "h"), "AVG DURATION")
    _draw_metric(draw, 320, 260, _fmt(vitals.get("hrv_ms"), 0, " ms"), "HRV")
    _draw_metric(draw, 580, 260, _fmt(vitals.get("recovery_pct"), 0, "%"), "RECOVERY")
    _draw_metric(draw, 820, 260, _fmt(vitals.get("rhr_bpm"), 0, " bpm"), "RHR")

    _draw_footer(draw, stats)
    return img


def build_glucose(stats):
    img, draw = _base_image()
    _draw_header(draw, "Glucose Observatory")

    draw.text((48, 100), "GLUCOSE", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Continuous glucose monitoring. Dexcom Stelo.", fill=MUTED, font=_font(FONT_MONO, 14))

    # Glucose-specific data may not be in public_stats — use placeholders
    draw.text((48, 280), "Time-in-range, variability, meal responses.", fill=FAINT, font=_font(FONT_MONO, 13))
    draw.text((48, 310), "Real CGM data. Updated daily.", fill=FAINT, font=_font(FONT_MONO, 13))

    _draw_footer(draw, stats)
    return img


def build_training(stats):
    img, draw = _base_image()
    _draw_header(draw, "Training Load")

    training = stats.get("training", {})

    draw.text((48, 100), "TRAINING", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Whoop strain x Strava volume x recovery.", fill=MUTED, font=_font(FONT_MONO, 14))

    z2 = training.get("zone2_this_week_min")
    _draw_metric(draw, 48, 260, _fmt(z2, 0, " min"), "ZONE 2 THIS WEEK")
    _draw_metric(draw, 380, 260, _fmt(training.get("acwr"), 1), "ACWR")
    _draw_metric(draw, 620, 260, training.get("form_status", "\u2014").upper(), "FORM")

    _draw_footer(draw, stats)
    return img


def _load_character_stats():
    """Read the computed character_stats.json (written by character-sheet-compute).
    Returns {} on any failure so the card falls back gracefully."""
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="generated/data/character_stats.json")
        return json.loads(resp["Body"].read()) or {}
    except Exception as e:
        print(f"[WARN] character_stats.json read failed (character card falls back): {e}")
        return {}


def build_character(stats):
    """#420: the character-sheet card now renders from COMPUTED character stats via the
    #595 engine — level, tier, XP, days active, per-pillar levels — never a narrated
    line and never chronological age (ADR-104 + phenoage privacy). Falls back to the
    platform streak/day figures when character_stats.json isn't available yet."""
    cstats = _load_character_stats()
    if cstats.get("character"):
        return card_engine.render("character", cstats)

    # Fallback (first days / stats not yet computed): the historic minimal card.
    img, draw = _base_image()
    _draw_header(draw, "Character Sheet")
    draw.text((48, 100), "THE SCORE", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Gamified health tracking. 7 pillars. Real XP.", fill=MUTED, font=_font(FONT_MONO, 14))
    platform = stats.get("platform", {})
    _draw_metric(draw, 48, 260, _fmt(platform.get("tier0_streak"), 0), "TIER-0 STREAK", GREEN)
    _draw_metric(draw, 380, 260, _fmt(platform.get("days_in"), 0), "DAYS IN")
    _draw_footer(draw, stats)
    return img


def build_nutrition(stats):
    img, draw = _base_image()
    _draw_header(draw, "Nutrition Observatory")

    draw.text((48, 100), "NUTRITION", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "MacroFactor data. Calories, protein, deficit status.", fill=MUTED, font=_font(FONT_MONO, 14))

    vitals = stats.get("vitals", {})
    _draw_metric(draw, 48, 260, _fmt(vitals.get("weight_lbs"), 1, " lbs"), "CURRENT WEIGHT")

    _draw_footer(draw, stats)
    return img


def build_mind(stats):
    img, draw = _base_image()
    _draw_header(draw, "Inner Life Observatory")
    draw.text((48, 100), "INNER LIFE", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Mood, willpower, connection, vice streaks.", fill=MUTED, font=_font(FONT_MONO, 14))
    platform = stats.get("platform", {})
    _draw_metric(draw, 48, 260, _fmt(platform.get("days_in"), 0), "DAYS TRACKED")
    _draw_footer(draw, stats)
    return img


def build_labs(stats):
    img, draw = _base_image()
    _draw_header(draw, "Bloodwork Intelligence")
    draw.text((48, 100), "THE LABS", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "74 biomarkers. 7 draws. The ground truth.", fill=MUTED, font=_font(FONT_MONO, 14))
    _draw_metric(draw, 48, 260, "74", "BIOMARKERS")
    _draw_metric(draw, 320, 260, "7", "DRAWS")
    _draw_footer(draw, stats)
    return img


def build_chronicle(stats):
    img, draw = _base_image()
    _draw_header(draw, "The Measured Life")
    draw.text((48, 100), "CHRONICLE", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Weekly dispatches from a health transformation.", fill=MUTED, font=_font(FONT_MONO, 14))
    draw.text((48, 260), "Every Wednesday. Real data. Every failure included.", fill=FAINT, font=_font(FONT_MONO, 13))
    _draw_footer(draw, stats)
    return img


def build_weekly(stats):
    img, draw = _base_image()
    _draw_header(draw, "Weekly Snapshots")
    draw.text((48, 100), "THE WEEK", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Walk the journey one week at a time.", fill=MUTED, font=_font(FONT_MONO, 14))
    platform = stats.get("platform", {})
    _draw_metric(draw, 48, 260, _fmt(platform.get("days_in"), 0), "DAYS IN")
    _draw_footer(draw, stats)
    return img


def build_experiments(stats):
    img, draw = _base_image()
    _draw_header(draw, "N=1 Experiments")
    draw.text((48, 100), "EXPERIMENTS", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Testing protocols against my own data.", fill=MUTED, font=_font(FONT_MONO, 14))
    _draw_footer(draw, stats)
    return img


def build_essay_org_chart(stats):
    """#741 — the flagship career-artifact share card. The essay
    (/journal/essays/org-chart-of-one/) is the piece Matthew publishes externally, and
    its *measured travel* is the story's success metric — so it earns a bespoke card
    instead of the generic home card. Static editorial (like the chronicle card): a
    kicker, the wrapped title, and one honest lede — no fabricated metrics. Rendered
    through the same primitives so it stays byte-consistent with the card family."""
    img, draw = _base_image()
    _draw_header(draw, "Essay")

    draw.text((48, 92), "THE OPERATING SYSTEM, IN PUBLIC", fill=card_engine.AMBER, font=_font(FONT_MONO, 13))
    y = card_engine.draw_title(draw, "The Org Chart of One Human and N Agents", 126, size=64, width=22, max_lines=3)

    lede = "How a one-person production platform is actually run: sessions as mortal"
    lede2 = "employees, deterministic gates holding the keys, the failure log as credibility."
    y = max(y + 20, 430)
    draw.text((48, y), lede, fill=MUTED, font=_font(FONT_MONO, 15))
    draw.text((48, y + 26), lede2, fill=MUTED, font=_font(FONT_MONO, 15))

    card_engine.draw_footer(draw, left_text="an essay", right_text="averagejoematt.com/journal/essays")
    return img


def build_builders(stats):
    img, draw = _base_image()
    _draw_header(draw, "For Builders")
    draw.text((48, 100), "THE BUILD", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "How to build an AI health platform for $13/month.", fill=MUTED, font=_font(FONT_MONO, 14))
    stats.get("platform", {})
    _draw_metric(draw, 48, 260, "116", "MCP TOOLS")
    _draw_metric(draw, 320, 260, "59", "LAMBDAS")
    _draw_metric(draw, 560, 260, "$13", "MONTHLY COST")
    _draw_footer(draw, stats)
    return img


PAGES = [
    ("og-home", build_home),
    ("og-sleep", build_sleep),
    ("og-glucose", build_glucose),
    ("og-training", build_training),
    ("og-character", build_character),
    ("og-nutrition", build_nutrition),
    ("og-mind", build_mind),
    ("og-labs", build_labs),
    ("og-chronicle", build_chronicle),
    ("og-weekly", build_weekly),
    ("og-experiments", build_experiments),
    ("og-builders", build_builders),
    ("og-org-chart", build_essay_org_chart),  # #741 — the career-artifact essay card
]


def lambda_handler(event, context):
    # Read public_stats.json
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="generated/public_stats.json")
        stats = json.loads(resp["Body"].read())
    except Exception as e:
        print(f"[ERROR] Failed to read public_stats.json: {e}")
        # Use empty stats — images will show placeholder dashes
        stats = {}

    generated = []
    for name, builder in PAGES:
        try:
            img = builder(stats)
            # PNG (original — keep for compatibility with crawlers that don't read WebP)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            png_bytes = buf.read()
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"generated/assets/images/{name}.png",
                Body=png_bytes,
                ContentType="image/png",
                CacheControl="max-age=86400",
            )
            # Phase 8.7 (2026-05-16): also emit WebP — 50-60% smaller payload
            # for modern crawlers (Facebook, Twitter, Slack, Discord, iMessage
            # all prefer WebP when offered). Pillow supports WebP natively.
            try:
                wbuf = io.BytesIO()
                img.save(wbuf, format="WebP", quality=80, method=4)
                wbuf.seek(0)
                webp_bytes = wbuf.read()
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=f"generated/assets/images/{name}.webp",
                    Body=webp_bytes,
                    ContentType="image/webp",
                    CacheControl="max-age=86400",
                )
                _shrink = round(100 * (1 - len(webp_bytes) / max(1, len(png_bytes))))
                print(f"[OK] Generated {name}.png ({len(png_bytes)} B) + .webp ({len(webp_bytes)} B, -{_shrink}%)")
            except Exception as we:
                print(f"[WARN] WebP encode failed for {name} (PNG still saved): {we}")
            generated.append(name)
        except Exception as e:
            print(f"[ERROR] Failed to generate {name}: {e}")

    # Invalidate CloudFront for OG images
    if generated:
        try:
            cf = boto3.client("cloudfront", region_name="us-east-1")
            cf.create_invalidation(
                DistributionId=CF_DIST_ID,
                InvalidationBatch={
                    "Paths": {
                        "Quantity": 1,
                        "Items": ["/assets/images/og-*.png"],
                    },
                    "CallerReference": str(int(time.time())),
                },
            )
            print(f"[OK] CloudFront invalidation created for {len(generated)} images")
        except Exception as e:
            print(f"[WARN] CloudFront invalidation failed (non-fatal): {e}")

    # #404: permalinked shareable moments (weekly recap · board answers · graded
    # predictions) — shells + per-moment cards under generated/moments/. Fail-soft:
    # a moments error never blocks the daily page cards.
    moments_n = 0
    try:
        from web.og_moments import sweep_moments

        idx = sweep_moments(s3, stats)
        moments_n = (
            (1 if idx.get("week") else 0) + len(idx.get("qa") or {}) + len(idx.get("predictions") or []) + len(idx.get("chronicles") or {})
        )
    except Exception as e:
        print(f"[WARN] moments sweep failed (non-fatal): {e}")

    # #593: per-coach OG share cards — the engraved portraits travel off-site. Fail-soft:
    # a coach-card error never blocks the daily page/moment cards.
    coach_n = 0
    try:
        from web.og_coach_cards import sweep_coach_cards

        coach_n = len(sweep_coach_cards(s3, S3_BUCKET))
    except Exception as e:
        print(f"[WARN] coach card sweep failed (non-fatal): {e}")

    return {
        "statusCode": 200,
        "body": f"Generated {len(generated)}/{len(PAGES)} OG images + {moments_n} moment(s) + {coach_n} coach card(s)",
    }
