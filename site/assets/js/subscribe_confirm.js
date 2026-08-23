(function () {
  var tb = document.querySelector(".theme-toggle");
  if (tb) tb.addEventListener("click", function () {
    var cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = cur === "light" ? "dark" : "light";
    try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {}
  });

  // The email-confirm API lands here with ?confirmed=true|already or
  // ?error=invalid_token|token_expired|server_error. The static markup above IS
  // the no-param state ("check your inbox"), so a no-JS/crawler view shows real
  // content; this script re-renders the card for the other states. State marks
  // come from the shared line-icon sprite (DESIGN_SYSTEM_V5 §8.1): mail =
  // incoming reading, check = confirmed, flatline = signal lost.
  var p = new URLSearchParams(location.search);
  var states = {
    "confirmed:true":      ["check", "You're in.", 'Subscription confirmed — The Measured Life lands every Wednesday.<br><br><a href="/story/chronicle/">Read the chronicle while you wait →</a>', "confirmed", "ok"],
    "confirmed:already":   ["check", "Already confirmed.", 'You were already on the list — nothing more to do.<br><br><a href="/story/chronicle/">Read the chronicle →</a>', "confirmed", "ok"],
    "error:invalid_token": ["flatline", "That link didn't check out.", 'The confirmation link is invalid — it may have been clipped by your email client.<br><br><a href="/subscribe/">Subscribe again →</a>', "invalid link", "err"],
    "error:token_expired": ["flatline", "That link expired.", 'Confirmation links are time-limited. Re-subscribe and a fresh one will land in your inbox.<br><br><a href="/subscribe/">Subscribe again →</a>', "link expired", "err"],
    "error:server_error":  ["flatline", "Something went wrong on our side.", 'Not you — us. Try the link again in a minute, or re-subscribe.<br><br><a href="/subscribe/">Back to subscribe →</a>', "server error", "err"],
    "none:none":           ["mail", "Check your inbox.", 'A confirmation email is on its way — click the link inside to lock in your subscription.<br><br>No email? Check spam, or <a href="/subscribe/">try again →</a>', "awaiting confirmation", "wait"],
  };
  var key = p.get("confirmed") ? "confirmed:" + p.get("confirmed")
          : p.get("error") ? "error:" + p.get("error")
          : "none:none";
  var s = states[key] || states["error:invalid_token"];
  document.getElementById("cc-icon").innerHTML =
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-' + s[0] + '"></use></svg>';
  document.getElementById("cc-title").textContent = s[1];
  document.getElementById("cc-body").innerHTML = s[2];
  document.getElementById("cc-state").textContent = s[3];
  document.getElementById("confirm-card").dataset.state = s[4];
})();
