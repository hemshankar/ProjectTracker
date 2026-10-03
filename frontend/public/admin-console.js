(function(){
  "use strict";

  // Agent Admin Console (Phase 8) — Activity tab (audit_log) and Traces tab
  // (llm_calls), plus the lighter per-board Activity view any board
  // viewer/editor can open without full Admin Console access.

  var activityBoardFilter = document.getElementById("activity-board-filter");
  var activityActorFilter = document.getElementById("activity-actor-filter");
  var activityRefreshBtn = document.getElementById("activity-refresh-btn");
  var activityList = document.getElementById("activity-list");

  var tracesBoardFilter = document.getElementById("traces-board-filter");
  var tracesRefreshBtn = document.getElementById("traces-refresh-btn");
  var tracesLiveIndicator = document.getElementById("traces-live-indicator");
  var tracesList = document.getElementById("traces-list");
  var tracesDetail = document.getElementById("traces-detail");

  var boardActivityModal = document.getElementById("board-activity-modal");
  var boardActivityTitle = document.getElementById("board-activity-title");
  var boardActivityList = document.getElementById("board-activity-list");
  var boardActivityClose = document.getElementById("board-activity-close");

  var boardTitleById = {};
  var currentAgentId = null;
  var activeTab = "config";
  var selectedCallId = null;

  function fmtTime(ts){
    if(!ts) return "";
    try{ return new Date(ts).toLocaleString(); }catch(e){ return String(ts); }
  }

  function fmtUsd(usd){
    return window.UsageFormat.usd(usd || 0);
  }

  function boardLabel(boardId){
    return boardTitleById[boardId] || boardId || "(unknown board)";
  }

  function populateBoardFilter(select){
    var current = select.value;
    select.innerHTML = '<option value="">All boards</option>';
    Object.keys(boardTitleById).forEach(function(boardId){
      var opt = document.createElement("option");
      opt.value = boardId;
      opt.textContent = boardTitleById[boardId];
      select.appendChild(opt);
    });
    select.value = current;
  }

  function setBoards(boards){
    boardTitleById = {};
    (boards || []).forEach(function(b){ boardTitleById[b.id] = b.title || "Untitled board"; });
    populateBoardFilter(activityBoardFilter);
    populateBoardFilter(tracesBoardFilter);
  }

  function jsonPreview(value){
    if(value === null || value === undefined) return "—";
    try{ return JSON.stringify(value, null, 2); }catch(e){ return String(value); }
  }

  function renderEmpty(container, message){
    container.innerHTML = "";
    var p = document.createElement("p");
    p.className = "settings-hint";
    p.textContent = message;
    container.appendChild(p);
  }

  function activityRow(entry, showBoard){
    var row = document.createElement("div");
    row.className = "activity-row";

    var summary = document.createElement("div");
    summary.className = "activity-row-summary";
    var who = entry.actorType === "agent" ? "Agent" : "Human";
    var scope = showBoard ? (boardLabel(entry.boardId) + " — ") : "";
    summary.textContent = fmtTime(entry.ts) + " · " + who + " " + entry.action + "d " + entry.entityType +
      (scope ? " · " + scope.replace(/ — $/, "") : "");
    row.appendChild(summary);

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "btn activity-row-toggle";
    toggle.textContent = "Before/After";
    var detail = document.createElement("div");
    detail.className = "activity-row-detail";
    detail.hidden = true;

    var before = document.createElement("pre");
    before.textContent = "Before:\n" + jsonPreview(entry.before);
    var after = document.createElement("pre");
    after.textContent = "After:\n" + jsonPreview(entry.after);
    detail.appendChild(before);
    detail.appendChild(after);

    toggle.addEventListener("click", function(){ detail.hidden = !detail.hidden; });
    row.appendChild(toggle);
    row.appendChild(detail);
    return row;
  }

  async function loadActivity(){
    if(!currentAgentId) return;
    renderEmpty(activityList, "Loading…");
    var params = new URLSearchParams();
    if(activityBoardFilter.value) params.set("boardId", activityBoardFilter.value);
    if(activityActorFilter.value) params.set("actorType", activityActorFilter.value);
    try{
      var rows = await window.Identity.apiGet(
        "/agents/" + currentAgentId + "/audit" + (params.toString() ? "?" + params.toString() : "")
      );
      if(!rows.length){ renderEmpty(activityList, "No activity yet."); return; }
      activityList.innerHTML = "";
      rows.forEach(function(entry){ activityList.appendChild(activityRow(entry, !activityBoardFilter.value)); });
    }catch(e){
      renderEmpty(activityList, "Couldn't load activity.");
    }
  }

  function tracesRow(call){
    var row = document.createElement("div");
    row.className = "activity-row traces-row";
    if(call.id === selectedCallId) row.classList.add("selected");
    row.dataset.callId = call.id;

    var summary = document.createElement("div");
    summary.className = "activity-row-summary";
    var indent = call.parentRunId ? "↳ " : "";
    summary.textContent = indent + fmtTime(call.ts) + " · " + (call.tool || "(no tool call)") +
      " · " + call.status + " · " + fmtUsd(call.usd) +
      (call.latencyMs ? " · " + Math.round(call.latencyMs) + "ms" : "");
    if(call.parentRunId) summary.style.paddingLeft = "1.2em";
    row.appendChild(summary);

    row.addEventListener("click", function(){ selectCall(call.id); });
    return row;
  }

  async function loadTraces(){
    if(!currentAgentId) return;
    renderEmpty(tracesList, "Loading…");
    var params = new URLSearchParams();
    if(tracesBoardFilter.value) params.set("boardId", tracesBoardFilter.value);
    try{
      var rows = await window.Identity.apiGet(
        "/agents/" + currentAgentId + "/llm-calls" + (params.toString() ? "?" + params.toString() : "")
      );
      if(!rows.length){ renderEmpty(tracesList, "No LLM calls yet."); return; }
      tracesList.innerHTML = "";
      rows.forEach(function(call){ tracesList.appendChild(tracesRow(call)); });
    }catch(e){
      renderEmpty(tracesList, "Couldn't load traces.");
    }
  }

  async function selectCall(callId){
    selectedCallId = callId;
    Array.prototype.forEach.call(tracesList.querySelectorAll(".traces-row"), function(row){
      row.classList.toggle("selected", row.dataset.callId === callId);
    });
    tracesDetail.innerHTML = "";
    var loading = document.createElement("p");
    loading.className = "settings-hint";
    loading.textContent = "Loading…";
    tracesDetail.appendChild(loading);
    try{
      var call = await window.Identity.apiGet("/agents/" + currentAgentId + "/llm-calls/" + callId);
      renderCallDetail(call);
    }catch(e){
      renderEmpty(tracesDetail, "Couldn't load this call.");
    }
  }

  function detailBlock(label, text){
    var wrap = document.createElement("div");
    wrap.className = "traces-detail-block";
    var h = document.createElement("h4");
    h.textContent = label;
    var pre = document.createElement("pre");
    pre.textContent = text || "—";
    wrap.appendChild(h);
    wrap.appendChild(pre);
    return wrap;
  }

  function renderCallDetail(call){
    tracesDetail.innerHTML = "";
    var meta = document.createElement("p");
    meta.className = "settings-hint";
    meta.textContent = fmtTime(call.ts) + " · " + fmtUsd(call.usd) + " · " +
      (call.inputTokens || 0) + " in / " + (call.outputTokens || 0) + " out tokens · " +
      Math.round(call.latencyMs || 0) + "ms" + (call.parentRunId ? " · nested under run " + call.parentRunId : "");
    tracesDetail.appendChild(meta);
    tracesDetail.appendChild(detailBlock("System prompt", call.systemPrompt));
    tracesDetail.appendChild(detailBlock("Request messages", jsonPreview(call.messages)));
    tracesDetail.appendChild(detailBlock("Response", call.response));
    tracesDetail.appendChild(detailBlock("Tool call", jsonPreview(call.toolCalls && call.toolCalls[0])));
  }

  function onLiveLlmCall(boardId, call){
    if(activeTab !== "traces") return;
    if(tracesBoardFilter.value && tracesBoardFilter.value !== boardId) return;
    call = Object.assign({boardId: boardId}, call);
    if(tracesList.querySelector(".settings-hint")) tracesList.innerHTML = "";
    tracesList.appendChild(tracesRow(call));
    tracesList.scrollTop = tracesList.scrollHeight;
    tracesLiveIndicator.hidden = false;
  }

  function onTabActivated(name, agentId){
    activeTab = name;
    currentAgentId = agentId;
    tracesLiveIndicator.hidden = true;
    if(name === "activity") loadActivity();
    if(name === "traces") loadTraces();
    if(name === "usage" && window.UsageTab) window.UsageTab.activate(agentId);
  }

  // Jump from a Usage ledger row to the matching Traces entry.
  async function openTrace(callId){
    document.getElementById("admin-tab-btn-traces").click();
    await loadTraces();
    selectCall(callId);
  }

  activityRefreshBtn.addEventListener("click", loadActivity);
  activityBoardFilter.addEventListener("change", loadActivity);
  activityActorFilter.addEventListener("change", loadActivity);

  tracesRefreshBtn.addEventListener("click", loadTraces);
  tracesBoardFilter.addEventListener("change", loadTraces);

  function closeBoardActivity(){ boardActivityModal.hidden = true; }
  boardActivityClose.addEventListener("click", closeBoardActivity);
  boardActivityModal.addEventListener("mousedown", function(e){
    if(e.target === boardActivityModal) closeBoardActivity();
  });
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !boardActivityModal.hidden) closeBoardActivity();
  });

  async function openBoardActivity(boardId, title){
    boardActivityTitle.textContent = (title || "Board") + " — activity";
    boardActivityModal.hidden = false;
    renderEmpty(boardActivityList, "Loading…");
    try{
      var rows = await window.Identity.apiGet("/boards/" + boardId + "/audit");
      if(!rows.length){ renderEmpty(boardActivityList, "No activity yet on this board."); return; }
      boardActivityList.innerHTML = "";
      rows.forEach(function(entry){ boardActivityList.appendChild(activityRow(entry, false)); });
    }catch(e){
      renderEmpty(boardActivityList, "Couldn't load this board's activity.");
    }
  }

  window.AdminConsole = {
    setBoards: setBoards,
    onTabActivated: onTabActivated,
    onLiveLlmCall: onLiveLlmCall,
    openBoardActivity: openBoardActivity,
    openTrace: openTrace,
    boardTitle: boardLabel
  };
})();
