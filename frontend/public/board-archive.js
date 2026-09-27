(function(){
  "use strict";

  var apiPatch = window.BoardApi.apiPatch;
  var apiDelete = window.BoardApi.apiDelete;
  var hueValue = window.BoardUtil.hueValue;
  var closeAllPopovers = window.BoardUtil.closeAllPopovers;

  var archiveAnchor = document.getElementById("archive-anchor");
  var archiveBtn = document.getElementById("archive-btn");
  var archiveCountEl = document.getElementById("archive-count");

  function updateArchiveUI(){
    var archived = window.BoardState.state.boards.filter(function(b){ return b.completed; });
    archiveCountEl.textContent = archived.length;
    archiveBtn.hidden = archived.length === 0;
    if(!archived.length){
      var pop = archiveAnchor.querySelector(".archive-pop");
      if(pop) pop.remove();
    }
  }

  function wireArmedDelete(btn, onConfirm){
    var armed = false;
    var timer = null;
    btn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      if(!armed){
        armed = true;
        btn.classList.add("armed");
        btn.title = "Click again to permanently delete";
        clearTimeout(timer);
        timer = setTimeout(function(){ armed = false; btn.classList.remove("armed"); btn.title = "Delete board permanently"; }, 2500);
        return;
      }
      clearTimeout(timer);
      onConfirm();
    });
  }

  function buildArchiveItem(board){
    var readOnly = board.myRole === "viewer";
    var li = document.createElement("li");
    li.className = "archive-item";

    var dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = hueValue(board.color);

    var title = document.createElement("span");
    title.className = "title";
    title.textContent = board.title;

    var restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.title = "Restore board";
    restoreBtn.setAttribute("aria-label", "Restore board");
    restoreBtn.innerHTML = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8h8a4 4 0 0 1 0 8H9"/><path d="M9 5 6 8l3 3"/></svg>';
    restoreBtn.disabled = readOnly;
    restoreBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    restoreBtn.addEventListener("click", function(e){
      if(readOnly) return;
      e.stopPropagation();
      board.completed = false;
      window.BoardList.renderAll();
      apiPatch("/boards/" + board.id, {completed: false}).catch(function(){});
      renderArchivePop();
    });

    var deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "archived-delete-btn";
    deleteBtn.title = "Delete board permanently";
    deleteBtn.setAttribute("aria-label", "Delete board permanently");
    deleteBtn.textContent = "×";
    deleteBtn.disabled = readOnly;
    wireArmedDelete(deleteBtn, function(){
      var state = window.BoardState.state;
      state.boards = state.boards.filter(function(b){ return b.id !== board.id; });
      window.BoardList.renderAll();
      apiDelete("/boards/" + board.id).catch(function(){});
      renderArchivePop();
    });

    li.appendChild(dot);
    li.appendChild(title);
    li.appendChild(restoreBtn);
    li.appendChild(deleteBtn);
    return li;
  }

  function renderArchivePop(){
    var pop = archiveAnchor.querySelector(".archive-pop");
    if(!pop) return;
    var archived = window.BoardState.state.boards.filter(function(b){ return b.completed; });
    if(!archived.length){ pop.remove(); return; }
    var list = pop.querySelector(".archive-list");
    list.innerHTML = "";
    archived.forEach(function(b){ list.appendChild(buildArchiveItem(b)); });
  }

  archiveBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
  archiveBtn.addEventListener("click", function(e){
    e.stopPropagation();
    var existing = archiveAnchor.querySelector(".archive-pop");
    if(existing){ existing.remove(); return; }
    closeAllPopovers();
    var pop = document.createElement("div");
    pop.className = "archive-pop popover";
    pop.innerHTML = '<div class="completed-pop-header"><span>Completed boards</span></div><ul class="archive-list"></ul>';
    archiveAnchor.appendChild(pop);
    renderArchivePop();
  });

  window.BoardArchive = {
    updateArchiveUI: updateArchiveUI
  };
})();
