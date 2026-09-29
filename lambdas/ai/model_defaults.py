"""model_defaults.py — the ONE narrative-tier (Sonnet) default model name (#4275, box 4).

No Lambda sets `AI_MODEL` or `AI_MODEL_SONNET` (read live, 2026-09-29: 111 functions in
us-west-2, the only model env var set anywhere is `AI_MODEL_HAIKU` on 8), so the literal each
Sonnet caller passed as its `os.environ.get(...)` default WAS the production model — and
there were ten of them. Every one now imports this constant; `tests/test_bedrock_client.py`
holds that no other module under `lambdas/` or `mcp/` carries a Sonnet model-name literal
outside `ai/bedrock_client.py`'s resolution map and this file.

Moving the narrative tier to another model is ONE edit here (or an `AI_MODEL` env var) — and
it is #4278 (gate:owner), not this constant's job. The value is unchanged by #4275.

Leaf module: no imports, so `common/` and `mcp/` can depend on it without a cycle.
"""

NARRATIVE_MODEL = "claude-sonnet-4-6"
