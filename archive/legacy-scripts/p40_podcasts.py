#!/usr/bin/env python3
"""
P40 Podcast Recommender
Reads your Pocket Casts OPML, fetches recent episodes from all feeds,
and asks Claude to recommend the best ones based on your mood/topic.

Usage:
    python3 p40_podcasts.py
    python3 p40_podcasts.py --topic "MCP and AI agents"
    python3 p40_podcasts.py --topic "leadership and managing up"
    python3 p40_podcasts.py --topic "fitness and recovery"
    python3 p40_podcasts.py --days 14   # look back 14 days instead of 30

Requirements:
    pip3 install anthropic
"""

import os
import sys
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
import time

try:
    import anthropic
except ImportError:
    print("\n❌  Run: pip3 install anthropic --break-system-packages\n")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
OPML_PATH = os.path.expanduser("~/Documents/Claude/PocketCasts.opml")
ENV_PATH  = os.path.expanduser("~/.p40_env")
MODEL     = "claude-sonnet-4-20250514"

DAYS_BACK        = 30    # How far back to look for episodes
MAX_WORKERS      = 20    # Parallel feed fetches
FEED_TIMEOUT     = 8     # Seconds before giving up on a feed
MAX_EPISODES     = 400   # Cap total episodes sent to Claude
TOP_N            = 7     # Number of recommendations to return

# Podcast categories — helps Claude understand your library
CATEGORIES = {
    "AI & Tech": [
        "Hard Fork", "The Vergecast", "Decoder with Nilay Patel", "Practical AI",
        "This Day in AI Podcast", "The AI Daily Brief: Artificial Intelligence News and Analysis",
        "The Anthropic AI Daily Brief", "AI + a16z", "The a16z Show", "Me, Myself, and AI",
        "Software Engineering Daily", "The Changelog: Software Development, Open Source",
        "Accidental Tech Podcast", "Clockwise", "Hanselminutes with Scott Hanselman",
        "The AWS Developers Podcast", "AWS for Software Companies Podcast",
        "Syntax - Tasty Web Development Treats", "MIT Technology Review Narrated",
        "The AI Why with Liam Lawson", "Azeem Azhar's Exponential View",
        "Uncanny Valley | WIRED", "Dev Interrupted", "CoRecursive: Coding Stories",
        "Security Now (Audio)", "Darknet Diaries", "The Cloudcast",
    ],
    "CIO & Enterprise Tech": [
        "CIO Leadership Live", "CIO Talk Network Podcast", "CIO Podcast by Healthcare IT Today",
        "Modern CTO", "Mindful CIO Podcast", "The CIO In The Know Podcast",
        "The Clockwork CIO", "Ask the CIO", "CXOTalk", "Technovation with Peter High",
        "Brown Advisory CIO Perspectives", "Ticket Volume - IT Podcast",
        "The IT Experience Podcast", "Service Management Leadership Podcast",
        "Killer Innovations with Phil McKinney",
    ],
    "ERP & Enterprise Apps": [
        "Digital Stratosphere: Digital Transformation, ERP, HCM, and CRM Implementation Best Practices",
        "Enterprise Apps Unpacked", "The ERP Advisor", "The ABCs of ERP & Beyond",
        "The NetSuite Podcast", "WBSRocks: Scaling Growth with AI, Enterprise Software, and Digital Transformation",
        "Scrum Master Toolbox Podcast: Agile storytelling from the trenches",
    ],
    "Leadership & Career": [
        "The Engineering Leadership Podcast", "HBR IdeaCast", "Manager Tools",
        "The Knowledge Project", "Worklife with Adam Grant", "Secret Leaders",
        "The Diary Of A CEO with Steven Bartlett", "TED Business", "Mission Daily",
        "How to Be a Better Human", "Read to Lead Podcast", "The Tim Ferriss Show",
    ],
    "Public Speaking & Communication": [
        "Think Fast Talk Smart: Communication Techniques", "Fearless Presentations",
        "The Toastmasters Podcast", "The Speaker Lab Podcast", "The Engaging Performer",
        "How To Own The Room", "Social Skills Coaching", "Rock Your Voice Podcast",
        "The Power of Vocal Dynamics Business School",
    ],
    "Health & Fitness": [
        "Huberman Lab", "The Peter Attia Drive", "FoundMyFitness",
        "Optimal Health Daily - Fitness and Nutrition", "Barbell Medicine Podcast",
        "Barbell Shrugged", "Joe DeFranco's Industrial Strength Show",
        "The Revive Stronger Podcast", "The Ready State Podcast",
        "The Running Explained Podcast", "WHOOP Podcast",
        "Feel Better, Live More with Dr Rangan Chatterjee",
        "Ask a Cycling Coach Podcast - Presented by TrainerRoad",
        "The Roadman Cycling Podcast", "TED Health",
    ],
    "Mental Health & Psychology": [
        "10% Happier with Dan Harris", "Hidden Brain", "The Happiness Lab with Dr. Laurie Santos",
        "Shrink For The Shy Guy", "The Overwhelmed Brain", "Speaking of Psychology",
        "The Anxious Achiever", "Mental Illness Happy Hour", "The Anxiety Guy Podcast",
        "Anxiety Slayer™ with Shann and Ananga", "The Anxiety Coaches Podcast",
        "Social Anxiety Solutions - your journey to social confidence!",
        "The Boundaries.me Podcast", "Maintenance Phase", "We Can Do Hard Things",
        "UnF*ck Your Brain: Feminist Self-Help for Everyone",
    ],
    "Business & Finance": [
        "Acquired", "Invest Like the Best with Patrick O'Shaughnessy",
        "The Stacking Benjamins Show", "Money Guy Show", "ChooseFI",
        "Planet Money", "Freakonomics Radio", "No Stupid Questions",
        "Choiceology with Katy Milkman", "WSJ Your Money Briefing",
        "The Rational Reminder Podcast",
    ],
    "History": [
        "Dan Carlin's Hardcore History", "Dan Carlin's Hardcore History: Addendum",
        "The Rest Is History", "American History Hit", "Dan Snow's History Hit",
        "HISTORY This Week", "Stuff You Missed in History Class", "History on Fire",
        "Fall of Civilizations Podcast", "The History of Rome", "You're Dead to Me",
        "Short History Of...", "Presidential",
    ],
    "News & Politics": [
        "The Daily", "Up First from NPR", "Today, Explained", "Plain English with Derek Thompson",
        "The Rest Is Politics", "The Rest Is Politics: US", "Left, Right & Center",
        "Pod Save America", "NPR Politics Podcast", "Newshour", "The Ezra Klein Show",
    ],
    "Football": [
        "Sky Sports Premier League Podcast", "Football Weekly", "The Gary Neville Podcast",
        "The Anfield Wrap", "The Athletic FC Podcast", "The FM Show - A Football Manager Podcast",
        "Football Manager Therapy", "606", "The Overlap",
    ],
    "Sleep": [
        "Nothing much happens: bedtime stories to help you sleep", "Sleep With Me",
        "Bedtime Stories to Bore You Asleep from Sleep With Me", "Tracks To Relax Sleep Meditations",
        "Sleep and Study Soundscapes", "SW Podcast – Sleep Whispers", "Bedtime Stories",
        "Podcast to Fall Asleep to",
    ],
    "General Interest": [
        "Stuff You Should Know", "Stuff To Blow Your Mind", "No Such Thing As A Fish",
        "Everything is Alive", "Revisionist History", "Science Vs", "Freakonomics Radio",
        "The Infinite Monkey Cage", "StarTalk Radio", "Sean Carroll's Mindscape",
        "Making Sense with Sam Harris", "Philosophize This!", "Decoder Ring",
        "The New Yorker: Fiction", "Answer Me This!", "How To Fail With Elizabeth Day",
        "This Past Weekend w/ Theo Von", "SmartLess", "Desert Island Discs",
        "The West Wing Weekly", "Great Lives", "More or Less",
    ],
}

# ─────────────────────────────────────────────
# LOAD ENV
# ─────────────────────────────────────────────
def load_env():
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

# ─────────────────────────────────────────────
# PARSE OPML
# ─────────────────────────────────────────────
def parse_opml(opml_path):
    tree = ET.parse(opml_path)
    root = tree.getroot()
    feeds = []
    for outline in root.iter("outline"):
        url  = outline.get("xmlUrl")
        name = outline.get("text", "Unknown")
        if url:
            feeds.append({"name": name, "url": url})
    return feeds

# ─────────────────────────────────────────────
# FETCH SINGLE FEED
# ─────────────────────────────────────────────
def fetch_feed(feed, cutoff_date):
    """Fetch RSS feed and return recent episodes."""
    try:
        req = Request(
            feed["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; PodcastReader/1.0)"}
        )
        with urlopen(req, timeout=FEED_TIMEOUT) as resp:
            content = resp.read()

        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is None:
            return []

        episodes = []
        for item in channel.findall("item"):
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "") or item.findtext("summary", "")
            pub   = item.findtext("pubDate", "")

            if not title:
                continue

            # Parse date
            pub_date = None
            if pub:
                try:
                    pub_date = parsedate_to_datetime(pub)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                    pub_date = pub_date.astimezone(timezone.utc)
                except Exception:
                    pass

            # Filter by date
            if pub_date and pub_date < cutoff_date:
                continue

            # Clean description (strip HTML tags crudely)
            clean_desc = ""
            if desc:
                import re
                clean_desc = re.sub(r"<[^>]+>", " ", desc)
                clean_desc = re.sub(r"\s+", " ", clean_desc).strip()[:300]

            episodes.append({
                "podcast": feed["name"],
                "title": title,
                "description": clean_desc,
                "pub_date": pub_date.strftime("%Y-%m-%d") if pub_date else "unknown",
            })

        return episodes[:5]  # Max 5 recent episodes per podcast

    except Exception:
        return []

# ─────────────────────────────────────────────
# FETCH ALL FEEDS
# ─────────────────────────────────────────────
def fetch_all_feeds(feeds, days_back):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    all_episodes = []
    failed = 0

    print(f"📡  Fetching {len(feeds)} feeds (last {days_back} days)...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_feed, feed, cutoff): feed for feed in feeds}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            episodes = future.result()
            if episodes:
                all_episodes.extend(episodes)
            else:
                failed += 1
            if completed % 50 == 0:
                print(f"   {completed}/{len(feeds)} feeds checked... ({len(all_episodes)} episodes so far)")

    # Sort by date descending
    all_episodes.sort(key=lambda x: x["pub_date"], reverse=True)

    print(f"✅  Found {len(all_episodes)} episodes across {len(feeds) - failed} active feeds")
    if failed:
        print(f"   ({failed} feeds timed out or had no recent episodes)")

    return all_episodes[:MAX_EPISODES]

# ─────────────────────────────────────────────
# GET CATEGORY FOR PODCAST
# ─────────────────────────────────────────────
def get_category(podcast_name):
    for cat, podcasts in CATEGORIES.items():
        if podcast_name in podcasts:
            return cat
    return "General"

# ─────────────────────────────────────────────
# ASK CLAUDE FOR RECOMMENDATIONS
# ─────────────────────────────────────────────
def get_recommendations(client, episodes, topic, top_n):
    # Build episode list grouped by category
    episode_lines = []
    for ep in episodes:
        cat = get_category(ep["podcast"])
        line = f"[{ep['pub_date']}] [{cat}] {ep['podcast']} — {ep['title']}"
        if ep["description"]:
            line += f"\n    {ep['description'][:200]}"
        episode_lines.append(line)

    episode_text = "\n\n".join(episode_lines)

    topic_line = f"TOPIC/MOOD REQUESTED: {topic}" if topic else "TOPIC/MOOD: Matthew hasn't specified — recommend the most broadly valuable episodes across his interests"

    prompt = f"""You are recommending podcast episodes to Matthew — Senior Director of Corporate Systems, Seattle, 35. He runs a personal development framework across 7 pillars: Physical Health, Mental Health, Identity, Work/Craft, Relationships, Aliveness/Play, Agency/Discipline.

His podcast library spans: AI & Tech, CIO/Enterprise Tech, ERP, Leadership, Public Speaking, Health/Fitness, Mental Health, Finance, History, Football, News, and Sleep.

{topic_line}

Here are {len(episodes)} recent episodes from his subscriptions (last {DAYS_BACK} days):

{episode_text}

---

Return EXACTLY {top_n} episode recommendations. For each:

RANK [N]: [Podcast Name] — [Episode Title]
DATE: [pub date]
CATEGORY: [category]
WHY: 2-3 sentences on why this episode is worth Matthew's time RIGHT NOW, specific to his profile and the requested topic. Be direct — what will he actually get from it?
BEST FOR: [one of: commute · workout · deep focus · wind-down · background]

After the {top_n} recommendations, add:

ALSO CONSIDER:
List 3 more episodes in one line each that narrowly missed the cut, with one-sentence reason.

Be specific and confident. Don't hedge. If the topic is technical, prioritise depth. If it's personal development, connect it to his P40 pillars."""

    print(f"\n🤖  Asking Claude to pick the best {top_n} episodes...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

# ─────────────────────────────────────────────
# INTERACTIVE MODE
# ─────────────────────────────────────────────
def interactive_mode(client, feeds, days_back):
    """Run repeated recommendations without re-fetching feeds."""
    print("\n" + "─"*60)
    print("  🎙️  Podcast Recommender — Interactive Mode")
    print("  Type a topic, press Enter for surprise picks, or 'exit'")
    print("─"*60)

    # Fetch once
    episodes = fetch_all_feeds(feeds, days_back)
    if not episodes:
        print("\n❌  No recent episodes found. Try increasing --days\n")
        return

    while True:
        try:
            topic = input("\nWhat do you want to learn or hear about? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.\n")
            break

        if topic.lower() == "exit":
            print("\nGoodbye.\n")
            break

        result = get_recommendations(client, episodes, topic or None, TOP_N)
        print("\n" + "═"*60)
        print(result)
        print("═"*60)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="P40 Podcast Recommender")
    parser.add_argument("--topic", type=str, default=None,
                        help="What you want to hear about (e.g. 'MCP and AI agents')")
    parser.add_argument("--days", type=int, default=DAYS_BACK,
                        help=f"How many days back to look (default: {DAYS_BACK})")
    parser.add_argument("--interactive", action="store_true",
                        help="Run in interactive mode — ask multiple times without re-fetching")
    args = parser.parse_args()

    print("\n" + "═"*60)
    print("  🎙️  P40 Podcast Recommender")
    print("═"*60)

    # Credentials
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        import getpass
        key = getpass.getpass("\n  Anthropic API key: ")
        os.environ["ANTHROPIC_API_KEY"] = key

    # Check OPML
    opml_path = OPML_PATH
    if not os.path.exists(opml_path):
        # Try Desktop fallback
        desktop_path = os.path.expanduser("~/Desktop/PocketCasts.opml")
        if os.path.exists(desktop_path):
            opml_path = desktop_path
        else:
            print(f"\n❌  OPML file not found at: {opml_path}")
            print(f"    Export from Pocket Casts and save to ~/Documents/Claude/PocketCasts.opml\n")
            sys.exit(1)

    # Parse feeds
    feeds = parse_opml(opml_path)
    print(f"📚  Loaded {len(feeds)} podcast subscriptions")

    client = anthropic.Anthropic()

    if args.interactive:
        interactive_mode(client, feeds, args.days)
    else:
        # Single run
        episodes = fetch_all_feeds(feeds, args.days)
        if not episodes:
            print("\n❌  No recent episodes found. Try --days 60\n")
            sys.exit(1)

        result = get_recommendations(client, episodes, args.topic, TOP_N)

        print("\n" + "═"*60)
        if args.topic:
            print(f"  Top picks for: {args.topic}")
        else:
            print("  Top picks this week")
        print("═"*60)
        print(result)
        print("═"*60 + "\n")

if __name__ == "__main__":
    main()
