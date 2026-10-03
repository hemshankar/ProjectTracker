(function(){
  "use strict";

  // Renders the connected accounts of one tool inside a settings tool row.
  // onChange() is called after any change so the caller can reload.

  function el(tag, className, text){
    var node = document.createElement(tag);
    if(className) node.className = className;
    if(text !== undefined) node.textContent = text;
    return node;
  }

  function button(text, onClick){
    var b = el("button", "btn settings-tool-connect-btn", text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function toolUrl(agentId, suffix){
    return "/agents/" + agentId + "/tools/" + suffix;
  }

  function startConnect(agentId, toolType, personal){
    var label = window.prompt("Name this account (for example its email address):", "");
    if(label === null) return;
    var query = [];
    if(personal) query.push("personal=true");
    if(label.trim()) query.push("label=" + encodeURIComponent(label.trim()));
    window.location.href = "/api/agents/" + agentId + "/tools/" + toolType + "/connect" +
      (query.length ? "?" + query.join("&") : "");
  }

  function accountRow(agentId, conn, canManage, onChange){
    var row = el("div", "settings-conn-account");
    row.appendChild(el("span", "settings-conn-label", conn.label || "Connected"));
    row.appendChild(el("span", "settings-conn-badge", conn.ownerUserId ? "Personal" : "Shared"));
    if(conn.status === "expired") row.appendChild(el("span", "settings-conn-badge settings-conn-badge-warn", "Reconnect needed"));
    if(conn.isDefault) row.appendChild(el("span", "settings-conn-badge settings-conn-badge-default", "Default"));
    var actions = el("span", "settings-conn-actions");
    if(canManage && !conn.isDefault && !conn.ownerUserId && conn.connected){
      actions.appendChild(button("Make default", async function(){
        try{ await window.Identity.apiSend("POST", toolUrl(agentId, "by-id/" + conn.connectionId + "/default")); }catch(e){}
        onChange();
      }));
    }
    actions.appendChild(button("Disconnect", async function(){
      try{ await window.Identity.apiSend("DELETE", toolUrl(agentId, "by-id/" + conn.connectionId)); }catch(e){}
      onChange();
    }));
    row.appendChild(actions);
    return row;
  }

  // connections: every entry for this tool (placeholders without connectionId are ignored)
  function render(container, agentId, toolType, connections, onChange){
    container.innerHTML = "";
    var accounts = connections.filter(function(c){ return c.connectionId; });
    var canManage = window.Identity.getCurrentAgentRole && window.Identity.getCurrentAgentRole() === "admin";
    if(!accounts.length) container.appendChild(el("span", "settings-tool-conn-status", "Not connected"));
    accounts.forEach(function(c){ container.appendChild(accountRow(agentId, c, canManage, onChange)); });
    var bar = el("div", "settings-conn-add");
    bar.appendChild(button(accounts.length ? "Connect another account" : "Connect", function(){
      startConnect(agentId, toolType, false);
    }));
    bar.appendChild(button("Connect my own account", function(){ startConnect(agentId, toolType, true); }));
    container.appendChild(bar);
  }

  window.SettingsConnections = {render: render};
})();
