(function(){
  "use strict";

  var API = "/api";
  var AGENT_KEY = "scatterboard.agentId.v1";

  var currentUser = null;
  var agents = [];
  var currentAgentId = null;
  var agentChangeListeners = [];

  var loginScreen = document.getElementById("login-screen");
  var appToolbar = document.getElementById("app-toolbar");
  var canvasScroll = document.getElementById("canvas-scroll");

  var switcherBtn = document.getElementById("agent-switcher-btn");
  var switcherLabel = document.getElementById("agent-switcher-label");
  var switcherAnchor = document.getElementById("agent-switcher-anchor");

  var userMenuBtn = document.getElementById("user-menu-btn");
  var userMenuAnchor = document.getElementById("user-menu-anchor");
  var userAvatarImg = document.getElementById("user-avatar-img");
  var userAvatarFallback = document.getElementById("user-avatar-fallback");

  var createModal = document.getElementById("agent-create-modal");
  var createCancelBtn = document.getElementById("agent-create-cancel");
  var createForm = document.getElementById("agent-create-form");
  var createInput = document.getElementById("agent-create-input");
  var createDescriptionInput = document.getElementById("agent-create-description");

  async function apiGet(path){
    var r = await fetch(API + path, {credentials: "same-origin"});
    if(!r.ok) throw {status: r.status};
    return r.json();
  }
  async function apiSend(method, path, body){
    var r = await fetch(API + path, {
      method: method,
      credentials: "same-origin",
      headers: body !== undefined ? {"Content-Type": "application/json"} : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
    if(!r.ok){
      var detail = null;
      try{ detail = (await r.json()).detail; }catch(e){}
      throw {status: r.status, detail: detail};
    }
    var ct = r.headers.get("content-type") || "";
    if(ct.indexOf("application/json") !== -1) return r.json();
    return null;
  }

  function closeSwitcherPop(){
    var pop = switcherAnchor.querySelector(".agent-switcher-pop");
    if(pop) pop.remove();
  }
  function closeUserPop(){
    var pop = userMenuAnchor.querySelector(".user-menu-pop");
    if(pop) pop.remove();
  }

  function renderUserMenu(){
    if(currentUser.pictureUrl){
      userAvatarImg.src = currentUser.pictureUrl;
      userAvatarImg.hidden = false;
      userAvatarFallback.hidden = true;
    } else {
      userAvatarFallback.textContent = (currentUser.name || currentUser.email || "?").charAt(0).toUpperCase();
      userAvatarFallback.hidden = false;
      userAvatarImg.hidden = true;
    }
  }

  function renderSwitcherLabel(){
    var agent = agents.find(function(a){ return a.id === currentAgentId; });
    switcherLabel.textContent = agent ? agent.name : "Select Workspace…";
  }

  function setCurrentAgent(agentId){
    currentAgentId = agentId;
    try{ localStorage.setItem(AGENT_KEY, agentId); }catch(e){}
    renderSwitcherLabel();
    agentChangeListeners.forEach(function(cb){ cb(agentId); });
  }

  function openCreateModal(){
    closeSwitcherPop();
    createModal.hidden = false;
    createCancelBtn.hidden = !agents.length;
    createInput.value = "";
    createDescriptionInput.value = "";
    createInput.focus();
  }
  function closeCreateModal(){ createModal.hidden = true; }
  createCancelBtn.addEventListener("click", closeCreateModal);

  function startRename(){
    var agent = agents.find(function(a){ return a.id === currentAgentId; });
    if(!agent) return;
    var input = document.createElement("input");
    input.type = "text";
    input.className = "agent-rename-input";
    input.value = agent.name;
    input.setAttribute("aria-label", "Workspace name");
    var done = false;
    function finish(save){
      if(done) return;
      done = true;
      var name = input.value.trim();
      var valid = name && name.split(/\s+/).length <= MAX_NAME_WORDS;
      switcherBtn.hidden = false;
      input.remove();
      if(!save || !valid || name === agent.name) return;
      apiSend("PATCH", "/agents/" + agent.id, {name: name, description: agent.description || ""})
        .then(function(updated){ window.Identity.updateAgentLocal(updated); })
        .catch(function(){});
    }
    input.addEventListener("keydown", function(e){
      if(e.key === "Enter"){ e.preventDefault(); finish(true); }
      else if(e.key === "Escape"){ finish(false); }
    });
    input.addEventListener("blur", function(){ finish(true); });
    switcherBtn.hidden = true;
    switcherAnchor.insertBefore(input, switcherBtn);
    input.focus();
    input.select();
  }

  function renderSwitcherPop(){
    closeUserPop();
    var existing = switcherAnchor.querySelector(".agent-switcher-pop");
    if(existing){ existing.remove(); return; }
    var pop = document.createElement("div");
    pop.className = "agent-switcher-pop popover";
    var list = document.createElement("ul");
    list.className = "agent-switcher-list";
    agents.forEach(function(a){
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "agent-switcher-item" + (a.id === currentAgentId ? " active" : "");
      btn.textContent = a.name;
      var badge = document.createElement("span");
      badge.className = "agent-role-badge";
      badge.textContent = a.myRole;
      btn.appendChild(badge);
      btn.addEventListener("click", function(){
        closeSwitcherPop();
        if(a.id !== currentAgentId) setCurrentAgent(a.id);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    pop.appendChild(list);
    var newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "agent-switcher-new";
    newBtn.textContent = "+ New Workspace";
    newBtn.addEventListener("click", openCreateModal);
    pop.appendChild(newBtn);
    var current = agents.find(function(a){ return a.id === currentAgentId; });
    if(current && current.myRole === "admin"){
      var renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.className = "agent-switcher-new agent-switcher-rename";
      renameBtn.textContent = "Rename this Workspace";
      renameBtn.addEventListener("click", function(){ closeSwitcherPop(); startRename(); });
      pop.appendChild(renameBtn);
    }
    switcherAnchor.appendChild(pop);
  }

  function renderUserPop(){
    closeSwitcherPop();
    var existing = userMenuAnchor.querySelector(".user-menu-pop");
    if(existing){ existing.remove(); return; }
    var pop = document.createElement("div");
    pop.className = "user-menu-pop popover";
    var info = document.createElement("div");
    info.className = "user-menu-info";
    info.innerHTML = "<strong>" + (currentUser.name || "") + "</strong><span>" + (currentUser.email || "") + "</span>";
    var signOut = document.createElement("button");
    signOut.type = "button";
    signOut.className = "user-menu-signout";
    signOut.textContent = "Sign out";
    signOut.addEventListener("click", async function(){
      try{ await apiSend("POST", "/auth/logout"); }catch(e){}
      window.location.reload();
    });
    pop.appendChild(info);
    pop.appendChild(signOut);
    userMenuAnchor.appendChild(pop);
  }

  switcherBtn.addEventListener("click", function(e){ e.stopPropagation(); renderSwitcherPop(); });
  userMenuBtn.addEventListener("click", function(e){ e.stopPropagation(); renderUserPop(); });
  document.addEventListener("pointerdown", function(e){
    if(!e.target.closest("#agent-switcher-anchor")) closeSwitcherPop();
    if(!e.target.closest("#user-menu-anchor")) closeUserPop();
  });

  var MAX_NAME_WORDS = 30;
  function wordCount(s){ return s.split(/\s+/).filter(Boolean).length; }
  createInput.addEventListener("input", function(){ createInput.setCustomValidity(""); });

  createForm.addEventListener("submit", async function(e){
    e.preventDefault();
    var name = createInput.value.trim();
    if(!name) return;
    if(wordCount(name) > MAX_NAME_WORDS){ createInput.setCustomValidity("Keep the name to ".concat(MAX_NAME_WORDS, " words or fewer.")); createInput.reportValidity(); return; }
    try{
      var agent = await apiSend("POST", "/agents", {name: name, description: createDescriptionInput.value.trim()});
      agents.push(agent);
      closeCreateModal();
      setCurrentAgent(agent.id);
    }catch(err){}
  });

  async function loadWorkspaces(){
    agents = await apiGet("/agents");
    var stored = null;
    try{ stored = localStorage.getItem(AGENT_KEY); }catch(e){}
    var match = agents.find(function(a){ return a.id === stored; });
    currentAgentId = match ? match.id : (agents[0] ? agents[0].id : null);
    renderSwitcherLabel();
  }

  function showLoggedOut(){
    loginScreen.hidden = false;
    appToolbar.hidden = true;
    canvasScroll.hidden = true;
  }

  async function init(){
    try{
      currentUser = await apiGet("/auth/me");
    }catch(e){
      showLoggedOut();
      return null;
    }

    renderUserMenu();
    await loadWorkspaces();

    if(!agents.length){
      appToolbar.hidden = false;
      canvasScroll.hidden = true;
      await new Promise(function(resolve){
        openCreateModal();
        createForm.addEventListener("submit", function handler(){
          createForm.removeEventListener("submit", handler);
          resolve();
        });
      });
    }

    loginScreen.hidden = true;
    appToolbar.hidden = false;
    canvasScroll.hidden = false;
    agentChangeListeners.forEach(function(cb){ cb(currentAgentId); });
    return {user: currentUser, agentId: currentAgentId};
  }

  window.Identity = {
    init: init,
    getCurrentAgentId: function(){ return currentAgentId; },
    getCurrentAgentRole: function(){
      var agent = agents.find(function(a){ return a.id === currentAgentId; });
      return agent ? agent.myRole : null;
    },
    getUser: function(){ return currentUser; },
    getWorkspaces: function(){ return agents.slice(); },
    updateAgentLocal: function(updated){
      var existing = agents.find(function(a){ return a.id === updated.id; });
      if(existing){
        existing.name = updated.name;
        existing.description = updated.description;
      }
      if(updated.id === currentAgentId) renderSwitcherLabel();
    },
    onAgentChange: function(cb){ agentChangeListeners.push(cb); },
    apiGet: apiGet,
    apiSend: apiSend
  };
})();
