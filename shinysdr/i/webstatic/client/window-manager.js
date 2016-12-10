// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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
  var WINDOW_LIST_ID = 'shinysdr-subwindow-list';

  var allWindows = [];
  var visibleCount = NaN;
  var firstUpdateDone = false;
  
  function isWindowListSubwindow(subwindowElement) {
    return subwindowElement.querySelector('#' + WINDOW_LIST_ID) != null;
  }
  
  function enroll(/* this = element */) {
    var header = this.querySelector('h2');
    if (!header) {
      console.warn(ELEMENT + ' inserted without h2');
      return;
    }

    // Modifications to element DOM.
    var leftSlot = header.insertBefore(document.createElement('span'), header.firstChild);
    var rightSlot = header.appendChild(document.createElement('span'));
    rightSlot.classList.add('subwindow-show-buttons');

    // Show-this-subwindow button to be displayed elsewhere.
    var showBtnOuter, showButton;
    if (isWindowListSubwindow(this)) {
      showBtnOuter = showButton = document.createElement('button');
      showButton.classList.add('subwindow-menu-button');
      var showButtonIcon = showButton.appendChild(document.createElement('img'));
      showButtonIcon.src = '/client/menu.svg';
      showButtonIcon.alt = '\u2261';
    } else {
      showBtnOuter = document.createElement('li');
      showBtnOuter.classList.add('subwindow-show-button');
      showButton = showBtnOuter.appendChild(document.createElement('button'));
      showButton.tabIndex = 0;
      showButton.textContent = header.textContent;
    }

    var visible = this.hasAttribute(VISIBLE_ATTRIBUTE) ? JSON.parse(this.getAttribute(VISIBLE_ATTRIBUTE)) : true;
    
    var lastUserOpenedTime = 0;

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
      showBtnOuter.classList[visible ? 'add' : 'remove']('subwindow-show-button-shown');
      if (ns) ns.setItem('detailsOpen', JSON.stringify(visible));
      
      if (firstUpdateDone) {  // don't do n^2 work on page load
        globalUpdate();
      }
    }.bind(this);
    function toggle(event) {
      // Don't grab events from controls in headers
      // There doesn't seem to be a better more composable way to handle this --
      // http://stackoverflow.com/questions/15657776/detect-default-event-handling
      if (event.target != showButton &&
          (event.target.tagName === 'INPUT'
           || event.target.tagName === 'LABEL'
           || event.target.tagName === 'BUTTON')) {
        return;
      }

      var hasFocusBefore = document.activeElement;

      if (visible && visibleCount <= 1) return;
      if (!visible) lastUserOpenedTime = Date.now();
      setVisibleAndUpdate(!visible);
      event.stopPropagation();
      
      // The focused thing might be the menu button moved by globalUpdate, so restore focus.
      if (hasFocusBefore) hasFocusBefore.focus();
    }
    function setVisibleAndUpdate(newVisible) {
      visible = newVisible;
      update();
      globalUpdate();
    }
    showButton.addEventListener('click', toggle, false);

    allWindows.push({
      element: this,
      visible: function() { return visible; },
      setVisibleAndUpdate: setVisibleAndUpdate,
      leftSlot: leftSlot,
      rightSlot: rightSlot,
      button: showBtnOuter,
      update: update,
      getLastUserOpenedTime: function () { return lastUserOpenedTime; }
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
    var windowListElement = document.getElementById(WINDOW_LIST_ID);
    
    if (closeExtraWide()) {
      // Don't do anything because closeExtraWide triggered its own update.
      return;
    }
    
    // TODO: Don't rebuild entire structure every time; this approach is a relic of a different design.
    if (!windowListElement) {
      console.warn('#' + WINDOW_LIST_ID + ' not present in document.');
    } else { 
      var windowListSubwindow;
      visibleCount = 0;
      allWindows.forEach(function (r) {
        if (r.visible()) {
          visibleCount++;
        }
        if (isWindowListSubwindow(r.element)) {
          windowListSubwindow = r;
        }
        if (windowListElement) {
          windowListElement.appendChild(r.button);
        }
      });
      
      if (windowListSubwindow) {
        allWindows.some(function (r) {
          if (r.visible()) {
            r.leftSlot.appendChild(windowListSubwindow.button);
            return true;
          }
        });
        windowListSubwindow.button.disabled = visibleCount <= 1 && windowListSubwindow.visible();
      }
    }
    
    if (visibleCount <= 0 && allWindows.length > 0) {
      // If all windows are hidden (e.g. due to bad persistent state), show one.
      allWindows[0].setVisibleAndUpdate(true);
      return;
    }
    
    // kludge to trigger relayout on other elements that need it
    // This kludge is needed because there's no way for an element to be notified on relayout.
    var resize = document.createEvent('Event');
    resize.initEvent('resize', false, false);
    window.dispatchEvent(resize);
  }
  
  // returns true if it triggered an update
  function closeExtraWide() {
    // TODO: Subwindows might be used somewhere other than document.body
    if (document.body.scrollWidth > document.body.offsetWidth) {
      var bestToClose = null;
      var bestTime = Date.now();
      allWindows.forEach(function (r) {
        // TODO: Use something other than the class name, because this module is supposed to be largely independent of other app HTML usage
        if (r.visible() && !r.element.classList.contains('stretchy') && r.getLastUserOpenedTime() < bestTime) {
          bestToClose = r;
          bestTime = r.getLastUserOpenedTime();
        }
      });
      if (bestToClose) {
        bestToClose.setVisibleAndUpdate(false);
        return true;
      }
    }
    return false;
  }
  window.addEventListener('resize', function (event) {
    closeExtraWide();
  });
  
  if (!document.registerElement) {
    console.warn('document.registerElement not supported; window management unavailable');
    return;
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
  /* const Subwindow = */ document.registerElement(ELEMENT, {
    prototype: Subwindow_prototype
    // extends: 'section'   // for some reason doing this breaks callbacks
  });
  
  globalUpdate();
  firstUpdateDone = true;
});
