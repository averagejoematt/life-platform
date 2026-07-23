# ci/

CI support data (not scripts). **Kept, load-bearing:** `lambda_map.json` is the canonical
source-file → function → stack mapping the deploy tooling and `tests/test_role_policies.py`
consume; `lambda_s3_paths.json` and `deprecated_secrets.txt` are the companion CI manifests.
Changing a Lambda's wiring means editing `lambda_map.json` here. See `docs/REPO_STRUCTURE.md`.
