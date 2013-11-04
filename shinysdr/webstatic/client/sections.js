// Copyright 2013 Kevin Reid <kpreid@switchb.org>
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

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

    var visible = section.hasAttribute('data-visible') ? JSON.parse(section.getAttribute('data-visible')) : true;

    if (section.id) {
      // same protocol as we install on <details>
      var ns = new StorageNamespace(localStorage, 'shinysdr.elementState.' + section.id + '.');
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
      
      // kludge to trigger relayout on other elements that need it
      // This kludge is needed because there's no way for an element to be notified on relayout.
      var resize = document.createEvent('Event');
      resize.initEvent('resize', false, false);
      window.dispatchEvent(resize);
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
