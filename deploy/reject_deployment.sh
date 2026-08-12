#!/usr/bin/env bash
# Reject a pending production deployment for a CI/CD run (#2467).
#
# THE POSTURE THIS ENCODES: a gated run parked at the `production` gate OCCUPIES the
# job-level `ci-cd-deploy-<ref>` concurrency slot (CONVENTIONS §4d), so a stale one left
# "pinned and waiting" holds the whole deploy fleet hostage — the 2026-08-09 all-day
# wedge was two 8-day-old zombies doing exactly that. Rejecting is the safe exit: the
# run dies, nothing stale deploys, the slot frees. Approving instead would deploy the
# old sha the run was minted from, and "GitHub expires them at 30d" was measured false
# at day 8. Fresh runs (see STALE_GATE_REJECT_HOURS in scripts/check_deploy_wedge.py)
# still get actioned on Matthew's say-so via deploy/approve_deployment.sh.
#
# Usage: bash deploy/reject_deployment.sh <run_id> [comment]
#   <run_id>  the waiting CI/CD run's databaseId (from `gh run list` or check_deploy_wedge)
#   [comment] optional rejection comment
set -euo pipefail
RUN_ID="${1:?usage: reject_deployment.sh <run_id> [comment]}"
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
