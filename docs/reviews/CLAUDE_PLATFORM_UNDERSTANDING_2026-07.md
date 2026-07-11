# How well does Claude actually understand this platform? — 2026-07 self-assessment

> **Status:** point-in-time review (audit record) · **Author:** Claude (Fable 5), 2026-07-11 overnight sweep · **Requested by:** Matthew
> The question asked: *"how much do you fully understand the website, the platform, the content, the experiment, the purpose — and is there anything better we can do with our SDLC, context, or subagents?"* An honest answer requires evidence in both directions. The ER-05 caveat applies: this is self-assessment against a self-authored rubric.

## What I demonstrably understand (evidence from this session)

**The purpose.** The causal loop (DATA → COACHING → PROTOCOLS → shifts the data, narrated by THE STORY), the four audiences, proof-not-promises, honesty-as-moat, the non-negotiables (correlative-never-causal, no AI arithmetic, privacy absolutes, restraint over gloss). Evidence: tonight's ranking decisions consistently used these as tiebreakers without re-deriving them — e.g. killing a glow proposal on sight, framing every filed issue's "outcome" in loop/audience terms.

**The system.** Ingest→store→serve, the single-table key families and phase taxonomy, the budget governor tiers, the one-bundle deploy rule, the reset machinery, the AI chokepoint + honesty gates (ADR-104/105/108), the MCP surface. Evidence: the sweep's 13 lens briefs were written from memory-plus-index in one pass and none of them missed their target subsystem; the verifier pass confirmed 67/70 of what they found.

**The operational reflexes.** Worktree discipline, squash-drift, doc-sync literal conflicts, reset-aware tests, deploy-from-main, the render-QA bar. Evidence: tonight began by pruning 5 stale worktrees *before* the baseline suite (the exact trap in memory), caught main red from the reset's honest snapshot refresh, and fixed it with the #941 pattern rather than reverting the honesty.

**The character engine, as of tonight.** Formula-level: EMA/streak/step leveling, XP bands/debt, blend/coverage semantics, atrophy — plus the five places its arithmetic betrays its own honesty contract (see `docs/engines/CHARACTER_MATH_AUDIT_2026-07.md`).

## Where my understanding is genuinely thin

1. **The lived reader experience.** I read copy and structure; I don't *feel* the weekly return-visit pull, and my taste for "does this land emotionally" is a proxy built from Matthew's past verdicts. This is why the taste gates (portraits, visual identity, story voice) rightly stay human. The throughline lens partially compensates — but it is still a model reading a site about a man, not a friend checking if he's okay.
2. **Matthew's off-platform context.** I know what's logged. Cycle-5's *why now*, energy, and appetite for risk are things I infer from instruction tone. When I filed #955 (presence across genesis) as a decision rather than deciding it, that was this limit operating correctly.
3. **The long tail of ~94 lambdas.** I hold maybe a third at implementation depth at any time; the rest I re-derive on demand. Re-derivation works (tonight's lenses did it) but costs tokens and occasionally misses cross-module interactions until a sweep like this forces them out (e.g. the singleton-reader class cut across four modules nobody "owned").
4. **Live-state drift between sessions.** My model of AWS state ages the moment a session ends; docs that assert current-truth-that-isn't actively poison recall (this sweep found and fixed several: the hypothesis-engine cadence claim, the 27-vs-40 verify count, a memory entry still teaching the retired layer-deploy path). The existing rule — verify live at write time — is right; the failure mode is docs written as intention.
5. **Cross-ADR interactions.** 133 ADRs exceed working context; the index works for lookup, but interactions (e.g. ADR-104 absence semantics × the confidence blend × the #913 up-gate = tonight's critical finding) only surface when something forces joint reasoning. The character audit found exactly this class.

## Verdict

Strong-to-authoritative on purpose, architecture, conventions, and the honesty machinery; competent-but-reconstructive on the long tail; structurally weak on lived experience and off-platform context — which is precisely where Matthew's judgment is already the gate. The failure mode to guard against is not ignorance but *stale confidence*: docs/memory asserting yesterday's truth. The counter is mechanical (drift gates, tombstones, verify-at-write) and is working — extend it (#973) rather than trusting better recall.

## SDLC / context / subagent changes (shipped tonight or filed)

| Change | Status |
|---|---|
| `/platform-review` skill — the R22-style sweep (survey→dedup→verify→file) as a reusable command instead of a thrice-rebuilt bespoke ritual; tonight's run validated the recipe (67/70 findings survived adversarial verification vs the historical ~50%) | **shipped** (`.claude/commands/platform-review.md`) |
| `issue-filer` agent — encodes the ADR-099 filing contract (labels, milestones, score lines, epic linking, public-repo privacy discipline) | **shipped** (`.claude/agents/issue-filer.md`) |
| Repo-walk tests skip `.claude/` worktrees + `cdk.out`; beats.json schema validated locally at wrap | shipping (#953) |
| Memory hygiene: terminal Active Work entries archived per #797; the stale layer-deploy entry retired | **done** (memory dir, at wrap) |
| CLAUDE.md corrections: hypothesis-engine cadence, 40-URL verify surface | **shipped** (this PR) |
| Doc-drift gate-gap class (prose counts, verified-dates, engine-doc↔code) | filed #973 |
| Permissions kernel: mutating aws wildcards without ask rules | filed #977 (Matthew's call) |

**What I'd ask of Matthew** (the two highest-leverage context gifts): (1) when a session's instruction embeds a *mood* ("character should be sad"), keep doing that — tone constraints are the off-platform context I can't infer; (2) when you overrule a ranked pick, one line of *why* into memory compounds — the taste model improves only from verdicts.
