# config/

Runtime configuration catalogs the Lambdas load at execution time. **Kept, load-bearing:**
holds DynamoDB schemas, `user_goals.json` (the genesis/baseline source read by the compute
pipeline), the board/coach definitions, and feature configs (`character_sheet.json`,
`experiment_library.json`, `action_detection_rules.json`, …). Not generated — these are the
authored source of truth for engine behavior. See `docs/REPO_STRUCTURE.md`.
