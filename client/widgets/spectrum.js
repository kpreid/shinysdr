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
  './basic', 
  './dbui',
  '../database',
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
    numberT,
  } = import_types;
  const {
    ConstantCell,
    DerivedCell,
  } = import_values;
  const {
    alwaysCreateReceiverFromEvent,
    createWidgetExt,
  } = import_widget;
  
  const exports = {};
  
  // Widget for a monitor block
  function Monitor(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      const outerElement = this.element = config.element;
      outerElement.classList.add('widget-Monitor-outer');
      
      const scrollElement = outerElement.appendChild(document.createElement('div'));
      scrollElement.classList.add('widget-Monitor-scrollable');
      scrollElement.id = config.element.id + '-scrollable';
      
      const overlayContainer = scrollElement.appendChild(document.createElement('div'));
      overlayContainer.classList.add('widget-Monitor-scrolled');

      // TODO: shouldn't need to have this declared, should be implied by context
      const isRFSpectrum = config.element.hasAttribute('data-is-rf-spectrum');
      const context = config.context.withSpectrumView(scrollElement, overlayContainer, block, isRFSpectrum);
      
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
        var radioCell = config.radioCell;
        return new DerivedCell(numberT, config.scheduler, function (dirty) {
          return radioCell.depend(dirty).source.depend(dirty).freq.depend(dirty);
        });
      }()) : new ConstantCell(0);
      const freqScaleEl = overlayContainer.appendChild(document.createElement('div'));
      createWidgetExt(context, FreqScale, freqScaleEl, freqCell);
      
      const splitHandleEl = overlayContainer.appendChild(document.createElement('div'));
      createWidgetExt(context, VerticalSplitHandle, splitHandleEl, context.spectrumView.parameters.spectrum_split);
      
      // Not in overlayContainer because it does not scroll.
      // Works with zero height as the top-of-scale reference.
      const verticalScaleEl = outerElement.appendChild(document.createElement('div'));
      createWidgetExt(context, VerticalScale, verticalScaleEl, new ConstantCell('dummy'));

      const parametersEl = outerElement.appendChild(document.createElement('div'));
      createWidgetExt(context, MonitorDetailedOptions, parametersEl, config.target);
      
      // TODO should logically be doing this -- need to support "widget with possibly multiple target elements"
      //addWidget(null, MonitorQuickOptions);
      
      // MonitorDetailedOptions will handle what we don't.
      ignore('*');
      
      // kludge to trigger SpectrumView layout computations after it's added to the DOM :(
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
      addWidget('frame_rate', LogSlider, 'Rate');
      if (block.freq_resolution && block.freq_resolution.set) {  // for audio monitor
        addWidget('freq_resolution', LogSlider, 'Resolution');
      } else {
        ignore('freq_resolution');
      }
      if ('paused' in block) {
        var pausedLabel = getAppend().appendChild(document.createElement('label'));
        var pausedEl = pausedLabel.appendChild(document.createElement('input'));
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
      
      var details = getAppend().appendChild(document.createElement('details'));
      details.appendChild(document.createElement('summary'))
          .appendChild(document.createTextNode('Options'));
      setInsertion(details);
      
      addWidget(config.view.parameters.spectrum_split, LinSlider, 'Split view');
      addWidget(config.view.parameters.spectrum_average, LogSlider, 'Averaging');
      addWidget(config.view.parameters.spectrum_level_min, LinSlider, 'Lowest value');
      addWidget(config.view.parameters.spectrum_level_max, LinSlider, 'Highest value');
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
  function CanvasSpectrumWidget(config, buildGL, build2D) {
    var fftCell = config.target;
    var view = config.view;
    
    var canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
    }
    this.element = canvas;
    view.addClickToTune(canvas);
    canvas.setAttribute('title', '');  // prohibit auto-set title -- TODO: Stop having auto-set titles in the first place
    
    var glOptions = {
      alpha: true,
      depth: false,
      stencil: false,
      antialias: false,
      preserveDrawingBuffer: false
    };
    var gl = getGL(config, canvas, glOptions);
    var ctx2d = canvas.getContext('2d');
    
    var dataHook = function () {}, drawOuter = function () {};
    
    var draw = config.boundedFn(function drawOuterTrampoline() {
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
    draw.scheduler = config.scheduler;
    
    if (gl) (function() {
      function initContext() {
        var drawImpl = buildGL(gl, draw);
        dataHook = drawImpl.newData.bind(drawImpl);
        
        drawOuter = drawImpl.performDraw.bind(drawImpl);
      }
      
      initContext();
      handleContextLoss(canvas, initContext);
    }.call(this)); else if (ctx2d) (function () {
      var drawImpl = build2D(ctx2d, draw);
      dataHook = drawImpl.newData.bind(drawImpl);
      drawOuter = drawImpl.performDraw.bind(drawImpl);
    }.call(this));
    
    function newFFTFrame(bundle) {
      dataHook(bundle);
      draw.scheduler.enqueue(draw);
    }
    newFFTFrame.scheduler = config.scheduler;

    fftCell.subscribe(newFFTFrame);
    draw();
  }
  
  function WaterfallPlot(config) {
    var self = this;
    var view = config.view;
    var avgAlphaCell = view.parameters.spectrum_average;
    
    var minLevelCell = view.parameters.spectrum_level_min;
    var maxLevelCell = view.parameters.spectrum_level_max;
    
    // I have read recommendations that color gradient scales should not involve more than two colors, as certain transitions between colors read as overly significant. However, in this case (1) we are not intending the waterfall chart to be read quantitatively, and (2) we want to have distinguishable small variations across a large dynamic range.
    var colors = [
      [0, 0, 0],
      [0, 0, 255],
      [0, 200, 255],
      [255, 255, 0],
      [255, 0, 0]
    ];
    var colorCountForScale = colors.length - 1;
    var colorCountForIndex = colors.length - 2;
    // value from 0 to 1, writes 0..255 into 4 elements of outArray
    function interpolateColor(value, outArray, base) {
      value *= colorCountForScale;
      var colorIndex = Math.max(0, Math.min(colorCountForIndex, Math.floor(value)));
      var colorInterp1 = value - colorIndex;
      var colorInterp0 = 1 - colorInterp1;
      var color0 = colors[colorIndex];
      var color1 = colors[colorIndex + 1];
      outArray[base    ] = color0[0] * colorInterp0 + color1[0] * colorInterp1;
      outArray[base + 1] = color0[1] * colorInterp0 + color1[1] * colorInterp1;
      outArray[base + 2] = color0[2] * colorInterp0 + color1[2] * colorInterp1;
      outArray[base + 3] = 255;
    }
    
    var backgroundColor = [119, 119, 119];
    var backgroundColorCSS = '#' + backgroundColor.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('');
    var backgroundColorGLSL = 'vec4(' + backgroundColor.map(function (v) { return v / 255; }).join(', ') + ', 1.0)';
    
    // TODO: Instead of hardcoding this, implement dynamic resizing of the history buffers. Punting for now because reallocating the GL textures would be messy.
    var historyCount = Math.max(
      1024,
      config.element.nodeName === 'CANVAS' ? config.element.height : 0);
    
    var canvas;
    var cleared = true;
    
    CanvasSpectrumWidget.call(this, config, buildGL, build2D);
    
    var lvf, rvf, w, h;
    function commonBeforeDraw(scheduledDraw) {
      view.n.listen(scheduledDraw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      w = canvas.width;
      h = canvas.height;
    }
    
    function buildGL(gl, draw) {
      canvas = self.element;

      var useFloatTexture =
        config.clientState.opengl_float.depend(config.rebuildMe) &&
        !!gl.getExtension('OES_texture_float') &&
        !!gl.getExtension('OES_texture_float_linear');

      var shaderPrefix =
        '#define USE_FLOAT_TEXTURE ' + (useFloatTexture ? '1' : '0') + '\n'
        + '#line 1 0\n' + shader_common
        + '\n#line 1 1\n';

      var graphProgram = buildProgram(gl, 
        shaderPrefix + shader_graph_v,
        shaderPrefix + shader_graph_f);
      var graphQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(graphProgram, 'position'));

      var waterfallProgram = buildProgram(gl,
        shaderPrefix + shader_waterfall_v,
        '#define BACKGROUND_COLOR ' + backgroundColorGLSL + '\n'
            + shaderPrefix + shader_waterfall_f);
      var waterfallQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(waterfallProgram, 'position'));
      
      var u_scroll = gl.getUniformLocation(waterfallProgram, 'scroll');
      var u_xTranslate = gl.getUniformLocation(waterfallProgram, 'xTranslate');
      var u_xScale = gl.getUniformLocation(waterfallProgram, 'xScale');
      var u_yScale = gl.getUniformLocation(waterfallProgram, 'yScale');
      var wu_currentFreq = gl.getUniformLocation(waterfallProgram, 'currentFreq');
      var gu_currentFreq = gl.getUniformLocation(graphProgram, 'currentFreq');
      var wu_freqScale = gl.getUniformLocation(waterfallProgram, 'freqScale');
      var gu_freqScale = gl.getUniformLocation(graphProgram, 'freqScale');
      var u_textureRotation = gl.getUniformLocation(waterfallProgram, 'textureRotation');
      
      var fftSize = Math.max(1, config.target.get().length);
      

      var bufferTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      // Ideally we would be linear in S (freq) and nearest in T (time), but that's not an option.
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      var historyFreqTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      var gradientTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      (function() {
        var components = 4;
        // stretch = number of texels to generate per color. If we generate only the minimum and fully rely on hardware gl.LINEAR interpolation then certain pixels in the display tends to flicker as it scrolls, on some GPUs.
        var stretch = 10;
        var limit = (colors.length - 1) * stretch + 1;
        var gradientInit = new Uint8Array(limit * components);
        for (var i = 0; i < limit; i++) {
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
        function computeGradientScale() {
          var gradientInset = 0.5 / (gradientInit.length / components);
          var insetZero = gradientInset;
          var insetScale = 1 - gradientInset * 2;
          var valueZero, valueScale;
          if (useFloatTexture) {
            var minLevel = minLevelCell.depend(computeGradientScale);
            var maxLevel = maxLevelCell.depend(computeGradientScale);
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
        }
        computeGradientScale.scheduler = config.scheduler;
        computeGradientScale();
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
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
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
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
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
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'data'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE0);
      
      // initial state of waterfall program
      gl.useProgram(waterfallProgram);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'data'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE3);
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'gradient'), 3);
      gl.activeTexture(gl.TEXTURE0);

      var slicePtr = 0;

      var freqWriteBuffer = useFloatTexture ? new Float32Array(1) : new Uint8Array(4);
      var intConversionBuffer, intConversionOut;
      
      return {
        newData: function (fftBundle) {
          var buffer = fftBundle[1];
          var bufferCenterFreq = fftBundle[0].freq;
          
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
          gl.uniform1f(u_textureRotation, config.view.isRealFFT() ? 0 : -(0.5 - 0.5/fftSize));

          if (useFloatTexture) {
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
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
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
            // TODO: By doing the level shift at this point, we are locking in the current settings. It would be better to arrange for min/max changes to rescale historical data as well, as it does in float-texture mode (would require keeping the original data as well as the texture contents and recopying it).
            var minLevel = minLevelCell.get();
            var maxLevel = maxLevelCell.get();
            var cscale = 255 / (maxLevel - minLevel);
            for (var i = 0; i < fftSize; i++) {
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
      var scaler = document.createElement('canvas');
      scaler.height = 1;
      var scalerCtx = scaler.getContext('2d');
      if (!scalerCtx) { throw new Error('failed to get headless canvas context'); }
      
      // view parameters recomputed on draw
      var freqToCanvasPixelFactor;
      var xTranslateFreq;
      var pixelWidthOfFFT;
      
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
      var slices = [];
      var slicePtr = 0;
      var lastDrawnLeftVisibleFreq = NaN;
      var lastDrawnRightVisibleFreq = NaN;
      
      // for detecting when to invalidate the averaging buffer
      var lastDrawnCenterFreq = NaN;
      
      // Graph drawing parameters and functions
      // Each variable is updated in draw()
      // This is done so that the functions need not be re-created
      // each frame.
      var gxZero, xScale, xNegBandwidthCoord, xPosBandwidthCoord, yZero, yScale, firstPoint, lastPoint, fftLen, graphDataBuffer;
      function freqToCoord(freq) {
        return (freq - lvf) / (rvf-lvf) * w;
      }
      function graphPath() {
        ctx.beginPath();
        ctx.moveTo(xNegBandwidthCoord - xScale, h + 2);
        for (var i = firstPoint; i <= lastPoint; i++) {
          ctx.lineTo(gxZero + i * xScale, yZero + graphDataBuffer[mod(i, fftLen)] * yScale);
        }
        ctx.lineTo(xPosBandwidthCoord + xScale, h + 2);
      }
      
      // Drawing state for graph
      ctx.lineWidth = 1;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      
      var fillStyle = 'white';
      var strokeStyle = 'white';
      canvas.addEventListener('shinysdr:lifecycleinit', event => {
        fillStyle = getComputedStyle(canvas).fill;
        strokeStyle = getComputedStyle(canvas).stroke;
      }, true);
      
      function changedSplit() {
        cleared = true;
        draw.scheduler.enqueue(draw);
      }
      changedSplit.scheduler = config.scheduler;
      
      var performDraw = config.boundedFn(function performDrawImpl(clearedIn) {
        commonBeforeDraw(draw);
        
        cleared = cleared || clearedIn;
        var viewLVF = view.leftVisibleFreq();
        var viewRVF = view.rightVisibleFreq();
        var viewCenterFreq = view.getCenterFreq();
        freqToCanvasPixelFactor = w / (viewRVF - viewLVF);
        xTranslateFreq = viewLVF - view.leftFreq();
        pixelWidthOfFFT = view.getTotalPixelWidth();

        var split = Math.round(canvas.height * view.parameters.spectrum_split.depend(changedSplit));
        var topOfWaterfall = h - split;
        var heightOfWaterfall = split;

        let buffer, bufferCenterFreq, ibuf;
        if (dataToDraw) {
          buffer = dataToDraw[1];
          bufferCenterFreq = dataToDraw[0].freq;
          var fftLength = buffer.length;

          // can't draw with w=0
          if (w === 0 || fftLength === 0) {
            return;
          }

          // Find slice to write into
          if (slices.length < historyCount) {
            slices.push([ibuf = ctx.createImageData(fftLength, 1), bufferCenterFreq]);
          } else {
            var record = slices[slicePtr];
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
          var xZero = view.isRealFFT() ? 0 : Math.floor(fftLength / 2);
          var cScale = 1 / (maxLevelCell.get() - minLevelCell.get());
          var cZero = 1 - maxLevelCell.get() * cScale;
          var data = ibuf.data;
          for (var x = 0; x < fftLength; x++) {
            var base = x * 4;
            var colorVal = buffer[mod(x + xZero, fftLength)] * cScale + cZero;
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
          for (var i = sliceCount - 1; i >= 0; i--) {
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
          var halfFFTLen = Math.floor(fftLen / 2);
        
          if (halfFFTLen <= 0) {
            // no data yet, don't try to draw
            return;
          }

          var viewCenterFreq = view.getCenterFreq();
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
      });

      var dataToDraw = null;  // TODO this is a data flow kludge
      return {
        newData: function (fftBundle) {
          var buffer = fftBundle[1];
          var bufferCenterFreq = fftBundle[0].freq;
          var len = buffer.length;
          var alpha = avgAlphaCell.get();
          var invAlpha = 1 - alpha;

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
    var view = config.view;
    var radioCell = config.radioCell;
    var others = config.index.implementing('shinysdr.interfaces.IHasFrequency');
    // TODO: That this cell matters here is shared knowledge between this and ReceiverMarks. Should instead be managed by SpectrumView (since it already handles freq coordinates), in the form "get Y position of minLevel".
    var splitCell = view.parameters.spectrum_split;
    var minLevelCell = view.parameters.spectrum_level_min;
    var maxLevelCell = view.parameters.spectrum_level_max;
    
    var canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
      canvas.classList.add('widget-Monitor-overlay');  // TODO over-coupling
    }
    this.element = canvas;
    
    var ctx = canvas.getContext('2d');
    var textOffsetFromTop =
        //ctx.measureText('j').fontBoundingBoxAscent; -- not yet supported
        10 + 2; // default font size is "10px", ignoring effect of baseline
    var textSpacing = 10 + 1;
    
    // Drawing parameters and functions
    // Each variable is updated in draw()
    // This is done so that the functions need not be re-created
    // each frame.
    var w, h, lvf, rvf;
    function freqToCoord(freq) {
      return (freq - lvf) / (rvf-lvf) * w;
    }
    function drawHair(freq) {
      var x = freqToCoord(freq);
      x = Math.floor(x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, ctx.canvas.height);
      ctx.stroke();
    }
    function drawBand(freq1, freq2) {
      var x1 = freqToCoord(freq1);
      var x2 = freqToCoord(freq2);
      ctx.fillRect(x1, 0, x2 - x1, ctx.canvas.height);
    }
    
    var draw = config.boundedFn(function drawImpl() {
      view.n.listen(draw);
      var visibleDevice = radioCell.depend(draw).source_name.depend(draw);
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
      
      var yScale = -(h * (1 - splitCell.depend(draw))) / (maxLevelCell.depend(draw) - minLevelCell.depend(draw));
      var yZero = -maxLevelCell.depend(draw) * yScale;
      
      ctx.strokeStyle = 'gray';
      drawHair(view.getCenterFreq()); // center frequency
      
      others.depend(draw).forEach(function (object) {
        ctx.strokeStyle = 'green';
        drawHair(object.freq.depend(draw));
      });
      
      var receivers = radioCell.depend(draw).receivers.depend(draw);
      receivers._reshapeNotice.listen(draw);
      for (var recKey in receivers) {
        var receiver = receivers[recKey].depend(draw);
        var device_name_now = receiver.device_name.depend(draw);
        var rec_freq_now = receiver.rec_freq.depend(draw);
        
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
        var squelch_threshold_cell = receiver.demodulator.depend(draw).squelch_threshold;
        if (squelch_threshold_cell) {
          var squelchPower = squelch_threshold_cell.depend(draw);
          var squelchL, squelchR, bandwidth;
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
          var squelchPSD = squelchPower - to_dB(bandwidth);
          var squelchY = Math.floor(yZero + squelchPSD * yScale) + 0.5;
          var minSquelchHairWidth = 30;
          if (squelchR - squelchL < minSquelchHairWidth) {
            var squelchMid = (squelchR + squelchL) / 2;
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
          for (var markerFreqStr in band_shape_now.markers) {
            const markerAbsFreq = rec_freq_now + (+markerFreqStr);
            drawHair(markerAbsFreq);
            ctx.fillText(String(band_shape_now.markers[markerFreqStr]), freqToCoord(markerAbsFreq) + 2, textY + textSpacing);
          }
        }
      }
    });
    draw.scheduler = config.scheduler;
    config.scheduler.enqueue(draw);  // must draw after widget inserted to get proper layout
  }
  
  // Waterfall overlay printing amplitude labels.
  function VerticalScale(config) {
    const view = config.view;
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
    
    function draw() {
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
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  
  function FreqScale(config) {
    const view = config.view;
    const dataSource = config.view.isRFSpectrum() ? config.freqDB.groupSameFreq() : emptyDatabase;
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
    function doLayout() {
      // TODO: This is shared knowledge between this, WaterfallPlot, and ReceiverMarks. Should instead be managed by SpectrumView (since it already handles freq coordinates), in the form "get Y position of minLevel".
      outer.style.bottom = (view.parameters.spectrum_split.depend(doLayout) * 100).toFixed(2) + '%';
    }
    doLayout.scheduler = config.scheduler;
    doLayout();
    
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
        var labelLower = Math.max(record.lowerFreq, lower);
        var labelUpper = Math.min(record.upperFreq, upper);
        el.style.left = view.freqToCSSLeft(labelLower);
        el.style.width = view.freqToCSSLength(labelUpper - labelLower);
        el.style.bottom = pickY(record.lowerFreq, record.upperFreq) + 'em';
      };
      return el;
    }

    var numberCache = new VisibleItemCache(numbers, function (freq) {
      var label = document.createElement('span');
      label.className = 'freqscale-number';
      label.textContent = formatFreqExact(freq);
      label.my_update = function () {
        label.style.left = view.freqToCSSLeft(freq);
      };
      return label;
    });
    var labelCache = new VisibleItemCache(labels, function makeLabel(record) {
      switch (record.type) {
        case 'group':
        case 'channel':
          return addChannel(record);
        case 'band':
          return addBand(record);
      }
    });
    
    var scale_coarse = 10;
    var scale_fine1 = 4;
    var scale_fine2 = 2;
    
    var draw = config.boundedFn(function drawImpl() {
      view.n.listen(draw);
      lower = view.leftFreq();
      upper = view.rightFreq();
      
      // TODO: identical to waterfall's use, refactor
      outer.style.marginLeft = view.freqToCSSLeft(lower);
      outer.style.width = view.freqToCSSLength(upper - lower);
      
      // Minimum spacing between labels in Hz
      var MinHzPerLabel = (upper - lower) * labelWidth / view.getTotalPixelWidth();
      
      var step = 1;
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
      
      for (var i = lower - mod(lower, step), sanity = 1000;
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
        var label = labelCache.add(record);
        if (label) label.my_update();
      });
      labelCache.flush();
    });
    draw.scheduler = config.scheduler;
    draw();
  }
  
  // A collection/algorithm which allocates integer indexes to provided intervals such that no overlapping intervals have the same index.
  // Intervals are treated as open, unless the endpoints are equal in which case they are treated as closed (TODO: slightly inconsistently but it doesn't matter for the application).
  function IntervalStacker() {
    this._elements = [];
  }
  IntervalStacker.prototype.clear = function () {
    this._elements.length = 0;
  };
  // Find index of value in the array, or index to insert at
  IntervalStacker.prototype._search1 = function (position) {
    // if it turns out to matter, replace this with a binary search
    var array = this._elements;
    for (var i = 0; i < array.length; i++) {
      if (array[i].key >= position) return i;
    }
    return i;
  };
  IntervalStacker.prototype._ensure1 = function (position, which) {
    var index = this._search1(position);
    var el = this._elements[index];
    if (!(el && el.key === position)) {
      // insert
      var newEl = {key: position, below: Object.create(null), above: Object.create(null)};
      // insert neighbors' info
      var lowerNeighbor = this._elements[index - 1];
      if (lowerNeighbor) {
        Object.keys(lowerNeighbor.above).forEach(function (value) {
          newEl.below[value] = newEl.above[value] = true;
        });
      }
      var upperNeighbor = this._elements[index + 1];
      if (upperNeighbor) {
        Object.keys(upperNeighbor.below).forEach(function (value) {
          newEl.below[value] = newEl.above[value] = true;
        });
      }
      
      // TODO: if it turns out to be worthwhile, use a more efficient insertion
      this._elements.push(newEl);
      this._elements.sort(function (a, b) { return a.key - b.key; });
      var index2 = this._search1(position);
      if (index2 !== index) throw new Error('assumption violated');
      if (this._elements[index].key !== position) { throw new Error('assumption2 violated'); }
    }
    return index;
  };
  // Given an interval, which may be zero-length, claim and return the lowest index (>= 0) which has not previously been used for an overlapping interval.
  IntervalStacker.prototype.claim = function (low, high) {
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
  };
    
  // Keep track of elements corresponding to keys and insert/remove as needed
  // maker() returns an element or falsy
  function VisibleItemCache(parent, maker) {
    // TODO: Look into rebuilding this on top of AddKeepDrop.
    var cache = new Map();
    var count = 0;
    
    this.add = function(key) {
      count++;
      var element = cache.get(key);
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
  
  function VerticalSplitHandle(config) {
    var target = config.target;
    
    var positioner = this.element = document.createElement('div');
    positioner.classList.add('widget-VerticalSplitHandle-positioner');
    var handle = positioner.appendChild(document.createElement('div'));
    handle.classList.add('widget-VerticalSplitHandle-handle');
    
    function draw() {
      positioner.style.bottom = (100 * target.depend(draw)) + '%';
    }
    draw.scheduler = config.scheduler;
    draw();
    
    // TODO refactor into something generic that handles x or y and touch-event drags too
    // this code is similar to the ScopePlot drag code
    var dragScreenOrigin = 0;
    var dragValueOrigin = 0;
    var dragScale = 0;
    function drag(event) {
      var draggedTo = dragValueOrigin + (event.clientY - dragScreenOrigin) * dragScale;
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
  
  return Object.freeze(exports);
});
