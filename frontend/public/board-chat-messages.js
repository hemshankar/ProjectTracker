(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;
  var renderMarkdown = window.BoardMarkdown.renderMarkdown;

  function buildActionRequestEl(board, chat, m){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";

    if(m.text){
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.innerHTML = renderMarkdown(m.text);
      col.appendChild(bubble);
    }

    var payload = m.payload || {};
    var card = document.createElement("div");
    card.className = "action-card";

    var desc = document.createElement("div");
    desc.className = "action-card-desc";
    desc.textContent = payload.description || ("Proposed action: " + payload.tool);
    card.appendChild(desc);

    var status = document.createElement("div");
    status.className = "action-card-status action-status-" + (payload.status || "pending");
    card.appendChild(status);

    function renderStatus(){
      if(payload.status === "approved"){
        status.className = "action-card-status action-status-approved";
        status.textContent = "Approved" + (payload.result ? " — " + payload.result : "");
      } else if(payload.status === "rejected"){
        status.className = "action-card-status action-status-rejected";
        status.textContent = "Rejected";
      } else {
        status.className = "action-card-status action-status-pending";
        status.textContent = "Waiting for approval";
      }
    }
    renderStatus();

    if(payload.status === "pending"){
      var actions = document.createElement("div");
      actions.className = "action-card-buttons";
      var approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.className = "action-approve-btn";
      approveBtn.textContent = "Approve";
      var rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "action-reject-btn";
      rejectBtn.textContent = "Reject";

      function decide(approved){
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        status.textContent = approved ? "Approving…" : "Rejecting…";
        var path = "/boards/" + board.id + "/chats/" + chat.id + "/messages/" + m.id + "/" + (approved ? "approve" : "reject");
        apiPost(path).then(function(resp){
          board.chats = resp.chats;
          board.activeChatId = resp.activeChatId;
          board.tasks = resp.tasks;
          board.status = resp.status;
          window.BoardChat.notifyBoardUpdated(board.id);
          window.BoardTaskDetail.refreshIfOpen(board.id, (m.payload || {}).taskId);
        }).catch(function(){
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
          renderStatus();
        });
      }

      approveBtn.addEventListener("click", function(){ decide(true); });
      rejectBtn.addEventListener("click", function(){ decide(false); });
      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      card.appendChild(actions);
    }

    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildDelegationRequestEl(m){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";

    if(m.text){
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.innerHTML = renderMarkdown(m.text);
      col.appendChild(bubble);
    }

    var payload = m.payload || {};
    var card = document.createElement("div");
    card.className = "action-card";

    var desc = document.createElement("div");
    desc.className = "action-card-desc";
    desc.textContent = "Delegated to " + (payload.targetAgentName || "another Agent") + ": " + (payload.request || "");
    card.appendChild(desc);

    var status = document.createElement("div");
    if(payload.status === "resolved"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Resolved" + (payload.result ? " — " + payload.result : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting on delegated Agent…";
    }
    card.appendChild(status);

    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildChatMessageEl(board, chat, m){
    if(m.type === "action_request") return buildActionRequestEl(board, chat, m);
    if(m.type === "delegation_request") return buildDelegationRequestEl(m);
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + m.role;
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = m.text ? renderMarkdown(m.text) : "";
    wrap.appendChild(bubble);
    return wrap;
  }

  window.BoardChatMessages = {
    buildActionRequestEl: buildActionRequestEl,
    buildDelegationRequestEl: buildDelegationRequestEl,
    buildChatMessageEl: buildChatMessageEl
  };
})();
