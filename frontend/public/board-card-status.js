(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;
  var API = window.BoardApi.API;
  var findTask = window.BoardState.findTask;

  // What each glow state means, in words — the ring color alone doesn't
  // say why a board is glowing, so the banner spells it out. `cls` is the
  // hyphenated suffix the CSS rules use (`.glow-banner-needs-reply`), kept
  // separate from the backend's own underscored `needs_reply` spelling.
  var GLOW_MESSAGES = {
    processing:      {cls: "processing",      text: "Working on it&hellip;"},
    done:            {cls: "done",            text: "All tasks done"},
    needs_reply:     {cls: "needs-reply",     text: "Waiting on your reply"},
    needs_approval:  {cls: "needs-approval",  text: "Needs your approval"}
  };

  function wire(ctx){
    var board = ctx.board, el = ctx.el, readOnly = ctx.readOnly;
    var startBtn = el.querySelector(".start-btn");
    var stopBtn = el.querySelector(".stop-btn");
    var glowBanner = el.querySelector(".glow-banner");

    glowBanner.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    glowBanner.addEventListener("click", function(e){
      e.stopPropagation();
      window.BoardChat.open(board.id);
    });

    function updateRunUI(){
      var status = board.status || "idle";
      var active = status === "queued" || status === "running";
      var budgetStopped = status === "stopped" && board.statusReason === "budget_exceeded";
      // The four-state glow taxonomy (Phase 7) is the single source of
      // truth for the board's ring color — `board.glow` is derived and
      // persisted server-side (see `execution.glow`), never re-derived here.
      var glowState = board.glow || "none";
      el.classList.toggle("glow-processing", glowState === "processing");
      el.classList.toggle("glow-done", glowState === "done");
      el.classList.toggle("glow-needs-reply", glowState === "needs_reply");
      el.classList.toggle("glow-needs-approval", glowState === "needs_approval");
      el.classList.toggle("run-stopped-budget", budgetStopped);
      el.title = budgetStopped ? "Stopped: budget exceeded" : "";
      startBtn.hidden = readOnly || active;
      stopBtn.hidden = readOnly || !active;

      var message = GLOW_MESSAGES[glowState];
      glowBanner.hidden = !message;
      if(message){
        glowBanner.className = "glow-banner glow-banner-" + message.cls;
        glowBanner.innerHTML = message.text;
      }
    }

    startBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    startBtn.addEventListener("click", function(e){
      e.stopPropagation();
      if(readOnly) return;
      apiPost("/boards/" + board.id + "/start").then(function(res){
        board.status = res.status;
        updateRunUI();
      }).catch(function(){});
    });

    stopBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    stopBtn.addEventListener("click", function(e){
      e.stopPropagation();
      if(readOnly) return;
      apiPost("/boards/" + board.id + "/stop").catch(function(){});
    });

    updateRunUI();

    var eventSource = null;
    try{
      eventSource = new EventSource(API + "/boards/" + board.id + "/events");
      eventSource.onmessage = function(ev){
        var data;
        try{ data = JSON.parse(ev.data); }catch(err){ return; }
        if(data.taskId){
          var t = findTask(board, data.taskId);
          if(!t) return;
          t.status = data.status;
          t.done = data.status === "done";
          if("statusReason" in data) t.statusReason = data.statusReason;
          ctx.renderTasks();
          ctx.updateMeta();
          window.BoardTaskDetail.refreshIfOpen(board.id, data.taskId);
        } else if(data.boardId){
          if("status" in data){
            board.status = data.status;
            board.statusReason = data.statusReason;
          }
          if("glow" in data){
            board.glow = data.glow;
          }
          if(data.llmCall && window.AdminConsole){
            window.AdminConsole.onLiveLlmCall(data.boardId, data.llmCall);
          }
          updateRunUI();
        }
      };
      window.BoardState.state.activeBoardStreams.push(eventSource);
    }catch(e){}

    ctx.eventSource = eventSource;
  }

  window.BoardCardStatus = { wire: wire };
})();
