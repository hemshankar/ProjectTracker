(function(){
  "use strict";

  var modal = document.getElementById("share-modal");
  var closeBtn = document.getElementById("share-modal-close");
  var titleEl = document.getElementById("share-modal-title");
  var form = document.getElementById("share-form");
  var emailInput = document.getElementById("share-email-input");
  var roleSelect = document.getElementById("share-role-select");
  var submitBtn = document.getElementById("share-submit-btn");
  var errorEl = document.getElementById("share-error");
  var listEl = document.getElementById("share-list");

  var activeBoardId = null;

  function showError(message){
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function buildShareItem(share){
    var li = document.createElement("li");
    li.className = "share-item";
    var name = document.createElement("span");
    name.className = "share-item-email";
    name.textContent = (share.user && (share.user.name || share.user.email)) || share.userId;
    var role = document.createElement("span");
    role.className = "share-item-role";
    role.textContent = share.role;
    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "share-item-remove";
    removeBtn.setAttribute("aria-label", "Remove access");
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", async function(){
      try{
        await window.Identity.apiSend("DELETE", "/boards/" + activeBoardId + "/shares/" + share.userId);
        li.remove();
      }catch(e){ showError("Could not remove access."); }
    });
    li.appendChild(name);
    li.appendChild(role);
    li.appendChild(removeBtn);
    return li;
  }

  async function renderList(){
    listEl.innerHTML = "<li class=\"share-list-loading\">Loading…</li>";
    try{
      var shares = await window.Identity.apiGet("/boards/" + activeBoardId + "/shares");
      listEl.innerHTML = "";
      if(!shares.length){
        listEl.innerHTML = "<li class=\"share-list-empty\">Not shared with anyone yet.</li>";
        return;
      }
      shares.forEach(function(s){ listEl.appendChild(buildShareItem(s)); });
    }catch(e){
      listEl.innerHTML = "<li class=\"share-list-empty\">Couldn&rsquo;t load collaborators.</li>";
    }
  }

  function open(board){
    activeBoardId = board.id;
    titleEl.textContent = "Share “" + (board.title || "Untitled board") + "”";
    showError("");
    emailInput.value = "";
    roleSelect.value = "viewer";
    modal.hidden = false;
    renderList();
    emailInput.focus();
  }

  function close(){
    modal.hidden = true;
    activeBoardId = null;
  }

  closeBtn.addEventListener("click", close);
  modal.addEventListener("mousedown", function(e){ if(e.target === modal) close(); });
  document.addEventListener("keydown", function(e){
    if(e.key === "Escape" && !modal.hidden) close();
  });

  form.addEventListener("submit", async function(e){
    e.preventDefault();
    var email = emailInput.value.trim();
    if(!email || !activeBoardId) return;
    submitBtn.disabled = true;
    showError("");
    try{
      await window.Identity.apiSend("POST", "/boards/" + activeBoardId + "/shares", {
        email: email, role: roleSelect.value
      });
      emailInput.value = "";
      await renderList();
    }catch(err){
      if(err.status === 404) showError("No user has signed in with that email yet.");
      else if(err.status === 409) showError(err.detail || "That user already has access.");
      else showError("Something went wrong. Please try again.");
    } finally {
      submitBtn.disabled = false;
    }
  });

  window.Sharing = { open: open };
})();
