(function(){
  "use strict";

  // Phase 7: server-side truth (`services.undo_service`), not a client-only
  // stack — a per-agent, per-user pointer into that user's own audit-log
  // entries. Survives a reload, and only ever replays *this user's own*
  // board/task edits — an agent's changes are never in this timeline.

  function applyUndoRedoResult(res){
    if(!res || !res.ok) return;
    var state = window.BoardState.state;
    if(res.board){
      var idx = state.boards.findIndex(function(b){ return b.id === res.board.id; });
      if(idx === -1){ state.boards.push(res.board); } else { state.boards[idx] = res.board; }
      state.zCounter = Math.max(state.zCounter, res.board.z || 0);
    } else if(res.boardId){
      state.boards = state.boards.filter(function(b){ return b.id !== res.boardId; });
    }
    window.BoardList.renderAll();
  }
  function performUndo(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    window.BoardApi.apiPost("/agents/" + agentId + "/undo").then(applyUndoRedoResult).catch(function(){});
  }
  function performRedo(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    window.BoardApi.apiPost("/agents/" + agentId + "/redo").then(applyUndoRedoResult).catch(function(){});
  }
  function initHistoryShortcuts(){
    document.addEventListener("keydown", function(e){
      if(!(e.ctrlKey || e.metaKey)) return;
      var tag = (e.target && e.target.tagName) || "";
      if(tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
      // A plain text input (e.g. the "Add a task" box) keeps focus after its
      // value is committed, so only defer to native input-undo while there's
      // still uncommitted text in it.
      if(tag === "INPUT" && e.target.value) return;
      var key = e.key.toLowerCase();
      if(key === "z" && e.shiftKey){
        e.preventDefault();
        performRedo();
      } else if(key === "z"){
        e.preventDefault();
        performUndo();
      } else if(key === "y"){
        e.preventDefault();
        performRedo();
      }
    });
  }

  window.BoardHistory = {
    initHistoryShortcuts: initHistoryShortcuts
  };
})();
