# Handover — 2026-08-21 (~10:00 → ~18:30 PT): four epic tails drained, and every gate I touched was lying about something

**Session:** Opus, owner-directed. The driving question was literally *"what can we be doing without
fable to really get the open issues paid down? Are there things I am blocking?"* — so this was a
backlog-drain session with a deliberate no-`model:fable` constraint. Previous wrap archived as
`HANDOVER_2026-08-20_p1-rate-limit-identity.md`.

**Build beat:** none — six PRs shipped and deployed, and a reader can see **none** of it. The work
is a pre-merge derivation, a mutation-proof ledger, two doc regenerations, an impossible percentage
removed from one API row, and a CI gate that now fails when it cannot run. Per
`docs/content/BUILD_DISPATCH_CHECKLIST.md` a beat needs merged **and** deployed work a reader
experiences; the closest candidate (the `light_pct` fix) is a number *disappearing* from a chart.

**Main:** green (`e9892197`) — with one decode, closed via `--decoded`. `check_main_green.py` reports
the latest **completed** CI/CD run green (`32537046993`: Deploy ✅ Smoke ✅ Visual+AI QA ✅ Post-deploy ✅,
rollback skipped), then correctly flags that main's HEAD `6d7b89ab` has no run referencing it. That is
**not** the swallowed-push shape: `6d7b89ab` is a `chore(reconcile)` commit authored by
`github-actions[bot]`, and a GITHUB_TOKEN push never dispatches a workflow — it mints zero runs by
design. Its parent `d6074bf7` has run `32541686521`, still on its Deploy leg at wrap time.

**Docs:** `docs/CONVENTIONS.md` (new §4a1 — the pre-merge command; new §8b — the closure convention),
`docs/SCHEMA.md` (paste partitions ×2 sk forms, 4 weather fields, the pruned-tool note, the raw
filename), `docs/DATA_GOVERNANCE.md` (inbound-social retention row), `docs/INCIDENT_LOG.md`
(Patterns regenerated + 3 backfilled rows + 3 new session rows).

**Decisions:** none needed — no governance-consequential choice landed. The nearest was #2841's
"do not accept the false-red rate", which is a *measurement-driven scope call* recorded on the issue
and as a CONVENTIONS §8b rule, not an architecture/data/deploy-posture change.

**Incidents:** 3 rows added — the deploy-plane wedge (two gates, ~6h and ~2.5h, auto-filed #2937);
the dark AI gates on the deploy path (#2938); the live impossible `light_pct: 106.7` on
`/api/sleep_detail` (#2939).

**Closures:** #2924, #2810, #2638, #2840, #2938, #2937 commented (ADR-099 shape). #2938 is
deliberately **partial**, not realized — see below.

**Backlog:** Now live at 9 actionable; no refill needed. No stale `Later` issues printed.
`check_backlog_hygiene.py` printed one blocking violator (#2932, no `## Outcome`) — fixed in-session
with a sanctioned-audience Outcome; gate now `OK — 82 open issue(s)`.

**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.

**Alarms:** 0 uncited — every alarm red >72h cites an incident row or issue, and nothing red >14d
lacks a filed issue.

**CI warnings:** 2 — both triaged, no new issues filed. (1) *Smoke test content-truth failures,
non-gating (#1921)* — these are the `/api/sleep_detail` findings this session diagnosed and fixed;
the count already dropped **2 → 1** between the two runs as the fix propagated, and the remainder is
the reader-truth false positive whose suppressor ships in #2939. (2) *Unit Tests over its 1200s
budget* — measured **1517s** then **1482s** across tonight's two runs; either way this is the **fifth**
crossing and wider than #2692's recorded 1247s. Commented the new measurement on #2692 rather than
raising the budget, since that issue's own title says "measure before raising it again"; ~30 of
tonight's tests are mine and I said so on the issue.

---

## The shape of the session

86 → 82 open. Five closed, two filed by me, one reopened by me correcting my own error, one reopened
on honest re-scope. **Net −4.**

The premise I was given ("we haven't got much done") turned out to be wrong, and worth correcting:
the previous 10 days shipped 181 PRs and 158 closures. What was flat was the *open count*, because
two review days filed 117 issues. I recommended not running another `/fullreview` until the elite
review's 33 remaining issues drain.

The strategy was **epic tails** — four epics were 1–2 issues from closing, so draining them buys
closures at ~1.5× the rate of cherry-picking.

## What shipped

| PR | What |
|---|---|
| #2933 | the pre-merge derivation was blind to a sweep one import away (#2924) |
| #2934 | SCHEMA rows for the two newest signals (#2810) |
| #2935 | the mypy mutation proof went stale in the ledger built to prevent that (#2638) |
| #2936 | INCIDENT_LOG patterns become derived; silence scored honestly (#2840) |
| #2939 | no impossible stage percentage + the gate that missed it, and the oracle's UTC arithmetic |
| #2940 | a requested AI gate that graded nothing is a FAILURE, not a warning (#2938) |

All six merged. `eightsleep_lambda.py` + `reader_truth_qa.py` deployed via fleet (104/104 Lambdas
verified by `LastModified`; the 6 untouched are CDK's own `LogRetention` helpers).

## The through-line: every gate I opened was lying about something

Not one of the four epic-tail issues was what it said on the tin.

- **#2924** asked to "demote the 168-test set honestly". The derived entry point it wanted **already
  existed** (the `premerge` marker) — 155 of the 168 tests were in it. The 13 that weren't exposed
  the real defect: the #2372 derivation reads each test file's *own* source, so a guard factoring its
  sweep into a helper is invisible. `test_conformance_guard_2844.py` — the **charter conformance
  guard** — landed 08-17, was classified nowhere, and ran post-merge only **inside the command
  everyone called a pre-merge check**. 24 files, 22 unclassified.
- **#2638** was four-fifths done. Verifying the open box found the census's own recorded proof had
  been **wrong for six days** (`return-value: exit 0 — SILENT`, enabled two days later). `scope`
  exists so "can-fail" cannot read as "fully armed" — but the staleness guard compares **gate IDs,
  not claims**.
- **#2840**'s silence axis **does not reproduce**. Medians 23.5 vs 12.0 min, means within 10%, and
  58 of 149 TTD cells unparseable. The direction holds; "days-scale vs minutes" came from the worst
  ~10 rows. Said so in the doc and enforced it with a test.
- **#2841** I deliberately did **not** close. Measured 13 false-red rows in 21 August days — 1 per
  1.6 days, *not improving*. A dated acceptance would have been optimising for a tidy count while
  auto-rollback un-ships healthy code.

## The find of the night

A monitor fired a confirmed reader-truth FAIL on `/api/sleep_detail`. Chasing it produced three
things, in order of how wrong I was:

1. I told the owner the oracle "reads UTC as local". **Wrong** — it converted and applied **PST in
   August**. One hour, which moves the instant across midnight. I had worked from a 300-char
   truncated log line; the full note refuted me. Corrected on #2841.
2. The oracle flagged the wrong row. One row above, `light_pct: 106.7` was **live on the public
   site** (`deep 11.1 + rem 31.1 + light 106.7 = 148.9%`).
3. **Why nothing caught it:** `accuracy_audit.impossible_values` had exactly the right rule (`_pct`
   in `[0,100]`) but read two blocks of ONE document. The bad value was in a *list*, on an endpoint
   it never fetched — #2652's defect in the numeric gate.

Then, verifying the deploy: **both AI gates in the deploy-gating `visual-qa` job were dark.** `boto3`
was never installed in any of the three copies, so `--ai-qa` and `--reader-truth` printed `⚠` and the
job reported **success** — while CLAUDE.md and ADR-076 describe them as gating since 2026-06-05.

## Judgment calls worth keeping

- **Guard the invariant, not a proxy.** My first `light_pct` guard omitted percentages whenever
  stages failed to reconcile with TST. Measured across all 991 rows: **45 fail to reconcile, 1 ever
  published an impossible number.** That guard would have stripped 44 nights of plausible figures to
  fix one defect. Rewritten to fire on the thing that cannot be true.
- **Measure before arming.** Widening the numeric gate is how the 2026-07-17 spurious rollback
  happened. Swept live first: **59/59 endpoints, one finding, the known one.**
- **Sequencing.** #2938 was landed **last** on purpose. Arming the AI gates any earlier would have
  red-flagged the deploy path on defects still live.

## Mistakes

- **I closed #2921 by accident** by writing `"Does NOT close #2921"` in a commit body. A negated
  closing keyword still closes — the parser cannot see the `NOT`. This trap is in my own memory and
  took out #1221 two sessions ago. Reopened.
- **I closed #2578 overclaiming.** I wrote "all five acceptance boxes verified"; box 2 (*every gate
  carries a verdict*) is **6 of 482**. I verified the mechanism and let it stand for the population.
  Reopened with an honest scope.
- **The #1964 guard caught me** building a second Pacific frame inside the function whose job is
  catching wrong Pacific conversions. Pre-merge, not on main.
- **My own test caught** the ISO instant's `07:02` being read as the model's stated conversion.

## Residual / next picks

- #2652 — QA coverage: box 3 remains, **69 uncovered GET routes** (boxes 1/2/4 already shipped;
  11 POST write-doors excepted with a derived reason)
- #2803 — privacy-tier AST gate; biggest of the set, Tier-2 medical fields reaching public/AI surfaces
- #2932 — capture-door idempotency collapse (latent, `## Outcome` added this session)
- #2921 — the device-interleaving half, genuinely untouched by #2939
- #2578 — reopened; box 2 needs an honest bounded definition, and `unproven` must stop meaning both
  "not examined" and "fine"
- #2841 — standing umbrella for the QA-oracle false-red class; re-measure the rate next session
- #2938's unclaimed box — *not-work — sweep for other CI steps invoking a flag whose dependency the
  job never installs; named in the closure comment as a real residual, no issue filed yet*
- #2692 — Unit Tests wall-clock, now 1517s; commented, not raised
