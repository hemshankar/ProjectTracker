(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPost = window.BoardApi.apiPost;
  var apiPatch = window.BoardApi.apiPatch;
  var API = window.BoardApi.API;
  var findBoard = window.BoardState.findBoard;
  var findTask = window.BoardState.findTask;
  var setModalTitle = window.BoardUtil.setModalTitle;
  var hueValue = window.BoardUtil.hueValue;
  var closeAllPopovers = window.BoardUtil.closeAllPopovers;

  // Tasks whose chat has never produced a message yet don't clutter the tab
  // strip — but a task that's actively suspended/running earns a tab even
  // before its first message lands (e.g. right as a run claims it).
  var ACTIVE_TASK_TAB_STATUSES = {
    running: 1, awaiting_approval: 1, awaiting_reply: 1, awaiting_clarification: 1, manual: 1
  };

  var chatModal = document.getElementById("chat-modal");
  var chatModalTitle = document.getElementById("chat-modal-title");
  var chatModalSubtitle = document.getElementById("chat-modal-subtitle");
  var chatModalDot = document.getElementById("chat-modal-dot");
  var chatModalClose = document.getElementById("chat-modal-close");
  var chatModalBody = document.getElementById("chat-modal-body");
  var chatForm = document.getElementById("chat-modal-form");
  var chatTextarea = document.getElementById("chat-modal-textarea");
  var chatSendBtn = document.getElementById("chat-modal-send");
  var chatNewBtn = document.getElementById("chat-new-btn");
  var chatHistoryAnchor = document.getElementById("chat-history-anchor");
  var chatHistoryBtn = document.getElementById("chat-history-btn");

  var boardChatTabs = document.getElementById("board-chat-tabs");
  var boardChatTabBoard = document.getElementById("board-chat-tab-board");
  var boardChatMoreAnchor = document.getElementById("board-chat-more-anchor");
  var boardChatMoreBtn = document.getElementById("board-chat-more-btn");
  var taskChatSubtabs = document.getElementById("task-chat-subtabs");
  var taskDetailRunBtn = document.getElementById("task-detail-run-btn");
  var taskDetailStopBtn = document.getElementById("task-detail-stop-btn");

  var chatBoardId = null;
  var chatAbortController = null;
  var activeTab = "board"; // "board" | a task id
  var extraOpenTaskIds = []; // task tabs opened this modal session via the "+" picker or the task list

  function abortActiveChatStream(){
    if(chatAbortController){ chatAbortController.abort(); chatAbortController = null; }
  }

  function setChatBusy(busy){
    if(activeTab !== "board") return;
    chatSendBtn.textContent = busy ? "Stop" : "Send";
    chatTextarea.disabled = busy;
  }

  function autoSizeChatTextarea(){
    chatTextarea.style.height = "auto";
    chatTextarea.style.height = Math.min(chatTextarea.scrollHeight, 160) + "px";
  }

  function renderChatMessages(){
    var board = findBoard(chatBoardId);
    if(!board) return;
    var chat = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    var messages = chat ? chat.messages : [];
    chatModalBody.innerHTML = "";
    if(!messages.length){
      var empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "Ask about this board — priorities, next steps, drafts, anything.";
      chatModalBody.appendChild(empty);
    } else {
      messages.forEach(function(m){ chatModalBody.appendChild(window.BoardChatMessages.buildChatMessageEl(board, chat, m)); });
    }
    chatModalBody.scrollTop = chatModalBody.scrollHeight;
  }

  function buildChatHistoryItem(board, chat){
    var li = document.createElement("li");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-history-item" + (chat.id === board.activeChatId ? " active" : "");
    var firstUser = chat.messages.find(function(m){ return m.role === "user"; });
    var snippet = firstUser ? firstUser.text : "New chat";
    if(snippet.length > 46) snippet = snippet.slice(0, 46) + "…";
    var meta = new Date(chat.createdAt).toLocaleString(undefined, {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"});
    meta += " · " + chat.messages.length + (chat.messages.length === 1 ? " message" : " messages");
    var snippetEl = document.createElement("span");
    snippetEl.className = "snippet";
    snippetEl.textContent = snippet;
    var metaEl = document.createElement("span");
    metaEl.className = "meta";
    metaEl.textContent = meta;
    btn.appendChild(snippetEl);
    btn.appendChild(metaEl);
    btn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      switchChat(board.id, chat.id);
    });
    li.appendChild(btn);
    return li;
  }

  function renderChatHistoryPop(){
    var pop = chatHistoryAnchor.querySelector(".chat-history-pop");
    if(!pop) return;
    var board = findBoard(chatBoardId);
    if(!board) return;
    var list = pop.querySelector(".chat-history-list");
    list.innerHTML = "";
    var sorted = (board.chats || []).filter(function(c){ return !c.taskId; }).slice().sort(function(a, b){ return b.createdAt - a.createdAt; });
    sorted.forEach(function(chat){ list.appendChild(buildChatHistoryItem(board, chat)); });
  }

  async function ensureChatsLoaded(board){
    if(board._chatsLoaded) return;
    try{
      var data = await apiGet("/boards/" + board.id + "/chats");
      board.chats = data.chats || [];
      board.activeChatId = data.activeChatId;
      if(!(board.chats || []).some(function(c){ return !c.taskId; })){
        var chat = await apiPost("/boards/" + board.id + "/chats");
        board.chats.push(chat);
        board.activeChatId = chat.id;
      }
      board._chatsLoaded = true;
    }catch(e){
      board.chats = board.chats || [];
    }
  }

  async function startNewChat(boardId){
    var board = findBoard(boardId);
    if(!board || activeTab !== "board") return;
    abortActiveChatStream();
    var current = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    if(!current || current.messages.length){
      try{
        var chat = await apiPost("/boards/" + boardId + "/chats");
        board.chats.push(chat);
        board.activeChatId = chat.id;
      }catch(e){}
    }
    setChatBusy(false);
    renderChatMessages();
    renderChatHistoryPop();
    chatTextarea.focus();
  }

  function switchChat(boardId, chatId){
    var board = findBoard(boardId);
    if(!board) return;
    if(chatId === board.activeChatId || !(board.chats || []).some(function(c){ return c.id === chatId; })) return;
    abortActiveChatStream();
    board.activeChatId = chatId;
    apiPatch("/boards/" + boardId + "/chats/active", {chatId: chatId}).catch(function(){});
    setChatBusy(false);
    renderChatMessages();
    renderChatHistoryPop();
  }

  // ---------------- tab strip (Board + one per task with activity) ----------------

  function computeVisibleTaskIds(board){
    var chatsByTask = {};
    (board.chats || []).forEach(function(c){ if(c.taskId) chatsByTask[c.taskId] = c; });
    var ids = (board.tasks || []).filter(function(t){
      var chat = chatsByTask[t.id];
      return (chat && chat.messages && chat.messages.length) || ACTIVE_TASK_TAB_STATUSES[t.status];
    }).map(function(t){ return t.id; });
    extraOpenTaskIds.forEach(function(id){
      if(ids.indexOf(id) === -1 && findTask(board, id)) ids.push(id);
    });
    return ids;
  }

  function buildTaskTabLabel(task){
    var text = (task.text || "Task").trim();
    return text.length > 22 ? text.slice(0, 22) + "…" : text;
  }

  function renderTabStrip(){
    var board = findBoard(chatBoardId);
    if(!board) return;
    Array.prototype.slice.call(boardChatTabs.querySelectorAll(".board-chat-task-tab")).forEach(function(btn){ btn.remove(); });
    var ids = computeVisibleTaskIds(board);
    ids.forEach(function(taskId){
      var task = findTask(board, taskId);
      if(!task) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "admin-console-tab board-chat-task-tab" + (activeTab === taskId ? " active" : "");
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", activeTab === taskId ? "true" : "false");
      btn.title = task.text || "Task";
      btn.textContent = buildTaskTabLabel(task);
      btn.addEventListener("click", function(){ activateTab(taskId); });
      boardChatTabs.insertBefore(btn, boardChatMoreAnchor);
    });
    boardChatTabBoard.classList.toggle("active", activeTab === "board");
    boardChatTabBoard.setAttribute("aria-selected", activeTab === "board" ? "true" : "false");

    // "+ Chat" is an overflow picker for tasks not already shown as a tab —
    // it hides once every task already has one (nothing left to reach), and
    // also while none has one yet (no chats have started anywhere, so
    // there's nothing to reach "the rest" of; starting a task's first chat
    // happens from the task list instead).
    var remainingCount = (board.tasks || []).filter(function(t){ return ids.indexOf(t.id) === -1; }).length;
    boardChatMoreAnchor.hidden = remainingCount === 0 || ids.length === 0;
    if(boardChatMoreAnchor.hidden){
      var openPop = document.querySelector(".board-chat-more-pop");
      if(openPop) openPop.remove();
    }
  }

  function refreshTabsIfOpen(boardId){
    if(chatBoardId !== boardId || chatModal.hidden) return;
    renderTabStrip();
  }

  // Popovers elsewhere in the app live inside a `position:relative` anchor
  // and just use `top`/`right` — fine near the modal header, but the "+
  // Chat" anchor sits inside the tab strip, and `.chat-modal-dialog` clips
  // overflow, so that CSS-only positioning could get cut off. This instead
  // measures the anchor and places the popover with `position:fixed` on
  // `document.body`, clamped to the viewport, so it's never clipped.
  function positionFloatingPopover(pop, anchorEl){
    var margin = 8;
    var rect = anchorEl.getBoundingClientRect();
    var popRect = pop.getBoundingClientRect();
    var left = Math.min(rect.right - popRect.width, window.innerWidth - popRect.width - margin);
    left = Math.max(margin, left);
    var top = rect.bottom + 6;
    if(top + popRect.height > window.innerHeight - margin){
      top = Math.max(margin, rect.top - popRect.height - 6);
    }
    pop.style.position = "fixed";
    pop.style.top = top + "px";
    pop.style.left = left + "px";
    pop.style.right = "auto";
    pop.style.zIndex = "2100";
  }

  function renderMorePop(pop){
    var board = findBoard(chatBoardId);
    if(!board) return;
    var list = pop.querySelector(".chat-history-list");
    list.innerHTML = "";
    var visible = computeVisibleTaskIds(board);
    var remaining = (board.tasks || []).filter(function(t){ return visible.indexOf(t.id) === -1; });
    if(!remaining.length){
      var empty = document.createElement("li");
      empty.className = "chat-history-empty";
      empty.textContent = "No other tasks on this board.";
      list.appendChild(empty);
      return;
    }
    remaining.forEach(function(task){
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chat-history-item";
      var snippetEl = document.createElement("span");
      snippetEl.className = "snippet";
      snippetEl.textContent = task.text || "Task";
      btn.appendChild(snippetEl);
      btn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
      btn.addEventListener("click", function(e){
        e.stopPropagation();
        closeAllPopovers();
        openTaskTab(task);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  function openTaskTab(task){
    if(extraOpenTaskIds.indexOf(task.id) === -1) extraOpenTaskIds.push(task.id);
    renderTabStrip();
    activateTab(task.id);
  }

  function updateTaskTabHeader(board, task){
    if(activeTab !== task.id) return;
    setModalTitle(chatModalTitle, task.text || "Task");
    chatModalSubtitle.textContent = task.status ? ("Status: " + task.status) : "";
  }

  function activateTab(name){
    var board = findBoard(chatBoardId);
    if(!board) return;
    var leavingTask = activeTab !== "board" ? activeTab : null;
    var task = name !== "board" ? findTask(board, name) : null;
    if(name !== "board" && !task){
      name = "board"; // task no longer exists (e.g. deleted) — fall back
    }

    if(name === "board"){
      if(leavingTask && window.BoardTaskDetail) window.BoardTaskDetail.deactivate();
      activeTab = "board";
      taskChatSubtabs.hidden = true;
      taskDetailRunBtn.hidden = true;
      taskDetailStopBtn.hidden = true;
      chatModalBody.hidden = false;
      if(window.BoardTaskTabs) window.BoardTaskTabs.hideTaskOnlyPanels();
      chatForm.hidden = false;
      chatTextarea.placeholder = "Ask about this board…";
      setModalTitle(chatModalTitle, board.title || "Untitled board");
      chatModalSubtitle.textContent = "Scoped to this board — remembers this conversation";
      chatModalDot.style.background = hueValue(board.color);
      chatModalDot.hidden = false;
      setChatBusy(!!chatAbortController);
      renderChatMessages();
    } else {
      activeTab = name;
      chatModalDot.hidden = true;
      taskChatSubtabs.hidden = false;
      chatForm.hidden = false;
      chatTextarea.placeholder = "Message about this task…";
      updateTaskTabHeader(board, task);
      chatSendBtn.textContent = "Send";
      chatTextarea.disabled = false;
      if(window.BoardTaskDetail) window.BoardTaskDetail.activate(chatBoardId, task);
    }
    renderTabStrip();
  }

  async function openChatModal(boardId){
    var board = findBoard(boardId);
    if(!board) return;
    if(chatBoardId !== boardId){
      abortActiveChatStream();
      extraOpenTaskIds = [];
    }
    chatBoardId = boardId;
    chatModal.hidden = false;
    closeAllPopovers();
    chatModalBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    await ensureChatsLoaded(board);
    if(chatBoardId !== boardId) return;
    activateTab("board");
    chatTextarea.value = "";
    autoSizeChatTextarea();
    chatTextarea.focus();
  }

  async function openTask(boardId, task){
    var board = findBoard(boardId);
    if(!board) return;
    if(chatBoardId !== boardId){
      abortActiveChatStream();
      extraOpenTaskIds = [];
    }
    chatBoardId = boardId;
    chatModal.hidden = false;
    closeAllPopovers();
    await ensureChatsLoaded(board);
    if(chatBoardId !== boardId) return;
    openTaskTab(task);
    chatTextarea.value = "";
  }

  function closeChatModal(){
    abortActiveChatStream();
    if(activeTab !== "board" && window.BoardTaskDetail) window.BoardTaskDetail.deactivate();
    closeAllPopovers();
    chatModal.hidden = true;
    chatBoardId = null;
    activeTab = "board";
    extraOpenTaskIds = [];
  }

  async function sendChatMessage(){
    var boardId = chatBoardId;
    var board = findBoard(boardId);
    if(!board) return;
    var text = chatTextarea.value.trim();
    if(!text || chatAbortController) return;

    var chat = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    if(!chat) return;

    chat.messages.push({role: "user", text: text});
    chatTextarea.value = "";
    autoSizeChatTextarea();
    if(chatBoardId === boardId) renderChatMessages();

    var pending = {role: "assistant", text: ""};
    chat.messages.push(pending);
    if(chatBoardId === boardId) renderChatMessages();

    var controller = new AbortController();
    chatAbortController = controller;
    if(chatBoardId === boardId) setChatBusy(true);

    try{
      var resp = await fetch(API + "/boards/" + boardId + "/chats/" + chat.id + "/messages", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: text}),
        signal: controller.signal
      });
      if(!resp.ok || !resp.body) throw new Error("chat request failed");

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while(true){
        var res = await reader.read();
        if(res.done) break;
        buffer += decoder.decode(res.value, {stream: true});
        var parts = buffer.split("\n\n");
        buffer = parts.pop();
        for(var i = 0; i < parts.length; i++){
          var line = parts[i];
          if(line.indexOf("data: ") !== 0) continue;
          var payload = JSON.parse(line.slice(6));
          if(payload.delta){
            pending.text += payload.delta;
            if(chatBoardId === boardId) renderChatMessages();
          }
        }
      }
    }catch(err){
      if(err && err.name === "AbortError"){
        pending.text = pending.text || "(stopped)";
      } else {
        pending.text = pending.text || "Something went wrong reaching the assistant.";
      }
    } finally {
      if(chatAbortController === controller) chatAbortController = null;
      if(chatBoardId === boardId){ setChatBusy(false); renderChatMessages(); }
    }
  }

  function wireChatModal(){
    chatModalClose.addEventListener("click", closeChatModal);
    chatModal.addEventListener("mousedown", function(e){
      if(e.target === chatModal) closeChatModal();
    });
    document.addEventListener("keydown", function(e){
      if(e.key === "Escape" && !chatModal.hidden) closeChatModal();
    });
    chatForm.addEventListener("submit", function(e){
      e.preventDefault();
      if(activeTab === "board"){
        if(chatAbortController){ chatAbortController.abort(); return; }
        sendChatMessage();
      } else if(window.BoardTaskDetail){
        window.BoardTaskDetail.sendMessage();
      }
    });
    chatTextarea.addEventListener("keydown", function(e){
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        if(chatForm.requestSubmit) chatForm.requestSubmit();
        else chatForm.dispatchEvent(new Event("submit", {cancelable:true}));
      }
    });
    chatTextarea.addEventListener("input", autoSizeChatTextarea);

    chatNewBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatNewBtn.addEventListener("click", function(e){
      e.stopPropagation();
      closeAllPopovers();
      if(chatBoardId && activeTab === "board") startNewChat(chatBoardId);
    });

    chatHistoryBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatHistoryBtn.addEventListener("click", function(e){
      e.stopPropagation();
      if(activeTab !== "board") return;
      var existing = chatHistoryAnchor.querySelector(".chat-history-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "chat-history-pop popover";
      pop.innerHTML = '<div class="completed-pop-header"><span>Previous chats</span></div><ul class="chat-history-list"></ul>';
      chatHistoryAnchor.appendChild(pop);
      renderChatHistoryPop();
    });

    boardChatTabBoard.addEventListener("click", function(){ activateTab("board"); });

    boardChatMoreBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    boardChatMoreBtn.addEventListener("click", function(e){
      e.stopPropagation();
      var existing = document.querySelector(".board-chat-more-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "chat-history-pop popover board-chat-more-pop";
      pop.innerHTML = '<div class="completed-pop-header"><span>Open a task&rsquo;s chat</span></div><ul class="chat-history-list"></ul>';
      document.body.appendChild(pop);
      renderMorePop(pop);
      positionFloatingPopover(pop, boardChatMoreBtn);
    });
  }

  window.BoardChat = {
    open: openChatModal,
    openTask: openTask,
    init: wireChatModal,
    notifyBoardUpdated: function(boardId){
      if(chatBoardId !== boardId) return;
      if(activeTab === "board") renderChatMessages();
      else if(window.BoardTaskDetail) window.BoardTaskDetail.refreshIfOpen(boardId, activeTab);
    },
    refreshTabsIfOpen: refreshTabsIfOpen,
    updateTaskTabHeader: updateTaskTabHeader
  };
})();
