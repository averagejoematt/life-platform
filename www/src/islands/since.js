// "Since your last visit" (2026-11-14) — a reason to come back that is substance, not tracking. The page carries the
// dated events it already publishes (chapters published, calls graded) as day numbers; this browser remembers ONE
// thing, the edition date it last saw, under a single localStorage key. Nothing is sent anywhere. Storage blocked or
// a first visit → the line stays hidden.
const KEY = "ajm.lastSeenDay";
const DAY = 864e5;
const words = (n) => new Date(n * DAY).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export function mount(root = document.querySelector("[data-since]")) {
  if (!root) return;
  const asOf = Number(root.dataset.asof);
  let events = [];
  try {
    events = JSON.parse(root.dataset.events || "[]");
  } catch {
    return;
  }
  let last = null;
  try {
    const v = localStorage.getItem(KEY);
    last = v == null ? null : Number(v);
    if (Number.isFinite(asOf)) localStorage.setItem(KEY, String(asOf));
  } catch {
    return;
  }
  if (last == null || !Number.isFinite(last) || !Number.isFinite(asOf) || last >= asOf) return;
  const fresh = events.filter((e) => e.d > last && e.d <= asOf);
  const chapters = fresh.filter((e) => e.k === "chapter");
  const right = fresh.filter((e) => e.k === "confirmed").length;
  const wrong = fresh.filter((e) => e.k === "refuted").length;
  const bits = [];
  if (chapters.length === 1) bits.push(`a new chapter, “${chapters[0].t}”`);
  else if (chapters.length > 1) bits.push(plural(chapters.length, "new chapter", "new chapters"));
  if (right + wrong) bits.push(`${plural(right + wrong, "coach call", "coach calls")} graded — ${right} right, ${wrong} wrong`);
  const text = root.querySelector("[data-since-text]");
  if (!text) return;
  text.textContent = bits.length
    ? `Since your last visit (${words(last)}): ${bits.join("; ")}.`
    : `Nothing new was published since your last visit (${words(last)}); the readings below moved on.`;
  const link = root.querySelector("[data-since-link]");
  if (link && chapters.length === 1 && chapters[0].u) {
    link.setAttribute("href", chapters[0].u);
    link.hidden = false;
  }
  root.hidden = false;
}

mount();
