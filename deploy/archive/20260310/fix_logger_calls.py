#!/usr/bin/env python3
"""
fix_logger_calls.py — Convert PlatformLogger-incompatible %s format calls to f-strings.
Run from project root: python3 deploy/fix_logger_calls.py
"""
import re, os
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def fix_file(relpath, fixes):
    path = os.path.join(PROJ, relpath)
    with open(path) as f:
        content = f.read()
    changed = 0
    for old, new in fixes:
        if old in content:
            content = content.replace(old, new, 1)
            changed += 1
        else:
            print(f"  ⚠️  Not found: {old[:70]}")
    with open(path, 'w') as f:
        f.write(content)
    remaining = [(i+1, l.strip()) for i, l in enumerate(content.splitlines())
                 if re.search(r'logger\.(info|warning|error|debug)\(.*%[sdf].*,', l)]
    print(f"  ✅ {relpath}: {changed} fixes applied, {len(remaining)} remaining")
    for ln, l in remaining:
        print(f"    L{ln}: {l[:90]}")

# ── character_sheet_lambda.py ──────────────────────────────────────────────
fix_file("lambdas/character_sheet_lambda.py", [
    ('logger.warning("[character] fetch_date(%s, %s) failed: %s", source, date_str, e)',
     'logger.warning(f"[character] fetch_date({source}, {date_str}) failed: {e}")'),
    ('logger.warning("[character] fetch_range(%s, %s→%s) failed: %s", source, start_date, end_date, e)',
     'logger.warning(f"[character] fetch_range({source}, {start_date}→{end_date}) failed: {e}")'),
    ('logger.warning("[character] fetch_journal_entries(%s) failed: %s", date_str, e)',
     'logger.warning(f"[character] fetch_journal_entries({date_str}) failed: {e}")'),
    ('logger.info("[character] Data assembled for %s in %.1fs — sources: %s",\n                yesterday_str, elapsed,\n                ", ".join(k for k in ["whoop", "macrofactor", "apple", "habit_scores",\n                                       "state_of_mind", "journal_entries"] if data.get(k)))',
     'logger.info(f"[character] Data assembled for {yesterday_str} in {elapsed:.1f}s — sources: " + ", ".join(k for k in ["whoop", "macrofactor", "apple", "habit_scores", "state_of_mind", "journal_entries"] if data.get(k)))'),
    ('logger.info("[character] Override date: %s", yesterday_str)',
     'logger.info(f"[character] Override date: {yesterday_str}")'),
    ('logger.info("[character] Already computed for %s (level %s, tier %s) — skipping",\n                        yesterday_str,\n                        existing.get("character_level", "?"),\n                        existing.get("character_tier", "?"))',
     'logger.info(f"[character] Already computed for {yesterday_str} — skipping")'),
    ('logger.info("[character] Sick day flagged for %s (%s) — freezing EMA", yesterday_str, _sick_reason)',
     'logger.info(f"[character] Sick day flagged for {yesterday_str} ({_sick_reason}) — freezing EMA")'),
    ('logger.info("[character] Frozen record stored for %s (from %s)",\n                        yesterday_str, _frozen.get("frozen_from", "?"))',
     'logger.info(f"[character] Frozen record stored for {yesterday_str} (from {_frozen.get(\'frozen_from\', \'?\')})")'),
    ('logger.info("[character] Previous state loaded — Level %s (%s %s)",\n                    previous_state.get("character_level", "?"),\n                    previous_state.get("character_tier_emoji", ""),\n                    previous_state.get("character_tier", "?"))',
     'logger.info(f"[character] Previous state loaded — Level {previous_state.get(\'character_level\', \'?\')} ({previous_state.get(\'character_tier_emoji\', \'\')} {previous_state.get(\'character_tier\', \'?\')})")'),
    ('logger.error("[character] compute_character_sheet failed: %s", e, exc_info=True)',
     'logger.error(f"[character] compute_character_sheet failed: {e}")'),
    ('logger.info("[character]   %s: raw=%s level=%s tier=%s (%s)",\n                    p, pd.get("raw_score", "?"), pd.get("level", "?"),\n                    pd.get("tier", "?"), pd.get("tier_emoji", "?"))',
     'logger.info(f"[character]   {p}: raw={pd.get(\'raw_score\', \'?\')} level={pd.get(\'level\', \'?\')} tier={pd.get(\'tier\', \'?\')} ({pd.get(\'tier_emoji\', \'?\')})")'),
    ('logger.info("[character]   EVENT: %s", json.dumps(ev, default=str))',
     'logger.info(f"[character]   EVENT: {json.dumps(ev, default=str)}")'),
    ('logger.info("[character]   EFFECT: %s %s", eff.get("emoji", ""), eff.get("name", ""))',
     'logger.info(f"[character]   EFFECT: {eff.get(\'emoji\', \'\')} {eff.get(\'name\', \'\')}")'),
    ('logger.info("[character] Stored: %s — Level %s (%s %s) — %d events",\n                    yesterday_str, char_level, char_emoji, char_tier, len(events))',
     'logger.info(f"[character] Stored: {yesterday_str} — Level {char_level} ({char_emoji} {char_tier}) — {len(events)} events")'),
    ('logger.error("[character] store_character_sheet failed: %s", e, exc_info=True)',
     'logger.error(f"[character] store_character_sheet failed: {e}")'),
    ('logger.info("[character] Config loaded — %d pillars", len(config.get("pillars", {})))',
     'logger.info(f"[character] Config loaded — {len(config.get(\'pillars\', {}))} pillars")'),
    ('logger.info("[character] Raw score histories loaded — %d days of history", history_depth)',
     'logger.info(f"[character] Raw score histories loaded — {history_depth} days of history")'),
])

# ── daily_metrics_compute_lambda.py ───────────────────────────────────────
fix_file("lambdas/daily_metrics_compute_lambda.py", [
    ('logger.warning("fetch_date(%s, %s) failed: %s", source, date_str, e)',
     'logger.warning(f"fetch_date({source}, {date_str}) failed: {e}")'),
    ('logger.warning("fetch_range(%s, %s→%s) failed: %s", source, start, end, e)',
     'logger.warning(f"fetch_range({source}, {start}→{end}) failed: {e}")'),
    ('logger.error("fetch_profile failed: %s", e)',
     'logger.error(f"fetch_profile failed: {e}")'),
    ('logger.warning("fetch_journal_entries(%s) failed: %s", date_str, e)',
     'logger.warning(f"fetch_journal_entries({date_str}) failed: {e}")'),
    ('logger.info("Stored day_grade: %s → %s (%s)", date_str, total_score, grade)',
     'logger.info(f"Stored day_grade: {date_str} → {total_score} ({grade})")'),
    ('logger.warning("store_day_grade failed: %s", e)',
     'logger.warning(f"store_day_grade failed: {e}")'),
    ('logger.warning("store_habit_scores failed: %s", e)',
     'logger.warning(f"store_habit_scores failed: {e}")'),
    ('logger.info("Dedup: %d → %d Strava activities", orig, deduped)',
     'logger.info(f"Dedup: {orig} → {deduped} Strava activities")'),
    ('logger.info("Override date: %s", yesterday_str)',
     'logger.info(f"Override date: {yesterday_str}")'),
    ('logger.info("Recomputing %s — %s", yesterday_str, reason)',
     'logger.info(f"Recomputing {yesterday_str} — {reason}")'),
    ('logger.info("Sick day flagged for %s (%s) — storing sick record", yesterday_str, _sick_reason)',
     'logger.info(f"Sick day flagged for {yesterday_str} ({_sick_reason}) — storing sick record")'),
    ('logger.info(\n            "Sick day record stored for %s — streaks preserved (T0=%s T01=%s)",\n            yesterday_str, _t0_streak, _t01_streak,\n        )',
     'logger.info(f"Sick day record stored for {yesterday_str} — streaks preserved (T0={_t0_streak} T01={_t01_streak})")'),
    ('logger.info("Source fingerprints: %s", source_fps)',
     'logger.info(f"Source fingerprints: {source_fps}")'),
    ('logger.info("Day grade: %s (%s)", day_grade_score, grade)',
     'logger.info(f"Day grade: {day_grade_score} ({grade})")'),
    ('logger.info("  %-20s %s", comp, score)',
     'logger.info(f"  {comp:<20} {score}")'),
    ('logger.info("Readiness: %s (%s)", readiness_score, readiness_colour)',
     'logger.info(f"Readiness: {readiness_score} ({readiness_colour})")'),
])

print("\n✅ Logger fixes applied. Now run:")
print("  bash deploy/deploy_lambda.sh character-sheet-compute")
print("  bash deploy/deploy_lambda.sh daily-metrics-compute")
