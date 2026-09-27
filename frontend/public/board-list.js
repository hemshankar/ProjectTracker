(function(){
  "use strict";

  var apiPatch = window.BoardApi.apiPatch;
  var boardCountEl = document.getElementById("board-count");

  function updateCount(){
    var boards = window.BoardState.state.boards;
    var active = boards.filter(function(b){ return !b.completed; }).length;
    boardCountEl.textContent = active + (active === 1 ? " board" : " boards");
  }

  function bringToFront(board, el){
    var state = window.BoardState.state;
    state.zCounter += 1;
    board.z = state.zCounter;
    el.style.zIndex = state.zCounter;
    apiPatch("/boards/" + board.id, {z: state.zCounter}).catch(function(){});
  }

  function renderAll(){
    var state = window.BoardState.state;
    var canvas = document.getElementById("canvas");
    window.BoardSocket.reset();
    canvas.innerHTML = "";
    state.boards.filter(function(b){ return !b.completed; }).forEach(function(board){
      canvas.appendChild(window.BoardCard.create(board));
    });
    updateCount();
    window.BoardArchive.updateArchiveUI();
  }

  window.BoardList = {
    renderAll: renderAll,
    updateCount: updateCount,
    bringToFront: bringToFront
  };
})();
