"""
HP-13: OG Image Generator Lambda

Generates 6 data-driven 1200x630 PNG OG images from public_stats.json.
Runs daily at 11:30am PT (19:30 UTC) after the daily brief updates stats.

Images:  og-home.png, og-sleep.png, og-glucose.png,
         og-training.png, og-character.png, og-nutrition.png
Output:  s3://matthew-life-platform/site/assets/images/
"""
import json
import io
import os
import time
import boto3
from PIL import Image, ImageDraw, ImageFont

REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
CF_DIST_ID = os.environ.get("CF_DISTRIBUTION_ID", "E3S424OXQZ8NBE")

s3 = boto3.client("s3", region_name=REGION)

# Fonts — bundled as TTF in the deployment package
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_font_cache = {}


def _font(name, size):
    key = (name, size)
    if key not in _font_cache:
        path = os.path.join(FONT_DIR, name)
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except Exception:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# Design tokens
BG = (8, 12, 10)          # #080c0a
TEXT = (232, 240, 232)     # #e8f0e8
MUTED = (138, 170, 144)   # #8aaa90
FAINT = (90, 117, 101)    # #5a7565
GREEN = (34, 197, 94)     # #22c55e
BORDER = (14, 26, 18)     # subtle line

FONT_DISPLAY = "bebas-neue-400.ttf"
FONT_MONO = "space-mono-400.ttf"
FONT_MONO_BOLD = "space-mono-700.ttf"

W, H = 1200, 630


def _base_image():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # Top accent line
    draw.rectangle([0, 0, W, 3], fill=GREEN)
    # Bottom bar
    draw.rectangle([0, H - 40, W, H], fill=(6, 10, 8))
    return img, draw


def _draw_header(draw, page_label):
    draw.text((48, 28), "averagejoematt.com", fill=MUTED, font=_font(FONT_MONO, 13))
    draw.text((48, 52), page_label.upper(), fill=GREEN, font=_font(FONT_MONO, 11))


def _draw_metric(draw, x, y, value, label, color=TEXT):
    draw.text((x, y), str(value), fill=color, font=_font(FONT_DISPLAY, 56))
    draw.text((x, y + 60), label, fill=MUTED, font=_font(FONT_MONO, 11))


def _draw_footer(draw, stats):
    days_in = stats.get("platform", {}).get("days_in", 0)
    draw.text((48, H - 30), f"Day {days_in}", fill=FAINT, font=_font(FONT_MONO, 11))
    draw.text((W - 48, H - 30), "updated daily by life-platform",
              fill=FAINT, font=_font(FONT_MONO, 11), anchor="ra")


def _fmt(val, decimals=0, suffix=""):
    if val is None:
        return "\u2014"
    if decimals == 0:
        return f"{int(round(val))}{suffix}"
    return f"{round(val, decimals)}{suffix}"


def build_home(stats):
    img, draw = _base_image()
    _draw_header(draw, "The Measured Life")

    journey = stats.get("journey", {})
    vitals = stats.get("vitals", {})
    platform = stats.get("platform", {})

    # Title
    draw.text((48, 100), "AVERAGEJOEMATT", fill=TEXT, font=_font(FONT_DISPLAY, 72))

    # Subtitle
    draw.text((48, 180), "One man. 25 data sources. Total transparency.",
              fill=MUTED, font=_font(FONT_MONO, 14))

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
    draw.text((48, 180), "Eight Sleep x Whoop cross-referenced.",
              fill=MUTED, font=_font(FONT_MONO, 14))

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
    draw.text((48, 180), "Continuous glucose monitoring. Dexcom Stelo.",
              fill=MUTED, font=_font(FONT_MONO, 14))

    # Glucose-specific data may not be in public_stats — use placeholders
    draw.text((48, 280), "Time-in-range, variability, meal responses.",
              fill=FAINT, font=_font(FONT_MONO, 13))
    draw.text((48, 310), "Real CGM data. Updated daily.",
              fill=FAINT, font=_font(FONT_MONO, 13))

    _draw_footer(draw, stats)
    return img


def build_training(stats):
    img, draw = _base_image()
    _draw_header(draw, "Training Load")

    training = stats.get("training", {})

    draw.text((48, 100), "TRAINING", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Whoop strain x Strava volume x recovery.",
              fill=MUTED, font=_font(FONT_MONO, 14))

    z2 = training.get("zone2_this_week_min")
    _draw_metric(draw, 48, 260, _fmt(z2, 0, " min"), "ZONE 2 THIS WEEK")
    _draw_metric(draw, 380, 260, _fmt(training.get("acwr"), 1), "ACWR")
    _draw_metric(draw, 620, 260, training.get("form_status", "\u2014").upper(), "FORM")

    _draw_footer(draw, stats)
    return img


def build_character(stats):
    img, draw = _base_image()
    _draw_header(draw, "Character Sheet")

    draw.text((48, 100), "THE SCORE", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "Gamified health tracking. 7 pillars. Real XP.",
              fill=MUTED, font=_font(FONT_MONO, 14))

    platform = stats.get("platform", {})
    _draw_metric(draw, 48, 260, _fmt(platform.get("tier0_streak"), 0), "TIER-0 STREAK", GREEN)
    _draw_metric(draw, 380, 260, _fmt(platform.get("days_in"), 0), "DAYS IN")

    _draw_footer(draw, stats)
    return img


def build_nutrition(stats):
    img, draw = _base_image()
    _draw_header(draw, "Nutrition Observatory")

    draw.text((48, 100), "NUTRITION", fill=TEXT, font=_font(FONT_DISPLAY, 72))
    draw.text((48, 180), "MacroFactor data. Calories, protein, deficit status.",
              fill=MUTED, font=_font(FONT_MONO, 14))

    vitals = stats.get("vitals", {})
    _draw_metric(draw, 48, 260, _fmt(vitals.get("weight_lbs"), 1, " lbs"), "CURRENT WEIGHT")

    _draw_footer(draw, stats)
    return img


PAGES = [
    ("og-home", build_home),
    ("og-sleep", build_sleep),
    ("og-glucose", build_glucose),
    ("og-training", build_training),
    ("og-character", build_character),
    ("og-nutrition", build_nutrition),
]


def lambda_handler(event, context):
    # Read public_stats.json
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="site/public_stats.json")
        stats = json.loads(resp["Body"].read())
    except Exception as e:
        print(f"[ERROR] Failed to read public_stats.json: {e}")
        # Use empty stats — images will show placeholder dashes
        stats = {}

    generated = []
    for name, builder in PAGES:
        try:
            img = builder(stats)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"site/assets/images/{name}.png",
                Body=buf.read(),
                ContentType="image/png",
                CacheControl="max-age=86400",
            )
            generated.append(name)
            print(f"[OK] Generated {name}.png")
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

    return {"statusCode": 200, "body": f"Generated {len(generated)}/{len(PAGES)} OG images"}
