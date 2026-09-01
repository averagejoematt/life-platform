#!/usr/bin/env bash
# deploy/lib/smoke_verdict.sh — #3395: which SURFACE did the smoke red, and can a
# `site/**` rollback even reach it? (the smoke edition of the #3352 visual-QA scope check)
#
# WHY THIS EXISTS
# ---------------
# `site-deploy.yml`'s `rollback-site-on-failure` reverts `site/**` whenever the smoke
# or visual-QA gate reds. #3352 gave the VISUAL leg a per-surface scope verdict
# (`tests/visual_qa_verdict.py`); the smoke leg kept firing unconditionally. Live
# 2026-09-01 01:35Z (INCIDENT_LOG P3): site-deploy run 33459065966 failed ONE smoke
# check — `/api/vitals` weight arbitration, a data-plane state served from DynamoDB —
# and the rollback reverted PR #3392's site content, "successfully", without touching
# the actual disagreement. The deploy's own visual QA had PASSED. A rollback whose
# scope cannot reach its trigger is the silent-failure floor.
#
# THE THREE SURFACES (declared at the CALL SITE, not inferred from strings)
# -------------------------------------------------------------------------
# Unlike the visual leg (which classifies a report after the fact), every smoke check
# already knows what it is judging, so the harness DECLARES the surface up front via
# the `SMOKE_SURFACE` variable, set per section in deploy/smoke_test_site.sh:
#
#   site   — bytes that came out of `site/` (page shells, static assets, content
#            markers, structural/static-core/OG checks). REACHABLE: the previous
#            build's bytes are the fix.
#   api    — `/api/*` payloads and other data-plane state (DynamoDB via site-api,
#            Lambda-written `generated/` objects like the permanence archive).
#            NOT reachable — this is the 2026-09-01 P3 / 2026-08-27 Session G case:
#            reverting `site/**` deletes innocent work and leaves the defect live.
#   infra  — edge/deploy-path configuration a `site/**` revert cannot republish:
#            the v4-redirects CloudFront function, CDK-owned response headers (CSP),
#            cache-control stamps written by sync_site_to_s3.sh itself (the #3352
#            `deploy-script` class — a rollback re-RUNS that script, so it re-runs
#            the defect; the 2026-08-31 P1). NOT reachable.
#
# THE NEGATIVE CONTROL, AND WHY IT POINTS WHERE IT DOES (same rule as #3352)
# --------------------------------------------------------------------------
# An unset or unrecognised `SMOKE_SURFACE` records as `site` — i.e. the rollback still
# runs, exactly as it does today. This change may only ever REMOVE a rollback we can
# prove is futile, never suppress one on a shape we have not thought about. Likewise a
# failure that bypasses `smoke_record_fail` entirely (a future bare `FAIL=$((FAIL+1))`)
# simply goes unrecorded: the job still reds, no `false` verdict is emitted, and the
# rollback fires as before — the fail-safe is today's behaviour, and the drift is
# printed out loud by the row-count consistency warning in `smoke_emit_verdict`.
# `tests/test_smoke_rollback_scope_3395.py` pins both directions with functional
# positive/negative controls (the #3200 lesson: green tests on a path that cannot
# fire prove nothing — the live proof is the SMOKE_INJECT_SURFACE dispatch run).
#
# VERDICT SEMANTICS (mirrors visual_qa_verdict.py)
# ------------------------------------------------
# `site_reachable` is the AND over every recorded failure: ONE unreachable surface
# declines the whole rollback (a partial revert of a mixed failure is the worst of
# both — the human the #1447 issue reaches still sees every surface by name). Zero
# recorded failures emit `true`: the gate may have died before recording anything,
# and the fail-safe is today's behaviour.

# The surface the NEXT recorded failure belongs to. Sections of smoke_test_site.sh
# reassign this as they go; anything unrecognised counts as `site` (see above).
SMOKE_SURFACE="${SMOKE_SURFACE:-site}"

SMOKE_FAIL_SITE=0
SMOKE_FAIL_API=0
SMOKE_FAIL_INFRA=0
SMOKE_FAILED_ROWS=""

# smoke_record_fail [label] — THE one failure recorder: increments FAIL and files the
# failure under the currently declared surface. Every ❌ path in smoke_test_site.sh
# must go through here (pinned by tests/test_smoke_rollback_scope_3395.py — guard the
# SET, not the instance).
smoke_record_fail() {
  local label="${1:-${CURRENT_CHECK:-unnamed check}}"
  FAIL=$((${FAIL:-0} + 1))
  local surface
  case "${SMOKE_SURFACE:-site}" in
    api) surface="api"; SMOKE_FAIL_API=$((SMOKE_FAIL_API + 1)) ;;
    infra) surface="infra"; SMOKE_FAIL_INFRA=$((SMOKE_FAIL_INFRA + 1)) ;;
    # Negative control: an unknown surface is a site/** rendering defect — today's
    # behaviour (roll back). Never silently widen the decline set.
    *) surface="site"; SMOKE_FAIL_SITE=$((SMOKE_FAIL_SITE + 1)) ;;
  esac
  SMOKE_FAILED_ROWS+="${surface}|${label}"$'\n'
}

# smoke_emit_verdict — print the human verdict and, when $GITHUB_OUTPUT is set (CI),
# append the machine-readable outputs the rollback's scope check reads:
#   site_reachable=true|false   surfaces=api:N,infra:N,site:N   summary=<one line>
# Only an explicit `false` ever declines a rollback (site-deploy.yml's guard) — an
# absent verdict (script aborted before this ran) rolls back exactly as today.
smoke_emit_verdict() {
  local recorded=$((SMOKE_FAIL_SITE + SMOKE_FAIL_API + SMOKE_FAIL_INFRA))
  local unreachable=$((SMOKE_FAIL_API + SMOKE_FAIL_INFRA))
  local reachable="true"
  local surfaces="" part
  for part in "api:$SMOKE_FAIL_API" "infra:$SMOKE_FAIL_INFRA" "site:$SMOKE_FAIL_SITE"; do
    [[ "${part##*:}" -gt 0 ]] && surfaces="${surfaces}${surfaces:+,}${part}"
  done
  local summary
  if [[ "$recorded" -eq 0 ]]; then
    summary="no recorded smoke failure — rollback scope unchanged (reachable)"
  elif [[ "$unreachable" -gt 0 ]]; then
    reachable="false"
    summary="$unreachable of $recorded failed smoke check(s) are NOT site/**-reachable ($surfaces) — a site/** revert cannot cure a data-plane or edge-config red"
  else
    summary="all $recorded failed smoke check(s) are site/**-reachable ($surfaces)"
  fi
  echo "── Rollback scope check (#3395 — the smoke edition of #3352) ──"
  echo "  site/**-reachable: $reachable"
  echo "  $summary"
  if [[ -n "$SMOKE_FAILED_ROWS" ]]; then
    while IFS='|' read -r row_surface row_label; do
      [[ -z "$row_surface" ]] && continue
      printf '    · %-6s %s\n' "$row_surface" "$row_label"
    done <<< "$SMOKE_FAILED_ROWS"
  fi
  if [[ "${FAIL:-0}" -ne "$recorded" ]]; then
    echo "  ⚠ FAIL count (${FAIL:-0}) != recorded surface rows ($recorded) — a failure bypassed"
    echo "    smoke_record_fail. Unrecorded failures default to site/** (rollback runs — the"
    echo "    #3352 negative-control direction); route them through smoke_record_fail."
  fi
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "site_reachable=$reachable"
      echo "surfaces=$surfaces"
      echo "summary=$summary"
    } >> "$GITHUB_OUTPUT"
  fi
}
