(function(){
  // theme toggle parity with the doors
  var tb = document.querySelector(".theme-toggle");
  if (tb) tb.addEventListener("click", function(){
    var cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = cur === "light" ? "dark" : "light";
    try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {}
  });
})();

const params = new URLSearchParams(window.location.search);
const action = params.get('action');
const token = params.get('token');

// State marks come from the shared line-icon sprite (DESIGN_SYSTEM_V5 §8.1),
// never text dingbats: mail = incoming reading, check = confirmed, flatline = signal ends.
function stateIcon(sb, name) {
  const si = sb.querySelector('.si');
  if (si) si.innerHTML = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/assets/icons/icons.svg#i-' + name + '"></use></svg>';
}

if (action === 'confirmed') {
  document.getElementById('form-block').style.display = 'none';
  const sb = document.getElementById('success-block');
  sb.style.display = 'block';
  stateIcon(sb, 'check');
  sb.querySelector('.st').textContent = "You're in.";
  sb.querySelector('.sb').innerHTML = "Subscription confirmed. You'll get The Measured Life every Wednesday.<br><br><a href=\"/story/chronicle/\">Read the chronicle while you wait →</a>";
}
if (action === 'unsubscribed') {
  document.getElementById('form-block').style.display = 'none';
  const sb = document.getElementById('success-block');
  sb.style.display = 'block';
  stateIcon(sb, 'flatline');
  sb.querySelector('.st').textContent = 'Unsubscribed.';
  sb.querySelector('.sb').innerHTML = "You've been removed. No hard feelings.<br><br><a href=\"/\">← back to the experiment</a>";
}
if (action === 'confirm' && token) {
  fetch('/api/subscribe?action=confirm&token=' + encodeURIComponent(token))
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(() => { window.location.search = '?action=confirmed'; })
    .catch(() => { document.getElementById('form-status').textContent = 'Confirmation failed — try the link again.'; });
}
if (action === 'unsubscribe' && token) {
  fetch('/api/subscribe?action=unsubscribe&token=' + encodeURIComponent(token))
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(() => { window.location.search = '?action=unsubscribed'; })
    .catch(() => { document.getElementById('form-status').textContent = 'Error — try again.'; });
}

function setStatus(status, text, kind) {
  status.textContent = text;
  status.classList.toggle('is-error', kind === 'error');
  status.classList.toggle('is-info', kind === 'info');
}
document.getElementById('submit-btn').addEventListener('click', async () => {
  const btn = document.getElementById('submit-btn');
  if (btn.disabled) return;
  const emailEl = document.getElementById('email');
  const email = emailEl.value.trim();
  const src = document.getElementById('source-field').value.trim();
  const status = document.getElementById('form-status');
  if (!email || !email.includes('@')) {
    emailEl.setAttribute('aria-invalid', 'true');
    setStatus(status, 'Enter a valid email address.', 'error');
    emailEl.focus();
    return;
  }
  emailEl.setAttribute('aria-invalid', 'false');
  btn.disabled = true;
  setStatus(status, 'Sending…', 'info');
  try {
    const res = await fetch('/api/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // #1621: the measured UTM attribution captured on LANDING (anywhere on the
      // site) and carried in sessionStorage by the attribution module the canonical
      // footer loads. These are extra JSON fields — the currently deployed API
      // ignores unknown keys, so this page degrades gracefully if it ships first.
      body: JSON.stringify({ email, source: src || 'subscribe-page', ...(window.__ajmAttribution ? window.__ajmAttribution.payload() : {}) }),
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById('form-block').style.display = 'none';
      document.getElementById('success-block').style.display = 'block';
    } else {
      setStatus(status, data.error || 'Something went wrong — try again.', 'error');
    }
  } catch { setStatus(status, 'Network error — try again.', 'error'); }
  btn.disabled = false;
});
document.getElementById('email').addEventListener('input', e => {
  if (e.target.getAttribute('aria-invalid') === 'true' && e.target.value.includes('@')) {
    e.target.setAttribute('aria-invalid', 'false');
  }
});
document.getElementById('email').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('submit-btn').click();
});

// subscriber count (pluralised)
fetch('/api/sub_count').then(r => r.ok ? r.json() : null).then(d => {
  const line = document.getElementById('sub-count-line');
  // Below ~10, a raw "Join 1 person" reads as weak proof — lead with "be one of the first".
  if (line && d && d.count != null && d.count >= 10) {
    line.textContent = `Join ${d.count} people following the experiment.`;
  }
}).catch(() => {});
