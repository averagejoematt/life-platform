#!/usr/bin/env python3
"""
P40 Morning Mail Briefing
Connects to Proton Mail via Bridge and produces a daily email briefing:
  - Summary of unread emails
  - Flags emails needing a reply
  - Draft reply suggestions for flagged emails
  - Categorises emails by type

Usage:
    python3 p40_mail_briefing.py

Requirements:
    pip3 install anthropic
"""

import imaplib
import email
import getpass
import os
import sys
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr

try:
    import anthropic
except ImportError:
    print("\n❌  Missing dependency. Run: pip3 install anthropic --break-system-packages\n")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
IMAP_HOST = "127.0.0.1"
IMAP_PORT = 1143
SMTP_HOST = "127.0.0.1"
SMTP_PORT = 1025
PROTON_EMAIL = ""  # Set your Proton email here, or leave blank to be prompted

MAX_EMAILS = 20       # Max unread emails to process
MAX_BODY_CHARS = 2000 # Chars of body to send to Claude per email

# Categories — Claude will assign one to each email
CATEGORIES = [
    "Action Required",
    "Awaiting Reply",
    "Finance & Admin",
    "Personal",
    "Work",
    "Newsletter / Info",
    "Junk / Low Priority",
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def decode_str(s):
    """Decode email header string."""
    if not s:
        return ""
    parts = decode_header(s)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)

def get_body(msg):
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in disp:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return body.strip()

def fetch_unread(email_addr, password):
    """Connect to Proton Bridge IMAP and fetch unread emails."""
    print(f"\n🔌  Connecting to Proton Bridge ({IMAP_HOST}:{IMAP_PORT})...")
    try:
        mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        mail.login(email_addr, password)
    except Exception as e:
        print(f"\n❌  Connection failed: {e}")
        print("    Make sure Proton Mail Bridge is running and your password is correct.\n")
        sys.exit(1)

    mail.select("INBOX")
    _, data = mail.search(None, "UNSEEN")
    ids = data[0].split()
    print(f"✉️   Found {len(ids)} unread email(s). Processing up to {MAX_EMAILS}...")

    emails = []
    for uid in ids[-MAX_EMAILS:]:  # Most recent first
        _, msg_data = mail.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        sender_name, sender_addr = parseaddr(decode_str(msg.get("From", "")))
        subject = decode_str(msg.get("Subject", "(No subject)"))
        date_str = msg.get("Date", "")
        body = get_body(msg)[:MAX_BODY_CHARS]

        emails.append({
            "uid": uid.decode(),
            "from_name": sender_name or sender_addr,
            "from_addr": sender_addr,
            "subject": subject,
            "date": date_str,
            "body": body,
        })

    mail.logout()
    return emails

def analyse_with_claude(emails):
    """Send emails to Claude for analysis and return structured results."""
    client = anthropic.Anthropic()

    # Build the email list for Claude
    email_list = ""
    for i, e in enumerate(emails, 1):
        email_list += f"""
---
EMAIL {i}
From: {e['from_name']} <{e['from_addr']}>
Subject: {e['subject']}
Date: {e['date']}
Body:
{e['body']}
"""

    prompt = f"""You are analysing unread emails for Matthew — a Senior Director of Technology in Seattle, UK-born, early 30s. He values directness, efficiency, and has a structured personal life.

Here are his {len(emails)} unread emails:

{email_list}

For EACH email, provide:
1. CATEGORY: One of: {", ".join(CATEGORIES)}
2. SUMMARY: 1-2 sentence plain English summary of what this email is actually about
3. NEEDS_REPLY: true or false — does this genuinely need a response from Matthew?
4. REPLY_DRAFT: If NEEDS_REPLY is true, write a concise, professional draft reply in Matthew's voice (direct, warm, no fluff). If false, write "N/A".
5. PRIORITY: High / Medium / Low

Format your response EXACTLY like this for each email, using the EMAIL number:

EMAIL 1:
CATEGORY: [category]
SUMMARY: [summary]
NEEDS_REPLY: [true/false]
PRIORITY: [High/Medium/Low]
REPLY_DRAFT:
[draft text or N/A]
---

After all emails, add a section:

BRIEFING SUMMARY:
[3-5 sentence overview of what's in the inbox today, what needs attention first, and anything Matthew should know]"""

    print("🤖  Analysing with Claude...")
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def print_briefing(emails, analysis, output_file=None):
    """Print the formatted briefing to terminal and optionally to file."""
    lines = []
    lines.append("\n" + "═" * 65)
    lines.append("  📬  P40 MORNING MAIL BRIEFING")
    lines.append(f"  {datetime.now().strftime('%A, %d %B %Y  •  %H:%M')}")
    lines.append(f"  {len(emails)} unread email(s) processed")
    lines.append("═" * 65)

    # Print Claude's full analysis
    lines.append("\n" + analysis)
    lines.append("\n" + "═" * 65)
    lines.append("  Raw email details below for reference")
    lines.append("═" * 65)

    for i, e in enumerate(emails, 1):
        lines.append(f"\n  [{i}] {e['subject']}")
        lines.append(f"      From: {e['from_name']} <{e['from_addr']}>")
        lines.append(f"      Date: {e['date']}")

    lines.append("\n" + "═" * 65 + "\n")

    output = "\n".join(lines)
    print(output)

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        print(f"\n💾  Briefing saved to: {output_file}\n")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def load_env():
    """Load credentials from ~/.p40_env if it exists."""
    env_path = os.path.expanduser("~/.p40_env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

def main():
    print("\n" + "─" * 65)
    print("  P40 Morning Mail Briefing")
    print("─" * 65)

    # Load credentials from ~/.p40_env
    load_env()

    # Get credentials — use .p40_env values, fall back to prompts
    email_addr = os.environ.get("PROTON_EMAIL") or input("\n  Proton email address: ").strip()
    password = os.environ.get("PROTON_BRIDGE_PASSWORD") or getpass.getpass("  Bridge password (hidden): ")

    # Check for Anthropic API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n  ⚠️  ANTHROPIC_API_KEY not set in environment.")
        api_key = getpass.getpass("  Paste your Anthropic API key (hidden): ")
        os.environ["ANTHROPIC_API_KEY"] = api_key

    # Fetch emails
    emails = fetch_unread(email_addr, password)

    if not emails:
        print("\n✅  Inbox is clear — no unread emails.\n")
        return

    # Analyse
    analysis = analyse_with_claude(emails)

    # Output — save to Desktop for easy access
    desktop = os.path.expanduser("~/Desktop")
    filename = f"mail_briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    output_path = os.path.join(desktop, filename)

    print_briefing(emails, analysis, output_file=output_path)

if __name__ == "__main__":
    main()
