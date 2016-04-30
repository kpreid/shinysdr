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

define(['./values', './events', './coordination'], function (values, events, coordination) {
  'use strict';
  
  var Cell = values.Cell;
  var ConstantCell = values.ConstantCell;
  var Coordinator = coordination.Coordinator;
  var DerivedCell = values.DerivedCell;
  var StorageNamespace = values.StorageNamespace;
  
  var exports = {};
  
  // contains *only* widget types and can be used as a lookup namespace
  var widgets = Object.create(null);
  
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }
  
  function alwaysCreateReceiverFromEvent(event) {
    return event.shiftKey;
  }
  exports.alwaysCreateReceiverFromEvent = alwaysCreateReceiverFromEvent;
  
  // HTML element life cycle facility
  // We want to know "This element has been inserted in the final tree (has layout)" and "This element will no longer be used".
  
  function fireLifecycleEvent(element, condition) {
    //console.log('fire', element, condition);
    var key = '__shinysdr_lifecycle_' + condition + '__';
    if (key in element) {
      element[key].forEach(function(callback) {
        // TODO: error handling and think about scheduling
        callback();
      });
    }
  }
  
  function addLifecycleListener(element, condition, callback) {
    var key = '__shinysdr_lifecycle_' + condition + '__';
    if (!(key in element)) {
      element[key] = [];
    }
    element[key].push(callback);
  }
  exports.addLifecycleListener = addLifecycleListener;
  
  function lifecycleInit(element) {
    if (element.__shinysdr_lifecycle__ !== undefined) return;
    
    var root = element;
    while (root.parentNode) root = root.parentNode;
    if (root.nodeType !== Node.DOCUMENT_NODE) return;
    
    element.__shinysdr_lifecycle__ = 'live';
    fireLifecycleEvent(element, 'init');
    
    //Array.prototype.forEach.call(element.children, function (childEl) {
    //  lifecycleInit(childEl);
    //});
  }
  
  function lifecycleDestroy(element) {
    if (element.__shinysdr_lifecycle__ !== 'live') return;
    
    element.__shinysdr_lifecycle__ = 'dead';
    fireLifecycleEvent(element, 'destroy');
    
    Array.prototype.forEach.call(element.children, function (childEl) {
      lifecycleDestroy(childEl);
    });
  }
  
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
    var scheduler = context.scheduler;
    
    var originalStash = node;
    
    var container = node.parentNode;
    if (!container) {
      throw new Error('createWidget: The supplied node ' + node.nodeName + ' did not have a parent node.');
    }

    var currentWidgetEl = node;
    var shouldBePanel = container.classList.contains('frame') || container.nodeName === 'DETAILS';  // TODO: less DWIM, more precise
    
    var id = node.id;
    var idPrefix = id === '' ? null : node.id + '.';
    
    var go = function go() {
      var targetCell = targetCellCell.depend(go);
      if (!targetCell) {
        if (node.parentNode) { // TODO: This condition shouldn't be necessary?
          node.parentNode.replaceChild(document.createTextNode('[Missing: ' + targetStr + ']'), node);
        }
        return;
      }
      
      var boundedFnEnabled = true;
      function boundedFn(f) {
        return function boundedFnWrapper() {
          if (boundedFnEnabled) f.apply(undefined, arguments);
        }
      }

      lifecycleDestroy(currentWidgetEl);

      var newSourceEl = originalStash.cloneNode(true);
      container.replaceChild(newSourceEl, currentWidgetEl);
      
      var config = Object.freeze({
        scheduler: scheduler,
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
        boundedFn: boundedFn,
        idPrefix: idPrefix
      });
      var widget = undefined;
      try {
        widget = new widgetCtor(config);
      } catch (error) {
        console.error('Error creating widget: ', error);
        console.log(error.stack);
        widget = new ErrorWidget(config, widgetCtor, error);
      }
      
      widget.element.classList.add('widget-' + widget.constructor.name);  // TODO use stronger namespacing
      
      var newEl = widget.element;
      var placeMark = newSourceEl.nextSibling;
      if (newSourceEl.hasAttribute('title')) {
        console.warn('Widget ' + widgetCtor.name + ' did not handle title attribute');
      }
      
      if (newSourceEl.parentNode === container) {
        container.replaceChild(newEl, newSourceEl);
      } else {
        container.insertBefore(newEl, placeMark);
      }
      currentWidgetEl = newEl;
      
      doPersistentDetails(currentWidgetEl);
      
      // allow widgets to embed widgets
      createWidgetsInNode(targetCell || rootTargetCell, context, widget.element);
      
      addLifecycleListener(newEl, 'destroy', function() {
        boundedFnEnabled = false;
      });
      
      // signal now that we've inserted
      // TODO: Make this less DWIM
      lifecycleInit(newEl);
      setTimeout(function() {
        lifecycleInit(newEl);
      }, 0);
    }
    go.scheduler = scheduler;
    go();
    
    return Object.freeze({
      destroy: function() {
        lifecycleDestroy(currentWidgetEl);
        container.replaceChild(originalStash, currentWidgetEl);
      }
    });
  }
  
  function createWidgetExt(context, widgetCtor, node, targetCell) {
    if (!targetCell) {
      // catch a likely early error
      throw new Error('createWidgetExt: missing targetCell');
    }
    return createWidget(
      new ConstantCell(values.any, targetCell),
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
    return new DerivedCell(values.any, scheduler, function (dirty) {
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
        targetCellCell = new ConstantCell(values.any, rootTargetCell);
      }
      
      var typename = node.getAttribute('data-widget');
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
      var go = function go() {
        // TODO defend against JS-significant keys
        var target = evalTargetStr(rootTargetCell, node.getAttribute('data-target'), scheduler).depend(go);
        if (!target) {
          node.textContent = '[Missing: ' + node.getAttribute('data-target') + ']';
          return;
        }
        
        node.textContent = ''; // fast clear
        node.appendChild(html.cloneNode(true));
        createWidgetsInNode(target, context, node);
      }
      go.scheduler = scheduler;
      go();

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
    // TODO: It should be the case that radioCell is used only if isRFSpectrum is true. This is not quite true.
    var radioCell = config.radioCell;
    var container = config.outerElement;
    var innerElement = config.innerElement;
    var scheduler = config.scheduler;
    var storage = config.storage;
    var isRFSpectrum = config.isRFSpectrum;
    var signalTypeCell = config.signalTypeCell;
    var tune = config.actions.tune;
    var self = this;

    var n = this.n = new events.Notifier();
    
    // per-drawing-frame parameters
    var nyquist, centerFreq, leftFreq, rightFreq, pixelWidth, pixelsPerHertz, analytic;
    
    // Zoom state variables
    // We want the cursor point to stay fixed, but scrollLeft quantizes to integer; fractionalScroll stores a virtual fractional part.
    var zoom = 1;
    var fractionalScroll = 0;
    var cacheScrollLeft = 0;
    
    // Restore persistent zoom state
    addLifecycleListener(container, 'init', function() {
      // TODO: clamp zoom here in the same way changeZoom does
      zoom = parseFloat(storage.getItem('zoom')) || 1;
      var initScroll = parseFloat(storage.getItem('scroll')) || 0;
      innerElement.style.width = (container.offsetWidth * zoom) + 'px';
      prepare();
      function later() {  // gack kludge
        container.scrollLeft = Math.floor(initScroll);
        fractionalScroll = mod(initScroll, 1);
        prepare();
      }
      later.scheduler = scheduler;
      scheduler.enqueue(later);
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
      analytic = sourceType.kind == 'IQ';  // TODO have glue code
      leftFreq = analytic ? centerFreq - nyquist : centerFreq;
      rightFreq = centerFreq + nyquist;
      pixelsPerHertz = pixelWidth / (rightFreq - leftFreq) * zoom;
      
      if (!isFinite(fractionalScroll)) {
        console.error("Shouldn't happen: SpectrumView fractionalScroll =", fractionalScroll);
        fractionalScroll = 0;
      }
      
      // Adjust scroll to match possible viewport size change.
      // (But if we are hidden or zero size, then the new scroll position would be garbage, so keep the old state.)
      if (container.offsetWidth > 0 && pixelWidth != container.offsetWidth) {
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
    prepare.scheduler = config.scheduler;
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
    
    function clampZoom(zoomValue) {
      var maxZoom = Math.max(
        1,  // at least min zoom,
        Math.max(
          nyquist / 10e3, // at least 10 kHz
          radioCell.get().monitor.get().freq_resolution.get() / MAX_ZOOM_BINS));
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
      var oldZoom = zoom;
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
        if (event.wheelDeltaX > 0 && cacheScrollLeft == 0
            || event.wheelDeltaX < 0 && cacheScrollLeft == (container.scrollWidth - container.clientWidth)) {
          if (isRFSpectrum) {
            var freqCell = radioCell.get().source.get().freq;
            freqCell.set(freqCell.get() + (event.wheelDeltaX * -0.12) / pixelsPerHertz);
          }
          
          // This shouldn't be necessary, but Chrome treats horizontal scroll events from touchpad as a back/forward gesture.
          event.preventDefault();
        }
      }
    }, true);
    
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
      mayTapToTune = Object.keys(activeTouches) == 0 && event.changedTouches.length == 1;
      
      // Record the frequency the user has touched
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        var x = clientXToViewportLeft(touch.clientX);
        activeTouches[touch.identifier] = {
          grabFreq: clientXToFreq(touch.clientX),
          grabView: x,  // fixed
          nowView: x  // updated later
        };
      });
    }, false);
    
    container.addEventListener('touchmove', function (event) {
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        activeTouches[touch.identifier].nowView = clientXToViewportLeft(touch.clientX);
      });
      
      var identifiers = Object.keys(activeTouches);
      if (identifiers.length >= 2) {
        // Zoom using first two touches
        var f1 = activeTouches[0].grabFreq;
        var f2 = activeTouches[1].grabFreq;
        var p1 = activeTouches[0].nowView;
        var p2 = activeTouches[1].nowView;
        var newPixelsPerHertz = Math.abs(p2 - p1) / Math.abs(f2 - f1);
        var unzoomedPixelsPerHertz = pixelWidth / (rightFreq - leftFreq);
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
      if (overrun != 0 && isRFSpectrum) {
        // TODO repeated code -- abstract "cell to use to change freq"
        var freqCell = radioCell.get().source.get().freq;
        freqCell.set(freqCell.get() + overrun / pixelsPerHertz);
      }
      
      finishZoomUpdate(clampedScroll);
    }, true);
    
    function touchcancel(event) {
      // Prevent mouse-emulation handling
      event.preventDefault();
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        delete activeTouches[touch.identifier];
      });
    }
    container.addEventListener('touchcancel', touchcancel, true);
    
    container.addEventListener('touchend', function (event) {
      // Prevent mouse-emulation handling
      event.preventDefault();
      
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
          })
        }
      }
      
      // Forget the touch
      touchcancel(event);
    }, true);
    
    this.addClickToTune = function addClickToTune(element) {
      if (!isRFSpectrum) return;
      
      var dragReceiver = undefined;
      
      function clickTune(event) {
        var firstEvent = event.type === 'mousedown';
        // compute frequency
        var freq = clientXToFreq(event.clientX);
        
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
          dragReceiver = undefined;
          document.removeEventListener('mousemove', clickTune, true);
        }, true);
        clickTune(event);
      }, false);
    }.bind(this);
    
    lifecycleInit(container);
  }
  exports.SpectrumView = SpectrumView;
  
  function ErrorWidget(config, widgetCtor, error) {
    this.element = document.createElement('div');
    this.element.appendChild(document.createTextNode('An error occurred preparing what should occupy this space (' + widgetCtor.name + ' named ' + config.element.getAttribute('title') + '). '));
    this.element.appendChild(document.createElement('code')).textContent = String(error);
  }
  
  return Object.freeze(exports);
});
