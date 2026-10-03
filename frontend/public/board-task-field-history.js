(function(){
  "use strict";

  var renderMarkdown = window.BoardMarkdown.renderMarkdown;

  var AUTHOR_LABELS = {agent: "Agent", integration: "Integration", human: "User"};

  function describeAuthor(author){
    return (author && AUTHOR_LABELS[author.type || author]) || "Someone";
  }

  function formatWhen(ts){
    if(!ts) return "";
    try{
      return new Date(ts).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
    }catch(e){ return ""; }
  }

  function buildRow(rev, isCurrent, canEdit, onRestore){
    var row = document.createElement("details");
    row.className = "tf-history-row";
    var summary = document.createElement("summary");
    var label = "v" + rev.version + " · " + describeAuthor(rev.authorType) + " · " + formatWhen(rev.ts);
    if(rev.note) label += " · " + rev.note;
    if(isCurrent) label += " · current";
    summary.textContent = label;
    row.appendChild(summary);
    var body = document.createElement("div");
    body.className = "tf-history-body";
    body.innerHTML = rev.content ? renderMarkdown(rev.content) : '<p class="settings-hint">(empty)</p>';
    row.appendChild(body);
    if(canEdit && !isCurrent){
      var restore = document.createElement("button");
      restore.type = "button";
      restore.className = "btn tf-restore-btn";
      restore.textContent = "Restore this version";
      restore.addEventListener("click", function(){ onRestore(rev.version); });
      row.appendChild(restore);
    }
    return row;
  }

  // Renders the newest-first revision list into `container`. Restoring never
  // rewinds history — the server writes the old text as a new revision.
  function render(container, revisions, currentVersion, canEdit, onRestore){
    container.innerHTML = "";
    if(!revisions.length){
      var empty = document.createElement("p");
      empty.className = "settings-hint";
      empty.textContent = "No earlier versions yet.";
      container.appendChild(empty);
      return;
    }
    revisions.forEach(function(rev){
      container.appendChild(buildRow(rev, rev.version === currentVersion, canEdit, onRestore));
    });
  }

  window.BoardTaskFieldHistory = {render: render, describeAuthor: describeAuthor, formatWhen: formatWhen};
})();
