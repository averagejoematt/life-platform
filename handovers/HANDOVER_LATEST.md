# HANDOVER — Coaching brilliance + the orchestrated queue burn — 2026-08-10 ~03:00Z → ~05:0xZ

> Instruction thread: *the plan file `~/.claude/plans/distributed-sprouting-yao.md` (all owner decisions pre-resolved: fully autonomous, spend Fable to ~95%, all four coaching features in scope), plus an expanded mandate in the session prompt: "don't just take my ideas — talk to the board, the product team, the spirit of the website, use your own research… how can these coaches pass a test with humans that they aren't AI… if you think of 50 ideas that make me wake up and feel like they are way better to talk to on Telegram, do it. Reach for the stars."*

**The one-line outcome:** the coaches got a **character upgrade grounded in evidence rather than taste** — the first night of real transcripts was harvested and read, its five robotic tells named and fixed, the chat surface's *never-actually-enabled* prompt caching turned on, coaches made experiment-aware (Day N, their own open predictions), and bounded initiative shipped (referral handoffs + Eli's morning check-in, dark until BotFather) — alongside a 19-PR queue burn and a green deploy-of-record.

## The evidence that drove Act 1 (read this before tuning voices again)

A subagent harvested every real `CHAT#` row (4 partitions with traffic: sleep 15, training 15, nutrition 9, mind 8; all 2026-08-09→10). Findings, all now fixed or filed:

- **Register asymmetry is the loudest tell.** Matthew texts a median of 2–5 words ("Hi", "Yo", "PPL", "Push I think", max 126 chars). Coaches averaged 121–294 chars, max 676. The best conversation in the corpus — the training re-entry thread — is precisely the one whose replies came closest to *his* length.
- **Stat recitals.** The sleep coach opened three consecutive replies with the same "6.8h vs 7.8h average" line, once in answer to "Tell me about yourself" and once to a bare "Hey".
- **Question compulsion.** 12 of 22 replies ended in a question; "What's on your mind?" appeared four times, twice back-to-back from the same coach.
- **Shared stock phrases across supposedly distinct voices** — "Honest answer:" used verbatim by two different coaches.
- **The identity catastrophe (pre-#2478).** Matthew used the coaches' human names and they *denied having them* — "I'm not Lisa!", "mind_coach is the handle". Worse, the summarizer memorialized it: Lisa's long-term memory now contains a note asserting she is not Lisa.
- What already worked: burst rhythm (8/22 multi-bubble), honest data refusals in voice, and lane-passing by name with correct pronouns (#2478 landing well).

## Act 1 — coaching brilliance (3 PRs + a roadmap)

- **#2481 the humanity pass.** CONVERSATION RULES v2 from the evidence above: register matching (a bare "hey" gets a bare hey back), question budget with the filler-question ban, assistant-ism/stock-opener ban, sparing name use, no formatting in texts, **off-lane conversation explicitly welcomed** ("you're a person he knows, not a service line"), and **persona-outranks-remembered-notes** — which defuses the poisoned "not Lisa" row without editing his data. Plus: **the system prompt now actually caches.** `build_request` had been sending `system` as a plain string while the docstring claimed COST-OPT-2 caching — on the platform's highest-frequency AI surface. `build_system_blocks` emits the stable prefix (persona + texting + colleagues) as a `cache_control: ephemeral` block; both renderers derive from one `_system_parts` so they cannot fork. CHAT#summary voice moved from third-person minutes to the coach's own first-person notes. `chat_pk("eli_marsh")` → `COACH#eli_marsh` (was inventing a `_coach`-suffixed partition no other surface reads) — fixed pre-traffic, nothing migrates.
- **#2498 experiment-aware coaches.** `EXPERIMENT FRAME:` block — Day N of cycle 13, week N — plus each coach's own ≤3 open `PREDICTION#` calls (read-only, `with_phase_filter` mandatory), and Eli alone gets the integrator's weekly priority. Two judgment calls by the implementer, both right: it used the integrator's *actual* week expression (so a coach citing the row names the same week the row does), and it passed `generation_date_iso=PT` into the grounder — without which a UTC-anchored gate would have **held every evening reply that named the day**, 5pm–midnight PT, nightly.
- **#2505 bounded initiative** (merged last — see the IAM note). Referral handoffs via a `[[refer: id]]` marker (stripped from every send path; unknown/self/no-bot/quiet-hours/cap all fail dark), Eli's weekday 10:15-PT check-in, silence respect (stop after 2 ignored), one shared ledger capping unsolicited texts at 2/day (referrals ≤1). Training route aliased to Max so Matthew's existing training-bot thread continues. Its gates caught three real things, including that the telegram worker had **no error alarm** — fine when every invocation was a text he was waiting on, not fine once a cron path exists.
- **`docs/design/COACH_HUMANITY_ROADMAP.md` (#2484)** — the standing ledger for the mandate: a seven-property theory of why texting feels human, 52 ideas marked shipped/filed/horizon, and a discipline section (grounding never relaxed for feel; initiative stays scarce or it becomes app notifications). **12 stories filed #2485–#2496** under a new `area:coach-humanity` label and stitched into epic #2363: reaction emojis, open-loop promise-keeping, voice notes in each persona's TTS voice, event-triggered celebration/concern, an inside-references ledger, Grand Rounds group chat, track-record humility.

## Act 2 — the burn (19 PRs merged, 12 issues closed, 31 triage actions)

Shipped: #2464 agent_commit nonzero refusals · #2467 wedge detector sees gate-parked runs of any age · #2351 find_days `mode='similar'` · #2414 PT-today sweep (**the guard found 49 sites, not the estimated ~15**) · #2370 privacy scrub (**~60 files** once counted honestly — including a regex-embedded literal and a zero-width-split instance; several fail-opens converted to fail-closed) · #1905 /legacy clinician attributions (found a higher-severity stray the issue missed) · #2331 strava measured-zero (the sweep found **648 of 650** zero-distance rows are trainer sessions, where storing 0 would fabricate the *opposite* way — so the rule needed a channel arm, not just a type arm) · #2326 MacroFactor quiet-notice · #2350 repetition detector (deterministic, advisory).

Triage: epic #1024 closed complete; 7 Later→Next promotions; 2 fable→opus relabels; ratification comments on every epic and Later story needing Matthew's ruling. **Open corpus 64** (41 stories: 4 Now / 13 Next / 24 Later; 15 epics).

## Gotchas (novel this session — durable copies in memory)

- **Fail-closed must be scoped to the ARTIFACT, not the lane.** #2503's raising channel sat inside a reconcile generator, and three consecutive main runs died — literal reconciliation stopped platform-wide over a CI secret that doesn't exist yet. Fix (#2510): hold the regen, exit 0. Grep `run_generators` in ci-cd.yml before adding any fail-closed dependency.
- **A volatile timestamp inside an asserted blob is a ~10%/run flake.** `assert "43" not in json.dumps(result)` reds whenever `compressed_at`'s microseconds contain "43" (#2509).
- **The pre-commit hook stages doc literals into EVERY commit — including `--allow-empty`.** One one-file test fix needed four branches (#2497→#2502→#2504→#2509) as each re-minted commit re-acquired the literals and went CONFLICTING. Use `agent_commit.sh` for driver commits too; resolve rebase literal conflicts with `git checkout origin/main -- <files>`, never `--theirs`.
- **The black pin skew bites the driver, not just implementers.** Local 25.9.0 passed `visual_qa.py`; the 26.3.1 pin rejected it, and after formatting with the pin the *hook* (PATH black) refused the commit. `agent_commit.sh` resolves this correctly.
- **A visual-QA all-empty FAIL cannot tell a genesis dark state from a broken bind** — it rolled the site back in a loop, reverting a privacy fix. #2511 probes the page's own `api_deps`: affirmatively-empty payload → warning; unknown shape/non-200/populated → still gates.
- **The eternal skeleton (#2514).** That same discoveries failure was diagnosed as a *transient origin hang during the fleet deploys*, not a render bug — the page is correct live. But `getJSON` had no timeout, so a fetch that never settles slides past `tryJSON`'s catch-only guard and strands the skeleton forever, across ~15 renderers on all four doors. One `AbortSignal.timeout(10000)` at the chokepoint.

## Residuals / next picks

- **Owner ①** `bash deploy/cdk_deploy.sh LifePlatformServe` — **required**: #2505 carries new infra (EventBridge weekday rule + worker `UpdateItem` IAM) and per R8-ST6 an undeployed IAM merge strands later CI deploys. Until it runs, Eli's check-in has no schedule (it is independently dark anyway, no bot token).
- **Owner ②** BotFather trio (@ajm_headcoach_bot / @ajm_pattern_bot / @ajm_career_bot) → `setup_telegram_bots.py headcoach pattern career` + `register_telegram_webhooks.py`; rename @ajm_longevity_bot's display to Dr. Max Reyes. The morning check-in and all Vale/Brooks referrals light up the moment Eli's token lands in the secret.
- **Owner ③** `CONTENT_FILTER_JSON` repo secret + `config/content_filter.local.json` on the main checkout (#2503) — until then the two scrub CI gates skip with a visible warning and the game-page regen holds.
- **Owner ④** `python3 scripts/reconcile_strava_measured_zero.py` (review the 6-row plan, then `--apply`) — optional; new ingests are already correct.
- **Owner ⑤** the ratification list — epics #723 / #1668 / #2363, and the close recommendations on #1414 / #1402 / #1401 / #1631.
- **Owner ⑥** portraits contact-sheet for Vale/Brooks (ADR-106); #2465 Monday rituals.
- **Live QA is the acceptance bar for Act 1** — text the coaches in the morning: do they match your register, skip the stat recital, take an off-topic message like a person, and cite their own predictions naturally? #2492 (prompt-pass v3: grounded pushback + conversational repair) is the filed follow-up.

## Model note (matters for what the next session may pick up)

The Fable weekly allowance was exhausted partway through the close-out; the tail of this session ran on **Opus 5**. Everything after that point was mechanical — merges, gate reruns, deploy verification, the wrap — deliberately **no `model:fable` work was started**, because a voice/taste judgment made by a different model than the one the ritual is calibrated on isn't the same artifact (`feedback_review_ritual_model_identity`). Deferred to the Fable reset (Saturday), not dropped:

- **#2492** prompt-pass v3 — grounded pushback + conversational repair. This is the highest-value coaching follow-up and it is deliberately `model:fable`: it is few-shot and register work against real transcripts.
- **#1114** coach portrait art direction v2 (ADR-106 — Matthew's approval gate either way).
- The frontier/ideation `model:fable` set: #1415, #1391, #1389, #1380, #1400 (now opus), #1570, #748.

Anything in that list appearing in a "next picks" prompt should be re-checked against the model budget before it starts.

**Build beat:** `2026-08-10-coaches-that-text-like-people` — the humanity pass, from real transcripts to shipped rules (merged + deployed via run 31354465497).
