# Implementation Brief: Arena v2 + Lab v2 — Remaining Work

> **Session**: March 26, 2026 | **Platform version**: ~v3.9.4
> **Context**: Product Board session redesigned `/challenges/` and `/experiments/` pages. Three lifecycle gaps fixed. Two new features scoped: challenge voting and podcast intelligence pipeline.
> **Audience**: Claude Code or next Claude session — all context needed to execute without re-explanation.

---

## STATUS: What's Already Done (This Session)

### Deployed ✅
| Item | Details |
|------|---------|
| `/challenges/` Arena v2 redesign | Visual tile wall, icon-forward, 6 category filters, detail overlay, collapsed methodology |
| `/experiments/` Lab v2 redesign | Tile grid for library, compact mission control, evidence rings, vote buttons, collapsed H/P/D |
| `challenges_catalog.json` | 35 challenges across 6 categories in S3 (`site/config/challenges_catalog.json`) |
| `/api/challenge_catalog` endpoint | New handler + route in `site_api_lambda.py` — serving 200 with 21KB |
| `experiment_library.json` | Copied to `site/config/experiment_library.json` (was only at `config/`) |

### Coded But NOT Yet Deployed ⏳
These changes are in the local filesystem but need `bash deploy/deploy_lifecycle_gaps.sh`:

| File | Change | Gap # |
|------|--------|-------|
| `mcp/tools_challenges.py` | `create_challenge` accepts `catalog_id` param; `list_challenges` computes overdue detection (days_since_activation, overdue bool, days_overdue); summary includes overdue count | 1 + 2 |
| `mcp/registry.py` | Added `catalog_id` to `create_challenge` schema | 2 |
| `lambdas/site_api_lambda.py` | `handle_achievements()` queries challenges partition, counts completed + perfect challenges, adds 5 new badges (Arena Debut/Regular/Veteran/Legend/Flawless) + challenge stats in summary | 3 |
| `site/achievements/index.html` | Added `challenge` category (amber color, 🏆 icons), 5 badge icon mappings | 3 |

**Deploy command** (run MCP registry test first):
```bash
cd ~/Documents/Claude/life-platform
python3 -m pytest tests/test_mcp_registry.py -v
bash deploy/deploy_lifecycle_gaps.sh
```

---

## TASK 1: Challenge Voting (Frontend + Backend)

### What
Add "🙋 I'd try this" button to challenge tiles + email capture for notification when challenge activates. Reuses the experiment vote/follow infrastructure already in `site_api_lambda.py`.

### Backend Changes

**1a. Add vote endpoint for challenges** (`lambdas/site_api_lambda.py`)

Create `_handle_challenge_vote(event)` — copy the pattern from `_handle_experiment_vote()` (line ~2752) with these changes:
- Partition key: `VOTES#challenges` (not `VOTES#experiment_library`)
- Rate limit key: `VOTES#rate_limit` / `IP#{ip_hash}#CH#{catalog_id}` (1 vote per IP per challenge per 24h via DDB TTL)
- Body: `{"catalog_id": "cold-shower-finish"}`

```python
def _handle_challenge_vote(event: dict) -> dict:
    """POST /api/challenge_vote — Rate-limited vote for challenge catalog entries."""
    # Same pattern as _handle_experiment_vote but with VOTES#challenges partition
    source_ip = (event.get("requestContext", {}).get("http", {}).get("sourceIp") or "unknown")
    body = json.loads(event.get("body") or "{}")
    catalog_id = (body.get("catalog_id") or "").strip().lower()
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id required")
    
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    
    # Rate limit: 1 per IP per challenge per 24h
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#CH#{catalog_id}"
    try:
        table.put_item(
            Item={"pk": rate_pk, "sk": rate_sk, "voted_at": now_epoch, "ttl": now_epoch + 86400},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {"statusCode": 429, "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                    "body": json.dumps({"error": "Already voted for this challenge in the last 24 hours"})}
        return _error(500, "Vote rate limit check failed")
    
    # Increment vote count
    vote_pk = "VOTES#challenges"
    vote_sk = f"CH#{catalog_id}"
    result = table.update_item(
        Key={"pk": vote_pk, "sk": vote_sk},
        UpdateExpression="ADD vote_count :one SET catalog_id = :cid, last_voted = :ts",
        ExpressionAttributeValues={":one": 1, ":cid": catalog_id, ":ts": now_epoch},
        ReturnValues="UPDATED_NEW",
    )
    new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    return {"statusCode": 200, "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"catalog_id": catalog_id, "new_count": new_count})}
```

**1b. Add follow endpoint for challenges** (`lambdas/site_api_lambda.py`)

Create `_handle_challenge_follow(event)` — copy from `_handle_experiment_follow()` (line ~2800) with:
- Partition key: `CHALLENGE_FOLLOWS` (not `EXPERIMENT_FOLLOWS`)
- Body: `{"email": "user@example.com", "catalog_id": "cold-shower-finish"}`
- Same rate limit pattern (10 follows per IP per hour)

**1c. Wire vote counts into catalog response**

Modify `handle_challenge_catalog()` to merge vote counts from DDB, same as `handle_experiment_library()` does:

```python
def handle_challenge_catalog() -> dict:
    global _challenge_catalog_cache
    if _challenge_catalog_cache is None:
        _challenge_catalog_cache = _load_s3_json(
            "site/config/challenges_catalog.json", "challenge_catalog"
        )
    
    # Merge vote counts from DynamoDB
    vote_counts = {}
    try:
        vote_pk = "VOTES#challenges"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            cid = item.get("sk", "").replace("CH#", "")
            vote_counts[cid] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[challenge_catalog] Vote query failed (non-fatal): {e}")
    
    # Inject votes into each challenge
    result = dict(_challenge_catalog_cache)
    challenges = list(result.get("challenges", []))
    total_votes = 0
    for ch in challenges:
        ch["votes"] = vote_counts.get(ch.get("id", ""), 0)
        total_votes += ch["votes"]
    result["challenges"] = challenges
    result["total_votes"] = total_votes
    
    return _ok(result, cache_seconds=900)  # 15 min cache (was 1hr, reduce for vote freshness)
```

**1d. Add routes** (in the `lambda_handler` POST section and GET_ROUTES dict):

```python
# In GET_ROUTES:
# Change handle_challenge_catalog cache from 3600 to 900 (already handled by code above)

# In lambda_handler POST section (after challenge_checkin):
if path == "/api/challenge_vote":
    if method != "POST":
        return _error(405, "POST required")
    return _handle_challenge_vote(event)

if path == "/api/challenge_follow":
    if method != "POST":
        return _error(405, "POST required")
    return _handle_challenge_follow(event)
```

### Frontend Changes

**1e. Update `/challenges/index.html` tile grid**

In the `renderTiles()` function, add vote button and "I'd try this" button to each tile's bottom row:

```javascript
// Replace the tile__footer section in renderTiles()
'<div class="tile__footer">' +
  '<span class="tile__duration">' + durLabel + '</span>' +
  '<div class="tile__difficulty">' + diffDots(ch.difficulty || 2) + '</div>' +
  '<button class="vote-btn' + (isVoted ? ' voted' : '') + '" ' +
    'onclick="event.stopPropagation();handleChallengeVote(this,\'' + ch.id + '\')">' +
    '🙋 ' + (ch.votes || 0) +
  '</button>' +
'</div>'
```

Add vote handler (same pattern as experiments page):

```javascript
var votedChallenges = {};
try { votedChallenges = JSON.parse(localStorage.getItem('amj_ch_votes') || '{}'); } catch(e) {}

window.handleChallengeVote = function(btn, catalogId) {
  if (votedChallenges[catalogId]) return;
  btn.classList.add('voted');
  var count = parseInt(btn.textContent.replace(/[^0-9]/g, '') || '0') + 1;
  btn.innerHTML = '🙋 ' + count;
  votedChallenges[catalogId] = true;
  try { localStorage.setItem('amj_ch_votes', JSON.stringify(votedChallenges)); } catch(e) {}
  fetch(API + '/challenge_vote', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({catalog_id: catalogId})
  }).catch(function() {});
};
```

Add "Follow" button to the detail overlay for email capture:

```javascript
// In showDetail(), add to bodyHtml:
bodyHtml += '<div class="detail-field" style="text-align:center;padding-top:var(--space-4)">' +
  '<button class="btn-ck" onclick="handleChallengeFollow(\'' + ch.id + '\')" id="follow-btn-' + ch.id + '">' +
    '🔔 Notify me when this starts' +
  '</button></div>';
```

```javascript
window.handleChallengeFollow = function(catalogId) {
  var btn = document.getElementById('follow-btn-' + catalogId);
  if (btn.classList.contains('followed')) return;
  var email = prompt('Get notified when this challenge activates. Enter your email:');
  if (!email || email.indexOf('@') < 0) return;
  btn.classList.add('followed');
  btn.textContent = '✓ Following';
  fetch(API + '/challenge_follow', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({catalog_id: catalogId, email: email})
  }).catch(function() {});
};
```

### CSS additions needed:
```css
.vote-btn.voted { border-color: var(--ar-dim); color: var(--ar); background: var(--ar-bg-s); }
.btn-ck.followed { background: var(--ar-bg); color: var(--ar); border-color: var(--ar-dim); cursor: default; }
```

### Deploy for Task 1:
```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude ".DS_Store"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/challenges/*" "/api/challenge_catalog" "/api/challenge_vote" "/api/challenge_follow" \
  --region us-east-1
```

---

## TASK 2: Podcast Intelligence Pipeline

### Phase 1: Schema Extension + Conversational Flow (No new code needed)

**2a. Extend `challenges_catalog.json` schema**

Add these optional fields to the challenge schema:

```json
{
  "id": "sauna-2x-week",
  "name": "Sauna Protocol",
  "icon": "🧖",
  "one_liner": "Sauna 2x per week for 6 weeks",
  "category": "discipline",
  "duration_days": 42,
  "difficulty": 3,
  "evidence_tier": "strong",
  "evidence_summary": "4-7 sauna sessions/week associated with 40% reduction in all-cause mortality",
  "evidence_citation": "Laukkanen et al., JAMA Internal Medicine, 2015",
  "board_recommender": "Dr. Rhonda Patrick",
  "board_quote": "The cardiovascular benefits of sauna rival those of moderate exercise.",
  "protocol": "20 minutes at 174°F (79°C), 2x per week minimum. Hydrate before and after.",
  "status": "backlog",
  
  "source_type": "podcast",
  "source_podcast": "FoundMyFitness",
  "source_episode": "Sauna Use: Cardiovascular & Longevity Benefits",
  "source_url": "https://www.youtube.com/watch?v=example",
  "source_speaker": "Dr. Rhonda Patrick",
  "source_timestamp": "12:35"
}
```

Same fields apply to `experiment_library.json` entries:

```json
{
  "id": "sauna-cardiovascular",
  "name": "Sauna Cardiovascular Protocol",
  "pillar": "movement",
  "evidence_tier": "strong",
  "evidence_citation": "Laukkanen et al., JAMA Internal Medicine, 2015",
  
  "source_type": "podcast",
  "source_podcast": "FoundMyFitness",
  "source_episode": "Sauna Use: Cardiovascular & Longevity Benefits",
  "source_url": "https://www.youtube.com/watch?v=example",
  "source_speaker": "Dr. Rhonda Patrick",
  "source_timestamp": "12:35",
  "discovered_via": "FoundMyFitness Episode 142"
}
```

**2b. Update detail overlay to show podcast source**

In both `/challenges/index.html` and `/experiments/index.html`, add to the detail overlay body rendering:

```javascript
if (ch.source_type === 'podcast') {
  bodyHtml += '<div class="detail-field">' +
    '<div class="detail-field__label">// Discovered Via Podcast</div>' +
    '<div class="detail-field__value">' +
      '🎙️ <strong>' + ch.source_podcast + '</strong>' +
      (ch.source_episode ? ' — ' + ch.source_episode : '') +
      (ch.source_speaker ? '<br>Speaker: ' + ch.source_speaker : '') +
      (ch.source_timestamp ? ' (at ' + ch.source_timestamp + ')' : '') +
      (ch.source_url ? '<br><a href="' + ch.source_url + '" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;border-bottom:1px solid var(--accent-dim)">Listen to episode →</a>' : '') +
    '</div></div>';
}
```

**2c. Conversational flow (already works — just needs the right prompt)**

When Matthew says: *"Rhonda Patrick just recommended magnesium L-threonate for sleep, FoundMyFitness episode 142, she cited Abbot et al. 2012"*

Claude creates the entry by:
1. Searching the web for the cited study to verify evidence tier
2. Calling the appropriate creation tool with full podcast metadata
3. Uploading the updated catalog to S3

This flow works TODAY with existing MCP tools — no new code needed.

### Phase 2: Automated Podcast Scanner (Future — EventBridge Lambda)

**Architecture:**
```
EventBridge (weekly) → podcast-scanner Lambda → YouTube Transcript API → Haiku extraction → S3 drafts → notification email
```

**2d. Create podcast watchlist config** (`config/podcast_watchlist.json`):

```json
{
  "version": "1.0.0",
  "scan_frequency": "weekly",
  "podcasts": [
    {
      "id": "foundmyfitness",
      "name": "FoundMyFitness",
      "host": "Dr. Rhonda Patrick",
      "youtube_channel_id": "UCWF8SqJVNlx-ctXv4SkUIKg",
      "type_bias": "experiment",
      "domains": ["supplements", "nutrition", "metabolic"],
      "active": true
    },
    {
      "id": "stronger-by-science",
      "name": "Stronger By Science",
      "host": "Dr. Layne Norton & Eric Trexler",
      "youtube_channel_id": "UCMgRFPaxBdSBFaetyOAMgEA",
      "type_bias": "challenge",
      "domains": ["nutrition", "movement"],
      "active": true
    },
    {
      "id": "huberman-lab",
      "name": "Huberman Lab",
      "host": "Dr. Andrew Huberman",
      "youtube_channel_id": "UC2D2CMWXMOVWx7giW1n3LIg",
      "type_bias": "both",
      "domains": ["sleep", "mental", "discipline", "supplements"],
      "active": true
    },
    {
      "id": "the-drive",
      "name": "The Drive",
      "host": "Dr. Peter Attia",
      "youtube_channel_id": "UC8kGsMa0LygSX9nkBcBH1Sg",
      "type_bias": "experiment",
      "domains": ["metabolic", "movement", "nutrition"],
      "active": true
    },
    {
      "id": "zoe-science",
      "name": "ZOE Science & Nutrition",
      "host": "Jonathan Wolf",
      "youtube_channel_id": "UCB5f4Psg1TF9LZpCKkFahag",
      "type_bias": "experiment",
      "domains": ["nutrition", "metabolic"],
      "active": true
    },
    {
      "id": "feel-better-live-more",
      "name": "Feel Better Live More",
      "host": "Dr. Rangan Chatterjee",
      "youtube_channel_id": "UCqYPhGiB9tkShZjXaKswZLQ",
      "type_bias": "challenge",
      "domains": ["social", "mental", "discipline"],
      "active": true
    },
    {
      "id": "the-proof",
      "name": "The Proof",
      "host": "Simon Hill",
      "youtube_channel_id": "UCLSf2GlUO4k5AYnwPhiUoog",
      "type_bias": "experiment",
      "domains": ["nutrition"],
      "active": true
    }
  ],
  "extraction_prompt": "You are an expert health science curator. From this podcast transcript, extract any ACTIONABLE health interventions mentioned. For each intervention, return a JSON array of objects with: name (short), description (1 sentence), protocol (what to do), duration_days (suggested), difficulty (easy/moderate/hard), evidence_tier (strong if multiple RCTs cited, moderate if observational studies, emerging if anecdotal), evidence_citation (if any study was cited by name), speaker_quote (1 key quote under 15 words), type (experiment if measurable biomarker endpoint, challenge if behavioral), domains (array of: sleep, movement, nutrition, supplements, mental, social, discipline, metabolic). Return ONLY the JSON array, no preamble.",
  "haiku_model": "claude-haiku-4-5-20251001",
  "max_tokens_per_extraction": 2000
}
```

**2e. Lambda implementation** (`lambdas/podcast_scanner_lambda.py`):

Dependencies: `youtube-transcript-api` (pip install into Lambda layer)

Flow:
1. Read watchlist from S3
2. For each active podcast, fetch YouTube channel's recent videos (last 7 days)
3. For each new video, fetch transcript via `youtube-transcript-api`
4. Send transcript chunks to Haiku with extraction prompt
5. Classify each extracted intervention as experiment or challenge
6. Write draft entries to `s3://matthew-life-platform/site/config/podcast_drafts.json`
7. Send SES notification to Matthew: "3 new interventions found from this week's podcasts — review and approve"

**Estimated cost**: ~$0.40/month (7 podcasts × 4 episodes × ~$0.01/episode Haiku cost)

**EventBridge rule**: `cron(0 8 ? * SUN *)` — every Sunday at 8 AM PT

**This is a FUTURE task** — not needed for the current sprint. Phase 1 (conversational creation with podcast metadata) works immediately.

---

## TASK 3: Seed Additional Experiments from Product Board Brainstorm

The Product Board brainstormed 10+ new experiments in the session. These should be added to `config/experiment_library.json`. Here are the ones NOT already in the 52-experiment library:

```json
[
  {
    "id": "sauna-2x-week-6wk",
    "name": "Sauna 2x/Week for 6 Weeks",
    "description": "Regular sauna use to test cardiovascular and recovery benefits",
    "pillar": "movement",
    "evidence_tier": "strong",
    "evidence_summary": "4-7 sauna sessions/week associated with 40% reduction in all-cause mortality",
    "evidence_citation": "Laukkanen et al., JAMA Internal Medicine, 2015",
    "suggested_duration_days": 42,
    "difficulty": "moderate",
    "experiment_type": "measurable",
    "hypothesis_template": "Regular sauna use (2x/week, 20 min at 174°F) will improve HRV by >5% and reduce resting heart rate",
    "protocol_template": "20 minutes at 174°F (79°C), 2x per week. Hydrate before and after. No cold plunge after (isolate variable).",
    "metrics_measurable": ["hrv", "resting_heart_rate", "recovery_score", "sleep_quality"],
    "tags": ["heat", "cardiovascular", "recovery"],
    "status": "backlog"
  },
  {
    "id": "cold-plunge-3x-week",
    "name": "Cold Plunge 2 min, 3x/Week",
    "description": "Deliberate cold exposure for dopamine and mood",
    "pillar": "mental",
    "evidence_tier": "strong",
    "evidence_summary": "Cold water immersion increases dopamine 250%, norepinephrine 530%",
    "evidence_citation": "Šrámek et al., 2000; Huberman Lab",
    "suggested_duration_days": 28,
    "difficulty": "hard",
    "experiment_type": "measurable",
    "hypothesis_template": "Cold plunge (2 min, 3x/week) will increase morning HRV and improve subjective mood scores",
    "protocol_template": "2 minutes in cold water (50-59°F), 3x per week. Morning preferred. No warm shower after for 20 min.",
    "metrics_measurable": ["hrv", "mood_score", "energy_score"],
    "tags": ["cold", "dopamine", "mental"],
    "status": "backlog"
  },
  {
    "id": "zone2-150-min-week",
    "name": "Zone 2 Cardio 150+ min/Week",
    "description": "Sustained Zone 2 base building for 8 weeks",
    "pillar": "movement",
    "evidence_tier": "strong",
    "evidence_summary": "Zone 2 training is the highest-evidence longevity modality — VO2max, mitochondrial density, fat oxidation",
    "evidence_citation": "Attia, Outlive; WHO guidelines",
    "suggested_duration_days": 56,
    "difficulty": "moderate",
    "experiment_type": "measurable",
    "hypothesis_template": "150+ min/week Zone 2 for 8 weeks will improve cardiac efficiency (pace-at-HR) by >5%",
    "protocol_template": "Minimum 150 minutes per week in Zone 2 (60-70% max HR). Walking, cycling, or rucking. Track via Garmin/Strava HR.",
    "metrics_measurable": ["zone2_minutes", "cardiac_efficiency", "resting_heart_rate"],
    "tags": ["zone2", "cardio", "longevity"],
    "status": "backlog"
  },
  {
    "id": "morning-sunlight-blue-blockers",
    "name": "Morning Sunlight + Evening Blue Blockers",
    "description": "Full circadian protocol: morning light + evening protection",
    "pillar": "sleep",
    "evidence_tier": "strong",
    "evidence_summary": "Morning light advances circadian phase; evening blue blockers preserve melatonin onset",
    "evidence_citation": "Huberman Lab; Chang et al., PNAS 2015",
    "suggested_duration_days": 21,
    "difficulty": "moderate",
    "experiment_type": "measurable",
    "hypothesis_template": "Combined morning sunlight + evening blue blockers will reduce sleep onset latency and increase deep sleep %",
    "protocol_template": "10+ min outdoor light within 30 min of waking (no sunglasses). Blue-blocking glasses from sunset. Track with Whoop/Eight Sleep.",
    "metrics_measurable": ["sleep_onset_latency", "deep_sleep_pct", "sleep_efficiency"],
    "tags": ["circadian", "light", "sleep"],
    "status": "backlog"
  },
  {
    "id": "trf-12pm-8pm",
    "name": "Time-Restricted Eating (12pm-8pm)",
    "description": "8-hour eating window for metabolic benefits",
    "pillar": "nutrition",
    "evidence_tier": "strong",
    "evidence_summary": "TRF improves insulin sensitivity, reduces inflammation, supports circadian alignment",
    "evidence_citation": "Panda, The Circadian Code; Sutton et al., Cell Metabolism 2018",
    "suggested_duration_days": 28,
    "difficulty": "moderate",
    "experiment_type": "measurable",
    "hypothesis_template": "8-hour eating window (12pm-8pm) will reduce fasting glucose variability and improve time-in-range",
    "protocol_template": "First meal at 12pm, last bite by 8pm. Black coffee/tea/water only before noon. Track via CGM + MacroFactor.",
    "metrics_measurable": ["glucose_variability", "time_in_range", "fasting_glucose"],
    "tags": ["TRF", "fasting", "metabolic"],
    "status": "backlog"
  },
  {
    "id": "eliminate-alcohol-30d",
    "name": "Eliminate Alcohol 30 Days",
    "description": "Complete alcohol elimination to measure sleep and recovery impact",
    "pillar": "discipline",
    "evidence_tier": "strong",
    "evidence_summary": "Even moderate alcohol disrupts REM sleep, suppresses HRV, impairs recovery for 3+ days per drink",
    "evidence_citation": "Attia, Outlive; Huberman Lab; Walker, Why We Sleep",
    "suggested_duration_days": 30,
    "difficulty": "moderate",
    "experiment_type": "measurable",
    "hypothesis_template": "30 days zero alcohol will improve REM % by >10% and HRV by >5ms",
    "protocol_template": "Zero alcohol for 30 days. No exceptions. Track REM %, HRV, recovery score, sleep efficiency via Whoop.",
    "metrics_measurable": ["rem_pct", "hrv", "recovery_score", "sleep_efficiency"],
    "tags": ["alcohol", "sleep", "recovery"],
    "status": "backlog"
  }
]
```

**How to add**: Read current `config/experiment_library.json`, append these to the `experiments` array, upload back to both S3 locations:
```bash
aws s3 cp config/experiment_library.json s3://matthew-life-platform/config/experiment_library.json --region us-west-2
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json --region us-west-2
```

---

## DEPLOY SEQUENCE

Run in this order:

### Step 1: Lifecycle gaps (already coded)
```bash
python3 -m pytest tests/test_mcp_registry.py -v
bash deploy/deploy_lifecycle_gaps.sh
```

### Step 2: Challenge voting (Task 1)
1. Patch `site_api_lambda.py` with vote + follow handlers
2. Add POST routes in `lambda_handler`
3. Update `handle_challenge_catalog()` to merge vote counts
4. Update `/challenges/index.html` with vote buttons + follow overlay
5. Deploy:
```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude ".DS_Store"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/challenges/*" "/api/challenge_catalog" --region us-east-1
```

### Step 3: Podcast schema + new experiments (Task 2a + Task 3)
1. Add podcast fields to `challenges_catalog.json` schema (future entries)
2. Update both page detail overlays to render podcast source
3. Append 6 new experiments to `experiment_library.json`
4. Upload to S3:
```bash
aws s3 cp config/experiment_library.json s3://matthew-life-platform/config/experiment_library.json --region us-west-2
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json --region us-west-2
aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude ".DS_Store"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/experiments/*" "/challenges/*" "/api/experiment_library" --region us-east-1
```

### Step 4: Podcast watchlist config (Task 2d — prep for future Lambda)
```bash
aws s3 cp config/podcast_watchlist.json s3://matthew-life-platform/config/podcast_watchlist.json --region us-west-2
```
This is prep only — the scanner Lambda (Task 2e) is a future sprint.

---

## FILES MODIFIED THIS SESSION

| File | Status | What Changed |
|------|--------|--------------|
| `site/challenges/index.html` | DEPLOYED | Arena v2 redesign — tile wall |
| `site/experiments/index.html` | DEPLOYED | Lab v2 redesign — tile grid |
| `seeds/challenges_catalog.json` | DEPLOYED | 35 challenges, S3 uploaded |
| `lambdas/site_api_lambda.py` | NEEDS DEPLOY | challenge_catalog handler + route + achievements badges |
| `mcp/tools_challenges.py` | NEEDS DEPLOY | catalog_id, overdue detection |
| `mcp/registry.py` | NEEDS DEPLOY | catalog_id in schema |
| `site/achievements/index.html` | NEEDS DEPLOY | challenge category + badge icons + CSS |
| `deploy/deploy_challenges_overhaul.sh` | Created | Arena v2 deploy |
| `deploy/deploy_experiments_v2.sh` | Created | Lab v2 deploy |
| `deploy/deploy_lifecycle_gaps.sh` | Created | 3 gap fixes deploy |

---

## KEY DESIGN DECISIONS (for context)

1. **Challenges = "I'd try this" not "vote"** — Product Board consensus. Social proof framing, not democratic prioritization. Email capture on first interaction.
2. **Evidence tier comes from cited research, not the podcast** — Dr. Lena Johansson's rule. Podcast is the discovery mechanism, not the evidence source.
3. **Phase 1 podcast flow is conversational** — Matthew tells Claude what he heard, Claude creates the entry with metadata. No new code needed.
4. **Phase 2 automated scanner is ~$0.40/month** — YouTube transcripts are free, Haiku extraction is trivial. Weekly EventBridge Lambda. Future sprint.
5. **Retry semantics** — Each challenge attempt gets a unique DDB record (slug + date). Multiple failures then a success all tracked separately. Completed count across ALL records drives badge progression.
