/* #2574 — fill the permanence panel from the published archive documents.
   Two rules, both ADR-104: never render a number that was not read, and
   never let the terms depend on the fetch — the clause list is static and
   stands whether or not these two documents answer. */
(function(){
  var panel = document.getElementById("perm-live");
  if (!panel) return;
  var slot = function(name){ return panel.querySelector('[data-perm="' + name + '"]'); };
  var ABSENT = "not available";

  function absent(name){
    var el = slot(name);
    if (!el) return;
    el.textContent = ABSENT;
    el.setAttribute("data-absent", "1");
  }
  function fill(name, value){
    var el = slot(name);
    if (!el) return;
    if (value === null || value === undefined || value === "") { absent(name); return; }
    el.textContent = value;
    el.removeAttribute("data-absent");
  }
  function note(text){
    var el = slot("note");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
  }
  function mib(bytes){
    if (typeof bytes !== "number" || !isFinite(bytes) || bytes < 0) return null;
    if (bytes < 1024) return bytes + " bytes";
    var mb = bytes / (1024 * 1024);
    return mb >= 1 ? mb.toFixed(1) + " MB" : (bytes / 1024).toFixed(0) + " KB";
  }
  function stamp(iso){
    if (typeof iso !== "string" || !iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var p = function(n){ return String(n).padStart(2, "0"); };
    return d.getUTCFullYear() + "-" + p(d.getUTCMonth() + 1) + "-" + p(d.getUTCDate()) +
           " " + p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()) + " UTC";
  }
  function getJSON(url){
    return fetch(url, { cache: "no-store" }).then(function(r){
      if (!r.ok) throw new Error(url + " " + r.status);
      return r.json();
    });
  }

  function plural(n, word){ return n + " " + word + (n === 1 ? "" : "s"); }

  // Two failure classes, kept apart on purpose. "unreadable" is a document
  // that did not answer; "incomplete" is a document that answered 200 with
  // a shape this panel cannot state a number from — a half-written nightly.
  // Both must SAY so: an unexplained absence reads as an empty box, and an
  // empty box reads as zero.
  var unreadable = [];
  var incomplete = [];
  var mismatch = null;

  var manifest = getJSON("/archive/manifest.json").then(function(m){
    if (!m || typeof m !== "object") throw new Error("manifest: not an object");
    var arc = (m.archive && typeof m.archive === "object") ? m.archive : {};
    var built = stamp(m.generated_at);
    var size = mib(arc.bytes);
    var count = typeof m.entry_count === "number" ? plural(m.entry_count, "file") : null;
    var sha = (typeof arc.sha256 === "string" && arc.sha256) ? arc.sha256 : null;
    fill("built", built);
    fill("bytes", size);
    fill("entries", count);
    fill("sha", sha);
    if (built === null || size === null || count === null || sha === null) incomplete.push("the manifest");
  }).catch(function(){
    ["built", "bytes", "entries", "sha"].forEach(absent);
    unreadable.push("the manifest");
  });

  var continuity = getJSON("/archive/continuity.json").then(function(c){
    if (!c || typeof c !== "object") throw new Error("continuity: not an object");
    var days = typeof c.days_silent === "number" ? c.days_silent : null;
    var state = typeof c.state === "string" ? c.state : null;
    if (state === null) { absent("state"); incomplete.push("the continuity clock"); }
    else if (c.measurement_failed || state === "unknown") { fill("state", "not measured on the last run"); }
    else { fill("state", state + (days === null ? "" : " · " + plural(days, "day") + " since the last signal")); }

    var live = (c.terms && typeof c.terms.version === "string") ? c.terms.version : null;
    var list = document.querySelector(".perm-clauses");
    var built = list ? list.getAttribute("data-built-version") : null;
    fill("version", live);
    if (live === null && incomplete.indexOf("the continuity clock") === -1) incomplete.push("the continuity clock");
    if (live && built && live !== built) {
      mismatch = "The published edition of these terms is " + live + ", but the clauses on this page were rendered from edition " +
                 built + ". Read the published document as authoritative until this page catches up.";
    }
  }).catch(function(){
    absent("state");
    absent("version");
    unreadable.push("the continuity clock");
  });

  Promise.all([manifest, continuity]).then(function(){
    // Every reachable state gets its own sentence, and they compose — an
    // edition mismatch must not swallow the reason four numbers are blank.
    var lines = [];
    if (unreadable.length) {
      var line = "Could not read " + unreadable.join(" or ") + " just now, so those numbers are shown as unavailable rather than guessed.";
      // Hedge about the download ONLY when the manifest is what failed. If
      // the manifest answered, this panel has just published the archive's
      // build time, size and checksum — warning that the download may not
      // answer would contradict evidence the page is itself showing.
      if (unreadable.indexOf("the manifest") !== -1) {
        line += " The download address above is fixed and does not move, but it may not answer either until the next nightly build.";
      }
      lines.push(line);
    }
    if (incomplete.length) {
      lines.push("The last published copy of " + incomplete.join(" and ") + " did not carry every number this panel states, so the missing ones are left unavailable rather than filled in.");
    }
    if (mismatch) lines.push(mismatch);
    if (lines.length) note(lines.join(" "));
  });
})();
