# setup/

One-time OAuth/credential setup scripts per integration (Garmin, Withings, Eight Sleep,
Whoop, calendar sync, CloudTrail, …) — the DR/operator toolkit. **Kept, load-bearing:** run
locally on the operator's machine for token rotation and disaster recovery (e.g.
`setup_whoop_auth.py`, `fix_withings_oauth.py`). Not part of the deployed Lambda bundles, but
essential to keep ingestion authenticated. See `docs/REPO_STRUCTURE.md`.
