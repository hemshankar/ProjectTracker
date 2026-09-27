(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPost = window.BoardApi.apiPost;
  var findBoard = window.BoardState.findBoard;
  var findTask = window.BoardState.findTask;
  var TASK_RUNNABLE_STATUSES = window.BoardUtil.TASK_RUNNABLE_STATUSES;
  var TASK_STOPPABLE_STATUSES = window.BoardUtil.TASK_STOPPABLE_STATUSES;
  var Render = window.BoardTaskDetailRender;

  // Content controller for a task's tab inside the unified chat modal
  // (`board-chat.js` owns the modal shell and tab strip; this owns what's
  // rendered into the shared body/activity elements and the run/stop/send
  // actions, for whichever task tab is currently active).
  var taskDetailBody = document.getElementById("chat-modal-body");
  var taskDetailActivityBody = document.getElementById("task-detail-activity-body");
  var taskDetailTabBtnChat = document.getElementById("task-detail-tab-btn-chat");
  var taskDetailTabBtnActivity = document.getElementById("task-detail-tab-btn-activity");
  var taskDetailRunBtn = document.getElementById("task-detail-run-btn");
  var taskDetailStopBtn = document.getElementById("task-detail-stop-btn");
  var taskDetailForm = document.getElementById("chat-modal-form");
  var taskDetailTextarea = document.getElementById("chat-modal-textarea");
  var taskDetailSendBtn = document.getElementById("chat-modal-send");

  var taskDetailBoardId = null;
  var taskDetailTaskId = null;
  var taskDetailChatId = null;
  var taskDetailSubTab = "chat";
  var taskDetailSending = false;

  // Token-by-token text from an in-flight run, shown as a transient bubble
  // until the next authoritative refresh (a status change, or a fresh
  // `chat_stream_start`) reconciles it with the persisted messages.
  var streamText = "";
  var streamActive = false;

  function isActive(boardId, taskId){
    return taskDetailBoardId === boardId && taskDetailTaskId === taskId;
  }

  async function activate(boardId, task){
    taskDetailBoardId = boardId;
    taskDetailTaskId = task.id;
    taskDetailChatId = null;
    streamText = "";
    streamActive = false;
    activateSubTab("chat");
    updateHeaderButtons();
    taskDetailBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    taskDetailActivityBody.innerHTML = "";
    await loadTaskDetail(boardId, task.id);
  }

  function deactivate(){
    taskDetailBoardId = null;
    taskDetailTaskId = null;
    taskDetailChatId = null;
    streamText = "";
    streamActive = false;
  }

  function updateHeaderButtons(){
    var board = findBoard(taskDetailBoardId);
    var task = board && findTask(board, taskDetailTaskId);
    var runnable = !!task && TASK_RUNNABLE_STATUSES[task.status] && board.myRole !== "viewer";
    var stoppable = !!task && TASK_STOPPABLE_STATUSES[task.status] && board.myRole !== "viewer";
    taskDetailRunBtn.hidden = !runnable;
    taskDetailRunBtn.disabled = !runnable;
    taskDetailStopBtn.hidden = !stoppable;
    taskDetailStopBtn.disabled = !stoppable;
  }

  async function loadTaskDetail(boardId, taskId){
    var board = findBoard(boardId);
    if(!board) return;
    try{
      var results = await Promise.all([
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/activity"),
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/chat")
      ]);
      if(!isActive(boardId, taskId)) return;
      var activity = results[0];
      var chatData = results[1];
      taskDetailChatId = chatData.chatId;
      streamText = "";
      streamActive = false;
      renderTaskDetailActivity(board, {id: chatData.chatId, messages: chatData.messages}, activity);
    }catch(e){
      if(!isActive(boardId, taskId)) return;
      taskDetailBody.innerHTML = '<div class="chat-empty">Couldn&rsquo;t load this task&rsquo;s activity.</div>';
    }
  }

  function buildStreamingBubble(){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble chat-bubble-streaming";
    bubble.textContent = streamText;
    wrap.appendChild(bubble);
    return wrap;
  }

  function renderTaskDetailActivity(board, chat, activity){
    var task = findTask(board, taskDetailTaskId);
    if(task && window.BoardChat) window.BoardChat.updateTaskTabHeader(board, task);
    updateHeaderButtons();
    taskDetailBody.innerHTML = "";
    var messages = chat.messages || [];
    if(!messages.length && !streamActive){
      var empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "No activity yet for this task. Say something below to get started.";
      taskDetailBody.appendChild(empty);
    } else {
      messages.forEach(function(m){ taskDetailBody.appendChild(Render.buildOwnTaskMessageEl(board, chat, m)); });
      if(streamActive) taskDetailBody.appendChild(buildStreamingBubble());
    }
    taskDetailBody.scrollTop = taskDetailBody.scrollHeight;

    taskDetailActivityBody.innerHTML = "";
    taskDetailActivityBody.appendChild(Render.buildCountsSummary(activity.counts || {}));
    taskDetailActivityBody.appendChild(Render.buildSubAgentSection(activity.subAgentRuns || []));
    taskDetailActivityBody.appendChild(Render.buildPeerAgentSection(activity.peerDelegations || []));
  }

  function renderStreamBubble(){
    if(taskDetailSubTab !== "chat") return;
    var existing = taskDetailBody.querySelector(".chat-bubble-streaming");
    if(existing){
      existing.textContent = streamText;
    } else {
      var emptyEl = taskDetailBody.querySelector(".chat-empty");
      if(emptyEl) emptyEl.remove();
      taskDetailBody.appendChild(buildStreamingBubble());
    }
    taskDetailBody.scrollTop = taskDetailBody.scrollHeight;
  }

  function onStreamEvent(boardId, data){
    if(!isActive(boardId, data.taskId)) return;
    if(data.type === "chat_stream_start"){
      streamActive = true;
      streamText = "";
      renderStreamBubble();
    } else if(data.type === "chat_delta"){
      streamActive = true;
      streamText += data.delta || "";
      renderStreamBubble();
    }
    // `chat_stream_end` needs no handling here — either another
    // `chat_stream_start` (next tool round) or the task's next status-change
    // event (`refreshTaskDetailIfOpen`) reconciles this transient bubble
    // with whatever actually got persisted.
  }

  function refreshTaskDetailIfOpen(boardId, taskId){
    if(!isActive(boardId, taskId)) return;
    loadTaskDetail(boardId, taskId);
  }

  function activateSubTab(name){
    taskDetailSubTab = name;
    taskDetailBody.hidden = name !== "chat";
    taskDetailActivityBody.hidden = name !== "activity";
    taskDetailTabBtnChat.classList.toggle("active", name === "chat");
    taskDetailTabBtnChat.setAttribute("aria-selected", name === "chat" ? "true" : "false");
    taskDetailTabBtnActivity.classList.toggle("active", name === "activity");
    taskDetailTabBtnActivity.setAttribute("aria-selected", name === "activity" ? "true" : "false");
    taskDetailForm.hidden = name !== "chat";
  }

  async function sendTaskDetailMessage(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    var text = taskDetailTextarea.value.trim();
    if(!text || taskDetailSending || !boardId || !taskId) return;

    taskDetailSending = true;
    taskDetailSendBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/chat/messages", {text: text});
      var board = findBoard(boardId);
      if(board && resp && resp.chats){
        board.chats = resp.chats;
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      taskDetailTextarea.value = "";
      autoSizeTaskDetailTextarea();
      if(isActive(boardId, taskId)) await loadTaskDetail(boardId, taskId);
    }catch(e){
      // Left in the textarea so the user can retry.
    }finally{
      taskDetailSending = false;
      taskDetailSendBtn.disabled = false;
    }
  }

  function autoSizeTaskDetailTextarea(){
    taskDetailTextarea.style.height = "auto";
    taskDetailTextarea.style.height = Math.min(taskDetailTextarea.scrollHeight, 160) + "px";
  }

  async function runSingleTask(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    if(!boardId || !taskId || taskDetailRunBtn.disabled) return;
    taskDetailRunBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/run");
      var board = findBoard(boardId);
      if(board && resp && resp.tasks){
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      if(isActive(boardId, taskId)) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(isActive(boardId, taskId)) await loadTaskDetail(boardId, taskId);
    }
  }

  async function stopSingleTask(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    if(!boardId || !taskId || taskDetailStopBtn.disabled) return;
    taskDetailStopBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/stop");
      var board = findBoard(boardId);
      if(board && resp && resp.tasks){
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      if(isActive(boardId, taskId)) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(isActive(boardId, taskId)) await loadTaskDetail(boardId, taskId);
    }
  }

  function wireTaskDetailModal(){
    taskDetailTabBtnChat.addEventListener("click", function(){ activateSubTab("chat"); });
    taskDetailTabBtnActivity.addEventListener("click", function(){ activateSubTab("activity"); });
    taskDetailRunBtn.addEventListener("click", runSingleTask);
    taskDetailStopBtn.addEventListener("click", stopSingleTask);
  }

  window.BoardTaskDetail = {
    open: function(boardId, task){ if(window.BoardChat) window.BoardChat.openTask(boardId, task); },
    activate: activate,
    deactivate: deactivate,
    init: wireTaskDetailModal,
    refreshIfOpen: refreshTaskDetailIfOpen,
    sendMessage: sendTaskDetailMessage,
    onStreamEvent: onStreamEvent
  };
})();
