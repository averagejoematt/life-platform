# Full-cast portrait batch — 2026-07-04 (#616) — APPROVED round 1, promoted

Seven hand-authored recipes for the remaining public-surface coaches, per the
approved #587 standard (character illustration, shape language, silhouette litmus).
No AI raster step — hand-authored vectors (ADR-106 §1 preferred path), 3 self-review
render rounds before the gate.

**Gate outcome: Matthew APPROVED the full sheet in-session, 2026-07-04, round 1**
(contact sheet: https://claude.ai/code/artifact/6d473337-c9cf-4b79-8eb6-300878a1340e).
All 7 recipes promoted to `config/portraits/<persona_id>.json` with `_meta.sign_off`;
this directory keeps the batch record (briefs live in each recipe's `_meta.prompt`).

## The batch — geometric bases + signature features (all bases previously unclaimed)

| persona | base | signature (silhouette-carried) | accent element | engine id in `aliases` |
|---|---|---|---|---|
| marcus_webb | square | the full chestnut beard (only beard) + flat crop | henley neckband | nutrition_coach |
| nathan_reeves | pear | receding M-hairline, grey swept-back mane to jaw length (only grey) | — | mind_coach |
| victor_reyes | long rectangle | jet widow's-peak slick-back + chin-spike goatee | amber shirt under the coat | physical_coach |
| amara_patel | oval | long side braid over the shoulder + round glasses | braid tie + inner top | glucose_coach |
| james_okafor | dome | the only bald head + rectangular glasses | pocket square | labs_coach |
| henning_brandt | tall narrow | wild sandy curl-cloud (tallest silhouette) | the askew knit tie | explorer_coach |
| eli_marsh | broad trapezoid | flat-top crew cut + the only mustache-without-beard | — | (none — canonical id) |

Physical briefs derive from each persona's `config/board_of_directors.json` voice/
personality/relationship blocks (recorded per-recipe in `_meta.prompt`).

## Recorded decisions for the rest of the enumerated cast (issue #616 acceptance)

- **Dr. Kai Nakamura (`the_integrator`/`andrew_huberman`)** — DEFERRED: renders by
  name only (tensions band, weekly priority); no head call site exists to put a
  portrait in. Commission when the dispute/tensions UI gains heads.
- **The Chair (`the_chair`)** — SIGIL-ONLY per runbook §5: a `meta_role` whose persona
  document establishes a role, not a person; the drawing follows the character.
- **Dr. Vivek Murthy (`vivek_murthy`)** — NO PORTRAIT: the one persona carrying a real
  person's name. Any likeness fails the ADR-106 reverse-image rule; a deliberate
  non-likeness under his real name is incoherent. Email/prose surfaces only today.
  If he ever needs a web head: rename the persona first (Matthew's call).
- **Margaret Calloway / Coach Maya Rodriguez** — DEFERRED: email/backend surfaces only,
  no public web head renders them.
- **Dr. Iris Tanaka (`iris_tanaka_interim`)** — SKIPPED: interim seat with a documented
  sunset trigger; commissioning a retirement candidate is waste.
- **Dr. Cora Vance (`cora_vance`)** — DEFERRED: `active: false`, reading surface not
  yet wired to a live feature. Commission when the Reading pillar surfaces her.
