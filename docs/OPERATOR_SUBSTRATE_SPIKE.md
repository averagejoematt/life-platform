# Resident-Operator Substrate Spike (#2849, 2026-08-29)

> **Status:** canonical decision record · **Owner:** Matthew · **Verified:** 2026-08-29

**The question:** on what substrate does the platform's judgment loop run when the
owner's laptop is closed? Three candidates existed, none decided or priced. This spike
decides, per role, with rent per leg (ADR-103). The staff model is the five-role table
in issue #2849 (owner direction 2026-08-16): Engineering, Production support, QA,
Architect, Reader — each a scheduled or event-triggered leg, never one mega-agent.

## The three substrates, evaluated

| | GitHub Actions + Bedrock | Claude Code scheduled cloud routines | AgentCore / EventBridge-triggered |
|---|---|---|---|
| **Exists today** | Yes — the remediation agent (ADR-064/065, shadow mode) | Yes — routines API, runs the repo's actual skills with full checkout | No — new operational surface to build |
| **Identity / auth** | OIDC → scoped IAM role, no long-lived keys; gh token scoped by workflow | Anthropic-hosted session; GitHub App access to the repo; NO AWS credentials | IAM-native, event-subscribed; full AWS residency |
| **Trigger model** | cron + `repository_dispatch` (urgent alarms already wired) | cron only (min 1h interval); manual run API | event-driven — SNS/alarm to action in minutes |
| **What it can run** | scripts + Bedrock calls; NOT the interactive skill corpus | **the actual skills** (`.claude/skills/*`) against a real checkout — the only substrate that can | whatever is built for it; skills would need porting |
| **Cost shape** | free runners + Bedrock tokens (in-ceiling) | Claude usage (owner plan) per run; zero AWS | AgentCore runtime + tokens; a NEW standing bill |
| **Failure visibility** | CI-native (runs, logs, the #3234 class is known) | routine run history on claude.ai; PR/issue artifacts in-repo | CloudWatch; needs its own dead-man |
| **Governing risk** | the reconcile-job class — a workflow that cannot derive its own facts (#3156/#3234) | no AWS creds: anything needing SSM/DDB reads must go through public wire surfaces | rent-certain/benefit-hypothetical until an events-scale need exists (ADR-103) |

## The decision — a composite, stated explicitly

- **Scheduled JUDGMENT work → Claude Code cloud routines.** The rituals ARE skills;
  only this substrate runs them unported, with the repo's own discipline files in
  context. Chosen for: Architect (live today), Reader (next), and QA's judgment half.
- **Repo/PR mechanical work → GitHub Actions + Bedrock.** Already proven by the
  remediation agent; OIDC least-privilege is the right shape for anything touching
  AWS state read-only. Chosen for: Production support (existing remediation path,
  promotion governed by ADR-129 bars — NOT this spike), and Engineering's CI-side.
- **Event-driven response → EventBridge → the EXISTING Actions path
  (`repository_dispatch`), not AgentCore.** The urgent-SNS→dispatch wire already
  exists; minutes-scale response is already achievable on it. **AgentCore is
  explicitly DECLINED today** (ADR-103: a new standing operational surface whose
  benefit is hypothetical at current event volume — the urgent topic fires a handful
  of times a month). Revisit trigger: event volume or response-time evidence that the
  dispatch path materially lags, or an AWS-side action need that Actions' read-only
  posture cannot carry.

## Rent per leg (ADR-103) — and where each row lands

Rows land in `docs/PROPORTIONALITY.md` **when a leg goes live**, not before — a rent
row for machinery that doesn't run is the inverted form of the stale-ledger class.

| Leg | Substrate | Cadence | Authority (start) | Rent estimate | Status |
|---|---|---|---|---|---|
| **Architect** | cloud routine `architect-operator-2849` | weekly Mon 16:00 UTC | **report + file issues only** | ~1 opus session/week; most weeks a no-op calendar check (cents); a ritual week ≈ one review session | **LIVE 2026-08-29** — row added to PROPORTIONALITY |
| Reader | cloud routine | weekly | report + file issues | ≈ Architect's shape | not built |
| QA (judgment half) | cloud routine post-deploy/daily | act within QA scope | 1 haiku/sonnet run/day | not built (deterministic half already lives in CI/qa-smoke) |
| Production support | Actions + Bedrock (existing remediation agent) | MWF + urgent dispatch | observe/propose (shadow, ADR-129) | already priced in COST_TRACKER | live (pre-existing; not this story's claim) |
| Engineering | Actions or routine → worktree-implementer | weekday | propose-PR only; merge owner-batched | the big line: ~5 sonnet sessions/week; **do not arm before the Architect leg has 4 clean weeks** | not built |

Budget-tier gating: every routine leg gates itself on the PUBLIC
`/api/inference_receipt` → `budget_tier` (≥1 = stop; ADR-125 orders internal AI out
first) — chosen because routines hold no AWS credentials, and the tier is already an
honest public surface. Token bounding is per-run by prompt contract (one ritual max).

## The Architect leg — what is actually live

Routine `architect-operator-2849` (created 2026-08-29, model claude-opus-5, repo
checkout, zero MCP connectors — least privilege): boots, gates on the public budget
tier, runs `scripts/operating_calendar.py`, and either (a) reports no-op when nothing
is due within 7 days, or (b) runs the ONE most-overdue ritual in report-only mode,
lands the calendar-probe artifact as an `architect/<ritual>-<date>` PR (never merged
by it — the owner-batch merge IS what resets the ritual clock), and files
adversarially-reverified findings per ADR-099 under `via:architect-routine`. An
end-to-end proof run was fired at creation (2026-08-30T03:05Z). First scheduled run
2026-08-31; first ritual expected 2026-09-08 (fullreview-delta resumes 09-06, due
09-13, hard 09-16 — the routine catches it inside its window).

## The dependency stated honestly (acceptance box 2)

Box 2 wants the operator consuming the **system model (#2845)** and the charter's
paved roads as its instructions. #2845 is fable/`Next` and NOT landed. The Architect
leg does not need it (its instructions are the calendar registry + the skills
themselves, which is exactly what an Architect should read), but the Engineering and
Production-support legs SHOULD boot from the system model rather than from CLAUDE.md
prose — arming them before #2845 lands would re-create the boot-from-prose drift this
architecture is trying to leave. That ordering is a real dependency, not a caveat.

## Authority ladder (acceptance box 3)

Reused, not invented: the ADR-129 numeric promotion frame governs every leg.
Observe → propose-PR → act, per capability class; promotion requires the ADR-129
2026-07-20 bar (10 consecutive clean runs, operator flip, never automatic — retired
2026-08-30 by #2833, which made the agent's shadow posture permanent). The
remediation agent's shadow demotion is the live precedent that the ladder runs BOTH
directions. The Architect leg starts and stays at report-only — its "act" tier does
not exist by design (a reviewer that can fix things stops being a reviewer).
