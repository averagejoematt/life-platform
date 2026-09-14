# Handover — Session AB: land the held campaign, and find it inert (2026-09-13 ~03:00Z → ~22:00Z)

**Driver:** Opus 5 (1M). Owner brief: read Session AA's handover, then the approved plan — *"Phase 0 — land PR #3713. I've ruled: reconcile and merge it… prove it by shipped behaviour, not by sha."* Standing authority to merge, deploy and action deploy gates.

## The through-line

The plan said to prove #3713 **by running it**, because `training_week.json` is S3-read and a repo-side fix can be inert (#3675's trap). That instruction is the session. The branch merged clean, deployed clean, verified clean in the bundle — and the feature it delivered did not work.

`build_reference` returns eight keys. `build_training_reference_record` copied **six**. The two it dropped were `reference_schema` and `proven_bands` — the exact pair **#3710 added so a consumer could tell a stale record from a current one that found no comparable period**. Four minutes after episode-detect was redeployed *and re-run*, `get_benchmark view=prescription` still answered:

> *"training_reference is v1 … **episode-detect needs redeploying and re-running** before this view can answer."*

It had just been redeployed and re-run. The message could never clear: the writer could not produce what the reader was looking for. **#3708 ranked 4.00 — the top of the whole corpus — and the views built on it shipped inert, reporting their own inertness as an operations problem.** The merge, the CI run, the deploy and the bundle were all honest; `verify_deployed_symbol.sh` confirms `reference_schema` *is* in the shipped bundle. It just never reaches the row. Filed **#3735**, fixed in **#3736**, and closed on live proof — `applicable: true`, nearest band 310-319 at `band_distance_lb 1`, honestly refusing to prescribe from 4.0 effective days against a floor of 21.

Then the deploy of that fix went red at the accuracy gate — on **three honest numbers**. `delta_pct: -8.5` beside its own `direction: "declining"`, `delta_pct: 107.8` beside `"improving"`, and a `z2_pct` whose producer's comment says *"served uncapped"*. Same class as #3725 one day later, third and fourth specimens. Filed **#3739**, fixed in **#3740**.

## Shipped

| | what | status |
|---|---|---|
| **#3713** | Session Z's 7 stories — the campaign-reference chain | merged `5a0bcd46`, **deployed + verified by bundle content** |
| **#3736** | `training_reference` carries what the reference computes (#3735) | merged `5d9edd24`, **deployed + verified live** |
| **#3740** | `delta_pct`/`z2_pct` are the 3rd/4th `_pct` domains (#3739) | merged `1937867c`, deploying |
| **#3737** | the labs window frame (#3728) + ink-on-wash (#3726) | open, green, mergeable |
| **#3738** | four instruments that could not do their job (#3721/#3722/#3732) | open, green, mergeable |

**#3516 closed on live proof** — the source-facet gate fired on the physical coach 2026-09-11T17:04:35Z against the exact filed sentence, and all seven served coaches are clean with Garmin still paused, so it is a real pass and not an empty one.

## What running it found that reading it could not

- **#3728's filed diagnosis was wrong.** Not cycle-vs-lifetime. FOUR inputs reach the analyzer with THREE windows, and the culprit is `build_data_inventory`'s **rolling 90 days** — a third window nobody named. All 8 draws are 2026-04-03, so `exists` was False, the coach got "0 blood draws of data" beside a fact block naming its 8, and it reconciled that by narrating a completed panel as an upcoming appointment. `dexa` did the same to the **physical** coach's `requires_dexa` branch, pinning it to orientation permanently.
- **The defect changed clothes mid-session and the check went quiet.** At 17:07:01Z the analysis regenerated on the old code, stopped saying "zero lab draws" — so the regex found nothing — and told him *"Report any unusual fatigue or cold sensitivity **before the April draw**"*. A regex over one phrasing cannot see a defect that rephrases, so the check now asserts the FACT: when the newest draw is in the past, no served text may arrange one or instruct ahead of one.
- **#3721 was not one stale generator. It was fifteen.** Ten found by running each against a clean tree; five more write through a MODULE CONSTANT, so `.html` never appears at the call site and my own first detector saw nothing — **two of those five I had exempted as "a JSON artifact" on the strength of their docstrings.**
- **#3722 instrumented, not assumed.** The filed suspicion (lazy boto3 credentials) was close but wrong: the mechanism is per-call **latency**. A property test over pure functions was making ~150 live CloudWatch round-trips per run — median 18.1ms against a 200ms deadline.
- **#3726 repairs 11 live AA failures across 7 pages**, not the 3 the nightly reported; render-QA found `/data/mind/`, `/data/vitals/` and `/data/character/` failing too, with nothing measuring them.

## Gotchas hit — three of them mine

- **A CONFLICTING PR mints no checks, and I had the memory and did not apply it.** PR #3737 showed zero runs; I read it as the swallowed-push class and worked two rungs of the ladder (close/reopen, empty-commit supersede) — each "confirming" the swallow, because none of them can build a merge ref that does not exist. `gh pr view --json mergeable` was one command away. Third occurrence; the memory's trigger now names the swallow ladder explicitly, not just the outage hypothesis.
- **A sweep that restores a directory destroys your own uncommitted work in it.** My generator sweep ends each iteration with `git checkout -- site/`, which ate this session's uncommitted `tokens.css` and `evidence_body.js` **twice**. The first loss was caught only by a test I had just written; the second only by a stray `git status`. New memory written.
- **`git checkout main 2>/dev/null` can fail silently** and the whole wrap battery then grades the wrong tree. Caught by an unexplained diff, not by the gates.
- **A green `gh pr checks` is not a green check SET.** `wait_pr_green.sh` read 8/10 by name while `gh pr checks` reported settled-with-zero-failures — two expected checks had not attached. Absent ≠ pass.

## Verification

Full suite locally **25,596 passed** on the combined tree before the split. Every control mutation-proved: the inventory window, the `out_of_window` state, the preamble branch, both directions of the labs check, the past-draw-as-future arm, the wash contrast block and its derived selector list, the generator guard and its own detector, the telemetry off-switch and its bounds, the coverage band, and the wire contract against the exact shipped bug. **The module-size guard was paid out of extractions, not raised numbers** — `output_writers.py` 1116 → 990, which **leaves the accepted-debt registry entirely**.

**Build beat:** none — the two reader-facing PRs (#3737, #3738) are green and mergeable but not yet merged+deployed at wrap time, and a beat narrating work that is not live would be a plan.
**Docs:** `docs/PROPORTIONALITY.md` + the doc-sync literals (regenerated); `docs/OPERATING_KNOWLEDGE_LEDGER.md` reconciled during #3713's merge (three duplicate rows collapsed to their `homed-here` versions).
**Decisions:** none needed — every change this session is a defect fix inside existing ADR-104/105 semantics; no governance posture moved.
**Main:** green (`1937867c`) — the #3740 deploy is in flight; run 34770720925 earlier went red at `Visual + AI-vision QA` on the #3739 cause, with Deploy itself **success** and auto-rollback correctly skipped.
**Incidents:** 1 row added — the deploy-gating accuracy audit failing a healthy deploy on three honest `_pct` values (#3739), the second instance of the #3725 class in two days.
**Stash/hooks:** clean — one stash found (`WIP on fix/labs-window-frame-3728`), inspected, confirmed a duplicate of work already committed to #3737's branch, dropped.
**Closures:** #3516, #3724, #3735, #3739 commented · DoD: scanned 10, hits 3 after commenting — all three are `post-close-assertion` on #3709/#3710/#3711 matching the literal word "reopen" inside a comment that argues *against* reopening and discharges the residual; dispositioned as false positives of my own wording, `blocking=none`.
**Backlog:** Now live; milestones set on #3733, #3734, #3739 (filed this session without one). Later sweep — no stale issues surfaced.
**Alarms:** 0 uncited — board clean after three re-cites. `qa-smoke-failures` was cited to `coach_labs:truth` and the live cause now reads `-`; **that is the finding, not a resolution** — the analysis rephrased at 17:07Z, the regex went quiet, and the reader-facing defect did not move, so it is re-cited to #3728 with a note forbidding the empty read from being taken as the alarm clearing. Two fired-and-cleared DLQ flaps (`life-platform-ingestion-dlq-messages`, `life-platform-dlq-depth-warning`) recorded as `not-work` episodes under the #2912 detector rather than waved through because the board reads green now.
**CI warnings:** unverified — the latest completed main run is not green (the #3739 gate red), so there is no green run to read annotations from; #3740 is deploying and the next green run carries them.
**Ledger:** none — no standing machinery shipped; every change altered the behaviour of gates, generators and writers that already exist and already carry their rows.

## Residual / next picks

- **#3737** — the labs window frame + ink-on-wash. Green and mergeable; merge, approve the gate, then verify: invoke `ai-expert-analyzer` with `{"expert": "labs"}` and confirm the served `position_summary` stops arranging a past draw.
- **#3738** — the four instruments. Green and mergeable; merge and approve the gate.
- **#3739** — reopened deliberately: enumerating every `*_pct` the API can serve is the end of this class, and a deploy running green through `Visual + AI-vision QA` is its live proof.
- **#3728's `/api/labs` half** — the scope fields need the next scheduled 17:00Z brief. `write_clinical_json` has one live caller and DRY_RUN suppresses every write by design (#2255), so there is no build-but-do-not-send path; forcing it means sending a duplicate brief. `not-work — a clock-bound verification, not an implementation task.`
- **#3726's live proof** — the standalone nightly at ~22:00Z is the acceptance. If #3737 lands first, tonight's run is the proof.
- **#3733** — `/method/` and `/method/cycles/` overflow 248px at 1440, confirmed against production, pre-existing.
- **#3734** — `/data/vitals/` clips its own stamp at 390px, pre-existing.
- **#3731** — `Refs`, not `Fixes`: one term of one of four acceptance boxes. The remaining decomposition targets are measured and named on the issue.
- **#3715** — the training-constraints home. Research done and not implemented: the canonical home already exists at `config/user_goals.json::known_constraints`, already read by `build_coach_preamble` and the analyzer; what is missing is dated injury/equipment entries, not a new file. Its last acceptance box is `gate:owner`.
- **#3499** — not started.
- **#3716**, **#3717**, **#3719** — `gate:owner`; merging code does not settle an owner ruling.
