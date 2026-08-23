(function () {
  var root = document.getElementById("tr-readout");
  function esc(s){ return String(s).replace(/[&<>\"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]; }); }
  function el(h){ var d=document.createElement("div"); d.innerHTML=h; return d.firstElementChild; }

  function provLine(a){
    var p = a.provenance || {};
    var bits = [];
    bits.push('<span class="pv-src">LLM-coded from journal text' + (p.model ? ' &middot; model ' + esc(p.model) : '') +
              (p.schema_version != null ? ' &middot; schema v' + esc(p.schema_version) : '') + '</span>');
    if (a.n_days > 0) bits.push('<span>' + a.n_themes + ' theme' + (a.n_themes===1?'':'s') + ' over ' + a.n_days +
              ' enriched day' + (a.n_days===1?'':'s') + '</span>');
    if (a.window && a.window.end) bits.push('<span>as of ' + esc(a.window.end) + '</span>');
    return '<p class="provenance">' + bits.join("") + '</p>';
  }

  function emptyState(a){
    return '<div class="tr-state tr-empty" data-readout data-state="empty">' +
      '<p><strong>The river has not started flowing yet.</strong> No enriched journal entries have been coded for this ' +
      'attempt, so there are no themes to chart (n = 0). This fills in only as real entries are written and enriched — ' +
      'it will never show a made-up shape.</p></div>';
  }

  function spark(series, gmax, glow){
    // series: weekly counts; gmax: shared max across all bands. Column sparkline.
    var W = 240, H = 54, n = series.length, gap = 3;
    var bw = n > 0 ? (W - gap * (n - 1)) / n : W;
    var bars = "";
    for (var i = 0; i < n; i++){
      var v = series[i] || 0;
      var h = gmax > 0 ? (v / gmax) * (H - 2) : 0;
      var x = i * (bw + gap);
      var cls = v > 0 ? "tr-bar" : "tr-bar tr-bar--z";
      var bh = v > 0 ? Math.max(1.5, h) : 1.5;   // a zero week is a hairline, honestly present
      bars += '<rect class="' + cls + '" x="' + x.toFixed(1) + '" y="' + (H - bh).toFixed(1) +
              '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1"><title>week ' + (i+1) +
              ': ' + v + '</title></rect>';
    }
    return '<svg class="tr-spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" ' +
      'aria-label="weekly count, ' + n + ' weeks">' + bars +
      '<line class="tr-axis" x1="0" y1="' + (H-0.5) + '" x2="' + W + '" y2="' + (H-0.5) + '"></line></svg>';
  }

  function card(band, idx, weeks, gmax){
    var series = weeks.map(function(w){ return (w.counts && w.counts[band.theme]) || 0; });
    var glow = !!band.rising;
    return '<div class="tr-card' + (glow ? " tr-card--glow" : "") + '">' +
      '<div class="tr-rank">#' + (idx + 1) + (glow ? ' &middot; <span class="tr-rising-tag">rising</span>' : '') + '</div>' +
      '<h3>' + esc(band.theme) + '</h3>' +
      '<div class="tr-total">' + band.total + ' mention' + (band.total===1?'':'s') + '</div>' +
      spark(series, gmax, glow) +
      '<div class="tr-wk">' + weeks.length + ' week' + (weeks.length===1?'':'s') + '</div>' +
      '</div>';
  }

  function render(a){
    if (!a || a.state === "empty" || a.n_days === 0){ root.appendChild(el(emptyState(a))); return; }
    var weeks = a.weeks || [];
    var bands = a.bands || [];
    var gmax = 0;
    bands.forEach(function(b){ weeks.forEach(function(w){ gmax = Math.max(gmax, (w.counts && w.counts[b.theme]) || 0); }); });
    var frag = el('<div data-readout data-state="' + esc(a.state) + '"></div>');
    if (a.state === "warming_up"){
      frag.appendChild(el('<div class="tr-banner"><strong>Still forming.</strong> Only ' + a.n_days +
        ' enriched day' + (a.n_days===1?'':'s') + ' so far (the river reads as a shape past ' + a.warming_up_min_days +
        '). What is below is real but thin — no dominant theme is claimed yet.</div>'));
    }
    frag.appendChild(el('<p class="tr-meta">' + weeks.length + ' week' + (weeks.length===1?'':'s') +
      ' &middot; ' + a.n_entries + ' entr' + (a.n_entries===1?'y':'ies') +
      (a.rising_theme ? ' &middot; rising: <span class="tr-rising-tag">' + esc(a.rising_theme) + '</span>' : '') + '</p>'));
    var grid = el('<div class="tr-grid"></div>');
    bands.forEach(function(b, i){ grid.appendChild(el(card(b, i, weeks, gmax))); });
    frag.appendChild(grid);
    frag.appendChild(el(provLine(a)));
    root.appendChild(frag);
  }

  fetch('/data/theme_river.json', { cache: "no-store" })
    .then(function(r){ if (!r.ok) throw new Error("no artifact"); return r.json(); })
    .then(render)
    .catch(function(){ root.appendChild(el(emptyState(null))); });
})();
