# HANDOVER — HAE webhook edge into IaC: the #500 deploy, finally landed — 2026-07-05

> **⚠️ A PARALLEL WORKSTREAM was live during this session** (concurrent session merging
> intelligence/site work — #673, #675 and more appeared on `main` mid-session). To avoid a
> stomp on shared files, this session deliberately **did NOT touch** the CLAUDE.md status
> block or `HANDOVER_LATEST.md` — this standalone file is the record. The other session owns
> the next wrap of those two files.

Session opened as "read session + handover + memory." Matthew then asked for an ELI5 of the
one item session 17 left pending — the `LifePlatformIngestion`/HAE-webhook deploy — and
chose to proceed. **The deploy is now done, live, and verified.**

---

## What shipped (PR #671, merged + deployed + verified)

**#500 — HAE webhook edge codified into CDK — deployed.** Session 17 wrote the CDK constructs
(`apigwv2.HttpApi` + route + `CfnStage`) for the Health Auto Export webhook edge but left the
stack **undeployed** because a first-time codification of the hand-created API Gateway
(`a76xwxt2wa`) looked like it would replace the live URL and break ingestion. It did create a
new API — but the deploy turned out **zero-gap** (see below).

Two CDK bugs had to be fixed first — both **synth-clean but deploy-fails** (the dangerous
class):

1. **Route-settings casing.** Values inside the `CfnStage.route_settings` **map** are passed
   through by CDK untransformed (unlike the typed `default_route_settings`, which CDK converts
   to PascalCase). A `CfnStage.RouteSettingsProperty` used as a map value emitted camelCase
   keys (`throttlingBurstLimit`) → CloudFormation rejected it (`Unrecognized field ... 5 known
   properties: ThrottlingBurstLimit, ...`). **Fix:** raw dict with PascalCase keys for the map
   value.
2. **Stage/route ordering.** The stage's per-route settings (`POST /ingest`) are validated
   against routes that already exist, but CFN created the stage first → `Unable to find Route
   by key POST /ingest` (404). **Fix:** capture the routes from `add_routes(...)` and
   `stage.node.add_dependency(route)`.

Both failed attempts **rolled back cleanly** — the live edge was never touched, because the
old console API + its out-of-band Lambda permission were never stack-managed.

## Live state (verified)

- **New CDK-managed HTTP API: `p6clybdkkc`** →
  `https://p6clybdkkc.execute-api.us-west-2.amazonaws.com/ingest`
- Deploy is live; new API verified routing to the Lambda (no-token `POST /ingest` →
  the Lambda's own `401 {"error":"Unauthorized"}`).
- Matthew repointed the HAE app + forced a feed → **5 clean 200 ingests** in the Lambda logs
  (`webhook_complete`, `matched_metrics` > 0, zero errors), and the new API's CloudWatch Count
  confirmed it received the traffic.
- **Zero ingestion gap:** the old console API `a76xwxt2wa` + its `ApiGatewayInvoke` permission
  survived the deploy untouched, so the old URL kept working as a live fallback throughout.

## Outstanding

- **Delete the orphaned old API `a76xwxt2wa` + its broad `a76xwxt2wa/*/*` invoke permission**
  — the final cleanup that actually banks the "less debt" value (two edges → one, fully in
  IaC). **Do this ONLY after confirming the old API goes silent** — at wrap time the
  CloudWatch window still showed a few old-API hits (2 were this session's own `curl` verify
  tests; the rest need confirming as not-a-straggler-automation). Matthew was asked to
  double-check every HAE automation points at `p6clybdkkc`. If the old API is silent for a
  clean window, delete it.

## Value framing (asked directly, answered honestly)

This is **infrastructure hygiene / recoverability, not a feature** — no new data, nothing
faster. The real upside: the health-data front door (API GW, route, throttle, access logging)
now lives in code instead of only as hand-clicked console state, so it's rebuildable in one
`cdk deploy` and no longer carries the hardcoded-API-ID drift trap. Closes audit finding #500.
Net tech-debt only drops **after** the old-API deletion above.

## Gotcha saved to memory

`reference_cdk_apigwv2_stage_route_settings.md` — the two synth-clean/deploy-fails CDK quirks
above, with the "verify at synth" check (PascalCase in `RouteSettings`, stage `DependsOn` the
route).
