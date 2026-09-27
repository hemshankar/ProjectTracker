(function(){
  "use strict";

  var apiGet = window.BoardApi.apiGet;
  var apiPost = window.BoardApi.apiPost;
  var apiPatch = window.BoardApi.apiPatch;
  var hueValue = window.BoardUtil.hueValue;

  // Labels are global (shared across every board, not per-agent), so the
  // list is fetched once and cached for the session rather than reloaded
  // per board or per agent switch.
  var labelsCache = null;
  var labelsById = {};

  function ensureLabelsLoaded(){
    if(labelsCache) return Promise.resolve(labelsCache);
    return apiGet("/labels").then(function(list){
      labelsCache = list;
      labelsById = {};
      list.forEach(function(l){ labelsById[l.id] = l; });
      return list;
    }).catch(function(){ return labelsCache || []; });
  }

  function labelInitial(board){
    var l = board.labelId && labelsById[board.labelId];
    return l ? l.name.trim().charAt(0).toUpperCase() : "";
  }

  // Builds the "assign a label" section appended below the color swatches
  // in a board's color-pop popover — lists every shared label (global,
  // reused across all boards) plus a small form to create a new one.
  function buildLabelPopSection(el, board, pop){
    var section = document.createElement("div");
    section.className = "label-pop-section";
    var list = document.createElement("div");
    list.className = "label-pop-list";
    section.appendChild(list);

    function applyLabel(labelId){
      var beforeLabel = board.labelId || "";
      var afterLabel = labelId || "";
      if(beforeLabel === afterLabel){ pop.remove(); return; }
      // A board's color is locked to its label — picking one recolors the
      // board to match; clearing one just unlocks the swatches and leaves
      // whatever color was already showing.
      var afterColor = afterLabel && labelsById[afterLabel] ? labelsById[afterLabel].color : board.color;
      board.labelId = afterLabel;
      board.color = afterColor;
      el.style.setProperty("--card-hue", hueValue(afterColor));
      el.querySelector(".color-dot").textContent = labelInitial(board);
      pop.remove();
      apiPatch("/boards/" + board.id, {labelId: afterLabel, color: afterColor}).catch(function(){});
    }

    function renderChips(){
      list.innerHTML = "";
      var none = document.createElement("button");
      none.type = "button";
      none.className = "label-chip" + (!board.labelId ? " active" : "");
      none.textContent = "No label";
      none.addEventListener("click", function(ev){ ev.stopPropagation(); applyLabel(""); });
      list.appendChild(none);
      (labelsCache || []).forEach(function(l){
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "label-chip" + (board.labelId === l.id ? " active" : "");
        chip.textContent = l.name;
        chip.addEventListener("click", function(ev){ ev.stopPropagation(); applyLabel(l.id); });
        list.appendChild(chip);
      });
    }

    renderChips();
    ensureLabelsLoaded().then(renderChips);

    var form = document.createElement("form");
    form.className = "label-pop-new";
    form.innerHTML = '<input type="text" placeholder="New label&hellip;" maxlength="16"><button type="submit">+</button>';
    form.addEventListener("click", function(ev){ ev.stopPropagation(); });
    form.addEventListener("submit", function(ev){
      ev.preventDefault();
      var input = form.querySelector("input");
      var name = input.value.trim();
      if(!name) return;
      input.disabled = true;
      apiPost("/labels", {name: name, color: board.color}).then(function(label){
        labelsCache = (labelsCache || []).concat([label]);
        labelsById[label.id] = label;
        applyLabel(label.id);
      }).catch(function(){
        input.disabled = false;
      });
    });
    section.appendChild(form);
    return section;
  }

  window.BoardLabels = {
    hasCache: function(){ return !!labelsCache; },
    ensureLabelsLoaded: ensureLabelsLoaded,
    labelInitial: labelInitial,
    buildLabelPopSection: buildLabelPopSection
  };
})();
