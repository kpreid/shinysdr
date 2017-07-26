// Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

// Manages hideable tiling regions (panes) of the ShinySDR UI.

'use strict';

define([
  './domtools',
  './events',
  './types',
  './values',
  './widget',
], (
  import_domtools,
  import_events,
  import_types,
  import_values,
  import_widget
) => {
  const {
    lifecycleDestroy,
    lifecycleInit,
    reveal,
  } = import_domtools;
  const {
    AddKeepDrop,
    Neverfier,
    Notifier,
  } = import_events;
  const {
    blockT,
    numberT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    StorageNamespace,
  } = import_values;
  const {
    createWidgetExt,
  } = import_widget;
  
  const exports = {};
  
  const DEFAULT_TITLE_CELL = new ConstantCell('');
  
  // We assume that panes are the top-level organization of the page. h2 is the appropriate element for that level.
  const TITLE_BAR_ELEMENT_NAME = 'H2';
  
  const WINDOW_LIST_ID = 'shinysdr-subwindow-list';
  
  // Not used in a very standard widget fashion, but using the widget machinery gets us lots of useful things, like a context for widgets within with all the supporting bits (scheduler, storage, ID prefix...)
  class PaneWidget {
    constructor(config) {
      const paneImpl = config.target.get();
      const frameElement = this.element = config.element;
      const titleCell = paneImpl.titleCell;
      
      config.overrideChildTarget(paneImpl.childTarget);
      
      paneImpl.attachWidget(config, frameElement);
      
      frameElement.classList.add('pane-frame');
      
      const titleBarElement = (() => {
        const existing = frameElement.querySelector(TITLE_BAR_ELEMENT_NAME);
        if (existing) {
          return existing;
        } else {
          const newTitleEl = frameElement.insertBefore(document.createElement(TITLE_BAR_ELEMENT_NAME), frameElement.firstChild);
          const paneTitleNode = newTitleEl.appendChild(document.createTextNode(''));
          function updateTitleInPane() {
            paneTitleNode.data = titleCell.depend(updateTitleInPane);
          }
          updateTitleInPane.scheduler = config.scheduler;
          updateTitleInPane();
          return newTitleEl;
        }
      })();
      
      paneImpl.containerForMenuButton = titleBarElement;
      
      // Title bar controls
      const titleBarControls = titleBarElement.insertBefore(document.createElement('span'), titleBarElement.firstChild);
      titleBarControls.classList.add('widget-PaneImpl-controls');
      if (false) {  // TODO: Not having this until we have a full hide-versus-close story.
        const hideButton = titleBarControls.appendChild(document.createElement('button'));
        hideButton.textContent = '\u2573';  // TODO use icon so we can have a consistent style
        hideButton.classList.add('pane-hide-button');
        hideButton.addEventListener('click', event => {
          paneImpl.setVisible(false);
        }, false);
      }
      
      // Content element
      const contentElement = frameElement.appendChild(document.createElement('div'));
      paneImpl.contentElement = contentElement;  // TODO assert this happens only once
      
      // Misc glue events
      frameElement.addEventListener('shinysdr:reveal', () => {
        paneImpl.setVisible(true);
      }, false);
    }
  }
  
  class PaneImpl {
    constructor(paneManager, bootstrapFrameElement, titleCell) {
      this.paneManager = paneManager;
      this.titleCell = titleCell;
      this.childTarget = paneManager._defaultWidgetTarget;
      this.stateStorage = null;
      this.frameElement = null;
      const lastInteractionTimeCell = new LocalCell(numberT, Date.now());
      bindPropertyToCell(this, 'lastInteractionTime', lastInteractionTimeCell);
      
      const widgetHandle = createWidgetExt(paneManager._context, PaneWidget, bootstrapFrameElement, new ConstantCell(this, blockT));
      
      if (!this.contentElement) {
        // This property, among others, is assigned by the widget
        throw new Error('didn\'t glue up properly');
      }
      
      this.handle = new PaneHandle(this);
      
      Object.freeze(this);
      paneManager._add(this);
      
      const interacted = this.interacted.bind(this);
      this.frameElement.addEventListener('mouseup', interacted, true);
      this.frameElement.addEventListener('touchstart', interacted, true);
      this.frameElement.addEventListener('keyup', interacted, true);
    }
    
    attachWidget(config, frameElement) {
      this.frameElement = frameElement;
      
      // Restore visibility state from storage, or use attribute as default.
      let initialStateString = null;
      if (config.storage) {
        this.stateStorage = config.storage;
        initialStateString = this.stateStorage.getItem('detailsOpen');
      }
      if (initialStateString === null && frameElement.hasAttribute('visible')) {
        initialStateString = frameElement.getAttribute('visible');
      }
      if (initialStateString !== null) {
        try {
          this.setVisible(JSON.parse(initialStateString));
        } catch (e) {
          if (e instanceof SyntaxError) {
            console.warn('Bad pane initial visibility value:', e);
          } else {
            throw e;
          }
        }
      }
    }
    
    setVisible(value) {
      value = !!value;
      if (value) {
        this.frameElement.style.removeProperty('display');
        this.interacted();
      } else {
        this.frameElement.style.display = 'none';
      }
      
      if (this.stateStorage) {
        this.stateStorage.setItem('detailsOpen', JSON.stringify(value));
      }
      
      this.paneManager._scheduleGlobalCheckAndResize();
    }
    
    getVisible() {
      return this.frameElement.style.display !== 'none';
    }
    
    delete() {
      if (this.frameElement.parentNode) {
        this.frameElement.parentNode.removeChild(this.frameElement);
      }
      lifecycleDestroy(this.frameElement);
      this.paneManager._delete(this);
    }
    
    usefulToCloseForWidth() {
      // TODO: Use something other than the class name, because this module is supposed to be largely independent of other app HTML usage
      return this.getVisible() && !this.frameElement.classList.contains('stretchy');
    }
    
    interacted() {
      this.lastInteractionTime = Date.now();
    }
  }
  
  const paneImpls = new WeakMap();
  class PaneHandle {
    constructor(paneImpl) {
      paneImpls.set(this, paneImpl);
      this.contentElement = paneImpl.contentElement;
    }
    
    hide() {
      paneImpls.get(this).setVisible(false);
    }
    
    show() {
      paneImpls.get(this).setVisible(true);
    }
    
    delete() {
      paneImpls.get(this).delete();
    }
  }
  
  class PaneManager {
    constructor(context, container, defaultWidgetTarget) {
      // TODO: weakmap / impl pattern
      this._context = context;
      this._container = container;
      this._defaultWidgetTarget = defaultWidgetTarget;
      this._paneImpls = new Set();
      this._paneListNotifier = new Notifier();
      this._globalCheckAndResize = context.scheduler.claim(this._globalCheckAndResize.bind(this));
      
      this._reshapeNotice = new Neverfier();  // so we can be a target for PaneListWidget
      
      this._addExisting(container);
      
      window.addEventListener('resize', event => {
        this._closeExtraWide();
      });
      
      const initialListEl = container.querySelector('#' + WINDOW_LIST_ID);
      if (initialListEl) {
        createWidgetExt(context, PaneListWidget, initialListEl, new ConstantCell(this, blockT));
        const widgetizedListEl = container.querySelector('#' + WINDOW_LIST_ID);  // TODO kludge
        
        // Find which pane contains the list
        let listPaneImpl = null;
        for (var paneImpl of this._paneImpls) {
          if (paneImpl.frameElement.contains(widgetizedListEl)) {
            listPaneImpl = paneImpl;
            break;
          }
        }
        this._listPaneImpl = listPaneImpl;
        
        if (listPaneImpl) {
          // Show-this-pane button to be displayed elsewhere.
          const showButton = document.createElement('button');
          showButton.classList.add('subwindow-menu-button');
          const showButtonIcon = showButton.appendChild(document.createElement('img'));
          showButtonIcon.src = '/client/menu.svg';
          showButtonIcon.alt = '\u2261';
          this._listShowButton = showButton;
          setupPaneToggleButton(showButton, listPaneImpl);
        } else {
          console.info('#' + WINDOW_LIST_ID + ' not inside a pane.');
        }
      } else {
        console.warn('#' + WINDOW_LIST_ID + ' not present in document.');
      }
      
      this._globalCheckAndResize();
    }
    
    newPane({
      titleCell = DEFAULT_TITLE_CELL,
    } = {}) {
      const container = this._container;
      const frameElement = container.appendChild(document.createElement('section'));
      return new PaneImpl(this, frameElement, titleCell).handle;
    }
    
    _addExisting(container) {
      container.querySelectorAll('shinysdr-subwindow').forEach(element => {
        const titleBarElement = element.querySelector(TITLE_BAR_ELEMENT_NAME);
        const title = titleBarElement ? titleBarElement.textContent : '';
        const titleCell = new ConstantCell(title);
        
        new PaneImpl(this, element, titleCell);
      });
    }
    
    _add(paneImpl) {
      // TODO: This would be a good use case for partial updates rather than "something changed" notifications
      this._paneImpls.add(paneImpl);
      this._paneListNotifier.notify();
    }
    
    _delete(paneImpl) {
      this._paneImpls.delete(paneImpl);
      this._paneListNotifier.notify();
    }
    
    // Called when a pane changes visibility state to ensure we don't have none visible and fire relevant resize events.
    _scheduleGlobalCheckAndResize() {
      this._globalCheckAndResize.scheduler.enqueue(this._globalCheckAndResize);
    }
    
    _globalCheckAndResize() {
      if (this._closeExtraWide()) {
        return;
      }
      
      // Ensure that at least the pane list is visible.
      let visibleCount = 0;
      for (var paneImpl of this._paneImpls) {
        if (paneImpl.getVisible()) {
          visibleCount++;
        }
      }
      if (!visibleCount) {
        // TODO handle window list better
        reveal(this._container.querySelector('#' + WINDOW_LIST_ID));
        // This will cause another _globalCheckAndResize if it works right, but at least we're consistent even in failure cases.
      }
      
      // Place the list's toggle button
      if (this._listShowButton) {
        let bestPlace = null;
        for (var paneImpl of this._paneImpls) {
          const place = paneImpl.containerForMenuButton;
          if (paneImpl.getVisible() && (!bestPlace || elementOrderSort(place, bestPlace) > 0)) {
            bestPlace = place;
            continue;
          }
        }
        if (bestPlace) {
          bestPlace.insertBefore(this._listShowButton, bestPlace.firstChild);
        }
        this._listShowButton.disabled = visibleCount <= 1 &&
            (!this._listPaneImpl || this._listPaneImpl.getVisible());
      }
      
      // Fire resize event so pane contents can resize. TODO: Use new feature Resize Observers instead of everyone using the global resize.
      const resize = document.createEvent('Event');
      resize.initEvent('resize', false, false);
      window.dispatchEvent(resize);
    }
    
    // returns true if it triggered an update
    _closeExtraWide() {
      if (document.body.scrollWidth > document.body.offsetWidth) {
        var bestToClose = null;
        var bestTime = Date.now();
        for (var paneImpl of this._paneImpls) {
          if (paneImpl.usefulToCloseForWidth() && paneImpl.lastInteractionTime < bestTime) {
            bestToClose = paneImpl;
            bestTime = paneImpl.lastInteractionTime;
          }
        }
        if (bestToClose) {
          console.log('Closing', bestToClose, 'for width');
          bestToClose.setVisible(false);
          return true;
        }
      }
      return false;
    }
  }
  exports.PaneManager = PaneManager;
  
  class PaneListWidget {
    constructor(config) {
      const paneManager = config.target.depend(config.rebuildMe);
      const scheduler = config.scheduler;
      const list = this.element = config.element;
      
      const updateListAKD = new AddKeepDrop({
        add(paneImpl) {
          if (paneImpl.frameElement.contains(list)) {
            // Don't include a button for hiding ourselves.
            return null;
          }
          
          const listItem = list.appendChild(document.createElement('li'));
          const listButton = listItem.appendChild(document.createElement('button'));
          const listTitleNode = listButton.appendChild(document.createTextNode(''));
          
          setupPaneToggleButton(listButton, paneImpl);
        
          function updateTitle() {
            listTitleNode.data = String(paneImpl.titleCell.depend(updateTitle));
          }
          updateTitle.scheduler = config.scheduler;  // TODO: sub-scheduler or break update loop
          updateTitle();
        
          listItem.classList.add('subwindow-show-button');
          listItem.classList[paneImpl.getVisible() ? 'add' : 'remove']('subwindow-show-button-shown');
        
          return listItem;
        },
        remove(paneImpl, listItem) {
          if (!listItem) return;
          listItem.parentNode.removeChild(listItem);
        }
      });
      
      function check() {
        paneManager._paneListNotifier.listen(check);
        updateListAKD.begin();
        for (var paneImpl of paneManager._paneImpls) {
          updateListAKD.add(paneImpl);
        }
        updateListAKD.end();
      }
      check.scheduler = config.scheduler;
      check();
    }
  }
  exports.PaneListWidget = PaneListWidget;
  
  function setupPaneToggleButton(button, paneImpl) {
    button.addEventListener('click', () => {
      paneImpl.setVisible(!paneImpl.getVisible());
    }, false);
  }
  
  // Comparison function for sorting elements when neither contains the other.
  function elementOrderSort(a, b) {
    const comparison = a.compareDocumentPosition(b);
    return comparison & Node.DOCUMENT_POSITION_PRECEDING ? -1 :
           comparison & Node.DOCUMENT_POSITION_FOLLOWING ? 1 :
           0;  // shouldn't happen, bad answer
  }
  
  function bindPropertyToCell(object, prop, cell) {
    Object.defineProperty(object, prop, {
      configurable: true,
      enumerable: true,
      get: cell.get.bind(cell),
      set: cell.set.bind(cell),
    });
  }
  
  return Object.freeze(exports);
});
