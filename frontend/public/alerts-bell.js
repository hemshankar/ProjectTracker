(function(){
  "use strict";

  // Toolbar bell: shown to workspace admins, badge = open alerts nobody has acknowledged yet.
  // Polls the cheap summary endpoint; the alerts page has the detail.

  var POLL_MS = 60000;
  var btn = document.getElementById("alerts-btn");
  var badge = document.getElementById("alerts-count");
  var timer = null;

  function agentId(){ return window.Identity.getCurrentAgentId(); }

  function render(summary){
    var n = summary ? summary.unacknowledged : 0;
    badge.hidden = n === 0;
    badge.textContent = n > 99 ? "99+" : String(n);
    badge.classList.toggle("alerts-badge-warning", !!summary && summary.severity === "warning");
    btn.title = n ? n + " open alert" + (n === 1 ? "" : "s") : "System alerts";
  }

  async function refresh(){
    var id = agentId();
    if(!id || window.Identity.getCurrentAgentRole() !== "admin"){ btn.hidden = true; return; }
    btn.hidden = false;
    btn.href = "/alerts.html?agent=" + encodeURIComponent(id);
    try{
      render(await window.Identity.apiGet("/agents/" + id + "/alerts/summary"));
    }catch(e){ /* bell is best-effort: keep the last badge */ }
  }

  function start(){
    refresh();
    if(timer) clearInterval(timer);
    timer = setInterval(refresh, POLL_MS);
  }

  window.Identity.onAgentChange(start);
  start();
  window.AlertsBell = {refresh: refresh};
})();
