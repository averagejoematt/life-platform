#!/usr/bin/env python3
"""
restore_week02.py — Overwrite week-02.html with the correct "The Empty Journal" content.

The file was previously overwritten with "The Week Everything Leveled Up" content.
This restores the correct article.
"""

import boto3

REGION    = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CF_DIST   = "E1JOC1V6E6DDYI"

s3 = boto3.client("s3", region_name=REGION)
cf = boto3.client("cloudfront", region_name=REGION)

body_html = """<p>Here is something I did not expect to find two weeks into this assignment: a man who has built twenty-seven automated programs to monitor his sleep, his blood glucose, his heart rate recovery, his gait symmetry, and whether he remembered to take his apigenin before bed — who has not written a single journal entry since the day he started.</p>

<p>The journal is there. It has a template. Morning reflection, evening wind-down, space for whatever needs saying. The infrastructure is immaculate. The page is blank.</p>

<p>I mention this to Matthew on a Wednesday afternoon, and he doesn't flinch. "It's not avoidance," he says. "The morning routine isn't set yet. I'm only hitting the 4:30 alarm about forty percent of the time."</p>

<p>Fair enough. But when someone builds a system that tracks sixty-five daily habits and can tell you his Zone 2 heart rate range to the beat — 110 to 128, since you're wondering — the one habit he hasn't started is worth paying attention to. Not because he's failing at it. Because of what it suggests about what's easy for him and what isn't.</p>

<p>Tracking your body is straightforward. You step on a scale, you lift something heavy, you walk three miles, and the numbers change or they don't. It is physics in its most cooperative form. Sitting with a blank page and asking yourself what you actually feel? That is a different kind of weight entirely.</p>

<p>So instead of the journal, we talked. Off the record, he said, though he agreed to let me use the shape of it. What followed was the most honest hour I've spent with him yet.</p>

<p>I had asked a simple question: why now? Not the health-optimization answer — the real one.</p>

<p>He started with his mother, who died when he was twenty-nine. Whether that was the catalyst or not, he said, something shifted after. Friendships frayed. Family felt further away. He went inward. And into that growing emptiness, certain coping mechanisms moved in and made themselves comfortable. Binge eating, cycles of withdrawal, a slow retreat from the world that compounded year over year.</p>

<p>What struck me was not the story — grief rearranging a life is as common as weather — but the anger in how he told it. He is furious with himself. And that fury is complicated, because it coexists with a track record that most people would find remarkable. Less than eighteen months ago, this same man dropped from three hundred pounds to one-ninety. He rewarded himself with a Rolex — his first luxury purchase, chosen deliberately because he is too indecisive for a tattoo and wanted something permanent to mark what he'd accomplished.</p>

<p>The watch sits in a drawer now. He barely wears it. What was supposed to be a permanent reminder of what he could achieve has become a reminder of something else entirely, and so it stays in the dark.</p>

<p>What happened between one-ninety and where he is today is not a mystery of willpower. His sister-in-law Jo, who had been fighting cancer for the third time, took a turn for the worse and died while he was hiking Machu Picchu. He flew home to be with his brother, to sit with grief that was becoming too familiar. Then he returned to Seattle and was asked to lead a company reorganization — which is a corporate way of saying he spent weeks looking people he cared about in the eye and telling them they no longer had jobs.</p>

<p>The DoorDash orders piled up. The routine dissolved. A hundred pounds came back, and with them, anxiety he hadn't felt before. Small panic attacks. Tightness in his chest. The kind of symptoms that make you lie awake wondering whether you are having a medical event or just a very bad night.</p>

<p>He told me all of this, and then said the weight was "a distraction from the story."</p>

<p>I wrote that down twice.</p>

<p>The actual story, he said, is that he has spent the past five years disappearing. He used that word — disappeared. From friends, from spontaneity, from the version of himself who had ideas and purpose and felt like a main character in his own life rather than an extra in someone else's. He used to be less in his head. Less careful about what people thought. Less defended. He wants to find his way back to that, or to some new version of it — but he is honest enough to admit he doesn't know what that version looks like yet.</p>

<p>"I don't even know what I want," he said. And then he listed the questions that keep him up: purpose, happiness, community, what matters, whether the defensive posture he's built around his entire life — save aggressively, trust sparingly, expect the worst — is protecting him or just keeping everything out.</p>

<p>These are not questions a fitness tracker can answer. But it's telling that he built the tracker anyway. He described it as Maslow's hierarchy: the physical layer is controllable, evaluable, and responds to effort. The existential layer is none of those things. And right now, at this weight, with this level of fatigue — by the end of most days he is simply spent — the physical work is what he can reach.</p>

<p>There is wisdom in that, even if it looks like avoidance from the outside. Two weeks ago, he was having chest pains and couldn't sleep through the night. He is now lifting weights three mornings a week, riding the bike for thirty minutes after, cold showering, walking three to five miles in the evening, and taking eighteen supplements across three daily batches. The chest tightness has eased. The sleep is imperfect but improving. He told me he sees this as onboarding — a word borrowed from his day job, meaning the awkward period where nothing is automatic yet and everything takes twice the energy it eventually will.</p>

<p>I like that framing. You don't judge an onboarding by its elegance. You judge it by whether the person shows up the next day.</p>

<p>There is one detail I keep returning to, small enough that he almost didn't mention it. Brittany, his girlfriend, has been preparing meals aligned to his nutritional targets. She eats alongside him. He skips the carbs; she does not. But she is there, at the table, having quietly reorganized her own plate.</p>

<p>I don't know yet what role she plays in the longer arc of this story. But I know what it looks like when someone shows up without being asked, and this is that.</p>

<p>I asked him what "different this time" means. He's done this before — the weight loss, the discipline, the visible transformation. And then life arrived with its particular cruelties, and the whole structure fell. He knows the Goggins cycle. He can white-knuckle his way to any number on a scale. What he cannot do, and what he is trying to figure out, is build something underneath the discipline that holds when the discipline fails.</p>

<p>That is why there are seven pillars in his system and not one. Sleep, movement, nutrition, mind, metabolic health, consistency, relationships. He designed an architecture that measures more than weight before he could articulate why — which is something I find genuinely interesting about this project. The engineering is ahead of the insight. The system already knows what the man is still learning.</p>

<p>He will get to the journal. I believe that. The morning routine will settle, the alarm will stick more often than not, and one day he will sit down with that blank template and write something that has nothing to do with protein grams or Zone 2 minutes. When he does, that will be the week I write about whatever he finds there.</p>

<p>But this week, the empty journal was the story. And the conversation that filled its place was worth more than any template could have held.</p>

<hr>

<p><em>Next week: The routine finds its legs — or doesn't. Elena checks the 4:30 AM data.</em></p>

<p class="signature">The Measured Life is a weekly series following one man's attempt to use data, discipline, and occasionally brutal honesty to close the gap between the person he is and the person he wants to become. New installments every Wednesday.<br><br>Elena Voss is a freelance journalist embedded with this project. She has unfettered access to all of Matthew's health data, and occasionally, to the things the data cannot measure.</p>"""

post_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>The Empty Journal — The Measured Life</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <a href="index.html" class="series-title">The Measured Life</a>
    <p class="byline">An ongoing chronicle by Elena Voss</p>
    <nav class="site-nav"><a href="index.html">Archive</a><a href="about.html">About</a></nav>
  </header>
  <main>
    <article>
      <h1>"The Empty Journal"</h1>
      <p class="meta">Week 2 &middot; March 3, 2026</p>
      <p class="stats">Week 2 | February 25 – March 3, 2026 | Seattle, WA</p>
      <div class="body">
        {body_html}
      </div>
    </article>
    <nav class="post-nav">
      <a href="week-00.html">&larr; Prologue</a>
      <a href="index.html">All installments</a>
    </nav>
  </main>
  <footer>
    <p>&copy; 2026 The Measured Life. A chronicle of one man's attempt to change.</p>
  </footer>
</body>
</html>"""

s3.put_object(
    Bucket=S3_BUCKET, Key="blog/week-02.html",
    Body=post_html.encode("utf-8"),
    ContentType="text/html", CacheControl="max-age=3600",
)
print("week-02.html restored with correct content")

cf.create_invalidation(
    DistributionId=CF_DIST,
    InvalidationBatch={
        "Paths": {"Quantity": 1, "Items": ["/week-02.html"]},
        "CallerReference": "restore-empty-journal-content",
    },
)
print("CloudFront invalidated — /week-02.html")
print("Done. The Empty Journal article is live.")
