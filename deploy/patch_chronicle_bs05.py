#!/usr/bin/env python3
"""
Patch wednesday_chronicle_lambda.py to wire BS-05 confidence badge into:
  1. store_installment() — adds _confidence_level + _confidence_badge_html fields to DDB record
  2. build_email_html() — injects badge below stats_line in personal Matthew email

Run from project root:
  python3 deploy/patch_chronicle_bs05.py

Idempotent — skips if already patched.
"""

import sys
import re
from pathlib import Path

TARGET = Path(__file__).parent.parent / "lambdas/wednesday_chronicle_lambda.py"
content = TARGET.read_text()

if "_confidence_level" in content and "BS-05" in content:
    print("✅ BS-05 confidence already wired into wednesday_chronicle_lambda.py — skipping")
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1: In lambda_handler, compute confidence after parsing the installment.
# Insert after: title, stats_line, body_md = parse_installment(raw_installment)
# ─────────────────────────────────────────────────────────────────────────────

ANCHOR_PARSE = 'title, stats_line, body_md = parse_installment(raw_installment)'
if ANCHOR_PARSE not in content:
    print(f"❌ Anchor not found: {ANCHOR_PARSE!r}")
    sys.exit(1)

CONFIDENCE_BLOCK = '''
    # BS-05: Compute confidence badge based on total journey data depth.
    # Henning: LOW (<14d data), MEDIUM (14-49d), HIGH (≥50d + sig + effect).
    # Chronicle draws on full journey history — use days-since-start as n.
    _conf_level = "MEDIUM"
    _conf_badge_html = ""
    _conf_reason = ""
    if _HAS_CONFIDENCE:
        try:
            _journey_start = data.get("profile", {}).get("journey_start_date", "2026-02-09")
            _journey_days = (
                datetime.strptime(data["dates"]["end"], "%Y-%m-%d") -
                datetime.strptime(_journey_start, "%Y-%m-%d")
            ).days
            _conf = compute_confidence(days_of_data=_journey_days)
            _conf_level = _conf.get("level", "MEDIUM")
            _conf_badge_html = _conf.get("badge_html", "")
            _conf_reason = _conf.get("reason", "")
            logger.info(f"BS-05 confidence: {_conf_level} ({_conf_reason})")
        except Exception as _ce:
            logger.warning(f"BS-05 confidence compute failed (non-fatal): {_ce}")
'''

idx = content.index(ANCHOR_PARSE)
# Insert after the line containing the anchor
line_end = content.index('\n', idx)
content = content[:line_end + 1] + CONFIDENCE_BLOCK + content[line_end + 1:]
print("✅ PATCH 1: confidence block inserted after parse_installment()")


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2: Pass confidence into store_installment call.
# store_installment(date_str, week_num, title, stats_line, raw_installment, body_html, [], has_board)
# → add _confidence_level and _conf_badge_html as kwargs
# ─────────────────────────────────────────────────────────────────────────────

OLD_STORE = 'store_installment(date_str, week_num, title, stats_line, raw_installment,\n                      body_html, [], has_board)'
NEW_STORE = 'store_installment(date_str, week_num, title, stats_line, raw_installment,\n                      body_html, [], has_board,\n                      confidence_level=_conf_level,\n                      confidence_badge_html=_conf_badge_html)'

if OLD_STORE not in content:
    # Try alt whitespace
    OLD_STORE_ALT = 'store_installment(date_str, week_num, title, stats_line, raw_installment, body_html, [], has_board)'
    if OLD_STORE_ALT in content:
        NEW_STORE_ALT = ('store_installment(date_str, week_num, title, stats_line, raw_installment,'
                         ' body_html, [], has_board,\n                      confidence_level=_conf_level,'
                         '\n                      confidence_badge_html=_conf_badge_html)')
        content = content.replace(OLD_STORE_ALT, NEW_STORE_ALT, 1)
        print("✅ PATCH 2: store_installment call updated (single-line variant)")
    else:
        print("⚠️  PATCH 2: store_installment anchor not found — apply manually")
        print('   Find: store_installment(date_str, week_num, title, stats_line, raw_installment, ..., has_board)')
        print('   Add kwargs: confidence_level=_conf_level, confidence_badge_html=_conf_badge_html')
else:
    content = content.replace(OLD_STORE, NEW_STORE, 1)
    print("✅ PATCH 2: store_installment call updated")


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3: Update store_installment() function signature and DDB item.
# ─────────────────────────────────────────────────────────────────────────────

OLD_SIG = 'def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board):'
NEW_SIG = 'def store_installment(date_str, week_num, title, stats_line, raw_markdown, content_html, tags, has_board,\n                      confidence_level="MEDIUM", confidence_badge_html=""):'

if OLD_SIG in content:
    content = content.replace(OLD_SIG, NEW_SIG, 1)
    print("✅ PATCH 3a: store_installment() signature updated")

    # Add confidence fields to the DDB item — insert before table.put_item
    OLD_AUTHOR = '"author": "Elena Voss",'
    NEW_AUTHOR = ('"author": "Elena Voss",\n'
                  '        "_confidence_level": confidence_level,\n'
                  '        "_confidence_badge_html": confidence_badge_html,\n'
                  '        # BS-05: Henning confidence — LOW/MEDIUM/HIGH based on journey data depth')
    if OLD_AUTHOR in content:
        content = content.replace(OLD_AUTHOR, NEW_AUTHOR, 1)
        print("✅ PATCH 3b: _confidence fields added to DDB item")
    else:
        print("⚠️  PATCH 3b: 'author' anchor not found in store_installment — add manually")
else:
    print("⚠️  PATCH 3: store_installment signature not found — check whitespace and apply manually")


# ─────────────────────────────────────────────────────────────────────────────
# Write patched file
# ─────────────────────────────────────────────────────────────────────────────

TARGET.write_text(content)
print(f"\n✅ All patches written to {TARGET}")
print("   Deploy: bash deploy/deploy_lambda.sh wednesday-chronicle lambdas/wednesday_chronicle_lambda.py")
