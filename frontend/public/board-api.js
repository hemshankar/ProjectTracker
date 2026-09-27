(function(){
  "use strict";

  var API = "/api";

  async function apiGet(path){
    var r = await fetch(API + path);
    if(!r.ok) throw new Error("GET " + path + " failed");
    return r.json();
  }
  async function apiSend(method, path, body){
    var r = await fetch(API + path, {
      method: method,
      headers: body !== undefined ? {"Content-Type": "application/json"} : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
    if(!r.ok) throw new Error(method + " " + path + " failed");
    var ct = r.headers.get("content-type") || "";
    if(ct.indexOf("application/json") !== -1) return r.json();
    return null;
  }
  var apiPost = function(path, body){ return apiSend("POST", path, body === undefined ? {} : body); };
  var apiPatch = function(path, body){ return apiSend("PATCH", path, body); };
  var apiDelete = function(path){ return apiSend("DELETE", path); };

  function agentQS(){
    var id = window.Identity && window.Identity.getCurrentAgentId();
    return id ? ("?agentId=" + encodeURIComponent(id)) : "";
  }

  async function downloadFromApi(path, filename){
    var r = await fetch(API + path);
    if(!r.ok) throw new Error("download failed");
    var blob = await r.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function(){ URL.revokeObjectURL(url); }, 4000);
  }

  window.BoardApi = {
    API: API,
    apiGet: apiGet,
    apiPost: apiPost,
    apiPatch: apiPatch,
    apiDelete: apiDelete,
    agentQS: agentQS,
    downloadFromApi: downloadFromApi
  };
})();
