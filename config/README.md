# config/

Runtime configuration catalogs the Lambdas load at execution time. **Kept, load-bearing:**
holds DynamoDB schemas, `user_goals.json` (the genesis/baseline source read by the compute
pipeline), the board/coach definitions, and feature configs (`character_sheet.json`,
`experiment_library.json`, `action_detection_rules.json`, …). Not generated — these are the
authored source of truth for engine behavior. See `docs/REPO_STRUCTURE.md`.

| File | Owner | What it is |
|---|---|---|
| `exercise_library.json` | repo-generated (#5769) | The owner's exercise library — every Hevy movement he has logged plus expansion candidates, with attributes, verified-citation hypertrophy tiers, gates, `home_gym` availability and ranked fallbacks. `status: proposed`: only the #5773 selection engine reads it, in SHADOW (recorded on each draft, the #5075 pools serve) until the owner approves it through `scripts/approve_exercise_library.py`. Built by `deploy/build_exercise_library.py`; the N=1 half is the owner-private S3 overlay `config/coaching/exercise_library.private.json`. Doc: `docs/coaching/EXERCISE_LIBRARY.md`. |
| `training_charter.json` | hand-owned (#5068, ADR-164) | The training charter: the one source of every training target (split, step floor/target, cardio menu, rotation cadence, effort ceilings, gated movements, the concession ledger). Versioned with a `change_log`; any change needs an owner ruling. Read through `lambdas/training/training_charter.py`; published surfaces read `public_view()` only. |
| `training_charter.private.example.json` | hand-owned template (#5087) | Null-placeholder SHAPE of the owner-only half (`target_picture`, `appearance_brief`). The real object is never committed: env `TRAINING_CHARTER_PRIVATE_JSON` → gitignored `training_charter.private.local.json` → owner-private S3 `config/coaching/training_charter.private.json`. |
