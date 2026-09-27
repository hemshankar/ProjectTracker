(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPost = window.BoardApi.apiPost;
  var apiPatch = window.BoardApi.apiPatch;
  var API = window.BoardApi.API;
  var findBoard = window.BoardState.findBoard;
  var setModalTitle = window.BoardUtil.setModalTitle;
  var hueValue = window.BoardUtil.hueValue;
  var closeAllPopovers = window.BoardUtil.closeAllPopovers;

  var chatModal = document.getElementById("chat-modal");
  var chatModalTitle = document.getElementById("chat-modal-title");
  var chatModalDot = document.getElementById("chat-modal-dot");
  var chatModalClose = document.getElementById("chat-modal-close");
  var chatModalBody = document.getElementById("chat-modal-body");
  var chatForm = document.getElementById("chat-modal-form");
  var chatTextarea = document.getElementById("chat-modal-textarea");
  var chatSendBtn = document.getElementById("chat-modal-send");
  var chatNewBtn = document.getElementById("chat-new-btn");
  var chatHistoryAnchor = document.getElementById("chat-history-anchor");
  var chatHistoryBtn = document.getElementById("chat-history-btn");

  var chatBoardId = null;
  var chatAbortController = null;

  function abortActiveChatStream(){
    if(chatAbortController){ chatAbortController.abort(); chatAbortController = null; }
  }

  function setChatBusy(busy){
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
    var sorted = (board.chats || []).slice().sort(function(a, b){ return b.createdAt - a.createdAt; });
    sorted.forEach(function(chat){ list.appendChild(buildChatHistoryItem(board, chat)); });
  }

  async function ensureChatsLoaded(board){
    if(board._chatsLoaded) return;
    try{
      var data = await apiGet("/boards/" + board.id + "/chats");
      board.chats = data.chats || [];
      board.activeChatId = data.activeChatId;
      if(!board.chats.length){
        var chat = await apiPost("/boards/" + board.id + "/chats");
        board.chats = [chat];
        board.activeChatId = chat.id;
      }
      board._chatsLoaded = true;
    }catch(e){
      board.chats = board.chats || [];
    }
  }

  async function startNewChat(boardId){
    var board = findBoard(boardId);
    if(!board) return;
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

  async function openChatModal(boardId){
    var board = findBoard(boardId);
    if(!board) return;
    if(chatBoardId !== boardId) abortActiveChatStream();
    chatBoardId = boardId;
    setModalTitle(chatModalTitle, board.title || "Untitled board");
    chatModalDot.style.background = hueValue(board.color);
    chatModal.hidden = false;
    closeAllPopovers();
    setChatBusy(!!chatAbortController);
    chatModalBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    await ensureChatsLoaded(board);
    if(chatBoardId !== boardId) return;
    renderChatMessages();
    chatTextarea.value = "";
    autoSizeChatTextarea();
    chatTextarea.focus();
  }

  function closeChatModal(){
    abortActiveChatStream();
    closeAllPopovers();
    chatModal.hidden = true;
    chatBoardId = null;
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
      if(chatAbortController){ chatAbortController.abort(); return; }
      sendChatMessage();
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
      if(chatBoardId) startNewChat(chatBoardId);
    });

    chatHistoryBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatHistoryBtn.addEventListener("click", function(e){
      e.stopPropagation();
      var existing = chatHistoryAnchor.querySelector(".chat-history-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "chat-history-pop popover";
      pop.innerHTML = '<div class="completed-pop-header"><span>Previous chats</span></div><ul class="chat-history-list"></ul>';
      chatHistoryAnchor.appendChild(pop);
      renderChatHistoryPop();
    });
  }

  window.BoardChat = {
    open: openChatModal,
    init: wireChatModal,
    notifyBoardUpdated: function(boardId){
      if(chatBoardId === boardId) renderChatMessages();
    }
  };
})();
