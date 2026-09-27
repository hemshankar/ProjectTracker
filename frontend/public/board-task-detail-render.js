(function(){
  "use strict";

  var renderMarkdown = window.BoardMarkdown.renderMarkdown;

  function buildClarificationRequestEl(m){
    var payload = m.payload || {};
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = renderMarkdown(m.text || payload.question || "");
    col.appendChild(bubble);
    var card = document.createElement("div");
    card.className = "action-card";
    var status = document.createElement("div");
    if(payload.status === "answered"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Answered" + (payload.answer ? " — " + payload.answer : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting for your answer — reply below";
    }
    card.appendChild(status);
    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildManualHoldEl(m){
    var payload = m.payload || {};
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = renderMarkdown(m.text || payload.note || "");
    col.appendChild(bubble);
    var card = document.createElement("div");
    card.className = "action-card";
    var status = document.createElement("div");
    if(payload.status === "resolved"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Resolved" + (payload.resolution ? " — " + payload.resolution : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting on an external reply — reply below once you know what happened";
    }
    card.appendChild(status);
    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildOwnTaskMessageEl(board, chat, m){
    if(m.type === "action_request") return window.BoardChatMessages.buildActionRequestEl(board, chat, m);
    if(m.type === "clarification_request") return buildClarificationRequestEl(m);
    if(m.type === "manual_hold") return buildManualHoldEl(m);
    return buildTaskDetailMessageEl(m);
  }

  function buildTaskDetailMessageEl(m){
    if(m.type === "delegation_request") return window.BoardChatMessages.buildDelegationRequestEl(m);
    if(m.type === "clarification_request") return buildClarificationRequestEl(m);
    if(m.type === "manual_hold") return buildManualHoldEl(m);
    if(m.type === "action_request"){
      var payload = m.payload || {};
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
      var card = document.createElement("div");
      card.className = "action-card";
      var desc = document.createElement("div");
      desc.className = "action-card-desc";
      desc.textContent = payload.description || ("Proposed action: " + payload.tool);
      card.appendChild(desc);
      var status = document.createElement("div");
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
      card.appendChild(status);
      col.appendChild(card);
      wrap.appendChild(col);
      return wrap;
    }
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + m.role;
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = m.text ? renderMarkdown(m.text) : "";
    wrap.appendChild(bubble);
    return wrap;
  }

  function buildCountsSummary(counts){
    var el = document.createElement("div");
    el.className = "task-detail-counts";
    var parts = [
      (counts.agents || 0) + " agent" + (counts.agents === 1 ? "" : "s"),
      (counts.subAgents || 0) + " sub-agent" + (counts.subAgents === 1 ? "" : "s"),
      (counts.peerAgents || 0) + " peer Agent" + (counts.peerAgents === 1 ? "" : "s"),
    ];
    el.textContent = parts.join(" · ") + " have worked this task";
    return el;
  }

  function buildTranscriptEl(transcript){
    var list = document.createElement("div");
    list.className = "transcript-list";
    (transcript || []).forEach(function(entry){
      var row = document.createElement("div");
      row.className = "transcript-entry transcript-role-" + (entry.role || "text");
      var roleLabel = document.createElement("span");
      roleLabel.className = "transcript-role-label";
      roleLabel.textContent = entry.role === "tool_call" ? "tool call"
        : entry.role === "tool_result" ? "tool result"
        : entry.role;
      row.appendChild(roleLabel);
      var textEl = document.createElement("span");
      textEl.className = "transcript-text";
      var isRawText = entry.role === "tool_call" || entry.role === "tool_result";
      if(isRawText){
        textEl.textContent = entry.text || "";
      } else {
        textEl.innerHTML = entry.text ? renderMarkdown(entry.text) : "";
      }
      row.appendChild(textEl);
      list.appendChild(row);
    });
    return list;
  }

  function buildSubAgentSection(subAgentRuns){
    var details = document.createElement("details");
    details.className = "task-detail-collapsible";
    var summary = document.createElement("summary");
    summary.textContent = "Sub-agent activity (" + subAgentRuns.length + ")";
    details.appendChild(summary);
    if(!subAgentRuns.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "No sub-agents were spun up for this task.";
      details.appendChild(empty);
      return details;
    }
    subAgentRuns.forEach(function(run){
      var card = document.createElement("div");
      card.className = "subagent-run-card";
      var header = document.createElement("div");
      header.className = "subagent-run-header";
      header.textContent = (run.instructions || "Sub-agent") + " — " + run.status;
      card.appendChild(header);
      if(run.allowedTools && run.allowedTools.length){
        var toolsEl = document.createElement("div");
        toolsEl.className = "subagent-run-tools";
        toolsEl.textContent = "Tools: " + run.allowedTools.join(", ");
        card.appendChild(toolsEl);
      }
      card.appendChild(buildTranscriptEl(run.transcript));
      details.appendChild(card);
    });
    return details;
  }

  function buildPeerAgentSection(peerDelegations){
    var details = document.createElement("details");
    details.className = "task-detail-collapsible";
    var summary = document.createElement("summary");
    summary.textContent = "Peer Agent conversation (" + peerDelegations.length + ")";
    details.appendChild(summary);
    if(!peerDelegations.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "This task was never delegated to another Agent.";
      details.appendChild(empty);
      return details;
    }
    peerDelegations.forEach(function(peer){
      var card = document.createElement("div");
      card.className = "subagent-run-card";
      var header = document.createElement("div");
      header.className = "subagent-run-header";
      header.textContent = "Delegated to " + (peer.toAgentName || peer.toAgentId) + " — " + peer.status;
      card.appendChild(header);
      if(!peer.accessible){
        var restricted = document.createElement("p");
        restricted.className = "settings-hint";
        restricted.textContent = "You don't have access to that Agent's board, so its conversation isn't shown here.";
        card.appendChild(restricted);
      } else if(!peer.messages.length){
        var waiting = document.createElement("p");
        waiting.className = "settings-hint";
        waiting.textContent = "No activity yet on the delegated task.";
        card.appendChild(waiting);
      } else {
        peer.messages.forEach(function(m){ card.appendChild(buildTaskDetailMessageEl(m)); });
      }
      details.appendChild(card);
    });
    return details;
  }

  window.BoardTaskDetailRender = {
    buildOwnTaskMessageEl: buildOwnTaskMessageEl,
    buildTaskDetailMessageEl: buildTaskDetailMessageEl,
    buildCountsSummary: buildCountsSummary,
    buildSubAgentSection: buildSubAgentSection,
    buildPeerAgentSection: buildPeerAgentSection
  };
})();
