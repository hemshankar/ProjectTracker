(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;
  var U = window.BoardUtil;
  var closeAllPopovers = U.closeAllPopovers;
  var hueValue = U.hueValue;

  // Mirrors the backend's `tasks_service.TASK_MOVABLE_STATUSES` — a task
  // mid-run or waiting on a human is tied to this board's chat/context, so
  // it can't be moved off until it's idle/done/stopped/failed/blocked.
  var MOVABLE_STATUSES = {idle: true, done: true, stopped: true, failed: true, blocked: true};

  function wire(btn, li, ctx, task){
    var board = ctx.board;
    var movable = MOVABLE_STATUSES[task.status];
    btn.disabled = ctx.readOnly || !movable;
    btn.title = ctx.readOnly ? "Move to another board"
      : !movable ? "Finish or stop this task before moving it to another board"
      : "Move to another board";
    btn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      if(btn.disabled) return;
      if(li.__dragMoved) return;

      var existing = li.querySelector(".task-move-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();

      var others = window.BoardState.state.boards.filter(function(b){
        return b.id !== board.id && !b.completed;
      });

      var pop = document.createElement("div");
      pop.className = "task-move-pop popover";

      if(!others.length){
        var empty = document.createElement("div");
        empty.className = "task-move-empty";
        empty.textContent = "No other boards to move to";
        pop.appendChild(empty);
      } else {
        var list = document.createElement("ul");
        list.className = "task-move-list";
        others.forEach(function(target){
          var item = document.createElement("li");
          item.className = "task-move-item";
          item.innerHTML = '<span class="dot"></span><span class="title"></span>';
          item.querySelector(".dot").style.background = hueValue(target.color);
          item.querySelector(".title").textContent = target.title || "Untitled board";
          item.addEventListener("pointerdown", function(ev){ ev.stopPropagation(); });
          item.addEventListener("click", function(ev){
            ev.stopPropagation();
            pop.remove();
            moveTaskToBoard(ctx, task, target.id);
          });
          list.appendChild(item);
        });
        pop.appendChild(list);
      }

      li.appendChild(pop);
    });
  }

  function moveTaskToBoard(ctx, task, targetBoardId){
    var sourceBoard = ctx.board;
    var targetBoard = window.BoardState.findBoard(targetBoardId);
    if(!targetBoard || targetBoardId === sourceBoard.id) return;

    var targetEl = document.querySelector('.card[data-id="' + targetBoardId + '"]');
    var targetCtx = targetEl && targetEl._ctx;

    sourceBoard.tasks = sourceBoard.tasks.filter(function(t){ return t.id !== task.id; });
    targetBoard.tasks.push(task);
    ctx.renderTasks();
    ctx.updateMeta();
    if(targetCtx){ targetCtx.renderTasks(); targetCtx.updateMeta(); }

    apiPost("/boards/" + sourceBoard.id + "/tasks/" + task.id + "/move", {targetBoardId: targetBoardId})
      .catch(function(){
        targetBoard.tasks = targetBoard.tasks.filter(function(t){ return t.id !== task.id; });
        sourceBoard.tasks.push(task);
        ctx.renderTasks();
        ctx.updateMeta();
        if(targetCtx){ targetCtx.renderTasks(); targetCtx.updateMeta(); }
      });
  }

  window.BoardTaskMove = { wire: wire };
})();
