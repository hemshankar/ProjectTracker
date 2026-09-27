(function(){
  "use strict";

  var btn = document.getElementById("settings-btn");
  var modal = document.getElementById("settings-modal");
  var closeBtn = document.getElementById("settings-modal-close");
  var form = document.getElementById("settings-form");
  var savedMsg = document.getElementById("settings-saved-msg");
  var toolList = document.getElementById("settings-tool-list");
  var boardBudgetList = document.getElementById("settings-board-budget-list");

  var TOOL_LABELS = {gmail: "Gmail", calendar: "Calendar", slack: "Slack"};
  var toolRowState = {}; // toolType -> {enabledInput, rateLimitInput}

  var budgetCapInput = document.getElementById("settings-budget-cap");
  var budgetUnitSelect = document.getElementById("settings-budget-unit");

  var MODEL_LABELS = {
    "claude-opus-5": "Claude Opus 5",
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-haiku-4-5": "Claude Haiku 4.5"
  };
  var modelSelect = document.getElementById("settings-model-select");
  var maxTokensInput = document.getElementById("settings-max-tokens");
  var webSearchInput = document.getElementById("settings-web-search-enabled");
  var modelLimits = {};

  var maxConcurrentTasksInput = document.getElementById("settings-max-concurrent-tasks");
  var maxToolRoundsInput = document.getElementById("settings-max-tool-rounds");
  var maxToolRoundsCeiling = 100;
  var llmRetentionInput = document.getElementById("settings-llm-retention-days");
  var llmRetentionCeiling = 365;

  var agentIdentityForm = document.getElementById("agent-identity-form");
  var agentNameInput = document.getElementById("settings-agent-name");
  var agentDescriptionInput = document.getElementById("settings-agent-description");
  var agentSavedMsg = document.getElementById("settings-agent-saved-msg");

  var linksList = document.getElementById("settings-links-list");
  var linksForm = document.getElementById("settings-links-form");
  var linksTargetSelect = document.getElementById("settings-links-target-select");

  var TAB_PANELS = {
    config: document.getElementById("admin-tab-config"),
    activity: document.getElementById("admin-tab-activity"),
    traces: document.getElementById("admin-tab-traces")
  };
  var TAB_BUTTONS = {
    config: document.getElementById("admin-tab-btn-config"),
    activity: document.getElementById("admin-tab-btn-activity"),
    traces: document.getElementById("admin-tab-btn-traces")
  };

  function activateTab(name){
    Object.keys(TAB_PANELS).forEach(function(key){
      TAB_PANELS[key].hidden = key !== name;
      TAB_BUTTONS[key].classList.toggle("active", key === name);
      TAB_BUTTONS[key].setAttribute("aria-selected", key === name ? "true" : "false");
    });
    if(window.AdminConsole) window.AdminConsole.onTabActivated(name, window.Identity.getCurrentAgentId());
  }

  Object.keys(TAB_BUTTONS).forEach(function(key){
    TAB_BUTTONS[key].addEventListener("click", function(){ activateTab(key); });
  });

  function renderModelOptions(limits){
    modelLimits = limits || {};
    modelSelect.innerHTML = "";
    Object.keys(modelLimits).forEach(function(modelId){
      var option = document.createElement("option");
      option.value = modelId;
      option.textContent = MODEL_LABELS[modelId] || modelId;
      modelSelect.appendChild(option);
    });
  }

  function applyMaxTokensCeiling(){
    var ceiling = modelLimits[modelSelect.value];
    if(!ceiling) return;
    maxTokensInput.max = ceiling;
    if(parseInt(maxTokensInput.value, 10) > ceiling) maxTokensInput.value = ceiling;
  }

  modelSelect.addEventListener("change", applyMaxTokensCeiling);

  function updateVisibility(){
    var role = window.Identity && window.Identity.getCurrentAgentRole && window.Identity.getCurrentAgentRole();
    btn.hidden = role !== "admin";
    if(btn.hidden && !modal.hidden) close();
  }

  function renderToolRows(settings, connections){
    toolList.innerHTML = "";
    toolRowState = {};
    var connByType = {};
    connections.forEach(function(c){ connByType[c.toolType] = c; });

    Object.keys(TOOL_LABELS).forEach(function(toolType){
      var conn = connByType[toolType] || {connected: false};
      var toolSetting = (settings.tools && settings.tools[toolType]) || {enabled: false};
      var rateLimit = (settings.rateLimits && settings.rateLimits[toolType] && settings.rateLimits[toolType].capacityPerDay) || 50;

      var row = document.createElement("div");
      row.className = "settings-tool-row-full";

      var top = document.createElement("div");
      top.className = "settings-tool-row-top";

      var label = document.createElement("label");
      label.className = "settings-tool-row";
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = !!toolSetting.enabled;
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(" " + TOOL_LABELS[toolType]));
      top.appendChild(label);

      var connStatus = document.createElement("span");
      connStatus.className = "settings-tool-conn-status";
      connStatus.textContent = conn.connected ? ("Connected as " + (conn.label || "unknown")) : "Not connected";
      top.appendChild(connStatus);

      var actionBtn = document.createElement("button");
      actionBtn.type = "button";
      actionBtn.className = "btn settings-tool-connect-btn";
      if(conn.connected){
        actionBtn.textContent = "Disconnect";
        actionBtn.addEventListener("click", async function(){
          var agentId = window.Identity.getCurrentAgentId();
          try{
            await window.Identity.apiSend("DELETE", "/agents/" + agentId + "/tools/" + toolType);
            await open();
          }catch(e){}
        });
      } else {
        actionBtn.textContent = "Connect";
        actionBtn.addEventListener("click", function(){
          var agentId = window.Identity.getCurrentAgentId();
          window.location.href = "/api/agents/" + agentId + "/tools/" + toolType + "/connect";
        });
      }
      top.appendChild(actionBtn);
      row.appendChild(top);

      var rateRow = document.createElement("label");
      rateRow.className = "settings-tool-rate-row";
      rateRow.appendChild(document.createTextNode("Rate limit (per day) "));
      var rateInput = document.createElement("input");
      rateInput.type = "number";
      rateInput.min = "0";
      rateInput.step = "1";
      rateInput.value = rateLimit;
      rateRow.appendChild(rateInput);
      row.appendChild(rateRow);

      toolList.appendChild(row);
      toolRowState[toolType] = {enabledInput: checkbox, rateLimitInput: rateInput};
    });
  }

  function renderBoardBudgetRows(boards){
    boardBudgetList.innerHTML = "";
    boards.forEach(function(board){
      var row = document.createElement("div");
      row.className = "settings-board-budget-row";

      var title = document.createElement("span");
      title.className = "settings-board-budget-title";
      title.textContent = board.title || "Untitled board";
      row.appendChild(title);

      var input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "0.01";
      input.placeholder = "Inherit";
      input.value = (board.budgetCapUsd === null || board.budgetCapUsd === undefined) ? "" : board.budgetCapUsd;
      row.appendChild(input);

      var saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "btn";
      saveBtn.textContent = "Save";
      saveBtn.addEventListener("click", async function(){
        var capUsd = input.value === "" ? null : parseFloat(input.value);
        try{
          await window.Identity.apiSend("PATCH", "/boards/" + board.id + "/budget", {capUsd: capUsd});
          savedMsg.hidden = false;
        }catch(e){}
      });
      row.appendChild(saveBtn);

      boardBudgetList.appendChild(row);
    });
  }

  function fillForm(settings){
    var cap = settings.budget && settings.budget.capUsd;
    budgetCapInput.value = (cap === null || cap === undefined) ? "" : cap;
    budgetUnitSelect.value = (settings.budget && settings.budget.unit) || "usd";

    renderModelOptions(settings.modelLimits);
    var modelConfig = settings.modelConfig || {};
    modelSelect.value = modelConfig.model || modelSelect.value;
    applyMaxTokensCeiling();
    maxTokensInput.value = modelConfig.maxTokens || maxTokensInput.value;
    webSearchInput.checked = !!modelConfig.webSearchEnabled;

    var maxConcurrent = settings.concurrency && settings.concurrency.maxConcurrentTasks;
    maxConcurrentTasksInput.value = (maxConcurrent === null || maxConcurrent === undefined) ? "" : maxConcurrent;

    maxToolRoundsCeiling = settings.maxToolRoundsCeiling || maxToolRoundsCeiling;
    maxToolRoundsInput.max = maxToolRoundsCeiling;
    maxToolRoundsInput.value = (settings.execution && settings.execution.maxToolRounds) || maxToolRoundsInput.value;

    llmRetentionCeiling = settings.llmCallRetentionDaysCeiling || llmRetentionCeiling;
    llmRetentionInput.max = llmRetentionCeiling;
    llmRetentionInput.value = settings.llmCallRetentionDays || llmRetentionInput.value;
  }

  function renderLinksTargetOptions(){
    var agentId = window.Identity.getCurrentAgentId();
    var others = (window.Identity.getAgents() || []).filter(function(a){ return a.id !== agentId; });
    linksTargetSelect.innerHTML = "";
    others.forEach(function(a){
      var opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = a.name + (a.description ? " — " + a.description : " (no description set)");
      opt.title = a.description || "";
      linksTargetSelect.appendChild(opt);
    });
    linksForm.hidden = !others.length;
  }

  function renderLinks(links){
    linksList.innerHTML = "";
    if(!links.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "This Agent doesn't delegate to any other Agent yet.";
      linksList.appendChild(empty);
      return;
    }
    links.forEach(function(link){
      var row = document.createElement("div");
      row.className = "settings-link-row";
      var label = document.createElement("span");
      label.textContent = "Delegates to " + (link.toAgentName || link.toAgentId) +
        (link.toAgentDescription ? " — " + link.toAgentDescription : "");
      row.appendChild(label);
      var revokeBtn = document.createElement("button");
      revokeBtn.type = "button";
      revokeBtn.className = "btn";
      revokeBtn.textContent = "Revoke";
      revokeBtn.addEventListener("click", async function(){
        var agentId = window.Identity.getCurrentAgentId();
        try{
          await window.Identity.apiSend("DELETE", "/agents/" + agentId + "/links/" + link.toAgentId);
          await open();
        }catch(e){}
      });
      row.appendChild(revokeBtn);
      linksList.appendChild(row);
    });
  }

  linksForm.addEventListener("submit", async function(e){
    e.preventDefault();
    var agentId = window.Identity.getCurrentAgentId();
    var toAgentId = linksTargetSelect.value;
    if(!agentId || !toAgentId) return;
    try{
      await window.Identity.apiSend("POST", "/agents/" + agentId + "/links", {toAgentId: toAgentId});
      await open();
    }catch(err){}
  });

  function fillAgentIdentity(){
    var agentId = window.Identity.getCurrentAgentId();
    var agent = (window.Identity.getAgents() || []).find(function(a){ return a.id === agentId; });
    agentNameInput.value = agent ? agent.name || "" : "";
    agentDescriptionInput.value = agent ? agent.description || "" : "";
  }

  agentIdentityForm.addEventListener("submit", async function(e){
    e.preventDefault();
    var agentId = window.Identity.getCurrentAgentId();
    if(!agentId) return;
    agentSavedMsg.hidden = true;
    try{
      var updated = await window.Identity.apiSend("PATCH", "/agents/" + agentId, {
        name: agentNameInput.value.trim(),
        description: agentDescriptionInput.value.trim()
      });
      window.Identity.updateAgentLocal(updated);
      fillAgentIdentity();
      agentSavedMsg.hidden = false;
    }catch(err){}
  });

  async function open(){
    var agentId = window.Identity.getCurrentAgentId();
    if(!agentId) return;
    modal.hidden = false;
    savedMsg.hidden = true;
    agentSavedMsg.hidden = true;
    activateTab("config");
    fillAgentIdentity();
    try{
      var settings = await window.Identity.apiGet("/agents/" + agentId + "/settings");
      var connections = await window.Identity.apiGet("/agents/" + agentId + "/tools");
      var boards = await window.Identity.apiGet("/agents/" + agentId + "/boards");
      var links = await window.Identity.apiGet("/agents/" + agentId + "/links");
      fillForm(settings);
      renderToolRows(settings, connections);
      renderBoardBudgetRows(boards);
      renderLinksTargetOptions();
      renderLinks(links);
      if(window.AdminConsole) window.AdminConsole.setBoards(boards);
    }catch(e){
      close();
    }
  }

  function close(){ modal.hidden = true; }

  btn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  modal.addEventListener("mousedown", function(e){ if(e.target === modal) close(); });
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !modal.hidden) close();
  });

  form.addEventListener("submit", async function(e){
    e.preventDefault();
    var agentId = window.Identity.getCurrentAgentId();
    if(!agentId) return;
    var tools = {};
    var rateLimits = {};
    Object.keys(toolRowState).forEach(function(toolType){
      tools[toolType] = {enabled: toolRowState[toolType].enabledInput.checked};
      rateLimits[toolType] = {capacityPerDay: parseInt(toolRowState[toolType].rateLimitInput.value, 10) || 0};
    });
    var ceiling = modelLimits[modelSelect.value];
    var maxTokens = parseInt(maxTokensInput.value, 10) || 1;
    if(ceiling) maxTokens = Math.min(Math.max(maxTokens, 1), ceiling);
    var maxToolRounds = Math.min(Math.max(parseInt(maxToolRoundsInput.value, 10) || 1, 1), maxToolRoundsCeiling);
    var llmCallRetentionDays = Math.min(Math.max(parseInt(llmRetentionInput.value, 10) || 1, 1), llmRetentionCeiling);
    var payload = {
      tools: tools,
      rateLimits: rateLimits,
      budget: {
        capUsd: budgetCapInput.value === "" ? null : parseFloat(budgetCapInput.value),
        unit: budgetUnitSelect.value
      },
      modelConfig: {
        model: modelSelect.value,
        maxTokens: maxTokens,
        webSearchEnabled: webSearchInput.checked
      },
      concurrency: {
        maxConcurrentTasks: maxConcurrentTasksInput.value === "" ? null : parseInt(maxConcurrentTasksInput.value, 10)
      },
      execution: {
        maxToolRounds: maxToolRounds
      },
      llmCallRetentionDays: llmCallRetentionDays
    };
    savedMsg.hidden = true;
    try{
      var updated = await window.Identity.apiSend("PATCH", "/agents/" + agentId + "/settings", payload);
      fillForm(updated);
      savedMsg.hidden = false;
    }catch(err){}
  });

  if(window.Identity) window.Identity.onAgentChange(updateVisibility);

  window.Settings = {open: open};
})();
