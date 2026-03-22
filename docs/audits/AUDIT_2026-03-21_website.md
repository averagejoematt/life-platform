# Website Manual Audit — March 21, 2026

> **Auditor**: Matthew Walker (CEO / Founder)
> **Method**: Manual walkthrough, Brave Browser, MacBook
> **Scope**: All live pages on averagejoematt.com
> **Output**: 50 findings across 20+ pages → fed into WEBSITE_STRATEGY.md

---

## Site-Wide Findings (3)

1. **Organization problem** — pages exist that the creator didn't know about. Flat nav, no categories.
2. **Category/sub-category menu needed** — pages should map to sections (results, methods, tech, about me) with 4-5 sub-pages each.
3. **Bottom navigation continues to fail** despite multiple fix attempts.

## Homepage (10)

4. **0.00% to goal** — incorrect if weight has been lost.
5. **Streak is a dash** — should show 0 explicitly; make "no active streak" clear.
6. **"Signal / Human Systems"** in marquee — unclear meaning.
7. **Weight blank** on marquee — inconsistent with web page showing most recent weigh-in.
8. **"19 data sources" hardcoded** — won't auto-update. Need parameterized counts site-wide.
9. **Day on Journey blank** — missing calculation.
10. **Current streak blank** — should show 0, longest streak, and streak definition.
11. **HRV/heart rate graph** — is this real data or decorative?
12. **"Gained 11.8lb in 30 days"** — misleading without journey total context (weight lost overall).
13. **Recovery 89** — meaningless to a viewer without range/context.

## /story/ (2)

14. **Data points blank** (weight).
15. **"95 intelligence tools"** — hardcoded or referenced?

## /live/ (1)

16. **Page too light** — only shows weight. Should show habits, exercise types, state of mind, journal. The live view should be the most impressive page.

## /journal/ (5)

17. **Menu shows wrong date** unlike other pages; yellow nav color out of place.
18. **Journal mechanism broken** — missed Wednesday auto-publish. Review workflow.
19. **Need preview/approval flow** — send draft to Matthew first before publishing.
20. **Individual blog posts have old/outdated menu** — not centralized.
21. **Rebrand from "journal"** — this is investigative journalism (Louis Theroux style), not personal notes. Rename.
22. **Create restart interview entry** — document the 2-week failure and reset.

## /platform/ (7)

23. **Tries to do too many things** — journey/weight/why content covered elsewhere.
24. Should focus on: architecture, what it's built on, intelligence layer, tool structure, costs.
25. **Needs architecture diagram** that makes the system look impressive/seamless.
26. **CTO/CIO test** — what would impress a technical executive?

## /start/ (2)

27. **Essentially a sitemap** — redundant with good nav.
28. **Repetitive hooks** ("ONE PERSON 19 DATA") — user journey not traced.

## /subscribe/ (1)

29. **No confirmation email received** when subscribing.

## /ask/ (2)

30. **Back flow awkward** — can't return to start of ask page.
31. **"Subscribe for more"** shown when subscription isn't offered yet.

## /character/ (3)

32. **Missing intro section** — needs avatar, achievement badges, story of the character journey.
33. **Not just metrics** — about happiness, fulfillment, science of human flourishing. Users need to understand the RPG gamification isn't just weight.
34. **Scores in lockstep** — all pillars move together; relationships went up 2 points with no data; little data on mind. Rethink scoring computation.

## /privacy/ (1)

35. **Email wrong** — setup matt@averagejoematt.com forwarding or update address.

## /tools/ (1)

36. **Liked it** — explore expansion opportunities.

## /cost/ (2)

37. **Accuracy vs hardcoded** — how dynamic is this data?
38. **Should be sub-category** under tech/architecture.

## /board/ (2)

39. **Replace Huberman + Attia** (scandal concerns) with equivalent experts. Keep their science internally.
40. **Show other boards** (technical, web) or make them referenceable for product strategy / architecture reviews.

## /methodology/ (1)

41. **Should be in parent category** with cost + architecture.

## /protocols/ (2)

42. **Expand with habits page** — tiers, vices (filtered), streak data (current/best/target), click-down to "why."
43. **Supplements should link to discoveries** for N=1 conclusions. Thread the experiment together: "HOW DO WE THREAD THE NEEDLE SO IT ALL TIES TOGETHER — THEM CONNECTING THE STORY THEMSELVES."

## /experiments/ (2)

44. **Need to actively use experiments** — visible to visitors.
45. **Future: upvote/downvote** on experiment outcomes (needs auth — defer).

## /sleep/ (1)

46. **Lacks narrative, data, purpose** — what would Dr. Matthew Walker (sleep scientist) expect? Trend lines, bedtimes, architecture.

## /glucose/ (1)

47. **Low narrative** — what matters, why, data overlays, experiment ties, throughline.

## /supplements/ (2)

48. **Missing many logged supplements**.
49. **Needs evidence links** — scientific journals, evidence summary. Distinguish "testing as N=1" vs "confidently sourced."

## /benchmarks/ (2)

50. **Personal records** — best hike, fastest mile, best bench. "Benchmark unlocked" when achieved.
51. **Visitor comparison** — because the whole thing is about Matt's data.

## /progress/ (1)

52. **Too weight-focused** — happiness, relationships, fulfillment. "Eight billion people trying to live a fulfilled life."

## /results/ (1)

53. **Overlaps with progress** — how to present beyond weight.

## /discoveries/ (1)

54. **If empty, show placeholder** — "X days of data, unlocks in Y more days."

## /achievements/ (1)

55. **Think through overlap** — progress/results/benchmarks/discoveries may need consolidation with logical differentiators.

## /habits/ (3)

56. **Earlier feedback applies** (tiers, streaks, vices).
57. **Liked the heatmap** — mixing up visuals is good.
58. **Huge part of platform** — blow this up much more.

## /about/ (2)

59. **Remove weight widget** — think throughline, less data fatigue. About me as human.
60. **Build content belongs on /platform/** — not here.

## /intelligence/ (1)

61. **How dynamic** — does it auto-update as intelligence is added?

## /accountability/ (2)

62. **Don't know what this page is or who it's for**.
63. **Vision**: Show flatline, sad gamer icon, "platform isn't doing its job and Matt isn't helping," nudge mechanism. AI can't solve everything — this is where the human element surfaces.

---

*All 63 findings addressed in docs/WEBSITE_STRATEGY.md — 42 fully incorporated, 8 added as explicit tasks in v1.1 gap analysis.*
