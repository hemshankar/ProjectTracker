(function(){
  "use strict";

  var apiPost = window.BoardApi.apiPost;
  var apiPatch = window.BoardApi.apiPatch;
  var apiDelete = window.BoardApi.apiDelete;
  var U = window.BoardUtil;
  var wireInlineEditable = U.wireInlineEditable;
  var checkIcon = U.checkIcon, runIcon = U.runIcon, stopIcon = U.stopIcon, pencilIcon = U.pencilIcon;
  var linkify = window.BoardMarkdown.linkify;
  var TASK_RUNNABLE_STATUSES = U.TASK_RUNNABLE_STATUSES;
  var TASK_STOPPABLE_STATUSES = U.TASK_STOPPABLE_STATUSES;

  function wire(ctx){
    var board = ctx.board, el = ctx.el, readOnly = ctx.readOnly;
    var taskList = el.querySelector(".task-list");
    var taskCountEl = el.querySelector(".task-count");
    var progressFill = el.querySelector(".progress-fill");

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
        window.BoardTaskDetail.open(board.id, task);
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
          window.BoardTaskDetail.open(board.id, task);
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

    ctx.renderTasks = renderTasks;
    ctx.updateMeta = updateMeta;
  }

  window.BoardCardTasks = { wire: wire };
})();
