# Story Page — Draft Content for Review

## Source: Matthew Walker interview (March 26, 2026)
## Status: DRAFT — awaiting Matthew's redlines before implementation
## Privacy: All guardrails applied. Family members abstracted, specific events generalized.

---

## CHAPTER 01: THE MOMENT

I've lost 100 pounds before. Three times, actually — maybe four if you count the one in college. I know how to do it. I know the meal prep, the progressive overload, the morning walks that turn into rucks that turn into mountain trails. I know what it feels like when people start noticing. When old clothes fit again. When strangers at the gym nod at you like you belong there.

In May 2025, I was there. I'd spent nine months being ruthless — stretching every single day for 36 weeks straight, rucking Washington mountains with 25 pounds on my back, running 10-mile Saturday sessions and then hitting the gym afterwards. I was eating clean. I was wearing all my old clothes. I was down to 190 and felt like a different person. An old man at the gym came up to me and told me how determined I was. My girlfriend's dad said he couldn't recognize me. I bought myself a Rolex — not because I'm flashy, but because I'd never let myself have something like that, and I wanted a permanent reminder that I'd done it. I wrote a whole speech on my phone, imagining the moment I'd say it all out loud. I threw out every piece of large clothing I owned.

And then life happened. Within a few months, I lost a family member to cancer — the second time cancer had taken someone close to me, after my mum died in 2019. Work became uncertain in ways that affected not just me but people I was responsible for. The travel, the grief, the stress — each one alone might have been manageable. Together, they dismantled everything.

The slide didn't happen all at once. It never does. It started with one DoorDash order — something innocent, maybe justified. Then another. Then the gym sessions went from five days to three to one to none. Then it was just: wake up, work, sleep. Wake up, work, sleep. Weekends disappeared into nothing. I wasn't partying. I wasn't living some reckless life. I was just... on standby. Present, powered on, but doing nothing. And before I knew it, five months had gone by.

By February 2026, I stepped on the scale and saw 302.

The disgust wasn't new. The disappointment wasn't new. But this time there was something else underneath it — a recognition that I'd made this exact promise before. That I'd stood in front of a mirror at this exact weight, said "never again," and meant it completely. And yet here I was, buying an entirely new wardrobe to replace the one I'd thrown out in celebration six months earlier.

That's when the question changed. It wasn't "how do I lose weight again?" I know how. The question was: **why does it keep coming back?**

---

## CHAPTER 02: THE PROBLEM WITH PREVIOUS ATTEMPTS

I've been on this ride since I was a teenager. Gained weight before college, lost it, gained it back. Had my first real fitness chapter at 20, got in great shape, then went to work at sea — sailing, port cities, being 22 — and it crept up again. Moved to Seattle, found a girlfriend, lost and gained in cycles for years. From 22 to 27, I had it pretty well managed.

Then the wheels came off for real. I got promoted to a director role while finishing an MBA, relocated to a city where I knew nobody, and then my mum was diagnosed with stage 4 cancer — all at the same time. That was when the eating stopped being about hunger or convenience and became something else. A release. A way to feel something good in the middle of something terrible.

Here's the pattern, if I'm honest about it: I can do the work. That's never been the issue. When I'm locked in, I'm relentless — daily stretching, mountain rucks, 10-mile runs, clean eating for months on end. The engine runs. But the moment something disrupts the routine — a trip, a stressful week, a loss — there's a crack. And through that crack comes one DoorDash order. Then another. Then the gym falls away, and suddenly I'm in a cycle of work-sleep-work-sleep, and five months evaporate before I even register what happened.

The cruelest part is the embarrassment. When you've been visibly, publicly in shape — when people have congratulated you, when you've made the speeches and bought the watch and thrown out the clothes — regaining everything doesn't just feel like failure. It feels like fraud. You stop wanting to see people. You cancel plans. You find reasons not to leave the house. Not because you're lazy, but because the gap between who you were six months ago and who you are now is so loud that you can't face anyone who remembers the other version.

Every previous attempt treated this as a weight problem. Calories in, calories out. Move more. Eat less. And that works — until it doesn't. Because the weight was never the root issue. It was the coping mechanism. And no amount of rucking will fix a coping mechanism you haven't even named.

---

## CHAPTER 03: THE BUILD

The first thing I built had nothing to do with a website.

I'm a Senior Director at a SaaS company — my background is IT leadership. I manage teams, approve architecture decisions, run vendor relationships. I've overseen production deployments, upgraded servers, managed Oracle databases, shipped network infrastructure. But I had never, in my career, written application code and deployed it myself.

The idea was simple: get my health data into AWS so I could talk to Claude about it with actual numbers attached. Every AI conversation I'd had about my health was limited by the same problem — I'd give it context from memory, which meant I was filtering, forgetting, and rationalizing before the AI even got a chance to help. If I could pipe in real data from Whoop, Eight Sleep, MacroFactor, Habitify — all the things I was already tracking — then the feedback would be based on what actually happened, not what I remembered happening.

So I started. The first Lambda function was terrifying. I knew what Lambda *was* — my team uses these technologies daily, I'd approved dozens of architecture decisions involving them — but writing one myself, wiring it to DynamoDB, getting IAM permissions right? That was new. Claude handled the code. I handled the architecture decisions, the "what should this system actually do" questions, and every single deploy.

The thing that surprised me wasn't that Claude could write Python. I expected that. It was the infrastructure work — IAM roles, CI/CD pipelines, git workflows — where I had my first genuine "wait, this is actually possible" moment. The amount of operational complexity that just... worked, with minimal instruction, was the early signal that this wasn't going to be a toy project.

What I bring is the thing no language model can simulate: I know what it's like to be me. I know which patterns matter and which are noise. I know that my relationship with food isn't about macros — it's about coping. I know that my sleep quality correlates with how I'm doing mentally in ways that no generic training data can capture. The platform I'm building isn't something a prompt could decode, because the person it's designed for is too specific, too contradictory, and too stubborn to fit in a template.

The professional angle matters too. My team at work is responsible for rolling out Claude across the company. Building this platform gave me something I couldn't get from vendor demos or pilot programs — real, visceral understanding of what AI-assisted development actually feels like when you're not an engineer. Every conversation I have at work about AI adoption is now grounded in something I built with my own hands, on my own time, for stakes that actually matter to me.

---

## CHAPTER 04: WHAT THE DATA HAS SHOWN

This section is honest about where things stand: the platform is young, and I've spent more time building it than I have running it during a sustained active phase. But even in the early data, there are signals.

The first thing that surprised me was how directly supplements affect my sleep architecture. Not just "I slept well" or "I didn't" — but measurable shifts in deep sleep duration and HRV recovery that tracked to specific changes in my evening stack. Before the platform, I was taking supplements on faith. Now I can see which ones actually move the needle on the thing I care about most: waking up recovered.

The second discovery was more about my mind than my metabolism. I'd been carrying low-grade health anxiety for a while — the kind where you catastrophize every symptom, avoid the doctor when things are bad, and only go when you feel good enough to hear reassuring news. When I started wearing a continuous glucose monitor, the data didn't reveal some dramatic dietary problem. It showed me something better: I'm not in the danger zone I'd been quietly terrified of. The CGM didn't change my blood sugar. It changed my relationship with the fear. That's a discovery the platform surfaced that no amount of Googling "am I pre-diabetic" at 2am ever could.

The third discovery is the hardest to admit: **the platform didn't prevent the relapse.**

I built sick-day tracking. I built habit monitoring. I built an AI that reads 19 data sources every morning and writes me a coaching brief. And when the cold hit and the DoorDash started and the days on the couch stretched from three to thirty — the system watched it happen. It logged it faithfully. It didn't catch me.

That's not a failure of the technology. It's a gap in the design. The system was built to support someone who's engaged. It wasn't built to intervene when someone checks out. That gap — the space between tracking data and actually changing behavior during a spiral — is what the next phase of this platform needs to solve. If the AI can see that I'm logging sick days for three weeks straight while my DoorDash spend spikes and my gym check-ins vanish, it should do something about it. Not just record it.

This chapter will grow as the data does. I'm building the platform in public specifically so that the discoveries — real ones, with statistical backing — accumulate here over time. Right now, the most honest thing I can tell you is: the early signals are promising, the system works when I work with it, and the biggest insight so far is about what happens when I stop.

*[Explore the data yourself → Data Explorer]*

---

## CHAPTER 05: WHY PUBLIC

Here's the part I didn't plan to write.

Since my mum passed in 2019, I lost my cheerleader. That sounds simple but it isn't. She was the person who cared — really cared — about every promotion, every milestone, every "you won't believe what happened today" phone call. My dad and my brother love me, but the way they show it is different. A short text. A standard follow-up question. It's enough, and I don't blame them for it. But the feeling of being *seen* — of someone tracking the full arc of your life and caring about the details — that left when she did.

Maybe this site is me trying to find my cheerleaders.

I don't mean that in a self-pitying way. I mean it practically: I perform better when someone is watching. Not judging — watching. When I was in shape last May, part of what kept me going was that people could see it. The gym regulars. Brittany's family. The old man who said I was determined. The visibility wasn't vanity. It was accountability with a human face.

So I decided to publish everything. The weight. The streaks. The days I didn't show up. The weeks where the data flatlines because I was on the couch ordering delivery food and calling it "sick days." If I'm going to build a system that demands honesty from the data, I should demand the same from myself.

The second reason is less personal and more forward-looking. I know from years of quietly reading Reddit threads that there are a lot of people stuck in the same cycle I am — people who can do the work but can't sustain it, people who've lost the weight and gained it back and feel like frauds for it. I love fitness. I love working out. That's what's so strange about the periods when I stop — it's not that I hate it. I just... disconnect. If this platform and this site can show someone in that position that the problem isn't willpower, that there might be something more structural going on, and that there's a way to build systems around it — that would matter to me more than any metric on a dashboard.

The dream, eventually, is to make this available to others. Not just the data — the framework. The character sheet, the coaching briefs, the experiments, the accountability infrastructure. Right now, that's a distant goal. First I need to prove it works on me. First I need to show that I got happier, healthier, and more present — not through white-knuckling it, but through a system that caught what I couldn't see on my own.

185 pounds isn't just a number. It's the version of me where sports, exercise, socializing — none of it felt out of reach. I'm not naive enough to think I can go back to being 25. But for a couple of weeks last May, even with all my anxiety and awkwardness still intact, I could tell: I was better. Everything was a little more possible. That's what I'm building toward.

Every week, an AI journalist named Elena Voss reads the data and writes about what she finds. She doesn't soften the bad weeks. She doesn't celebrate plateaus as progress. The point is that the numbers tell the truth, even when I don't want them to.

You're welcome to watch.

---

## HOMEPAGE QUOTE (replacing placeholder)

**New quote:**
"I used to be the protagonist of my own life. Somewhere along the way, I became a spectator."
— Matthew Walker

---

## HOMEPAGE HERO NARRATIVE (replacing "got sick" framing)

**Current (inaccurate):**
"I built an AI health platform with 19 data sources and 95 intelligence tools. Then I got sick, fell off the wagon, and the system I built didn't catch me."

**Proposed replacement:**
"I built an AI health platform with 19 data sources and 95 intelligence tools. Then a three-day cold became a three-week DoorDash spiral, and the system I built watched it happen without catching me. So I'm starting over — publicly."

---

## HOMEPAGE DISCOVERY CARDS — ACTION REQUIRED

All three current cards are CONFIRMED PLACEHOLDERS:
1. "Sleep onset → Recovery" (r = -0.38) — NOT from real data
2. "Bed temp → Deep sleep" (+18 min) — NOT from real data
3. "Zone 2 → HRV" (+8%) — NOT from real data

**Options:**
A) Replace with "Coming soon — discoveries populate as data accumulates" treatment
B) Replace with the three real insights from the interview (supplements → sleep, CGM → anxiety relief, platform → didn't prevent relapse)
C) Mark current cards clearly as "Example correlations — real data coming"

**Board recommendation:** Option B reframed as narrative cards rather than fake correlation stats.

---

## ABOUT PAGE VALIDATION

### "Never shipped production code" — NEEDS REWORDING
**Current:** "I've never shipped production code at work."
**Revised:** "I've never written and deployed production application code at work — though I've shipped plenty of infrastructure changes, database updates, and network upgrades."

### Press bios (50-word and 100-word) — APPROVED as-is
Matthew confirmed these are acceptable for public use.

---

## FOLLOW-UP ITEMS (post-draft)

1. Matt to redline all 5 chapters — mark anything that's wrong, too exposed, or doesn't sound like him
2. Replace homepage discovery cards (decision needed: option A, B, or C above)
3. Chapter 4 will expand as real platform discoveries accumulate
4. "Standby" line from interview used in Chapter 1 (per Raj's recommendation to preserve it)
5. "Protagonist/spectator" quote goes on homepage (confirmed)
6. Pull quote in Chapter 2 currently reads: "The problem wasn't motivation..." — replace with something from the interview or remove
