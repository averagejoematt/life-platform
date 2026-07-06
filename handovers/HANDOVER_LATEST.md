# HANDOVER — R22 Consultancy Review: 47 findings filed #779–#825 — 2026-07-06

> Instruction: "review handover + memory + /uplevel, put together a prompt then a plan for a
> consultancy-grade deep-dive (CIO/CTO/CPO + reader panel); evaluate bugs, architecture,
> security, tech debt, modernization, how we use Claude, Fable-specific opportunities; red-team;
> move all findings into git issues with outcome ranking + plan of attack + model." Then:
> "Yes run it" → "out of band security but track it · file all 47 · do it now."

## What this session produced
- **Charter + plan:** `docs/reviews/REVIEW_PROMPT_R22_CONSULTANCY.md` (committed 20852ab0).
- **Method:** 14-lens discovery Workflow (`wf_17a5d2ee-85f`, 13 agents, ~1.34M tok) → inline dedup
  vs the 61 open issues + §13b → small adversarial-verify Workflow (`wf_64fab22e-f66`, red-team +
  live re-verify). 54 raw → **47 unique, all verified.** Red team corrected 2 of my own severities
  DOWN (F37 High→Low, F38 out of the Critical chain) — the FP firewall working.
- **Filed: #779–#825** (47 `type:story`, under existing epics; Critical/High→Now, Medium→Next,
  Low→Later; each carries a `model:` label = the plan-of-attack routing).
- **Closure record:** `docs/reviews/REVIEW_2026-07-06_R22.md` (redacted; committed c2ac8e90).
- **§13b** in `deploy/generate_review_bundle.py` now lists the R22 issues + corrects the stale R17
  WAF resolution → R23 can't re-flag.

## ⚠️ CRITICAL — LIVE security exposure, handled out-of-band (Matthew's action)
Public repo + open MCP `/token` = **unauthenticated read/write of ALL private health data**
(get_cgm/labs/genome + memory write/delete). Red-team confirmed the full chain. **Reproduction
detail is deliberately NOT in the repo** (it's public) — it's in private operator memory
`security-r22-mcp-token-exposure`. Public tracking = **#779** (harden /token+/authorize) + **#780**
(rotate + stop committing the Function URL), both terse/no-recipe. Fixing #779 closes the breach
even if the URL stays known; #780 is the rotation half. **Remediate before any public disclosure.**

## Top non-security themes (all filed)
- **Layer-drift disease** #781 (3 distribution channels; full-tree asset shadows the pinned layer)
  + I2 CI check mis-specified #792 + `personal_baselines` still missing from build_layer.sh #782 (5-min).
- **Content honesty** #786 (recap frozen 3wks, narrated "now") / #787 (coaches self-contradict on
  vitals under a "no invented numbers" banner) — highest reader-trust risk.
- **Claude-usage** #784 (Bash(*) leaves deploy boundary unenforced) / #785 (no hooks → main reds
  weekly) / #796 (no .claude/agents). Compounding leverage — do early.
- **Cost** #790 — June actually breached the $75 ceiling ($79.80); Haiku now the top AI line #808.

## Notes / caveats
- The pre-commit hook DID run `sync_doc_metadata` this session (printed Alarms:110 vs live 122 —
  re-confirms DOC-01 #795). So CI-02 #818 ("hook doesn't run sync_doc_metadata") may be a partial
  FP — verify before working it.
- `docs/reviews/REVIEW_BUNDLE_2026-07-06.md` left untracked (regenerable, 317KB).
- No deploys, no feature-code changes this session (read-only engagement + issue filing + docs).
- main's only red is still the PRE-EXISTING freshness-checker v116 drift (Operational hold), now
  captured properly as R22-CI-01 #792 / ARCH-01 #781 root cause. `cdk deploy LifePlatformOperational`
  still greens it — Matthew's call (unchanged from R21 handover).

## Recommended plan of attack
1. Security #779/#780 out-of-band NOW.
2. Green main + kill drift class: #782 (5-min) → #792 → #781 (L) + #791.
3. Honesty: #786/#787/#802 + #783.
4. Claude-usage hardening: #784/#785/#796.
5. Cost before readers: #790/#808/#810.
6. UX returnability: #788/#789 + jargon/SSR cluster.
Model split per issue label: sonnet=mechanical · opus=front-end/refactor · fable=security/arch/honesty/tooling.
