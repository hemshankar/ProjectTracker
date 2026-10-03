(function(){
  "use strict";

  // Admin Console -> Usage tab: controls, headline, chart, breakdown, drill-down, export.
  var F = window.UsageFormat, Core = window.UsageCore;
  var FILTER_PARAM = {board: "boardId", task: "taskId", model: "model", user: "userId", callKind: "callKind"};
  var ROW_PAGE = 50;
  var DAY = 86400000;

  var presets = document.getElementById("usage-presets");
  var granSel = document.getElementById("usage-granularity");
  var groupSel = document.getElementById("usage-groupby");
  var exportBtn = document.getElementById("usage-export-btn");
  var exportFormat = document.getElementById("usage-export-format");
  var totalEl = document.getElementById("usage-total");
  var compareEl = document.getElementById("usage-compare");
  var statusEl = document.getElementById("usage-status");
  var chartEl = document.getElementById("usage-chart");
  var breakdownEl = document.getElementById("usage-breakdown");
  var rowsEl = document.getElementById("usage-rows");
  var bannerEl = document.getElementById("usage-delay-banner");

  var state = {days: 30, range: null, filter: {}, names: {}, cursor: null, loaded: false, token: 0};

  function groupBy(){ return groupSel.value; }

  function currentRange(){
    return state.range || Core.rangeFor(state.days);
  }

  function nameOf(key){
    if(key === "_other") return "Other";
    if(key === "_all") return "All usage";
    var n = state.names[key];
    if(n) return n;
    if(groupBy() === "board" && window.AdminConsole) return window.AdminConsole.boardTitle(key);
    return key || "—";
  }

  function setStatus(text){
    statusEl.hidden = !text;
    statusEl.textContent = text || "";
  }

  function failure(e){
    setStatus(e && e.unavailable ? "History unavailable. Totals elsewhere may be stale." : "Couldn't load usage. Try again.");
    [chartEl, breakdownEl, rowsEl].forEach(function(n){ n.innerHTML = ""; });
    totalEl.textContent = "—";
    compareEl.textContent = "";
  }

  function scope(extra){
    var r = currentRange();
    return Object.assign({since: r.since, until: r.until}, state.filter, extra || {});
  }

  function renderHeadline(cur, prev){
    totalEl.textContent = F.usd(cur.usd);
    compareEl.textContent = "";
    if(state.range || !prev) return;
    var pct = F.change(cur.usd, prev.usd);
    compareEl.textContent = pct === null ? "No spend in the previous period"
      : (pct >= 0 ? "▲ " : "▼ ") + Math.abs(Math.round(pct)) + "% vs previous " + state.days + " days";
  }

  // Amber banner when delivery to the ledger is behind (outbox backed up) or the service is down.
  async function checkDelay(){
    try{
      var h = await window.UsageApi.health();
      var waiting = h.outbox.pending || 0;
      var late = h.outbox.oldestPendingAgeSeconds > h.delayThresholdSeconds;
      bannerEl.textContent = !h.serviceReachable
        ? "Usage service is unreachable. Newer spend may be missing" + (waiting ? " (" + waiting + " events waiting)." : ".")
        : "Usage data is delayed. " + waiting + " event" + (waiting === 1 ? "" : "s") + " waiting.";
      bannerEl.hidden = h.serviceReachable && !late;
    }catch(e){ bannerEl.hidden = true; }
  }

  async function load(){
    checkDelay();
    var token = ++state.token;
    setStatus("Loading…");
    var r = currentRange();
    var span = r.until - r.since;
    var tableGroup = groupBy() === "none" ? "board" : groupBy();
    try{
      var results = await Promise.all([
        window.UsageApi.summary(scope()),
        state.range ? Promise.resolve(null) : window.UsageApi.summary(Object.assign({}, state.filter, {since: r.since - span, until: r.since})),
        window.UsageApi.timeseries(scope({granularity: granSel.value, groupBy: groupBy()})),
        window.UsageApi.breakdown(scope({groupBy: tableGroup, limit: 100}))
      ]);
      if(token !== state.token) return;
      setStatus("");
      state.names = {};
      results[3].forEach(function(row){ if(row.key && row.name) state.names[row.key] = row.name; });
      renderHeadline(results[0], results[1]);
      window.UsageChart.render(chartEl, Core.stackSeries(results[2], 8), {nameOf: nameOf, onSelect: onBar});
      window.UsageTable.renderBreakdown(breakdownEl, results[3], results[0].usd, {
        nameOf: function(row){ return row.name || (tableGroup === "board" && window.AdminConsole ? window.AdminConsole.boardTitle(row.key) : row.key) || "—"; },
        onSelect: function(row){ drill(FILTER_PARAM[tableGroup], row.key); }
      });
      await loadRows(false);
    }catch(e){
      if(token === state.token) failure(e);
    }
  }

  function onBar(bar, key){
    var width = {day: DAY, week: 7 * DAY, month: 31 * DAY}[granSel.value];
    state.range = {since: bar.bucketTs, until: bar.bucketTs + width - 1};
    var param = FILTER_PARAM[groupBy()];
    if(key && key !== "_other" && key !== "_all" && param) state.filter[param] = key;
    markPreset(null);
    load();
  }

  function drill(param, key){
    if(!param || !key) return;
    state.filter[param] = key;
    load();
  }

  async function loadRows(append){
    try{
      var page = await window.UsageApi.rows(scope({limit: ROW_PAGE, cursor: append ? state.cursor : null}));
      state.cursor = page.nextCursor;
      window.UsageTable.renderRows(rowsEl, page.rows, {
        hasMore: !!page.nextCursor,
        onMore: function(){ loadRows(true); },
        onTrace: function(id){ window.AdminConsole.openTrace(id); }
      }, append);
    }catch(e){ failure(e); }
  }

  function markPreset(days){
    Array.prototype.forEach.call(presets.querySelectorAll("button"), function(b){
      b.classList.toggle("btn-primary", days !== null && Number(b.dataset.days) === days);
    });
  }

  function resetFilters(){ state.range = null; state.filter = {}; }

  presets.addEventListener("click", function(e){
    var days = e.target.dataset && Number(e.target.dataset.days);
    if(!days) return;
    state.days = days;
    resetFilters();
    granSel.value = Core.defaultGranularity(days);
    markPreset(days);
    load();
  });
  granSel.addEventListener("change", load);
  groupSel.addEventListener("change", function(){ state.filter = {}; load(); });
  exportBtn.addEventListener("click", function(){
    var url = window.UsageApi.exportUrl(Object.assign(scope(), {format: exportFormat.value}));
    var a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  });

  function activate(){
    if(state.loaded) return;
    state.loaded = true;
    granSel.value = Core.defaultGranularity(state.days);
    markPreset(state.days);
    load();
  }

  window.UsageTab = {activate: activate};
  window.Identity.onAgentChange(function(){ state.loaded = false; resetFilters(); });
})();
