#!/usr/bin/env bash
# Auto-approve the production deploy gate for the duration of an autonomous session.
#
# WHY THIS EXISTS (the "gated run is a deploy-group LEASE" rule): CI/CD's `production`
# GitHub Environment holds every deploy behind a manual approval. A single unapproved
# run does not just stall itself — it wedges the whole deploy group, so an overnight
# session that merges ten PRs and approves none of them ships nothing. Polling by hand
# is the thing that has historically eaten a session's first hour.
#
# STALE RUNS GET REJECTED, NOT SKIPPED (#2467). The previous posture pinned known
# zombies by id and left them waiting ("GitHub expires them at 30 days"). Both halves
# were wrong: a gated run parked at the gate OCCUPIES the job-level deploy slot, so
# leave-waiting holds the fleet hostage — the 2026-08-09 all-day wedge was two 8-day-old
# zombies doing exactly that, still alive with no expiry in sight. And approving one
# deploys the week-old sha it was minted from. So: a waiting run older than
# GATE_STALE_REJECT_HOURS (default 24) is REJECTED via deploy/reject_deployment.sh —
# the run dies, nothing stale deploys, the slot frees. Younger runs are approved as
# before.
#
# Usage: bash deploy/watch_deploy_gate.sh [interval_seconds] [max_minutes]
#   Env: EXCLUDE_RUNS="id,id"        run ids to never TOUCH (neither approve nor reject
#                                    — the manual-handling escape hatch)
#        GATE_STALE_REJECT_HOURS=N   age beyond which a waiting run is rejected (default 24)
#        GATE_WATCH_DRY_RUN=1        log would-approve / would-reject without acting
set -uo pipefail

INTERVAL="${1:-120}"
MAX_MINUTES="${2:-600}"
REPO="averagejoematt/life-platform"
STALE_HOURS="${GATE_STALE_REJECT_HOURS:-24}"

EXTRA="$(printf '%s' "${EXCLUDE_RUNS:-}" | tr ',' ' ')"
SKIP="${EXTRA}"

deadline=$(( $(date +%s) + MAX_MINUTES * 60 ))
actioned_file="$(mktemp)"

echo "[gate-watch] armed: every ${INTERVAL}s for ${MAX_MINUTES}m; stale-reject at ${STALE_HOURS}h; excluded: ${SKIP:-none}"

# DO NOT rely on `gh run list --status waiting` ALONE — measured 2026-08-08, it is
# unreliable: a live CI/CD run whose Deploy job was sitting at the environment gate did
# NOT appear in that list (its run-level status read `in_progress`), while two week-old
# zombies did. The authoritative signal is a NON-EMPTY `pending_deployments` on the run,
# which is also exactly what approve/reject_deployment.sh act on — so poll that directly
# over every run that has not completed. The waiting-status list is still swept IN
# ADDITION (#2467): it is exactly where an old gate-parked zombie lives once it has aged
# out of the recent-run window, and merging the two lists only ever adds candidates.
while [ "$(date +%s)" -lt "${deadline}" ]; do
  recent="$(gh run list --limit 200 --json databaseId,name,status,createdAt \
             --jq '.[] | select(.name == "CI/CD") | select(.status != "completed") | "\(.databaseId) \(.createdAt)"' 2>/dev/null || true)"
  parked="$(gh run list --status waiting --limit 100 --json databaseId,name,createdAt \
             --jq '.[] | select(.name == "CI/CD") | "\(.databaseId) \(.createdAt)"' 2>/dev/null || true)"
  candidates="$(printf '%s\n%s\n' "${recent}" "${parked}" | sed '/^[[:space:]]*$/d' | sort -u)"

  while read -r run created; do
    [ -n "${run:-}" ] || continue
    case " ${SKIP} " in *" ${run} "*)
      continue ;;
    esac
    if grep -qx "${run}" "${actioned_file}" 2>/dev/null; then
      continue
    fi
    pending="$(gh api "repos/${REPO}/actions/runs/${run}/pending_deployments" \
                --jq 'length' 2>/dev/null || echo 0)"
    if [ "${pending:-0}" -eq 0 ]; then
      continue
    fi

    age_hours="$(python3 -c 'import sys,datetime;ts=datetime.datetime.fromisoformat(sys.argv[1].replace("Z","+00:00"));print(int((datetime.datetime.now(datetime.timezone.utc)-ts).total_seconds()//3600))' "${created}" 2>/dev/null || echo 0)"

    if [ "${age_hours:-0}" -ge "${STALE_HOURS}" ]; then
      if [ -n "${GATE_WATCH_DRY_RUN:-}" ]; then
        echo "[gate-watch] DRY RUN — would REJECT stale run ${run} (parked ${age_hours}h at the gate, #2467)"
        echo "${run}" >>"${actioned_file}"
        continue
      fi
      echo "[gate-watch] $(date -u +%H:%M:%SZ) REJECTING stale run ${run} (parked ${age_hours}h at the gate — a parked Deploy holds the deploy slot, #2467)"
      if bash deploy/reject_deployment.sh "${run}" "Auto-rejected by the session gate monitor: parked ${age_hours}h at the gate — stale holder (#2467)."; then
        echo "${run}" >>"${actioned_file}"
      else
        echo "[gate-watch] rejection FAILED for ${run} — will retry next poll"
      fi
      continue
    fi

    if [ -n "${GATE_WATCH_DRY_RUN:-}" ]; then
      # Proof mode: exercise detection + selection without acting, so the firing path
      # can be verified against a run we must never actually approve.
      echo "[gate-watch] DRY RUN — would approve run ${run} (${age_hours}h old)"
      echo "${run}" >>"${actioned_file}"
      continue
    fi
    echo "[gate-watch] $(date -u +%H:%M:%SZ) approving run ${run}"
    if bash deploy/approve_deployment.sh "${run}" "Auto-approved by the session gate monitor."; then
      echo "${run}" >>"${actioned_file}"
    else
      echo "[gate-watch] approval FAILED for ${run} — will retry next poll"
    fi
  done <<EOF
${candidates}
EOF

  sleep "${INTERVAL}"
done

echo "[gate-watch] window elapsed; actioned: $(wc -l <"${actioned_file}" | tr -d ' ') run(s)"
