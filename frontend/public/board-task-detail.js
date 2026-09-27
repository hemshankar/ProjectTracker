(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPost = window.BoardApi.apiPost;
  var findBoard = window.BoardState.findBoard;
  var findTask = window.BoardState.findTask;
  var setModalTitle = window.BoardUtil.setModalTitle;
  var closeAllPopovers = window.BoardUtil.closeAllPopovers;
  var TASK_RUNNABLE_STATUSES = window.BoardUtil.TASK_RUNNABLE_STATUSES;
  var TASK_STOPPABLE_STATUSES = window.BoardUtil.TASK_STOPPABLE_STATUSES;
  var Render = window.BoardTaskDetailRender;

  var taskDetailModal = document.getElementById("task-detail-modal");
  var taskDetailTitle = document.getElementById("task-detail-title");
  var taskDetailSubtitle = document.getElementById("task-detail-subtitle");
  var taskDetailClose = document.getElementById("task-detail-close");
  var taskDetailBody = document.getElementById("task-detail-body");
  var taskDetailActivityBody = document.getElementById("task-detail-activity-body");
  var taskDetailTabBtnChat = document.getElementById("task-detail-tab-btn-chat");
  var taskDetailTabBtnActivity = document.getElementById("task-detail-tab-btn-activity");
  var taskDetailRunBtn = document.getElementById("task-detail-run-btn");
  var taskDetailStopBtn = document.getElementById("task-detail-stop-btn");
  var taskDetailForm = document.getElementById("task-detail-form");
  var taskDetailTextarea = document.getElementById("task-detail-textarea");
  var taskDetailSendBtn = document.getElementById("task-detail-send");

  var taskDetailBoardId = null;
  var taskDetailTaskId = null;
  var taskDetailChatId = null;
  var taskDetailSending = false;

  async function openTaskDetailModal(boardId, task){
    var board = findBoard(boardId);
    if(!board) return;
    taskDetailBoardId = boardId;
    taskDetailTaskId = task.id;
    taskDetailChatId = null;
    setModalTitle(taskDetailTitle, task.text || "Task");
    taskDetailSubtitle.textContent = task.status ? ("Status: " + task.status) : "";
    var runnable = TASK_RUNNABLE_STATUSES[task.status] && board.myRole !== "viewer";
    var stoppable = TASK_STOPPABLE_STATUSES[task.status] && board.myRole !== "viewer";
    taskDetailRunBtn.hidden = !runnable;
    taskDetailRunBtn.disabled = !runnable;
    taskDetailStopBtn.hidden = !stoppable;
    taskDetailStopBtn.disabled = !stoppable;
    taskDetailModal.hidden = false;
    closeAllPopovers();
    activateTaskDetailTab("chat");
    taskDetailBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    taskDetailActivityBody.innerHTML = "";
    taskDetailTextarea.value = "";
    await loadTaskDetail(boardId, task.id);
    if(taskDetailBoardId === boardId && taskDetailTaskId === task.id) taskDetailTextarea.focus();
  }

  async function loadTaskDetail(boardId, taskId){
    var board = findBoard(boardId);
    if(!board) return;
    try{
      var results = await Promise.all([
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/activity"),
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/chat")
      ]);
      if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
      var activity = results[0];
      var chatData = results[1];
      taskDetailChatId = chatData.chatId;
      renderTaskDetailActivity(board, {id: chatData.chatId, messages: chatData.messages}, activity);
    }catch(e){
      if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
      taskDetailBody.innerHTML = '<div class="chat-empty">Couldn&rsquo;t load this task&rsquo;s activity.</div>';
    }
  }

  function renderTaskDetailActivity(board, chat, activity){
    var task = findTask(board, taskDetailTaskId);
    if(task){
      setModalTitle(taskDetailTitle, task.text || "Task");
      taskDetailSubtitle.textContent = task.status ? ("Status: " + task.status) : "";
    }
    var runnable = !!task && TASK_RUNNABLE_STATUSES[task.status] && board.myRole !== "viewer";
    var stoppable = !!task && TASK_STOPPABLE_STATUSES[task.status] && board.myRole !== "viewer";
    taskDetailRunBtn.hidden = !runnable;
    taskDetailRunBtn.disabled = !runnable;
    taskDetailStopBtn.hidden = !stoppable;
    taskDetailStopBtn.disabled = !stoppable;
    taskDetailBody.innerHTML = "";
    var messages = chat.messages || [];
    if(!messages.length){
      var empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "No activity yet for this task. Say something below to get started.";
      taskDetailBody.appendChild(empty);
    } else {
      messages.forEach(function(m){ taskDetailBody.appendChild(Render.buildOwnTaskMessageEl(board, chat, m)); });
    }
    taskDetailBody.scrollTop = taskDetailBody.scrollHeight;

    taskDetailActivityBody.innerHTML = "";
    taskDetailActivityBody.appendChild(Render.buildCountsSummary(activity.counts || {}));
    taskDetailActivityBody.appendChild(Render.buildSubAgentSection(activity.subAgentRuns || []));
    taskDetailActivityBody.appendChild(Render.buildPeerAgentSection(activity.peerDelegations || []));
  }

  function closeTaskDetailModal(){
    taskDetailModal.hidden = true;
    taskDetailBoardId = null;
    taskDetailTaskId = null;
    taskDetailChatId = null;
  }

  function refreshTaskDetailIfOpen(boardId, taskId){
    if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
    loadTaskDetail(boardId, taskId);
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
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
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
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
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
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }
  }

  var TASK_DETAIL_TAB_PANELS = {chat: taskDetailBody, activity: taskDetailActivityBody};
  var TASK_DETAIL_TAB_BUTTONS = {chat: taskDetailTabBtnChat, activity: taskDetailTabBtnActivity};

  function activateTaskDetailTab(name){
    Object.keys(TASK_DETAIL_TAB_PANELS).forEach(function(key){
      TASK_DETAIL_TAB_PANELS[key].hidden = key !== name;
      TASK_DETAIL_TAB_BUTTONS[key].classList.toggle("active", key === name);
      TASK_DETAIL_TAB_BUTTONS[key].setAttribute("aria-selected", key === name ? "true" : "false");
    });
    taskDetailForm.hidden = name !== "chat";
  }

  function wireTaskDetailModal(){
    TASK_DETAIL_TAB_BUTTONS.chat.addEventListener("click", function(){ activateTaskDetailTab("chat"); });
    TASK_DETAIL_TAB_BUTTONS.activity.addEventListener("click", function(){ activateTaskDetailTab("activity"); });
    taskDetailClose.addEventListener("click", closeTaskDetailModal);
    taskDetailModal.addEventListener("mousedown", function(e){
      if(e.target === taskDetailModal) closeTaskDetailModal();
    });
    document.addEventListener("keydown", function(e){
      if(e.key === "Escape" && !taskDetailModal.hidden) closeTaskDetailModal();
    });
    taskDetailRunBtn.addEventListener("click", runSingleTask);
    taskDetailStopBtn.addEventListener("click", stopSingleTask);
    taskDetailForm.addEventListener("submit", function(e){
      e.preventDefault();
      sendTaskDetailMessage();
    });
    taskDetailTextarea.addEventListener("keydown", function(e){
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        if(taskDetailForm.requestSubmit) taskDetailForm.requestSubmit();
        else taskDetailForm.dispatchEvent(new Event("submit", {cancelable:true}));
      }
    });
    taskDetailTextarea.addEventListener("input", autoSizeTaskDetailTextarea);
  }

  window.BoardTaskDetail = {
    open: openTaskDetailModal,
    init: wireTaskDetailModal,
    refreshIfOpen: refreshTaskDetailIfOpen
  };
})();
