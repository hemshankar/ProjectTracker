(function(){
  "use strict";

  var apiPatch = window.BoardApi.apiPatch;
  var apiDelete = window.BoardApi.apiDelete;
  var U = window.BoardUtil;
  var hueValue = U.hueValue;
  var wireInlineEditable = U.wireInlineEditable;
  var closeAllPopovers = U.closeAllPopovers;

  function createCard(board){
    var readOnly = board.myRole === "viewer";
    var el = document.createElement("div");
    el.className = "card";
    el.dataset.id = board.id;
    el.style.left = board.x + "px";
    el.style.top = board.y + "px";
    el.style.width = board.w + "px";
    el.style.height = board.h + "px";
    el.style.zIndex = board.z;
    el.style.setProperty("--card-hue", hueValue(board.color));

    el.innerHTML =
      '<div class="card-topbar"></div>' +
      '<div class="card-header">' +
        '<div class="card-title" spellcheck="false"></div>' +
        '<div class="card-header-actions">' +
          '<button class="icon-btn edit-title-btn" title="Rename board" aria-label="Rename board"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13.4 3.6a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2L7 15.2l-3.2.8.8-3.2 8.8-9.2Z"/><path d="M12 5l3 3"/></svg></button>' +
          '<button class="icon-btn color-btn" title="Change color" aria-label="Change color"><span class="color-dot"></span></button>' +
          '<button class="icon-btn share-btn" title="Share board" aria-label="Share board"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="15" cy="5" r="2.2"/><circle cx="5" cy="10" r="2.2"/><circle cx="15" cy="15" r="2.2"/><path d="M7 8.8l6-2.6M7 11.2l6 2.6"/></svg></button>' +
          '<button class="icon-btn activity-btn" title="Board activity" aria-label="Board activity"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10h3l2 5 4-10 2 5h3"/></svg></button>' +
          '<button class="icon-btn start-btn" title="Start" aria-label="Start board"><svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><path d="M6.5 4.3v11.4a1 1 0 0 0 1.53.85l8.9-5.7a1 1 0 0 0 0-1.7l-8.9-5.7a1 1 0 0 0-1.53.85Z"/></svg></button>' +
          '<button class="icon-btn stop-btn" title="Stop" aria-label="Stop board" hidden><svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/></svg></button>' +
          '<button class="icon-btn chat-btn" title="Chat about this board" aria-label="Chat about this board"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.4a5.4 5.4 0 0 1 5.4-5.4h3.2a5.4 5.4 0 0 1 0 10.8H8l-3.6 2.6a.6.6 0 0 1-.95-.49L3.4 14a5.4 5.4 0 0 1-.4-2V9.4Z"/></svg></button>' +
          '<button class="icon-btn complete-btn" title="Mark board complete" aria-label="Mark board complete"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.3"/><path d="M6.7 10.2l2 2.1 4.4-4.6"/></svg></button>' +
          '<button class="icon-btn danger delete-btn" title="Delete board" aria-label="Delete board">&times;</button>' +
        "</div>" +
      "</div>" +
      '<div class="card-subtitle" spellcheck="false" data-placeholder="Add a one-line description&hellip;"></div>' +
      '<div class="progress-row">' +
        '<div class="progress-track"><div class="progress-fill"></div></div>' +
      "</div>" +
      '<div class="card-body">' +
        '<ul class="task-list"></ul>' +
        '<div class="task-count"></div>' +
        '<form class="task-add"><input type="text" placeholder="Add a task&hellip;" aria-label="New task"><button type="submit">Add</button></form>' +
      "</div>" +
      '<button type="button" class="glow-banner" hidden></button>' +
      '<div class="resize-handle" aria-hidden="true"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M10 1 1 10M11 5.5 5.5 11M11 9 9 11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></div>';

    var titleEl = el.querySelector(".card-title");
    var titleEditable = wireInlineEditable(titleEl, {
      editOnClick: false,
      allowDrag: true,
      readOnly: readOnly,
      getValue: function(){ return board.title; },
      setValue: function(val){
        var after = val || "Untitled board";
        board.title = after;
        apiPatch("/boards/" + board.id, {title: after}).catch(function(){});
      }
    });
    el.querySelector(".edit-title-btn").disabled = readOnly;
    el.querySelector(".edit-title-btn").addEventListener("click", function(e){
      e.stopPropagation();
      titleEditable.activate();
    });

    var subtitleEl = el.querySelector(".card-subtitle");
    wireInlineEditable(subtitleEl, {
      readOnly: readOnly,
      getValue: function(){ return board.description || ""; },
      setValue: function(val){
        var after = val;
        board.description = after;
        apiPatch("/boards/" + board.id, {description: after}).catch(function(){});
      }
    });

    var ctx = { board: board, el: el, readOnly: readOnly };
    window.BoardCardTasks.wire(ctx);
    window.BoardCardStatus.wire(ctx);

    var colorBtn = el.querySelector(".color-btn");
    var colorDot = el.querySelector(".color-dot");
    colorDot.textContent = window.BoardLabels.labelInitial(board);
    colorBtn.disabled = readOnly;
    colorBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    colorBtn.addEventListener("click", function(e){
      if(readOnly) return;
      e.stopPropagation();
      var existing = el.querySelector(".color-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "color-pop popover";

      // A labeled board's color is locked to its label — the swatches are
      // disabled rather than removed, so it's still visible what color a
      // board would take if the label were removed.
      var colorLocked = !!board.labelId;
      var swatchGrid = document.createElement("div");
      swatchGrid.className = "color-swatch-grid" + (colorLocked ? " locked" : "");
      U.HUES.forEach(function(h){
        var b = document.createElement("button");
        b.style.background = hueValue(h.name);
        b.title = h.name;
        b.disabled = colorLocked;
        b.addEventListener("click", function(ev){
          ev.stopPropagation();
          var after = h.name;
          board.color = after;
          el.style.setProperty("--card-hue", hueValue(after));
          pop.remove();
          apiPatch("/boards/" + board.id, {color: after}).catch(function(){});
        });
        swatchGrid.appendChild(b);
      });
      pop.appendChild(swatchGrid);
      if(colorLocked){
        var lockNote = document.createElement("div");
        lockNote.className = "color-lock-note";
        lockNote.textContent = "Color is locked to this board's label";
        pop.appendChild(lockNote);
      }
      pop.appendChild(window.BoardLabels.buildLabelPopSection(el, board, pop));
      el.querySelector(".card-header-actions").appendChild(pop);
    });

    var shareBtn = el.querySelector(".share-btn");
    shareBtn.hidden = readOnly;
    shareBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    shareBtn.addEventListener("click", function(e){
      e.stopPropagation();
      closeAllPopovers();
      if(window.Sharing) window.Sharing.open(board);
    });

    var activityBtn = el.querySelector(".activity-btn");
    activityBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    activityBtn.addEventListener("click", function(e){
      e.stopPropagation();
      closeAllPopovers();
      if(window.AdminConsole) window.AdminConsole.openBoardActivity(board.id, board.title);
    });

    var chatBtn = el.querySelector(".chat-btn");
    chatBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatBtn.addEventListener("click", function(e){
      e.stopPropagation();
      window.BoardChat.open(board.id);
    });

    var completeBoardBtn = el.querySelector(".complete-btn");
    completeBoardBtn.disabled = readOnly;
    completeBoardBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    completeBoardBtn.addEventListener("click", function(e){
      if(readOnly) return;
      e.stopPropagation();
      board.completed = true;
      window.BoardList.renderAll();
      apiPatch("/boards/" + board.id, {completed: true}).catch(function(){});
    });

    var deleteBtn = el.querySelector(".delete-btn");
    deleteBtn.disabled = readOnly;
    deleteBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    deleteBtn.addEventListener("click", function(e){
      if(readOnly) return;
      e.stopPropagation();
      var existing = el.querySelector(".confirm-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "confirm-pop popover";
      pop.innerHTML = "<p>Delete this board?</p>" +
        '<div class="confirm-actions"><button class="confirm-no">Cancel</button><button class="confirm-yes">Delete</button></div>';
      pop.querySelector(".confirm-no").addEventListener("click", function(ev){
        ev.stopPropagation();
        pop.remove();
      });
      pop.querySelector(".confirm-yes").addEventListener("click", function(ev){
        ev.stopPropagation();
        var state = window.BoardState.state;
        state.boards = state.boards.filter(function(b){ return b.id !== board.id; });
        window.BoardSocket.off(board.id);
        el.remove();
        window.BoardList.updateCount();
        apiDelete("/boards/" + board.id).catch(function(){});
      });
      el.querySelector(".card-header-actions").appendChild(pop);
    });

    window.BoardCardDrag.wire(ctx);
    el._ctx = ctx;

    return el;
  }

  window.BoardCard = { create: createCard };
})();
