(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var findBoard = window.BoardState.findBoard;
  var findTask = window.BoardState.findTask;

  // The task's two long-form fields. Each entry is everything that differs
  // between them; the panel, tab and cache logic below is shared.
  var FIELDS = {
    description: {
      field: "description", attr: "description", versionAttr: "descriptionVersion",
      tab: "description", rootId: "task-detail-description-body", buttonId: "task-detail-tab-btn-description",
      emptyText: "No description yet. Add detailed context here — you or the agent can fill it in as the task gets clearer.",
      placeholder: "Describe the task in detail (markdown supported)…"
    },
    summary: {
      field: "summary", attr: "completionSummary", versionAttr: "completionSummaryVersion",
      tab: "summary", rootId: "task-detail-summary-body", buttonId: "task-detail-tab-btn-summary",
      emptyText: "No execution summary yet. The agent writes one when it completes, fails, or parks this task.",
      placeholder: "Edit the execution summary (markdown supported)…"
    }
  };

  var panels = {};
  var openBoardId = null;
  var openTaskId = null;

  function applyToCache(boardId, taskId, cfg, state){
    var task = findTask(findBoard(boardId), taskId);
    if(!task) return;
    task[cfg.attr] = state.content;
    task[cfg.versionAttr] = state.version;
    if(cfg.field === "summary") task.completionSummaryStatus = state.status;
    document.dispatchEvent(new CustomEvent("task-field-changed", {detail: {boardId: boardId, taskId: taskId}}));
  }

  function init(){
    Object.keys(FIELDS).forEach(function(key){
      var cfg = FIELDS[key];
      var root = document.getElementById(cfg.rootId);
      var button = document.getElementById(cfg.buttonId);
      panels[key] = new window.TaskFieldPanel({
        field: cfg.field, root: root, emptyText: cfg.emptyText, placeholder: cfg.placeholder,
        onChange: function(taskId, state){
          if(taskId !== openTaskId) return;
          applyToCache(openBoardId, taskId, cfg, state);
          window.BoardTaskTabs.setIndicator(cfg.tab, !!(state.content && state.content.trim()));
        }
      });
      window.BoardTaskTabs.register({name: cfg.tab, button: button, panel: root, showForm: false});
    });
  }

  function open(boardId, task){
    var board = findBoard(boardId);
    var canEdit = !!board && board.myRole !== "viewer";
    openBoardId = boardId;
    openTaskId = task.id;
    Object.keys(FIELDS).forEach(function(key){
      var cfg = FIELDS[key];
      // Cached values (the board payload carries them) make the dot right immediately.
      window.BoardTaskTabs.setIndicator(cfg.tab, !!(task[cfg.attr] && String(task[cfg.attr]).trim()));
      panels[key].open(boardId, task.id, canEdit);
    });
  }

  function close(){
    Object.keys(panels).forEach(function(key){ panels[key].close(); });
    openBoardId = null;
    openTaskId = null;
  }

  // A `task_field_updated` socket event. The open task's panel reloads (or
  // raises a conflict if the user is mid-edit); any other task just gets its
  // cached copy refreshed so card snippets stay current.
  function onRemoteEvent(board, data){
    var cfg = FIELDS[data.field];
    var task = findTask(board, data.taskId);
    if(!cfg || !task || (task[cfg.versionAttr] || 0) >= data.version) return;
    if(openBoardId === board.id && openTaskId === data.taskId){
      panels[cfg.field].onRemoteVersion(data.version);
      return;
    }
    apiGet("/boards/" + board.id + "/tasks/" + data.taskId + "/fields/" + cfg.field).then(function(state){
      applyToCache(board.id, data.taskId, cfg, state);
    }).catch(function(){});
  }

  // A one-line, markdown-stripped preview of the Description for the board
  // card, or null when there is none.
  function buildSnippet(task){
    var plain = String(task.description || "")
      .replace(/[`*_#>\[\]]|\(https?:[^)]*\)/g, "").replace(/\s+/g, " ").trim();
    if(!plain) return null;
    var snippet = document.createElement("span");
    snippet.className = "task-desc-snippet";
    snippet.textContent = plain.length > 110 ? plain.slice(0, 107) + "…" : plain;
    return snippet;
  }

  window.BoardTaskFields = {
    init: init, open: open, close: close, onRemoteEvent: onRemoteEvent, buildSnippet: buildSnippet
  };
})();
