# The Coach Humanity Roadmap

> **North star (owner mandate, 2026-08-10):** open Telegram, ping a coach by name, and it
> feels like texting a real person — someone who remembers you, has their own life and
> opinions, can talk about anything, and initiates when it matters. The bar to aspire to:
> a cold reader of the thread couldn't reliably tell it isn't a human colleague. Telegram
> first; everything here eventually feeds the emails, the site's coach notes, and MCP.

This is the standing ledger for that ambition. Every idea carries a status:
**shipped** (merged), **filed** (a GitHub issue exists), or **horizon** (recorded here,
not yet worth an issue). The evidence base for the first wave is the first night of real
transcripts (2026-08-09/10, internal QA): the failures were register asymmetry (replies
5–10× the inbound length), stat recitals, question-compulsion, shared stock phrases
across voices, and a coach arguing with Matthew about her own name because a poisoned
memory row said otherwise. The single best conversation of the corpus was the one whose
replies matched Matthew's length and whose questions advanced a decision.

**The theory, compressed:** texting feels human when seven things hold —
(1) *register symmetry* (length, punctuation, energy mirror the other person),
(2) *memory with feelings* (what a friend remembers, not what a CRM stores),
(3) *initiative* (real people text first, at the right moments, and respect silence),
(4) *imperfection* (fragments, dropped periods, occasional self-correction — never polish),
(5) *inner life* (opinions, a day of their own, taste, disagreement),
(6) *time-awareness* (Friday-ness, "been a minute", anniversaries),
(7) *bounded honesty* (never fabricates — the grounding gate is load-bearing for trust,
which is itself a humanity feature: a friend who makes things up stops being one).

## 1. Register & rhythm

| # | Idea | Status |
|---|------|--------|
| 1 | Register mirroring — a bare "hey" gets a bare hey back; default one bubble, 1–2 sentences | **shipped** (#2481) |
| 2 | Question budget — end on statements when the thread has momentum; filler-question ban | **shipped** (#2481) |
| 3 | Assistant-ism & stock-opener ban; sparing use of his name | **shipped** (#2481) |
| 4 | Texture — fragments fine, short bubbles drop the final period, no lists/headers ever | **shipped** (#2481) |
| 5 | Typing-time-proportional bubble delays (long bubble = longer typing indicator) | **shipped** (outbound PR) |
| 6 | Length variance downward — "ha", "fair", a lone emoji are complete replies | **shipped** (implicit in #1) |
| 7 | Reaction emojis via `setMessageReaction` — sometimes the human move is 👍 on his message, not a reply | filed |
| 8 | Occasional double-text minutes later ("also —") when a genuine afterthought exists | horizon (must be rare or it's a gimmick) |
| 9 | Read-without-reply — after "thanks", the human move is often nothing | horizon (needs care: silence from a bot reads as breakage until trust exists) |
| 10 | Rare self-correction double-text ("*push day") | horizon (only if organic; never simulated typos) |
| 11 | Per-persona typing speed and latency personality (Brooks slow and deliberate, Vale instant) | horizon |

## 2. Memory that feels like friendship

| # | Idea | Status |
|---|------|--------|
| 12 | First-person memory voice — summaries as the coach's notes-to-self, not meeting minutes | **shipped** (#2481) |
| 13 | Persona outranks poisoned notes — identity is never re-litigated from a bad memory row | **shipped** (#2481) |
| 14 | Open-loop keeping — "I'll check in Friday" is a promise the coach actually keeps (scheduled follow-through on coach commitments) | **shipped** (#2486 — extracted from the stored `CHAT#` turn, not a derived row) |
| 15 | Memory callbacks with feeling — "how'd the 5am push day actually go?" | **shipped** in substance (summaries + morning check-in); quality tracked here |
| 16 | Inside references — recurring bits accumulate per relationship (a RELATIONSHIP#bits ledger, capped, curated) | filed |
| 17 | His-people memory — names he mentions (friends, family) persist so a coach can ask about them later (internal only, never on any public surface) | filed |
| 18 | Emotional-state continuity — yesterday's frustration shapes today's opening | partial (summaries keep emotional context; strengthen as evidence arrives) |
| 19 | Time-gap awareness — "been a minute" after a quiet week | filed (cheap: last-chat date is already in the partition) |
| 20 | Milestone/anniversary memory — "a year since attempt #1" | horizon |

## 3. Initiative — the biggest unlock

| # | Idea | Status |
|---|------|--------|
| 21 | Eli's weekday morning check-in — one message, the day's single priority, silence-respecting | **shipped** (outbound PR; dark until his bot is registered) |
| 22 | Referral handoffs — coach A names a colleague's lane, the colleague texts once with context | **shipped** (outbound PR) |
| 23 | Silence respect — two ignored outbounds ⇒ stop initiating | **shipped** (outbound PR) |
| 24 | Hard caps as a feature — ≤2 unsolicited texts/day platform-wide; scarcity is what keeps initiative human | **shipped** (outbound PR) |
| 25 | Event-triggered celebration — a PR on a lift, a weight milestone: the right coach texts first | **shipped** (#2490) |
| 26 | Event-triggered concern — three bad recovery days: Lisa checks in softly | **shipped** (#2490) |
| 27 | Pre-event support — he mentions a presentation tomorrow; the coach he TOLD texts that morning | **shipped** (#2486, same extractor — the `COMMITMENT#` substrate premise was wrong: those rows are the nightly `OUTPUT#` extraction, coach→Matthew actions) |
| 28 | Sunday-evening reflection from Eli (the week, in one warm text — distinct from the Monday compass email) | horizon |
| 29 | Non-data initiative from persona interests ("watched the game?") | horizon (needs real persona-interest grounding to not be hollow) |

## 4. Inner life & texture

| # | Idea | Status |
|---|------|--------|
| 30 | Off-lane competence — text a coach about anything; person first, service line never | **shipped** (#2481) |
| 31 | Opinions & respectful disagreement — coaches hold views from their bibles and push back | partial (bibles carry beliefs; pushback few-shots as evidence arrives) |
| 32 | Grounded pushback — "you sure? last time 5am starts wrecked your week" (facts-backed, gate-safe) | filed |
| 33 | Weather & season texture — the platform already ingests weather; "cold one this morning, warm up properly" | filed |
| 34 | Day-of-week texture — Friday-ness and Monday-ness in voice (moment line already carries the day) | filed (same issue as #33) |
| 35 | Persona-stable routine references ("just got out of a session") — bible-consistent texture, never variable fabrication | horizon (needs a written boundary: texture from the bible is voice; invented events are lies) |
| 36 | Per-coach emoji palettes and verbal tics | **shipped** (texting_style exists per persona; tuning continues) |
| 37 | Voice notes — Telegram `sendVoice` in the persona's TTS voice (registry already carries `tts_voice`; podcast TTS infra exists) | filed |
| 38 | Coach availability in voice — budget pauses and caps phrased as the persona would say them, per coach | filed |
| 39 | Images — Brooks sketches a plan on a whiteboard photo | horizon |

## 5. Conversation intelligence

| # | Idea | Status |
|---|------|--------|
| 40 | Emotional subtext before data — respond to how he sounds, then to what he asked | **shipped** (#2481 rules; ongoing craft) |
| 41 | No stat recitals — never restate a number already sent in-thread | **shipped** (#2478/#2481) |
| 42 | Deterministic repetition detector — "said the same thing nine times" becomes measurable | filed (#2350, promoted) |
| 43 | Conversational repair — when corrected, "ah, my bad", not "Thank you for the correction" | filed (prompt-pass v3 bundle) |
| 44 | Experiment-aware conversation — Day N framing, the coach's own open predictions cited naturally ("I called 7h+ sleep this week — holding so far") | **shipped** (experiment-awareness PR) |
| 45 | Track-record humility — "I called this one wrong last cycle" (prediction outcomes, not just open calls) | **shipped** (#2496 — graded calls join the fact block; a miss is guaranteed a slot over newer hits) |
| 46 | Multi-day thread pickup — resume exactly where things left off | **shipped** in substance (summaries; open-loops line strengthens it) |

## 6. The relationship arc & the team

| # | Idea | Status |
|---|------|--------|
| 47 | Relationship stages shape formality and bluntness over weeks | **shipped** substrate (RELATIONSHIP#state already feeds the prompt); tuning continues |
| 48 | Handoff continuity — the referred coach opens with the referral context, like colleagues actually talking | **shipped** (outbound PR) |
| 49 | Team texture — "we talked about you Tuesday — good things", grounded in real team-meeting artifacts | **shipped** (#2496 — TEAM ROOM from the inter-coach threads the coach was in, with a gate that refuses an invented meeting) |
| 50 | Grand Rounds — the board bot becomes a true group chat, multiple coaches responding in sequence with distinct voices | filed (epic #2363 roster item) |
| 51 | Succession done humanly — Max carries the training thread forward; history stays under Sarah's byline | **shipped** (route re-point + voice-structure port, outbound PR) |
| 52 | Coach-to-coach visible disagreement in Grand Rounds (two coaches, two readings, both grounded) | horizon (after #50) |

## Porting beyond Telegram

The register rules (§1) are chat-specific. Everything else — first-person memory,
initiative discipline, inner life, experiment-awareness, track-record humility — applies
verbatim to the daily brief's coach sections, the weekly emails, the site's coach notes,
and MCP check-ins. The porting order when Telegram proves out: **daily brief coach
voices → check-in queue → site coach commentary**. The measure stays the same: would a
cold reader think a person wrote this?

## Discipline

- Every shipped idea lands with tuning_log entries and behavior-suite pins; prompt rules
  are requests, so anything that must ALWAYS hold gets a deterministic gate as well.
- The grounding gate is never relaxed for the sake of feel. Honesty is the personality.
- Initiative stays scarce (caps above) — the moment coaches text like an app sends
  notifications, the illusion dies.
- Filed issues carry `area:coach-humanity` so this ledger and the backlog can't drift.

### The outbound priority decision (owner, 2026-08-10 — #2490)

Ideas 14, 21, 22, 25, 26 and 27 all end in the same place: an unsolicited text, out of
the same two-a-day budget. First-come-first-served was fine with two features and is a
bug with six — whichever one happens to fire last in the day is permanently starved, and
it is never the least valuable one. So **every outbound now declares a provenance class,
and the classes are ranked** (`coach_outbound.OUTBOUND_PRIORITY`), highest first:

1. **a kept promise** — breaking one is the worst thing a coach can do
2. **referral** — contextual to a conversation he just had
3. **pre-event support**
4. **soft concern**
5. **morning check-in**
6. **celebration**

Two consequences, both deliberate. Within one sweep the higher class speaks: a soft
concern outranks a celebration, because checking on him matters more than congratulating
him. And **from 09:00 PT the day's SECOND slot is reserved for the top three (reactive)
classes** — the hour by which every scheduled outbound has already run in both PDT and
PST — so a routine morning ping can open the day but cannot close it before the text that
was actually about something happens. In practice that means at most one routine
unsolicited text a day, with the second slot held for a reactive one.

**The cap stays at 2.** This is ordering, not a raise; the moment it becomes a volume
knob the scarcity rule above is dead. `tests/test_coach_outbound_behavior.py` pins the
rank, the reservation, and the cap itself.
