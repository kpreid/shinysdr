// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

define(['./types', './values', './events', './network'], function (types, values, events, network) {
  'use strict';
  
  var exports = {};
  
  var BulkDataType = types.BulkDataType;
  var Cell = values.Cell;
  var ConstantCell = values.ConstantCell;
  var LocalCell = values.LocalCell;
  var LocalReadCell = values.LocalReadCell;
  var Neverfier = events.Neverfier;
  
  var EMPTY_CHUNK = [];
  
  function connectAudio(scheduler, url) {
    var audio = new AudioContext();
    var nativeSampleRate = audio.sampleRate;
    
    // Stream parameters
    var numAudioChannels = null;
    var streamSampleRate = null;
    
    // Queue size management
    // The queue should be large to avoid underruns due to bursty processing/delivery.
    // The queue should be small to minimize latency.
    var targetQueueSize = Math.round(0.2 * nativeSampleRate);  // units: sample count
    // Circular buffer of queue fullness history.
    var queueHistory = new Int32Array(200);
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
    
    // Placeholder sample value
    var fillL = 0;
    var fillR = 0;
    
    // Flags for start/stop handling
    var started = false;
    var startStopTickle = false;
    
    //var averageSkew = 0;
    
    // local synth for debugging glitches
    //var fakePhase = 0;
    //function fake(arr) {
    //  for (var i = 0; i < arr.length; i++) {
    //    arr[i] = Math.sin(fakePhase) * 0.1;
    //    fakePhase += (Math.PI * 2) * (600 / nativeSampleRate);
    //  }
    //}
    
    // Analyzer for display
    var analyzerNode = audio.createAnalyser();
    analyzerNode.smoothingTimeConstant = 0;
    analyzerNode.fftSize = 16384;
    var analyzerAdapter = new AudioAnalyzerAdapter(scheduler, analyzerNode, analyzerNode.frequencyBinCount / 2);
    
    // User-facing status display
    // TODO should be faceted read-only when exported
    var errorTime = 0;
    function error(s) {
      info.error._update(String(s));
      errorTime = Date.now() + 1000;
    }
    var info = values.makeBlock({
      buffered: new LocalReadCell(new types.Range([[0, 2]], false, false), 0),
      target: new LocalReadCell(String, ''),  // TODO should be numeric w/ unit
      error: new LocalReadCell(new types.Notice(true), ''),
      //averageSkew: new LocalReadCell(Number, 0),
      monitor: new ConstantCell(types.block, analyzerAdapter)
    });
    function updateStatus() {
      // TODO: I think we are mixing up per-channel and total samples here  (queueSampleCount counts both channels individually)
      var buffered = (queueSampleCount + audioStreamChunk.length - chunkIndex) / nativeSampleRate;
      var target = targetQueueSize / nativeSampleRate;
      info.buffered._update(buffered / target);
      info.target._update(target.toFixed(2) + ' s');
      //info.averageSkew._update(averageSkew);
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
    
    // Note that this filter's frequency is updated from the network
    var antialiasFilter = audio.createBiquadFilter();
    antialiasFilter.type = 'lowpass';
    
    network.retryingConnection(url + '?rate=' + encodeURIComponent(JSON.stringify(nativeSampleRate)), null, function (ws) {
      ws.binaryType = 'arraybuffer';
      function lose(reason) {
        // TODO: Arrange to trigger exponential backoff if we get this kind of error promptly (maybe retryingConnection should just have a time threshold)
        console.error('audio:', reason);
        ws.close(4000);  // first "application-specific" error code
      }
      ws.onmessage = function(event) {
        var wsDataValue = event.data;
        if (wsDataValue instanceof ArrayBuffer) {
          // Audio data.
          
          // Don't buffer huge amounts of data.
          if (queue.length > 100) {
            console.log('Extreme audio overrun.');
            queue.length = 0;
            queueSampleCount = 0;
            return;
          }
          
          if (numAudioChannels === null) {
            lose('Did not receive number-of-channels message before first chunk');
          }
          
          // Read in floats and zero-stuff.
          var interpolation = nativeSampleRate / streamSampleRate;  // TODO fail if not integer
          var streamRateChunk = new Float32Array(event.data);
          var nSamples = streamRateChunk.length / numAudioChannels;
          
          // Insert zeros to change sample rate, e.g. with interpolation = 3,
          //     [l r l r l r] becomes [l r 0 0 0 0 l r 0 0 0 0 l r 0 0 0 0]
          var nativeRateChunk = new Float32Array(nSamples * numAudioChannels * interpolation);  // TODO: With partial-chunk processing we could avoid allocating new buffers all the time -- use a circular buffer? (But we can't be allocation-free anyway since the WebSocket isn't.)
          var rightChannelIndex = numAudioChannels - 1;
          var step = interpolation * numAudioChannels;
          for (var i = 0; i < nSamples; i++) {
            nativeRateChunk[i * step] = streamRateChunk[i * numAudioChannels];
            nativeRateChunk[i * step + rightChannelIndex] = streamRateChunk[i * numAudioChannels + 1];
          }
          
          queue.push(nativeRateChunk);
          queueSampleCount += nativeRateChunk.length;
          inputChunkSizeSample = nativeRateChunk.length;
          updateParameters();
          if (!started) startStop();
          
        } else if (typeof wsDataValue === 'string') {
          // Metadata.
          
          var message;
          try {
            message = JSON.parse(wsDataValue);
          } catch (e) {
            if (e instanceof SyntaxError) {
              lose(e);
              return;
            } else {
              throw e;
            }
          }
          if (!(typeof message === 'object' && message.type === 'audio_stream_metadata')) {
            lose('Message was not properly formatted');
            return;
          }
          numAudioChannels = message.signal_type.kind === 'STEREO' ? 2 : 1;
          streamSampleRate = message.signal_type.sample_rate;
          
          // TODO: We should not update this now, but when the audio callback starts reading the new-rate samples. (This could be done by stuffing the message into the queue.) But unless it's a serious problem, let's not bother until Audio Workers are available at which time we'll need to rewrite much of this anyway.
          antialiasFilter.frequency.value = streamSampleRate * 0.45;  // TODO justify choice of 0.45
          console.log('Streaming', streamSampleRate, numAudioChannels + 'ch', 'audio and converting to', nativeSampleRate);
          
        } else {
          lose('Unexpected type from WebSocket message event: ' + wsDataValue);
          return;
        }        
      };
      ws.addEventListener('close', function (event) {
        error('Disconnected.');
        numAudioChannels = null;
        setTimeout(startStop, 0);
      });
      // Starting the audio ScriptProcessor will be taken care of by the onmessage handler
    });
    
    var rxBufferSize = delayToBufferSize(nativeSampleRate, 0.15);
    
    var ascr = audio.createScriptProcessor(rxBufferSize, 0, 2);
    ascr.onaudioprocess = function audioCallback(event) {
      var abuf = event.outputBuffer;
      var outputChunkSize = outputChunkSizeSample = abuf.length;
      var l = abuf.getChannelData(0);
      var r = abuf.getChannelData(1);
      var rightChannelIndex = numAudioChannels - 1;
      
      var totalOverrun = 0;
      
      var j;
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
        if (audioStreamChunk.length == 0) {
          break;
        }
        for (;
             chunkIndex < audioStreamChunk.length && j < outputChunkSize;
             chunkIndex += numAudioChannels, j++) {
          l[j] = audioStreamChunk[chunkIndex];
          r[j] = audioStreamChunk[chunkIndex + rightChannelIndex];
        }
        if (queueSampleCount > targetQueueSize) {
          var drop = Math.ceil((queueSampleCount - targetQueueSize) / 1024);
          j = Math.max(0, j - drop);
          totalOverrun += drop;
        }
      }
      if (j > 0) {
        fillL = l[j-1];
        fillR = r[j-1];
      }
      var underrun = outputChunkSize - j;
      if (underrun > 0) {
        // Fill any underrun
        for (; j < outputChunkSize; j++) {
          l[j] = fillL;
          r[j] = fillR;
        }
      }
      if (prevUnderrun != 0 && underrun != rxBufferSize) {
        // Report underrun, but only if it's not just due to the stream stopping
        error('Underrun by ' + prevUnderrun + ' samples.');
      }
      prevUnderrun = underrun;

      if (totalOverrun > 50) {  // ignore small clock-skew-ish amounts of overrun
        error('Overrun; dropping ' + totalOverrun + ' samples.');
      }
      //var totalSkew = totalOverrun - underrun;
      //averageSkew = averageSkew * 15/16 + totalSkew * 1/16;

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
    
    ascr.connect(antialiasFilter);    
    var nodeBeforeDestination = antialiasFilter;
    
    function startStop() {
      startStopTickle = false;
      if (queue.length > 0 || audioStreamChunk !== EMPTY_CHUNK) {
        if (!started) {
          // Avoid unnecessary click because previous fill value is not being played.
          fillL = fillR = 0;
          
          started = true;
          nodeBeforeDestination.connect(audio.destination);
          nodeBeforeDestination.connect(analyzerNode);
          analyzerAdapter.setLockout(false);
        }
      } else {
        if (started) {
          started = false;
          nodeBeforeDestination.disconnect(audio.destination);
          nodeBeforeDestination.disconnect(analyzerNode);
          analyzerAdapter.setLockout(true);
        }
      }
    }
    
    return info;
  }
  
  exports.connectAudio = connectAudio;

  // TODO adapter should have gui settable parameters and include these
  // These options create a less meaningful and more 'decorative' result.
  var FREQ_ADJ = false;    // Compensate for typical frequency dependence in music so peaks are equal.
  var TIME_ADJ = false;    // Subtract median amplitude; hides strong beats.
  
  // Takes frequency data from an AnalyzerNode and provides an interface like a MonitorSink
  function AudioAnalyzerAdapter(scheduler, analyzerNode, length) {
    // Constants
    var effectiveSampleRate = analyzerNode.context.sampleRate * (length / analyzerNode.frequencyBinCount);
    var info = Object.freeze({freq: 0, rate: effectiveSampleRate});
    
    // State
    var fftBuffer = new Float32Array(length);
    var lastValue = [info, fftBuffer];
    var subscriptions = [];
    var isScheduled = false;
    var pausedCell = this.paused = new LocalCell(Boolean, true);
    var lockout = false;
    
    function update() {
      isScheduled = false;
      analyzerNode.getFloatFrequencyData(fftBuffer);
    
      var absolute_adj;
      if (TIME_ADJ) {
        var medianBuffer = Array.prototype.slice.call(fftBuffer);
        medianBuffer.sort(function(a, b) {return a - b; });
        absolute_adj = -100 - medianBuffer[length / 2];
      } else {
        absolute_adj = 0;
      }
      
      var freq_adj;
      if (FREQ_ADJ) {
        freq_adj = 1;
      } else {
        freq_adj = 0;
      }
      
      for (var i = 0; i < length; i++) {
        fftBuffer[i] = fftBuffer[i] + absolute_adj + freq_adj * Math.pow(i, 0.5);
      }
      
      var newValue = [info, fftBuffer];  // fresh array, same contents, good enough.
    
      // Deliver value
      lastValue = newValue;
      maybeScheduleUpdate();
      // TODO replace this with something async
      for (var i = 0; i < subscriptions.length; i++) {
        (0,subscriptions[i])(newValue);
      }
    }
    
    function maybeScheduleUpdate() {
      if (!isScheduled && subscriptions.length && !lockout) {
        if (pausedCell.get()) {
          pausedCell.n.listen(maybeScheduleUpdate);
        } else {
          isScheduled = true;
          // A basic rAF loop seems to be about the right rate to poll the AnalyzerNode for new data. Using the Scheduler instead would try to run faster.
          requestAnimationFrame(update);
        }
      }
    }
    maybeScheduleUpdate.scheduler = scheduler;
    
    Object.defineProperty(this, 'setLockout', {value: function (value) {
      lockout = !!value;
      if (!lockout) {
        maybeScheduleUpdate();
      }
    }});
    
    // Output cell
    this.fft = new Cell(new types.BulkDataType('dff', 'b'));  // TODO BulkDataType really isn't properly involved here
    this.fft.get = function () {
      return lastValue;
    };
    // TODO: put this on a more general and sound framework (same as BulkDataCell)
    this.fft.subscribe = function (callback) {
      subscriptions.push(callback);
      maybeScheduleUpdate();
    };
    
    // Other elements expected by Monitor widget
    Object.defineProperty(this, '_implements_shinysdr.i.blocks.IMonitor', {enumerable: false});
    this.freq_resolution = new ConstantCell(Number, length);
    this.signal_type = new ConstantCell(types.any, {kind: 'USB', sample_rate: effectiveSampleRate});
  }
  Object.defineProperty(AudioAnalyzerAdapter.prototype, '_reshapeNotice', {value: new Neverfier()});
  Object.freeze(AudioAnalyzerAdapter.prototype);
  Object.freeze(AudioAnalyzerAdapter);
  exports.AudioAnalyzerAdapter = AudioAnalyzerAdapter;
  
  // Given a maximum acceptable delay, calculate the largest power-of-two buffer size for a ScriptProcessorNode which does not result in more than that delay.
  function delayToBufferSize(sampleRate, maxDelayInSeconds) {
    var maxBufferSize = sampleRate * maxDelayInSeconds;
    var powerOfTwoBufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
    // Size limits defined by the Web Audio API specification.
    powerOfTwoBufferSize = Math.max(256, Math.min(16384, powerOfTwoBufferSize));
    return powerOfTwoBufferSize;
  }
  
    
  return Object.freeze(exports);
});