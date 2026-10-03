(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPut = window.BoardApi.apiPut;
  var apiPost = window.BoardApi.apiPost;
  var renderMarkdown = window.BoardMarkdown.renderMarkdown;
  var History = window.BoardTaskFieldHistory;

  var AUTOSAVE_MS = 1200;

  function el(tag, className, text){
    var node = document.createElement(tag);
    if(className) node.className = className;
    if(text) node.textContent = text;
    return node;
  }

  // One versioned long-form field of a task (Description or Execution
  // Summary) rendered into `cfg.root`: markdown view, autosaving editor,
  // stale-edit conflict banner, and revision history. Both fields share this
  // — `cfg` carries only what differs (field name, empty text, tab name).
  function TaskFieldPanel(cfg){
    this.cfg = cfg;
    this.boardId = null;
    this.taskId = null;
    this.canEdit = false;
    this.state = {content: "", version: 0, updatedAt: null, updatedBy: null, status: null};
    this.editing = false;
    this.dirty = false;
    this.saving = false;
    this.conflict = null;
    this.saveTimer = null;
    this.historyOpen = false;
    this._build();
  }

  TaskFieldPanel.prototype._path = function(boardId, taskId, suffix){
    return "/boards/" + boardId + "/tasks/" + taskId + "/fields/" + this.cfg.field + (suffix || "");
  };

  TaskFieldPanel.prototype._build = function(){
    var self = this, root = this.cfg.root;
    root.innerHTML = "";
    root.classList.add("tf-panel");
    this.metaEl = el("div", "tf-meta");
    this.bannerEl = el("div", "tf-conflict");
    this.bannerEl.hidden = true;
    this.viewEl = el("div", "tf-view");
    this.editorEl = el("textarea", "tf-editor");
    this.editorEl.placeholder = this.cfg.placeholder;
    this.editorEl.hidden = true;
    this.statusEl = el("span", "tf-save-status");
    this.actionsEl = el("div", "tf-actions");
    this.editBtn = el("button", "btn", "Edit");
    this.editBtn.type = "button";
    this.historyBtn = el("button", "btn", "History");
    this.historyBtn.type = "button";
    this.actionsEl.appendChild(this.editBtn);
    this.actionsEl.appendChild(this.historyBtn);
    this.actionsEl.appendChild(this.statusEl);
    this.historyEl = el("div", "tf-history");
    this.historyEl.hidden = true;
    [this.metaEl, this.bannerEl, this.viewEl, this.editorEl, this.actionsEl, this.historyEl]
      .forEach(function(n){ root.appendChild(n); });

    this.editBtn.addEventListener("click", function(){
      if(self.editing) self.stopEditing(); else if(self.canEdit) self.startEditing();
    });
    this.historyBtn.addEventListener("click", function(){ self.toggleHistory(); });
    this.editorEl.addEventListener("input", function(){ self._onInput(); });
    this.editorEl.addEventListener("blur", function(){ self.save(); });
    this.viewEl.addEventListener("dblclick", function(){ if(self.canEdit) self.startEditing(); });
  };

  TaskFieldPanel.prototype.open = function(boardId, taskId, canEdit){
    this.close();
    this.boardId = boardId;
    this.taskId = taskId;
    this.canEdit = canEdit;
    this.state = {content: "", version: 0, updatedAt: null, updatedBy: null, status: null};
    this.editing = false;
    this.dirty = false;
    this.conflict = null;
    this.historyOpen = false;
    this.historyEl.hidden = true;
    this.bannerEl.hidden = true;
    this.statusEl.textContent = "";
    this.render();
    return this.load();
  };

  // Flushes any unsaved draft before the panel moves on to another task.
  TaskFieldPanel.prototype.close = function(){
    clearTimeout(this.saveTimer);
    if(this.dirty && !this.conflict) this.save();
    this.boardId = null;
    this.taskId = null;
  };

  TaskFieldPanel.prototype.load = async function(){
    var boardId = this.boardId, taskId = this.taskId;
    try{
      var data = await apiGet(this._path(boardId, taskId));
      if(this.boardId !== boardId || this.taskId !== taskId) return;
      this._applyState(data);
    }catch(e){
      if(this.boardId !== boardId || this.taskId !== taskId) return;
      this.viewEl.innerHTML = '<p class="settings-hint">Couldn&rsquo;t load this.</p>';
    }
  };

  TaskFieldPanel.prototype._applyState = function(data){
    this.state = data;
    if(this.editing && !this.dirty) this.editorEl.value = data.content;
    this.render();
    if(this.cfg.onChange) this.cfg.onChange(this.taskId, data);
  };

  TaskFieldPanel.prototype.render = function(){
    var s = this.state;
    var hasContent = !!(s.content && s.content.trim());
    this.viewEl.hidden = this.editing;
    this.editorEl.hidden = !this.editing;
    this.editBtn.hidden = !this.canEdit;
    this.editBtn.textContent = this.editing ? "Done" : "Edit";
    if(!this.editing){
      this.viewEl.innerHTML = hasContent
        ? renderMarkdown(s.content)
        : '<p class="settings-hint">' + this.cfg.emptyText + "</p>";
    }
    var parts = [];
    if(s.status) parts.push(s.status.toUpperCase());
    if(s.version) parts.push("v" + s.version + " · " + History.describeAuthor(s.updatedBy) + " · " + History.formatWhen(s.updatedAt));
    this.metaEl.textContent = parts.join("  ·  ");
    this.metaEl.hidden = !parts.length;
    this.metaEl.setAttribute("data-status", s.status || "");
  };

  TaskFieldPanel.prototype.startEditing = function(){
    if(!this.canEdit) return;
    this.editing = true;
    this.editorEl.value = this.state.content;
    this.render();
    this.editorEl.focus();
  };

  TaskFieldPanel.prototype.stopEditing = async function(){
    clearTimeout(this.saveTimer);
    await this.save();
    if(this.conflict) return; // leave the editor open until the conflict is resolved
    this.editing = false;
    this.render();
  };

  TaskFieldPanel.prototype._onInput = function(){
    this.dirty = true;
    this.statusEl.textContent = "Unsaved changes…";
    clearTimeout(this.saveTimer);
    var self = this;
    this.saveTimer = setTimeout(function(){ self.save(); }, AUTOSAVE_MS);
  };

  TaskFieldPanel.prototype.save = async function(){
    if(!this.dirty || this.saving || this.conflict || !this.boardId) return;
    var boardId = this.boardId, taskId = this.taskId;
    var content = this.editorEl.value;
    this.saving = true;
    this.statusEl.textContent = "Saving…";
    try{
      var res = await apiPut(this._path(boardId, taskId), {content: content, baseVersion: this.state.version});
      this.saving = false;
      if(this.taskId !== taskId) return;
      this.state = res;
      this.dirty = this.editorEl.value !== res.content; // typed more while saving
      this.statusEl.textContent = this.dirty ? "Unsaved changes…" : "Saved";
      this.render();
      if(this.cfg.onChange) this.cfg.onChange(taskId, res);
      if(this.dirty) this._onInput();
    }catch(e){
      this.saving = false;
      if(this.taskId !== taskId) return;
      if(e.status === 409 && e.body && e.body.detail && e.body.detail.current){
        this._showConflict(e.body.detail.current);
      } else {
        this.statusEl.textContent = "Couldn’t save — will retry on your next edit";
      }
    }
  };

  TaskFieldPanel.prototype._showConflict = function(current){
    var self = this;
    this.conflict = current;
    // Keep the draft on screen even if "Done" already closed the editor.
    this.editing = true;
    this.render();
    this.statusEl.textContent = "";
    this.bannerEl.innerHTML = "";
    this.bannerEl.appendChild(el("p", "tf-conflict-msg",
      History.describeAuthor(current.updatedBy) + " changed this while you were editing. Your draft is kept below."));
    var latest = el("details", "tf-conflict-latest");
    latest.appendChild(el("summary", "", "See the latest version"));
    latest.appendChild(el("pre", "tf-conflict-pre", current.content || "(empty)"));
    this.bannerEl.appendChild(latest);
    var row = el("div", "tf-conflict-actions");
    var keep = el("button", "btn", "Overwrite with my draft");
    var take = el("button", "btn", "Discard my draft");
    keep.type = take.type = "button";
    keep.addEventListener("click", function(){
      self.state.version = current.version;
      self._clearConflict();
      self.save();
    });
    take.addEventListener("click", function(){
      self.dirty = false;
      self._clearConflict();
      self._applyState(current);
      self.editorEl.value = current.content;
    });
    row.appendChild(keep);
    row.appendChild(take);
    this.bannerEl.appendChild(row);
    this.bannerEl.hidden = false;
  };

  TaskFieldPanel.prototype._clearConflict = function(){
    this.conflict = null;
    this.bannerEl.hidden = true;
  };

  // A live update from someone else (the agent, another user): reload quietly
  // unless the user is mid-edit, in which case surface it as a conflict
  // rather than yanking the text out from under them.
  TaskFieldPanel.prototype.onRemoteVersion = async function(version){
    if(!this.boardId || version <= this.state.version) return;
    if(this.editing && this.dirty){
      try{ this._showConflict(await apiGet(this._path(this.boardId, this.taskId))); }catch(e){}
      return;
    }
    await this.load();
    if(this.historyOpen) this._loadHistory();
  };

  TaskFieldPanel.prototype.toggleHistory = function(){
    this.historyOpen = !this.historyOpen;
    this.historyEl.hidden = !this.historyOpen;
    this.historyBtn.textContent = this.historyOpen ? "Hide history" : "History";
    if(this.historyOpen) this._loadHistory();
  };

  TaskFieldPanel.prototype._loadHistory = async function(){
    var self = this, boardId = this.boardId, taskId = this.taskId;
    try{
      var data = await apiGet(this._path(boardId, taskId, "/history"));
      if(this.taskId !== taskId) return;
      History.render(this.historyEl, data.revisions || [], this.state.version, this.canEdit, function(version){
        self._restore(version);
      });
    }catch(e){
      this.historyEl.innerHTML = '<p class="settings-hint">Couldn&rsquo;t load history.</p>';
    }
  };

  TaskFieldPanel.prototype._restore = async function(version){
    var boardId = this.boardId, taskId = this.taskId;
    try{
      var res = await apiPost(this._path(boardId, taskId, "/restore"), {version: version, baseVersion: this.state.version});
      if(this.taskId !== taskId) return;
      this.dirty = false;
      this._applyState(res);
      this._loadHistory();
    }catch(e){
      if(e.status === 409 && e.body && e.body.detail){ this._applyState(e.body.detail.current); this._loadHistory(); }
    }
  };

  window.TaskFieldPanel = TaskFieldPanel;
})();
