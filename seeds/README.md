# seeds/

Test/dev bootstrap data generators and kept JSON seeds for DynamoDB state (`seed_*.py`,
`challenges_catalog.json`, `content_filter.json`, …). **Kept, load-bearing:** these seed
catalogs are consumed to bootstrap local/dev state and are referenced by the running system,
not throwaway fixtures. Not a one-shot migration (those go to `patches/`/`backfill/`). See
`docs/REPO_STRUCTURE.md`.
