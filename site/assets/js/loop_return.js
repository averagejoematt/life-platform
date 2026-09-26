/*
  loop_return.js — dates the loop close's return trigger (#4182, A-grade sweep fix 1).
  ----------------------------------------------------------------------------
  Every chrome-bearing page closes with scripts/v4_chrome.loop_forward(). Its "or come
  back" line used to say "follow by email for the next entry" — a return trigger with no
  date in it. The static copy now names the weekly cadence; this module swaps the
  `[data-next-writeup]` span for the dated line, from the SAME served fields the story
  door reads (/api/content_cadence `chronicle.next_date`, and the held-draft `pending`
  marker on /journal/posts.json) through entry_age.js::loopReturnText. Any fetch failure
  leaves the static copy in place — never an invented date.
*/
import { loopReturnText } from "/assets/js/entry_age.js";

async function getJSON(url) {
  try {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

async function run() {
  const slot = document.querySelector(".loop-forward [data-next-writeup]");
  if (!slot) return;
  const [cad, pj] = await Promise.all([getJSON("/api/content_cadence"), getJSON("/journal/posts.json")]);
  const t = loopReturnText(cad, pj && pj.pending);
  if (t) slot.textContent = t;
}

run();
