(function(){
  "use strict";

  // Pure helpers shared by badges, the Usage tab and the chart. No DOM, no fetch,
  // so they can be exercised from a plain node script (see window.UsageCore at the bottom).

  function usd(n, stale){
    if(n === null || n === undefined || isNaN(n)) return "—";
    var abs = Math.abs(n);
    var text;
    if(abs === 0) text = "$0.00";
    else if(abs < 0.01) text = "$" + n.toFixed(4);
    else if(abs < 1000) text = "$" + n.toFixed(abs < 1 ? 4 : 2);
    else text = "$" + n.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    return (stale ? "≈" : "") + text;
  }

  function compact(n){
    n = n || 0;
    if(n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if(n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }

  function percent(part, total){
    if(!total) return "0%";
    var p = part / total * 100;
    return (p > 0 && p < 1 ? "<1" : Math.round(p)) + "%";
  }

  function change(current, previous){
    if(!previous) return null;
    return (current - previous) / previous * 100;
  }

  // Optimistic live increment: returns a new totals map, never mutates the old one.
  function addLive(totals, key, usdDelta){
    var next = Object.assign({}, totals);
    if(next[key] !== null && next[key] !== undefined) next[key] = next[key] + (usdDelta || 0);
    return next;
  }

  // Groups time-series points into stacked bars: top `topN` keys by total spend, the rest as "Other".
  function stackSeries(points, topN){
    var totalsByKey = {};
    points.forEach(function(p){ var k = p.key || "_all"; totalsByKey[k] = (totalsByKey[k] || 0) + p.usd; });
    var ranked = Object.keys(totalsByKey).sort(function(a, b){ return totalsByKey[b] - totalsByKey[a]; });
    var keep = ranked.slice(0, topN);
    var buckets = {};
    points.forEach(function(p){
      var b = buckets[p.bucket] || (buckets[p.bucket] = {bucket: p.bucket, bucketTs: p.bucketTs, total: 0, parts: {}});
      var k = p.key || "_all";
      if(keep.indexOf(k) === -1) k = "_other";
      b.parts[k] = (b.parts[k] || 0) + p.usd;
      b.total += p.usd;
    });
    var bars = Object.keys(buckets).map(function(k){ return buckets[k]; })
      .sort(function(a, b){ return a.bucketTs - b.bucketTs; });
    var keys = keep.slice();
    if(bars.some(function(b){ return b.parts._other; })) keys.push("_other");
    var max = bars.reduce(function(m, b){ return Math.max(m, b.total); }, 0);
    return {bars: bars, keys: keys, max: max};
  }

  var DAY = 86400000;
  function rangeFor(days, now){
    now = now || Date.now();
    return {since: now - days * DAY, until: now};
  }
  function defaultGranularity(days){ return days <= 31 ? "day" : (days <= 100 ? "week" : "month"); }

  window.UsageFormat = {usd: usd, compact: compact, percent: percent, change: change};
  window.UsageCore = {addLive: addLive, stackSeries: stackSeries, rangeFor: rangeFor,
                      defaultGranularity: defaultGranularity};
})();
