(function(){
  "use strict";

  var API = "/api";
  var THEME_KEY = "scatterboard.theme.v1";
  var ZOOM_KEY = "scatterboard.zoom.v1";
  var CANVAS_W = 2600, CANVAS_H = 1600;
  var MIN_W = 220, MIN_H = 180;
  var ZOOM_MIN = 0.3, ZOOM_MAX = 2, ZOOM_STEP = 0.1, ZOOM_DEFAULT = 1;
  var zoom = ZOOM_DEFAULT;
  var activeBoardStreams = [];

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

  // Labels are global (shared across every board, not per-agent), so the
  // list is fetched once and cached for the session rather than reloaded
  // per board or per agent switch.
  var labelsCache = null;
  var labelsById = {};

  function ensureLabelsLoaded(){
    if(labelsCache) return Promise.resolve(labelsCache);
    return apiGet("/labels").then(function(list){
      labelsCache = list;
      labelsById = {};
      list.forEach(function(l){ labelsById[l.id] = l; });
      return list;
    }).catch(function(){ return labelsCache || []; });
  }

  function labelInitial(board){
    var l = board.labelId && labelsById[board.labelId];
    return l ? l.name.trim().charAt(0).toUpperCase() : "";
  }

  // Builds the "assign a label" section appended below the color swatches
  // in a board's color-pop popover — lists every shared label (global,
  // reused across all boards) plus a small form to create a new one.
  function buildLabelPopSection(el, board, pop){
    var section = document.createElement("div");
    section.className = "label-pop-section";
    var list = document.createElement("div");
    list.className = "label-pop-list";
    section.appendChild(list);

    function applyLabel(labelId){
      var beforeLabel = board.labelId || "";
      var afterLabel = labelId || "";
      if(beforeLabel === afterLabel){ pop.remove(); return; }
      // A board's color is locked to its label — picking one recolors the
      // board to match; clearing one just unlocks the swatches and leaves
      // whatever color was already showing.
      var afterColor = afterLabel && labelsById[afterLabel] ? labelsById[afterLabel].color : board.color;
      board.labelId = afterLabel;
      board.color = afterColor;
      el.style.setProperty("--card-hue", hueValue(afterColor));
      el.querySelector(".color-dot").textContent = labelInitial(board);
      pop.remove();
      apiPatch("/boards/" + board.id, {labelId: afterLabel, color: afterColor}).catch(function(){});
    }

    function renderChips(){
      list.innerHTML = "";
      var none = document.createElement("button");
      none.type = "button";
      none.className = "label-chip" + (!board.labelId ? " active" : "");
      none.textContent = "No label";
      none.addEventListener("click", function(ev){ ev.stopPropagation(); applyLabel(""); });
      list.appendChild(none);
      (labelsCache || []).forEach(function(l){
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "label-chip" + (board.labelId === l.id ? " active" : "");
        chip.textContent = l.name;
        chip.addEventListener("click", function(ev){ ev.stopPropagation(); applyLabel(l.id); });
        list.appendChild(chip);
      });
    }

    renderChips();
    ensureLabelsLoaded().then(renderChips);

    var form = document.createElement("form");
    form.className = "label-pop-new";
    form.innerHTML = '<input type="text" placeholder="New label&hellip;" maxlength="16"><button type="submit">+</button>';
    form.addEventListener("click", function(ev){ ev.stopPropagation(); });
    form.addEventListener("submit", function(ev){
      ev.preventDefault();
      var input = form.querySelector("input");
      var name = input.value.trim();
      if(!name) return;
      input.disabled = true;
      apiPost("/labels", {name: name, color: board.color}).then(function(label){
        labelsCache = (labelsCache || []).concat([label]);
        labelsById[label.id] = label;
        applyLabel(label.id);
      }).catch(function(){
        input.disabled = false;
      });
    });
    section.appendChild(form);
    return section;
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

  function agentQS(){
    var id = window.Identity && window.Identity.getCurrentAgentId();
    return id ? ("?agentId=" + encodeURIComponent(id)) : "";
  }

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

  function findBoard(boardId){
    return boards.find(function(b){ return b.id === boardId; });
  }
  function findTask(board, taskId){
    return board && board.tasks.find(function(t){ return t.id === taskId; });
  }

  // ---------------- undo / redo ----------------
  // Phase 7: server-side truth (`services.undo_service`), not a client-only
  // stack — a per-agent, per-user pointer into that user's own audit-log
  // entries. Survives a reload, and only ever replays *this user's own*
  // board/task edits — an agent's changes are never in this timeline.

  function applyUndoRedoResult(res){
    if(!res || !res.ok) return;
    if(res.board){
      var idx = boards.findIndex(function(b){ return b.id === res.board.id; });
      if(idx === -1){ boards.push(res.board); } else { boards[idx] = res.board; }
      zCounter = Math.max(zCounter, res.board.z || 0);
    } else if(res.boardId){
      boards = boards.filter(function(b){ return b.id !== res.boardId; });
    }
    renderAll();
  }
  function performUndo(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    apiPost("/agents/" + agentId + "/undo").then(applyUndoRedoResult).catch(function(){});
  }
  function performRedo(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    apiPost("/agents/" + agentId + "/redo").then(applyUndoRedoResult).catch(function(){});
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

  var taskDetailModal = document.getElementById("task-detail-modal");
  var taskDetailTitle = document.getElementById("task-detail-title");
  var taskDetailSubtitle = document.getElementById("task-detail-subtitle");
  var taskDetailClose = document.getElementById("task-detail-close");
  var taskDetailBody = document.getElementById("task-detail-body");
  var taskDetailActivityBody = document.getElementById("task-detail-activity-body");
  var taskDetailTabBtnChat = document.getElementById("task-detail-tab-btn-chat");
  var taskDetailTabBtnActivity = document.getElementById("task-detail-tab-btn-activity");
  var taskDetailRunBtn = document.getElementById("task-detail-run-btn");
  var taskDetailStopBtn = document.getElementById("task-detail-stop-btn");
  var taskDetailForm = document.getElementById("task-detail-form");
  var taskDetailTextarea = document.getElementById("task-detail-textarea");
  var taskDetailSendBtn = document.getElementById("task-detail-send");

  var TASK_RUNNABLE_STATUSES = {idle: true, failed: true, stopped: true, blocked: true};
  var TASK_STOPPABLE_STATUSES = {
    running: true, queued: true, awaiting_approval: true, awaiting_reply: true,
    awaiting_clarification: true, manual: true
  };

  var taskDetailBoardId = null;
  var taskDetailTaskId = null;
  var taskDetailChatId = null;
  var taskDetailSending = false;

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

  function escapeHtml(text){
    var esc = document.createElement("div");
    esc.textContent = text;
    return esc.innerHTML;
  }

  function linkifyEscaped(escaped){
    return escaped.replace(/((https?:\/\/|www\.)[^\s<]+)/gi, function(match){
      var trail = "";
      var m = match.match(/[),.;:!?]+$/);
      if(m){ trail = m[0]; match = match.slice(0, match.length - trail.length); }
      var href = /^https?:\/\//i.test(match) ? match : "https://" + match;
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + match + "</a>" + trail;
    });
  }

  function linkify(text){
    return linkifyEscaped(escapeHtml(text));
  }

  function renderInline(text){
    var escaped = escapeHtml(text);
    var codeSpans = [];
    escaped = escaped.replace(/`([^`]+)`/g, function(_, code){
      var idx = codeSpans.length;
      codeSpans.push(code);
      return "\u0000CODE" + idx + "\u0000";
    });
    escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function(_, label, href){
      return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
    });
    escaped = escaped.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "<strong>$2</strong>");
    escaped = escaped.replace(/(\*|_)(?=\S)([^*_]*?\S)\1/g, "<em>$2</em>");
    escaped = linkifyEscaped(escaped);
    escaped = escaped.replace(/\u0000CODE(\d+)\u0000/g, function(_, idx){
      return "<code>" + codeSpans[+idx] + "</code>";
    });
    return escaped;
  }

  function renderMarkdown(text){
    if(!text) return "";
    var lines = String(text).replace(/\r\n/g, "\n").split("\n");
    var html = "";
    var listStack = null;
    var paragraphBuffer = [];

    function flushParagraph(){
      if(paragraphBuffer.length){
        html += "<p>" + paragraphBuffer.map(renderInline).join("<br>") + "</p>";
        paragraphBuffer = [];
      }
    }
    function closeList(){
      if(listStack){ html += "</" + listStack + ">"; listStack = null; }
    }

    var i = 0;
    while(i < lines.length){
      var line = lines[i];

      var fence = line.match(/^\s*(```|~~~)(.*)$/);
      if(fence){
        flushParagraph(); closeList();
        var fenceMarker = fence[1];
        var codeLines = [];
        i++;
        while(i < lines.length && lines[i].indexOf(fenceMarker) !== 0){
          codeLines.push(lines[i]);
          i++;
        }
        i++;
        html += "<pre><code>" + escapeHtml(codeLines.join("\n")) + "</code></pre>";
        continue;
      }

      if(/^\s*$/.test(line)){
        flushParagraph();
        closeList();
        i++;
        continue;
      }

      var header = line.match(/^(#{1,6})\s+(.*)$/);
      if(header){
        flushParagraph(); closeList();
        var level = header[1].length;
        html += "<h" + level + ">" + renderInline(header[2]) + "</h" + level + ">";
        i++;
        continue;
      }

      if(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)){
        flushParagraph(); closeList();
        html += "<hr>";
        i++;
        continue;
      }

      var quote = line.match(/^\s*>\s?(.*)$/);
      if(quote){
        flushParagraph(); closeList();
        var quoteLines = [quote[1]];
        i++;
        while(i < lines.length && /^\s*>\s?/.test(lines[i])){
          quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        html += "<blockquote>" + renderInline(quoteLines.join(" ")) + "</blockquote>";
        continue;
      }

      var ul = line.match(/^\s*[-*+]\s+(.*)$/);
      if(ul){
        flushParagraph();
        if(listStack !== "ul"){ closeList(); html += "<ul>"; listStack = "ul"; }
        html += "<li>" + renderInline(ul[1]) + "</li>";
        i++;
        continue;
      }

      var ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if(ol){
        flushParagraph();
        if(listStack !== "ol"){ closeList(); html += "<ol>"; listStack = "ol"; }
        html += "<li>" + renderInline(ol[1]) + "</li>";
        i++;
        continue;
      }

      closeList();
      paragraphBuffer.push(line);
      i++;
    }
    flushParagraph();
    closeList();
    return html;
  }

  function wireInlineEditable(el, opts){
    function renderView(){
      var val = opts.getValue();
      el.innerHTML = val ? linkify(val) : "";
    }
    renderView();

    function activate(){
      if(opts.readOnly) return;
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
      '<button type="button" class="glow-banner" hidden></button>' +
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

    var taskList = el.querySelector(".task-list");
    var taskCountEl = el.querySelector(".task-count");
    var progressFill = el.querySelector(".progress-fill");
    var startBtn = el.querySelector(".start-btn");
    var stopBtn = el.querySelector(".stop-btn");
    var glowBanner = el.querySelector(".glow-banner");

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

    glowBanner.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    glowBanner.addEventListener("click", function(e){
      e.stopPropagation();
      openChatModal(board.id);
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
          renderTasks();
          updateMeta();
          refreshTaskDetailIfOpen(board.id, data.taskId);
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
      activeBoardStreams.push(eventSource);
    }catch(e){}

    function renderTasks(){
      taskList.innerHTML = "";
      var openTasks = board.tasks.filter(function(t){ return !t.done; });
      var doneTasks = board.tasks.filter(function(t){ return t.done; });

      openTasks.forEach(function(task){
        var li = document.createElement("li");
        // Task-level glow taxonomy (Phase 7): `needs-approval` and
        // `needs-reply` mirror the board-level precedence
        // (needs_approval > needs_reply > processing > done > none) at the
        // individual task a human would actually act on. `awaiting_reply`,
        // `awaiting_clarification` and `manual` all share `needs-reply` —
        // each is the agent waiting on a human's text reply in chat, just
        // for a different reason — while keeping their own specific classes
        // below for the existing distinct badge copy.
        var needsApproval = task.status === "awaiting_approval";
        var needsReply = task.status === "awaiting_reply" || task.status === "awaiting_clarification" || task.status === "manual";
        li.className = "task" +
          (task.status === "running" ? " running" : "") +
          (task.status === "queued" ? " queued" : "") +
          (task.status === "awaiting_clarification" ? " needs-input" : "") +
          (task.status === "manual" ? " manual-pending" : "") +
          (needsApproval ? " needs-approval" : "") +
          (needsReply ? " needs-reply" : "");
        li.setAttribute("data-done", "false");
        var badge = task.status === "queued" ? '<span class="task-queued-badge">waiting…</span>'
          : task.status === "awaiting_clarification" ? '<span class="task-queued-badge">question&hellip;</span>'
          : task.status === "manual" ? '<span class="task-queued-badge">manual pending&hellip;</span>'
          : task.status === "awaiting_approval" ? '<span class="task-queued-badge">needs approval&hellip;</span>'
          : task.status === "awaiting_reply" ? '<span class="task-queued-badge">question&hellip;</span>'
          : (task.status === "idle" && task.statusReason) ? '<span class="task-queued-badge">' + task.statusReason + '</span>'
          : "";
        var runnable = !readOnly && TASK_RUNNABLE_STATUSES[task.status];
        var stoppable = !readOnly && TASK_STOPPABLE_STATUSES[task.status];
        li.innerHTML =
          '<button class="task-check" aria-label="Mark task done">' + checkIcon() + "</button>" +
          '<span class="task-text" spellcheck="false"></span>' +
          badge +
          (runnable ? '<button class="task-run-btn" title="Run this task" aria-label="Run this task">' + runIcon() + "</button>" : "") +
          (stoppable ? '<button class="task-stop-btn" title="Stop this task" aria-label="Stop this task">' + stopIcon() + "</button>" : "") +
          '<button class="task-edit-btn" aria-label="Edit task text">' + pencilIcon() + "</button>" +
          '<button class="task-del" aria-label="Delete task">&times;</button>';

        if(runnable){
          var runBtn = li.querySelector(".task-run-btn");
          runBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
          runBtn.addEventListener("click", function(e){
            e.stopPropagation();
            runBtn.disabled = true;
            apiPost("/boards/" + board.id + "/tasks/" + task.id + "/run").then(function(resp){
              if(resp && resp.tasks){ board.tasks = resp.tasks; board.status = resp.status; }
              renderTasks();
              updateMeta();
            }).catch(function(){ runBtn.disabled = false; });
          });
        }

        if(stoppable){
          var stopBtnEl = li.querySelector(".task-stop-btn");
          stopBtnEl.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
          stopBtnEl.addEventListener("click", function(e){
            e.stopPropagation();
            stopBtnEl.disabled = true;
            apiPost("/boards/" + board.id + "/tasks/" + task.id + "/stop").then(function(resp){
              if(resp && resp.tasks){ board.tasks = resp.tasks; board.status = resp.status; }
              renderTasks();
              updateMeta();
            }).catch(function(){ stopBtnEl.disabled = false; });
          });
        }

        li.querySelector(".task-edit-btn").disabled = readOnly;
        li.querySelector(".task-edit-btn").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
        li.querySelector(".task-edit-btn").addEventListener("click", function(e){
          e.stopPropagation();
          if(readOnly) return;
          textEditable.activate();
        });

        li.querySelector(".task-check").disabled = readOnly;
        li.querySelector(".task-check").addEventListener("click", function(){
          if(readOnly) return;
          task.done = true;
          renderTasks();
          updateMeta();
          apiPatch("/boards/" + board.id + "/tasks/" + task.id, {done: true}).catch(function(){});
        });

        var textEl = li.querySelector(".task-text");
        var textEditable = wireInlineEditable(textEl, {
          editOnClick: false,
          readOnly: readOnly,
          getValue: function(){ return task.text; },
          setValue: function(val){
            var after = val;
            task.text = after;
            apiPatch("/boards/" + board.id + "/tasks/" + task.id, {text: after}).catch(function(){});
          },
          onEmpty: function(){
            board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
            renderTasks();
            updateMeta();
            apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
          }
        });

        li.addEventListener("click", function(e){
          if(readOnly) return;
          if(e.target.closest(".task-check, .task-run-btn, .task-stop-btn, .task-edit-btn, .task-del, a")) return;
          if(textEl.isContentEditable) return;
          openTaskDetailModal(board.id, task);
        });

        li.querySelector(".task-del").disabled = readOnly;
        li.querySelector(".task-del").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
        li.querySelector(".task-del").addEventListener("click", function(){
          if(readOnly) return;
          board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
          renderTasks();
          updateMeta();
          apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
        });

        taskList.appendChild(li);
      });

      if(doneTasks.length){
        var sep = document.createElement("li");
        sep.className = "task-separator";
        sep.innerHTML =
          '<span class="task-separator-label">Completed (' + doneTasks.length + ")</span>" +
          '<button class="clear-completed-btn" type="button"' + (readOnly ? " disabled" : "") + ">Clear all</button>";
        sep.querySelector(".clear-completed-btn").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
        sep.querySelector(".clear-completed-btn").addEventListener("click", function(e){
          e.stopPropagation();
          if(readOnly) return;
          board.tasks = board.tasks.filter(function(t){ return !t.done; });
          renderTasks();
          updateMeta();
          apiPost("/boards/" + board.id + "/tasks/clear-completed").catch(function(){});
        });
        taskList.appendChild(sep);

        doneTasks.forEach(function(task){ taskList.appendChild(buildCompletedItem(task)); });
      }
    }

    function updateMeta(){
      var total = board.tasks.length;
      var done = board.tasks.filter(function(t){ return t.done; }).length;
      var open = total - done;
      taskCountEl.textContent = total ? (open + (open === 1 ? " task left" : " tasks left")) : "No tasks yet";
      progressFill.style.width = total ? Math.round((done / total) * 100) + "%" : "0%";
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
      li.addEventListener("click", function(e){
        if(e.target.closest(".task-check, .task-del, a")) return;
        openTaskDetailModal(board.id, task);
      });
      li.querySelector(".task-check").disabled = readOnly;
      li.querySelector(".task-check").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
      li.querySelector(".task-check").addEventListener("click", function(){
        if(readOnly) return;
        task.done = false;
        renderTasks();
        updateMeta();
        apiPatch("/boards/" + board.id + "/tasks/" + task.id, {done: false}).catch(function(){});
      });
      li.querySelector(".task-del").disabled = readOnly;
      li.querySelector(".task-del").addEventListener("pointerdown", function(e){ e.stopPropagation(); });
      li.querySelector(".task-del").addEventListener("click", function(){
        if(readOnly) return;
        board.tasks = board.tasks.filter(function(t){ return t.id !== task.id; });
        renderTasks();
        updateMeta();
        apiDelete("/boards/" + board.id + "/tasks/" + task.id).catch(function(){});
      });
      return li;
    }

    renderTasks();
    updateMeta();

    var form = el.querySelector(".task-add");
    var input = form.querySelector("input");
    if(readOnly){ form.hidden = true; }
    input.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    form.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    form.addEventListener("submit", function(e){
      e.preventDefault();
      if(readOnly) return;
      var val = input.value.trim();
      if(!val) return;
      input.value = "";
      apiPost("/boards/" + board.id + "/tasks", {text: val}).then(function(task){
        board.tasks.push(task);
        renderTasks();
        updateMeta();
      }).catch(function(){});
    });

    var colorBtn = el.querySelector(".color-btn");
    var colorDot = el.querySelector(".color-dot");
    colorDot.textContent = labelInitial(board);
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
      HUES.forEach(function(h){
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
      pop.appendChild(buildLabelPopSection(el, board, pop));
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
      openChatModal(board.id);
    });

    var completeBoardBtn = el.querySelector(".complete-btn");
    completeBoardBtn.disabled = readOnly;
    completeBoardBtn.addEventListener("pointerdown", function(e){ e.stopPropagation(); });
    completeBoardBtn.addEventListener("click", function(e){
      if(readOnly) return;
      e.stopPropagation();
      board.completed = true;
      renderAll();
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
        boards = boards.filter(function(b){ return b.id !== board.id; });
        if(eventSource) eventSource.close();
        el.remove();
        updateCount();
        apiDelete("/boards/" + board.id).catch(function(){});
      });
      el.querySelector(".card-header-actions").appendChild(pop);
    });

    // ---- drag ----
    var header = el.querySelector(".card-header");
    header.addEventListener("pointerdown", function(e){
      if(readOnly) return;
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

  function buildActionRequestEl(board, chat, m){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";

    if(m.text){
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.innerHTML = renderMarkdown(m.text);
      col.appendChild(bubble);
    }

    var payload = m.payload || {};
    var card = document.createElement("div");
    card.className = "action-card";

    var desc = document.createElement("div");
    desc.className = "action-card-desc";
    desc.textContent = payload.description || ("Proposed action: " + payload.tool);
    card.appendChild(desc);

    var status = document.createElement("div");
    status.className = "action-card-status action-status-" + (payload.status || "pending");
    card.appendChild(status);

    function renderStatus(){
      if(payload.status === "approved"){
        status.className = "action-card-status action-status-approved";
        status.textContent = "Approved" + (payload.result ? " — " + payload.result : "");
      } else if(payload.status === "rejected"){
        status.className = "action-card-status action-status-rejected";
        status.textContent = "Rejected";
      } else {
        status.className = "action-card-status action-status-pending";
        status.textContent = "Waiting for approval";
      }
    }
    renderStatus();

    if(payload.status === "pending"){
      var actions = document.createElement("div");
      actions.className = "action-card-buttons";
      var approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.className = "action-approve-btn";
      approveBtn.textContent = "Approve";
      var rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "action-reject-btn";
      rejectBtn.textContent = "Reject";

      function decide(approved){
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        status.textContent = approved ? "Approving…" : "Rejecting…";
        var path = "/boards/" + board.id + "/chats/" + chat.id + "/messages/" + m.id + "/" + (approved ? "approve" : "reject");
        apiPost(path).then(function(resp){
          board.chats = resp.chats;
          board.activeChatId = resp.activeChatId;
          board.tasks = resp.tasks;
          board.status = resp.status;
          if(chatBoardId === board.id) renderChatMessages();
          if(taskDetailBoardId === board.id && taskDetailTaskId === (m.payload || {}).taskId) loadTaskDetail(board.id, taskDetailTaskId);
        }).catch(function(){
          approveBtn.disabled = false;
          rejectBtn.disabled = false;
          renderStatus();
        });
      }

      approveBtn.addEventListener("click", function(){ decide(true); });
      rejectBtn.addEventListener("click", function(){ decide(false); });
      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      card.appendChild(actions);
    }

    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildDelegationRequestEl(m){
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";

    if(m.text){
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      bubble.innerHTML = renderMarkdown(m.text);
      col.appendChild(bubble);
    }

    var payload = m.payload || {};
    var card = document.createElement("div");
    card.className = "action-card";

    var desc = document.createElement("div");
    desc.className = "action-card-desc";
    desc.textContent = "Delegated to " + (payload.targetAgentName || "another Agent") + ": " + (payload.request || "");
    card.appendChild(desc);

    var status = document.createElement("div");
    if(payload.status === "resolved"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Resolved" + (payload.result ? " — " + payload.result : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting on delegated Agent…";
    }
    card.appendChild(status);

    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildChatMessageEl(board, chat, m){
    if(m.type === "action_request") return buildActionRequestEl(board, chat, m);
    if(m.type === "delegation_request") return buildDelegationRequestEl(m);
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + m.role;
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = m.text ? renderMarkdown(m.text) : "";
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
      messages.forEach(function(m){ chatModalBody.appendChild(buildChatMessageEl(board, chat, m)); });
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

  var CHAT_TITLE_MAX_CHARS = 25;

  function setModalTitle(el, text){
    var full = text || "";
    el.textContent = full.length > CHAT_TITLE_MAX_CHARS
      ? full.slice(0, CHAT_TITLE_MAX_CHARS - 1).trimEnd() + "…"
      : full;
    el.title = full;
  }

  async function openChatModal(boardId){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    if(chatBoardId !== boardId) abortActiveChatStream();
    chatBoardId = boardId;
    setModalTitle(chatModalTitle, board.title || "Untitled board");
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

  function buildClarificationRequestEl(m){
    var payload = m.payload || {};
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = renderMarkdown(m.text || payload.question || "");
    col.appendChild(bubble);
    var card = document.createElement("div");
    card.className = "action-card";
    var status = document.createElement("div");
    if(payload.status === "answered"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Answered" + (payload.answer ? " — " + payload.answer : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting for your answer — reply below";
    }
    card.appendChild(status);
    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildManualHoldEl(m){
    var payload = m.payload || {};
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    var col = document.createElement("div");
    col.className = "action-msg-col";
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = renderMarkdown(m.text || payload.note || "");
    col.appendChild(bubble);
    var card = document.createElement("div");
    card.className = "action-card";
    var status = document.createElement("div");
    if(payload.status === "resolved"){
      status.className = "action-card-status action-status-approved";
      status.textContent = "Resolved" + (payload.resolution ? " — " + payload.resolution : "");
    } else {
      status.className = "action-card-status action-status-pending";
      status.textContent = "Waiting on an external reply — reply below once you know what happened";
    }
    card.appendChild(status);
    col.appendChild(card);
    wrap.appendChild(col);
    return wrap;
  }

  function buildOwnTaskMessageEl(board, chat, m){
    if(m.type === "action_request") return buildActionRequestEl(board, chat, m);
    if(m.type === "clarification_request") return buildClarificationRequestEl(m);
    if(m.type === "manual_hold") return buildManualHoldEl(m);
    return buildTaskDetailMessageEl(m);
  }

  function buildTaskDetailMessageEl(m){
    if(m.type === "delegation_request") return buildDelegationRequestEl(m);
    if(m.type === "clarification_request") return buildClarificationRequestEl(m);
    if(m.type === "manual_hold") return buildManualHoldEl(m);
    if(m.type === "action_request"){
      var payload = m.payload || {};
      var wrap = document.createElement("div");
      wrap.className = "chat-msg chat-msg-assistant";
      var col = document.createElement("div");
      col.className = "action-msg-col";
      if(m.text){
        var bubble = document.createElement("div");
        bubble.className = "chat-bubble";
        bubble.innerHTML = renderMarkdown(m.text);
        col.appendChild(bubble);
      }
      var card = document.createElement("div");
      card.className = "action-card";
      var desc = document.createElement("div");
      desc.className = "action-card-desc";
      desc.textContent = payload.description || ("Proposed action: " + payload.tool);
      card.appendChild(desc);
      var status = document.createElement("div");
      if(payload.status === "approved"){
        status.className = "action-card-status action-status-approved";
        status.textContent = "Approved" + (payload.result ? " — " + payload.result : "");
      } else if(payload.status === "rejected"){
        status.className = "action-card-status action-status-rejected";
        status.textContent = "Rejected";
      } else {
        status.className = "action-card-status action-status-pending";
        status.textContent = "Waiting for approval";
      }
      card.appendChild(status);
      col.appendChild(card);
      wrap.appendChild(col);
      return wrap;
    }
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + m.role;
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.innerHTML = m.text ? renderMarkdown(m.text) : "";
    wrap.appendChild(bubble);
    return wrap;
  }

  async function openTaskDetailModal(boardId, task){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    taskDetailBoardId = boardId;
    taskDetailTaskId = task.id;
    taskDetailChatId = null;
    setModalTitle(taskDetailTitle, task.text || "Task");
    taskDetailSubtitle.textContent = task.status ? ("Status: " + task.status) : "";
    var runnable = TASK_RUNNABLE_STATUSES[task.status] && board.myRole !== "viewer";
    var stoppable = TASK_STOPPABLE_STATUSES[task.status] && board.myRole !== "viewer";
    taskDetailRunBtn.hidden = !runnable;
    taskDetailRunBtn.disabled = !runnable;
    taskDetailStopBtn.hidden = !stoppable;
    taskDetailStopBtn.disabled = !stoppable;
    taskDetailModal.hidden = false;
    closeAllPopovers();
    activateTaskDetailTab("chat");
    taskDetailBody.innerHTML = '<div class="chat-empty">Loading&hellip;</div>';
    taskDetailActivityBody.innerHTML = "";
    taskDetailTextarea.value = "";
    await loadTaskDetail(boardId, task.id);
    if(taskDetailBoardId === boardId && taskDetailTaskId === task.id) taskDetailTextarea.focus();
  }

  async function loadTaskDetail(boardId, taskId){
    var board = boards.find(function(b){ return b.id === boardId; });
    if(!board) return;
    try{
      var results = await Promise.all([
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/activity"),
        apiGet("/boards/" + boardId + "/tasks/" + taskId + "/chat")
      ]);
      if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
      var activity = results[0];
      var chatData = results[1];
      taskDetailChatId = chatData.chatId;
      renderTaskDetailActivity(board, {id: chatData.chatId, messages: chatData.messages}, activity);
    }catch(e){
      if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
      taskDetailBody.innerHTML = '<div class="chat-empty">Couldn&rsquo;t load this task&rsquo;s activity.</div>';
    }
  }

  function buildCountsSummary(counts){
    var el = document.createElement("div");
    el.className = "task-detail-counts";
    var parts = [
      (counts.agents || 0) + " agent" + (counts.agents === 1 ? "" : "s"),
      (counts.subAgents || 0) + " sub-agent" + (counts.subAgents === 1 ? "" : "s"),
      (counts.peerAgents || 0) + " peer Agent" + (counts.peerAgents === 1 ? "" : "s"),
    ];
    el.textContent = parts.join(" · ") + " have worked this task";
    return el;
  }

  function buildTranscriptEl(transcript){
    var list = document.createElement("div");
    list.className = "transcript-list";
    (transcript || []).forEach(function(entry){
      var row = document.createElement("div");
      row.className = "transcript-entry transcript-role-" + (entry.role || "text");
      var roleLabel = document.createElement("span");
      roleLabel.className = "transcript-role-label";
      roleLabel.textContent = entry.role === "tool_call" ? "tool call"
        : entry.role === "tool_result" ? "tool result"
        : entry.role;
      row.appendChild(roleLabel);
      var textEl = document.createElement("span");
      textEl.className = "transcript-text";
      var isRawText = entry.role === "tool_call" || entry.role === "tool_result";
      if(isRawText){
        textEl.textContent = entry.text || "";
      } else {
        textEl.innerHTML = entry.text ? renderMarkdown(entry.text) : "";
      }
      row.appendChild(textEl);
      list.appendChild(row);
    });
    return list;
  }

  function buildSubAgentSection(subAgentRuns){
    var details = document.createElement("details");
    details.className = "task-detail-collapsible";
    var summary = document.createElement("summary");
    summary.textContent = "Sub-agent activity (" + subAgentRuns.length + ")";
    details.appendChild(summary);
    if(!subAgentRuns.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "No sub-agents were spun up for this task.";
      details.appendChild(empty);
      return details;
    }
    subAgentRuns.forEach(function(run){
      var card = document.createElement("div");
      card.className = "subagent-run-card";
      var header = document.createElement("div");
      header.className = "subagent-run-header";
      header.textContent = (run.instructions || "Sub-agent") + " — " + run.status;
      card.appendChild(header);
      if(run.allowedTools && run.allowedTools.length){
        var toolsEl = document.createElement("div");
        toolsEl.className = "subagent-run-tools";
        toolsEl.textContent = "Tools: " + run.allowedTools.join(", ");
        card.appendChild(toolsEl);
      }
      card.appendChild(buildTranscriptEl(run.transcript));
      details.appendChild(card);
    });
    return details;
  }

  function buildPeerAgentSection(peerDelegations){
    var details = document.createElement("details");
    details.className = "task-detail-collapsible";
    var summary = document.createElement("summary");
    summary.textContent = "Peer Agent conversation (" + peerDelegations.length + ")";
    details.appendChild(summary);
    if(!peerDelegations.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "This task was never delegated to another Agent.";
      details.appendChild(empty);
      return details;
    }
    peerDelegations.forEach(function(peer){
      var card = document.createElement("div");
      card.className = "subagent-run-card";
      var header = document.createElement("div");
      header.className = "subagent-run-header";
      header.textContent = "Delegated to " + (peer.toAgentName || peer.toAgentId) + " — " + peer.status;
      card.appendChild(header);
      if(!peer.accessible){
        var restricted = document.createElement("p");
        restricted.className = "settings-hint";
        restricted.textContent = "You don't have access to that Agent's board, so its conversation isn't shown here.";
        card.appendChild(restricted);
      } else if(!peer.messages.length){
        var waiting = document.createElement("p");
        waiting.className = "settings-hint";
        waiting.textContent = "No activity yet on the delegated task.";
        card.appendChild(waiting);
      } else {
        peer.messages.forEach(function(m){ card.appendChild(buildTaskDetailMessageEl(m)); });
      }
      details.appendChild(card);
    });
    return details;
  }

  function renderTaskDetailActivity(board, chat, activity){
    var task = findTask(board, taskDetailTaskId);
    if(task){
      setModalTitle(taskDetailTitle, task.text || "Task");
      taskDetailSubtitle.textContent = task.status ? ("Status: " + task.status) : "";
    }
    var runnable = !!task && TASK_RUNNABLE_STATUSES[task.status] && board.myRole !== "viewer";
    var stoppable = !!task && TASK_STOPPABLE_STATUSES[task.status] && board.myRole !== "viewer";
    taskDetailRunBtn.hidden = !runnable;
    taskDetailRunBtn.disabled = !runnable;
    taskDetailStopBtn.hidden = !stoppable;
    taskDetailStopBtn.disabled = !stoppable;
    taskDetailBody.innerHTML = "";
    var messages = chat.messages || [];
    if(!messages.length){
      var empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "No activity yet for this task. Say something below to get started.";
      taskDetailBody.appendChild(empty);
    } else {
      messages.forEach(function(m){ taskDetailBody.appendChild(buildOwnTaskMessageEl(board, chat, m)); });
    }
    taskDetailBody.scrollTop = taskDetailBody.scrollHeight;

    taskDetailActivityBody.innerHTML = "";
    taskDetailActivityBody.appendChild(buildCountsSummary(activity.counts || {}));
    taskDetailActivityBody.appendChild(buildSubAgentSection(activity.subAgentRuns || []));
    taskDetailActivityBody.appendChild(buildPeerAgentSection(activity.peerDelegations || []));
  }

  function closeTaskDetailModal(){
    taskDetailModal.hidden = true;
    taskDetailBoardId = null;
    taskDetailTaskId = null;
    taskDetailChatId = null;
  }

  function refreshTaskDetailIfOpen(boardId, taskId){
    if(taskDetailBoardId !== boardId || taskDetailTaskId !== taskId) return;
    loadTaskDetail(boardId, taskId);
  }

  async function sendTaskDetailMessage(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    var text = taskDetailTextarea.value.trim();
    if(!text || taskDetailSending || !boardId || !taskId) return;

    taskDetailSending = true;
    taskDetailSendBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/chat/messages", {text: text});
      var board = boards.find(function(b){ return b.id === boardId; });
      if(board && resp && resp.chats){
        board.chats = resp.chats;
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      taskDetailTextarea.value = "";
      autoSizeTaskDetailTextarea();
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }catch(e){
      // Left in the textarea so the user can retry.
    }finally{
      taskDetailSending = false;
      taskDetailSendBtn.disabled = false;
    }
  }

  function autoSizeTaskDetailTextarea(){
    taskDetailTextarea.style.height = "auto";
    taskDetailTextarea.style.height = Math.min(taskDetailTextarea.scrollHeight, 160) + "px";
  }

  async function runSingleTask(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    if(!boardId || !taskId || taskDetailRunBtn.disabled) return;
    taskDetailRunBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/run");
      var board = boards.find(function(b){ return b.id === boardId; });
      if(board && resp && resp.tasks){
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }
  }

  async function stopSingleTask(){
    var boardId = taskDetailBoardId;
    var taskId = taskDetailTaskId;
    if(!boardId || !taskId || taskDetailStopBtn.disabled) return;
    taskDetailStopBtn.disabled = true;
    try{
      var resp = await apiPost("/boards/" + boardId + "/tasks/" + taskId + "/stop");
      var board = boards.find(function(b){ return b.id === boardId; });
      if(board && resp && resp.tasks){
        board.tasks = resp.tasks;
        board.status = resp.status;
      }
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }catch(e){
      if(taskDetailBoardId === boardId && taskDetailTaskId === taskId) await loadTaskDetail(boardId, taskId);
    }
  }

  var TASK_DETAIL_TAB_PANELS = {chat: taskDetailBody, activity: taskDetailActivityBody};
  var TASK_DETAIL_TAB_BUTTONS = {chat: taskDetailTabBtnChat, activity: taskDetailTabBtnActivity};

  function activateTaskDetailTab(name){
    Object.keys(TASK_DETAIL_TAB_PANELS).forEach(function(key){
      TASK_DETAIL_TAB_PANELS[key].hidden = key !== name;
      TASK_DETAIL_TAB_BUTTONS[key].classList.toggle("active", key === name);
      TASK_DETAIL_TAB_BUTTONS[key].setAttribute("aria-selected", key === name ? "true" : "false");
    });
    taskDetailForm.hidden = name !== "chat";
  }

  function wireTaskDetailModal(){
    TASK_DETAIL_TAB_BUTTONS.chat.addEventListener("click", function(){ activateTaskDetailTab("chat"); });
    TASK_DETAIL_TAB_BUTTONS.activity.addEventListener("click", function(){ activateTaskDetailTab("activity"); });
    taskDetailClose.addEventListener("click", closeTaskDetailModal);
    taskDetailModal.addEventListener("mousedown", function(e){
      if(e.target === taskDetailModal) closeTaskDetailModal();
    });
    document.addEventListener("keydown", function(e){
      if(e.key === "Escape" && !taskDetailModal.hidden) closeTaskDetailModal();
    });
    taskDetailRunBtn.addEventListener("click", runSingleTask);
    taskDetailStopBtn.addEventListener("click", stopSingleTask);
    taskDetailForm.addEventListener("submit", function(e){
      e.preventDefault();
      sendTaskDetailMessage();
    });
    taskDetailTextarea.addEventListener("keydown", function(e){
      if(e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        if(taskDetailForm.requestSubmit) taskDetailForm.requestSubmit();
        else taskDetailForm.dispatchEvent(new Event("submit", {cancelable:true}));
      }
    });
    taskDetailTextarea.addEventListener("input", autoSizeTaskDetailTextarea);
  }

  function pencilIcon(){
    return '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13.4 3.6a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2L7 15.2l-3.2.8.8-3.2 8.8-9.2Z"/><path d="M12 5l3 3"/></svg>';
  }

  function runIcon(){
    return '<svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><path d="M6.5 4.3v11.4a1 1 0 0 0 1.53.85l8.9-5.7a1 1 0 0 0 0-1.7l-8.9-5.7a1 1 0 0 0-1.53.85Z"/></svg>';
  }

  function stopIcon(){
    return '<svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/></svg>';
  }

  // ---------------- boards ----------------

  function renderAll(){
    activeBoardStreams.forEach(function(es){ try{ es.close(); }catch(e){} });
    activeBoardStreams = [];
    canvas.innerHTML = "";
    boards.filter(function(b){ return !b.completed; }).forEach(function(board){
      canvas.appendChild(createCard(board));
    });
    updateCount();
    updateArchiveUI();
  }

  async function addBoard(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId) return;
    var scrollLeft = canvasScroll.scrollLeft / zoom, scrollTop = canvasScroll.scrollTop / zoom;
    var count = boards.length;
    var x = clamp(scrollLeft + 50 + (count % 6) * 26, 0, CANVAS_W - 300);
    var y = clamp(scrollTop + 50 + (count % 6) * 26, 0, CANVAS_H - 260);
    try{
      var board = await apiPost("/boards", {
        agentId: agentId,
        title: "New task list",
        description: "",
        color: HUES[count % HUES.length].name,
        x: x, y: y, w: 290, h: 260
      });
      board.tasks = board.tasks || [];
      boards.push(board);
      zCounter = Math.max(zCounter, board.z);
      renderAll();
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
      renderAll();
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
      return apiPost("/boards/clear" + agentQS()).then(function(newBoards){
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
      downloadFromApi("/boards/export" + agentQS(), "scatterboard-boards.json").then(function(){
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

  async function reloadBoards(){
    var agentId = window.Identity && window.Identity.getCurrentAgentId();
    if(!agentId){ boards = []; renderAll(); return; }
    try{
      boards = await window.Identity.apiGet("/agents/" + agentId + "/boards");
    }catch(e){
      boards = [];
    }
    boards.forEach(function(b){ b.tasks = b.tasks || []; });
    zCounter = boards.reduce(function(m, b){ return Math.max(m, b.z || 0); }, 10);
    renderAll();
    // Labels are cached after their first fetch — this re-render only
    // actually happens the very first time (or after a hard reload).
    var hadLabels = !!labelsCache;
    ensureLabelsLoaded().then(function(){ if(!hadLabels) renderAll(); });
  }

  async function init(){
    initTheme();
    initZoom();
    initHistoryShortcuts();
    wireChatModal();
    wireTaskDetailModal();

    var session = await window.Identity.init();
    if(!session) return;

    window.Identity.onAgentChange(reloadBoards);
    await reloadBoards();
  }

  init();
})();
