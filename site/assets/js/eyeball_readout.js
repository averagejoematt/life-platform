(function () {
  var MACRO_LABELS = { calories: "Calories", protein_g: "Protein", carbs_g: "Carbs", fat_g: "Fat" };
  var root = document.getElementById("eb-readout");
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]; }); }
  function el(html){ var d=document.createElement("div"); d.innerHTML=html; return d.firstElementChild; }
  function emptyState(a){
    return '<div class="eb-state eb-empty" data-readout data-state="empty">' +
      '<p><strong>No graded photos yet.</strong> Nothing has been eyeballed and graded, so there is no error to report ' +
      '(n = 0). This chart fills in only as real meal photos are estimated and checked against the logged day — ' +
      'it will never show a made-up accuracy number.</p></div>';
  }
  function bar(label, mape){
    var pct = Math.max(0, Math.min(100, mape));
    return '<div class="eb-bar-row"><span class="eb-bar-label">' + esc(label) + '</span>' +
      '<span class="eb-bar-track"><span class="eb-bar-fill" style="width:' + pct.toFixed(1) + '%"></span></span>' +
      '<span class="eb-bar-val">' + mape.toFixed(1) + '% MAPE</span></div>';
  }
  function macroCard(key, cell){
    var name = MACRO_LABELS[key] || key;
    if (!cell || !cell.sufficient) {
      var n = (cell && cell.n) || 0;
      return '<div class="eb-macro"><h3>' + esc(name) + '</h3>' +
        '<div class="eb-lown">n = ' + n + ' — too few to score yet. Stats are withheld until there are enough graded days ' +
        '(honest low-n; no precision claimed on thin data).</div></div>';
    }
    var body = '<div class="eb-macro"><h3>' + esc(name) + '</h3>' +
      '<div class="eb-n">n = ' + cell.n + ' graded days</div>' +
      bar("Mean abs err", cell.mape_pct) +
      '<div class="eb-bar-row"><span class="eb-bar-label">Median</span><span></span>' +
        '<span class="eb-bar-val">' + cell.median_abs_pct.toFixed(1) + '%</span></div>' +
      '<div class="eb-bar-row"><span class="eb-bar-label">Bias</span><span></span>' +
        '<span class="eb-bar-val">' + (cell.bias_pct > 0 ? "+" : "") + cell.bias_pct.toFixed(1) + '% (' +
          (cell.bias_pct > 0 ? "over" : (cell.bias_pct < 0 ? "under" : "no bias")) + ')</span></div>';
    if (cell.trend) {
      body += '<p class="eb-trend">Trend: ' + esc(cell.trend.direction) + ' — recent ' +
        cell.trend.recent_mape_pct.toFixed(1) + '% vs earlier ' + cell.trend.earlier_mape_pct.toFixed(1) + '%.</p>';
    }
    return body + '</div>';
  }
  function render(a){
    if (!a || a.state === "empty" || a.n_days === 0) { root.appendChild(el(emptyState(a))); return; }
    var wrap = el('<div class="eb-state" data-readout data-state="' + esc(a.state) + '"></div>');
    var head = '<p class="eb-n" style="font-family:var(--font-mono);color:var(--ink-faint)">' +
      a.n_days + ' graded day' + (a.n_days === 1 ? "" : "s") + ' &middot; as of ' + esc(a.as_of || "") +
      (a.state === "low_n" ? ' &middot; low-n: summary stats withheld below the threshold of ' + esc(a.min_n) : '') + '</p>';
    wrap.innerHTML = head + '<div class="eb-grid">' +
      Object.keys(MACRO_LABELS).map(function(k){ return macroCard(k, (a.macros||{})[k]); }).join("") + '</div>';
    root.appendChild(wrap);
  }
  fetch('/data/eyeball_calibration.json', { cache: "no-store" })
    .then(function(r){ if (!r.ok) throw new Error("no artifact"); return r.json(); })
    .then(render)
    .catch(function(){ root.appendChild(el(emptyState(null))); });
})();
