// Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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

define([
  './coordination', 
  './domtools', 
  './events', 
  './types', 
  './values',
], (
  import_coordination,
  import_domtools,
  import_events,
  import_types,
  import_values
) => {
  const {
    Coordinator,
  } = import_coordination;
  const {
    lifecycleDestroy,
    lifecycleInit,
  } = import_domtools;
  const {
    SubScheduler,
  } = import_events;
  const {
    anyT,
  } = import_types;
  const {
    Cell,
    ConstantCell,
    DerivedCell,
    StorageNamespace,
  } = import_values;
  
  const exports = {};
  
  const elementHasWidgetRole = new WeakMap();
  
  function assertNotAlreadySomeWidgetRole(node) {
    if (elementHasWidgetRole.has(node)) {
      // console can allow inspecting the object
      console.error('node already a widget ' + elementHasWidgetRole.get(node), node);
      throw new Error('node already a widget ' + elementHasWidgetRole.get(node) + ': ' + node);
    }
    let widgetChildren = node.querySelectorAll('.live-widget');
    if (widgetChildren.length) {
      // console can allow inspecting the object
      console.error('node already contains widget(s)', widgetChildren);
      throw new Error('node already contains widget(s) ' + widgetChildren);
    }
  }
  
  function alwaysCreateReceiverFromEvent(event) {
    return event.shiftKey;
  }
  exports.alwaysCreateReceiverFromEvent = alwaysCreateReceiverFromEvent;
  
  // TODO figure out what this does and give it a better name
  class Context {
    constructor(config) {
      this.widgets = config.widgets || Object.freeze({});
      this.clientState = config.clientState || null;  // TODO: make mandatory or stub
      this.scheduler = config.scheduler || (() => {
        throw new Error('Context: Missing scheduler argument');
      })();
      this.radioCell = config.radioCell || null;
      this.index = config.index || null;  // TODO: create stub empty index
      this.freqDB = config.freqDB || null;
      this.writableDB = config.writableDB || null;
      this.layoutContext = config.layoutContext || null;
      this.coordinator = config.coordinator || new Coordinator(this.scheduler, this.freqDB, this.radioCell);
      this.actionCompleted = config.actionCompleted || Object.freeze(function actionCompletedNoop() {});
      Object.freeze(this);
    }
    
    withLayoutContext(layoutContext) {
      if (typeof layoutContext !== 'object') {
        throw new TypeError('bad layoutContext');
      }
      return new Context({
        widgets: this.widgets,
        radioCell: this.radioCell,
        index: this.index,
        clientState: this.clientState,
        freqDB: this.freqDB,
        writableDB: this.writableDB,
        scheduler: this.scheduler,
        layoutContext: layoutContext,
        coordinator: this.coordinator,
        actionCompleted: this.actionCompleted
      });
    }
    
    forMenu(closeCallback) {
      return new Context({
        widgets: this.widgets,
        radioCell: this.radioCell,
        index: this.index,
        clientState: this.clientState,
        freqDB: this.freqDB,
        writableDB: this.writableDB,
        scheduler: this.scheduler,
        layoutContext: null,  // menu is also a new default layout context
        coordinator: this.coordinator,
        actionCompleted: function actionCompletedWrapper() {  // wrapper to suppress this
          closeCallback();
        }
      });
    }
  }
  exports.Context = Context;
  
  function createWidgetsInNode(rootTargetCell, context, node) {
    Array.prototype.forEach.call(node.childNodes, function (child) {
      createWidgets(rootTargetCell, context, child);
    });
  }
  
  // Replace the given template/input node with a widget node.
  function createWidget(targetCellCell, targetStr, context, node, widgetCtor) {
    assertNotAlreadySomeWidgetRole(node);
    
    const templateStash = node;
    elementHasWidgetRole.set(node, 'template');
    
    const container = node.parentNode;
    if (!container) {
      throw new Error('createWidget: The supplied node ' + node.nodeName + ' did not have a parent node.');
    }

    let currentWidgetEl = node;
    const shouldBePanel = container.classList.contains('frame') || container.nodeName === 'DETAILS';  // TODO: less DWIM, more precise
    
    const id = node.id;
    const idPrefix = id === '' ? null : node.id + '.';
    
    context.scheduler.startNow(function go() {
      // TODO: Unbreakable notify loop on targetCellCell. We could stop it on explicit destroy, but explicit destroy doesn't happen very much!
      const targetCell = targetCellCell.depend(go);
      if (!targetCell) {
        if (node.parentNode) { // TODO: This condition shouldn't be necessary?
          node.parentNode.replaceChild(document.createTextNode('[Missing: ' + targetStr + ']'), node);
        }
        return;
      }
      
      let childTargetCell = targetCell;
      
      lifecycleDestroy(currentWidgetEl);

      const newSourceEl = templateStash.cloneNode(true);
      elementHasWidgetRole.set(newSourceEl, 'instance');
      container.replaceChild(newSourceEl, currentWidgetEl);
      
      // TODO: Better interface to the metadata
      if (!newSourceEl.hasAttribute('title') && targetCell.metadata.naming.label !== null) {
        newSourceEl.setAttribute('title', targetCell.metadata.naming.label);
      }
      
      let disableScheduler;
      const config = Object.freeze({
        scheduler: new SubScheduler(context.scheduler, disable => {
          disableScheduler = disable;
        }),
        target: targetCell,
        element: newSourceEl,
        context: context, // TODO redundant values -- added for programmatic widget-creation; maybe facetize createWidget. Also should remove text-named widget table from this to make it more tightly scoped, perhaps.
        getLayoutContext(contextType) {
          if (context.layoutContext instanceof contextType) {
            return context.layoutContext;
          } else if (context.layoutContext === null) {
            throw new Error('missing expected layout context');
          } else {
            throw new Error('wrong layout context type');
          }
        },
        clientState: context.clientState,
        freqDB: context.freqDB, // TODO: remove the need for this
        writableDB: context.writableDB, // TODO: remove the need for this
        radioCell: context.radioCell, // TODO: remove the need for this
        index: context.index, // TODO: remove the need for this
        actions: context.coordinator.actions,
        storage: idPrefix ? new StorageNamespace(localStorage, 'shinysdr.widgetState.' + idPrefix) : null,
        shouldBePanel: shouldBePanel,
        rebuildMe: go,
        idPrefix: idPrefix,
        overrideChildTarget: tc => {
          if (!(tc instanceof Cell)) {
            throw new TypeError('overrideChildTarget: ' + childTargetCell + ' is not a cell');
          }
          childTargetCell = tc;
        }  // TODO: kludge for PaneManager; replace with something better
      });
      let widget, widgetChosenElement;
      try {
        widget = new widgetCtor(config);
        widgetChosenElement = widget.element;
        
        if (!(widgetChosenElement instanceof Element)) {
          throw new TypeError('Widget ' + widget.constructor.name + ' did not provide an element but ' + widgetChosenElement);
        }
      } catch (error) {
        console.error('Error creating widget: ', error);
        console.log(error.stack);
        // TODO: Arrange so that if widgetCtor is widgets_basic.PickWidget it can give the more-specific name.
        widget = new ErrorWidget(config, widgetCtor, error);
        widgetChosenElement = widget.element;
      }
      
      // 'live-widget' class is used for detecting bad nesting and also may be useful in debugging, but currently is not, and probably should not be used for styling.
      widgetChosenElement.classList.add('live-widget');
      // Specific class used for attaching styling to widgets.
      widgetChosenElement.classList.add('widget-' + widget.constructor.name);  // TODO use stronger namespacing
      
      const placeMark = newSourceEl.nextSibling;
      if (newSourceEl.hasAttribute('title') && newSourceEl.getAttribute('title') === templateStash.getAttribute('title')) {
        console.warn('Widget ' + widget.constructor.name + ' did not handle title attribute');
      }
      
      if (newSourceEl.parentNode === container) {
        container.replaceChild(widgetChosenElement, newSourceEl);
      } else {
        container.insertBefore(widgetChosenElement, placeMark);
      }
      currentWidgetEl = widgetChosenElement;
      
      doPersistentDetails(currentWidgetEl);
      
      // allow widgets to embed widgets
      createWidgetsInNode(childTargetCell, context, widgetChosenElement);
      
      widgetChosenElement.addEventListener('shinysdr:lifecycledestroy', event => {
        widgetChosenElement.classList.remove('live-widget');
        disableScheduler();
      }, false);
      
      // signal now that we've inserted
      // TODO: Make this less DWIM
      lifecycleInit(widgetChosenElement);
      setTimeout(function() {
        lifecycleInit(widgetChosenElement);
      }, 0);
    });
    
    return Object.freeze({
      destroy: function() {
        lifecycleDestroy(currentWidgetEl);
        container.replaceChild(templateStash, currentWidgetEl);
      }
    });
  }
  
  function createWidgetExt(context, widgetCtor, node, targetCell) {
    // catch a likely early error
    if (!context) {
      throw new Error('createWidgetExt: missing context');
    }
    if (!widgetCtor) {
      throw new Error('createWidgetExt: missing widgetCtor');
    }
    if (!node) {
      throw new Error('createWidgetExt: missing node');
    }
    if (!targetCell) {
      throw new Error('createWidgetExt: missing targetCell');
    }
    return createWidget(
      new ConstantCell(targetCell, anyT),
      String(targetCell),
      context,
      node,
      widgetCtor);
  }
  exports.createWidgetExt = createWidgetExt;
  
  // return a cell containing the cell from rootCell's block according to str
  // e.g. if str is foo.bar then the returned cell's value is
  //   rootCell.get().foo.get().bar
  function evalTargetStr(rootCell, str, scheduler) {
    var steps = str.split(/\./);
    return new DerivedCell(anyT, scheduler, function (dirty) {
      var cell = rootCell;
      steps.forEach(function (name) {
        if (cell !== undefined) cell = cell.depend(dirty)[name];
      });
      return cell;
    });
  }
  
  function createWidgets(rootTargetCell, context, node) {
    var scheduler = context.scheduler;
    if (elementHasWidgetRole.get(node)) {
      // Don't walk into existing structure managed by widgets.
      return;
    }
    if (node.hasAttribute && node.hasAttribute('data-widget')) {
      var targetCellCell, targetStr;
      if (node.hasAttribute('data-target')) {
        targetStr = node.getAttribute('data-target');
        targetCellCell = evalTargetStr(rootTargetCell, targetStr, scheduler);
      } else {
        targetStr = "<can't happen>";
        targetCellCell = new ConstantCell(rootTargetCell, anyT);
      }
      
      var typename = node.getAttribute('data-widget');
      node.removeAttribute('data-widget');  // prevent widgetifying twice
      if (typename === null) {
        console.error('Unspecified widget type:', node);
        return;
      }
      var widgetCtor = context.widgets[typename];
      if (!widgetCtor) {
        console.error('Bad widget type:', node);
        return;
      }
      // TODO: use a placeholder widget (like Squeak Morphic does) instead of having a different code path for the above errors
      
      createWidget(targetCellCell, targetStr, context, node, widgetCtor);
      
    } else if (node.hasAttribute && node.hasAttribute('data-target')) (function () {
      // TODO: this is an oddball a bit like a widget itself (e.g. it uses cloneNode similarly), maybe turn it into a widget
      
      assertNotAlreadySomeWidgetRole(node);
      elementHasWidgetRole.set(node, 'targeted container');
      
      doPersistentDetails(node);
      
      var html = document.createDocumentFragment();
      while (node.firstChild) {
        assertNotAlreadySomeWidgetRole(node.firstChild);
        elementHasWidgetRole.set(node, 'targeted container child');
        html.appendChild(node.firstChild);
      }
      scheduler.startNow(function go() {
        // TODO defend against JS-significant keys
        var target = evalTargetStr(rootTargetCell, node.getAttribute('data-target'), scheduler).depend(go);
        if (!target) {
          node.textContent = '[Missing: ' + node.getAttribute('data-target') + ']';
          return;
        }
        
        node.textContent = ''; // fast clear
        node.appendChild(html.cloneNode(true));
        createWidgetsInNode(target, context, node);
      });

    }()); else {
      doPersistentDetails(node);
      createWidgetsInNode(rootTargetCell, context, node);
    }
  }
  exports.createWidgets = createWidgets;
  
  // Bind a <details> element's open state to localStorage, if this is one
  function doPersistentDetails(node) {
    if (node.nodeName === 'DETAILS' && node.hasAttribute('id')) {
      var ns = new StorageNamespace(localStorage, 'shinysdr.elementState.' + node.id + '.');
      var stored = ns.getItem('detailsOpen');
      if (stored !== null) node.open = JSON.parse(stored);
      new MutationObserver(function(mutations) {
        ns.setItem('detailsOpen', JSON.stringify(node.open));
      }).observe(node, {attributes: true, attributeFilter: ['open']});
    }
  }
  
  function ErrorWidget(config, widgetCtor, error) {
    this.element = document.createElement('div');
    let widgetCtorName = widgetCtor ? widgetCtor.name : '<unknown widget type>';
    this.element.appendChild(document.createTextNode('An error occurred preparing what should occupy this space (' + widgetCtorName + ' named ' + config.element.getAttribute('title') + '). '));
    this.element.appendChild(document.createElement('code')).textContent = String(error);
  }
  
  return Object.freeze(exports);
});
