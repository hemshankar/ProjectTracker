(function(){
  "use strict";

  var CANVAS_W = 2600, CANVAS_H = 1600;
  var MIN_W = 220, MIN_H = 180;
  var ZOOM_MIN = 0.3, ZOOM_MAX = 2, ZOOM_STEP = 0.1, ZOOM_DEFAULT = 1;
  var CHAT_TITLE_MAX_CHARS = 25;

  var TASK_RUNNABLE_STATUSES = {idle: true, failed: true, stopped: true, blocked: true};
  var TASK_STOPPABLE_STATUSES = {
    running: true, queued: true, awaiting_approval: true, awaiting_reply: true,
    awaiting_clarification: true, manual: true
  };

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

  function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }

  function closeAllPopovers(){
    document.querySelectorAll(".popover").forEach(function(p){ p.remove(); });
  }

  function setModalTitle(el, text){
    var full = text || "";
    el.textContent = full.length > CHAT_TITLE_MAX_CHARS
      ? full.slice(0, CHAT_TITLE_MAX_CHARS - 1).trimEnd() + "…"
      : full;
    el.title = full;
  }

  function wireInlineEditable(el, opts){
    function renderView(){
      var val = opts.getValue();
      el.innerHTML = val ? window.BoardMarkdown.linkify(val) : "";
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
  function pencilIcon(){
    return '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13.4 3.6a1.4 1.4 0 0 1 2 0l1 1a1.4 1.4 0 0 1 0 2L7 15.2l-3.2.8.8-3.2 8.8-9.2Z"/><path d="M12 5l3 3"/></svg>';
  }
  function runIcon(){
    return '<svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><path d="M6.5 4.3v11.4a1 1 0 0 0 1.53.85l8.9-5.7a1 1 0 0 0 0-1.7l-8.9-5.7a1 1 0 0 0-1.53.85Z"/></svg>';
  }
  function stopIcon(){
    return '<svg viewBox="0 0 20 20" fill="currentColor" stroke="none"><rect x="5.5" y="5.5" width="9" height="9" rx="1.5"/></svg>';
  }
  function moveIcon(){
    return '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M10 3v14M3 10h14"/>' +
      '<path d="M10 3 7.8 5.2M10 3l2.2 2.2M10 17l-2.2-2.2M10 17l2.2-2.2M3 10l2.2-2.2M3 10l2.2 2.2M17 10l-2.2-2.2M17 10l-2.2 2.2"/>' +
      "</svg>";
  }

  window.BoardUtil = {
    CANVAS_W: CANVAS_W, CANVAS_H: CANVAS_H,
    MIN_W: MIN_W, MIN_H: MIN_H,
    ZOOM_MIN: ZOOM_MIN, ZOOM_MAX: ZOOM_MAX, ZOOM_STEP: ZOOM_STEP, ZOOM_DEFAULT: ZOOM_DEFAULT,
    TASK_RUNNABLE_STATUSES: TASK_RUNNABLE_STATUSES,
    TASK_STOPPABLE_STATUSES: TASK_STOPPABLE_STATUSES,
    HUES: HUES,
    hueValue: hueValue,
    clamp: clamp,
    closeAllPopovers: closeAllPopovers,
    setModalTitle: setModalTitle,
    wireInlineEditable: wireInlineEditable,
    checkIcon: checkIcon,
    pencilIcon: pencilIcon,
    runIcon: runIcon,
    stopIcon: stopIcon,
    moveIcon: moveIcon
  };
})();
