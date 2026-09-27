(function(){
  "use strict";

  // One WebSocket per agent, multiplexing every visible board's status/task/
  // glow events onto a single connection — replaces what used to be one
  // EventSource per board, which was exhausting the browser's per-origin
  // connection limit once an agent had more than a handful of boards open.

  var socket = null;
  var generation = 0;
  var reconnectTimer = null;
  var reconnectDelayMs = 1000;
  var handlers = {};

  function wsUrl(agentId){
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/api/agents/" + encodeURIComponent(agentId) + "/ws";
  }

  function teardownSocket(){
    clearTimeout(reconnectTimer);
    if(socket){
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      try{ socket.close(); }catch(e){}
      socket = null;
    }
  }

  function openSocket(agentId, gen){
    var ws = new WebSocket(wsUrl(agentId));
    socket = ws;
    ws.onopen = function(){ reconnectDelayMs = 1000; };
    ws.onmessage = function(ev){
      var data;
      try{ data = JSON.parse(ev.data); }catch(e){ return; }
      var handler = data.boardId && handlers[data.boardId];
      if(handler) handler(data);
    };
    ws.onclose = function(){
      // A stale generation means a newer connect() already replaced this
      // socket (agent switch) — don't let this one's retry loop fight it.
      if(gen !== generation) return;
      reconnectTimer = setTimeout(function(){ openSocket(agentId, gen); }, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 15000);
    };
    ws.onerror = function(){ try{ ws.close(); }catch(e){} };
  }

  function connect(agentId){
    generation += 1;
    teardownSocket();
    handlers = {};
    reconnectDelayMs = 1000;
    if(agentId) openSocket(agentId, generation);
  }

  function on(boardId, handler){ handlers[boardId] = handler; }
  function off(boardId){ delete handlers[boardId]; }
  function reset(){ handlers = {}; }

  window.BoardSocket = { connect: connect, on: on, off: off, reset: reset };
})();
