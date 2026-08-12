#!/usr/bin/env bash
# deploy/lib/deploy_gate_lease.sh — surface who owns the production deploy lease (#2590).
#
# THE AMBIGUITY THIS RESOLVES: `pending_deployments` returning `[]` for a run has
# TWO completely different meanings and the run itself cannot tell you which:
#
#   (a) the gate has not opened yet for this run — wait; or
#   (b) an OLDER run is parked at the `production` gate and OWNS the lease. Because
#       ci-cd.yml sets `concurrency: cancel-in-progress: false` and a Deploy job
#       parked at the gate still occupies the job-level `ci-cd-deploy-<ref>` slot,
#       every newer run queues silently behind it as `Deploy: pending` with an
#       EMPTY `pending_deployments`. From the newer run's side that is
#       indistinguishable from (a).
#
# Observed 2026-08-11: run 31528727429 sat `waiting` while the newer 31529270801
# showed `Deploy: pending` with empty `pending_deployments`, reading as "the gate
# never opened". It had not — the lease was held. Rejecting the holder released it
# instantly. So whenever a gate action finds nothing to action, name the holder.
#
# Usage:  source deploy/lib/deploy_gate_lease.sh
#         surface_gate_lease_holder <repo> <run_id>

surface_gate_lease_holder() {
  local repo="$1" run_id="$2" holders
  echo "  \`pending_deployments\` is EMPTY for run ${run_id} — that is ambiguous (#2590):"
  echo "    (a) the gate has not opened for this run yet, or"
  echo "    (b) an OLDER run owns the production lease and is silently queueing this one behind it."

  # Every non-completed run in `waiting` — no recency bound, because the 2026-08-09
  # all-day wedge was held by two EIGHT-DAY-OLD gated runs that a recent-run window
  # could not see (#2467).
  holders=$(gh api "repos/${repo}/actions/runs?status=waiting&per_page=100" \
    --jq ".workflow_runs[] | select(.id != ${run_id}) | \"    LEASE HOLDER: run \(.id) sha \(.head_sha[0:9]) branch \(.head_branch) waiting since \(.created_at)  \(.html_url)\"" \
    2>/dev/null || true)

  if [ -n "${holders}" ]; then
    echo "  (b) — the lease IS held:"
    echo "${holders}"
    echo "  Action the HOLDER, not this run (#2467 — approve or reject, never leave waiting):"
    echo "    bash deploy/reject_deployment.sh <holder_run_id>   # superseded/stale sha — releases the lease immediately"
    echo "    bash deploy/approve_deployment.sh <holder_run_id>  # only if the holder's sha is still the one to ship"
  else
    echo "  (a) — no run is in \`waiting\`, so nothing holds the lease."
    echo "  If this run's Deploy is stuck \`pending\` with every other job GREEN, that is the"
    echo "  #2052 phantom deploy wedge, not an approval you are waiting for:"
    echo "    python3 scripts/check_deploy_wedge.py"
  fi
}
