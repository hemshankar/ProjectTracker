(function(){
  "use strict";

  var state = {
    boards: [],
    zCounter: 10,
    activeBoardStreams: []
  };

  function findBoard(boardId){
    return state.boards.find(function(b){ return b.id === boardId; });
  }
  function findTask(board, taskId){
    return board && board.tasks.find(function(t){ return t.id === taskId; });
  }

  window.BoardState = {
    state: state,
    findBoard: findBoard,
    findTask: findTask
  };
})();
