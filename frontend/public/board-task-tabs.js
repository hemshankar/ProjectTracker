(function(){
  "use strict";

  // Data-driven sub-tab strip for a task inside the unified chat modal. Each
  // tab is registered with its button, its body panel, and whether the chat
  // input form belongs under it — adding a tab is a `register` call, not
  // another branch in a switch.
  var form = document.getElementById("chat-modal-form");
  var tabs = [];
  var current = null;

  function register(def){
    tabs.push(def);
    def.button.addEventListener("click", function(){ show(def.name); });
  }

  function find(name){
    return tabs.find(function(t){ return t.name === name; });
  }

  function show(name){
    var target = find(name);
    if(!target) return;
    current = name;
    tabs.forEach(function(t){
      var on = t === target;
      t.panel.hidden = !on;
      t.button.classList.toggle("active", on);
      t.button.setAttribute("aria-selected", on ? "true" : "false");
    });
    form.hidden = !target.showForm;
    if(target.onShow) target.onShow();
  }

  // The chat tab's panel is also the Board tab's message list, so leaving
  // the task view only hides the panels that belong to tasks alone.
  function hideTaskOnlyPanels(){
    tabs.forEach(function(t){ if(!t.sharedPanel) t.panel.hidden = true; });
  }

  function setIndicator(name, hasContent){
    var t = find(name);
    if(t) t.button.classList.toggle("has-content", !!hasContent);
  }

  window.BoardTaskTabs = {
    register: register,
    show: show,
    current: function(){ return current; },
    hideTaskOnlyPanels: hideTaskOnlyPanels,
    setIndicator: setIndicator
  };
})();
