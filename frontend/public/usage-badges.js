(function(){
  "use strict";

  // Cost pills: one per board card and one in the task detail header. Totals come from the
  // server; each live `llmCall` event adds its usd optimistically, then a debounced refetch
  // reconciles so drift can't accumulate.

  var F = window.UsageFormat;
  var RECONCILE_MS = 3000;

  var boardTotals = {};      // boardId -> usd | null
  var boardStale = {};       // boardId -> bool
  var boardPills = {};       // boardId -> element
  var task = {boardId: null, taskId: null, usd: null, stale: false, tokens: null};
  var taskPill = document.getElementById("task-usage-badge");
  var timers = {};
  var boardsEnabled = true;  // admin can hide board totals workspace-wide
  var cardLists = {};        // boardId -> task <ul> element
  var cardTotals = {};       // boardId -> {enabled, totals{taskId: usd}, stale} (once loaded)

  function paint(el, usd, stale, title, showUnknown){
    if(!el) return;
    el.hidden = (usd === null || usd === undefined) && !showUnknown;
    el.textContent = F.usd(usd, stale);
    el.title = stale ? "May be a few seconds behind" : (title || "Spent so far");
  }

  function paintBoard(boardId){
    if(!boardsEnabled){ if(boardPills[boardId]) boardPills[boardId].hidden = true; return; }
    paint(boardPills[boardId], boardTotals[boardId], boardStale[boardId], "Board spend so far");
  }

  function paintTask(){
    var isAdmin = window.Identity.getCurrentAgentRole() === "admin";
    var detail = isAdmin && task.tokens ? " (" + F.compact(task.tokens.input) + " in / " + F.compact(task.tokens.output) + " out)" : "";
    // Shows "\u2014" while loading or when the service can't answer, so the pill is never silently absent.
    paint(taskPill, task.usd, task.stale, task.stale ? undefined : "Task spend so far" + detail, !!task.taskId);
  }

  function paintTaskCards(boardId){
    var list = cardLists[boardId], data = cardTotals[boardId];
    if(!list) return;
    Array.prototype.forEach.call(list.querySelectorAll(".task-card-usage"), function(el){
      var usd = data && data.enabled ? data.totals[el.dataset.taskId] : null;
      paint(el, usd, data && data.stale, "Task spend so far");
    });
  }

  async function loadTaskCards(boardId){
    try{
      var res = await window.UsageApi.taskTotals(boardId);
      cardTotals[boardId] = {enabled: res.enabled !== false, totals: res.totals || {}, stale: !!res.stale};
    }catch(e){ cardTotals[boardId] = {enabled: false, totals: {}}; }
    paintTaskCards(boardId);
  }

  // Called after every task-list render: repaint from cache, fetching once per board.
  function mountTaskCards(board, listEl){
    cardLists[board.id] = listEl;
    if(cardTotals[board.id]) paintTaskCards(board.id);
    else{ cardTotals[board.id] = {enabled: false, totals: {}}; loadTaskCards(board.id); }
  }

  function reloadTaskCards(){ Object.keys(cardLists).forEach(loadTaskCards); }

  function mountBoard(board, cardEl){
    boardPills[board.id] = cardEl.querySelector(".board-usage-pill");
    paintBoard(board.id);
  }

  async function loadBoards(){
    try{
      var res = await window.UsageApi.boardTotals();
      boardTotals = {};
      Object.keys(res.totals || {}).forEach(function(id){ boardTotals[id] = res.totals[id]; boardStale[id] = !!res.stale; });
      boardsEnabled = res.enabled !== false;
      Object.keys(boardPills).forEach(paintBoard);
    }catch(e){ /* totals are a nicety; never disturb the board list */ }
  }

  async function refreshBoard(boardId){
    try{
      var res = await window.UsageApi.boardTotal(boardId);
      boardTotals[boardId] = res.usd;
      boardStale[boardId] = !!res.stale;
      paintBoard(boardId);
    }catch(e){}
  }

  async function refreshTask(){
    var boardId = task.boardId, taskId = task.taskId;
    if(!taskId) return;
    try{
      var res = await window.UsageApi.taskTotal(boardId, taskId);
      if(task.taskId !== taskId) return;
      task.usd = res.usd;
      task.stale = !!res.stale;
      task.tokens = res.inputTokens !== undefined ? {input: res.inputTokens, output: res.outputTokens} : null;
      paintTask();
    }catch(e){ if(task.taskId === taskId){ task.usd = null; paintTask(); } }
  }

  function debounce(key, fn){
    clearTimeout(timers[key]);
    timers[key] = setTimeout(fn, RECONCILE_MS);
  }

  function scheduleReconcile(boardId){
    debounce("board:" + boardId, function(){ refreshBoard(boardId); if(cardTotals[boardId] && cardTotals[boardId].enabled) loadTaskCards(boardId); });
    if(task.boardId === boardId) debounce("task", refreshTask);
  }

  function onLlmCall(boardId, call){
    var delta = (call && call.usd) || 0;
    boardTotals = window.UsageCore.addLive(boardTotals, boardId, delta);
    paintBoard(boardId);
    var cards = cardTotals[boardId];
    if(call.taskId && cards && cards.enabled && cards.totals[call.taskId] !== undefined){
      cards.totals = window.UsageCore.addLive(cards.totals, call.taskId, delta);
      paintTaskCards(boardId);
    }
    if(call.taskId && task.taskId === call.taskId){
      task.usd = window.UsageCore.addLive({v: task.usd}, "v", delta).v;
      paintTask();
    }
    scheduleReconcile(boardId);
  }

  // Chat and dispatch calls raise no llmCall event; refetch when a chat stream ends.
  function onChatEnd(boardId){ clearTimeout(timers["board:" + boardId]); refreshBoard(boardId); if(task.boardId === boardId) refreshTask(); }

  function showTask(boardId, taskId){
    task = {boardId: boardId, taskId: taskId, usd: null, stale: false, tokens: null};
    paintTask();
    refreshTask();
  }

  function hideTask(){
    task = {boardId: null, taskId: null, usd: null, stale: false, tokens: null};
    paintTask();
  }

  window.UsageBadges = {mountBoard: mountBoard, loadBoards: loadBoards, onLlmCall: onLlmCall,
                        onChatEnd: onChatEnd, mountTaskCards: mountTaskCards, reloadTaskCards: reloadTaskCards, showTask: showTask, hideTask: hideTask};
})();
