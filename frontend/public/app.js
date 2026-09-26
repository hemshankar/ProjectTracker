(function(){
  "use strict";

  var API = "/api";
  var THEME_KEY = "scatterboard.theme.v1";
  var DESC_KEY = "scatterboard.descVisible.v1";
  var ZOOM_KEY = "scatterboard.zoom.v1";
  var CANVAS_W = 2600, CANVAS_H = 1600;
  var MIN_W = 220, MIN_H = 180;
  var ZOOM_MIN = 0.3, ZOOM_MAX = 2, ZOOM_STEP = 0.1, ZOOM_DEFAULT = 1;
  var zoom = ZOOM_DEFAULT;

  var HUES = [
    {name:"blue",  var:"--hue-blue"},
    {name:"sage",  var:"--hue-sage"},
    {name:"clay",  var:"--hue-clay"},
    {name:"mauve", var:"--hue-mauve"},
    {name:"ochre", var:"--hue-ochre"},
    {name:"slate", var:"--hue-slate"}
  ];

  function hueValue(name){
    var h = HUES.find(function(x){ return x.name === name; }) || HUES[0];
    return getComputedStyle(document.documentElement).getPropertyValue(h.var).trim();
  }

  // ---------------- API helpers ----------------

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

  function systemPrefersDark(){
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyTheme(theme){
    if(theme === "light" || theme === "dark"){
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  function initTheme(){
    var stored = null;
    try{ stored = localStorage.getItem(THEME_KEY); }catch(e){}
    applyTheme(stored);

    var toggle = document.getElementById("theme-toggle");
    toggle.addEventListener("click", function(){
      var current = document.documentElement.getAttribute("data-theme");
      var isDark = current ? current === "dark" : systemPrefersDark();
      var next = isDark ? "light" : "dark";
      applyTheme(next);
      try{ localStorage.setItem(THEME_KEY, next); }catch(e){}
      refreshCardHues();
    });
  }

  function initDescToggle(){
    var stored = null;
    try{ stored = localStorage.getItem(DESC_KEY); }catch(e){}
    if(stored === "hidden"){
      document.documentElement.classList.add("hide-descriptions");
    }
    var toggle = document.getElementById("desc-toggle");
    toggle.addEventListener("click", function(){
      var hidden = document.documentElement.classList.toggle("hide-descriptions");
      try{ localStorage.setItem(DESC_KEY, hidden ? "hidden" : "visible"); }catch(e){}
    });
  }

  function refreshCardHues(){
    canvas.querySelectorAll(".card").forEach(function(el){
      var board = boards.find(function(b){ return b.id === el.dataset.id; });
      if(board) el.style.setProperty("--card-hue", hueValue(board.color));
    });
  }

  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

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

  var boards = [];
  var zCounter = 10;

  // ---------------- undo / redo ----------------

  var MAX_HISTORY = 200;
  var undoStack = [];
  var redoStack = [];

  function pushHistory(entry){
    undoStack.push(entry);
    if(undoStack.length > MAX_HISTORY) undoStack.shift();
    redoStack.length = 0;
  }
  function performUndo(){
    if(!undoStack.length) return;
    var entry = undoStack.pop();
    entry.undo();
    redoStack.push(entry);
  }
  function performRedo(){
    if(!redoStack.length) return;
    var entry = redoStack.pop();
    entry.redo();
    undoStack.push(entry);
  }
  function initHistoryShortcuts(){
    document.addEventListener("keydown", function(e){
      if(!(e.ctrlKey || e.metaKey)) return;
      var tag = (e.target && e.target.tagName) || "";
      if(tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
      // A plain text input (e.g. the "Add a task" box) keeps focus after its
      // value is committed, so only defer to native input-undo while there's
      // still uncommitted text in it.
      if(tag === "INPUT" && e.target.value) return;
      var key = e.key.toLowerCase();
      if(key === "z" && e.shiftKey){
        e.preventDefault();
        performRedo();
      } else if(key === "z"){
        e.preventDefault();
        performUndo();
      } else if(key === "y"){
        e.preventDefault();
        performRedo();
      }
    });
  }

  function findBoard(boardId){
    return boards.find(function(b){ return b.id === boardId; });
  }
  function findTask(board, taskId){
    return board && board.tasks.find(function(t){ return t.id === taskId; });
  }
  function cloneTask(task){
    return {id: task.id, text: task.text, done: !!task.done};
  }
  function snapshotBoard(board){
    return {
      id: board.id, title: board.title, description: board.description,
      color: board.color, completed: !!board.completed,
      x: board.x, y: board.y, w: board.w, h: board.h, z: board.z,
      tasks: board.tasks.map(cloneTask)
    };
  }

  function restoreBoardFromSnapshot(snapshot){
    var restored = {
      id: snapshot.id, title: snapshot.title, description: snapshot.description,
      color: snapshot.color, completed: snapshot.completed,
      x: snapshot.x, y: snapshot.y, w: snapshot.w, h: snapshot.h,
      z: snapshot.z, tasks: snapshot.tasks.map(cloneTask)
    };
    boards.push(restored);
    zCounter = Math.max(zCounter, restored.z) + 1;
    restored.z = zCounter;
    apiPost("/boards", {
      id: restored.id, title: restored.title, description: restored.description,
      color: restored.color, completed: restored.completed,
      x: restored.x, y: restored.y, w: restored.w, h: restored.h,
      z: restored.z, tasks: restored.tasks
    }).catch(function(){});
    renderAll();
  }
  function removeBoardFromState(boardId){
    boards = boards.filter(function(b){ return b.id !== boardId; });
    apiDelete("/boards/" + boardId).catch(function(){});
    renderAll();
  }
  function setBoardField(boardId, field, value){
    var b = findBoard(boardId);
    if(!b) return;
    b[field] = value;
    var patch = {}; patch[field] = value;
    apiPatch("/boards/" + boardId, patch).catch(function(){});
    renderAll();
  }
  function setBoardPosition(boardId, x, y){
    var b = findBoard(boardId);
    if(!b) return;
    b.x = x; b.y = y;
    var el = canvas.querySelector('.card[data-id="' + boardId + '"]');
    if(el){ el.style.left = x + "px"; el.style.top = y + "px"; }
    apiPatch("/boards/" + boardId, {x: x, y: y}).catch(function(){});
  }
  function setBoardSize(boardId, w, h){
    var b = findBoard(boardId);
    if(!b) return;
    b.w = w; b.h = h;
    var el = canvas.querySelector('.card[data-id="' + boardId + '"]');
    if(el){ el.style.width = w + "px"; el.style.height = h + "px"; }
    apiPatch("/boards/" + boardId, {w: w, h: h}).catch(function(){});
  }
  function setBoardCompleted(boardId, completed){
    setBoardField(boardId, "completed", completed);
  }

  function setTaskDone(boardId, taskId, done){
    var b = findBoard(boardId);
    var t = findTask(b, taskId);
    if(!t) return;
    t.done = done;
    apiPatch("/boards/" + boardId + "/tasks/" + taskId, {done: done}).catch(function(){});
    renderAll();
  }
  function setTaskText(boardId, taskId, text){
    var b = findBoard(boardId);
    var t = findTask(b, taskId);
    if(!t) return;
    t.text = text;
    apiPatch("/boards/" + boardId + "/tasks/" + taskId, {text: text}).catch(function(){});
    renderAll();
  }
  function removeTask(boardId, taskId){
    var b = findBoard(boardId);
    if(!b) return;
    b.tasks = b.tasks.filter(function(t){ return t.id !== taskId; });
    apiDelete("/boards/" + boardId + "/tasks/" + taskId).catch(function(){});
    renderAll();
  }
  function restoreTaskAt(boardId, taskSnapshot, index){
    var b = findBoard(boardId);
    if(!b) return;
    apiPost("/boards/" + boardId + "/tasks", {id: taskSnapshot.id, text: taskSnapshot.text, done: taskSnapshot.done}).catch(function(){});
    var clampedIdx = Math.max(0, Math.min(index, b.tasks.length));
    b.tasks.splice(clampedIdx, 0, cloneTask(taskSnapshot));
    renderAll();
  }
  function restoreTasks(boardId, taskSnapshots){
    var b = findBoard(boardId);
    if(!b) return;
    taskSnapshots.forEach(function(t){
      apiPost("/boards/" + boardId + "/tasks", {id: t.id, text: t.text, done: t.done}).catch(function(){});
      b.tasks.push(cloneTask(t));
    });
    renderAll();
  }
  function removeTasks(boardId, taskIds){
    var b = findBoard(boardId);
    if(!b) return;
    b.tasks = b.tasks.filter(function(t){ return taskIds.indexOf(t.id) === -1; });
    taskIds.forEach(function(id){ apiDelete("/boards/" + boardId + "/tasks/" + id).catch(function(){}); });
    renderAll();
  }

  var canvas = document.getElementById("canvas");
  var canvasZoomWrapper = document.getElementById("canvas-zoom");
  var canvasScroll = document.getElementById("canvas-scroll");
  var boardCountEl = document.getElementById("board-count");
  var zoomOutBtn = document.getElementById("zoom-out-btn");
  var zoomInBtn = document.getElementById("zoom-in-btn");
  var zoomLevelBtn = document.getElementById("zoom-level-btn");

  var chatModal = document.getElementById("chat-modal");
  var chatModalTitle = document.getElementById("chat-modal-title");
  var chatModalDot = document.getElementById("chat-modal-dot");
  var chatModalClose = document.getElementById("chat-modal-close");
  var chatModalBody = document.getElementById("chat-modal-body");
  var chatForm = document.getElementById("chat-modal-form");
  var chatTextarea = document.getElementById("chat-modal-textarea");
  var chatSendBtn = document.getElementById("chat-modal-send");
  var chatNewBtn = document.getElementById("chat-new-btn");
  var chatHistoryAnchor = document.getElementById("chat-history-anchor");
  var chatHistoryBtn = document.getElementById("chat-history-btn");

  var chatBoardId = null;
  var chatAbortController = null;

  // ---------------- zoom ----------------

  function loadZoom(){
    try{
      var raw = localStorage.getItem(ZOOM_KEY);
      var val = raw ? parseFloat(raw) : ZOOM_DEFAULT;
      return isFinite(val) ? clamp(val, ZOOM_MIN, ZOOM_MAX) : ZOOM_DEFAULT;
    }catch(e){ return ZOOM_DEFAULT; }
  }
  function persistZoom(){
    try{ localStorage.setItem(ZOOM_KEY, String(zoom)); }catch(e){}
  }
  function updateZoomUI(){
    zoomLevelBtn.textContent = Math.round(zoom * 100) + "%";
    zoomOutBtn.disabled = zoom <= ZOOM_MIN + 1e-6;
    zoomInBtn.disabled = zoom >= ZOOM_MAX - 1e-6;
  }
  function setZoom(next, anchor){
    next = clamp(Math.round(next * 100) / 100, ZOOM_MIN, ZOOM_MAX);
    if(next === zoom) return;

    var rect = canvasScroll.getBoundingClientRect();
    var ax = anchor ? anchor.x - rect.left : canvasScroll.clientWidth / 2;
    var ay = anchor ? anchor.y - rect.top : canvasScroll.clientHeight / 2;
    var canvasX = (canvasScroll.scrollLeft + ax) / zoom;
    var canvasY = (canvasScroll.scrollTop + ay) / zoom;

    zoom = next;
    canvas.style.transform = "scale(" + zoom + ")";
    canvasZoomWrapper.style.width = (CANVAS_W * zoom) + "px";
    canvasZoomWrapper.style.height = (CANVAS_H * zoom) + "px";

    canvasScroll.scrollLeft = canvasX * zoom - ax;
    canvasScroll.scrollTop = canvasY * zoom - ay;

    updateZoomUI();
    persistZoom();
  }
  function initZoom(){
    zoom = loadZoom();
    canvas.style.transform = "scale(" + zoom + ")";
    canvasZoomWrapper.style.width = (CANVAS_W * zoom) + "px";
    canvasZoomWrapper.style.height = (CANVAS_H * zoom) + "px";
    updateZoomUI();

    zoomOutBtn.addEventListener("click", function(){ setZoom(zoom - ZOOM_STEP); });
    zoomInBtn.addEventListener("click", function(){ setZoom(zoom + ZOOM_STEP); });
    zoomLevelBtn.addEventListener("click", function(){ setZoom(ZOOM_DEFAULT); });

    canvasScroll.addEventListener("wheel", function(e){
      if(!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      var factor = Math.exp(-e.deltaY * 0.0015);
      setZoom(zoom * factor, {x: e.clientX, y: e.clientY});
    }, {passive:false});

    document.addEventListener("keydown", function(e){
      if(!(e.ctrlKey || e.metaKey)) return;
      var tag = (e.target && e.target.tagName) || "";
      if(tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
      if(e.key === "=" || e.key === "+"){
        e.preventDefault();
        setZoom(zoom + ZOOM_STEP);
      } else if(e.key === "-" || e.key === "_"){
        e.preventDefault();
        setZoom(zoom - ZOOM_STEP);
      } else if(e.key === "0"){
        e.preventDefault();
        setZoom(ZOOM_DEFAULT);
      }
    });
  }

  function updateCount(){
    var active = boards.filter(function(b){ return !b.completed; }).length;
    boardCountEl.textContent = active + (active === 1 ? " board" : " boards");
  }

  function bringToFront(board, el){
    zCounter += 1;
    board.z = zCounter;
    el.style.zIndex = zCounter;
    apiPatch("/boards/" + board.id, {z: zCounter}).catch(function(){});
  }

  function linkify(text){
    var esc = document.createElement("div");
    esc.textContent = text;
    var escaped = esc.innerHTML;
    return escaped.replace(/((https?:\/\/|www\.)[^\s<]+)/gi, function(match){
      var trail = "";
      var m = match.match(/[),.;:!?]+$/);
      if(m){ trail = m[0]; match = match.slice(0, match.length - trail.length); }
      var href = /^https?:\/\//i.test(match) ? match : "https://" + match;
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + match + "</a>" + trail;
    });
  }

  function wireInlineEditable(el, opts){
    function renderView(){
      var val = opts.getValue();
      el.innerHTML = val ? linkify(val) : "";
    }
    renderView();

    function activate(){
      if(el.isContentEditable) return;
      el.contentEditable = "true";
      el.textContent = opts.getValue();
      el.focus();
      var range = document.createRange();
      range.selectNodeContents(el);
      range.collapse(false);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }

    el.addEventListener("pointerdown", function(e){
      if(e.target.closest("a")) return;
      if(opts.allowDrag && !el.isContentEditable) return;
      e.stopPropagation();
    });
    if(opts.editOnClick !== false){
      el.addEventListener("click", function(e){
        if(e.target.closest("a")) return;
        activate();
      });
    }
    el.addEventListener("keydown", function(e){
      if(e.key === "Enter"){ e.preventDefault(); el.blur(); }
    });
    el.addEventListener("blur", function(){
      if(!el.isContentEditable) return;
      el.removeAttribute("contenteditable");
      var val = el.textContent.trim();
      if(!val && opts.onEmpty){ opts.onEmpty(); return; }
      opts.setValue(val);
      renderView();
    });

    return { activate: activate };
  }

  function checkIcon(){
    return '<svg viewBox="0 0 12 12" fill="none"><path d="M2.2 6.4L4.6 8.8L9.8 3.2" stroke="var(--accent-ink,#fff)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  function createCard(board){
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
          '<button class="icon-btn chat-btn" title="Chat about this board" aria-label="Chat about this board"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.4a5.4 5.4 0 0 1 5.4-5.4h3.2a5.4 5.4 0 0 1 0 10.8H8l-3.6 2.6a.6.6 0 0 1-.95-.49L3.4 14a5.4 5.4 0 0 1-.4-2V9.4Z"/></svg></button>' +
          '<button class="icon-btn complete-btn" title="Mark board complete" aria-label="Mark board complete"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.3"/><path d="M6.7 10.2l2 2.1 4.4-4.6"/></svg></button>' +
          '<button class="icon-btn danger delete-btn" title="Delete board" aria-label="Delete board">&times;</button>' +
        "</div>" +
      "</div>" +
      '<div class="card-subtitle" spellcheck="false" data-placeholder="Add a one-line description&hellip;"></div>' +
      '<div class="progress-row">' +
        '<div class="progress-track"><div class="progress-fill"></div></div>' +
        '<span class="anchor completed-anchor">' +
          '<button class="completed-btn" type="button" hidden aria-label="View completed tasks">' +
            '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.3"/><path d="M6.7 10.2l2 2.1 4.4-4.6"/></svg>' +
            '<span class="completed-count">0</span>' +
          "</button>" +
        "</span>" +
      "</div>" +
      '<div class="card-body">' +
        '<ul class="task-list"></ul>' +
        '<div class="task-count"></div>' +
        '<form class="task-add"><input type="text" placeholder="Add a task&hellip;" aria-label="New task"><button type="submit">Add</button></form>' +
      "</div>" +
      '<div class="resize-handle" aria-hidden="true"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M10 1 1 10M11 5.5 5.5 11M11 9 9 11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></div>';

    var titleEl = el.querySelector(".card-title");
    var titleEditable = wireInlineEditable(titleEl, {
      editOnClick: false,
      allowDrag: true,
      getValue: function(){ return board.title; },
      setValue: function(val){
        var before = board.title;
        var after = val || "Untitled board";
        board.title = after;
        apiPatch("/boards/" + board.id, {title: after}).catch(function(){});
        if(before !== after){
          pushHistory({
            undo: function(){ setBoardField(board.id, "title", before); },
            redo: function(){ setBoardField(board.id, "title", after); }
          });
        }
      }
    });
    el.querySelector(".edit-title-btn").addEventListener("click", function(e){
      e.stopPropagation();
      titleEditable.activate();
    });

    var subtitleEl = el.querySelector(".card-subtitle");
    wireInlineEditable(subtitleEl, {
      getValue: function(){ return board.description || ""; },
      setValue: function(val){
        var before = board.description || "";
        var after = val;
        board.description = after;
        apiPatch("/boards/" + board.id, {description: after}).catch(function(){});
        if(before !== after){
          pushHistory({
            undo: function(){ setBoardField(board.id, "description", before); },
            redo: function(){ setBoardField(board.id, "description", after); }
          });
        }
      }
    });

    var taskList = el.querySelector(".task-list");
    var taskCountEl = el.querySelector(".task-count");
    var progressFill = el.querySelector(".progress-fill");
    var completedAnchor = el.querySelector(".completed-anchor");
    var completedBtn = el.querySelector(".completed-btn");
    var completedCountEl = el.querySelector(".completed-count");

    function renderTasks(){
      taskList.innerHTML = "";
      board.tasks.filter(function(t){ return !t.done; }).forEach(function(task){
        var li = document.createElement("li");
        li.className = "task";
        li.setAttribute("data-done", "false");
        li.innerHTML =
          '<button class="task-check" aria-label="Mark task done">' + checkIcon() + "</button>" +
          '<span class="task-text" spellcheck="false"></span>' +
          '<button class="task-del" aria-label="Delete task">&times;</button>';

        li.querySelector(".task-check").addEventListener("click", function(){
          task.done = true;
          renderTasks();
          updateMeta();
          renderCompletedPop();
          apiPatch("/boards/" + board.id + "/tasks/" + task.id, {done: true}).catch(function(){});
          pushHistory({
            undo: function(){ setTaskDone(board.id, task.id, false); },
            redo: function(){ setTaskDone(board.id, task.id, true); }
          });
        });

        var textEl = li.querySelector(".task-text");
        wireInlineEditable(textEl, {
          getValue: function(){ return task.text; },
          setValue: function(val){
            var before = task.text;
            var after = val;
            task.text = after;
            apiPatch("/boards/" + board.id + "/tasks/" + task.id, {text: after}).catch(function(){});
            if(before !== after){
              pushHistory({
                undo: function(){ setTaskText(board.id, task.id, before); },
                redo: function(){ setTaskText(board.id, task.id, after); }
              });
            }
          },
          onEmpty: function(){
            var idx = board.tasks.indexOf(task);
            var snapshot = cloneTask(task);
            board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
            renderTasks();
            updateMeta();
            apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
            pushHistory({
              undo: function(){ restoreTaskAt(board.id, snapshot, idx); },
              redo: function(){ removeTask(board.id, snapshot.id); }
            });
          }
        });

        li.querySelector(".task-del").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
        li.querySelector(".task-del").addEventListener("click", function(){
          var idx = board.tasks.indexOf(task);
          var snapshot = cloneTask(task);
          board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
          renderTasks();
          updateMeta();
          apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
          pushHistory({
            undo: function(){ restoreTaskAt(board.id, snapshot, idx); },
            redo: function(){ removeTask(board.id, snapshot.id); }
          });
        });

        taskList.appendChild(li);
      });
    }

    function updateMeta(){
      var total = board.tasks.length;
      var done = board.tasks.filter(function(t){ return t.done; }).length;
      var open = total - done;
      taskCountEl.textContent = total ? (open + (open === 1 ? " task left" : " tasks left")) : "No tasks yet";
      progressFill.style.width = total ? Math.round((done / total) * 100) + "%" : "0%";
      completedCountEl.textContent = done;
      completedBtn.hidden = done === 0;
    }

    function buildCompletedItem(task){
      var li = document.createElement("li");
      li.className = "task";
      li.setAttribute("data-done", "true");
      li.innerHTML =
        '<button class="task-check" aria-label="Restore task">' + checkIcon() + "</button>" +
        '<span class="task-text"></span>' +
        '<button class="task-del" aria-label="Delete task permanently">&times;</button>';
      li.querySelector(".task-text").innerHTML = linkify(task.text);
      li.querySelector(".task-check").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
      li.querySelector(".task-check").addEventListener("click", function(){
        task.done = false;
        renderTasks();
        updateMeta();
        renderCompletedPop();
        apiPatch("/boards/" + board.id + "/tasks/" + task.id, {done: false}).catch(function(){});
        pushHistory({
          undo: function(){ setTaskDone(board.id, task.id, true); },
          redo: function(){ setTaskDone(board.id, task.id, false); }
        });
      });
      li.querySelector(".task-del").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
      li.querySelector(".task-del").addEventListener("click", function(){
        var idx = board.tasks.indexOf(task);
        var snapshot = cloneTask(task);
        board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
        updateMeta();
        renderCompletedPop();
        apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
        pushHistory({
          undo: function(){ restoreTaskAt(board.id, snapshot, idx); },
          redo: function(){ removeTask(board.id, snapshot.id); }
        });
      });
      return li;
    }

    function renderCompletedPop(){
      var pop = completedAnchor.querySelector(".completed-pop");
      if(!pop) return;
      var done = board.tasks.filter(function(t){ return t.done; });
      if(!done.length){ pop.remove(); return; }
      var list = pop.querySelector(".task-list");
      list.innerHTML = "";
      done.forEach(function(task){ list.appendChild(buildCompletedItem(task)); });
    }

    completedBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    completedBtn.addEventListener("click", function(e){
      e.stopPropagation();
      var existing = completedAnchor.querySelector(".completed-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "completed-pop popover";
      pop.innerHTML =
        '<div class="completed-pop-header"><span>Completed</span><button class="clear-completed-btn" type="button">Clear all</button></div>' +
        '<ul class="task-list"></ul>';
      pop.querySelector(".clear-completed-btn").addEventListener("pointerdown", function(ev){ ev.stopPropagation(); });
      pop.querySelector(".clear-completed-btn").addEventListener("click", function(ev){
        ev.stopPropagation();
        var removed = board.tasks.filter(function(t){ return t.done; }).map(cloneTask);
        board.tasks = board.tasks.filter(function(t){ return !t.done; });
        updateMeta();
        apiPost("/boards/" + board.id + "/tasks/clear-completed").catch(function(){});
        pop.remove();
        if(removed.length){
          pushHistory({
            undo: function(){ restoreTasks(board.id, removed); },
            redo: function(){ removeTasks(board.id, removed.map(function(t){ return t.id; })); }
          });
        }
      });
      completedAnchor.appendChild(pop);
      renderCompletedPop();
    });

    renderTasks();
    updateMeta();

    var form = el.querySelector(".task-add");
    var input = form.querySelector("input");
    input.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    form.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    form.addEventListener("submit", function(e){
      e.preventDefault();
      var val = input.value.trim();
      if(!val) return;
      input.value = "";
      apiPost("/boards/" + board.id + "/tasks", {text: val}).then(function(task){
        board.tasks.push(task);
        renderTasks();
        updateMeta();
        pushHistory({
          undo: function(){ removeTask(board.id, task.id); },
          redo: function(){ restoreTaskAt(board.id, task, board.tasks.length); }
        });
      }).catch(function(){});
    });

    var colorBtn = el.querySelector(".color-btn");
    colorBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    colorBtn.addEventListener("click", function(e){
      e.stopPropagation();
      var existing = el.querySelector(".color-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "color-pop popover";
      HUES.forEach(function(h){
        var b = document.createElement("button");
        b.style.background = hueValue(h.name);
        b.title = h.name;
        b.addEventListener("click", function(ev){
          ev.stopPropagation();
          var before = board.color;
          var after = h.name;
          board.color = after;
          el.style.setProperty("--card-hue", hueValue(after));
          pop.remove();
          apiPatch("/boards/" + board.id, {color: after}).catch(function(){});
          if(before !== after){
            pushHistory({
              undo: function(){ setBoardField(board.id, "color", before); },
              redo: function(){ setBoardField(board.id, "color", after); }
            });
          }
        });
        pop.appendChild(b);
      });
      el.querySelector(".card-header-actions").appendChild(pop);
    });

    var chatBtn = el.querySelector(".chat-btn");
    chatBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatBtn.addEventListener("click", function(e){
      e.stopPropagation();
      openChatModal(board.id);
    });

    var completeBoardBtn = el.querySelector(".complete-btn");
    completeBoardBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    completeBoardBtn.addEventListener("click", function(e){
      e.stopPropagation();
      board.completed = true;
      renderAll();
      apiPatch("/boards/" + board.id, {completed: true}).catch(function(){});
      pushHistory({
        undo: function(){ setBoardCompleted(board.id, false); },
        redo: function(){ setBoardCompleted(board.id, true); }
      });
    });

    var deleteBtn = el.querySelector(".delete-btn");
    deleteBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    deleteBtn.addEventListener("click", function(e){
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
        var snapshot = snapshotBoard(board);
        boards = boards.filter(function(b){ return b.id !== board.id; });
        el.remove();
        updateCount();
        apiDelete("/boards/" + board.id).catch(function(){});
        pushHistory({
          undo: function(){ restoreBoardFromSnapshot(snapshot); },
          redo: function(){ removeBoardFromState(snapshot.id); }
        });
      });
      el.querySelector(".card-header-actions").appendChild(pop);
    });

    // ---- drag ----
    var header = el.querySelector(".card-header");
    header.addEventListener("pointerdown", function(e){
      if(e.target.closest(".icon-btn, .popover")) return;
      var titleTarget = e.target.closest(".card-title");
      if(titleTarget && titleTarget.isContentEditable) return;
      e.preventDefault();
      bringToFront(board, el);
      el.classList.add("dragging");
      var startX = e.clientX, startY = e.clientY;
      var origX = board.x, origY = board.y;
      header.setPointerCapture(e.pointerId);

      function onMove(ev){
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
        if(board.x !== origX || board.y !== origY){
          var boardId = board.id, beforeX = origX, beforeY = origY, afterX = board.x, afterY = board.y;
          pushHistory({
            undo: function(){ setBoardPosition(boardId, beforeX, beforeY); },
            redo: function(){ setBoardPosition(boardId, afterX, afterY); }
          });
        }
      }
      header.addEventListener("pointermove", onMove);
      header.addEventListener("pointerup", onUp);
    });

    // ---- resize ----
    var handle = el.querySelector(".resize-handle");
    handle.addEventListener("pointerdown", function(e){
      e.preventDefault();
      e.stopPropagation();
      bringToFront(board, el);
      el.classList.add("resizing");
      var startX = e.clientX, startY = e.clientY;
      var origW = board.w, origH = board.h;
      handle.setPointerCapture(e.pointerId);

      function onMove(ev){
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
        if(board.w !== origW || board.h !== origH){
          var boardId = board.id, beforeW = origW, beforeH = origH, afterW = board.w, afterH = board.h;
          pushHistory({
            undo: function(){ setBoardSize(boardId, beforeW, beforeH); },
            redo: function(){ setBoardSize(boardId, afterW, afterH); }
          });
        }
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
      bringToFront(board, el);
    }, {capture:true});

    return el;
  }

  function closeAllPopovers(){
    document.querySelectorAll(".popover").forEach(function(p){ p.remove(); });
  }

  // ---------------- chat ----------------

  function abortActiveChatStream(){
    if(chatAbortController){ chatAbortController.abort(); chatAbortController = null; }
  }

  function setChatBusy(busy){
    chatSendBtn.textContent = busy ? "Stop" : "Send";
    chatTextarea.disabled = busy;
  }

  function autoSizeChatTextarea(){
    chatTextarea.style.height = "auto";
    chatTextarea.style.height = Math.min(chatTextarea.scrollHeight, 160) + "px";
  }

  function buildChatMessageEl(m){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + m.role;
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = m.text ? linkify(m.text) : "";
    wrap.appendChild(bubble);
    return wrap;
  }

  function renderChatMessages(){
    var board = boards.find(function(b){ return b.id === chatBoardId; });
    if(!board) return;
    var chat = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    var messages = chat ? chat.messages : [];
    chatModalBody.innerHTML = "";
    if(!messages.length){
      var empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "Ask about this board — priorities, next steps, drafts, anything.";
      chatModalBody.appendChild(empty);
    } else {
      messages.forEach(function(m){ chatModalBody.appendChild(buildChatMessageEl(m)); });
    }
    chatModalBody.scrollTop = chatModalBody.scrollHeight;
  }

  function buildChatHistoryItem(board, chat){
    var li = document.createElement("li");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-history-item" + (chat.id === board.activeChatId ? " active" : "");
    var firstUser = chat.messages.find(function(m){ return m.role === "user"; });
    var snippet = firstUser ? firstUser.text : "New chat";
    if(snippet.length > 46) snippet = snippet.slice(0, 46) + "…";
    var meta = new Date(chat.createdAt).toLocaleString(undefined, {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"});
    meta += " · " + chat.messages.length + (chat.messages.length === 1 ? " message" : " messages");
    var snippetEl = document.createElement("span");
    snippetEl.className = "snippet";
    snippetEl.textContent = snippet;
    var metaEl = document.createElement("span");
    metaEl.className = "meta";
    metaEl.textContent = meta;
    btn.appendChild(snippetEl);
    btn.appendChild(metaEl);
    btn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      switchChat(board.id, chat.id);
    });
    li.appendChild(btn);
    return li;
  }

  function renderChatHistoryPop(){
    var pop = chatHistoryAnchor.querySelector(".chat-history-pop");
    if(!pop) return;
    var board = boards.find(function(b){ return b.id === chatBoardId; });
    if(!board) return;
    var list = pop.querySelector(".chat-history-list");
    list.innerHTML = "";
    var sorted = (board.chats || []).slice().sort(function(a, b){ return b.createdAt - a.createdAt; });
    sorted.forEach(function(chat){ list.appendChild(buildChatHistoryItem(board, chat)); });
  }

  async function ensureChatsLoaded(board){
    if(board._chatsLoaded) return;
    try{
      var data = await apiGet("/boards/" + board.id + "/chats");
      board.chats = data.chats || [];
      board.activeChatId = data.activeChatId;
      if(!board.chats.length){
        var chat = await apiPost("/boards/" + board.id + "/chats");
        board.chats = [chat];
        board.activeChatId = chat.id;
      }
      board._chatsLoaded = true;
    }catch(e){
      board.chats = board.chats || [];
    }
  }

  async function startNewChat(boardId){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    abortActiveChatStream();
    var current = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    if(!current || current.messages.length){
      try{
        var chat = await apiPost("/boards/" + boardId + "/chats");
        board.chats.push(chat);
        board.activeChatId = chat.id;
      }catch(e){}
    }
    setChatBusy(false);
    renderChatMessages();
    renderChatHistoryPop();
    chatTextarea.focus();
  }

  function switchChat(boardId, chatId){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    if(chatId === board.activeChatId || !(board.chats || []).some(function(c){ return c.id === chatId; })) return;
    abortActiveChatStream();
    board.activeChatId = chatId;
    apiPatch("/boards/" + boardId + "/chats/active", {chatId: chatId}).catch(function(){});
    setChatBusy(false);
    renderChatMessages();
    renderChatHistoryPop();
  }

  async function openChatModal(boardId){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    if(chatBoardId !== boardId) abortActiveChatStream();
    chatBoardId = boardId;
    chatModalTitle.textContent = board.title || "Untitled board";
    chatModalDot.style.background = hueValue(board.color);
    chatModal.hidden = false;
    closeAllPopovers();
    setChatBusy(!!chatAbortController);
    chatModalBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    await ensureChatsLoaded(board);
    if(chatBoardId !== boardId) return;
    renderChatMessages();
    chatTextarea.value = "";
    autoSizeChatTextarea();
    chatTextarea.focus();
  }

  function closeChatModal(){
    abortActiveChatStream();
    closeAllPopovers();
    chatModal.hidden = true;
    chatBoardId = null;
  }

  async function sendChatMessage(){
    var boardId = chatBoardId;
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    var text = chatTextarea.value.trim();
    if(!text || chatAbortController) return;

    var chat = (board.chats || []).find(function(c){ return c.id === board.activeChatId; });
    if(!chat) return;

    chat.messages.push({role: "user", text: text});
    chatTextarea.value = "";
    autoSizeChatTextarea();
    if(chatBoardId === boardId) renderChatMessages();

    var pending = {role: "assistant", text: ""};
    chat.messages.push(pending);
    if(chatBoardId === boardId) renderChatMessages();

    var controller = new AbortController();
    chatAbortController = controller;
    if(chatBoardId === boardId) setChatBusy(true);

    try{
      var resp = await fetch(API + "/boards/" + boardId + "/chats/" + chat.id + "/messages", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: text}),
        signal: controller.signal
      });
      if(!resp.ok || !resp.body) throw new Error("chat request failed");

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while(true){
        var res = await reader.read();
        if(res.done) break;
        buffer += decoder.decode(res.value, {stream: true});
        var parts = buffer.split("\n\n");
        buffer = parts.pop();
        for(var i = 0; i < parts.length; i++){
          var line = parts[i];
          if(line.indexOf("data: ") !== 0) continue;
          var payload = JSON.parse(line.slice(6));
          if(payload.delta){
            pending.text += payload.delta;
            if(chatBoardId === boardId) renderChatMessages();
          }
        }
      }
    }catch(err){
      if(err && err.name === "AbortError"){
        pending.text = pending.text || "(stopped)";
      } else {
        pending.text = pending.text || "Something went wrong reaching the assistant.";
      }
    } finally {
      if(chatAbortController === controller) chatAbortController = null;
      if(chatBoardId === boardId){ setChatBusy(false); renderChatMessages(); }
    }
  }

  function wireChatModal(){
    chatModalClose.addEventListener("click", closeChatModal);
    chatModal.addEventListener("mousedown", function(e){
      if(e.target === chatModal) closeChatModal();
    });
    document.addEventListener("keydown", function(e){
      if(e.key === "Escape" && !chatModal.hidden) closeChatModal();
    });
    chatForm.addEventListener("submit", function(e){
      e.preventDefault();
      if(chatAbortController){ chatAbortController.abort(); return; }
      sendChatMessage();
    });
    chatTextarea.addEventListener("keydown", function(e){
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        if(chatForm.requestSubmit) chatForm.requestSubmit();
        else chatForm.dispatchEvent(new Event("submit", {cancelable:true}));
      }
    });
    chatTextarea.addEventListener("input", autoSizeChatTextarea);

    chatNewBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatNewBtn.addEventListener("click", function(e){
      e.stopPropagation();
      closeAllPopovers();
      if(chatBoardId) startNewChat(chatBoardId);
    });

    chatHistoryBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    chatHistoryBtn.addEventListener("click", function(e){
      e.stopPropagation();
      var existing = chatHistoryAnchor.querySelector(".chat-history-pop");
      if(existing){ existing.remove(); return; }
      closeAllPopovers();
      var pop = document.createElement("div");
      pop.className = "chat-history-pop popover";
      pop.innerHTML = '<div class="completed-pop-header"><span>Previous chats</span></div><ul class="chat-history-list"></ul>';
      chatHistoryAnchor.appendChild(pop);
      renderChatHistoryPop();
    });
  }

  // ---------------- boards ----------------

  function renderAll(){
    canvas.innerHTML = "";
    boards.filter(function(b){ return !b.completed; }).forEach(function(board){
      canvas.appendChild(createCard(board));
    });
    updateCount();
    updateArchiveUI();
  }

  async function addBoard(){
    var scrollLeft = canvasScroll.scrollLeft / zoom, scrollTop = canvasScroll.scrollTop / zoom;
    var count = boards.length;
    var x = clamp(scrollLeft + 50 + (count % 6) * 26, 0, CANVAS_W - 300);
    var y = clamp(scrollTop + 50 + (count % 6) * 26, 0, CANVAS_H - 260);
    try{
      var board = await apiPost("/boards", {
        title: "New task list",
        description: "",
        color: HUES[count % HUES.length].name,
        x: x, y: y, w: 290, h: 260
      });
      board.tasks = board.tasks || [];
      boards.push(board);
      zCounter = Math.max(zCounter, board.z);
      renderAll();
      pushHistory({
        undo: function(){ removeBoardFromState(board.id); },
        redo: function(){ restoreBoardFromSnapshot(snapshotBoard(board)); }
      });
    }catch(e){}
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

  var archiveAnchor = document.getElementById("archive-anchor");
  var archiveBtn = document.getElementById("archive-btn");
  var archiveCountEl = document.getElementById("archive-count");

  function updateArchiveUI(){
    var archived = boards.filter(function(b){ return b.completed; });
    archiveCountEl.textContent = archived.length;
    archiveBtn.hidden = archived.length === 0;
    if(!archived.length){
      var pop = archiveAnchor.querySelector(".archive-pop");
      if(pop) pop.remove();
    }
  }

  function buildArchiveItem(board){
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
    restoreBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    restoreBtn.addEventListener("click", function(e){
      e.stopPropagation();
      board.completed = false;
      renderAll();
      apiPatch("/boards/" + board.id, {completed: false}).catch(function(){});
      renderArchivePop();
      pushHistory({
        undo: function(){ setBoardCompleted(board.id, true); },
        redo: function(){ setBoardCompleted(board.id, false); }
      });
    });

    var deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "archived-delete-btn";
    deleteBtn.title = "Delete board permanently";
    deleteBtn.setAttribute("aria-label", "Delete board permanently");
    deleteBtn.textContent = "×";
    wireArmedDelete(deleteBtn, function(){
      boards = boards.filter(function(b){ return b.id !== board.id; });
      renderAll();
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
    var archived = boards.filter(function(b){ return b.completed; });
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
      return apiPost("/boards/clear").then(function(newBoards){
        boards = newBoards;
        zCounter = 10;
        renderAll();
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
      downloadFromApi("/boards/export", "scatterboard-boards.json").then(function(){
        return doClear();
      }).catch(function(){ fail(clearExportBtn, "Clear & Export"); });
    });
    anchor.appendChild(pop);
  });
  document.addEventListener("pointerdown", function(e){
    if(e.target.closest(".popover, .color-btn, .delete-btn, #clear-btn")) return;
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
      runExportItem(ev.currentTarget, "/boards/export", "scatterboard-boards.json");
    });
    pop.querySelector('[data-kind="pdf"]').addEventListener("click", function(ev){
      ev.stopPropagation();
      runExportItem(ev.currentTarget, "/boards/export/pdf", "scatterboard-summary.pdf");
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
        showImportMessage("That file doesn&rsquo;t look like a Scatterboard export.");
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
        apiPost("/boards/import", {boards: parsed.boards}).then(function(newBoards){
          boards = newBoards;
          zCounter = boards.reduce(function(m, b){ return Math.max(m, b.z); }, 10);
          renderAll();
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

  async function init(){
    initTheme();
    initDescToggle();
    initZoom();
    initHistoryShortcuts();
    wireChatModal();

    try{
      boards = await apiGet("/boards");
    }catch(e){
      boards = [];
    }
    zCounter = boards.reduce(function(m, b){ return Math.max(m, b.z || 0); }, 10);
    renderAll();
  }

  init();
})();
