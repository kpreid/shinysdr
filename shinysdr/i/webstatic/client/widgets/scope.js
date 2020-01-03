// Copyright 2014, 2015, 2016, 2017, 2018, 2019 Kevin Reid and the ShinySDR contributors
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

// TODO post split, reduce deps here
'use strict';

define([
  './basic',
  '../gltools',
  '../math',
  '../types',
  '../values',
  'text!./scope-v.glsl',
  'text!./scope-f.glsl',
  'text!./scope-pp1.glsl',
  'text!./scope-pp2.glsl',
], (
  import_widgets_basic,
  import_gltools,
  import_math,
  import_types,
  import_values,
  shader_dot_vertex,
  shader_dot_fragment,
  shader_pp1,
  shader_pp2
) => {
  const {
    Block,
    Radio,
  } = import_widgets_basic;
  const {
    PostProcessor,
    buildProgram,
    getGL,
    handleContextLoss,
  } = import_gltools;
  const {
    dB,
    mod,
  } = import_math;
  const {
    EnumT,
    RangeT,
    anyT,
    booleanT,
  } = import_types;
  const {
    DerivedCell,
    StorageCell,
    makeBlock,
  } = import_values;
  
  const exports = {};
  
  function ScopeParameters(storage) {
    function sc(key, type, value) {
      return new StorageCell(sessionStorage, type, value, key);
    }
    return makeBlock({
      paused: sc('paused', booleanT, false),
      axes: sc('axes', new EnumT({
        't,ch1,1': 'AT',
        't,ch2,1': 'BT',
        'ch1,ch2,t': 'XY',
        'ch2,ch1,t': 'XY Rev',
        '1-2,1+2,t': 'Stereo'
      }), 't,ch1,1'),
      trigger_channel: sc('trigger_channel',  new EnumT({
        'ch1': 'A',
        'ch2': 'B'
      }), 'ch1'),
      trigger_level: sc('trigger_level', new RangeT([[-1, 1]], false, false), 0),
      trigger_hysteresis: sc('trigger_hysteresis', new RangeT([[0.001, 0.5]], true, false), 0.01),
      draw_line: sc('draw_line', booleanT, false),  // TODO better name
      history_samples: sc('history_samples', new RangeT([[256, 256], [512, 512], [1024, 1024], [2048, 2048], [4096, 4096], [8192, 8192], [16384, 16384]/*, [32768, 32768], [65536, 65536]*/], true, true), 8192),
      time_scale: sc('time_scale', new RangeT([[128, 16384]], false, false), 1024),
      dot_interpolation: sc('dot_interpolation', new RangeT([[1, 40]], false, true), 10),
      gain: sc('gain', new RangeT([[-50, 50]], false, false), 0),
      intensity: sc('intensity', new RangeT([[0.01, 100.0]], true, false), 1.0),
      focus_falloff: sc('focus_falloff', new RangeT([[0.1, 3]], false, false), 0.8),
      persistence_gamma: sc('persistence_gamma', new RangeT([[1, 100]], true, false), 10.0),
      invgamma: sc('invgamma', new RangeT([[0.5, 2]], false, false), 1.0),
      graticule_intensity: sc('graticule_intensity', new RangeT([[0, 1]], false, false), 0.25),
    });
  }
  exports.ScopeParameters = ScopeParameters;
  
  function multAddVector(ka, a, kb, b) {
    const result = [];
    for (let i = 0; i < a.length; i++) {
      result[i] = ka * a[i] + kb * b[i];
    }
    return result;
  }
  function scaleVector(ka, a) {
    const result = [];
    for (let i = 0; i < a.length; i++) {
      result[i] = ka * a[i];
    }
    return result;
  }
  
  // This does not follow the widget protocol; it is a subsection of ScopePlot's implementation.
  function ScopeGraticule(config, canvas, parameters, projectionCell) {
    const scheduler = config.scheduler;
    const ctx = canvas.getContext('2d');
    
    function draw() {
      const w = canvas.offsetWidth;
      const h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
      } else {
        ctx.clearRect(0, 0, w, h);
      }
      
      const intensity = parameters.graticule_intensity.depend(draw);
      if (intensity <= 0) {
        return;
      }
      
      const hscale = (h / w) / 2;
      const vscale = 1 / 2;
      
      const projectionInfo = projectionCell.depend(draw);
      const projection = projectionInfo.projection;
      function project(x, y, t) {
        const newVector = [0, 0, 0, 0];
        for (let i = 0; i < 4; i++) {
          newVector[i] += projection[i * 4 + 0] * x;
          newVector[i] += projection[i * 4 + 1] * y;
          newVector[i] += projection[i * 4 + 2] * t;
          newVector[i] += projection[i * 4 + 3] * 1;
        }
        //console.log(vector, projection, newVector);
        const projectedX = newVector[0] / newVector[3];
        const projectedY = -newVector[1] / newVector[3];  // flip Y to match GL
        return [(projectedX * hscale + 0.5) * w, (projectedY * vscale + 0.5) * h];
      }

      ctx.strokeStyle = 'rgba(255, 200, 200, ' + intensity.toFixed(4) + ')';  // applies to lines
      ctx.fillStyle = 'rgba(255, 200, 200, ' + (intensity * 2.0).toFixed(4) + ')';  // applies to text
      
      const viewportOuterRadius = Math.hypot(h / 2, w / 2);  // Bounding circle of region we need to paint
      const viewportInnerRadius = Math.min(h / 2, w / 2);  // Box/circle guaranteed to be visible 
      const screenZeroPos = project(0, 0, 0);
      function paintAxis(unitVector, divisions, showLabels, labelScale) {
        const valueSizeOfDivision = Math.hypot(...unitVector) / divisions;
        
        const screenUnitPos = project(...unitVector);
        const projectedUnitVector = multAddVector(1, screenUnitPos, -1, screenZeroPos);
        const projectedUnitLength = Math.hypot(...projectedUnitVector);
        if (projectedUnitLength / divisions <= 2) {
          // Don't draw anything less than 2 pixels per step.
          // TODO: Make this a fade-out instead.
          return;
        }

        const unitVectorsToEdge = viewportOuterRadius / projectedUnitLength;
        const divisionsToEdge = Math.ceil(unitVectorsToEdge * divisions);

        const perpendicularUnit = [-projectedUnitVector[1], projectedUnitVector[0]];
        const perpendicularOffscreen = scaleVector(unitVectorsToEdge, perpendicularUnit);
        
        const textOffset = scaleVector(
          ((viewportInnerRadius - 60/* pixels */) / projectedUnitLength)
          * (unitVector[0] ? -1 : 1),
          perpendicularUnit);

        for (let i = -divisionsToEdge; i <= divisionsToEdge; i++) {
          const vecScale = i / divisions;
          const value = valueSizeOfDivision * i;
          const step = multAddVector(1, screenZeroPos, vecScale, projectedUnitVector);
          
          ctx.beginPath();
          ctx.moveTo(...multAddVector(1, step, -1, perpendicularOffscreen));
          ctx.lineTo(...multAddVector(1, step, 1, perpendicularOffscreen));
          ctx.stroke();
          
          if (showLabels && i % 2 === 0) {
            const labelText = (value * labelScale).toFixed(Math.max(0, Math.round(-Math.log10(valueSizeOfDivision * labelScale))));
            const textWidth = ctx.measureText(labelText).width;
            let [tx, ty] = multAddVector(1, step, 1, textOffset);
            ctx.save();
            ctx.translate(tx, ty);
            const angle = Math.atan2(projectedUnitVector[0], -projectedUnitVector[1]);
            ctx.rotate(angle);
            ctx.fillText(labelText, (angle > Math.PI / 8 ? - textWidth - 5 : 5), 3);
            ctx.restore();
          }
        }
      }
      
      function paintValueAxis(unitVector) {
        const baseExponent = Math.floor(1.5 + 0.1 * parameters.gain.depend(draw));
        paintAxis(unitVector, Math.pow(10, baseExponent), true, 1);
        paintAxis(unitVector, Math.pow(10, (baseExponent - 1)), false, 1);
      }
      function paintTimeAxis() {
        // divide by 2 because the coordinate span is -1 to 1
        const labelScale = parameters.history_samples.depend(draw) / 2;
        const divsScale = labelScale / parameters.time_scale.depend(draw);
        const baseExponent = 4 + Math.floor(Math.log2(divsScale));
        paintAxis([0, 0, 1], Math.pow(2, baseExponent), true, labelScale);
      }
      
      paintValueAxis([1, 0, 0]);
      paintValueAxis([0, 1, 0]);
      paintTimeAxis();
    }
    scheduler.claim(draw);
    
    // TODO: This is a kludge and will never get properly removed; we need a general solution for this and other pixel-layout-dependent stuff
    window.addEventListener('resize', event => {
      // immediate to ensure smooth animation
      scheduler.callNow(draw);
    });
    
    scheduler.enqueue(draw);
  }
  
  function ScopePlot(config) {
    const scheduler = config.scheduler;
    const scopeAndParams = config.target.depend(config.rebuildMe);
    const parameters = scopeAndParams.parameters.depend(config.rebuildMe);
    const scopeCell = scopeAndParams.scope;
    
    const container = config.element;
    this.element = container;
    const canvas = container.appendChild(document.createElement('canvas'));
    canvas.classList.add('widget-ScopePlot-data');
    
    const graticuleCanvas = container.appendChild(document.createElement('canvas'));
    graticuleCanvas.classList.add('widget-ScopePlot-graticule');
    
    const fakeDataMode = false;
    
    const numberOfChannels = 2;  // not directly changeable; this is for documentation
    
    const kernelRadius = 10;

    const gl = getGL(config, canvas, {
      powerPreference: 'high-performance',
      alpha: false,
      depth: false,
      stencil: false,
      antialias: false,
      preserveDrawingBuffer: false
    });
    
    if (!( gl.getExtension('OES_texture_float')
        && gl.getExtension('OES_texture_float_linear')
        && gl.getParameter(gl.MAX_VERTEX_TEXTURE_IMAGE_UNITS) >= 1)) {
      // TODO: Add a way to provide a nicer-formatted error message.
      throw new Error('Required WebGL feastures not available.');
    }
    
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.FUNC_ADD, gl.FUNC_ADD);
    gl.blendFunc(gl.ONE, gl.ONE);
    
    const scopeDataTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, scopeDataTexture);
    // TODO: Implement more accurate than linear filtering in the shader, and set this to NEAREST.
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    // Texel index into which to write the newest data.
    let circularBufferPtr;
    
    // These are initialized by configureDataBuffer.
    let numberOfSamples;
    let numberOfDots;
    let interpScale;
    const timeBuffer = gl.createBuffer();
    // scopeDataArray is a copy of the texture contents, not used for drawing but is used to calculate the trigger position.
    let scopeDataArray = new Float32Array(0);
    
    // Contents are indexes like circularBufferPtr, points at where we triggered, is itself a circular buffer
    const NO_TRIGGER = -1;
    const triggerSampleIndexes = new Int32Array(20);
    triggerSampleIndexes.fill(NO_TRIGGER);
    let triggerAddPtr = 0;
    let triggerInhibition = 0;
    
    // Takes accumulated dots and applies horizontal kernel.
    const postProcessor1 = new PostProcessor(gl, {
      // This is not ideal: since we just want to accumulate dots, the least wasteful would be a 16 or 32-bit integer single-component (LUMINANCE) buffer. But neither larger than 8-bit integers nor LUMINANCE are allowed by WebGL for a framebuffer texture.
      format: gl.RGBA,
      type: gl.FLOAT,
      fragmentShader: 'const int radius = ' + kernelRadius + '; ' + shader_pp1
    });
    
    const postProcessor2 = new PostProcessor(gl, {
      format: gl.RGBA,
      type: gl.FLOAT,
      fragmentShader: 'const int radius = ' + kernelRadius + '; ' + shader_pp2
    });
        
    const program = buildProgram(gl, shader_dot_vertex, shader_dot_fragment);
    const att_relativeTime = gl.getAttribLocation(program, 'relativeTime');
    gl.uniform1i(gl.getUniformLocation(program, 'scopeData'), 0);  // texture
    
    scheduler.startNow(function configureDataBuffer() {
      // TODO: Once we have proper non-linear interpolation, we will want to interpolate even if drawing lines.
      interpScale =
          parameters.draw_line.depend(configureDataBuffer) ? 1 :
          parameters.dot_interpolation.depend(configureDataBuffer);
      numberOfSamples = parameters.history_samples.depend(configureDataBuffer);
      numberOfDots = (numberOfSamples - 1) * interpScale + 1;  // avoids having any end-to-beginning wraparound points
      
      circularBufferPtr = 0;  // just reset
      scopeDataArray = new Float32Array(numberOfSamples * numberOfChannels);
    
      let fakeData;
      if (fakeDataMode) {
        fakeData = new Float32Array(numberOfSamples * numberOfChannels);
        for (let i = 0; i < fakeData.length; i += numberOfChannels) {
          // a noticeably 'polygonal' signal when linearly interpolated
          fakeData[i] = Math.sin(i / 3);
          fakeData[i+1] = Math.cos(i / 3);
        }
      } else {
        fakeData = null;
      }
  
      gl.bindTexture(gl.TEXTURE_2D, scopeDataTexture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0, // level
        gl.LUMINANCE_ALPHA, // internalformat -- we want numberOfChannels components
        numberOfSamples, // width -- TODO use a squarer texture to hit limits later
        1, // height
        0, // border
        gl.LUMINANCE_ALPHA, // format
        gl.FLOAT, // type
        fakeData);  // pixels -- will be initialized later
      gl.bindTexture(gl.TEXTURE_2D, null);
    
      gl.bindBuffer(gl.ARRAY_BUFFER, timeBuffer);
      const timeIndexes = new Float32Array(numberOfDots);
      for (let i = 0; i < numberOfDots; i++) {
        timeIndexes[i] = (i + 0.5) / numberOfDots;
      }
      gl.bufferData(gl.ARRAY_BUFFER, timeIndexes, gl.STATIC_DRAW);
      
      gl.uniform1f(gl.getUniformLocation(program, 'interpStep'),
        // This is the size of a "one-dot" step in scopeDataTexture's x coordinate (i.e. interpScale * interpStep is one texel) used for implementing interpolation.
        1 / (numberOfSamples * numberOfDots));
    });
      
    handleContextLoss(canvas, config.rebuildMe);
    
    let projectionCell = new DerivedCell(/* Float32Array */ anyT, scheduler, dirty => {
      const gainLin = dB(parameters.gain.depend(dirty));
      const tAxisStretch = parameters.history_samples.depend(dirty) / parameters.time_scale.depend(dirty);
      
      const projection = new Float32Array([
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 1
      ]);
      let usesTrigger = false;
      String(parameters.axes.depend(dirty)).split(',').forEach((axisSpec, index) => {
        let v0 = 0, v1 = 0, v2 = 0, v3 = 0;
        switch (axisSpec.trim()) {
          case '1': v3 = 1; break;
          case 'ch1': v0 = gainLin; break;
          case 'ch2': v1 = gainLin; break;
          case 't': 
            v2 = index === 2 ? 1 : tAxisStretch;
            if (index !== 2) usesTrigger = true;  // TODO kludgy
          break;
          case '1+2': v0 = gainLin; v1 = gainLin; break;
          case '1-2': v0 = gainLin; v1 = -gainLin; break;
          default:
            console.warn('bad axis specification', JSON.stringify(axisSpec));
            break;
        }
        projection[index * 4 + 0] += v0;
        projection[index * 4 + 1] += v1;
        projection[index * 4 + 2] += v2;
        projection[index * 4 + 3] += v3;
      });
      if (false) {
        console.log(projection.slice(0, 4));
        console.log(projection.slice(4, 8));
        console.log(projection.slice(8, 12));
        console.log('---', usesTrigger);
      }
      return {
        projection: projection,
        usesTrigger: usesTrigger
      };
    });
    
    // Assumes gl.useProgram(program).
    const setProjection = (() => {
      const dynamicProjectionBuffer = new Float32Array(4 * 4);
      return function setProjection(staticProjection, aspect, triggerRelativeTime, zOffset) {
        dynamicProjectionBuffer.set(staticProjection);
        // multiply with the trigger translation
        //  TODO use real matrix manipulation functions
        for (let i = 0; i < 4; i++) {
          dynamicProjectionBuffer[i * 4 + 3] -= dynamicProjectionBuffer[i * 4 + 2] * (triggerRelativeTime * 2 - 1);
        }
        // apply aspect ratio -- TODO conditional on axis type
        for (let i = 0; i < 4; i++) {
          dynamicProjectionBuffer[i] /= aspect;
        }
        // apply z offset
        dynamicProjectionBuffer[2 * 4 + 3] += zOffset;
        
        gl.uniformMatrix4fv(gl.getUniformLocation(program, 'projection'), false, dynamicProjectionBuffer);
      };
    })();
    
    function draw() {
      let w, h;
      // Fit current layout
      w = canvas.offsetWidth;
      h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
        postProcessor1.setSize(w, h);
        postProcessor2.setSize(w, h);
      }
      // TODO better viewport / axis scaling rule
      // TODO: use drawingBufferWidth etc.
      const aspect = w / h;
      gl.viewport(0, 0, w, h);

      let ppKernel;
      {
        const focus_falloff = parameters.focus_falloff.depend(draw);
        const diameter = kernelRadius * 2 + 1;
        ppKernel = new Float32Array(diameter);
        let sum = 0;
        for (let kx = 0; kx < diameter; kx++) {
          const r = Math.abs(kx - kernelRadius);
          sum += (ppKernel[kx] = Math.exp(-focus_falloff * r * r));
        }
        // normalize kernel
        for (let kx = 0; kx < diameter; kx++) {
          ppKernel[kx] /= sum;
        }
      }
      
      const drawLine = parameters.draw_line.depend(draw);
      const compensatedIntensity = drawLine
          ? parameters.intensity.depend(draw) / 10  // fudge factor, not applicable to all cases
          : parameters.intensity.depend(draw) / interpScale;
      
      gl.useProgram(postProcessor1.getProgram());
      gl.uniform1fv(gl.getUniformLocation(postProcessor1.getProgram(), 'kernel'), ppKernel);
      
      gl.useProgram(postProcessor2.getProgram());
      gl.uniform1fv(gl.getUniformLocation(postProcessor2.getProgram(), 'kernel'), ppKernel);
      gl.uniform1f(gl.getUniformLocation(postProcessor2.getProgram(), 'intensity'), compensatedIntensity);
      gl.uniform1f(gl.getUniformLocation(postProcessor2.getProgram(), 'invgamma'), parameters.invgamma.depend(draw));
      
      gl.useProgram(program);
      gl.uniform1f(gl.getUniformLocation(program, 'persistence_gamma'), parameters.persistence_gamma.depend(draw));
      gl.uniform1f(gl.getUniformLocation(program, 'bufferCutPoint'), circularBufferPtr / numberOfSamples);
      
      // Begin frame and set up attributes for drawing sample points.
      postProcessor1.beginInput();
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enableVertexAttribArray(att_relativeTime);
      gl.bindBuffer(gl.ARRAY_BUFFER, timeBuffer);
      gl.vertexAttribPointer(
        att_relativeTime,
        1, // components
        gl.FLOAT,
        false,
        0,
        0);
      gl.bindTexture(gl.TEXTURE_2D, scopeDataTexture);
      
      const staticProjectionInfo = projectionCell.depend(draw);
      const primitive = drawLine ? gl.LINE_STRIP : gl.POINTS;
      let hadAnyTrigger = false;
      if (staticProjectionInfo.usesTrigger) {
        for (let i = triggerSampleIndexes.length - 1; i >= 0; i--) {
          const index = triggerSampleIndexes[mod(triggerAddPtr + i, triggerSampleIndexes.length)];
          if (index !== NO_TRIGGER) {
            const relativeTime = mod((index - circularBufferPtr) / numberOfSamples, 1);
            setProjection(staticProjectionInfo.projection, aspect, relativeTime, i / triggerSampleIndexes.length - 1);
            // TODO: Only draw a suitable surrounding range of points.
            gl.drawArrays(primitive, 0, numberOfDots);
            hadAnyTrigger = true;
          }
        }
      }
      if (!hadAnyTrigger) {
        setProjection(staticProjectionInfo.projection, aspect, 0.5, 0.0);
        gl.drawArrays(primitive, 0, numberOfDots);
      }
      
      // End sample point drawing.
      gl.bindTexture(gl.TEXTURE_2D, null);
      postProcessor1.endInput();
      
      postProcessor2.beginInput();
        gl.clear(gl.COLOR_BUFFER_BIT);
        postProcessor1.drawOutput();
      postProcessor2.endInput();
      
      postProcessor2.drawOutput();
    }
    config.scheduler.claim(draw);
    
    function contiguousWrite(array) {
      const samples = array.length / numberOfChannels;
      gl.texSubImage2D(
          gl.TEXTURE_2D,
          0, // level
          circularBufferPtr, // xoffset
          0, // yoffset
          samples,  // width
          1,  // height
          gl.LUMINANCE_ALPHA,
          gl.FLOAT,
          array);
      scopeDataArray.set(array, circularBufferPtr * numberOfChannels);
      circularBufferPtr = mod(circularBufferPtr + samples, numberOfSamples);
    }
    
    function newScopeFrame(bundle) {
      if (fakeDataMode || parameters.paused.get()) {
        return;
      }
      
      const newDataArray = bundle[1];
      if (newDataArray.length % numberOfChannels !== 0) {
        // We expect paired IQ/XY samples.
        console.error('Scope data not of even length!');
        return;
      }
      
      // Save range of new data for trigger calculations
      const newDataStart = circularBufferPtr;
      const newDataSampleCount = newDataArray.length / numberOfChannels;
      const newDataEnd = circularBufferPtr + newDataSampleCount;
      
      // Write new data into scopeDataTexture and scopeDataArray.
      gl.bindTexture(gl.TEXTURE_2D, scopeDataTexture);
      const remainingSpace = numberOfSamples * numberOfChannels - circularBufferPtr;
      if (newDataSampleCount > numberOfSamples) {
        // chunk is bigger than our circular buffer, so we must drop some
        circularBufferPtr = 0;
        contiguousWrite(newDataArray.subarray(0, numberOfSamples));
      } else if (remainingSpace < newDataArray.length) {
        // write to end and loop back to beginning
        contiguousWrite(newDataArray.subarray(0, remainingSpace));
        //if (circularBufferPtr !== 0) { throw new Error('oops'); }
        contiguousWrite(newDataArray.subarray(remainingSpace));
      } else {
        contiguousWrite(newDataArray);
      }
      gl.bindTexture(gl.TEXTURE_2D, null);
      
      let nadd = 0;
      let nrem = 0;
      
      // Erase trigger indexes pointing into old samples we are about to overwrite
      for (let i = 0; i < triggerSampleIndexes.length; i++) {
        const tsi = triggerSampleIndexes[i];
        if (tsi !== NO_TRIGGER && mod(tsi - newDataStart, numberOfSamples) + newDataStart < newDataEnd) {
          triggerSampleIndexes[i] = NO_TRIGGER;
          nrem++;
        }
      }
      
      // calculate new trigger points
      let triggerChannel;
      switch (parameters.trigger_channel.get()) {
        case 'ch1':
          triggerChannel = 0;
          break;
        /* case 'ch2': */ default:
          triggerChannel = 1;
          break;
      }
      const triggerLevel = parameters.trigger_level.get();
      const triggerHysteresis = parameters.trigger_hysteresis.get();
      for (let i = newDataStart; i < newDataEnd; i++) {  // note: i may > numberOfSamples
        if (triggerInhibition > 0) {
          triggerInhibition--;
        } else {
          triggerInhibition = 0;
          const previousSampleCh1 = scopeDataArray[mod(i - 1, numberOfSamples) * numberOfChannels + triggerChannel];
          const thisSampleCh1 = scopeDataArray[mod(i, numberOfSamples) * numberOfChannels + triggerChannel];
          if (previousSampleCh1 <= triggerLevel
              && thisSampleCh1 > triggerLevel
              && (thisSampleCh1 - previousSampleCh1) > triggerHysteresis) {
            triggerSampleIndexes[triggerAddPtr] = mod(i, numberOfSamples);
            triggerAddPtr = mod(triggerAddPtr + 1, triggerSampleIndexes.length);
            triggerInhibition += Math.min(numberOfSamples, parameters.time_scale.get());
            nadd++;
          }
        }
      }
      //if (nadd > 0 || nrem > 0) console.log(nadd, nrem);
      
      draw.scheduler.enqueue(draw);
    }
    config.scheduler.claim(newScopeFrame);

    new ScopeGraticule(config, graticuleCanvas, parameters, projectionCell);

    scopeCell.subscribe(newScopeFrame);
    draw();
  }
  exports.ScopePlot = ScopePlot;
  
  function ScopeControls(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      const container = getAppend();
      function makeContainer(title) {
        const header = container.appendChild(document.createElement('div'));
        header.className = 'panel frame-controls';
        header.appendChild(document.createTextNode(title));
        const subcontainer = container.appendChild(document.createElement('div'));
        subcontainer.className = 'panel frame';
        setInsertion(subcontainer);
      }
      
      // TODO: Consider breaking up the parameters object itself up instead of hardcoding these groupings. Unclear whether that makes sense or not.
      
      makeContainer('View');
      addWidget('axes', Radio);
      
      makeContainer('Signal');
      addWidget('gain');
      
      makeContainer('Time');
      addWidget('history_samples');
      addWidget('time_scale');
      addWidget('dot_interpolation');

      makeContainer('Trigger');
      addWidget('trigger_channel');
      addWidget('trigger_level');
      addWidget('trigger_hysteresis');

      makeContainer('Rendering');
      addWidget('intensity');
      addWidget('focus_falloff');
      addWidget('persistence_gamma');
      addWidget('invgamma');
      addWidget('draw_line');
      
      setInsertion(container);
    });
  }
  exports.ScopeControls = ScopeControls;
  
  return Object.freeze(exports);
});
