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

// Implementation of streaming audio buffering. Can be used with AudioWorklet or ScriptProcessor.

/* globals AudioWorkletProcessor, registerProcessor, sampleRate */

'use strict';

(function () {
  const exports = {};
  
  const EMPTY_CHUNK = Object.freeze([]);
   
  // Accepts incoming samples (from the network) and requests for samples (from the local audio context).
  // Post-construction communication is all through a MessagePort to allow use in a worker.
  // Port message protocol incoming:
  //   ['acceptSamples', <Float32Array>]
  //   ['setFormat', newNumAudioChannels, newStreamSampleRate]
  //   ['resetFill']
  // Outgoing:
  //   ['setStatus', {bufferedFraction, targetSeconds, queueNotEmpty}]
  //   ['error', <string>]
  function AudioBuffererImpl(nativeSampleRate, messagePort) {
    const rxBufferSize = delayToBufferSize(nativeSampleRate, 0.15);
    
    // Stream parameters
    let numAudioChannels = null;
    let streamSampleRate = null;
    
    // Queue size management
    // The queue should be large to avoid underruns due to bursty processing/delivery.
    // The queue should be small to minimize latency.
    let targetQueueSize = Math.round(0.2 * nativeSampleRate);  // units: sample count
    // Circular buffer of queue fullness history.
    let queueHistory = new Int32Array(200);
    let queueHistoryPtr = 0;
    
    // Size of data chunks we get from network and the audio context wants, used for tuning our margins
    let inputChunkSizeSample = 0;
    let outputChunkSizeSample = 0;
    
    // Queue of chunks
    let queue = [];
    let queueSampleCount = 0;
    
    // Chunk currently being copied into audio node buffer
    let audioStreamChunk = EMPTY_CHUNK;
    let chunkIndex = 0;
    let prevUnderrun = 0;
    
    // Placeholder sample value
    let fillL = 0;
    let fillR = 0;
    
    function updateStatus() {
      // TODO: I think we are mixing up per-channel and total samples here  (queueSampleCount counts both channels individually)
      const bufferedSeconds = (queueSampleCount + audioStreamChunk.length - chunkIndex) / nativeSampleRate;
      const targetSeconds = targetQueueSize / nativeSampleRate;
      const bufferedFraction = bufferedSeconds / targetSeconds;
      const queueNotEmpty = queue.length > 0 || audioStreamChunk !== EMPTY_CHUNK;
      messagePort.postMessage(['setStatus', {bufferedFraction, targetSeconds, queueNotEmpty}]);
    }
    
    function updateParameters() {
      // Update queue size management
      queueHistory[queueHistoryPtr] = queueSampleCount;
      queueHistoryPtr = (queueHistoryPtr + 1) % queueHistory.length;
      const least = Math.min.apply(undefined, queueHistory);
      const most = Math.max.apply(undefined, queueHistory);
      targetQueueSize = Math.max(1, Math.round(
        ((most - least) + Math.max(inputChunkSizeSample, outputChunkSizeSample))));
      
      updateStatus();
    }
    
    messagePort.onmessage = new MessageHandlerAdapter({
      setFormat(newNumAudioChannels, newStreamSampleRate) {
        numAudioChannels = newNumAudioChannels;
        streamSampleRate = newStreamSampleRate;
      },
      
      resetFill() {
        fillL = fillR = 0;
      },
      
      acceptSamples(wsDataValue) {
        if (streamSampleRate === null) throw new Error('not initialized');
      
        // Don't buffer huge amounts of data.
        if (queue.length > 100) {
          console.log('Extreme audio overrun.');  // TODO send a proper feedback message
          queue.length = 0;
          queueSampleCount = 0;
          return;
        }
        
        // Read in floats and zero-stuff.
        const interpolation = nativeSampleRate / streamSampleRate;  // TODO fail if not integer
        const streamRateChunk = new Float32Array(wsDataValue);
        const nSamples = streamRateChunk.length / numAudioChannels;
        
        // Insert zeros to change sample rate, e.g. with interpolation = 3,
        //     [l r l r l r] becomes [l r 0 0 0 0 l r 0 0 0 0 l r 0 0 0 0]
        const nativeRateChunk = new Float32Array(nSamples * numAudioChannels * interpolation);  // TODO: With partial-chunk processing we could avoid allocating new buffers all the time -- use a circular buffer? (But we can't be allocation-free anyway since the WebSocket isn't.)
        const rightChannelIndex = numAudioChannels - 1;
        const step = interpolation * numAudioChannels;
        for (let i = 0; i < nSamples; i++) {
          nativeRateChunk[i * step] = streamRateChunk[i * numAudioChannels];
          nativeRateChunk[i * step + rightChannelIndex] = streamRateChunk[i * numAudioChannels + rightChannelIndex];
        }
    
        queue.push(nativeRateChunk);
        queueSampleCount += nativeRateChunk.length;
        inputChunkSizeSample = nativeRateChunk.length;
        updateParameters();
      },
    });

    this.produceSamples = function(l /* Float32Array */, r /* Float32Array */) {
      if (l.length !== r.length) throw new Error('bad arrays');
      const outputChunkSize = l.length;
      outputChunkSizeSample = outputChunkSize;
      
      if (numAudioChannels === null) {
        // not initialized yet, produce zeros
        for (let j = 0; j < outputChunkSize; j++) {
          l[j] = fillL;
          r[j] = fillR;
        }
        return;
      }
      const rightChannelIndex = numAudioChannels - 1;
      
      let totalOverrun = 0;
      
      let j;
      for (j = 0;
           chunkIndex < audioStreamChunk.length && j < outputChunkSize;
           chunkIndex += numAudioChannels, j++) {
        l[j] = audioStreamChunk[chunkIndex];
        r[j] = audioStreamChunk[chunkIndex + rightChannelIndex];
      }
      while (j < outputChunkSize) {
        // Get next chunk
        // TODO: shift() is expensive
        audioStreamChunk = queue.shift() || EMPTY_CHUNK;
        queueSampleCount -= audioStreamChunk.length;
        chunkIndex = 0;
        if (audioStreamChunk.length === 0) {
          break;
        }
        for (;
             chunkIndex < audioStreamChunk.length && j < outputChunkSize;
             chunkIndex += numAudioChannels, j++) {
          l[j] = audioStreamChunk[chunkIndex];
          r[j] = audioStreamChunk[chunkIndex + rightChannelIndex];
        }
        if (queueSampleCount > targetQueueSize) {
          let drop = Math.ceil((queueSampleCount - targetQueueSize) / 1024);
          j = Math.max(0, j - drop);
          totalOverrun += drop;
        }
      }
      if (j > 0) {
        fillL = l[j-1];
        fillR = r[j-1];
      }
      const underrun = outputChunkSize - j;
      if (underrun > 0) {
        // Fill any underrun
        for (; j < outputChunkSize; j++) {
          l[j] = fillL;
          r[j] = fillR;
        }
      }
      if (prevUnderrun !== 0 && underrun !== rxBufferSize) {
        // Report underrun, but only if it's not just due to the stream stopping
        messagePort.postMessage(['error', 'Underrun by ' + prevUnderrun + ' samples.']);
      }
      prevUnderrun = underrun;

      if (totalOverrun > 50) {  // ignore small clock-skew-ish amounts of overrun
        messagePort.postMessage(['error', 'Overrun; dropping ' + totalOverrun + ' samples.']);
      }
      //const totalSkew = totalOverrun - underrun;
      //averageSkew = averageSkew * 15/16 + totalSkew * 1/16;
      
      if (underrun > 0) {
        messagePort.postMessage(['checkStartStop']);
      }
      
      updateParameters();
    };
  }
  exports.AudioBuffererImpl = AudioBuffererImpl;
  
  function MessageHandlerAdapter(handler) {
    return function messageEventHandler(event) {
      const selector = event.data[0];
      if (!handler.propertyIsEnumerable(selector)) {
        throw new Error('Refusing to call non-enumerable method ' + selector);
      }
      handler[selector](...Array.prototype.slice.call(event.data, 1));
    };
  }
  exports.MessageHandlerAdapter = MessageHandlerAdapter;

  // Given a maximum acceptable delay, calculate the largest power-of-two buffer size for a ScriptProcessorNode which does not result in more than that delay.
  function delayToBufferSize(sampleRate, maxDelayInSeconds) {
    var maxBufferSize = sampleRate * maxDelayInSeconds;
    var powerOfTwoBufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
    // Size limits defined by the Web Audio API specification.
    powerOfTwoBufferSize = Math.max(256, Math.min(16384, powerOfTwoBufferSize));
    return powerOfTwoBufferSize;
  }
  exports.delayToBufferSize = delayToBufferSize;
  
  Object.freeze(exports);

  if (typeof define !== 'undefined') {
    // RequireJS environment
    define([], () => exports);
  }
  if (typeof registerProcessor !== 'undefined') {
    // AudioWorklet environment
    registerProcessor('WorkletBufferer', class WorkletBufferer extends AudioWorkletProcessor {
      static get parameterDescriptors() {
        return [];
      }
      
      constructor(options) {
        super(options);
        this._b = new AudioBuffererImpl(/* (global) */ sampleRate, this.port);
      }
      
      process(inputs, outputs, parameters) {
        const soleOutput = outputs[0];
        // Be robust against mono output even though we shouldn't ever get it.
        this._b.produceSamples(soleOutput[0], soleOutput[soleOutput.length - 1]);
        return true;  // indicate we are an active source
      }
    });
  }
}());
