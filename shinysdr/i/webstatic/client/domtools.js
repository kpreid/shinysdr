// Copyright 2014, 2017, 2019 Kevin Reid and the ShinySDR contributors
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

'use strict';
  
define(() => {
  const exports = {};
  
  // DOM element life cycle facility. It is expected that:
  // "init" is fired when the element has been inserted in the document (and has approximately correct layout)
  // "destroy" is fired when the element and its children are going to be discarded (not reused)
  
  const lifecycleState = new WeakMap();
  function lifecycleInit(element) {
    if (lifecycleState.has(element)) {
      // Already inited.
      return;
    }
    
    let root = element;
    while (root.parentNode) root = root.parentNode;
    if (root.nodeType !== Node.DOCUMENT_NODE) {
      // Too early; node not in document.
      return;
    }
    
    lifecycleState.set(element, 'live');
    element.dispatchEvent(new CustomEvent('shinysdr:lifecycleinit', {bubbles: false}));
  }
  exports.lifecycleInit = lifecycleInit;
  
  function lifecycleDestroy(element) {
    const stateBeforehand = lifecycleState.get(element);
    lifecycleState.set(element, 'dead');
    
    // Fire a destroy event iff we previously fired an init event.
    if (stateBeforehand === 'live') {
      element.dispatchEvent(new CustomEvent('shinysdr:lifecycledestroy', {bubbles: false}));
    }
    
    // Destroy descendants.
    Array.prototype.forEach.call(element.children, childEl => {
      lifecycleDestroy(childEl);
    });
  }
  exports.lifecycleDestroy = lifecycleDestroy;
  
  // Is the given element visible in the sense of taking up some space in the visual layout?
  // Does not check for being obscured by other elements, clipped by a smaller container, etc, but will detect being detached from the DOM or being inside a display:none element.
  // TODO: This can false-positive if the node has no content.
  function isVisibleInLayout(node) {
    const w = node.offsetWidth;
    if (typeof w !== 'number') {
      throw new TypeError('isVisibleInLayout: cannot work with ' + node);
    }
    return w > 0;
  }
  exports.isVisibleInLayout = isVisibleInLayout;
  
  // "Reveal" facility.
  // To reveal a node is to make it visible on-screen (as opposed to hidden by some hidden/collapsed container).
  // Custom collapsible-things may add event listeners to handle revealing.
  function reveal(node) {
    node.dispatchEvent(new CustomEvent('shinysdr:reveal', {
      bubbles: true
    }));
    
    // Handle built-in elements
    for (let parent = node; parent; parent = parent.parentNode) {
      switch (parent.nodeName.toLowerCase()) {
        case 'details':
          parent.open = true;
          break;
        case 'dialog':
          // TODO: show/showModal choice -- this might not be a good idea?
          parent.show();
          break;
      }
      
      if (!parent.parentNode && parent !== node.ownerDocument) {
        console.warn('domtools.reveal: tried to reveal an un-rooted node', node);
        return false;
      }
    }

    if (!isVisibleInLayout(node)) {
      console.warn('domtools.reveal: apparently failed to reveal', node);
      return false;
    }
    return true;
  }
  exports.reveal = reveal;
  
  function pixelsFromWheelEvent(event) {
    // deltaMode: 0 = pixels, 1 = "lines", 2 = "pages"; we have no notion of "pages" so treat it as "lines".
    const scaling = event.deltaMode ? 30 : 1;
    return [
      event.deltaX * scaling,
      event.deltaY * scaling,
    ];
  }
  exports.pixelsFromWheelEvent = pixelsFromWheelEvent;
  
  return Object.freeze(exports);
});
