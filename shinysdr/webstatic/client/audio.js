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

define(['./values', './events', './network'], function (values, events, network) {
  'use strict';
  
  var exports = {};
  
  var EMPTY_CHUNK = [];
  
  function connectAudio(url) {
    // TODO more portability
    var audio = new (typeof AudioContext !== 'undefined' ? AudioContext : webkitAudioContext)();
    var sampleRate = audio.sampleRate;
    function delayToBufferSize(maxDelayInSeconds) {
      var maxBufferSize = sampleRate * maxDelayInSeconds;
      var powerOfTwoBufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
      // Specification-defined limits
      powerOfTwoBufferSize = Math.max(256, Math.min(16384, powerOfTwoBufferSize));
      return powerOfTwoBufferSize;
    }
    
    // Stream parameters
    var numAudioChannels = null;
    
    // Queue size management
    // The queue should be large to avoid underruns due to bursty processing/delivery.
    // The queue should be small to minimize latency.
    var targetQueueSize = Math.round(0.2 * sampleRate);
    var queueHistory = new Int32Array(20);
    var queueHistoryPtr = 0;
    
    // Size of data chunks we get from network and the audio context wants, used for tuning our margins
    var inputChunkSizeSample = 0;
    var outputChunkSizeSample = 0;
    
    // Queue of chunks
    var queue = [];
    var queueSampleCount = 0;
    
    // Chunk currently being copied into audio node buffer
    var audioStreamChunk = EMPTY_CHUNK;
    var chunkIndex = 0;
    var prevUnderrun = 0;
    
    // Flags for start/stop handling
    var started = false;
    var startStopTickle = false;
    
    // User-facing status display
    // TODO should be faceted read-only when exported
    var errorTime = 0;
    function error(s) {
      info.error._update(String(s));
      errorTime = Date.now() + 1000;
    }
    var info = values.makeBlock({
      buffered: new values.LocalReadCell(new values.Range([[0, 2]], false, false), 0),
      target: new values.LocalReadCell(String, ''),  // TODO should be numeric w/ unit
      error: new values.LocalReadCell(new values.Notice(true), ''),
    });
    function updateStatus() {
      var buffered = (queueSampleCount + audioStreamChunk.length - chunkIndex) / sampleRate;
      var target = targetQueueSize / sampleRate;
      info.buffered._update(buffered / target);
      info.target._update(target.toFixed(2) + ' s');
      if (errorTime < Date.now()) {
        info.error._update('');
      }
    }
    
    function updateParameters() {
      // Update queue size management
      queueHistory[queueHistoryPtr] = queueSampleCount;
      queueHistoryPtr = (queueHistoryPtr + 1) % queueHistory.length;
      var least = Math.min.apply(undefined, queueHistory);
      var most = Math.max.apply(undefined, queueHistory);
      targetQueueSize = Math.max(1, Math.round(
        ((most - least) + Math.max(inputChunkSizeSample, outputChunkSizeSample))));
      
      updateStatus();
    }
    
    network.retryingConnection(url + '?rate=' + encodeURIComponent(JSON.stringify(sampleRate)), function (ws) {
      ws.binaryType = 'arraybuffer';
      function lose(reason) {
        console.error('audio:', reason);
        ws.close(4000);  // first "application-specific" error code
      }
      ws.onmessage = function(event) {
        if (queue.length > 100) {
          console.log('Extreme audio overrun.');
          queue.length = 0;
          queueSampleCount = 0;
          return;
        }
        var chunk;
        if (typeof event.data === 'string') {
          if (numAudioChannels !== null) {
            console.log('audio: Got string message when already initialized');
            return;
          } else {
            var info = JSON.parse(event.data);
            if (typeof info !== 'number') {
              lose('Message was not a number');
            }
            numAudioChannels = info;
          }
          return;
        } else if (event.data instanceof ArrayBuffer) {
          // TODO think about float format portability (endianness only...?)
          chunk = new Float32Array(event.data);
        } else {
          // TODO handle in general
          lose('bad WS data');
          return;
        }

        if (numAudioChannels === null) {
          lose('Missing number-of-channels message');
        }
        queue.push(chunk);
        queueSampleCount += chunk.length;
        inputChunkSizeSample = chunk.length;
        updateParameters();
        if (!started) startStop();
      };
      ws.addEventListener('close', function (event) {
        error('Disconnected.');
        numAudioChannels = null;
        setTimeout(startStop, 0);
      });
      // Starting the audio ScriptProcessor will be taken care of by the onmessage handler
    });
    
    var rxBufferSize = delayToBufferSize(0.15);
    
    var ascr = audio.createScriptProcessor(rxBufferSize, 0, 2);
    ascr.onaudioprocess = function audioCallback(event) {
      var abuf = event.outputBuffer;
      outputChunkSizeSample = abuf.length;
      var l = abuf.getChannelData(0);
      var r = abuf.getChannelData(1);
      var rightChannelIndex = numAudioChannels - 1;
      var j;
      for (j = 0;
           chunkIndex < audioStreamChunk.length && j < abuf.length;
           chunkIndex += numAudioChannels, j++) {
        l[j] = audioStreamChunk[chunkIndex];
        r[j] = audioStreamChunk[chunkIndex + rightChannelIndex];
      }
      while (j < abuf.length) {
        // Get next chunk
        // TODO: shift() is expensive
        audioStreamChunk = queue.shift() || EMPTY_CHUNK;
        queueSampleCount -= audioStreamChunk.length;
        chunkIndex = 0;
        if (audioStreamChunk.length == 0) {
          break;
        }
        for (;
             chunkIndex < audioStreamChunk.length && j < abuf.length;
             chunkIndex += numAudioChannels, j++) {
          l[j] = audioStreamChunk[chunkIndex];
          r[j] = audioStreamChunk[chunkIndex + rightChannelIndex];
        }
        if (queueSampleCount > targetQueueSize) {
          var drop = Math.ceil((queueSampleCount - targetQueueSize) / 1024);
          if (drop > 12) {  // ignore small clock-skew-ish amounts of overrun
            error('Overrun; dropping ' + drop + ' samples.');
          }
          j = Math.max(0, j - drop);
        }
      }
      var underrun = abuf.length - j;
      for (; j < abuf.length; j++) {
        // Fill any underrun
        l[j] = 0;
        r[j] = 0;
      }
      if (prevUnderrun != 0 && underrun != rxBufferSize) {
        // Report underrun, but only if it's not just due to the stream stopping
        error('Underrun by ' + prevUnderrun + ' samples.');
      }
      prevUnderrun = underrun;

      if (underrun > 0 && !startStopTickle) {
        // Consider stopping the audio callback
        setTimeout(startStop, 1000);
        startStopTickle = true;
      }

      updateParameters();
    };

    // Workaround for Chromium bug https://code.google.com/p/chromium/issues/detail?id=82795 -- ScriptProcessor nodes are not kept live
    window['__dummy_audio_node_reference_' + Math.random()] = ascr;
    //console.log('audio init done');
    
    function startStop() {
      startStopTickle = false;
      if (queue.length > 0 || audioStreamChunk !== EMPTY_CHUNK) {
        if (!started) {
          // Note: empirically, it's not actually _necessary_ to avoid redundant connect or disconnect operations, but I want to avoid possibly causing extra work (e.g. if the implementation prepares for a flow graph change even if it doesn't do anything).
          started = true;
          ascr.connect(audio.destination);
        }
      } else {
        if (started) {
          started = false;
          ascr.disconnect(audio.destination);
        }
      }
    }
    
    return info;
  }
  
  exports.connectAudio = connectAudio;
  
  return Object.freeze(exports);
});