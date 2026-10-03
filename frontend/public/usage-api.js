(function(){
  "use strict";

  // Thin wrapper over the core's usage endpoints. Throws {unavailable:true} on the structured 503
  // so callers can show "History unavailable" instead of a generic error.

  function agentId(){ return window.Identity.getCurrentAgentId(); }

  function qs(params){
    var q = new URLSearchParams();
    Object.keys(params || {}).forEach(function(k){
      if(params[k] !== null && params[k] !== undefined && params[k] !== "") q.set(k, params[k]);
    });
    var s = q.toString();
    return s ? "?" + s : "";
  }

  async function get(path){
    try{
      return await window.Identity.apiGet(path);
    }catch(e){
      if(e && e.status === 503) throw {unavailable: true, status: 503};
      throw e;
    }
  }

  function agentPath(suffix, params){ return "/agents/" + agentId() + "/usage/" + suffix + qs(params); }

  window.UsageApi = {
    boardTotal: function(boardId){ return get("/boards/" + boardId + "/usage"); },
    taskTotal: function(boardId, taskId){ return get("/boards/" + boardId + "/tasks/" + taskId + "/usage"); },
    taskTotals: function(boardId){ return get("/boards/" + boardId + "/usage/tasks"); },
    boardTotals: function(){ return get(agentPath("boards")); },
    summary: function(p){ return get(agentPath("summary", p)); },
    timeseries: function(p){ return get(agentPath("timeseries", p)); },
    breakdown: function(p){ return get(agentPath("breakdown", p)); },
    health: function(){ return get(agentPath("health")); },
    rows: function(p){ return get(agentPath("rows", p)); },
    exportUrl: function(p){ return "/api" + agentPath("export", p); }
  };
})();
