// Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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
  './math', 
  './types', 
  './values',
], (
  import_coordination,
  import_domtools,
  import_events,
  import_math,
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
    Notifier,
    SubScheduler,
  } = import_events;
  const {
    mod,
  } = import_math;
  const {
    anyT,
    RangeT,
  } = import_types;
  const {
    ConstantCell,
    DerivedCell,
    StorageCell,
    StorageNamespace,
    makeBlock,
  } = import_values;
  
  const exports = {};
  
  const elementHasWidgetRole = new WeakMap();
  
  function alwaysCreateReceiverFromEvent(event) {
    return event.shiftKey;
  }
  exports.alwaysCreateReceiverFromEvent = alwaysCreateReceiverFromEvent;
  
  // TODO figure out what this does and give it a better name
  function Context(config) {
    this.widgets = config.widgets;
    this.radioCell = config.radioCell;
    this.index = config.index;
    this.clientState = config.clientState;
    this.scheduler = config.scheduler;
    this.freqDB = config.freqDB;
    this.writableDB = config.writableDB;
    this.spectrumView = config.spectrumView;
    // TODO reconsider this unusual handling. Required to avoid miscellaneous things needing to define a coordinator.
    this.coordinator = config.coordinator || new Coordinator(this.scheduler, this.freqDB, this.radioCell);
    this.actionCompleted = config.actionCompleted || function actionCompletedNoop() {};
    Object.freeze(this);
  }
  Context.prototype.withSpectrumView = function (outerElement, innerElement, monitor, isRFSpectrum) {
    var id = outerElement.id || innerElement.id;
    if (!id) throw new Error('spectrum view element must have an id for persistence');
    var ns = new StorageNamespace(localStorage, 'shinysdr.viewState.' + id + '.');
    var view = new SpectrumView({
      scheduler: this.scheduler,
      radioCell: this.radioCell,
      outerElement: outerElement,
      innerElement: innerElement,
      storage: ns,
      isRFSpectrum: isRFSpectrum,
      signalTypeCell: monitor.signal_type,
      actions: this.coordinator.actions
    });
    return new Context({
      widgets: this.widgets,
      radioCell: this.radioCell,
      index: this.index,
      clientState: this.clientState,
      freqDB: this.freqDB,
      writableDB: this.writableDB,
      scheduler: this.scheduler,
      spectrumView: view,
      coordinator: this.coordinator,
      actionCompleted: this.actionCompleted
    });
  };
  Context.prototype.forMenu = function (closeCallback) {
    return new Context({
      widgets: this.widgets,
      radioCell: this.radioCell,
      index: this.index,
      clientState: this.clientState,
      freqDB: this.freqDB,
      writableDB: this.writableDB,
      scheduler: this.scheduler,
      spectrumView: null,
      coordinator: this.coordinator,
      actionCompleted: function actionCompletedWrapper() {  // wrapper to suppress this
        closeCallback();
      }
    });
  };
  exports.Context = Context;
  
  function createWidgetsInNode(rootTargetCell, context, node) {
    Array.prototype.forEach.call(node.childNodes, function (child) {
      createWidgets(rootTargetCell, context, child);
    });
  }
  
  // Replace the given template/input node with a widget node.
  function createWidget(targetCellCell, targetStr, context, node, widgetCtor) {
    if (elementHasWidgetRole.has(node)) {
      throw new Error('node already a widget ' + elementHasWidgetRole.get(node));
    }
    
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
        view: context.spectrumView,
        clientState: context.clientState,
        freqDB: context.freqDB, // TODO: remove the need for this
        writableDB: context.writableDB, // TODO: remove the need for this
        radioCell: context.radioCell, // TODO: remove the need for this
        index: context.index, // TODO: remove the need for this
        actions: context.coordinator.actions,
        storage: idPrefix ? new StorageNamespace(localStorage, 'shinysdr.widgetState.' + idPrefix) : null,
        shouldBePanel: shouldBePanel,
        rebuildMe: go,
        idPrefix: idPrefix
      });
      let widget;
      try {
        widget = new widgetCtor(config);
        
        if (!(widget.element instanceof Element)) {
          throw new TypeError('Widget ' + widget.constructor.name + ' did not provide an element but ' + widget.element);
        }
      } catch (error) {
        console.error('Error creating widget: ', error);
        console.log(error.stack);
        // TODO: Arrange so that if widgetCtor is widgets_basic.PickWidget it can give the more-specific name.
        widget = new ErrorWidget(config, widgetCtor, error);
      }
      
      widget.element.classList.add('widget-' + widget.constructor.name);  // TODO use stronger namespacing
      
      const newEl = widget.element;
      const placeMark = newSourceEl.nextSibling;
      if (newSourceEl.hasAttribute('title') && newSourceEl.getAttribute('title') === templateStash.getAttribute('title')) {
        console.warn('Widget ' + widget.constructor.name + ' did not handle title attribute');
      }
      
      if (newSourceEl.parentNode === container) {
        container.replaceChild(newEl, newSourceEl);
      } else {
        container.insertBefore(newEl, placeMark);
      }
      currentWidgetEl = newEl;
      
      doPersistentDetails(currentWidgetEl);
      
      // allow widgets to embed widgets
      createWidgetsInNode(targetCell, context, widget.element);
      
      newEl.addEventListener('shinysdr:lifecycledestroy', event => {
        disableScheduler();
      }, false);
      
      // signal now that we've inserted
      // TODO: Make this less DWIM
      lifecycleInit(newEl);
      setTimeout(function() {
        lifecycleInit(newEl);
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
    if (!targetCell) {
      // catch a likely early error
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
      doPersistentDetails(node);
      
      var html = document.createDocumentFragment();
      while (node.firstChild) html.appendChild(node.firstChild);
      scheduler.start(function go() {
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
  
  // Defines the display parameters and coordinate calculations of the spectrum widgets
  // TODO: Revisit whether this should be in widgets.js -- it is closely tied to the spectrum widgets, but also managed by the widget framework.
  var MAX_ZOOM_BINS = 60; // Maximum zoom shows this many FFT bins
  function SpectrumView(config) {
    var radioCell = config.isRFSpectrum ? config.radioCell : null;
    var container = config.outerElement;
    var innerElement = config.innerElement;
    var scheduler = config.scheduler;
    var storage = config.storage;
    var isRFSpectrum = config.isRFSpectrum;
    var signalTypeCell = config.signalTypeCell;
    var tune = config.actions.tune;
    var self = this;

    var n = this.n = new Notifier();
    
    // per-drawing-frame parameters
    var nyquist, centerFreq, leftFreq, rightFreq, pixelWidth, pixelsPerHertz, analytic;
    
    // Zoom state variables
    // We want the cursor point to stay fixed, but scrollLeft quantizes to integer; fractionalScroll stores a virtual fractional part.
    var zoom = 1;
    var fractionalScroll = 0;
    var cacheScrollLeft = 0;
    
    // Restore persistent zoom state
    container.addEventListener('shinysdr:lifecycleinit', event => {
      // TODO: clamp zoom here in the same way changeZoom does
      zoom = parseFloat(storage.getItem('zoom')) || 1;
      var initScroll = parseFloat(storage.getItem('scroll')) || 0;
      innerElement.style.width = (container.offsetWidth * zoom) + 'px';
      prepare();
      scheduler.startLater(function later() {
        // Delay kludge because the container is potentially zero width at initialization time and therefore cannot actually be scrolled.
        container.scrollLeft = Math.floor(initScroll);
        fractionalScroll = mod(initScroll, 1);
        prepare();
      });
    });
    
    function prepare() {
      // TODO: unbreakable notify loop here; need to be lazy
      var sourceType = signalTypeCell.depend(prepare);
      if (isRFSpectrum) {
        // Note that this uses source.freq, not the spectrum data center freq. This is correct because we want to align the coords with what we have selected, not the current data; and the WaterfallPlot is aware of this distinction.
        centerFreq = radioCell.depend(prepare).source.depend(prepare).freq.depend(prepare);
      } else {
        centerFreq = 0;
      }
      nyquist = sourceType.sample_rate / 2;
      analytic = sourceType.kind === 'IQ';  // TODO have glue code
      leftFreq = analytic ? centerFreq - nyquist : centerFreq;
      rightFreq = centerFreq + nyquist;
      pixelsPerHertz = pixelWidth / (rightFreq - leftFreq) * zoom;
      
      if (!isFinite(fractionalScroll)) {
        console.error("Shouldn't happen: SpectrumView fractionalScroll =", fractionalScroll);
        fractionalScroll = 0;
      }
      
      // Adjust scroll to match possible viewport size change.
      // (But if we are hidden or zero size, then the new scroll position would be garbage, so keep the old state.)
      if (container.offsetWidth > 0 && pixelWidth !== container.offsetWidth) {
        // Compute change (with case for first time initialization)
        var scaleChange = isFinite(pixelWidth) ? container.offsetWidth / pixelWidth : 1;
        var scrollValue = (cacheScrollLeft + fractionalScroll) * scaleChange;
        
        pixelWidth = container.offsetWidth;
        
        // Update scrollable range
        var w = pixelWidth * zoom;
        innerElement.style.width = w + 'px';
        
        // Apply change
        container.scrollLeft = scrollValue;
        fractionalScroll = scrollValue - container.scrollLeft;
      }
      
      // accessing scrollLeft triggers relayout, so cache it
      cacheScrollLeft = container.scrollLeft;
      n.notify();
    }
    scheduler.claim(prepare);
    prepare();
    
    window.addEventListener('resize', function (event) {
      // immediate to ensure smooth animation and to allow scroll adjustment
      scheduler.callNow(prepare);
    }.bind(this));
    
    container.addEventListener('scroll', scheduler.syncEventCallback(function (event) {
      storage.setItem('scroll', String(container.scrollLeft + fractionalScroll));
      // immediate to ensure smooth animation and interaction
      scheduler.callNow(prepare);
    }), false);
    
    // exported for the sake of createWidgets -- TODO proper factoring?
    this.scheduler = scheduler;
    
    this.isRFSpectrum = function () {
      return isRFSpectrum;
    };
    this.isRealFFT = function isRealFFT(freq) {
      // When posible, prefer the coordinate-conversion functions to this one. But sometimes this is much more direct.
      return !analytic;
    };
    this.freqToCSSLeft = function freqToCSSLeft(freq) {
      return ((freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSRight = function freqToCSSRight(freq) {
      return (pixelWidth - (freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSLength = function freqToCSSLength(freq) {
      return (freq * pixelsPerHertz) + 'px';
    };
    this.leftFreq = function getLeftFreq() {
      return leftFreq;
    };
    this.rightFreq = function getRightFreq() {
      return rightFreq;
    };
    this.leftVisibleFreq = function leftVisibleFreq() {
      return leftFreq + cacheScrollLeft / pixelsPerHertz;
    };
    this.rightVisibleFreq = function rightVisibleFreq() {
      return leftFreq + (cacheScrollLeft + pixelWidth) / pixelsPerHertz;
    };
    this.getCenterFreq = function getCenterFreq() {
      return centerFreq;
    };
    this.getVisiblePixelWidth = function getVisiblePixelWidth() {
      return pixelWidth;
    };
    this.getTotalPixelWidth = function getTotalPixelWidth() {
      return pixelWidth * zoom;
    };
    this.getVisiblePixelHeight = function getVisiblePixelHeight() {
      // TODO: This being vertical rather than horizontal doesn't fit much with the rest of SpectrumView's job, but it needs to know about innerElement.
      return innerElement.offsetHeight;
    };
    
    function clampZoom(zoomValue) {
      var maxZoom = Math.max(
        1,  // at least min zoom,
        Math.max(
          nyquist / 3e3, // at least 3 kHz
          radioCell
            ? radioCell.get().monitor.get().freq_resolution.get() / MAX_ZOOM_BINS
            : 0));
      return Math.min(maxZoom, Math.max(1.0, zoomValue));
    }
    function clampScroll(scrollValue) {
      return Math.max(0, Math.min(pixelWidth * (zoom - 1), scrollValue));
    }
    function startZoomUpdate() {
      // Force scrollable range to update, for when zoom and scrollLeft change together.
      // The (temporary) range is the max of the old and new ranges.
      var w = pixelWidth * zoom;
      var oldWidth = parseInt(innerElement.style.width);
      innerElement.style.width = Math.max(w, oldWidth) + 'px';
    }
    function finishZoomUpdate(scrollValue) {
      scrollValue = clampScroll(scrollValue);
      
      // Final scroll-range update.
      var w = pixelWidth * zoom;
      innerElement.style.width = w + 'px';
      
      container.scrollLeft = scrollValue;
      fractionalScroll = scrollValue - container.scrollLeft;
      
      storage.setItem('zoom', String(zoom));
      storage.setItem('scroll', String(scrollValue));
      
      // recompute with new scrollLeft/fractionalScroll
      scheduler.callNow(prepare);
    }
    
    this.changeZoom = function changeZoom(delta, cursorX) {
      cursorX += fractionalScroll;
      var cursor01 = cursorX / pixelWidth;
      
      // Find frequency to keep under the cursor
      var cursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Adjust and clamp zoom
      zoom *= Math.exp(-delta * 0.0005);
      zoom = clampZoom(zoom);
      
      // Recompute parameters now so we can adjust pan (scroll)
      scheduler.callNow(prepare);
      
      var unadjustedCursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Force scrollable range to update
      startZoomUpdate();
      // Current virtual scroll
      var scroll = container.scrollLeft + fractionalScroll;
      // Adjust
      scroll = scroll + (cursorFreq - unadjustedCursorFreq) * pixelsPerHertz;
      // Write back
      finishZoomUpdate(scroll);
    };
    
    // TODO: mousewheel event is allegedly nonstandard and inconsistent among browsers, notably not in Firefox (not that we're currently FF-compatible due to the socket issue).
    container.addEventListener('mousewheel', function(event) {
      if (Math.abs(event.wheelDeltaY) > Math.abs(event.wheelDeltaX)) {
        // Vertical scrolling: override to zoom.
        self.changeZoom(-event.wheelDeltaY, event.clientX - container.getBoundingClientRect().left);
        event.preventDefault();
        event.stopPropagation();
      } else {
        // Horizontal scrolling (or diagonal w/ useless vertical component): if hits edge, change frequency.
        if (event.wheelDeltaX > 0 && cacheScrollLeft === 0
            || event.wheelDeltaX < 0 && cacheScrollLeft === (container.scrollWidth - container.clientWidth)) {
          if (isRFSpectrum) {
            var freqCell = radioCell.get().source.get().freq;
            freqCell.set(freqCell.get() + (event.wheelDeltaX * -0.12) / pixelsPerHertz);
          }
          
          // This shouldn't be necessary, but Chrome treats horizontal scroll events from touchpad as a back/forward gesture.
          event.preventDefault();
        }
      }
    }, {capture: true, passive: false});
    
    function clientXToViewportLeft(clientX) {
      return clientX - container.getBoundingClientRect().left;
    }
    function clientXToHardLeft(clientX) {  // left in the content not the viewport
      return clientXToViewportLeft(clientX) + cacheScrollLeft;
    }
    function clientXToFreq(clientX) {
      return clientXToHardLeft(clientX) / pixelsPerHertz + leftFreq;
    }
    
    var activeTouches = Object.create(null);
    var mayTapToTune = false;
    
    container.addEventListener('touchstart', function (event) {
      // Prevent mouse-emulation handling
      event.preventDefault();
      
      // Tap-to-tune requires exactly one touch just starting
      mayTapToTune = Object.keys(activeTouches) === 0 && event.changedTouches.length === 1;
      
      // Record the frequency the user has touched
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        var x = clientXToViewportLeft(touch.clientX);
        activeTouches[touch.identifier] = {
          grabFreq: clientXToFreq(touch.clientX),
          grabView: x,  // fixed
          nowView: x  // updated later
        };
      });
    }, {capture: false, passive: false});
    
    container.addEventListener('touchmove', function (event) {
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        activeTouches[touch.identifier].nowView = clientXToViewportLeft(touch.clientX);
      });
      
      const touchIdentifiers = Object.keys(activeTouches);
      if (touchIdentifiers.length >= 2) {
        // Zoom using two touches
        touchIdentifiers.sort();  // Ensure stable choice (though oldest would be better).
        const id1 = touchIdentifiers[0];
        const id2 = touchIdentifiers[1];
        const f1 = activeTouches[id1].grabFreq;
        const f2 = activeTouches[id2].grabFreq;
        const p1 = activeTouches[id1].nowView;
        const p2 = activeTouches[id2].nowView;
        const newPixelsPerHertz = Math.abs(p2 - p1) / Math.abs(f2 - f1);
        const unzoomedPixelsPerHertz = pixelWidth / (rightFreq - leftFreq);
        zoom = clampZoom(newPixelsPerHertz / unzoomedPixelsPerHertz);
        startZoomUpdate();
      }
      
      // Compute scroll pos, using NEW zoom value
      var scrolls = [];
      for (var idString in activeTouches) {
        var info = activeTouches[idString];
        var grabbedFreq = info.grabFreq;
        var touchedPixelNow = info.nowView;
        var newScrollLeft = (grabbedFreq - leftFreq) * pixelsPerHertz - touchedPixelNow;
        scrolls.push(newScrollLeft);
      }
      
      var avgScroll = scrolls.reduce(function (a, b) { return a + b; }, 0) / scrolls.length;
      
      // Frequency pan
      var clampedScroll = clampScroll(avgScroll);
      var overrun = avgScroll - clampedScroll;
      if (overrun !== 0 && isRFSpectrum) {
        // TODO repeated code -- abstract "cell to use to change freq"
        var freqCell = radioCell.get().source.get().freq;
        freqCell.set(freqCell.get() + overrun / pixelsPerHertz);
      }
      
      finishZoomUpdate(clampedScroll);
    }, {capture: true, passive: true});
    
    function touchcancel(event) {
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        delete activeTouches[touch.identifier];
      });
    }
    container.addEventListener('touchcancel', touchcancel, {capture: true, passive: true});
    
    container.addEventListener('touchend', function (event) {
      // Tap-to-tune
      // TODO: The overall touch event handling is disabling clicking on frequency DB labels. We need to recognize them as event targets in _this_ bunch of handlers, so that we can decide whether a gesture is pan or tap-on-label.
      if (mayTapToTune && isRFSpectrum) {
        var touch = event.changedTouches[0];  // known to be exactly one
        var info = activeTouches[touch.identifier];
        var newViewX = clientXToViewportLeft(touch.clientX);
        if (Math.abs(newViewX - info.grabView) < 20) {  // TODO justify choice of slop
          tune({
            freq: info.grabFreq,  // use initial touch pos, not final, because I expect it to be more precise
            alwaysCreate: alwaysCreateReceiverFromEvent(event)
          });
        }
      }
      
      // Forget the touch
      touchcancel(event);
    }, {capture: true, passive: true});
    
    this.addClickToTune = element => {
      if (!isRFSpectrum) return;
      
      let dragReceiver = null;
      
      function clickTune(event) {
        const firstEvent = event.type === 'mousedown';
        const freq = clientXToFreq(event.clientX);
        
        if (!firstEvent && !dragReceiver) {
          // We sent the request to create a receiver, but it doesn't exist on the client yet. Do nothing.
          // TODO: Check for the appearance of the receiver and start dragging it.
        } else {
          dragReceiver = tune({
            receiver: dragReceiver,
            freq: freq,
            alwaysCreate: firstEvent && alwaysCreateReceiverFromEvent(event)
          });
          
          // handled event
          event.stopPropagation();
          event.preventDefault(); // no drag selection
        }
      }
      element.addEventListener('mousedown', function(event) {
        if (event.button !== 0) return;  // don't react to right-clicks etc.
        event.preventDefault();
        document.addEventListener('mousemove', clickTune, true);
        document.addEventListener('mouseup', function(event) {
          dragReceiver = null;
          document.removeEventListener('mousemove', clickTune, true);
        }, true);
        clickTune(event);
      }, false);
    };
    
    function cc(key, type, value) {
      return new StorageCell(storage, type, value, key);
    }
    this.parameters = makeBlock({
      spectrum_split: cc('spectrum_split', new RangeT([[0, 1]], false, false), 0.6),
      spectrum_average: cc('spectrum_average', new RangeT([[0.1, 1]], true, false), 0.15),
      spectrum_level_min: cc('spectrum_level_min', new RangeT([[-200, -20]], false, false), -130),
      spectrum_level_max: cc('spectrum_level_max', new RangeT([[-100, 0]], false, false), -20)
    });
    
    lifecycleInit(container);
  }
  exports.SpectrumView = SpectrumView;
  
  function ErrorWidget(config, widgetCtor, error) {
    this.element = document.createElement('div');
    let widgetCtorName = widgetCtor ? widgetCtor.name : '<unknown widget type>';
    this.element.appendChild(document.createTextNode('An error occurred preparing what should occupy this space (' + widgetCtorName + ' named ' + config.element.getAttribute('title') + '). '));
    this.element.appendChild(document.createElement('code')).textContent = String(error);
  }
  
  return Object.freeze(exports);
});
