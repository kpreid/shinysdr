// Copyright 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020 Kevin Reid and the ShinySDR contributors
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
  './basic', 
  './dbui',
  '../database',
  '../domtools',
  '../events',
  '../gltools', 
  '../math', 
  '../menus', 
  '../types', 
  '../values', 
  '../widget',
  'text!./spectrum-common.glsl',
  'text!./spectrum-graph-f.glsl', 
  'text!./spectrum-graph-v.glsl',
  'text!./spectrum-waterfall-f.glsl', 
  'text!./spectrum-waterfall-v.glsl',
], (
  import_widgets_basic, 
  import_widgets_dbui,
  import_database,
  import_domtools,
  import_events,
  import_gltools, 
  import_math, 
  import_menus, 
  import_types, 
  import_values, 
  import_widget,
  shader_common,
  shader_graph_f,
  shader_graph_v,
  shader_waterfall_f,
  shader_waterfall_v
) => {
  const {
    Block,
    LinSlider,
    LogSlider,
    Toggle,
  } = import_widgets_basic;
  const {
    BareFreqList,
  } = import_widgets_dbui;
  const {
    empty: emptyDatabase,
  } = import_database;
  const {
    lifecycleInit,
    pixelsFromWheelEvent,
  } = import_domtools;
  const {
    Notifier,
  } = import_events;
  const {
    buildProgram,
    getGL,
    handleContextLoss,
    SingleQuad,
  } = import_gltools;
  const {
    formatFreqExact,
    formatFreqInexactVerbose,
    mod,
  } = import_math;
  const {
    Menu,
  } = import_menus;
  const {
    RangeT,
    numberT,
  } = import_types;
  const {
    ConstantCell,
    DerivedCell,
    StorageCell,
    StorageNamespace,
    makeBlock,
  } = import_values;
  const {
    alwaysCreateReceiverFromEvent,
    createWidgetExt,
  } = import_widget;
  
  const exports = {};
  
  function testForFirefoxFlexboxIssue() {
    // The CSS structure we use for a horizontally-scrollable element inside flexbox columns does not currently work on Firefox. Test for the bad layout consequence.
    const tester = document.body.appendChild(document.createElement('div'));
    tester.innerHTML = '<div style="width: 100px; display: flex; flex-direction: row;"><div style="border: solid; flex: 1 2; width: 1px;"><div style="overflow-x: scroll;"><div style="width: 1000px">foo</div></div></div></div>';
    const x = tester.firstChild.firstChild.offsetWidth;
    tester.parentNode.removeChild(tester);
    return x > 500;
  }
  
  const DISABLE_SPECTRUM_ZOOM = testForFirefoxFlexboxIssue();
  
  // Defines the display parameters and coordinate calculations of the spectrum widgets
  // TODO: Revisit whether this should be in widgets.js -- it is closely tied to the spectrum widgets, but also managed by the widget framework.
  const MAX_ZOOM_BINS = 60; // Maximum zoom shows this many FFT bins
  function SpectrumLayoutContext(config) {
    const radioCell = config.isRFSpectrum ? config.radioCell : null;
    const container = config.outerElement;
    const innerElement = config.innerElement;
    const scheduler = config.scheduler;
    const storage = config.storage;
    const isRFSpectrum = config.isRFSpectrum;
    const signalTypeCell = config.signalTypeCell;
    const tune = config.actions.tune;
    const self = this;

    const n = this.n = new Notifier();
    
    // per-drawing-frame parameters
    let nyquist, centerFreq, leftFreq, rightFreq, pixelWidth, pixelsPerHertz, analytic;
    
    // Zoom state variables
    // We want the cursor point to stay fixed, but scrollLeft quantizes to integer; fractionalScroll stores a virtual fractional part.
    let zoom = 1;
    let fractionalScroll = 0;
    let cacheScrollLeft = 0;
    
    // Restore persistent zoom state
    container.addEventListener('shinysdr:lifecycleinit', event => {
      // TODO: clamp zoom here in the same way changeZoom does
      zoom = parseFloat(storage.getItem('zoom')) || 1;
      const initScroll = parseFloat(storage.getItem('scroll')) || 0;
      if (!DISABLE_SPECTRUM_ZOOM) innerElement.style.width = (container.offsetWidth * zoom) + 'px';
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
      const sourceType = signalTypeCell.depend(prepare);
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
      
      if (!isFinite(fractionalScroll)) {
        console.error("Shouldn't happen: SpectrumLayoutContext fractionalScroll =", fractionalScroll);
        fractionalScroll = 0;
      }
      
      // Adjust scroll to match possible viewport size change.
      // (But if we are hidden or zero size, then the new scroll position would be garbage, so keep the old state.)
      if (container.offsetWidth > 0 && pixelWidth !== container.offsetWidth) {
        // Compute change (with case for first time initialization)
        const scaleChange = isFinite(pixelWidth) ? container.offsetWidth / pixelWidth : 1;
        const scrollValue = (cacheScrollLeft + fractionalScroll) * scaleChange;
        
        pixelWidth = container.offsetWidth;
        
        // Update scrollable range
        const w = pixelWidth * zoom;
        if (!DISABLE_SPECTRUM_ZOOM) innerElement.style.width = w + 'px';
        
        // Apply change
        container.scrollLeft = scrollValue;
        fractionalScroll = scrollValue - container.scrollLeft;
      }
      
      // Display scale. Note that this must be calculated after the pixelWidth update, but also even if only zoom and not pixelWidth changes.
      pixelsPerHertz = pixelWidth / (rightFreq - leftFreq) * zoom;
      
      // accessing scrollLeft triggers relayout, so cache it
      cacheScrollLeft = container.scrollLeft;
      n.notify();
    }
    scheduler.claim(prepare);
    prepare();
    
    window.addEventListener('resize', event => {
      // immediate to ensure smooth animation and to allow scroll adjustment
      scheduler.callNow(prepare);
    });
    
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
      // TODO: This being vertical rather than horizontal doesn't fit much with the rest of SpectrumLayoutContext's job, but it needs to know about innerElement.
      return innerElement.offsetHeight;
    };
    
    function clampZoom(zoomValue) {
      if (DISABLE_SPECTRUM_ZOOM) {
        return 1;
      }
      const maxZoom = Math.max(
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
      const w = pixelWidth * zoom;
      const oldWidth = parseInt(innerElement.style.width);
      if (!DISABLE_SPECTRUM_ZOOM) innerElement.style.width = Math.max(w, oldWidth) + 'px';
    }
    function finishZoomUpdate(scrollValue) {
      scrollValue = clampScroll(scrollValue);
      
      // Final scroll-range update.
      const w = pixelWidth * zoom;
      if (!DISABLE_SPECTRUM_ZOOM) innerElement.style.width = w + 'px';
      
      container.scrollLeft = scrollValue;
      fractionalScroll = scrollValue - container.scrollLeft;
      
      storage.setItem('zoom', String(zoom));
      storage.setItem('scroll', String(scrollValue));
      
      // recompute with new scrollLeft/fractionalScroll
      scheduler.callNow(prepare);
    }
    
    this.changeZoom = function changeZoom(delta, cursorX) {
      cursorX += fractionalScroll;
      const cursor01 = cursorX / pixelWidth;
      
      // Find frequency to keep under the cursor
      const cursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Adjust and clamp zoom
      zoom *= Math.exp(-delta * 0.0005);
      zoom = clampZoom(zoom);
      
      // Recompute parameters now so we can adjust pan (scroll)
      scheduler.callNow(prepare);
      
      const unadjustedCursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Force scrollable range to update
      startZoomUpdate();
      // Current virtual scroll
      let scroll = container.scrollLeft + fractionalScroll;
      // Adjust
      scroll = scroll + (cursorFreq - unadjustedCursorFreq) * pixelsPerHertz;
      // Write back
      finishZoomUpdate(scroll);
    };
    
    container.addEventListener('wheel', event => {
      const [dx, dy] = pixelsFromWheelEvent(event);
      if (Math.abs(dy) > Math.abs(dx) && !DISABLE_SPECTRUM_ZOOM) {
        // Vertical scrolling: override to zoom.
        self.changeZoom(dy, event.clientX - container.getBoundingClientRect().left);
        event.preventDefault();
        event.stopPropagation();
      } else {
        // Horizontal scrolling (or diagonal w/ useless vertical component): if hits edge, change frequency.
        if (dx < 0 && cacheScrollLeft === 0
            || dx > 0 && cacheScrollLeft === (container.scrollWidth - container.clientWidth)) {
          if (isRFSpectrum) {
            const freqCell = radioCell.get().source.get().freq;
            freqCell.set(freqCell.get() + dx / pixelsPerHertz);
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
    
    const activeTouches = Object.create(null);
    let mayTapToTune = false;
    
    container.addEventListener('touchstart', function (event) {
      // Prevent mouse-emulation handling
      event.preventDefault();
      
      // Tap-to-tune requires exactly one touch just starting
      mayTapToTune = Object.keys(activeTouches) === 0 && event.changedTouches.length === 1;
      
      // Record the frequency the user has touched
      Array.prototype.forEach.call(event.changedTouches, function (touch) {
        const x = clientXToViewportLeft(touch.clientX);
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
      const scrolls = [];
      for (const idString in activeTouches) {
        const info = activeTouches[idString];
        const grabbedFreq = info.grabFreq;
        const touchedPixelNow = info.nowView;
        const newScrollLeft = (grabbedFreq - leftFreq) * pixelsPerHertz - touchedPixelNow;
        scrolls.push(newScrollLeft);
      }
      
      const avgScroll = scrolls.reduce(function (a, b) { return a + b; }, 0) / scrolls.length;
      
      // Frequency pan
      const clampedScroll = clampScroll(avgScroll);
      const overrun = avgScroll - clampedScroll;
      if (overrun !== 0 && isRFSpectrum) {
        // TODO repeated code -- abstract "cell to use to change freq"
        const freqCell = radioCell.get().source.get().freq;
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
        const touch = event.changedTouches[0];  // known to be exactly one
        const info = activeTouches[touch.identifier];
        const newViewX = clientXToViewportLeft(touch.clientX);
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
  
  function addSpectrumLayoutContext(context, outerElement, innerElement, monitor, isRFSpectrum) {
    const id = outerElement.id || innerElement.id;
    if (!id) {
      throw new Error('SpectrumLayoutContext element must have an id for persistence');
    }
    // TODO: Remove hardcoded localStorage
    const ns = new StorageNamespace(localStorage, 'shinysdr.viewState.' + id + '.');
    return context.withLayoutContext(new SpectrumLayoutContext({
      scheduler: context.scheduler,
      radioCell: context.radioCell,
      outerElement: outerElement,
      innerElement: innerElement,
      storage: ns,
      isRFSpectrum: isRFSpectrum,
      signalTypeCell: monitor.signal_type,
      actions: context.coordinator.actions
    }));
  }
  
  // Widget for a monitor block
  function Monitor(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      const outerElement = this.element = config.element;
      outerElement.classList.add('widget-Monitor-outer');
      
      const scrollElement = outerElement.appendChild(document.createElement('div'));
      scrollElement.classList.add('widget-Monitor-scrollable');
      if (DISABLE_SPECTRUM_ZOOM) scrollElement.style.overflow = 'visible';
      scrollElement.id = config.element.id + '-scrollable';
      
      const overlayContainer = scrollElement.appendChild(document.createElement('div'));
      overlayContainer.classList.add('widget-Monitor-scrolled');

      // TODO: shouldn't need to have this declared, should be implied by context
      const isRFSpectrum = config.element.hasAttribute('data-is-rf-spectrum');
      const context = addSpectrumLayoutContext(config.context, scrollElement, overlayContainer, block, isRFSpectrum);
      
      function makeOverlayPiece(name) {
        const el = overlayContainer.appendChild(document.createElement(name));
        el.classList.add('widget-Monitor-overlay');
        return el;
      }
      if (isRFSpectrum) createWidgetExt(context, ReceiverMarks, makeOverlayPiece('div'), block.fft);
      createWidgetExt(context, WaterfallPlot, makeOverlayPiece('canvas'), block.fft);
      ignore('fft');
      
      // TODO this is clunky. (Note we're not just using rebuildMe because we don't want to lose waterfall history and reinit GL and and and...)
      const freqCell = isRFSpectrum ? (function() {
        const radioCell = config.radioCell;
        return new DerivedCell(numberT, config.scheduler, function (dirty) {
          return radioCell.depend(dirty).source.depend(dirty).freq.depend(dirty);
        });
      }()) : new ConstantCell(0);
      const freqScaleEl = overlayContainer.appendChild(document.createElement('div'));
      createWidgetExt(context, FreqScale, freqScaleEl, freqCell);
      
      const splitHandleEl = overlayContainer.appendChild(document.createElement('div'));
      createWidgetExt(context, VerticalSplitHandle, splitHandleEl, context.layoutContext.parameters.spectrum_split);
      
      // Not in overlayContainer because it does not scroll.
      // Works with zero height as the top-of-scale reference.
      const verticalScaleEl = outerElement.appendChild(document.createElement('div'));
      createWidgetExt(context, VerticalScale, verticalScaleEl, new ConstantCell('dummy'));

      const parametersEl = outerElement.appendChild(document.createElement('div'));
      if (config.idPrefix) parametersEl.id = config.idPrefix + 'parameters';
      createWidgetExt(context, MonitorDetailedOptions, parametersEl, config.target);
      
      // TODO should logically be doing this -- need to support "widget with possibly multiple target elements"
      //addWidget(null, MonitorQuickOptions);
      
      // MonitorDetailedOptions will handle what we don't.
      ignore('*');
      
      // kludge to trigger SpectrumLayoutContext layout computations after it's added to the DOM :(
      setTimeout(function() {
        const resize = document.createEvent('Event');
        resize.initEvent('resize', false, false);
        window.dispatchEvent(resize);
      }, 0);
    });
  }
  exports.Monitor = Monitor;
  exports['interface:shinysdr.i.blocks.IMonitor'] = Monitor;
  
  function MonitorQuickOptions(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('signal_type');
      ignore('fft');
      ignore('scope');
      ignore('window_type');
      addWidget('frame_rate', LogSlider, 'Rate');
      if (block.freq_resolution && block.freq_resolution.set) {  // for audio monitor
        addWidget('freq_resolution', LogSlider, 'Resolution');
      } else {
        ignore('freq_resolution');
      }
      if ('paused' in block) {
        const pausedLabel = getAppend().appendChild(document.createElement('label'));
        const pausedEl = pausedLabel.appendChild(document.createElement('input'));
        pausedEl.type = 'checkbox';
        pausedLabel.appendChild(document.createTextNode('Pause'));
        createWidgetExt(config.context, Toggle, pausedEl, block.paused);
        ignore('paused');
      }
      ignore('time_length');
    });
  }
  exports.MonitorQuickOptions = MonitorQuickOptions;

  function MonitorDetailedOptions(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      this.element.classList.remove('panel');
      this.element.classList.remove('frame');
      
      const details = getAppend().appendChild(document.createElement('details'));
      details.appendChild(document.createElement('summary'))
          .appendChild(document.createTextNode('Options'));
      if (config.idPrefix) details.id = config.idPrefix + 'details';
      setInsertion(details);
      
      const layoutContext = config.getLayoutContext(SpectrumLayoutContext);
      addWidget(layoutContext.parameters.spectrum_split, LinSlider, 'Split view');
      addWidget(layoutContext.parameters.spectrum_average, LogSlider, 'Averaging');
      addWidget(layoutContext.parameters.spectrum_level_min, LinSlider, 'Lowest value');
      addWidget(layoutContext.parameters.spectrum_level_max, LinSlider, 'Highest value');
      addWidget(config.clientState.opengl, Toggle, 'Use OpenGL');
      // TODO losing the special indent here
      addWidget(config.clientState.opengl_float, Toggle, 'with float textures');

      // handled by MonitorQuickOptions
      ignore('paused');
      ignore('frame_rate');
      ignore('freq_resolution');
      
      // the data and metadata itself, handled by others or not to be shown at all
      ignore('fft');
      ignore('scope');
      ignore('time_length');
      ignore('signal_type');
    });
  }
  exports.MonitorDetailedOptions = MonitorDetailedOptions;
  
  // Abstract
  // TODO: CanvasSpectrumWidget is now only used once and should go away
  function CanvasSpectrumWidget(config, buildGL, build2D) {
    const fftCell = config.target;
    const view = config.getLayoutContext(SpectrumLayoutContext);
    
    let canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
    }
    this.element = canvas;
    view.addClickToTune(canvas);
    canvas.setAttribute('title', '');  // prohibit auto-set title -- TODO: Stop having auto-set titles in the first place
    
    const glOptions = {
      powerPreference: 'high-performance',
      alpha: true,
      depth: false,
      stencil: false,
      antialias: false,
      preserveDrawingBuffer: false
    };
    const gl = getGL(config, canvas, glOptions);
    const ctx2d = canvas.getContext('2d');
    
    let dataHook = function () {}, drawOuter = function () {};
    
    const draw = config.scheduler.claim(function drawOuterTrampoline() {
      view.n.listen(draw);
      
      // Update canvas position and dimensions.
      let cleared = false;
      canvas.style.marginLeft = view.freqToCSSLeft(view.leftVisibleFreq());
      canvas.style.width = view.freqToCSSLength(view.rightVisibleFreq() - view.leftVisibleFreq());
      let w = canvas.offsetWidth;
      let h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
        cleared = true;
      }
      
      drawOuter(cleared);
    });
    
    if (gl) (function() {
      function initContext() {
        const drawImpl = buildGL(gl, draw);
        dataHook = drawImpl.newData.bind(drawImpl);
        
        drawOuter = drawImpl.performDraw.bind(drawImpl);
      }
      
      initContext();
      handleContextLoss(canvas, initContext);
    }.call(this)); else if (ctx2d) (function () {
      const drawImpl = build2D(ctx2d, draw);
      dataHook = drawImpl.newData.bind(drawImpl);
      drawOuter = drawImpl.performDraw.bind(drawImpl);
    }.call(this));
    
    function newFFTFrame(bundle) {
      dataHook(bundle);
      draw.scheduler.enqueue(draw);
    }
    config.scheduler.claim(newFFTFrame);

    fftCell.subscribe(newFFTFrame);
    draw();
  }
  
  function WaterfallPlot(config) {
    const self = this;
    const view = config.getLayoutContext(SpectrumLayoutContext);
    const avgAlphaCell = view.parameters.spectrum_average;
    
    const minLevelCell = view.parameters.spectrum_level_min;
    const maxLevelCell = view.parameters.spectrum_level_max;
    
    // I have read recommendations that color gradient scales should not involve more than two colors, as certain transitions between colors read as overly significant. However, in this case (1) we are not intending the waterfall chart to be read quantitatively, and (2) we want to have distinguishable small variations across a large dynamic range.
    const colors = [
      [0, 0, 0],
      [0, 0, 255],
      [0, 200, 255],
      [255, 255, 0],
      [255, 0, 0]
    ];
    const colorCountForScale = colors.length - 1;
    const colorCountForIndex = colors.length - 2;
    // value from 0 to 1, writes 0..255 into 4 elements of outArray
    function interpolateColor(value, outArray, base) {
      value *= colorCountForScale;
      const colorIndex = Math.max(0, Math.min(colorCountForIndex, Math.floor(value)));
      const colorInterp1 = value - colorIndex;
      const colorInterp0 = 1 - colorInterp1;
      const color0 = colors[colorIndex];
      const color1 = colors[colorIndex + 1];
      outArray[base    ] = color0[0] * colorInterp0 + color1[0] * colorInterp1;
      outArray[base + 1] = color0[1] * colorInterp0 + color1[1] * colorInterp1;
      outArray[base + 2] = color0[2] * colorInterp0 + color1[2] * colorInterp1;
      outArray[base + 3] = 255;
    }
    
    const backgroundColor = [119, 119, 119];
    const backgroundColorCSS = '#' + backgroundColor.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('');
    const backgroundColorGLSL = 'vec4(' + backgroundColor.map(function (v) { return v / 255; }).join(', ') + ', 1.0)';
    
    // TODO: Instead of hardcoding this, implement dynamic resizing of the history buffers. Punting for now because reallocating the GL textures would be messy.
    const historyCount = Math.max(
      1024,
      config.element.nodeName === 'CANVAS' ? config.element.height : 0);
    
    let lvf, rvf, w, h;
    function commonBeforeDraw(scheduledDraw) {
      view.n.listen(scheduledDraw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      w = canvas.width;
      h = canvas.height;
    }
    
    let canvas;
    let cleared = true;
    
    CanvasSpectrumWidget.call(this, config, buildGL, build2D);
    
    function buildGL(gl, draw) {
      canvas = self.element;

      const useFloatTexture =
        config.clientState.opengl_float.depend(config.rebuildMe) &&
        !!gl.getExtension('OES_texture_float') &&
        !!gl.getExtension('OES_texture_float_linear');

      const shaderPrefix =
        '#define USE_FLOAT_TEXTURE ' + (useFloatTexture ? '1' : '0') + '\n'
        + '#line 1 0\n' + shader_common
        + '\n#line 1 1\n';

      const graphProgram = buildProgram(gl, 
        shaderPrefix + shader_graph_v,
        shaderPrefix + shader_graph_f);
      const graphQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(graphProgram, 'position'));

      const waterfallProgram = buildProgram(gl,
        shaderPrefix + shader_waterfall_v,
        '#define BACKGROUND_COLOR ' + backgroundColorGLSL + '\n'
            + shaderPrefix + shader_waterfall_f);
      const waterfallQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(waterfallProgram, 'position'));
      
      const u_scroll = gl.getUniformLocation(waterfallProgram, 'scroll');
      const u_xTranslate = gl.getUniformLocation(waterfallProgram, 'xTranslate');
      const u_xScale = gl.getUniformLocation(waterfallProgram, 'xScale');
      const u_yScale = gl.getUniformLocation(waterfallProgram, 'yScale');
      const wu_currentFreq = gl.getUniformLocation(waterfallProgram, 'currentFreq');
      const gu_currentFreq = gl.getUniformLocation(graphProgram, 'currentFreq');
      const wu_freqScale = gl.getUniformLocation(waterfallProgram, 'freqScale');
      const gu_freqScale = gl.getUniformLocation(graphProgram, 'freqScale');
      const u_textureRotation = gl.getUniformLocation(waterfallProgram, 'textureRotation');
      
      let fftSize = Math.max(1, config.target.get().length);
      

      const spectrumDataTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
      // Ideally we would be linear in S (freq) and nearest in T (time), but that's not an option.
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      const historyFreqTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      const gradientTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      (function() {
        const components = 4;
        // stretch = number of texels to generate per color. If we generate only the minimum and fully rely on hardware gl.LINEAR interpolation then certain pixels in the display tends to flicker as it scrolls, on some GPUs.
        const stretch = 10;
        const limit = (colors.length - 1) * stretch + 1;
        const gradientInit = new Uint8Array(limit * components);
        for (let i = 0; i < limit; i++) {
          interpolateColor(i / (limit - 1), gradientInit, i * 4);
        }

        gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0, // level
          gl.RGBA, // internalformat
          1, // width
          gradientInit.length / components, // height
          0, // border
          gl.RGBA, // format
          gl.UNSIGNED_BYTE, // type
          gradientInit);

        // gradientZero and gradientScale set the scaling from data texture values to gradient texture coordinates
        // gradientInset is the amount to compensate for half-texel edges
        config.scheduler.startNow(function computeGradientScale() {
          const gradientInset = 0.5 / (gradientInit.length / components);
          const insetZero = gradientInset;
          const insetScale = 1 - gradientInset * 2;
          let valueZero, valueScale;
          if (useFloatTexture) {
            const minLevel = minLevelCell.depend(computeGradientScale);
            const maxLevel = maxLevelCell.depend(computeGradientScale);
            valueScale = 1 / (maxLevel - minLevel);
            valueZero = valueScale * -minLevel;
          } else {
            valueZero = 0;
            valueScale = 1;
          }
        
          gl.useProgram(graphProgram);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'valueZero'), valueZero);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'valueScale'), valueScale);

          gl.useProgram(waterfallProgram);
          gl.uniform1f(gl.getUniformLocation(waterfallProgram, 'gradientZero'), insetZero + insetScale * valueZero);
          gl.uniform1f(gl.getUniformLocation(waterfallProgram, 'gradientScale'), insetScale * valueScale);
          draw.scheduler.enqueue(draw);
        });
      }());

      gl.bindTexture(gl.TEXTURE_2D, null);

      function configureTexture() {
        // TODO: If fftSize > gl.getParameter(gl.MAX_TEXTURE_SIZE) (or rather, if we fail to allocate a texture of that size), we have a problem. We can fix that by instead allocating a narrower texture and storing the fft data in multiple rows. (Or is that actually necessary -- do any WebGL implementations support squarish-but-not-long textures?)
        // If we fail due to total size, we can reasonably reduce the historyCount.
        if (useFloatTexture) {
          {
            const init = new Float32Array(fftSize*historyCount);
            for (let i = 0; i < fftSize*historyCount; i++) {
              init[i] = -1000;  // well below minimum display level
            }
            gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
            gl.texImage2D(
              gl.TEXTURE_2D,
              0, // level
              gl.LUMINANCE, // internalformat
              fftSize, // width (= fft size)
              historyCount, // height (= history size)
              0, // border
              gl.LUMINANCE, // format
              gl.FLOAT, // type -- TODO use non-float textures if needed
              init);
          }
          
          {
            const init = new Float32Array(historyCount);
            for (let i = 0; i < historyCount; i++) {
              init[i] = -1e20;  // dummy value which we hope will not land within the viewport
            }
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texImage2D(
              gl.TEXTURE_2D,
              0, // level
              gl.LUMINANCE, // internalformat
              1, // width
              historyCount, // height (= history size)
              0, // border
              gl.LUMINANCE, // format
              gl.FLOAT, // type
              init);
          }
        } else {
          {
            const init = new Uint8Array(fftSize*historyCount*4);
            gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
            gl.texImage2D(
              gl.TEXTURE_2D,
              0, // level
              gl.LUMINANCE, // internalformat
              fftSize, // width (= fft size)
              historyCount, // height (= history size)
              0, // border
              gl.LUMINANCE, // format
              gl.UNSIGNED_BYTE, // type
              init);
          }
          
          {
            const init = new Uint8Array(historyCount*4);
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texImage2D(
              gl.TEXTURE_2D,
              0, // level
              gl.RGBA, // internalformat
              1, // width
              historyCount, // height (= history size)
              0, // border
              gl.RGBA, // format
              gl.UNSIGNED_BYTE,
              init);
          }
        }

        gl.bindTexture(gl.TEXTURE_2D, null);
      }
      configureTexture();

      // initial state of graph program
      gl.useProgram(graphProgram);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'spectrumDataTexture'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE0);
      
      // initial state of waterfall program
      gl.useProgram(waterfallProgram);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'spectrumDataTexture'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE3);
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'gradient'), 3);
      gl.activeTexture(gl.TEXTURE0);

      let slicePtr = 0;

      const freqWriteBuffer = useFloatTexture ? new Float32Array(1) : new Uint8Array(4);
      let intConversionBuffer, intConversionOut;
      
      return {
        newData: function (fftBundle) {
          const buffer = fftBundle[1];
          const bufferCenterFreq = fftBundle[0].freq;
          
          if (buffer.length === 0) {
            return;
          }
          
          if (buffer.length !== fftSize || !useFloatTexture && !intConversionBuffer) {
            fftSize = buffer.length;
            configureTexture();
            intConversionBuffer = useFloatTexture ? null : new Uint8ClampedArray(fftSize);
            intConversionOut = useFloatTexture ? null : new Uint8Array(intConversionBuffer.buffer);
          }

          // TODO: This doesn't need to be updated every frame, but it does depend on the view unlike other things
          // Shift (with wrapping) the texture data by 1/2 minus half a bin width, to align the GL texels with the FFT bins.
          gl.uniform1f(u_textureRotation, view.isRealFFT() ? 0 : -(0.5 - 0.5/fftSize));

          if (useFloatTexture) {
            gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                fftSize,
                1,
                gl.LUMINANCE,
                gl.FLOAT,
                buffer);

            freqWriteBuffer[0] = bufferCenterFreq;
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                1,
                1,
                gl.LUMINANCE,
                gl.FLOAT,
                freqWriteBuffer);
          } else {
            gl.bindTexture(gl.TEXTURE_2D, spectrumDataTexture);
            // TODO: By doing the level shift at this point, we are locking in the current settings. It would be better to arrange for min/max changes to rescale historical data as well, as it does in float-texture mode (would require keeping the original data as well as the texture contents and recopying it).
            const minLevel = minLevelCell.get();
            const maxLevel = maxLevelCell.get();
            const cscale = 255 / (maxLevel - minLevel);
            for (let i = 0; i < fftSize; i++) {
              intConversionBuffer[i] = (buffer[i] - minLevel) * cscale;
            }
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                fftSize,
                1,
                gl.LUMINANCE,
                gl.UNSIGNED_BYTE,
                intConversionOut);

            freqWriteBuffer[0] = (bufferCenterFreq >> 0) & 0xFF;
            freqWriteBuffer[1] = (bufferCenterFreq >> 8) & 0xFF;
            freqWriteBuffer[2] = (bufferCenterFreq >> 16) & 0xFF;
            freqWriteBuffer[3] = (bufferCenterFreq >> 24) & 0xFF;
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                1,
                1,
                gl.RGBA,
                gl.UNSIGNED_BYTE,
                freqWriteBuffer);
          }

          gl.bindTexture(gl.TEXTURE_2D, null);
          slicePtr = mod(slicePtr + 1, historyCount);
        },
        performDraw: function (didResize) {
          commonBeforeDraw(draw);
          const viewCenterFreq = view.getCenterFreq();
          const split = Math.round(canvas.height * view.parameters.spectrum_split.depend(draw));
          
          // common calculations
          const lsf = view.leftFreq();
          const rsf = view.rightFreq();
          const bandwidth = rsf - lsf;
          const fs = 1.0 / bandwidth;
          const xScale = (rvf-lvf) * fs;
          
          gl.viewport(0, split, w, h - split);
          
          gl.useProgram(graphProgram);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xRes'), w);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'yRes'), h - split);
          gl.uniform1f(gu_freqScale, fs);
          gl.uniform1f(gu_currentFreq, viewCenterFreq);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'avgAlpha'), avgAlphaCell.depend(draw));
          // Adjust drawing region
          const halfBinWidth = bandwidth / fftSize / 2;
          // The half bin width correction is because OpenGL texture coordinates put (0,0) between texels, not centered on one.
          const xZero = (lvf - viewCenterFreq + halfBinWidth)/(rsf-lsf);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xZero'), xZero);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xScale'), xScale);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'scroll'), slicePtr / historyCount);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'historyStep'), 1.0 / historyCount);
          
          graphQuad.draw();
          
          gl.viewport(0, 0, w, split);
          
          gl.useProgram(waterfallProgram);
          gl.uniform1f(u_scroll, slicePtr / historyCount);
          gl.uniform1f(u_yScale, split / historyCount);
          gl.uniform1f(wu_freqScale, fs);
          gl.uniform1f(wu_currentFreq, viewCenterFreq);
          gl.uniform1f(u_xTranslate, (view.leftVisibleFreq() - view.leftFreq()) * fs);
          gl.uniform1f(u_xScale, xScale);

          waterfallQuad.draw();
          cleared = false;
        }
      };
    }
    
    function build2D(ctx, draw) {
      canvas = self.element;
      
      // secondary canvas to use for image scaling
      const scaler = document.createElement('canvas');
      scaler.height = 1;
      const scalerCtx = scaler.getContext('2d');
      if (!scalerCtx) { throw new Error('failed to get headless canvas context'); }
      
      // view parameters recomputed on draw
      let freqToCanvasPixelFactor;
      let xTranslateFreq;
      let pixelWidthOfFFT;
      
      function paintSlice(imageData, freqOffset, y) {
        if (scaler.width < imageData.width) {
          // TODO detect if we are exceeding maximum supported size
          scaler.width = imageData.width;
        }
        // TODO deal with left/right edge wraparound fringes
        scalerCtx.putImageData(imageData, 0, 0);
        ctx.drawImage(
          scaler,
          0, 0, imageData.width, 1,  // source rect
          freqToCanvasPixelFactor * (freqOffset - xTranslateFreq), y, pixelWidthOfFFT, 1);  // destination rect
      }
      
      // circular buffer of ImageData objects, and info to invalidate it
      const slices = [];
      let slicePtr = 0;
      let lastDrawnLeftVisibleFreq = NaN;
      let lastDrawnRightVisibleFreq = NaN;
      
      // for detecting when to invalidate the averaging buffer
      let lastDrawnCenterFreq = NaN;
      
      // Graph drawing parameters and functions
      // Each variable is updated in draw()
      // This is done so that the functions need not be re-created
      // each frame.
      let gxZero, xScale, xNegBandwidthCoord, xPosBandwidthCoord, yZero, yScale, firstPoint, lastPoint, fftLen, graphDataBuffer;
      function freqToCoord(freq) {
        return (freq - lvf) / (rvf-lvf) * w;
      }
      function graphPath() {
        ctx.beginPath();
        ctx.moveTo(xNegBandwidthCoord - xScale, h + 2);
        for (let i = firstPoint; i <= lastPoint; i++) {
          ctx.lineTo(gxZero + i * xScale, yZero + graphDataBuffer[mod(i, fftLen)] * yScale);
        }
        ctx.lineTo(xPosBandwidthCoord + xScale, h + 2);
      }
      
      // Drawing state for graph
      ctx.lineWidth = 1;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      
      let fillStyle = 'white';
      let strokeStyle = 'white';
      canvas.addEventListener('shinysdr:lifecycleinit', event => {
        fillStyle = getComputedStyle(canvas).fill;
        strokeStyle = getComputedStyle(canvas).stroke;
      }, true);
      
      function changedSplit() {
        cleared = true;
        draw.scheduler.enqueue(draw);
      }
      config.scheduler.claim(changedSplit);
      
      function performDraw(clearedIn) {
        commonBeforeDraw(draw);
        
        cleared = cleared || clearedIn;
        const viewLVF = view.leftVisibleFreq();
        const viewRVF = view.rightVisibleFreq();
        const viewCenterFreq = view.getCenterFreq();
        freqToCanvasPixelFactor = w / (viewRVF - viewLVF);
        xTranslateFreq = viewLVF - view.leftFreq();
        pixelWidthOfFFT = view.getTotalPixelWidth();

        const split = Math.round(canvas.height * view.parameters.spectrum_split.depend(changedSplit));
        const topOfWaterfall = h - split;
        const heightOfWaterfall = split;

        let buffer, bufferCenterFreq, ibuf;
        if (dataToDraw) {
          buffer = dataToDraw[1];
          bufferCenterFreq = dataToDraw[0].freq;
          const fftLength = buffer.length;

          // can't draw with w=0
          if (w === 0 || fftLength === 0) {
            return;
          }

          // Find slice to write into
          if (slices.length < historyCount) {
            slices.push([ibuf = ctx.createImageData(fftLength, 1), bufferCenterFreq]);
          } else {
            const record = slices[slicePtr];
            slicePtr = mod(slicePtr + 1, historyCount);
            ibuf = record[0];
            if (ibuf.width !== fftLength) {
              ibuf = record[0] = ctx.createImageData(fftLength, 1);
            }
            record[1] = bufferCenterFreq;
          }

          // Generate image slice from latest FFT data.
          // TODO get half-pixel alignment right elsewhere, and supply wraparound on both ends in this data
          // TODO: By converting to color at this point, we are locking in the current min/max settings. It would be better to arrange for min/max changes to rescale historical data as well, as it does in GL-float-texture mode (would require keeping the original data as well as the texture contents and recopying it).
          const xZero = view.isRealFFT() ? 0 : Math.floor(fftLength / 2);
          const cScale = 1 / (maxLevelCell.get() - minLevelCell.get());
          const cZero = 1 - maxLevelCell.get() * cScale;
          const data = ibuf.data;
          for (let x = 0; x < fftLength; x++) {
            const base = x * 4;
            const colorVal = buffer[mod(x + xZero, fftLength)] * cScale + cZero;
            interpolateColor(colorVal, data, base);
          }
        }

        ctx.fillStyle = backgroundColorCSS;

        const sameView = lastDrawnLeftVisibleFreq === viewLVF && lastDrawnRightVisibleFreq === viewRVF;
        if (dataToDraw && sameView && !cleared) {
          // Scroll
          ctx.drawImage(ctx.canvas,
            0, topOfWaterfall, w, heightOfWaterfall-1,
            0, topOfWaterfall+1, w, heightOfWaterfall-1);

          // fill background of new line, if needed
          if (bufferCenterFreq !== viewCenterFreq) {
            ctx.fillRect(0, topOfWaterfall, w, 1);
          }

          // Paint newest slice
          paintSlice(ibuf, bufferCenterFreq - viewCenterFreq, topOfWaterfall);
        } else if (cleared || !sameView) {
          // Horizontal position changed, paint all slices onto canvas
          
          lastDrawnLeftVisibleFreq = viewLVF;
          lastDrawnRightVisibleFreq = viewRVF;
          // fill background so scrolling is of an opaque image
          ctx.fillRect(0, 0, w, h);
          
          const sliceCount = slices.length;
          let y;
          for (let i = sliceCount - 1; i >= 0; i--) {
            const slice = slices[mod(i + slicePtr, sliceCount)];
            y = topOfWaterfall + sliceCount - i - 1;
            if (y >= h) break;

            // paint slice
            paintSlice(slice[0], slice[1] - viewCenterFreq, y);
          }
          ctx.fillRect(0, y+1, w, h);
        }

        // Done with waterfall, now draw graph
        (function() {
          if (!graphDataBuffer) return;
          
          fftLen = graphDataBuffer.length;  // TODO name collisionish
          const halfFFTLen = Math.floor(fftLen / 2);
        
          if (halfFFTLen <= 0) {
            // no data yet, don't try to draw
            return;
          }

          const viewCenterFreq = view.getCenterFreq();
          gxZero = freqToCoord(viewCenterFreq);
          xNegBandwidthCoord = freqToCoord(view.leftFreq());
          xPosBandwidthCoord = freqToCoord(view.rightFreq());
          xScale = (xPosBandwidthCoord - xNegBandwidthCoord) / fftLen;
          yScale = -topOfWaterfall / (maxLevelCell.depend(draw) - minLevelCell.depend(draw));
          yZero = -maxLevelCell.depend(draw) * yScale;

          // choose points to draw
          firstPoint = Math.floor(-gxZero / xScale) - 1;
          lastPoint = Math.ceil((w - gxZero) / xScale) + 1;

          // clip so our oversized path doesn't hit waterfall
          ctx.save();
          ctx.beginPath();
          ctx.rect(0, 0, w, topOfWaterfall);
          ctx.clip();
          
          // Draw graph.
          // Fill is deliberately over stroke. This acts to deemphasize downward stroking of spikes, which tend to occur in noise.
          ctx.clearRect(0, 0, w, topOfWaterfall);
          ctx.fillStyle = fillStyle;
          ctx.strokeStyle = strokeStyle;
          graphPath();
          ctx.stroke();
          graphPath();
          ctx.fill();
          
          // unclip
          ctx.restore();
        }());

        dataToDraw = null;
        cleared = false;
      }

      let dataToDraw = null;  // TODO this is a data flow kludge
      return {
        newData: function (fftBundle) {
          const buffer = fftBundle[1];
          const bufferCenterFreq = fftBundle[0].freq;
          const len = buffer.length;
          const alpha = avgAlphaCell.get();
          const invAlpha = 1 - alpha;

          // averaging
          // TODO: Get separate averaged and unaveraged FFTs from server so that averaging behavior is not dependent on frame rate over the network
          if (!graphDataBuffer
              || graphDataBuffer.length !== len
              || (lastDrawnCenterFreq !== bufferCenterFreq
                  && !isNaN(bufferCenterFreq))) {
            lastDrawnCenterFreq = bufferCenterFreq;
            graphDataBuffer = new Float32Array(buffer);
          }

          for (let i = 0; i < len; i++) {
            let v = graphDataBuffer[i] * invAlpha + buffer[i] * alpha;
            if (!isFinite(v)) v = buffer[i];
            graphDataBuffer[i] = v;
          }
          
          // Hand data over to waterfall drawing immediately, so that the scrolling occurs and every frame is painted.
          // TODO: It would be more efficient to queue things so that if we _do_ have multiple frames to draw, we don't do multiple one-pixel scrolling steps
          dataToDraw = fftBundle;
          performDraw(false);
        },
        performDraw: performDraw
      };
    }
  }
  exports.WaterfallPlot = WaterfallPlot;

  function to_dB(x) {
    return Math.log(x) / (Math.LN10 / 10);
  }

  function ReceiverMarks(config) {
    /* does not use config.target */
    const view = config.getLayoutContext(SpectrumLayoutContext);
    const radioCell = config.radioCell;
    const others = config.index.implementing('shinysdr.interfaces.IHasFrequency');
    // TODO: That this cell matters here is shared knowledge between this and ReceiverMarks. Should instead be managed by SpectrumLayoutContext (since it already handles freq coordinates), in the form "get Y position of minLevel".
    const splitCell = view.parameters.spectrum_split;
    const minLevelCell = view.parameters.spectrum_level_min;
    const maxLevelCell = view.parameters.spectrum_level_max;
    
    let canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
      canvas.classList.add('widget-Monitor-overlay');  // TODO over-coupling
    }
    this.element = canvas;
    
    const ctx = canvas.getContext('2d');
    const textOffsetFromTop =
        //ctx.measureText('j').fontBoundingBoxAscent; -- not yet supported
        10 + 2; // default font size is "10px", ignoring effect of baseline
    const textSpacing = 10 + 1;
    
    // Drawing parameters and functions
    // Each variable is updated in draw()
    // This is done so that the functions need not be re-created
    // each frame.
    let w, h, lvf, rvf;
    function freqToCoord(freq) {
      return (freq - lvf) / (rvf-lvf) * w;
    }
    function drawHair(freq) {
      let x = freqToCoord(freq);
      x = Math.floor(x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, ctx.canvas.height);
      ctx.stroke();
    }
    function drawBand(freq1, freq2) {
      const x1 = freqToCoord(freq1);
      const x2 = freqToCoord(freq2);
      ctx.fillRect(x1, 0, x2 - x1, ctx.canvas.height);
    }
    
    function draw() {
      view.n.listen(draw);
      const visibleDevice = radioCell.depend(draw).source_name.depend(draw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      
      canvas.style.marginLeft = view.freqToCSSLeft(lvf);
      canvas.style.width = view.freqToCSSLength(rvf - lvf);

      w = canvas.offsetWidth;
      h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
      } else {
        ctx.clearRect(0, 0, w, h);
      }
      
      const yScale = -(h * (1 - splitCell.depend(draw))) / (maxLevelCell.depend(draw) - minLevelCell.depend(draw));
      const yZero = -maxLevelCell.depend(draw) * yScale;
      
      ctx.strokeStyle = 'gray';
      drawHair(view.getCenterFreq()); // center frequency
      
      others.depend(draw).forEach(function (object) {
        ctx.strokeStyle = 'green';
        drawHair(object.freq.depend(draw));
      });
      
      const receivers = radioCell.depend(draw).receivers.depend(draw);
      receivers._reshapeNotice.listen(draw);
      for (const recKey in receivers) {
        const receiver = receivers[recKey].depend(draw);
        const device_name_now = receiver.device_name.depend(draw);
        const rec_freq_now = receiver.rec_freq.depend(draw);
        
        if (!(lvf <= rec_freq_now && rec_freq_now <= rvf && device_name_now === visibleDevice)) {
          continue;
        }
        
        const band_shape_cell = receiver.demodulator.depend(draw).band_shape;
        let band_shape_now;
        if (band_shape_cell) {
          band_shape_now = band_shape_cell.depend(draw);
        }

        if (band_shape_now) {
          ctx.fillStyle = '#3A3A3A';
          drawBand(rec_freq_now + band_shape_now.stop_low, rec_freq_now + band_shape_now.stop_high);
          ctx.fillStyle = '#444444';
          drawBand(rec_freq_now + band_shape_now.pass_low, rec_freq_now + band_shape_now.pass_high);
        }

        // TODO: marks ought to be part of a distinct widget
        const squelch_threshold_cell = receiver.demodulator.depend(draw).squelch_threshold;
        if (squelch_threshold_cell) {
          const squelchPower = squelch_threshold_cell.depend(draw);
          let squelchL, squelchR, bandwidth;
          if (band_shape_now) {
            squelchL = freqToCoord(rec_freq_now + band_shape_now.stop_low);
            squelchR = freqToCoord(rec_freq_now + band_shape_now.stop_high);
            bandwidth = (band_shape_now.pass_high - band_shape_now.pass_low);
          } else {
            // dummy
            squelchL = 0;
            squelchR = w;
            bandwidth = 10e3;
          }
          const squelchPSD = squelchPower - to_dB(bandwidth);
          const squelchY = Math.floor(yZero + squelchPSD * yScale) + 0.5;
          const minSquelchHairWidth = 30;
          if (squelchR - squelchL < minSquelchHairWidth) {
            const squelchMid = (squelchR + squelchL) / 2;
            squelchL = squelchMid - minSquelchHairWidth/2;
            squelchR = squelchMid + minSquelchHairWidth/2;
          }
          ctx.strokeStyle = '#F00';
          ctx.beginPath();
          ctx.moveTo(squelchL, squelchY);
          ctx.lineTo(squelchR, squelchY);
          ctx.stroke();
        }
        
        // prepare to draw hairlines and text
        ctx.strokeStyle = 'white';
        ctx.fillStyle = 'white';
        const textX = freqToCoord(rec_freq_now) + 2;
        let textY = textOffsetFromTop - textSpacing;
        
        // receiver hairline & info
        drawHair(rec_freq_now);
        ctx.fillText(recKey, textX, textY += textSpacing);
        ctx.fillText(formatFreqInexactVerbose(receiver.rec_freq.depend(draw)), textX, textY += textSpacing);
        ctx.fillText(receiver.mode.depend(draw), textX, textY += textSpacing);
        
        // additional hairlines
        if (band_shape_now) {
          ctx.strokeStyle = ctx.fillStyle = '#7F7';
          for (const markerFreqStr in band_shape_now.markers) {
            const markerAbsFreq = rec_freq_now + (+markerFreqStr);
            drawHair(markerAbsFreq);
            ctx.fillText(String(band_shape_now.markers[markerFreqStr]), freqToCoord(markerAbsFreq) + 2, textY + textSpacing);
          }
        }
      }
    }
    config.scheduler.startLater(draw);  // must draw after widget inserted to get proper layout
  }
  
  // Waterfall overlay printing amplitude labels.
  function VerticalScale(config) {
    const view = config.getLayoutContext(SpectrumLayoutContext);
    const splitCell = view.parameters.spectrum_split;
    const minLevelCell = view.parameters.spectrum_level_min;
    const maxLevelCell = view.parameters.spectrum_level_max;
    
    let minLevel = 0, maxLevel = 0, pixelHeight = 0;  // updated in draw()
    
    const outerEl = this.element = document.createElement('div');
    
    function amplitudeToY(amplitude) {
      return ((amplitude - maxLevel) / (minLevel - maxLevel) * pixelHeight) + 'px';
    }
    
    const numberCache = new VisibleItemCache(outerEl, amplitude => {
      const labelOuter = document.createElement('div');
      const labelInner = labelOuter.appendChild(document.createElement('div'));
      labelOuter.className = 'widget-VerticalScale-mark';
      labelInner.className = 'widget-VerticalScale-number';
      labelOuter.my_update = () => {
        labelInner.textContent = String(amplitude).replace('-', '\u2212');
        if (labelOuter.show_units) {
          // TODO: Get units from the cell metadata instead of assuming.
          labelInner.textContent += '\u00A0dBFS/Hz';
        }
        labelOuter.style.top = amplitudeToY(amplitude);
      };
      return labelOuter;
    });
    
    outerEl.tabIndex = 0;
    outerEl.addEventListener('click', event => {
      outerEl.classList.toggle('widget-VerticalScale-expanded');
    }, false);
    
    config.scheduler.startNow(function draw() {
      minLevel = minLevelCell.depend(draw);
      maxLevel = maxLevelCell.depend(draw);
      pixelHeight = view.getVisiblePixelHeight() * (1 - splitCell.depend(draw));
      view.n.listen(draw);
      
      outerEl.style.height = pixelHeight + 'px';
      
      for (let amplitude = Math.floor(maxLevel / 10) * 10,
               count = 0;
           amplitude >= minLevel && count < 50 /* sanity check */;
           amplitude -= 10, count++) {
        const entry = numberCache.add(amplitude);
        entry.show_units = count == 1;
        entry.my_update();
      }
      numberCache.flush();
    });
  }
  
  function FreqScale(config) {
    const view = config.getLayoutContext(SpectrumLayoutContext);
    const dataSource = view.isRFSpectrum() ? config.freqDB.groupSameFreq() : emptyDatabase;
    const tune = config.actions.tune;
    const menuContext = config.context;

    // cache query
    let query, qLower = NaN, qUpper = NaN;

    const labelWidth = 60; // TODO actually measure styled text
    
    // view parameters closed over
    let lower, upper;
    
    
    const stacker = new IntervalStacker();
    function pickY(lowerFreq, upperFreq) {
      return (stacker.claim(lowerFreq, upperFreq) + 1) * 1.15;
    }

    const outer = this.element = document.createElement("div");
    outer.className = "freqscale";
    const numbers = outer.appendChild(document.createElement('div'));
    numbers.className = 'freqscale-numbers';
    const labels = outer.appendChild(document.createElement('div'));
    labels.className = 'freqscale-labels';
    
    outer.style.position = 'absolute';
    config.scheduler.startNow(function doLayout() {
      // TODO: This is shared knowledge between this, WaterfallPlot, and ReceiverMarks. Should instead be managed by SpectrumLayoutContext (since it already handles freq coordinates), in the form "get Y position of minLevel".
      outer.style.bottom = (view.parameters.spectrum_split.depend(doLayout) * 100).toFixed(2) + '%';
    });
    
    // label maker fns
    function addChannel(record) {
      const isGroup = record.type === 'group';
      const channel = isGroup ? record.grouped[0] : record;
      const freq = record.freq;
      const el = document.createElement('button');
      el.className = 'freqscale-channel';
      el.textContent =
        (isGroup ? '(' + record.grouped.length + ') ' : '')
        + (channel.label || channel.mode);
      el.addEventListener('click', function(event) {
        if (isGroup) {
          const isAllSameMode = record.grouped.every(groupRecord =>
            groupRecord.mode === channel.mode);
          if (isAllSameMode) {
            tune({
              record: channel,
              alwaysCreate: alwaysCreateReceiverFromEvent(event)
            });
          }
          // TODO: It would make sense to, once the user picks a record from the group, to show that record as the arbitrary-choice-of-label in this widget.
          const menu = new Menu(menuContext, BareFreqList, record.grouped);
          menu.openAt(el);
        } else {
          tune({
            record: channel,
            alwaysCreate: alwaysCreateReceiverFromEvent(event)
          });
        }
      }, false);
      el.my_update = function() {
        el.style.left = view.freqToCSSLeft(freq);
        // TODO: the 2 is a fudge factor
        el.style.bottom = (pickY(freq, freq) - 2) + 'em';
      };
      return el;
    }
    function addBand(record) {
      const el = document.createElement('span');
      el.className = 'freqscale-band';
      el.textContent = record.label || record.mode;
      el.my_update = function () {
        const labelLower = Math.max(record.lowerFreq, lower);
        const labelUpper = Math.min(record.upperFreq, upper);
        el.style.left = view.freqToCSSLeft(labelLower);
        el.style.width = view.freqToCSSLength(labelUpper - labelLower);
        el.style.bottom = pickY(record.lowerFreq, record.upperFreq) + 'em';
      };
      return el;
    }

    const numberCache = new VisibleItemCache(numbers, function (freq) {
      const label = document.createElement('span');
      label.className = 'freqscale-number';
      label.textContent = formatFreqExact(freq);
      label.my_update = function () {
        label.style.left = view.freqToCSSLeft(freq);
      };
      return label;
    });
    const labelCache = new VisibleItemCache(labels, function makeLabel(record) {
      switch (record.type) {
        case 'group':
        case 'channel':
          return addChannel(record);
        case 'band':
          return addBand(record);
      }
    });
    
    const scale_coarse = 10;
    const scale_fine1 = 4;
    const scale_fine2 = 2;
    
    config.scheduler.startNow(function draw() {
      view.n.listen(draw);
      lower = view.leftFreq();
      upper = view.rightFreq();
      
      // TODO: identical to waterfall's use, refactor
      outer.style.marginLeft = view.freqToCSSLeft(lower);
      outer.style.width = view.freqToCSSLength(upper - lower);
      
      // Minimum spacing between labels in Hz
      const MinHzPerLabel = (upper - lower) * labelWidth / view.getTotalPixelWidth();
      
      let step = 1;
      // Widen label spacing exponentially until they have sufficient separation.
      // We could try to calculate the step using logarithms, but floating-point error would be tiresome.
      while (isFinite(step) && step < MinHzPerLabel) {
        step *= scale_coarse;
      }
      // Try to narrow the spacing using two possible fine scales.
      if (step / scale_fine1 > MinHzPerLabel) {
        step /= scale_fine1;
      } else if (step / scale_fine2 > MinHzPerLabel) {
        step /= scale_fine2;
      }
      
      for (let i = lower - mod(lower, step), sanity = 1000;
           sanity > 0 && i <= upper;
           sanity--, i += step) {
        numberCache.add(i).my_update();
      }
      numberCache.flush();
      
      stacker.clear();
      if (!(lower === qLower && upper === qUpper)) {
        query = dataSource.inBand(lower, upper);
        qLower = lower;
        qUpper = upper;
      }
      query.n.listen(draw);
      query.forEach(function (record) {
        const label = labelCache.add(record);
        if (label) label.my_update();
      });
      labelCache.flush();
    });
  }
  
  // A collection/algorithm which allocates integer indexes to provided intervals such that no overlapping intervals have the same index.
  // Intervals are treated as open, unless the endpoints are equal in which case they are treated as closed (TODO: slightly inconsistently but it doesn't matter for the application).
  class IntervalStacker {
    constructor() {
      this._elements = [];
    }
    
    clear() {
      this._elements.length = 0;
    }
    
    // Find index of value in the array, or index to insert at
    _search1(position) {
      // if it turns out to matter, replace this with a binary search
      const array = this._elements;
      let i;
      for (i = 0; i < array.length; i++) {
        if (array[i].key >= position) return i;
      }
      return i;
    }
    
    _ensure1(position, which) {
      const index = this._search1(position);
      const el = this._elements[index];
      if (!(el && el.key === position)) {
        // insert
        const newEl = {key: position, below: Object.create(null), above: Object.create(null)};
        // insert neighbors' info
        const lowerNeighbor = this._elements[index - 1];
        if (lowerNeighbor) {
          Object.keys(lowerNeighbor.above).forEach(function (value) {
            newEl.below[value] = newEl.above[value] = true;
          });
        }
        const upperNeighbor = this._elements[index + 1];
        if (upperNeighbor) {
          Object.keys(upperNeighbor.below).forEach(function (value) {
            newEl.below[value] = newEl.above[value] = true;
          });
        }
      
        // TODO: if it turns out to be worthwhile, use a more efficient insertion
        this._elements.push(newEl);
        this._elements.sort(function (a, b) { return a.key - b.key; });
        const index2 = this._search1(position);
        if (index2 !== index) throw new Error('assumption violated');
        if (this._elements[index].key !== position) { throw new Error('assumption2 violated'); }
      }
      return index;
    }
    
    // Given an interval, which may be zero-length, claim and return the lowest index (>= 0) which has not previously been used for an overlapping interval.
    claim(low, high) {
      // TODO: Optimize by not _storing_ zero-length intervals
      // note must be done in this order to not change the low index
      const lowIndex = this._ensure1(low);
      const highIndex = this._ensure1(high);
      //console.log(this._elements.map(function(x){return x.key;}), lowIndex, highIndex);
    
      for (let value = 0; value < 1000; value++) {
        let free = true;
        for (let i = lowIndex; i <= highIndex; i++) {
          const element = this._elements[i];
          if (i > lowIndex || lowIndex === highIndex) {
            free = free && !element.below[value];
          }
          if (i < highIndex || lowIndex === highIndex) {
            free = free && !element.above[value];
          }
        }
        if (!free) continue;
        for (let i = lowIndex; i <= highIndex; i++) {
          const element = this._elements[i];
          if (i > lowIndex) {
            element.below[value] = true;
          }
          if (i < highIndex) {
            element.above[value] = true;
          }
        }
        return value;
      }
      return null;
    }
  }
  
  // Keep track of elements corresponding to keys and insert/remove as needed
  // maker() returns an element or falsy
  class VisibleItemCache {
    constructor(parent, maker) {
      // TODO: Look into rebuilding this on top of AddKeepDrop.
      const cache = new Map();
      let count = 0;
    
      this.add = function(key) {
        count++;
        let element = cache.get(key);
        if (!element) {
          element = maker(key);
          if (!element) {
            return;
          }
          parent.appendChild(element);
          element.my_cacheKey = key;
          cache.set(key, element);
        }
        if (!element.parentNode) throw new Error('oops');
        element.my_inUse = true;
        return element;
      };
      this.flush = function() {
        const active = parent.childNodes;
        for (let i = active.length - 1; i >= 0; i--) {
          const element = active[i];
          if (element.my_inUse) {
            element.my_inUse = false;
          } else {
            parent.removeChild(element);
            if (!('my_cacheKey' in element)) throw new Error('oops2');
            cache.delete(element.my_cacheKey);
          }
        }
        if (active.length !== count || active.length !== cache.size) throw new Error('oops3');
        count = 0;
      };
    }
  }
  
  class VerticalSplitHandle {
    constructor(config) {
      const target = config.target;
    
      const positioner = this.element = document.createElement('div');
      positioner.classList.add('widget-VerticalSplitHandle-positioner');
      const handle = positioner.appendChild(document.createElement('div'));
      handle.classList.add('widget-VerticalSplitHandle-handle');
    
      config.scheduler.startNow(function draw() {
        positioner.style.bottom = (100 * target.depend(draw)) + '%';
      });
    
      // TODO refactor into something generic that handles x or y and touch-event drags too
      // this code is similar to the ScopePlot drag code
      let dragScreenOrigin = 0;
      let dragValueOrigin = 0;
      let dragScale = 0;
      function drag(event) {
        const draggedTo = dragValueOrigin + (event.clientY - dragScreenOrigin) * dragScale;
        target.set(Math.max(0, Math.min(1, draggedTo)));
        event.stopPropagation();
        event.preventDefault();  // no drag selection
      }
      handle.addEventListener('mousedown', function(event) {
        if (event.button !== 0) return;  // don't react to right-clicks etc.
        dragScreenOrigin = event.clientY;
        dragValueOrigin = target.get();
        dragScale = -1 / positioner.parentElement.offsetHeight;  // kludge
        event.preventDefault();
        document.addEventListener('mousemove', drag, true);
        document.addEventListener('mouseup', function(event) {
          document.removeEventListener('mousemove', drag, true);
        }, true);
      }, false);
    }
  }
  
  return Object.freeze(exports);
});
