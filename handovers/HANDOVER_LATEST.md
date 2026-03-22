→ See handovers/HANDOVER_v3.8.2.md

This session (2026-03-22):
- D10: site_writer.py v1.3.0 — added baseline param, daily_brief_lambda.py wired to pass it
- T20: deploy/add_reading_path_ctas.py — reading path CTAs on 7 pages (story→…→ask)
- deploy/deploy_d10_phase1.sh — one-command deploy for both changes
- Phase 0 COMPLETE, Phase 1 COMPLETE

Next session entry point:
1. Run: bash deploy/deploy_d10_phase1.sh  ← THIS FIRST (not yet deployed)
2. Verify: curl public_stats.json | grep -A6 '"baseline"'  and visit /story/ for CTA
3. Phase 2 begins: /habits/ page (heatmap + tier breakdown + streaks)
4. Check if Withings has resumed syncing (last weigh-in 2026-03-07)

Key context:
- D10 fix is code-complete but NOT YET DEPLOYED — deploy_d10_phase1.sh does it
- baseline{} fallback values: 302.0 lbs / 45 HRV / 62 RHR / 55% recovery (Feb 22 actuals)
- Profile can override with: baseline_date, baseline_weight_lbs, baseline_hrv_ms,
  baseline_rhr_bpm, baseline_recovery_pct fields on PROFILE#v1
- Phase 1 Task 20 reading path: /story/→/live/→/character/→/habits/→/experiments/
  →/discoveries/→/intelligence/→/ask/
- site_writer.py cache tightened 24h→1h (so public_stats updates propagate faster)
- Phase 2 first target: /habits/ page — heatmap + tier breakdown + streaks + keystone spotlight
  Endpoint needed: /api/habits (new, in site_api_lambda.py)
