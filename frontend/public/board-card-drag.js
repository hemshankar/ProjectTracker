(function(){
  "use strict";

  var apiPatch = window.BoardApi.apiPatch;
  var U = window.BoardUtil;
  var clamp = U.clamp;
  var CANVAS_W = U.CANVAS_W, CANVAS_H = U.CANVAS_H, MIN_W = U.MIN_W, MIN_H = U.MIN_H;

  function wire(ctx){
    var board = ctx.board, el = ctx.el, readOnly = ctx.readOnly;

    // ---- drag ----
    var header = el.querySelector(".card-header");
    header.addEventListener("pointerdown", function(e){
      if(readOnly) return;
      if(e.target.closest(".icon-btn, .popover")) return;
      var titleTarget = e.target.closest(".card-title");
      if(titleTarget && titleTarget.isContentEditable) return;
      e.preventDefault();
      window.BoardList.bringToFront(board, el);
      el.classList.add("dragging");
      var startX = e.clientX, startY = e.clientY;
      var origX = board.x, origY = board.y;
      header.setPointerCapture(e.pointerId);

      function onMove(ev){
        var zoom = window.BoardZoom.get();
        var dx = (ev.clientX - startX) / zoom, dy = (ev.clientY - startY) / zoom;
        var nx = clamp(origX + dx, 0, CANVAS_W - board.w);
        var ny = clamp(origY + dy, 0, CANVAS_H - board.h);
        board.x = nx; board.y = ny;
        el.style.left = nx + "px";
        el.style.top = ny + "px";
      }
      function onUp(ev){
        header.releasePointerCapture(e.pointerId);
        header.removeEventListener("pointermove", onMove);
        header.removeEventListener("pointerup", onUp);
        el.classList.remove("dragging");
        apiPatch("/boards/" + board.id, {x: board.x, y: board.y}).catch(function(){});
      }
      header.addEventListener("pointermove", onMove);
      header.addEventListener("pointerup", onUp);
    });

    // ---- resize ----
    var handle = el.querySelector(".resize-handle");
    if(readOnly) handle.hidden = true;
    handle.addEventListener("pointerdown", function(e){
      if(readOnly) return;
      e.preventDefault();
      e.stopPropagation();
      window.BoardList.bringToFront(board, el);
      el.classList.add("resizing");
      var startX = e.clientX, startY = e.clientY;
      var origW = board.w, origH = board.h;
      handle.setPointerCapture(e.pointerId);

      function onMove(ev){
        var zoom = window.BoardZoom.get();
        var dx = (ev.clientX - startX) / zoom, dy = (ev.clientY - startY) / zoom;
        var nw = clamp(origW + dx, MIN_W, CANVAS_W - board.x);
        var nh = clamp(origH + dy, MIN_H, CANVAS_H - board.y);
        board.w = nw; board.h = nh;
        el.style.width = nw + "px";
        el.style.height = nh + "px";
      }
      function onUp(ev){
        handle.releasePointerCapture(e.pointerId);
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        el.classList.remove("resizing");
        apiPatch("/boards/" + board.id, {w: board.w, h: board.h}).catch(function(){});
      }
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
    });

    el.addEventListener("pointerdown", function(e){
      // Clicks on buttons/inputs/popovers (delete, chat, checkboxes, task
      // text, etc.) don't need a z-bump — and bumping here raced the
      // board-delete confirm click against its DELETE request, since this
      // capture-phase listener fires before any bubble-phase stopPropagation.
      if(e.target.closest("button, input, textarea, a, .popover")) return;
      window.BoardList.bringToFront(board, el);
    }, {capture:true});
  }

  window.BoardCardDrag = { wire: wire };
})();
