# Reddit playbook — manual posting, 1–2× a month

**Status:** operating procedure · **Owner:** Matthew (human, always) · **Story:** #1625 (epic #1619)
**Verified:** 2026-07-21

Reddit is the only distribution channel that can reach **audience #1** — "Reddit
newcomers," the first row of the four-audience table in
`docs/PLATFORM_NORTH_STAR.md` — and it is also the only one that structurally
cannot be automated. That combination is why this is a document and not a
Lambda.

---

## 0. Do not automate this. Ever.

**No poster, no scheduler, no cross-post bot, no "assisted" draft-and-submit
flow. A future session reading this doc must not treat it as a spec.**

The reasoning, so nobody has to re-derive it:

- Reddit's spam and self-promotion enforcement is **account-level and
  retroactive**. A bot detected after 30 good posts doesn't lose the 31st — it
  loses the account, and often the domain along with it. `averagejoematt.com`
  getting domain-banned from the subs where audience #1 actually lives is an
  unrecoverable loss, not a setback.
- Enforcement is **per-subreddit and human**. Moderators apply judgment that no
  ruleset can be encoded against. The thing that gets a post removed is usually
  tone, not a rule violation you could lint for.
- The value here is **the comments**, and comments require a human who can
  answer follow-ups within the hour. A post that lands well and then goes silent
  for a day reads worse than no post at all.
- The expected value is asymmetric in the wrong direction for automation. One
  good manual post delivers roughly 200–2,000 visitors. Thirty days of flawless
  autoposting to a new, karma-less account delivers approximately zero — Jordan
  Kim's framing at the 2026-07-21 board: *"writing into a void with excellent
  penmanship."* Automation adds no upside and risks everything.

If a future story proposes automating any part of this, the answer is no, and
this section is the citation.

---

## 1. What actually travels: the gotcha, not the health data

This is the single most important calibration in the doc, and it is
counterintuitive.

**The asset is the build log** — `site/story/build/beats.json`, 57 beats as of
2026-07-21, every one carrying a `gotcha` and an `honest_miss` field. Those two
fields are the product. They are specific, technical, and unflattering, which is
exactly the shape of thing that earns engagement on these subs.

**The health narrative is not the asset.** A post that leads with weight,
recovery scores, or "I built a system to fix my life" reads as promotion on
every sub in the target list, because it is indistinguishable from the hundred
other such posts a mod removes each week. The health data is what people find
*after* the engineering earned their attention.

Concretely, from real beats:

- *"The public API that serves all this isn't managed by our infrastructure-as-code
  — it's deployed by its own script, which updates the code but never the shared
  code library it depends on."* — a deploy-topology trap any self-hoster has hit.
- *"The engine was still reading pre-2024 Whoop field names, so sleep — the single
  best-instrumented pillar — had been permanently stuck below the data-coverage
  floor and silently frozen."* — a silent-data-rot story with a real mechanism.
- *"The scoreboard is live but empty… every Brier score reads 'insufficient data'
  today. That's the honest state, not a bug."* — a public commitment to not
  faking a number.

Each of those is a post. None of them mentions a pound of body weight.

**The `honest_miss` field is the differentiator.** Reddit's reflex toward
self-promotion is suspicion, and the fastest way through it is to lead with what
didn't work. A post that says "here's what I built and here's the part that's
still broken" gets read as a peer's write-up. The same post without the second
half gets read as marketing.

---

## 2. Target subs

Four, in rough priority order. Each rewards something different, and a post
written for one will underperform in another.

| Sub | What it rewards | What gets you removed |
|---|---|---|
| **r/QuantifiedSelf** | Method and instrumentation. N-of-1 rigor. Honest null results. | Product launches; anything that reads like a service pitch. |
| **r/selfhosted** | Architecture, cost, and operational pain. Real numbers. | Hosted SaaS with no self-host story; screenshot-only posts. |
| **r/artificial** | What the model actually did and where it failed. Evaluation. | Hype; "I built an AI that…" with no failure analysis. |
| **r/loseit** | Personal honesty and sustainability. Lived experience. | Anything technical; anything that looks like traffic-seeking. |

**r/loseit is the odd one out and should be used sparingly, if at all.** It is
the only sub on this list where the health narrative *is* the asset and the
engineering is noise — the inverse of the calibration in §1. It is also the sub
where a badly-judged post does the most human damage, because the audience is
vulnerable and the moderation is protective by design. Default to the other
three; post to r/loseit only when there is a genuinely personal, non-technical
thing to say, and never with a link.

### Required pre-flight: read the sidebar

**Self-promotion rules are deliberately not transcribed into this doc.** They
change, they differ per sub, and a stale rule recorded here as fact would be
worse than no rule at all — it would be a confident wrong answer at the exact
moment accuracy matters.

Before every post, open the target sub and read:

1. The sidebar rules, in full.
2. The wiki/FAQ if the sidebar links one.
3. The last ~20 posts, to see what actually survives moderation there right now.

Record what you found in the log (§6) as of that date. If a sub requires
mod pre-approval for any self-referential post, ask — the ask costs a day, a
removal costs the account's standing.

---

## 3. Cadence

**1–2 posts per month, across all subs combined.** Not per sub — total.

This is a ceiling, not a target. There is no obligation to post monthly, and a
month with nothing worth saying should produce nothing. The failure mode this
guards against is the one every build-in-public account hits: posting because
the calendar said so, running out of genuine material, and sliding into
promotion. Two good posts a year beat twenty adequate ones, because the account's
credibility is the durable asset and it only spends down.

Minimum spacing between posts to the *same* sub: **one month**, regardless of
the overall count.

---

## 4. Format

- **Long-form, in Matthew's own voice.** First person, specific, technical where
  the sub is technical. Not a summary of a blog post — the post *is* the artifact.
- **No link in the body.** This is the rule most likely to be violated and most
  likely to get a post removed. If the post is good, people ask, and the link
  goes in a comment reply or the profile. A body link converts a write-up into
  an ad in one line.
- **No generated share cards, no OG images, no branded graphics.** The OG image
  Lambda's output is for link previews elsewhere; on Reddit it reads as
  marketing collateral. Plain text, or a screenshot of a real chart with real
  (possibly unflattering) data.
- **No AI-written prose.** Not for authenticity theater — because these subs
  detect it reliably and the penalty is dismissal of the whole post. The build
  beats are raw material to draw from, not text to paste.
- **Lead with the failure or the surprise.** The first two sentences decide
  whether the post is read. "Here's a thing that bit me" outperforms "I built a
  platform" every time.
- **Answer every comment for the first 24 hours.** This is the actual work of
  the post and the reason it can't be scheduled.

---

## 5. What a good post looks like

Three sketches, in Matthew's voice, drawn from real beats. These are examples of
*shape and register* — not templates. Do not fill in the blanks; write the post
that's true this month.

### r/selfhosted

> **My deploy script updated the code but not the library it depends on, and I
> didn't notice for a while**
>
> I run a personal health data platform on AWS — about 95 Lambdas, everything
> in CDK except one thing, and that one thing is what got me.
>
> The public API that serves my site has its own deploy script, separate from
> the infrastructure-as-code that manages everything else. It updates the
> function code. It does not update the shared library the function imports. So
> I'd publish a new version of the shared code, deploy the API, watch the deploy
> succeed, and get the old behavior — with no error anywhere, because nothing
> was actually wrong. The function was running exactly the code it had been
> given.
>
> The fix was collapsing to a single bundle so there's no second artifact that
> can lag. The lesson I'd pass on: if you have two deploy paths, you have two
> versions, and the one that bites you is the one that doesn't error.
>
> Happy to go into the CDK-vs-script split if anyone's facing the same call.

### r/QuantifiedSelf

> **My sleep pillar was silently frozen for months because I was reading field
> names that stopped existing in 2024**
>
> I track sleep through Whoop and score it as one pillar of a composite. The
> pillar sat below my data-coverage floor for a long stretch and I read that as
> "my sleep data is patchy" — a data-quality problem, annoying but explicable.
>
> It wasn't. The engine was still reading pre-2024 field names. The data was
> arriving fine; I was looking in the wrong place, and my own system was
> reporting the resulting hole as a coverage limitation rather than a bug. The
> best-instrumented thing I measure was the thing I was most wrong about.
>
> What I'd tell anyone doing n-of-1 work: an "insufficient data" state in your
> own pipeline deserves the same suspicion as a surprising result. Mine was
> load-bearing for months and I never questioned it, because a null reads as
> honest.

### r/artificial

> **I made my system grade its own predictions in public, and the scoreboard is
> currently empty**
>
> I have LLM-generated coaching that makes forward-looking calls about my own
> data. Rather than let those evaporate, I log every one and score it with a
> Brier score on a public page.
>
> Right now every score reads "insufficient data," because the ledger restarts
> at each experiment genesis and no call has come due yet. I shipped it anyway,
> empty, with the emptiness explained on the page — because the alternative was
> to wait until the numbers looked good, and a scoreboard you only publish once
> it flatters you isn't a scoreboard.
>
> The thing I actually learned building it: a separate sweep of 112 stored
> narratives found ~10% contained hard contradictions with the canonical facts.
> A grounding gate now kills invented numbers, but embellishment that uses no
> numbers at all still gets through. I don't have a good answer for that one yet.

Note what all three do: name a specific mechanism, admit something, and end
without a call to action.

---

## 6. Grading

**Upvotes are not the metric.** A post's value is measured in **confirmed
subscribers attributable to it** — the UTM and source attribution wired by
**#1621**. Until that story ships, grading is honestly unavailable and this
section is aspirational; say so rather than substituting vanity numbers.

Log each post in the build log or a running note with:

- date, sub, title, and the permalink
- the sidebar rules as read that day (§2)
- traffic in the following 7 days, from the traffic digest
- **confirmed subscribers attributed to the post** (once #1621 lands)
- a one-line honest read: did this earn attention or spend credibility?

A post that draws 2,000 visitors and zero subscribers is a **failure worth
recording as one** — it means the post traveled and the site didn't convert, and
that is a site problem, not a reason to post more. This is the same discipline
the platform applies to its own predictions: graded, in public, including the
misses.

---

## Related

- `docs/PLATFORM_NORTH_STAR.md` — the four audiences; Reddit newcomers are #1
- `docs/content/BUILD_DISPATCH_CHECKLIST.md` — how build beats are written (the raw material)
- `site/story/build/beats.json` — the 57 beats themselves
- **#1621** — subscriber attribution, the grading dependency
- **#1622** — the manual poster script, on a 30-day Phase 0 trial (a *drafting aid*, not an autoposter; it does not change §0)
- **#1619** — the social distribution epic
