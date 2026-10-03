(function(){
  "use strict";

  // Stacked-bar spend chart as inline SVG. Each segment carries a <title> so the data is readable
  // without color; the same numbers are in the breakdown table for keyboard / screen-reader users.

  var NS = "http://www.w3.org/2000/svg";
  var W = 640, H = 220, PAD = {l: 46, r: 8, t: 10, b: 28};

  function el(name, attrs, parent){
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function(k){ node.setAttribute(k, attrs[k]); });
    if(parent) parent.appendChild(node);
    return node;
  }

  function colorVar(keys, key){
    return key === "_other" ? "var(--usage-other)" : "var(--usage-c" + (keys.indexOf(key) % 8 + 1) + ")";
  }

  function bucketLabel(bucket){ return String(bucket).slice(5) || String(bucket); }

  // opts: {nameOf(key), onSelect(bar, key)}
  function render(container, series, opts){
    container.innerHTML = "";
    if(!series.bars.length || !series.max){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "No usage in this range";
      container.appendChild(empty);
      return;
    }
    var svg = el("svg", {viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Spend over time", "class": "usage-svg"});
    var plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
    var slot = plotW / series.bars.length, barW = Math.max(2, Math.min(36, slot * 0.7));

    [0, 0.5, 1].forEach(function(f){
      var y = PAD.t + plotH * (1 - f);
      el("line", {x1: PAD.l, x2: W - PAD.r, y1: y, y2: y, "class": "usage-grid"}, svg);
      var label = el("text", {x: PAD.l - 6, y: y + 3, "text-anchor": "end", "class": "usage-axis"}, svg);
      label.textContent = window.UsageFormat.usd(series.max * f);
    });

    var every = Math.ceil(series.bars.length / 8);
    series.bars.forEach(function(bar, i){
      var x = PAD.l + slot * i + (slot - barW) / 2;
      var y = PAD.t + plotH;
      var g = el("g", {"class": "usage-bar", tabindex: "0", role: "button"}, svg);
      g.setAttribute("aria-label", bar.bucket + ": " + window.UsageFormat.usd(bar.total));
      series.keys.forEach(function(key){
        var v = bar.parts[key];
        if(!v) return;
        var h = v / series.max * plotH;
        y -= h;
        var seg = el("rect", {x: x, y: y, width: barW, height: Math.max(h, 1), fill: colorVar(series.keys, key)}, g);
        el("title", {}, seg).textContent = bar.bucket + " · " + opts.nameOf(key) + " · " + window.UsageFormat.usd(v);
        seg.addEventListener("click", function(){ opts.onSelect(bar, key); });
      });
      g.addEventListener("keydown", function(e){ if(e.key === "Enter" || e.key === " ") opts.onSelect(bar, null); });
      if(i % every === 0){
        var t = el("text", {x: x + barW / 2, y: H - 8, "text-anchor": "middle", "class": "usage-axis"}, svg);
        t.textContent = bucketLabel(bar.bucket);
      }
    });
    container.appendChild(svg);
    container.appendChild(legend(series, opts));
  }

  function legend(series, opts){
    var ul = document.createElement("ul");
    ul.className = "usage-legend";
    series.keys.forEach(function(key){
      var li = document.createElement("li");
      var sw = document.createElement("span");
      sw.className = "usage-swatch";
      sw.style.background = colorVar(series.keys, key);
      li.appendChild(sw);
      li.appendChild(document.createTextNode(opts.nameOf(key)));
      ul.appendChild(li);
    });
    return ul;
  }

  window.UsageChart = {render: render};
})();
