(function(){
  "use strict";

  var THEME_KEY = "scatterboard.theme.v1";

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

  function refreshCardHues(){
    var canvas = document.getElementById("canvas");
    var boards = window.BoardState.state.boards;
    canvas.querySelectorAll(".card").forEach(function(el){
      var board = boards.find(function(b){ return b.id === el.dataset.id; });
      if(board) el.style.setProperty("--card-hue", window.BoardUtil.hueValue(board.color));
    });
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

  window.BoardTheme = {
    initTheme: initTheme,
    refreshCardHues: refreshCardHues
  };
})();
