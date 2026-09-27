(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;
  var agentQS = window.BoardApi.agentQS;
  var downloadFromApi = window.BoardApi.downloadFromApi;
  var U = window.BoardUtil;
  var clamp = U.clamp;
  var CANVAS_W = U.CANVAS_W, CANVAS_H = U.CANVAS_H;
  var closeAllPopovers = U.closeAllPopovers;

  async function addBoard(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    var canvasScroll = document.getElementById("canvas-scroll");
    var zoom = window.BoardZoom.get();
    var scrollLeft = canvasScroll.scrollLeft / zoom, scrollTop = canvasScroll.scrollTop / zoom;
    var state = window.BoardState.state;
    var count = state.boards.length;
    var x = clamp(scrollLeft + 50 + (count % 6) * 26, 0, CANVAS_W - 300);
    var y = clamp(scrollTop + 50 + (count % 6) * 26, 0, CANVAS_H - 260);
    try{
      var board = await apiPost("/boards", {
        agentId: agentId,
        title: "New task list",
        description: "",
        color: U.HUES[count % U.HUES.length].name,
        x: x, y: y, w: 290, h: 260
      });
      board.tasks = board.tasks || [];
      state.boards.push(board);
      state.zCounter = Math.max(state.zCounter, board.z);
      window.BoardList.renderAll();
    }catch(e){}
  }

  document.getElementById("add-btn").addEventListener("click", addBoard);

  document.getElementById("clear-btn").addEventListener("click", function(e){
    e.stopPropagation();
    var anchor = document.getElementById("clear-anchor");
    var existing = anchor.querySelector(".confirm-pop");
    if(existing){ existing.remove(); return; }
    closeAllPopovers();
    var pop = document.createElement("div");
    pop.className = "confirm-pop clear-confirm-pop popover";
    pop.innerHTML = "<p>Clear all boards? This can&rsquo;t be undone.</p>" +
      '<div class="confirm-actions confirm-actions-col">' +
        '<button type="button" class="confirm-yes clear-only-btn">Clear</button>' +
        '<button type="button" class="confirm-yes clear-export-btn">Clear &amp; Export</button>' +
        '<button type="button" class="confirm-no">Cancel</button>' +
      "</div>";
    var clearOnlyBtn = pop.querySelector(".clear-only-btn");
    var clearExportBtn = pop.querySelector(".clear-export-btn");
    var cancelBtn = pop.querySelector(".confirm-no");
    var allButtons = [clearOnlyBtn, clearExportBtn, cancelBtn];

    function setBusy(activeBtn, label){
      allButtons.forEach(function(b){ b.disabled = true; });
      if(label) activeBtn.textContent = label;
    }
    function doClear(){
      return apiPost("/boards/clear" + agentQS()).then(function(newBoards){
        var state = window.BoardState.state;
        state.boards = newBoards;
        state.zCounter = 10;
        window.BoardList.renderAll();
        pop.remove();
      });
    }
    function fail(btn, label){
      allButtons.forEach(function(b){ b.disabled = false; });
      btn.textContent = label;
    }

    cancelBtn.addEventListener("click", function(ev){
      ev.stopPropagation();
      pop.remove();
    });
    clearOnlyBtn.addEventListener("click", function(ev){
      ev.stopPropagation();
      setBusy(clearOnlyBtn, "Clearing…");
      doClear().catch(function(){ fail(clearOnlyBtn, "Clear"); });
    });
    clearExportBtn.addEventListener("click", function(ev){
      ev.stopPropagation();
      setBusy(clearExportBtn, "Exporting…");
      downloadFromApi("/boards/export" + agentQS(), "scatterboard-boards.json").then(function(){
        return doClear();
      }).catch(function(){ fail(clearExportBtn, "Clear & Export"); });
    });
    anchor.appendChild(pop);
  });

  document.addEventListener("pointerdown", function(e){
    if(e.target.closest(".popover, .color-btn, .delete-btn, .task-move-btn, #clear-btn")) return;
    closeAllPopovers();
  });

  var exportAnchor = document.getElementById("export-anchor");
  var exportMenuBtn = document.getElementById("export-menu-btn");
  var docIcon = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 2.6h4.2L15 6.4V16a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3.6a1 1 0 0 1 1-1Z"/><path d="M11.2 2.6V6.4H15"/></svg>';

  function runExportItem(btn, path, filename){
    var span = btn.querySelector("span");
    var original = span.textContent;
    btn.disabled = true;
    span.textContent = "Exporting…";
    downloadFromApi(path, filename).catch(function(){}).then(function(){
      btn.disabled = false;
      span.textContent = original;
      var pop = exportAnchor.querySelector(".export-menu-pop");
      if(pop) pop.remove();
    });
  }

  exportMenuBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
  exportMenuBtn.addEventListener("click", function(e){
    e.stopPropagation();
    var existing = exportAnchor.querySelector(".export-menu-pop");
    if(existing){ existing.remove(); return; }
    closeAllPopovers();
    var pop = document.createElement("div");
    pop.className = "export-menu-pop popover";
    pop.innerHTML =
      '<button type="button" class="export-menu-item" data-kind="json">' + docIcon + "<span>Export as JSON</span></button>" +
      '<button type="button" class="export-menu-item" data-kind="pdf">' + docIcon + "<span>Export as PDF</span></button>";
    pop.querySelector('[data-kind="json"]').addEventListener("click", function(ev){
      ev.stopPropagation();
      runExportItem(ev.currentTarget, "/boards/export" + agentQS(), "scatterboard-boards.json");
    });
    pop.querySelector('[data-kind="pdf"]').addEventListener("click", function(ev){
      ev.stopPropagation();
      runExportItem(ev.currentTarget, "/boards/export/pdf" + agentQS(), "scatterboard-summary.pdf");
    });
    exportAnchor.appendChild(pop);
  });

  var importAnchor = document.getElementById("import-anchor");
  var importInput = document.getElementById("import-input");

  function showImportMessage(message){
    var existing = importAnchor.querySelector(".confirm-pop");
    if(existing) existing.remove();
    closeAllPopovers();
    var pop = document.createElement("div");
    pop.className = "confirm-pop popover";
    pop.innerHTML = "<p>" + message + "</p><div class=\"confirm-actions\"><button class=\"confirm-no\">OK</button></div>";
    pop.querySelector(".confirm-no").addEventListener("click", function(ev){
      ev.stopPropagation();
      pop.remove();
    });
    importAnchor.appendChild(pop);
  }

  document.getElementById("import-btn").addEventListener("click", function(){
    importInput.value = "";
    importInput.click();
  });

  importInput.addEventListener("change", function(){
    var file = importInput.files && importInput.files[0];
    if(!file) return;
    var reader = new FileReader();
    reader.onload = function(){
      var parsed;
      try{ parsed = JSON.parse(String(reader.result)); }
      catch(e){ showImportMessage("That file isn&rsquo;t valid JSON."); return; }
      if(!parsed || !Array.isArray(parsed.boards) || !parsed.boards.length){
        showImportMessage("That file doesn&rsquo;t look like a Manifestation Board export.");
        return;
      }

      var existing = importAnchor.querySelector(".confirm-pop");
      if(existing) existing.remove();
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "confirm-pop popover";
      pop.innerHTML = "<p>Import " + parsed.boards.length + (parsed.boards.length === 1 ? " board" : " boards") + "? This replaces your current boards.</p>" +
        '<div class="confirm-actions"><button class="confirm-no">Cancel</button><button class="confirm-yes">Import</button></div>';
      pop.querySelector(".confirm-no").addEventListener("click", function(ev){
        ev.stopPropagation();
        pop.remove();
      });
      pop.querySelector(".confirm-yes").addEventListener("click", function(ev){
        ev.stopPropagation();
        apiPost("/boards/import" + agentQS(), {boards: parsed.boards}).then(function(newBoards){
          var state = window.BoardState.state;
          state.boards = newBoards;
          state.zCounter = state.boards.reduce(function(m, b){ return Math.max(m, b.z); }, 10);
          window.BoardList.renderAll();
          pop.remove();
        }).catch(function(){
          pop.remove();
          showImportMessage("Import failed — please try again.");
        });
      });
      importAnchor.appendChild(pop);
    };
    reader.onerror = function(){ showImportMessage("Could not read that file."); };
    reader.readAsText(file);
  });
})();
