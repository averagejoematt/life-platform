#!/usr/bin/env python3
"""
P40 Second Brain — Obsidian + Claude
Reads your entire Obsidian vault and opens an interactive Claude
conversation pre-loaded with all your notes.

Usage:
    python3 p40_obsidian.py
    python3 p40_obsidian.py --mode review      # Weekly review mode
    python3 p40_obsidian.py --mode gaps        # Find knowledge gaps
    python3 p40_obsidian.py --mode mentor      # Mentoring / progress check

Requirements:
    pip3 install anthropic
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("\n❌  Run: pip3 install anthropic --break-system-packages\n")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
VAULT_PATH = os.path.expanduser(
    "~/Documents/Applications/Second Brain/MWSecondBrain"
)
ENV_PATH = os.path.expanduser("~/.p40_env")
MAX_NOTE_CHARS = 3000  # Truncate very long individual notes
MODEL = "claude-sonnet-4-20250514"

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
# READ VAULT
# ─────────────────────────────────────────────
def read_vault(vault_path):
    """Read all markdown files from vault, preserving folder context."""
    vault = Path(vault_path)
    if not vault.exists():
        print(f"\n❌  Vault not found at: {vault_path}")
        print("    Edit VAULT_PATH in the script to match your vault location.\n")
        sys.exit(1)

    notes = []
    skipped = []

    for md_file in sorted(vault.rglob("*.md")):
        # Get relative path for folder context
        rel_path = md_file.relative_to(vault)
        folder = str(rel_path.parent) if str(rel_path.parent) != "." else "Root"
        name = md_file.stem

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                skipped.append(name)
                continue
            # Truncate very long notes
            truncated = False
            if len(content) > MAX_NOTE_CHARS:
                content = content[:MAX_NOTE_CHARS]
                truncated = True

            notes.append({
                "name": name,
                "folder": folder,
                "path": str(rel_path),
                "content": content,
                "truncated": truncated,
                "word_count": len(content.split()),
            })
        except Exception as e:
            skipped.append(f"{name} ({e})")

    return notes, skipped

def format_vault_for_claude(notes):
    """Format all notes into a structured prompt block."""
    sections = {}
    for note in notes:
        folder = note["folder"]
        if folder not in sections:
            sections[folder] = []
        sections[folder].append(note)

    output = []
    total_words = sum(n["word_count"] for n in notes)
    output.append(f"VAULT SUMMARY: {len(notes)} notes · {total_words:,} words · {len(sections)} folders\n")

    for folder, folder_notes in sorted(sections.items()):
        output.append(f"\n{'═'*60}")
        output.append(f"FOLDER: {folder} ({len(folder_notes)} notes)")
        output.append('═'*60)
        for note in folder_notes:
            trunc = " [truncated]" if note["truncated"] else ""
            output.append(f"\n## {note['name']}{trunc}")
            output.append(f"_Path: {note['path']}_\n")
            output.append(note["content"])
            output.append("")

    return "\n".join(output)

# ─────────────────────────────────────────────
# SYSTEM PROMPTS BY MODE
# ─────────────────────────────────────────────
def get_system_prompt(mode, vault_content):
    base = f"""You are Matthew's personal Second Brain assistant. You have been loaded with the complete contents of his Obsidian vault — his personal knowledge base, journal entries, book notes, professional development materials, and growth reflections.

ABOUT MATTHEW:
- 35, Senior Director of Corporate Systems, Seattle
- Running a 3-year personal development framework called Project40 across 7 pillars: Physical Health, Mental Health, Identity/Integrity, Meaningful Work, Relationships, Aliveness/Play, and Agency/Discipline
- Intellectually curious, optimization-focused, wants depth not surface
- Values directness — no filler, no excessive hedging
- His vault covers: Health & Fitness, Mental Health (Anxiety, Therapy, Memory), Professional (Leadership, Public Speaking, Soft Skills, Career, Finance)

HIS VAULT CONTENTS:
{vault_content}

YOUR CAPABILITIES:
- Answer questions about anything in his notes
- Find connections between notes he may have forgotten
- Identify gaps in his knowledge or thinking
- Help him go deeper on topics already in the vault
- Challenge his assumptions based on what he's written
- Track themes and patterns across his notes
- Suggest what to add, improve, or link
"""

    modes = {
        "chat": base + """
YOUR MODE: Open conversation. Answer whatever Matthew asks. Be direct, specific, and reference actual notes by name when relevant. Don't be vague — if it's in the vault, cite it.""",

        "review": base + """
YOUR MODE: Weekly Review. Analyse the vault and produce a structured review:
1. THEMES THIS PERIOD — what topics appear most recently or frequently
2. PROGRESS SIGNALS — evidence of growth or consistency in any pillar
3. DORMANT AREAS — topics that haven't been touched recently
4. STRONGEST NOTES — the most developed, useful notes in the vault
5. WEAKEST AREAS — where knowledge is thin or incomplete
6. 3 RECOMMENDED ACTIONS — specific things to add, link, or explore this week
Be specific. Reference actual note names.""",

        "gaps": base + """
YOUR MODE: Knowledge Gap Analysis. Your job is to identify what's missing.
1. Map what exists against Matthew's P40 pillars — what's well covered, what's absent
2. Identify topics mentioned in notes that have no dedicated note yet
3. Find areas where notes exist but lack depth or actionability
4. Suggest 5 specific notes he should create, with a one-line description of what each should contain
5. Identify any contradictions or unresolved tensions in his notes
Be direct and specific. This is diagnostic, not motivational.""",

        "mentor": base + """
YOUR MODE: Mentor & Progress Check. Act as a senior mentor who has read everything Matthew has written.
1. What patterns do you see in how he thinks and what he values?
2. Where is he clearly growing vs where is he stuck or avoiding?
3. What blind spots or gaps in self-awareness do you notice?
4. What is the single most important thing he should focus on right now based on everything you've read?
5. Ask him 3 probing questions that would move his thinking forward
Be honest. Don't just validate — challenge where the notes suggest he should be challenged.""",
    }

    return modes.get(mode, modes["chat"])

# ─────────────────────────────────────────────
# INTERACTIVE CHAT LOOP
# ─────────────────────────────────────────────
def chat_loop(client, system_prompt, initial_message=None):
    """Run an interactive multi-turn conversation."""
    messages = []
    print("\n" + "─"*60)
    print("  💬  Second Brain Chat  (type 'exit' to quit)")
    print("  Commands: 'review' · 'gaps' · 'mentor' · 'save' · 'exit'")
    print("─"*60 + "\n")

    # If there's an initial auto-message (for review/gaps/mentor modes)
    if initial_message:
        messages.append({"role": "user", "content": initial_message})
        print(f"Running: {initial_message}\n")
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        reply = response.content[0].text
        messages.append({"role": "assistant", "content": reply})
        print(reply)
        print()

    saved_responses = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye.\n")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print("\nGoodbye.\n")
            break

        if user_input.lower() == "save":
            # Save conversation to vault
            save_path = Path(VAULT_PATH) / "_Home" / f"Claude_Session_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            with open(save_path, "w") as f:
                f.write(f"# Claude Second Brain Session\n")
                f.write(f"_Generated: {datetime.now().strftime('%A, %d %B %Y %H:%M')}_\n\n")
                for msg in messages:
                    role = "**Matthew**" if msg["role"] == "user" else "**Claude**"
                    f.write(f"{role}:\n{msg['content']}\n\n---\n\n")
            print(f"\n💾  Saved to vault: {save_path.name}\n")
            continue

        # Special mode switches mid-conversation
        if user_input.lower() in ["review", "gaps", "mentor"]:
            mode_prompts = {
                "review": "Please run the weekly review analysis on my vault.",
                "gaps": "Please run the knowledge gap analysis on my vault.",
                "mentor": "Please run the mentor and progress check on my vault.",
            }
            user_input = mode_prompts[user_input.lower()]

        messages.append({"role": "user", "content": user_input})

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            )
            reply = response.content[0].text
            messages.append({"role": "assistant", "content": reply})
            print(f"\nClaude: {reply}\n")
        except Exception as e:
            print(f"\n❌  Error: {e}\n")
            messages.pop()  # Remove failed message

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="P40 Second Brain — Obsidian + Claude")
    parser.add_argument("--mode", choices=["chat", "review", "gaps", "mentor"],
                        default="chat", help="Conversation mode")
    args = parser.parse_args()

    print("\n" + "═"*60)
    print("  🧠  P40 Second Brain")
    print(f"  Mode: {args.mode.upper()}")
    print("═"*60)

    # Load credentials
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        import getpass
        key = getpass.getpass("\n  Anthropic API key: ")
        os.environ["ANTHROPIC_API_KEY"] = key

    # Read vault
    print(f"\n📂  Reading vault: {VAULT_PATH}")
    notes, skipped = read_vault(VAULT_PATH)
    print(f"✅  Loaded {len(notes)} notes", end="")
    if skipped:
        print(f" · {len(skipped)} skipped (empty)", end="")
    print()

    # Format for Claude
    vault_content = format_vault_for_claude(notes)
    total_chars = len(vault_content)
    print(f"📊  Vault: {total_chars:,} characters · fits in one context window")

    # Build system prompt
    system_prompt = get_system_prompt(args.mode, vault_content)

    # Set initial message for non-chat modes
    initial_messages = {
        "review": "Please run a full weekly review of my vault.",
        "gaps": "Please run a knowledge gap analysis of my vault.",
        "mentor": "Please run a mentor and progress check based on everything you've read.",
        "chat": None,
    }

    # Start client
    client = anthropic.Anthropic()

    if args.mode == "chat":
        print("\n✅  Vault loaded. Ask me anything about your notes.\n")

    chat_loop(client, system_prompt, initial_message=initial_messages[args.mode])

if __name__ == "__main__":
    main()