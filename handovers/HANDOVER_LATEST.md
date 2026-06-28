# HANDOVER — Coherence Program COMPLETE (Phase 4 shipped + live-validated) — 2026-06-28

**The 4-phase Self-Management & Coherence Program is now fully done, deployed, and live-validated.** Phase 4 (self-healing eyes on content) shipped this session as PRs #250/#251/#252, all merged + deployed. Matthew authorized all deploys this session.

---

## What shipped this session (3 PRs, #250–252, all merged + deployed)

### Phase 4 — self-healing gets eyes on content
The remediation agent could only triage **infra** (alarms, CI, DLQ). It now also sees the **"alive but not right"** class — the content/correctness failures the Coherence Sentinel catches.

- **#250 — Sentinel persists findings + grounds on canonical_facts.**
  - Writes its findings record to `s3://matthew-life-platform/coherence-log/{latest,<date>}.json` every run. The `coherence-overall` alarm only carries "OverallAlarm>=1"; this is *what* failed, so the agent (and a human) can triage from the real digest. `build_record()` is pure. Fail-soft.
  - New scoped IAM: `s3:PutObject` on `coherence-log/*` only (an audit prefix, not site/data). → `cdk deploy LifePlatformOperational` (done).
  - Folded in the grounding↔detection follow-up: `_gather_facts_and_narratives` now uses `canonical_facts.build_canonical_facts` — the SAME schema the coaches are grounded on. The semantic pass now sees protein avg/target/floor distinctly.
- **#251 — agent eyes + content taxonomy.** `agent.py::_coherence_findings()` reads the artifact as a `coherence` signal (no new IAM — the role already had `s3:GetObject`). `docs/REMEDIATION_TAXONOMY.md` gains a "Content & coherence signals" section routing each invariant to **Bucket B or C only — never auto-merge**. Content/AI surfaces added to the hard denylist. **A test asserts the auto-merge ALLOWLIST contains no content path** (the safety invariant). The agent runs from the repo → merge = live, no deploy.
- **#252 — fix: persisted status mirrors the alarm.** The first live run exposed a gap in the wiring itself: the AI semantic pass flagged a coach narrative incoherent while all deterministic invariants were green. `_emit_overall` fires the alarm on that (semantic_bad), but `build_record` set `status` to the deterministic verdict only ("ok") — so the alarm would fire while the agent's status filter dropped the record (alarm-with-no-detail). Fix: `status` now mirrors `_emit_overall` (ALARM when deterministic-worst is ALARM **or** semantic incoherent); adds `deterministic_status` + `semantic_incoherent`. → redeployed.

### The live validation (this is the headline)
On the first run after deploy, the semantic pass — now grounded on `canonical_facts` — **caught a real content bug the platform is serving**: a coach narrative claims **"RHR dropped to 53"** when the authoritative fact is `rhr_bpm=64`, plus self-contradictory weight numbers (**"13.8 lbs over four weeks"** AND **"15.8 lbs in fifteen days"** in the same essay). `coherence-overall` is now a **true-positive ALARM**. The auto-mode agent's next daily run (~07:45 PT) will surface it as a needs-human content finding and **cannot** auto-fix it.

---

## State of `main` + production
- All 3 PRs merged. **main is GREEN through Plan** (Lint ✓, Unit Tests ✓, Plan ✓). The Deploy job sits at the manual production-approval gate (intentional — the meaningful infra+code was `cdk deploy`'d directly this session).
- `LifePlatformOperational` deployed twice (the IAM grant + sentinel code, then the #252 build_record fix). Sentinel verified live: writes `coherence-log/latest.json`, status=alarm on the semantic finding.
- Remediation mode = `auto`.

### ⚠️ CI lesson (recurring) — see memory `reference_ci_masking_and_creds`
#250/#251 main runs went RED on the ENFORCED **ruff I001** gate — a **pre-existing** break since Phase-2 #246 (the `measurable_metrics` import block was un-sorted in `coach_state_updater.py`). Because Lint is first and Unit Tests/Plan/Deploy `needs` it, this masked the whole pipeline on every push since #246. The local flake8 fail-loud subset (`E9,F63,F7,F82`) does NOT run ruff's isort rules — **run full `ruff check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/` before merging.** #252 folded in the `ruff --fix`; main is green again.

---

## Open follow-ups
1. **The real content bug the Sentinel caught** (live, user-facing): a served coach narrative cites RHR 53 (vs fact 64) + self-contradictory weight numbers. Likely a **stale served `EXPERT#` record** or a coach ignoring the canonical-facts grounding. Decide: **re-run `ai-expert-analyzer`** (operational; likely clears a stale record) vs a grounding-prompt fix (Bucket B). This is exactly the Bucket-C "human decides" path the taxonomy describes.
2. **email-subscriber config drift** — `session_postflight.py` found CDK=15s vs live=30s. Align the CDK value or `cdk deploy LifePlatformOperational`.
3. **`ai_calls.py` nutrition guardrail** rides the next layer rebuild.
4. **Optional:** a scheduled monthly deep semantic-audit `Workflow` (multi-agent `/accuracy-review`). Not built — needs explicit opt-in.

---

## Verification / commands
- Sentinel + artifact: `aws lambda invoke --function-name life-platform-coherence-sentinel --region us-west-2 --cli-read-timeout 0 --payload '{}' /tmp/s.json` then `aws s3 cp s3://matthew-life-platform/coherence-log/latest.json -`
- Agent eyes (offline): `tests/test_remediation_agent.py` — coherence OK→noise, alarm→flagging-only, fail-soft, + the auto-merge safety assertions.
- Full lint gate before any merge: `black --check ... && ruff check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/`
- Tests: `python3 -m pytest tests/ -k "coherence or remediation or measurable or canonical or gradability" -q`

## Memories updated
The Self-Management & Coherence Program pointer in `MEMORY.md` (Phase 4 DONE + the live content-bug finding + the recurring ruff-masking lesson).
