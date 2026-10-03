(function(){
  "use strict";

  // Standalone alerts page. Admin-only: the API answers 403 to everyone else.
  var REFRESH_MS = 30000;
  var agent = new URLSearchParams(location.search).get("agent");
  var listEl = document.getElementById("alerts-list");
  var resolvedBox = document.getElementById("alerts-show-resolved");

  try{
    var theme = localStorage.getItem("scatterboard.theme.v1");
    if(theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
  }catch(e){}

  function path(suffix){ return "/api/agents/" + encodeURIComponent(agent) + "/alerts" + suffix; }

  function when(ms){ return ms ? new Date(ms).toLocaleString() : ""; }

  function text(tag, cls, value){
    var el = document.createElement(tag);
    if(cls) el.className = cls;
    el.textContent = value;
    return el;
  }

  function card(a){
    var el = text("article", "alert-card " + a.severity + (a.status === "resolved" ? " resolved" : ""), "");
    var top = text("div", "alert-top", "");
    top.appendChild(text("span", "alert-title", a.title));
    top.appendChild(text("span", "alert-tag", a.status === "resolved" ? "Resolved" : a.severity === "error" ? "Error" : "Warning"));
    if(a.status === "open" && a.acknowledgedAt) top.appendChild(text("span", "alert-tag", "Acknowledged"));
    if(a.status === "open" && !a.acknowledgedAt){
      var ack = text("button", "btn", "Acknowledge");
      ack.type = "button";
      ack.addEventListener("click", function(){ acknowledge(a.key, ack); });
      top.appendChild(ack);
    }
    el.appendChild(top);
    el.appendChild(text("div", "alert-msg", a.message));
    var meta = "First seen " + when(a.firstSeenAt) + " · last seen " + when(a.lastSeenAt) + " · " + a.count + "×";
    if(a.resolvedAt) meta += " · resolved " + when(a.resolvedAt);
    el.appendChild(text("div", "alert-meta", meta));
    return el;
  }

  function render(alerts){
    listEl.innerHTML = "";
    if(!alerts.length){
      listEl.appendChild(text("div", "alerts-empty", resolvedBox.checked ? "No alerts yet." : "No open alerts. Usage accounting is healthy."));
      return;
    }
    alerts.forEach(function(a){ listEl.appendChild(card(a)); });
  }

  async function request(method, suffix){
    var r = await fetch(path(suffix), {method: method, credentials: "same-origin"});
    if(!r.ok) throw {status: r.status};
    return r.status === 204 ? null : r.json();
  }

  function fail(e){
    listEl.innerHTML = "";
    var forbidden = e && (e.status === 403 || e.status === 401);
    listEl.appendChild(text("div", "alerts-error", !agent ? "Open this page from the bell on the boards screen."
      : forbidden ? "Only workspace admins can view alerts." : "Couldn't load alerts. Retrying…"));
  }

  async function load(){
    if(!agent) return fail();
    try{ render(await request("GET", resolvedBox.checked ? "?includeResolved=true" : "")); }
    catch(e){ fail(e); }
  }

  async function acknowledge(key, btn){
    btn.disabled = true;
    try{ await request("POST", "/" + encodeURIComponent(key) + "/acknowledge"); }catch(e){}
    load();
  }

  document.getElementById("alerts-back").href = "/";
  resolvedBox.addEventListener("change", load);
  load();
  setInterval(load, REFRESH_MS);
})();
