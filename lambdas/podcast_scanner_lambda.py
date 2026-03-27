"""
podcast_scanner_lambda.py — Podcast Intelligence Phase 2
Triggered weekly by EventBridge. Scans configured podcasts for new episodes,
extracts actionable health interventions using Claude Haiku, and stores
candidates as experiment/challenge entries in DynamoDB.

Config: s3://matthew-life-platform/config/podcast_watchlist.json
Output: DynamoDB life-platform table, PK=PODCAST#<podcast_id>, SK=EP#<episode_id>
        Also writes to experiment_candidates partition for review.

Cost estimate: ~$0.40/month (7 podcasts × 4 episodes × ~2K tokens Haiku)
"""
import json
import os
import logging
import hashlib
from datetime import datetime, timezone, timedelta

import boto3
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")
BUCKET = os.environ.get("BUCKET_NAME", "matthew-life-platform")
CONFIG_KEY = "config/podcast_watchlist.json"

# YouTube Data API (no API key needed for RSS — use channel RSS feeds)
YT_RSS_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE)
s3 = boto3.client("s3", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def lambda_handler(event, context):
    """Main entry point — triggered by EventBridge schedule."""
    logger.info("Podcast scanner starting")

    # Load watchlist config
    config = load_config()
    if not config:
        return {"status": "error", "message": "Could not load podcast_watchlist.json"}

    podcasts = [p for p in config.get("podcasts", []) if p.get("active", True)]
    extraction_prompt = config.get("extraction_prompt", "")
    model_id = config.get("haiku_model", "anthropic.claude-haiku-4-5-20251001-v1:0")
    max_tokens = config.get("max_tokens_per_extraction", 2000)

    results = {
        "scanned": 0,
        "new_episodes": 0,
        "interventions_extracted": 0,
        "errors": [],
    }

    for podcast in podcasts:
        try:
            process_podcast(podcast, extraction_prompt, model_id, max_tokens, results)
        except Exception as e:
            logger.error(f"Error processing {podcast['id']}: {e}")
            results["errors"].append({"podcast": podcast["id"], "error": str(e)})

    logger.info(f"Scan complete: {json.dumps(results)}")
    return {"status": "ok", "results": results}


def load_config():
    """Load podcast_watchlist.json from S3."""
    try:
        resp = s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return None


def process_podcast(podcast, extraction_prompt, model_id, max_tokens, results):
    """Check a single podcast for new episodes and extract interventions."""
    podcast_id = podcast["id"]
    channel_id = podcast.get("youtube_channel_id")
    if not channel_id:
        logger.warning(f"No youtube_channel_id for {podcast_id}, skipping")
        return

    results["scanned"] += 1

    # Fetch recent episodes from YouTube RSS
    episodes = fetch_youtube_rss(channel_id)
    if not episodes:
        logger.info(f"No episodes found for {podcast_id}")
        return

    # Check which episodes we've already processed
    for ep in episodes[:3]:  # Process max 3 most recent per scan
        ep_id = ep["id"]
        if episode_already_processed(podcast_id, ep_id):
            continue

        logger.info(f"New episode: {podcast_id}/{ep_id} — {ep['title']}")
        results["new_episodes"] += 1

        # Get transcript (YouTube auto-captions via timedtext API)
        transcript = fetch_transcript(ep["video_id"])
        if not transcript:
            logger.warning(f"No transcript for {ep['title']}")
            # Still record the episode so we don't retry
            store_episode(podcast_id, ep, [], "no_transcript")
            continue

        # Extract interventions using Claude Haiku
        interventions = extract_interventions(
            transcript, podcast, ep, extraction_prompt, model_id, max_tokens
        )
        results["interventions_extracted"] += len(interventions)

        # Store episode + interventions
        store_episode(podcast_id, ep, interventions, "processed")

        # Write intervention candidates for review
        for intervention in interventions:
            store_intervention_candidate(podcast_id, ep, intervention)


def fetch_youtube_rss(channel_id):
    """Fetch recent videos from a YouTube channel RSS feed."""
    url = YT_RSS_TEMPLATE.format(channel_id=channel_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8")
    except Exception as e:
        logger.error(f"RSS fetch failed for {channel_id}: {e}")
        return []

    # Simple XML parsing (avoid lxml dependency)
    episodes = []
    import re

    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
    for entry in entries[:5]:
        video_id_match = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
        title_match = re.search(r"<title>(.*?)</title>", entry)
        published_match = re.search(r"<published>(.*?)</published>", entry)

        if video_id_match and title_match:
            video_id = video_id_match.group(1)
            episodes.append({
                "id": hashlib.sha256(video_id.encode()).hexdigest()[:16],
                "video_id": video_id,
                "title": title_match.group(1),
                "published": published_match.group(1) if published_match else "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })

    # Filter to last 14 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    filtered = []
    for ep in episodes:
        if ep["published"]:
            try:
                pub_date = datetime.fromisoformat(ep["published"].replace("Z", "+00:00"))
                if pub_date >= cutoff:
                    filtered.append(ep)
            except ValueError:
                filtered.append(ep)  # Include if date parsing fails
        else:
            filtered.append(ep)

    return filtered


def fetch_transcript(video_id):
    """Attempt to fetch YouTube auto-generated captions."""
    # YouTube timedtext API — works for auto-generated captions
    # This is a simplified approach; production would use youtube-transcript-api
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "life-platform/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        # Extract captions URL from page source
        import re

        caption_match = re.search(r'"captions":.*?"captionTracks":\[(.*?)\]', html)
        if not caption_match:
            return None

        # Find English auto-generated track
        tracks_json = "[" + caption_match.group(1) + "]"
        tracks = json.loads(tracks_json)

        caption_url = None
        for track in tracks:
            if track.get("languageCode", "").startswith("en"):
                caption_url = track.get("baseUrl")
                break

        if not caption_url:
            return None

        # Fetch the actual transcript
        cap_req = urllib.request.Request(
            caption_url + "&fmt=json3",
            headers={"User-Agent": "life-platform/1.0"},
        )
        with urllib.request.urlopen(cap_req, timeout=15) as cap_resp:
            cap_data = json.loads(cap_resp.read().decode("utf-8"))

        # Extract text from JSON3 format
        events = cap_data.get("events", [])
        text_parts = []
        for event in events:
            segs = event.get("segs", [])
            for seg in segs:
                t = seg.get("utf8", "").strip()
                if t and t != "\n":
                    text_parts.append(t)

        transcript = " ".join(text_parts)

        # Truncate to ~8000 words to stay within Haiku context
        words = transcript.split()
        if len(words) > 8000:
            transcript = " ".join(words[:8000])

        return transcript if len(transcript) > 200 else None

    except Exception as e:
        logger.warning(f"Transcript fetch failed for {video_id}: {e}")
        return None


def extract_interventions(transcript, podcast, episode, prompt, model_id, max_tokens):
    """Use Claude Haiku to extract actionable health interventions from transcript."""
    system_prompt = prompt + (
        f"\n\nPodcast: {podcast['name']} by {podcast['host']}"
        f"\nEpisode: {episode['title']}"
        f"\nDomains to focus on: {', '.join(podcast.get('domains', []))}"
        f"\nPreferred type: {podcast.get('type_bias', 'both')}"
    )

    try:
        response = bedrock.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": f"Here is the transcript:\n\n{transcript}",
                    }
                ],
            }),
        )

        result = json.loads(response["body"].read().decode("utf-8"))
        text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        # Parse JSON array from response
        text = text.strip()
        if text.startswith("["):
            interventions = json.loads(text)
        else:
            # Try to extract JSON from markdown code block
            import re
            json_match = re.search(r"\[.*\]", text, re.DOTALL)
            if json_match:
                interventions = json.loads(json_match.group(0))
            else:
                logger.warning(f"Could not parse interventions from Haiku response")
                return []

        # Validate structure
        valid = []
        for item in interventions:
            if isinstance(item, dict) and "name" in item:
                valid.append(item)

        logger.info(f"Extracted {len(valid)} interventions from {episode['title']}")
        return valid[:10]  # Cap at 10 per episode

    except Exception as e:
        logger.error(f"Haiku extraction failed: {e}")
        return []


def episode_already_processed(podcast_id, ep_id):
    """Check if we've already processed this episode."""
    try:
        resp = table.get_item(
            Key={"PK": f"PODCAST#{podcast_id}", "SK": f"EP#{ep_id}"},
            ProjectionExpression="PK",
        )
        return "Item" in resp
    except Exception:
        return False


def store_episode(podcast_id, episode, interventions, status):
    """Store episode record in DynamoDB."""
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(
        Item={
            "PK": f"PODCAST#{podcast_id}",
            "SK": f"EP#{episode['id']}",
            "video_id": episode["video_id"],
            "title": episode["title"],
            "published": episode.get("published", ""),
            "url": episode["url"],
            "status": status,
            "intervention_count": len(interventions),
            "scanned_at": now,
            "TTL": int((datetime.now(timezone.utc) + timedelta(days=180)).timestamp()),
        }
    )


def store_intervention_candidate(podcast_id, episode, intervention):
    """Store an intervention candidate for Matthew's review."""
    now = datetime.now(timezone.utc)
    item_id = hashlib.sha256(
        f"{podcast_id}:{episode['id']}:{intervention.get('name', '')}".encode()
    ).hexdigest()[:16]

    table.put_item(
        Item={
            "PK": "PODCAST_CANDIDATE",
            "SK": f"{now.strftime('%Y-%m-%d')}#{item_id}",
            "source_podcast": podcast_id,
            "source_episode": episode["title"],
            "source_url": episode["url"],
            "name": intervention.get("name", ""),
            "description": intervention.get("description", ""),
            "protocol": intervention.get("protocol", ""),
            "duration_days": intervention.get("duration_days", 14),
            "difficulty": intervention.get("difficulty", "moderate"),
            "evidence_tier": intervention.get("evidence_tier", "emerging"),
            "evidence_citation": intervention.get("evidence_citation", ""),
            "speaker_quote": intervention.get("speaker_quote", ""),
            "type": intervention.get("type", "experiment"),
            "domains": intervention.get("domains", []),
            "status": "pending_review",
            "created_at": now.isoformat(),
            "TTL": int((now + timedelta(days=90)).timestamp()),
        }
    )
