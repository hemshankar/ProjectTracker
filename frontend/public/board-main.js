(function(){
  "use strict";

  async function reloadBoards(){
    var state = window.BoardState.state;
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    window.BoardSocket.connect(agentId);
    if(!agentId){ state.boards = []; window.BoardList.renderAll(); return; }
    try{
      state.boards = await window.Identity.apiGet("/agents/" + agentId + "/boards");
    }catch(e){
      state.boards = [];
    }
    state.boards.forEach(function(b){ b.tasks = b.tasks || []; });
    state.zCounter = state.boards.reduce(function(m, b){ return Math.max(m, b.z || 0); }, 10);
    window.BoardList.renderAll();
    // Labels are cached after their first fetch — this re-render only
    // actually happens the very first time (or after a hard reload).
    var hadLabels = window.BoardLabels.hasCache();
    window.BoardLabels.ensureLabelsLoaded().then(function(){ if(!hadLabels) window.BoardList.renderAll(); });
  }

  async function init(){
    window.BoardTheme.initTheme();
    window.BoardZoom.initZoom();
    window.BoardHistory.initHistoryShortcuts();
    window.BoardChat.init();
    window.BoardTaskDetail.init();

    var session = await window.Identity.init();
    if(!session) return;

    window.Identity.onAgentChange(reloadBoards);
    await reloadBoards();
  }

  init();
})();
