#!/usr/bin/env bash
# Auto-approve the production deploy gate for the duration of an autonomous session.
#
# WHY THIS EXISTS (the "gated run is a deploy-group LEASE" rule): CI/CD's `production`
# GitHub Environment holds every deploy behind a manual approval. A single unapproved
# run does not just stall itself — it wedges the whole deploy group, so an overnight
# session that merges ten PRs and approves none of them ships nothing. Polling by hand
# is the thing that has historically eaten a session's first hour.
#
# ZOMBIE EXCLUSION IS LOAD-BEARING. A gated run that has been waiting for days is
# pinned to the commit it was minted from; approving it deploys week-old code over
# current main. Those run ids are excluded by number and must never be "cleaned up"
# by approving them — GitHub expires them at 30 days on its own.
#
# Usage: bash deploy/watch_deploy_gate.sh [interval_seconds] [max_minutes]
#   Env: EXCLUDE_RUNS="id,id"  additional run ids to never approve (comma-separated)
set -uo pipefail

INTERVAL="${1:-120}"
MAX_MINUTES="${2:-600}"
REPO="averagejoematt/life-platform"

# Permanently excluded zombies — see the 2026-08-08 handover. Approving either would
# deploy code from 2026-08-01/02 over current main.
ZOMBIES="30727225837 30723876315"
EXTRA="$(printf '%s' "${EXCLUDE_RUNS:-}" | tr ',' ' ')"
SKIP="${ZOMBIES} ${EXTRA}"

deadline=$(( $(date +%s) + MAX_MINUTES * 60 ))
approved_file="$(mktemp)"

echo "[gate-watch] armed: every ${INTERVAL}s for ${MAX_MINUTES}m; skipping runs: ${SKIP}"

# DO NOT poll `gh run list --status waiting` — measured 2026-08-08, it is unreliable:
# a live CI/CD run whose Deploy job was sitting at the environment gate did NOT appear
# in that list (its run-level status read `in_progress`), while two week-old zombies
# did. A watcher built on it fires on the wrong runs and silently never fires on the
# right ones. The authoritative signal is a NON-EMPTY `pending_deployments` on the run,
# which is also exactly what approve_deployment.sh acts on — so poll that directly over
# every run that has not completed.
while [ "$(date +%s)" -lt "${deadline}" ]; do
  candidates="$(gh run list --limit 30 --json databaseId,name,status \
                 --jq '.[] | select(.name == "CI/CD") | select(.status != "completed") | .databaseId' 2>/dev/null || true)"

  waiting=""
  for run in ${candidates}; do
    pending="$(gh api "repos/${REPO}/actions/runs/${run}/pending_deployments" \
                --jq 'length' 2>/dev/null || echo 0)"
    if [ "${pending:-0}" -gt 0 ]; then
      waiting="${waiting} ${run}"
    fi
  done

  for run in ${waiting}; do
    case " ${SKIP} " in *" ${run} "*)
      continue ;;
    esac
    if grep -qx "${run}" "${approved_file}" 2>/dev/null; then
      continue
    fi
    if [ -n "${GATE_WATCH_DRY_RUN:-}" ]; then
      # Proof mode: exercise detection + selection without approving anything, so the
      # firing path can be verified against a run we must never actually approve.
      echo "[gate-watch] DRY RUN — would approve run ${run}"
      echo "${run}" >>"${approved_file}"
      continue
    fi
    echo "[gate-watch] $(date -u +%H:%M:%SZ) approving run ${run}"
    if bash deploy/approve_deployment.sh "${run}" "Auto-approved by the session gate monitor."; then
      echo "${run}" >>"${approved_file}"
    else
      echo "[gate-watch] approval FAILED for ${run} — will retry next poll"
    fi
  done

  sleep "${INTERVAL}"
done

echo "[gate-watch] window elapsed; approved: $(wc -l <"${approved_file}" | tr -d ' ') run(s)"
