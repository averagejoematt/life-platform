#!/usr/bin/env bash
# Reject a pending production deployment for a CI/CD run (#2467).
#
# THE POSTURE THIS ENCODES: a gated run parked at the `production` gate OCCUPIES the
# job-level `ci-cd-deploy-<ref>` concurrency slot (CONVENTIONS §4d), so a stale one left
# "pinned and waiting" holds the whole deploy fleet hostage — the 2026-08-09 all-day
# wedge was two 8-day-old zombies doing exactly that. Rejecting is the safe exit: the
# run dies, nothing stale deploys, the slot frees. Approving instead would deploy the
# old sha the run was minted from, and "GitHub expires them at 30d" was measured false
# at day 8. Fresh runs (the retired check_deploy_wedge.py's STALE_GATE_REJECT_HOURS was 24)
# still get actioned on Matthew's say-so via deploy/approve_deployment.sh.
#
# THE ONE RUN IT REFUSES TO REJECT (#5384): the run whose head is the PARENT of the reconcile
# bot's `chore(reconcile): ... [skip-reconcile]` commit. That child's Plan defers to its parent
# ("the run at its parent is alive or deployed; that run ships this tree", #4250) and skips its
# own Deploy, so rejecting the parent strands the merge undeployed (2026-10-26, ~20 min dark).
# `scripts/reconcile_child_guard.py` decides; the answer is to APPROVE the parent
# (`bash deploy/approve_deployment.sh <run_id>`). `--force-ancestor` is the explicit override
# for a real merge train whose parent run is genuinely superseded.
#
# Usage: bash deploy/reject_deployment.sh [--force-ancestor] <run_id> [comment]
#   <run_id>  the waiting CI/CD run's databaseId (from `gh run list`)
#   [comment] optional rejection comment
set -euo pipefail
FORCE_ANCESTOR=0
if [ "${1:-}" = "--force-ancestor" ]; then
  FORCE_ANCESTOR=1
  shift
fi
RUN_ID="${1:?usage: reject_deployment.sh [--force-ancestor] <run_id> [comment]}"
COMMENT="${2:-Rejected: stale gated run — a Deploy parked at the gate holds the deploy-group slot (#2467).}"
REPO="averagejoematt/life-platform"
# shellcheck source=deploy/lib/deploy_gate_lease.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/deploy_gate_lease.sh"

echo "Pending deployments for run ${RUN_ID}:"
gh api "repos/${REPO}/actions/runs/${RUN_ID}/pending_deployments" \
  --jq '.[] | "  env=\(.environment.name) id=\(.environment.id) can_approve=\(.current_user_can_approve)"'

ENV_IDS=$(gh api "repos/${REPO}/actions/runs/${RUN_ID}/pending_deployments" --jq '[.[].environment.id] | @json')
if [ "${ENV_IDS}" = "[]" ]; then
  echo "No pending deployments to reject for run ${RUN_ID}."
  surface_gate_lease_holder "${REPO}" "${RUN_ID}"
  exit 0
fi

if [ "${FORCE_ANCESTOR}" = "1" ]; then
  echo "--force-ancestor: skipping the reconcile-child guard (#5384) — you own the stranded-deploy risk."
else
  GUARD_RC=0
  python3 "$(cd "$(dirname "$0")" && pwd)/../scripts/reconcile_child_guard.py" "${RUN_ID}" || GUARD_RC=$?
  if [ "${GUARD_RC}" != "0" ]; then
    echo "Not rejecting run ${RUN_ID} (guard exit ${GUARD_RC}). Nothing was changed." >&2
    exit "${GUARD_RC}"
  fi
fi
echo "Rejecting environment_ids=${ENV_IDS} ..."

gh api "repos/${REPO}/actions/runs/${RUN_ID}/pending_deployments" \
  -X POST --input - <<EOF
{"environment_ids": ${ENV_IDS}, "state": "rejected", "comment": "${COMMENT}"}
EOF
echo "Rejection submitted — the run concludes, nothing stale deploys, the deploy slot is freed."
echo "NOTE (#2590): the run will now read \`conclusion: failure\` with \`Deploy\` as its sole red job"
echo "  (the job never executed, so it has no log). That is NOT a red main —"
echo "  scripts/check_main_green.py derives the rejection from this run's own"
echo "  \`…/actions/runs/${RUN_ID}/approvals\` record and reports it as rejected-and-superseded."
