"""The Mind Pillar (Reading) data layer — Phase A.

A new source-of-truth domain (reading) on the single `life-platform` table.
This package holds ONLY the data layer (entities, key/GSI discipline, the public
projection chokepoint, LLM enrichment, the cover pipeline). The recommender,
MCP tools, and site/UI are later phases (B–E) per
`docs/specs/CLAUDE_CODE_PROMPT_READING_MIND_v1.md`.

Canon: `docs/specs/SPEC_READING_MIND_2026-06-29.md` (§1 entities, §2 access patterns,
§3 GSIs, §8 covers, §10 public/private). All reading records are taxonomy class
CROSS_PHASE — durable identity data, never wiped or phase-filtered on an
experiment reset (registered in `phase_taxonomy.py`).
"""
