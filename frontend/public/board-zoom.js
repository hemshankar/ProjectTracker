(function(){
  "use strict";

  var ZOOM_KEY = "scatterboard.zoom.v1";
  var U = window.BoardUtil;
  var clamp = U.clamp;
  var CANVAS_W = U.CANVAS_W, CANVAS_H = U.CANVAS_H;
  var ZOOM_MIN = U.ZOOM_MIN, ZOOM_MAX = U.ZOOM_MAX, ZOOM_STEP = U.ZOOM_STEP, ZOOM_DEFAULT = U.ZOOM_DEFAULT;

  var zoom = ZOOM_DEFAULT;

  var canvas, canvasZoomWrapper, canvasScroll, zoomOutBtn, zoomInBtn, zoomLevelBtn;

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
    canvas = document.getElementById("canvas");
    canvasZoomWrapper = document.getElementById("canvas-zoom");
    canvasScroll = document.getElementById("canvas-scroll");
    zoomOutBtn = document.getElementById("zoom-out-btn");
    zoomInBtn = document.getElementById("zoom-in-btn");
    zoomLevelBtn = document.getElementById("zoom-level-btn");

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

  window.BoardZoom = {
    initZoom: initZoom,
    get: function(){ return zoom; }
  };
})();
