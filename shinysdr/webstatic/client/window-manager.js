// Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

// Manages hideable tiling subwindows in the ShinySDR UI.

define(['./values'], function (values) {
  'use strict';

  var StorageNamespace = values.StorageNamespace;
  
  var ELEMENT = 'shinysdr-subwindow';
  var VISIBLE_ATTRIBUTE = 'visible';

  var allWindows = [];
  var visibleCount = NaN;
  var firstUpdateDone = false;
  
  function enroll(/* this = element */) {
    var header = this.querySelector('h2');
    if (!header) {
      console.warn(ELEMENT + ' inserted without h2');
      return;
    }

    header.tabIndex = 0;

    var buttonsSlot = header.appendChild(document.createElement('span'));
    buttonsSlot.classList.add('subwindow-show-buttons');

    var showButton = document.createElement('a');
    showButton.tabIndex = 0;
    showButton.classList.add('subwindow-show-button');
    showButton.textContent = '\u25B8\u00A0' + header.textContent;

    var visible = this.hasAttribute(VISIBLE_ATTRIBUTE) ? JSON.parse(this.getAttribute(VISIBLE_ATTRIBUTE)) : true;

    if (this.id) {
      // same protocol as we install on <details>
      var ns = new StorageNamespace(localStorage, 'shinysdr.elementState.' + this.id + '.');
      var stored = ns.getItem('detailsOpen');
      if (stored !== null) visible = JSON.parse(stored);
    }

    var update = function () {
      if (visible) {
        this.style.removeProperty('display');
      } else {
        this.style.display = 'none';
      }
      if (ns) ns.setItem('detailsOpen', JSON.stringify(visible));
      
      if (firstUpdateDone) {  // don't do n^2 work on page load
        globalUpdate();
      }
    }.bind(this);
    function toggle(event) {
      // Don't grab events from controls in headers
      // There doesn't seem to be a better more composable way to handle this --
      // http://stackoverflow.com/questions/15657776/detect-default-event-handling
      if (event.target.tagName === 'INPUT') return;

      if (visible && visibleCount <= 1) return;
      visible = !visible;
      update();
      globalUpdate();
      event.stopPropagation();
    }
    // TODO look into how to accomplish automatic keyboard accessibility
    header.addEventListener('click', toggle, false);
    showButton.addEventListener('click', toggle, false);

    allWindows.push({
      element: this,
      visible: function() { return visible; },
      slot: buttonsSlot,
      button: showButton,
      update: update
    });
    allWindows.sort(function(a, b) {
      var comparison = a.element.compareDocumentPosition(b.element);
      return comparison & Node.DOCUMENT_POSITION_PRECEDING ? 1 :
             comparison & Node.DOCUMENT_POSITION_FOLLOWING ? -1 :
             0;  // shouldn't happen, bad answer
    });
    
    update();
  }
  
  function globalUpdate() {
    // Distribute show-buttons of hidden windows among headers of available visible windows.
    var lastVisibleWindow = null;
    var queued = [];
    visibleCount = 0;
    allWindows.forEach(function (r) {
      if (r.visible()) {
        visibleCount++;
        lastVisibleWindow = r;
        if (r.button.parentNode) r.button.parentNode.removeChild(r.button);
        
        queued.forEach(function (q) {
          r.slot.appendChild(q.button);
        });
        queued.length = 0;
      } else {
        if (lastVisibleWindow) {
          lastVisibleWindow.slot.appendChild(r.button);
        } else {
          queued.push(r);
        }
      }
    });
    
    // kludge to trigger relayout on other elements that need it
    // This kludge is needed because there's no way for an element to be notified on relayout.
    var resize = document.createEvent('Event');
    resize.initEvent('resize', false, false);
    window.dispatchEvent(resize);
  }
  
  // Using a custom element allows us to hook insertion/removal.
  var Subwindow_prototype = Object.create(HTMLElement.prototype);
  Subwindow_prototype.attachedCallback = enroll;
  Subwindow_prototype.detachedCallback = function() {
    allWindows = allWindows.filter(function (record) {
      return record.element != this;
    }.bind(this));
    globalUpdate();
  };
  var Subwindow = document.registerElement(ELEMENT, {
    prototype: Subwindow_prototype
    // extends: 'section'   // for some reason doing this breaks callbacks
  });
  
  globalUpdate();
  firstUpdateDone = true;
});
