(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;

  // Mirrors the backend's `tasks_service.TASK_MOVABLE_STATUSES` — a task
  // mid-run or waiting on a human is tied to this board's chat/context, so
  // it can't be dragged off until it's idle/done/stopped/failed/blocked.
  var MOVABLE_STATUSES = {idle: true, done: true, stopped: true, failed: true, blocked: true};
  var DRAG_THRESHOLD = 6;

  // Drag starts only from the move button (press-and-hold) — a plain click
  // on it opens the board picker instead (see `board-task-move.js`), and the
  // rest of the row is left free for its own click/edit/check interactions.
  function wire(btn, li, ctx, task){
    if(ctx.readOnly) return;

    btn.addEventListener("pointerdown", function(e){
      e.stopPropagation();
      if(btn.disabled) return;
      if(!MOVABLE_STATUSES[task.status]) return;

      var startX = e.clientX, startY = e.clientY;
      var pointerId = e.pointerId;
      var dragging = false;
      var ghost = null;
      var hoverCard = null;

      function moveGhost(x, y){
        ghost.style.left = x + "px";
        ghost.style.top = y + "px";
      }

      function startDrag(){
        dragging = true;
        li.__dragMoved = true;
        li.classList.add("task-dragging");
        var rect = li.getBoundingClientRect();
        ghost = li.cloneNode(true);
        ghost.classList.add("task-drag-ghost");
        ghost.style.width = rect.width + "px";
        document.body.appendChild(ghost);
        moveGhost(startX, startY);
      }

      function updateHover(x, y){
        var found = null;
        document.querySelectorAll(".card").forEach(function(cardEl){
          if(cardEl === ctx.el) return;
          var r = cardEl.getBoundingClientRect();
          if(x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) found = cardEl;
        });
        if(hoverCard && hoverCard !== found) hoverCard.classList.remove("task-drop-target");
        if(found) found.classList.add("task-drop-target");
        hoverCard = found;
      }

      function onMove(ev){
        var dx = ev.clientX - startX, dy = ev.clientY - startY;
        if(!dragging && Math.hypot(dx, dy) > DRAG_THRESHOLD) startDrag();
        if(dragging){
          moveGhost(ev.clientX, ev.clientY);
          updateHover(ev.clientX, ev.clientY);
        }
      }

      function cleanup(){
        btn.removeEventListener("pointermove", onMove);
        btn.removeEventListener("pointerup", onUp);
        btn.removeEventListener("pointercancel", onCancel);
        try{ btn.releasePointerCapture(pointerId); }catch(err){}
        if(ghost){ ghost.remove(); ghost = null; }
        if(hoverCard){ hoverCard.classList.remove("task-drop-target"); hoverCard = null; }
        li.classList.remove("task-dragging");
        if(dragging) setTimeout(function(){ li.__dragMoved = false; }, 0);
      }

      function onUp(){
        var targetEl = dragging ? hoverCard : null;
        cleanup();
        if(targetEl) moveTaskToBoard(ctx, task, targetEl.dataset.id);
      }

      function onCancel(){ cleanup(); }

      btn.setPointerCapture(pointerId);
      btn.addEventListener("pointermove", onMove);
      btn.addEventListener("pointerup", onUp);
      btn.addEventListener("pointercancel", onCancel);
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

  window.BoardTaskDrag = { wire: wire };
})();
