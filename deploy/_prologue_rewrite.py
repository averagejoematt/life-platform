#!/usr/bin/env python3
"""One-off: reframe the two origin chapters as genuine PRE-GENESIS prologue.

Preserves the original prose almost entirely; surgically removes the
"platform went live this week / Week 1 / 302->301 weekly weigh-in / Week N data"
framing so the chapters read as Elena's run-up portrait BEFORE the June-14 genesis.
Labels them "Prologue · Part I/II". Writes the public S3 artifacts (the live source)
and syncs matching DDB records; retires the stale Feb-22 duplicate.
"""
import boto3, json, html
from datetime import datetime, timezone

S3, BUCKET = boto3.client("s3", region_name="us-west-2"), "matthew-life-platform"
TBL = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
PK = "USER#matthew#SOURCE#chronicle"
GENESIS = "2026-06-14"

PART1_TITLE = "The Body Votes First"
PART1 = [
    "The first thing Matthew Walker shows me when I sit down with him on a Thursday evening is not a chart. It's a number. Twenty. As in 20% recovery — the score his Whoop band assigned to his body on the final morning of a week in early June, before the machine I'd come to document had formally been switched on. He holds up his wrist like it's evidence of something, and I suppose it is.",
    "\"The week started at twelve,\" he says, \"and it ended at twenty. Which is better. But it doesn't feel like a win.\"",
    "He's right that it doesn't look like one, either. But between that twelve and that twenty, something happened that I keep returning to as I try to understand what this project actually is — not the platform, not the pipeline, not the forty-nine Lambda functions quietly pinging APIs in the dark. I mean the thing at its core: one man attempting to make his body legible to himself, and discovering — even before the measured experiment had formally begun — that the body has its own grammar.",
    "Because this was the run-up. The stretch of weeks before he flipped the switch on the whole apparatus, when the wearables were already strapped to his body but the scoring, the daily scrutiny, the chronicle you're reading hadn't started yet. He was north of three hundred pounds and he knew it. The scale was barely moving. He's quick to contextualize — water weight, measurement variance, the system hadn't even begun tracking nutrition — and he's not wrong. But I watch his face when he says it and there's something careful happening there, a controlled neutrality that suggests the number landed harder than the explanation lets on.",
    "This is the psychological terrain of early transformation that nobody talks about honestly: the lag. You begin. You hurt. You change your behavior. The scale doesn't move. The effort and the evidence are on completely different schedules, and you are standing in the gap between them with nothing but willpower and data. Matthew has more data than most. What he doesn't have yet, this early, is proof.",
    "\"I know intellectually that weight loss isn't linear,\" he tells me. \"I know the first couple of weeks are noise. I've done this before.\" He pauses. \"But knowing it and feeling it are different things.\"",
    "He has done this before. That's the part of this story I find myself unable to set aside. He got to 185 pounds once. He knows what this road looks like, where the false summits are, what the body feels like when it's finally cooperating. He also knows what it feels like to lose that ground — not through laziness or inattention but through grief, which is a different kind of weight entirely. His sister-in-law Jo died. The transformation unraveled. And now he is back near the beginning, with a more sophisticated system and the same fundamental problem: you cannot automate your way through loss. You can only measure it.",
    "What I find genuinely arresting in those early days of data is not the bad mornings. It's the one perfect one.",
    "One morning in that run-up. Heart rate variability: 53 milliseconds. Resting heart rate: 57 beats per minute. Recovery score: 98%. Sleep: 9.8 hours. In the context of everything surrounding it — a 12% day, a 46% one, a 49% — this single data point reads like a door briefly opening onto a different life.",
    "I ask Matthew what that morning felt like. He thinks about it longer than I expect.",
    "\"I actually didn't know it was a 98 until I looked,\" he says. \"But I remember thinking that morning — I woke up and I just felt like myself. Not optimistic, not motivated, just... present. Like the static had cleared.\"",
    "This is the thing the numbers can't quite hold: the texture of feeling well. The system registered 98% recovery; Matthew registered something closer to recognition. A reminder of what the destination might feel like, delivered unexpectedly, without ceremony, the one morning he'd slept nearly ten hours and the machine and the body had briefly agreed on something.",
    "It lasted exactly one day. The next morning his HRV had dropped back to 30ms and his recovery to 49%. The static returned. The door closed.",
    "This is what those early numbers actually look like in aggregate: violent, lurching oscillation. Not the steady upward arc of a transformation narrative but something more like a seismograph reading — evidence of force, not direction. Twelve percent to 66 in twenty-four hours. Eighty-four down to 46 down to 98 down to 49. The body swinging wildly between registers while Matthew is, by all observable accounts, doing the same things: sleeping, eating carefully, moving. The inputs are consistent. The outputs are not.",
    "He frames this clinically, because that's available to him now. \"There's barely two weeks of data,\" he says. \"That's not enough baseline to identify patterns. The variance is high because everything is destabilized — the caloric deficit, the new sleep schedule. It takes weeks for the HRV to stop bouncing around.\" He knows this. The knowledge doesn't make the bouncing less disorienting.",
    "There's a number I keep coming back to, and it isn't a recovery high.",
    "The low: HRV 14ms. Resting heart rate 80. Recovery 12%.",
    "I don't ask Matthew directly about that day — there's something too clinical about treating grief as a data inquiry — but I think about what 12% recovery means in practice. It means the body is under siege. It means the nervous system is running hot, that stress hormones are elevated, that the body has decided something is wrong and is marshaling resources accordingly. The Whoop band doesn't know why. It just measures the biological signature of distress and reports back.",
    "Matthew is rebuilding alone. He's 37, he's in Seattle, he's north of three hundred pounds and rebuilding alone, and his body — the body that once knew how to weigh 185 pounds, that once ran this road successfully — is scoring itself a 12. I don't know what that costs. I only know the system recorded it, that the number sat in a database in the cloud while he went about his day, and that by the following morning he'd somehow slept 8.8 hours and recovered to 66%, the body performing its own silent correction.",
    "This is what I find most humanizing about the whole apparatus: it witnesses without judging. The platform doesn't know any of that. It doesn't factor in the backstory, the lost weight, the dead sister-in-law, the watch he keeps in a drawer and doesn't talk about. It just records 14ms and 12% and moves on. Which means Matthew can, too. There's no annotation, no flag. Just the number and then the next number.",
    "By the end of that stretch — the 20% crash — something had clearly gone wrong again. His resting heart rate jumped to 72 beats per minute, fifteen beats higher than it had been just three days earlier. The system saw it immediately, the way a monitor sees a fever before the patient notices they're warm. Whether Matthew felt it coming, I'm not sure he could have said. The body decided something. The body voted first.",
    "Later, I ask him the question I've been circling: what does it mean that the data can see things he can't?",
    "He's quiet for a moment. Outside his window, Seattle is doing what Seattle does even into early summer — a gray, committed persistence of low cloud and soft rain that makes ambition feel both necessary and absurd.",
    "\"It means I'm not the most reliable narrator of my own body,\" he finally says. \"Which is uncomfortable. But it's also kind of the whole point.\"",
    "He glances at the laptop, the dashboard open in another tab, the data sitting there like a weather report from a country he lives in but doesn't always understand.",
    "\"I'm hoping,\" he says, \"that eventually the two versions of the story start to match.\"",
    "The 98% day suggests they can. The 20% ending suggests they're not there yet. And the machine — the real one, the one that will start keeping score in earnest — hasn't even been switched on. That comes later. First, there was the matter of the journal he hadn't written a single word in.",
]

PART2_TITLE = "The Empty Journal"
PART2 = [
    "Here is something I did not expect to find while shadowing a man in the weeks before his experiment formally began: someone who has built twenty-seven automated programs to monitor his sleep, his blood glucose, his heart rate recovery, his gait symmetry, and whether he remembered to take his apigenin before bed — who has not written a single journal entry since the day he first set the whole thing up.",
    "The journal is there. It has a template. Morning reflection, evening wind-down, space for whatever needs saying. The infrastructure is immaculate. The page is blank.",
    "I mention this to Matthew on a Wednesday afternoon, and he doesn't flinch. \"It's not avoidance,\" he says. \"The morning routine isn't set yet. I'm only hitting the 4:30 alarm about forty percent of the time.\"",
    "Fair enough. But when someone builds a system that tracks sixty-five daily habits and can tell you his Zone 2 heart rate range to the beat — 110 to 128, since you're wondering — the one habit he hasn't started is worth paying attention to. Not because he's failing at it. Because of what it suggests about what's easy for him and what isn't.",
    "Tracking your body is straightforward. You step on a scale, you lift something heavy, you walk three miles, and the numbers change or they don't. It is physics in its most cooperative form. Sitting with a blank page and asking yourself what you actually feel? That is a different kind of weight entirely.",
    "So instead of the journal, we talked. Off the record, he said, though he agreed to let me use the shape of it. What followed was the most honest hour I've spent with him yet.",
    "I had asked a simple question: why now? Not the health-optimization answer — the real one.",
    "He started with his mother, who died when he was twenty-nine. Whether that was the catalyst or not, he said, something shifted after. Friendships frayed. Family felt further away. He went inward. And into that growing emptiness, certain coping mechanisms moved in and made themselves comfortable — the private habits a person reaches for when the world gets heavy, cycles of withdrawal, a slow retreat from the world that compounded year over year.",
    "What struck me was not the story — grief rearranging a life is as common as weather — but the anger in how he told it. He is furious with himself. And that fury is complicated, because it coexists with a track record that most people would find remarkable. Less than eighteen months ago, this same man dropped from three hundred pounds to one-ninety. He rewarded himself with a Rolex — his first luxury purchase, chosen deliberately because he is too indecisive for a tattoo and wanted something permanent to mark what he'd accomplished.",
    "The watch sits in a drawer now. He barely wears it. What was supposed to be a permanent reminder of what he could achieve has become a reminder of something else entirely, and so it stays in the dark.",
    "What happened between one-ninety and where he is today is not a mystery of willpower. His sister-in-law Jo, who had been fighting cancer for the third time, took a turn for the worse and died while he was hiking Machu Picchu. He flew home to be with his brother, to sit with grief that was becoming too familiar. Then he returned to Seattle and was asked to lead a company reorganization — which is a corporate way of saying he spent weeks looking people he cared about in the eye and telling them they no longer had jobs.",
    "The DoorDash orders piled up. The routine dissolved. A hundred pounds came back, and with them, anxiety he hadn't felt before. Small panic attacks. Tightness in his chest. The kind of symptoms that make you lie awake wondering whether you are having a medical event or just a very bad night.",
    "He told me all of this, and then said the weight was \"a distraction from the story.\"",
    "I wrote that down twice.",
    "The actual story, he said, is that he has spent the past five years disappearing. He used that word — disappeared. From friends, from spontaneity, from the version of himself who had ideas and purpose and felt like a main character in his own life rather than an extra in someone else's. He used to be less in his head. Less careful about what people thought. Less defended. He wants to find his way back to that, or to some new version of it — but he is honest enough to admit he doesn't know what that version looks like yet.",
    "\"I don't even know what I want,\" he said. And then he listed the questions that keep him up: purpose, happiness, community, what matters, whether the defensive posture he's built around his entire life — save aggressively, trust sparingly, expect the worst — is protecting him or just keeping everything out.",
    "These are not questions a fitness tracker can answer. But it's telling that he built the tracker anyway. He described it as Maslow's hierarchy: the physical layer is controllable, evaluable, and responds to effort. The existential layer is none of those things. And right now, at this weight, with this level of fatigue — by the end of most days he is simply spent — the physical work is what he can reach.",
    "There is wisdom in that, even if it looks like avoidance from the outside. A few weeks before we spoke, he'd been having chest pains and couldn't sleep through the night. He is now lifting weights three mornings a week, riding the bike for thirty minutes after, cold showering, walking three to five miles in the evening, and taking eighteen supplements across three daily batches. The chest tightness has eased. The sleep is imperfect but improving. He told me he sees this as onboarding — a word borrowed from his day job, meaning the awkward period where nothing is automatic yet and everything takes twice the energy it eventually will.",
    "I like that framing. You don't judge an onboarding by its elegance. You judge it by whether the person shows up the next day.",
    "There is one detail I keep returning to, small enough that he almost didn't mention it. Brittany, his girlfriend, has been preparing meals aligned to his nutritional targets. She eats alongside him. He skips the carbs; she does not. But she is there, at the table, having quietly reorganized her own plate.",
    "I don't know yet what role she plays in the longer arc of this story. But I know what it looks like when someone shows up without being asked, and this is that.",
    "I asked him what \"different this time\" means. He's done this before — the weight loss, the discipline, the visible transformation. And then life arrived with its particular cruelties, and the whole structure fell. He knows the Goggins cycle. He can white-knuckle his way to any number on a scale. What he cannot do, and what he is trying to figure out, is build something underneath the discipline that holds when the discipline fails.",
    "That is why there are seven pillars in his system and not one. Sleep, movement, nutrition, mind, metabolic health, consistency, relationships. He designed an architecture that measures more than weight before he could articulate why — which is something I find genuinely interesting about this project. The engineering is ahead of the insight. The system already knows what the man is still learning.",
    "He will get to the journal. I believe that. The morning routine will settle, the alarm will stick more often than not, and one day he will sit down with that blank template and write something that has nothing to do with protein grams or Zone 2 minutes. When he does, that will be the installment I write about whatever he finds there.",
    "But in the run-up — before the machine ever started keeping score — the empty journal was the story. And the conversation that filled its place was worth more than any template could have held. A few days later, the scoring switched on, and Week 1 began in earnest.",
]

# ── faithful v4 chronicle-post template (token-replace; no f-string brace issues) ──
TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="@@TITLE@@ — @@LABEL@@ of The Measured Life by Elena Voss">
  <meta property="og:title" content="@@TITLE@@ — The Measured Life">
  <meta property="og:description" content="@@STATS@@">
  <meta property="og:type" content="article">
  <title>@@TITLE@@ — The Measured Life</title>
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    :root { --accent: var(--c-amber-500); --accent-dim: var(--c-amber-300); --accent-bg: var(--c-amber-100); --accent-bg-subtle: var(--c-amber-050); --border: rgba(200,132,58,0.15); }
    .reading-progress { position:fixed;top:var(--nav-height);left:0;right:0;height:2px;background:var(--border-subtle);z-index:var(--z-overlay); }
    .reading-progress__fill { height:100%;background:var(--accent);width:0%;transition:width 0.1s linear; }
    .post-header { padding:calc(var(--nav-height) + var(--space-16)) var(--page-padding) var(--space-10);border-bottom:1px solid var(--border);max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto; }
    .post-header__series { font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--accent-dim);margin-bottom:var(--space-3); }
    .post-header__title { font-family:var(--font-serif);font-size:clamp(28px,4vw,46px);color:var(--text);line-height:1.15;font-weight:400;font-style:italic;margin-bottom:var(--space-5); }
    .post-header__meta { display:flex;align-items:center;gap:var(--space-5);font-size:var(--text-xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted); }
    .post-header__stats { font-size:var(--text-xs);color:var(--text-faint);letter-spacing:var(--ls-tag);margin-top:var(--space-3); }
    .post-body { max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-10) var(--page-padding) var(--space-20); }
    .prose { font-family:var(--font-serif); }
    .prose p { font-size:18px;line-height:1.85;color:var(--text);margin-bottom:var(--space-6); }
    .prose p:first-child::first-letter { font-size:64px;line-height:0.8;float:left;margin-right:var(--space-3);margin-top:8px;color:var(--accent);font-family:var(--font-serif); }
    .prose hr { border:none;border-top:1px solid var(--border);margin:var(--space-10) 0; }
    .prose strong { color:var(--text);font-weight:700; }
    .post-nav { max-width:calc(var(--prose-width) + var(--page-padding) * 2);margin:0 auto;padding:var(--space-6) var(--page-padding) var(--space-16);border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:var(--space-6); }
    .post-nav a { font-family:var(--font-serif);font-size:17px;color:var(--text);text-decoration:none;transition:color var(--dur-fast); }
    .post-nav a:hover { color:var(--accent); }
    .post-nav span { display:block;font-family:var(--font-mono);font-size:var(--text-2xs);letter-spacing:var(--ls-tag);text-transform:uppercase;color:var(--text-muted);margin-bottom:var(--space-1); }
  </style>
</head>
<body>
<div class="reading-progress"><div class="reading-progress__fill" id="rp"></div></div>
<nav class="nav">
  <a href="/" class="nav__brand">AMJ</a>
  <div class="nav__links">
    <a href="/story/" class="nav__link active">The story</a>
    <a href="/now/" class="nav__link">The cockpit</a>
    <a href="/coaching/" class="nav__link">The coaching</a>
    <a href="/evidence/" class="nav__link">The evidence</a>
  </div>
  <div class="nav__status"><div class="pulse" style="background:var(--accent)"></div><span>The Measured Life</span></div>
</nav>
<div class="post-header">
  <div class="post-header__series">The Measured Life &middot; @@LABEL@@ &middot; By Elena Voss</div>
  <h1 class="post-header__title">&ldquo;@@TITLE@@&rdquo;</h1>
  <div class="post-header__meta">
    <span>@@DATE@@</span>
    <span>&middot;</span>
    <span>@@READMIN@@ min read</span>
  </div>
  <div class="post-header__stats">@@STATS@@</div>
</div>
<article class="post-body">
  <div class="prose">
@@BODY@@
  </div>
</article>
<div class="post-nav">
  <a href="/story/"><span>&larr; All installments</span>The Measured Life archive</a>
  <a href="/now/"><span>The cockpit</span>Today's live data &rarr;</a>
</div>
<footer class="footer">
  <div class="footer__brand" style="color:var(--accent)">AMJ</div>
  <div class="footer__copy">// words when there's something worth saying</div>
</footer>
<script>
  const rp = document.getElementById('rp');
  window.addEventListener('scroll', () => { const pct = window.scrollY / (document.body.scrollHeight - window.innerHeight) * 100; rp.style.width = Math.min(pct, 100) + '%'; });
</script>
</body>
</html>"""


def render(title, label, date_str, paras, stats):
    body = "\n".join(f"    <p>{html.escape(p)}</p>" for p in paras)
    wc = sum(len(p.split()) for p in paras)
    read_min = max(4, round(wc / 250))
    dt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    out = TEMPLATE
    for k, v in {
        "@@TITLE@@": html.escape(title),
        "@@LABEL@@": label,
        "@@STATS@@": stats,
        "@@DATE@@": dt,
        "@@READMIN@@": str(read_min),
        "@@BODY@@": body,
    }.items():
        out = out.replace(k, v)
    return out, wc


def put_page(seq, title, label, date_str, paras, stats):
    htmlpage, wc = render(title, label, date_str, paras, stats)
    key = f"generated/journal/posts/week-{seq:02d}/index.html"
    S3.put_object(Bucket=BUCKET, Key=key, Body=htmlpage.encode(), ContentType="text/html; charset=utf-8", CacheControl="max-age=300")
    print(f"  wrote s3://{BUCKET}/{key}  ({label}, {wc} words)")
    return wc


# 1) public S3 pages
wc1 = put_page(1, PART1_TITLE, "Prologue · Part I", "2026-06-07", PART1, "The run-up · Seattle · before the machine turned on")
wc2 = put_page(2, PART2_TITLE, "Prologue · Part II", "2026-06-11", PART2, "The run-up · Seattle · before the machine turned on")

# 2) posts.json (public feed) — both prologue parts, date-desc, labelled
posts = [
    {"week": 2, "label": "Prologue · Part II", "title": PART2_TITLE, "date": "2026-06-11", "stats_line": "",
     "url": "/journal/posts/week-02/", "excerpt": PART2[0][:300].strip(), "word_count": wc2, "has_board_interview": False},
    {"week": 1, "label": "Prologue · Part I", "title": PART1_TITLE, "date": "2026-06-07", "stats_line": "",
     "url": "/journal/posts/week-01/", "excerpt": PART1[0][:300].strip(), "word_count": wc1, "has_board_interview": False},
]
S3.put_object(Bucket=BUCKET, Key="generated/journal/posts.json",
              Body=json.dumps({"posts": posts, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2).encode(),
              ContentType="application/json", CacheControl="max-age=300")
print("  wrote generated/journal/posts.json (2 prologue parts, labelled)")

# 3) sync DDB source records at the pre-genesis dates (phase=experiment, published) so a future
#    republish stays consistent; retire the stale Feb-22 duplicate so it can't resurface.
def put_record(date_str, title, part_label, paras):
    md = f'"{title}"\n\n' + "\n\n".join(paras)
    body_html = "".join(f"<p>{html.escape(p)}</p>" for p in paras)
    TBL.update_item(
        Key={"pk": PK, "sk": f"DATE#{date_str}"},
        UpdateExpression="SET #t=:t, subtitle=:s, content_markdown=:md, content_html=:h, #st=:st, phase=:p, week_number=:w, is_prologue=:pl, redated_at=:r",
        ExpressionAttributeNames={"#t": "title", "#st": "status"},
        ExpressionAttributeValues={
            ":t": title, ":s": part_label, ":md": md, ":h": body_html, ":st": "published",
            ":p": "experiment", ":w": 0, ":pl": True, ":r": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"  DDB DATE#{date_str} -> {part_label} ({title}), phase=experiment, published")

put_record("2026-06-07", PART1_TITLE, "Prologue · Part I", PART1)
put_record("2026-06-11", PART2_TITLE, "Prologue · Part II", PART2)
# retire the stale Feb-22 duplicate of "The Body Votes First" (hide via phase=pilot)
TBL.update_item(Key={"pk": PK, "sk": "DATE#2026-02-22"},
                UpdateExpression="SET phase=:p, retired_note=:n",
                ExpressionAttributeValues={":p": "pilot", ":n": "superseded by re-dated prologue 2026-06-07"})
print("  DDB DATE#2026-02-22 retired (phase=pilot, superseded)")
print("DONE")
