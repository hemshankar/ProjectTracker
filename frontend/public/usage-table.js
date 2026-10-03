(function(){
  "use strict";

  // Breakdown table and ledger drill-down rows for the Usage tab.
  var F = window.UsageFormat;

  function cell(tr, text, cls){
    var td = document.createElement("td");
    if(cls) td.className = cls;
    td.textContent = text;
    tr.appendChild(td);
    return td;
  }

  function tag(td, text){
    var s = document.createElement("span");
    s.className = "usage-tag";
    s.textContent = text;
    td.appendChild(document.createTextNode(" "));
    td.appendChild(s);
  }

  function table(headers){
    var t = document.createElement("table");
    t.className = "usage-table";
    var tr = document.createElement("tr");
    headers.forEach(function(h){ var th = document.createElement("th"); th.textContent = h; tr.appendChild(th); });
    var head = document.createElement("thead");
    head.appendChild(tr);
    t.appendChild(head);
    return t;
  }

  function heading(container, text){
    var h = document.createElement("h3");
    h.className = "usage-heading";
    h.textContent = text;
    container.appendChild(h);
  }

  // opts: {nameOf(row), onSelect(row)}
  function renderBreakdown(container, rows, total, opts){
    container.innerHTML = "";
    heading(container, "Breakdown");
    if(!rows.length){ container.appendChild(emptyNote()); return; }
    var t = table(["#", "Name", "Calls", "Tokens", "Spend", "Share"]);
    var body = document.createElement("tbody");
    rows.forEach(function(r, i){
      var tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.className = "usage-click";
      cell(tr, String(i + 1));
      var name = cell(tr, opts.nameOf(r));
      if(r.deleted) tag(name, "deleted");
      cell(tr, String(r.calls), "num");
      cell(tr, F.compact(r.inputTokens + r.outputTokens), "num");
      cell(tr, F.usd(r.usd), "num");
      cell(tr, F.percent(r.usd, total), "num");
      tr.addEventListener("click", function(){ opts.onSelect(r); });
      tr.addEventListener("keydown", function(e){ if(e.key === "Enter") opts.onSelect(r); });
      body.appendChild(tr);
    });
    t.appendChild(body);
    container.appendChild(t);
  }

  function emptyNote(){
    var p = document.createElement("p");
    p.className = "settings-hint";
    p.textContent = "No usage in this range";
    return p;
  }

  function rowTitle(r, kind){
    var name = kind === "board" ? (r.boardTitle || r.boardId) : (r.taskTitle || r.taskId);
    var gone = kind === "board" ? r.boardDeleted : r.taskDeleted;
    return {name: name || "—", gone: gone};
  }

  // opts: {onMore(), onTrace(callId), hasMore}
  function renderRows(container, rows, opts, append){
    var body = container.querySelector("tbody");
    if(!append || !body){
      container.innerHTML = "";
      heading(container, "Calls");
      if(!rows.length){ container.appendChild(emptyNote()); return; }
      var t = table(["Time", "Board", "Task", "Kind", "Model", "Tokens", "Spend", "Outcome"]);
      body = document.createElement("tbody");
      t.appendChild(body);
      container.appendChild(t);
    }
    rows.forEach(function(r){ body.appendChild(rowEl(r, opts)); });
    var more = container.querySelector(".usage-more");
    if(more) more.remove();
    if(opts.hasMore){
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn usage-more";
      btn.textContent = "Load more";
      btn.addEventListener("click", opts.onMore);
      container.appendChild(btn);
    }
  }

  function rowEl(r, opts){
    var tr = document.createElement("tr");
    tr.className = "usage-click";
    cell(tr, new Date(r.ts).toLocaleString());
    var b = rowTitle(r, "board"), k = rowTitle(r, "task");
    var bc = cell(tr, b.name); if(b.gone) tag(bc, "deleted");
    var kc = cell(tr, k.name); if(k.gone) tag(kc, "deleted");
    cell(tr, r.callKind);
    var mc = cell(tr, r.model);
    if(r.estimated) tag(mc, "estimated");
    cell(tr, F.compact((r.inputTokens || 0) + (r.outputTokens || 0)), "num");
    cell(tr, F.usd(r.usd), "num");
    cell(tr, r.outcome);
    tr.addEventListener("click", function(){ toggleDetail(tr, r, opts); });
    return tr;
  }

  function toggleDetail(tr, r, opts){
    var next = tr.nextElementSibling;
    if(next && next.classList.contains("usage-detail")){ next.remove(); return; }
    var d = document.createElement("tr");
    d.className = "usage-detail";
    var td = document.createElement("td");
    td.colSpan = 8;
    var pre = document.createElement("pre");
    pre.textContent = JSON.stringify(r, null, 2);
    td.appendChild(pre);
    var traceId = r.llmCallRef || r.callId;
    if(traceId){
      var link = document.createElement("button");
      link.type = "button";
      link.className = "btn";
      link.textContent = "View trace";
      link.addEventListener("click", function(){ opts.onTrace(traceId); });
      td.appendChild(link);
    }
    d.appendChild(td);
    tr.after(d);
  }

  window.UsageTable = {renderBreakdown: renderBreakdown, renderRows: renderRows};
})();
