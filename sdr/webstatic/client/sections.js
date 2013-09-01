// Manages collapsing of top-level UI sections (which are not <details> because those interact poorly with flexbox on Chrome)

define(['./values'], function (values) {
  'use strict';

  var StorageNamespace = values.StorageNamespace;

  var allSections = [];
  var visibleCount = NaN;
  Array.prototype.forEach.call(document.querySelectorAll('section'), function (section) {
    var header = section.querySelector('h2');
    if (!header) return;

    header.tabIndex = 0;

    var buttonsSlot = header.appendChild(document.createElement('span'));
    buttonsSlot.classList.add('ui-section-show-buttons');

    var showButton = document.createElement('a');
    showButton.tabIndex = 0;
    showButton.classList.add('ui-section-show-button');
    showButton.textContent = '\u25B8\u00A0' + header.textContent;

    var visible = true;

    if (section.id) {
      // same protocol as we install on <details>
      var ns = new StorageNamespace(localStorage, 'sdr.elementState.' + section.id + '.');
      var stored = ns.getItem('detailsOpen');
      if (stored !== null) visible = JSON.parse(stored);
    }

    function update() {
      if (visible) {
        section.style.removeProperty('display');
      } else {
        section.style.display = 'none';
      }
      distributeButtons();
      if (ns) ns.setItem('detailsOpen', JSON.stringify(visible));
    }
    function toggle(event) {
      if (visible && visibleCount <= 1) return;
      visible = !visible;
      update();
      event.stopPropagation();
    }
    // TODO look into how to accomplish automatic keyboard accessibility
    header.addEventListener('click', toggle, false);
    showButton.addEventListener('click', toggle, false);
    
    allSections.push({
      visible: function() { return visible; },
      slot: buttonsSlot,
      button: showButton,
      update: update
    });
  });
  function distributeButtons() {
    var lastVisibleSection = null;
    var queued = [];
    visibleCount = 0;
    allSections.forEach(function (r) {
      if (r.visible()) {
        visibleCount++;
        lastVisibleSection = r;
        if (r.button.parentNode) r.button.parentNode.removeChild(r.button);
        
        queued.forEach(function (q) {
          r.slot.appendChild(q.button);
        });
        queued.length = 0;
      } else {
        if (lastVisibleSection) {
          lastVisibleSection.slot.appendChild(r.button);
        } else {
          queued.push(r);
        }
      }
    });
  }
  allSections.forEach(function (r) { r.update(); });
  
  // TODO make this have exports rather than a side effect
});
