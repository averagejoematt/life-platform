# HANDOVER — Run 3 fully dispositioned + the coaches got phones: 41 findings closed out, 8 PRs merged, Telegram LIVE end-to-end — 2026-08-09 ~02:30Z → ~07:30Z

> Instruction thread: *resumed via `claude --continue` into the post-wrap tail of the
> gates session; the owner then drove three asks in sequence: (1) finish everything the
> /fullreview run 3 left half-done ("complete everything now"), (2) a NEW feature ask —
> "I want all my coaches as a contact in telegram… and while not telegram specific, i
> really want those coaches to feel human… their memories, and be invested in me" —
> prioritized in-session, and (3) "can you do it all if i authorize" for the full CDK
> go-live sequence. Mid-session the owner discovered the session was running on Opus
> for what he considered Fable work — "Abort and review, i just switched to fable" —
> the park/review/resume is a section below.*

**Main:** green (`c1eb156d`) — the #2404 run, full pipeline end to end, `check_main_green.py` exit 0 read at wrap.
THREE unit-tests reds along the way, every one with Deploy green throughout: the
stamped-literal red (~65 min, incident row 1), then the post-merge suite **serially
catching the new Telegram surface on two set guards** — the #946 tombstone guard
(unguarded `RELATIONSHIP#state` read, PR #2403) and the serve-stack Throttles-alarm
guard (both new Lambdas alarm-less, PR #2404 + a 39s stack update; alarms verified
live in CloudWatch) — incident row 2 covers the pair.
**Docs:** ARCHITECTURE secrets table + stamped inventory (26) via #2399/#2400,
SECRETS_MAP (+`life-platform/telegram`), INCIDENT_LOG (+2 rows), DECISIONS (ADR-151 +
index), deploy.md map regenerated. All wiki checkers green at commit.
**Decisions:** ADR-151 filed — Telegram coach chat: private-tier egress to the owner's
device sanctioned, the two-Lambda trust boundary, the no-exemption grounding posture,
budget rank with the daily brief.
**Build beat:** `2026-08-09-the-coaches-got-phones`.
**Incidents:** 2 rows added — (1) main unit-tests red ~65 min on the stamped
secret-count literal after a `deploy/`-only merge that triggered neither ci-cd nor its
reconcile job; (2) main unit-tests red ~2h on the #946 singleton-tombstone guard
catching the chat worker's unguarded singleton read, then the serve-stack
Throttles-alarm set guard on the same new surface — both POST-MERGE-ONLY guards the PR
lane could not show; fixed forward #2403/#2404, deploys healthy throughout.
**Closures:** 13 commented — #2360 #2337 #2391 #2364 (this session's merges, all with
live evidence) + #2343 #2344 #2333 #2338 #2204 #2346 #2353 #2213 #1940 (today's
overnight closures; verdicts honest — 3 `partial`, 1 `not-realized`).
**Backlog:** Now live at 8 actionable (no refill needed); Later sweep — zero stale; the
whole 95-issue corpus passes blocking hygiene (60 violations on this session's own
filings were fixed at wrap — see gotchas).
**Alarms:** all red >72h cited (registry clean on `check_alarm_citations.py`).
**CI warnings:** none to triage — the newest main run completed green at wrap; the
prior completed run was the doc-literal red, owned by (e2)'s decode + the incident row.
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## Part 1 — the /fullreview run-3 disposition (the "complete everything" ask)

Run 3's delta (produced on Fable by the prior workflow, `wf_e2e70bb0`) was found
untracked at session start with Phase 4 never run. It is now **fully dispositioned**:

- **Scorecard banked** (#2362): security **F → B+** (the #1943 genome absolute verified
  cleared live), cto B+→A-, reader B→B+, data-architect B-→B+, narrative B-→B.
- **6 findings fixed, merged AND deployed:**
  | finding | PR | what a reader stops seeing |
  |---|---|---|
  | R1/NAR-2 | #2361 | "Protein's under the floor every logged day" graded from **0/0** — `else None` at four API sites + `days_logged===0` render guards; also closed #2337 (the hoisted profile read) |
  | NAR-1/AIQ-3 | #2394 | six coach cards narrating a food-log "pause four days ago" that never happened — the prompt contract *prescribed* the phrasing; the never-logged branch now states the true fact and forbids the transition |
  | AIQ-2 | #2395 | the analyzer publishing with known-unresolved findings ("6→2" shipped 2 in prod) — regenerate-or-HOLD, gate moved **above** the cache write, ordering itself mutation-proved |
  | AIQ-1 (A-half) | #2396 | a Haiku condensation inventing a figure its source never contained — the fabricated-number floor on `guard_derived_summary`, covering BOTH derived-summary writers via the existing seam |
- **24 findings filed** (#2366–#2393 + the earlier #2360), each with the verifier's
  corrections embedded — several findings' prescribed fixes were WRONG and the issues
  say so (R4's "fix the writer" pointed at already-fixed code; the real culprit is
  `restart_leadin_pages.py`'s raw `[:300]` slice; R3's "coverage must not be 1.0" would
  contradict ADR-104's documented design).
- **The rest:** linked to open issues, verified-shipped-with-linked-fixes (DA-5, AIQ-7,
  AIQ-8 — checked against the actual merged diffs, not trusted), or refuted (exp-3).
- **Re-verification that mattered:** six findings were dispositioned "LINKED, not
  re-filed" against issues that CLOSED under the run (its SHA pin predated four merges).
  R2's live confirmation — the Webb card citing 2026-08-07's real HRV as current
  *after* #2343's fix merged — exposed the mechanism as the ungated `position_summary`
  re-parse, now #2390's subject.

## Part 2 — Telegram: idea → LIVE in one session (epic #2363)

**The insight that sized it:** the personality/memory/investment layer the owner asked
for already existed (voice specs with forbidden openings + humor styles + declared
inter-coach relationships; `relationship_engine`'s rapport arc; the `COACH#` memory
partitions; the fidelity harness). This was a **transport build**, and it shipped
end-to-end: PR #2365 (turn engine + 3-gate webhook gateway + setup script), #2397
(webhook + worker Lambdas + registration script), #2401 (CDK: FunctionURL + the
two-role trust boundary), all merged; `LifePlatformServe` deployed (74s); all 5
created bots registered; **the owner texted the coaches and they replied**.

Load-bearing design (ADR-151 records it): regenerate-once-then-HOLD (never
keep-if-better); the only no-exemption entry in the grounding registry (all 5 classes —
in a chat the owner picks the subject); budget rank with the daily brief (survives
tier 1, honest pause at ≥2, 40-turn/day cap); the chat writes `CHAT#` rows on the real
`COACH#` partitions so texting a coach feeds the dossier; routing keys are DOMAINS so
display names stay a `/setname` away from changing; glucose/labs deliberately not
created (attack surface); the board contact is the ROOM ("Grand Rounds", Eli Marsh
moderates inside it).

**Owner state:** 5/7 bots configured (`life-platform/telegram`, chat id 8724185006
discovered); sleep/mind/physical still need a "hi" + `setup_telegram_bots.py` re-run
(ENTER-keep now refreshes ids); explorer + board wait on BotFather's 24h limit —
tomorrow: create both, run the setup script, re-run
`register_telegram_webhooks.py --url https://hvqippdqcrbngivi5qifoaqmd40owrxu.lambda-url.us-west-2.on.aws`.

## The model-identity park (mid-session)

The owner discovered the session had run on Opus and called an abort/review. The
review's material finding: **the /fullreview ritual itself was never run on Opus** —
the run-3 delta was authored by the prior Fable workflow; this session only banked and
dispositioned it, so the ritual's model-identity rule was not breached. Everything
Opus-decided was either mechanically verified (mutation proofs) or sat on the unmerged
PR #2365, which the Fable resume then genuinely reviewed — and the review caught a real
defect: the grounding module had REIMPLEMENTED `allowed_numbers`/`allowed_dates` when
`ai.grounded_generation` already exports better versions (the fork would have made a
coach quoting its own memory read as fabrication). A source guard now pins the
delegation.

## Gotchas (the ones that will recur)

- **`agent_commit.sh`'s doc-literal restore SILENTLY REVERTS unnamed wrap edits when you
  commit on a side branch mid-wrap.** ADR-151, the SECRETS_MAP rows, both incident rows and
  the CLAUDE.md status block were all quietly checked out during the #2403/#2404 commits
  (only the named paths survive; handovers/ and site/ are outside the restore set, which is
  why the handover lived). Later edits then no-op'd against missing anchors while printing
  success. Wrap docs commit via PLAIN git (step f's own instruction), or name every doc.

- **The gates refused the transport work FIVE times, all correctly** — I5 (unmapped
  lambdas), SR1 (unregistered secret name), I3 (`lambda_handler` naming) + the
  handler-type-hint ratchet pre-merge; then R1/R2 caught the **KMS-on-CMK-table gap**
  (a silent runtime AccessDenied-in-waiting); then, post-merge only, the **#946
  singleton-tombstone guard** caught the worker's unguarded `RELATIONSHIP#state` read
  (the wiped cycle's rapport arc feeding a fresh-cycle chat — the #1897 vector);
  then, also post-merge-only, the serve-stack **Throttles-alarm set guard** (#1328's
  rule — for the worker at reserved-concurrency 2, a throttle is the owner's text
  silently queueing). New-Lambda registration is a SEVEN-gate affair (lambda_map +
  deploy.md, KNOWN_SECRETS ×2 + ARCHITECTURE table + S4 count, handler naming, type
  hints, role_policies IAM/KMS gates, tombstone guard, throttles-alarm set) — the
  post-merge-only members are candidates for the premerge lane (#2372's derivation
  would force the decision).
- **A `deploy/`-only merge triggers neither ci-cd nor the reconcile bot** — the stamped
  secret count redded main with no run to re-prove green and no bot to fix the four
  dependent doc literals (#2399/#2400, incident row). Check the trigger paths before
  assuming the bot will come.
- **Local black 25.9.0 vs the 26.3.1 pin bit again** — it "reformatted" ai_calls +3
  lines over an EXACT baseline. The repo now carries `.venv-black/` (agent_commit's own
  error message points at it); use it, never PATH black.
- **A branch cut from another feature branch goes CONFLICTING after the parent
  squash-merges** (#2398 → re-cut clean as #2401 via cherry-pick onto main).
- **`gh issue list --json -q length` defaults to 30** — the corpus is ~95; pass --limit.
- **The hygiene gate's audience vocabulary is exact** — 26 issues filed with
  "Owner"/"Readers" audiences cost a 60-violation fix-up at wrap. File with the
  sanctioned strings (`Matthew (the N=1 subject)` · `operator` · `Health /
  quantified-self enthusiasts` · `Friends & family` · `Reddit newcomers`) the first time.

## Residual / next picks

- **#2402** — the coaches text like coaching cards pasted into a chat (owner's own
  verdict after first use); per-coach texting registers, message bursts, memory depth.
  `model:fable`, owner taste session.
- **#2326** — MacroFactor now 46 days quiet; **the single highest-leverage owner action
  for the new chat**: Webb has a voice but nothing to say about food until an export
  lands. `gate:owner`.
- **#2381** — August's tier-2 pause is arithmetically due **~08-16** (verifier moved it
  earlier than the seed); decide the posture this week or it's July's scramble again —
  and it pauses the Telegram chat too. `gate:owner`.
- **#2390** — the invoke-site census: measured 64 modules invoking a model seam, 53
  unregistered; each needs its destination VERIFIED before an honest exemption. Also
  carries the R2/AIQ-6 live check: confirm the Webb card renders day-honest after the
  next 17:02Z generation.
- **#2377** — bundle commit fingerprints (the 08-08 deploy race, unmechanized), `Now`.
- **#2369** — raw subscriber emails in CloudWatch logs ×3 + the standing PII-log guard, `Now`.
- **#2382 residue** — the deterministic absence-transition guard (LogAvailability
  carries category sets, not dates — its own change).
- Tomorrow's bot completions (explorer + board + the three chat-id refreshes) are owner
  steps recorded in the memory topic. not-work — owner phone actions, not backlog.
- The two zombie gated runs stay pin-excluded in `deploy/watch_deploy_gate.sh`.
  not-work — documented leave-alone; GitHub expires them at 30d.
