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

define(['./values', './events'], function (values, events) {
  'use strict';
  
  var Cell = values.Cell;
  var ConstantCell = values.ConstantCell;
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
  
  // TODO figure out what this does and give it a better name
  function Context(config) {
    this.widgets = config.widgets;
    this.radio = config.radio;
    this.clientState = config.clientState;
    this.scheduler = config.scheduler;
    this.freqDB = config.freqDB;
    this.spectrumView = config.spectrumView;
  }
  Context.prototype.withSpectrumView = function (element) {
    if (!element.id) throw new Error('spectrum view element must have an id for persistence');
    var ns = new StorageNamespace(localStorage, 'shinysdr.viewState.' + element.id + '.');
    var view = new SpectrumView({
      scheduler: this.scheduler,
      radio: this.radio,
      element: element,
      storage: ns
    });
    return new Context({
      widgets: this.widgets,
      radio: this.radio,
      clientState: this.clientState,
      freqDB: this.freqDB,
      scheduler: this.scheduler,
      spectrumView: view
    })
  }
  exports.Context = Context;
  
  function createWidgetsInNode(rootTargetCell, context, node) {
    // TODO generalize this special case
    if (node.nodeType === 1 && node.classList.contains('hscalegroup')) {
      context = context.withSpectrumView(node);
    }
    
    Array.prototype.forEach.call(node.childNodes, function (child) {
      createWidgets(rootTargetCell, context, child);
    });
  }
  
  // Replace the given template/input node with a widget node.
  function createWidget(targetCellCell, targetStr, context, node, widgetCtor) {
    var scheduler = context.scheduler;
    
    var originalStash = node;
    
    var container = node.parentNode;
    var currentWidgetEl = node;
    var shouldBePanel = container.classList.contains('frame') || container.nodeName === 'DETAILS';  // TODO: less DWIM, more precise
    
    var go = function go() {
      var targetCell = targetCellCell.depend(go);
      if (!targetCell) {
        if (node.parentNode) { // TODO: This condition shouldn't be necessary?
          node.parentNode.replaceChild(document.createTextNode('[Missing: ' + targetStr + ']'), node);
        }
        return;
      }
      
      var widgetTarget;
      if (targetCell.type === values.block) {
        widgetTarget = targetCell.depend(go);
        widgetTarget._reshapeNotice.listen(go);
      } else {
        widgetTarget = targetCell;
      }

      var newSourceEl = originalStash.cloneNode(true);
      container.replaceChild(newSourceEl, currentWidgetEl);
      var widget = new widgetCtor({
        scheduler: scheduler,
        target: widgetTarget,
        element: newSourceEl,
        context: context, // TODO redundant values -- added for programmatic widget-creation; maybe facetize createWidget. Also should remove text-named widget table from this to make it more tightly scoped, perhaps.
        view: context.spectrumView, // TODO should be context-dependent
        clientState: context.clientState,
        freqDB: context.freqDB, // TODO: remove the need for this
        radio: context.radio, // TODO: remove the need for this
        storage: node.hasAttribute('id') ? new StorageNamespace(localStorage, 'shinysdr.widgetState.' + node.getAttribute('id') + '.') : null,
        shouldBePanel: shouldBePanel,
        rebuildMe: go
      });
      widget.element.classList.add('widget-' + widgetCtor.name);
      
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
      
      // allow widgets to embed widgets
      createWidgetsInNode(targetCell || rootTargetCell, context, widget.element);
    }
    go.scheduler = scheduler;
    go();
  }
  
  function createWidgetExt(context, widgetCtor, node, targetCell) {
    createWidget(
      new ConstantCell(values.any, targetCell),
      String(targetCell),
      context,
      node,
      widgetCtor);
  }
  exports.createWidgetExt = createWidgetExt;
  
  function createWidgets(rootTargetCell, context, node) {
    var scheduler = context.scheduler;
    if (node.hasAttribute && node.hasAttribute('data-widget')) {
      var targetCellCell, targetStr;
      if (node.hasAttribute('data-target')) {
        targetStr = node.getAttribute('data-target');
        targetCellCell = new DerivedCell(values.any, scheduler, function (dirty) {
          return rootTargetCell.depend(dirty)[targetStr];
        });
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
      var html = document.createDocumentFragment();
      while (node.firstChild) html.appendChild(node.firstChild);
      var go = function go() {
        // TODO defend against JS-significant keys
        var target = rootTargetCell.depend(go)[node.getAttribute('data-target')];
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

    }()); else if (node.nodeName === 'DETAILS' && node.hasAttribute('id')) {
      // Make any ID'd <details> element persistent
      var ns = new StorageNamespace(localStorage, 'shinysdr.elementState.' + node.id + '.');
      var stored = ns.getItem('detailsOpen');
      if (stored !== null) node.open = JSON.parse(stored);
      new MutationObserver(function(mutations) {
        ns.setItem('detailsOpen', JSON.stringify(node.open));
      }).observe(node, {attributes: true, attributeFilter: ['open']});
      createWidgetsInNode(rootTargetCell, context, node);

    } else {
      createWidgetsInNode(rootTargetCell, context, node);
    }
  }
  exports.createWidgets = createWidgets;
  
  // Defines the display parameters and coordinate calculations of the spectrum widgets
  // TODO: Revisit whether this should be in widgets.js -- it is closely tied to the spectrum widgets, but also managed by the widget framework.
  var MAX_ZOOM_BINS = 60; // Maximum zoom shows this many FFT bins
  function SpectrumView(config) {
    var radio = config.radio;
    var container = config.element;
    var scheduler = config.scheduler;
    var storage = config.storage;
    var self = this;

    // used to force the container's scroll range to widen immediately
    var scrollStub = container.appendChild(document.createElement('div'));
    scrollStub.style.height = '1px';
    scrollStub.style.marginTop = '-1px';
    scrollStub.style.visibility = 'hidden';
    
    var n = this.n = new events.Notifier();
    
    // per-drawing-frame parameters
    var bandwidth, centerFreq, leftFreq, pixelWidth, pixelsPerHertz, cacheScrollLeft;
    
    // Zoom state variables
    // We want the cursor point to stay fixed, but scrollLeft quantizes to integer; fractionalScroll stores a virtual fractional part.
    var zoom, fractionalScroll;
    // Zoom initial state:
    // TODO: clamp zoom here in the same way changeZoom does
    zoom = parseFloat(storage.getItem('zoom')) || 1;
    var initScroll = parseFloat(storage.getItem('scroll')) || 0;
    scrollStub.style.width = (container.offsetWidth * zoom) + 'px';
    container.scrollLeft = Math.floor(initScroll);
    var fractionalScroll = mod(initScroll, 1);
    
    function prepare() {
      // TODO: unbreakable notify loop here; need to be lazy
      var source = radio.source.depend(prepare);
      bandwidth = radio.input_rate.depend(prepare);
      centerFreq = source.freq.depend(prepare);
      leftFreq = centerFreq - bandwidth / 2;
      pixelWidth = container.offsetWidth;
      pixelsPerHertz = pixelWidth / bandwidth * zoom;
      // accessing scrollLeft triggers relayout
      cacheScrollLeft = container.scrollLeft;
      n.notify();
      // Note that this uses source.freq, not the spectrum data center freq. This is correct because we want to align the coords with what we have selected, not the current data; and the WaterfallPlot is aware of this distinction.
    }
    prepare.scheduler = config.scheduler;
    prepare();
    
    window.addEventListener('resize', function (event) {
      // immediate to ensure smooth animation
      scheduler.callNow(prepare);
    });
    
    container.addEventListener('scroll', scheduler.syncEventCallback(function (event) {
      storage.setItem('scroll', String(container.scrollLeft + fractionalScroll));
      // immediate to ensure smooth animation and interaction
      scheduler.callNow(prepare);
    }), false);
    
    // exported for the sake of createWidgets -- TODO proper factoring?
    this.scheduler = scheduler;
    
    // TODO legacy stubs -- vertical scale should be managed separately
    this.minLevel = -60;
    this.maxLevel = 30;
    
    this.freqToCSSLeft = function freqToCSSLeft(freq) {
      return ((freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSRight = function freqToCSSRight(freq) {
      return (pixelWidth - (freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSLength = function freqToCSSLength(freq) {
      return (freq * pixelsPerHertz) + 'px';
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
    this.getBandwidth = function getBandwidth() {
      return bandwidth;
    };
    this.getVisiblePixelWidth = function getVisiblePixelWidth() {
      return pixelWidth;
    };
    this.getTotalPixelWidth = function getTotalPixelWidth() {
      return pixelsPerHertz * bandwidth;
    };
    
    this.changeZoom = function changeZoom(delta, cursorX) {
      var maxZoom = Math.max(
        1,  // at least min zoom,
        Math.max(
          bandwidth / 100e3, // at least 100KHz
          radio.spectrum_fft.get().length / MAX_ZOOM_BINS));
      
      cursorX += fractionalScroll;
      var cursor01 = cursorX / pixelWidth;
      
      // Find frequency to keep under the cursor
      var cursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Adjust and clamp zoom
      var oldZoom = zoom;
      zoom *= Math.exp(-delta * 0.0005);
      zoom = Math.min(maxZoom, Math.max(1.0, zoom));
      
      // Recompute parameters now so we can adjust pan (scroll)
      prepare();
      
      var unadjustedCursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Force scrollable range to update
      var w = pixelWidth * zoom;
      scrollStub.style.width = w + 'px';
      // Current virtual scroll
      var scroll = container.scrollLeft + fractionalScroll;
      // Adjust
      scroll = Math.max(0, Math.min(w - pixelWidth, scroll + (cursorFreq - unadjustedCursorFreq) * pixelsPerHertz));
      // Write back
      container.scrollLeft = scroll;
      fractionalScroll = scroll - container.scrollLeft;
      
      storage.setItem('zoom', String(zoom));
      storage.setItem('scroll', String(scroll));
      
      scheduler.enqueue(prepare);
    };
    
    container.addEventListener('mousewheel', function(event) { // Portability note: Not in FF
      if (Math.abs(event.wheelDeltaY) > Math.abs(event.wheelDeltaX)) {
        // TODO: works only because we're at the left edge
        self.changeZoom(-event.wheelDeltaY, event.clientX);
        event.preventDefault();
        event.stopPropagation();
      } else {
        // allow normal horizontal scrolling
      }
    }, true);
    
    this.addClickToTune = function addClickToTune(element) {
      var dragReceiver = undefined;
      
      function clickTune(event) {
        var firstEvent = event.type === 'mousedown';
        // compute frequency
        // TODO: X calc works only because we're at the left edge
        var freq = (event.clientX + container.scrollLeft) / pixelsPerHertz + leftFreq;
        
        if (!firstEvent && !dragReceiver) {
          // We sent the request to create a receiver, but it doesn't exist on the client yet. Do nothing.
          // TODO: Check for the appearance of the receiver and start dragging it.
        } else {
          dragReceiver = radio.tune({
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
  }
  exports.SpectrumView = SpectrumView;
  
  return Object.freeze(exports);
});
