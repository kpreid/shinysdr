// Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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
  '../audio/bufferer',
  '../events',
  '../types',
  '../values',
], (
  import_audio_bufferer,
  import_events,
  import_types,
  import_values
) => {
  const {
    delayToBufferSize,
  } = import_audio_bufferer;
  const {
    Neverfier,
  } = import_events;
  const {
    BulkDataT,
    anyT,
    booleanT,
    numberT,
  } = import_types;
  const {
    ConstantCell,
    FakeBulkDataCell,
    LocalCell,
  } = import_values;

  const exports = {};
  
  // TODO adapter should have gui settable parameters and include these
  // These options create a less meaningful and more 'decorative' result.
  const FREQ_ADJ = false;    // Compensate for typical frequency dependence in music so peaks are equal.
  const TIME_ADJ = false;    // Subtract median amplitude; hides strong beats.
  
  const SUPPORTED_DISPLAY_SIZE = (() => {
    // Quick fix -- TODO: Plumb this up somehow so that we can adapt interactively instead of having to create a dummy context and proceed up front. This will also avoid depending on graphics stuff from the "lower" layers.
    const gl = document.createElement('canvas').getContext('webgl');
    if (!gl) return 4096;  // TODO: better 2D canvas assumptions
    try {
      return gl.getParameter(gl.MAX_TEXTURE_SIZE);
    } finally {
      const ext = gl.getExtension('WEBGL_lose_context');
      if (ext) ext.loseContext();
    }
  })();
  
  const WANTED_FFT_SIZE = Math.min(16384, SUPPORTED_DISPLAY_SIZE * 2);
  
  // Takes frequency data from an AnalyserNode and provides an interface like a MonitorSink
  function AudioAnalyserAdapter(scheduler, audioContext) {
    // Construct analyser.
    const analyserNode = audioContext.createAnalyser();
    analyserNode.smoothingTimeConstant = 0;
    try {
      analyserNode.fftSize = WANTED_FFT_SIZE;
    } catch (e) {
      // Safari as of version 10.1 does not support larger sizest than this, despite the specification limit being 32768.
      analyserNode.fftSize = Math.min(2048, SUPPORTED_DISPLAY_SIZE * 2);
    }
    if (false) {
      console.log('AudioAnalyserAdapter: FFT size', analyserNode.fftSize,
          'bin count', analyserNode.frequencyBinCount);
    }
    
    // Used to have the option to reduce this to remove empty high-freq bins from the view. Leaving that out for now.
    const length = analyserNode.frequencyBinCount;
    
    // Constant parameters for MonitorSink interface
    const effectiveSampleRate = analyserNode.context.sampleRate * (length / analyserNode.frequencyBinCount);
    const info = Object.freeze({freq: 0, rate: effectiveSampleRate});
    
    // State
    const fftBuffer = new Float32Array(length);
    let isScheduled = false;
    const pausedCell = this.paused = new LocalCell(booleanT, true);
    
    const outputCell = this.fft = new FakeBulkDataCell(
      new BulkDataT('dff', 'b'),  // TODO BulkDataT really isn't properly involved here -- there is no binary format -- so the architecture is wrong
      [info, fftBuffer],
      maybeScheduleUpdate);
    
    function update() {
      isScheduled = false;
      analyserNode.getFloatFrequencyData(fftBuffer);
    
      let absolute_adj;
      if (TIME_ADJ) {
        const medianBuffer = Array.prototype.slice.call(fftBuffer);
        medianBuffer.sort(function(a, b) {return a - b; });
        absolute_adj = -100 - medianBuffer[length / 2];
      } else {
        absolute_adj = 0;
      }
      
      let freq_adj;
      if (FREQ_ADJ) {
        freq_adj = 1;
      } else {
        freq_adj = 0;
      }
      
      for (let i = 0; i < length; i++) {
        fftBuffer[i] = fftBuffer[i] + absolute_adj + freq_adj * Math.pow(i, 0.5);
      }
      
      maybeScheduleUpdate();
      outputCell._update([info, fftBuffer]);  // fresh array, same contents, good enough.
    }
    
    function maybeScheduleUpdate() {
      if (!isScheduled && outputCell._hasSubscribers()) {
        if (pausedCell.get()) {
          pausedCell.n.listen(maybeScheduleUpdate);
        } else {
          isScheduled = true;
          // A basic rAF loop seems to be about the right rate to poll the AnalyserNode for new data. Using the Scheduler instead would try to run faster.
          requestAnimationFrame(update);
        }
      }
    }
    scheduler.claim(maybeScheduleUpdate);
    
    // This interface allows us to in the future have per-channel analysers without requiring the caller to deal with that.
    Object.defineProperty(this, 'connectFrom', {value: function (inputNode) {
      inputNode.connect(analyserNode);
    }});
    Object.defineProperty(this, 'disconnectFrom', {value: function (inputNode) {
      inputNode.disconnect(analyserNode);
    }});
    
    // Other elements expected by Monitor widget
    Object.defineProperty(this, '_implements_shinysdr.i.blocks.IMonitor', {enumerable: false});
    this.freq_resolution = new ConstantCell(length);
    this.signal_type = new ConstantCell({kind: 'USB', sample_rate: effectiveSampleRate}, anyT);
  }
  Object.defineProperty(AudioAnalyserAdapter.prototype, '_reshapeNotice', {value: new Neverfier()});
  Object.freeze(AudioAnalyserAdapter.prototype);
  Object.freeze(AudioAnalyserAdapter);
  exports.AudioAnalyserAdapter = AudioAnalyserAdapter;
  
  // Extract time-domain samples from an audio context suitable for the ScopePlot widget.
  // This is not based on AnalyserNode because AnalyserNode is single-channel and using multiple AnalyserNodes will not give time-alignment (TODO verify that).
  function AudioScopeAdapter(scheduler, audioContext) {
    // Parameters
    const bufferSize = delayToBufferSize(audioContext.sampleRate, 1/60);
    console.log('AudioScopeAdapter buffer size at', audioContext.sampleRate, 'Hz is', bufferSize);
    const nChannels = 2;
    
    // Buffers
    // We don't want to be constantly allocating new buffers or having an unbounded queue size, but we also don't want to require prompt efficient processing inside the audio callback. Therefore, have a circular buffer of buffers to hand off.
    const bufferBuffer = [1, 2, 3, 4].map(unused => {
      // TODO: It would be nice to have something reusable here. However, this is different from events.Notifier in that it doesn't require repeated re-subscription.
      let notifyScheduled = false;
      const notifyFn = () => {
        notifyScheduled = false;
        sendBuffer(copyBufferSet);
      };
      const copyBufferSet = {
        copyL: new Float32Array(bufferSize),
        copyR: new Float32Array(bufferSize),
        outputBuffer: new Float32Array(bufferSize * nChannels),
        notify: () => {
          if (!notifyScheduled) {
            notifyScheduled = true;
            requestAnimationFrame(notifyFn);
          }
        }
      };
      return copyBufferSet;
    });
    let bufferBufferPtr = 0;
    
    const captureProcessor = audioContext.createScriptProcessor(bufferSize, nChannels, nChannels);
    captureProcessor.onaudioprocess = function scopeCallback(event) {
      const inputBuffer = event.inputBuffer;
      const cellBuffer = bufferBuffer[bufferBufferPtr];
      bufferBufferPtr = (bufferBufferPtr + 1) % bufferBuffer.length;
      inputBuffer.copyFromChannel(cellBuffer.copyL, 0);
      inputBuffer.copyFromChannel(cellBuffer.copyR, 1);
      cellBuffer.notify();
    };
    captureProcessor.connect(audioContext.destination);
    
    // Output cell
    const info = Object.freeze({});  // dummy
    const outputCell = this.scope = new FakeBulkDataCell(
      new BulkDataT('d', 'f'),  // TODO BulkDataT really isn't properly involved here -- there is no binary format -- so the architecture is wrong
      [info, new Float32Array(bufferSize)]);
    
    function sendBuffer(copyBufferSet) {
      // Do this processing now rather than in callback to minimize work done in audio callback.
      const copyL = copyBufferSet.copyL;
      const copyR = copyBufferSet.copyR;
      const outputBuffer = copyBufferSet.outputBuffer;
      for (let i = 0; i < bufferSize; i++) {
        outputBuffer[i * 2] = copyL[i];
        outputBuffer[i * 2 + 1] = copyR[i];
      }
      
      outputCell._update([info, outputBuffer]);
    }
    
    // TODO: Also disconnect processor when nobody's subscribed.
    
    Object.defineProperty(this, 'connectFrom', {value: function (inputNode) {
      inputNode.connect(captureProcessor);
    }});
    Object.defineProperty(this, 'disconnectFrom', {value: function (inputNode) {
      inputNode.disconnect(captureProcessor);
    }});
    
    // Other elements expected by Monitor widget
    Object.defineProperty(this, '_implements_shinysdr.i.blocks.IMonitor', {enumerable: false});
    this.freq_resolution = new ConstantCell(length, numberT);
    this.signal_type = new ConstantCell({kind: 'USB', sample_rate: audioContext.sampleRate}, anyT);
  }
  Object.defineProperty(AudioScopeAdapter.prototype, '_reshapeNotice', {value: new Neverfier()});
  Object.freeze(AudioScopeAdapter.prototype);
  Object.freeze(AudioScopeAdapter);
  exports.AudioScopeAdapter = AudioScopeAdapter;
  
  return Object.freeze(exports);
});
