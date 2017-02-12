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

define(['./events', './network', './types', './values'],
       (   events,     network,     types,     values) => {
  'use strict';
  
  const BulkDataT = types.BulkDataT;
  const Cell = values.Cell;
  const ConstantCell = values.ConstantCell;
  const EnumT = types.EnumT;
  const LocalCell = values.LocalCell;
  const LocalReadCell = values.LocalReadCell;
  const NoticeT = types.NoticeT;
  const Notifier = events.Notifier;
  const Neverfier = events.Neverfier;
  const StorageCell = values.StorageCell;
  const booleanT = types.booleanT;
  const cellPropOfBlock = values.cellPropOfBlock;
  const makeBlock = values.makeBlock;
  const numberT = types.numberT;
  const retryingConnection = network.retryingConnection;
  const stringT = types.stringT;
  
  const exports = {};
  
  // In connectAudio, we assume that the maximum audio bandwidth is lower than that suiting this sample rate, so that if the native sample rate is much higher than this we can send a lower one over the network without losing anything of interest.
  const ASSUMED_USEFUL_SAMPLE_RATE = 40000;
  
  const EMPTY_CHUNK = Object.freeze([]);
  
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
    
    // Analyser for display
    var analyserAdapter = new AudioAnalyserAdapter(scheduler, audio);
    
    // User-facing status display
    // TODO should be faceted read-only when exported
    var errorTime = 0;
    function error(s) {
      info.error._update(String(s));
      errorTime = Date.now() + 1000;
    }
    var info = makeBlock({
      buffered: new LocalReadCell(new types.RangeT([[0, 2]], false, false), 0),
      target: new LocalReadCell({value_type: stringT, naming: { label: 'Target latency' }}, ''),  // TODO should be numeric w/ unit
      error: new LocalReadCell(new NoticeT(true), ''),
      //averageSkew: new LocalReadCell(Number, 0),
      monitor: new ConstantCell(types.blockT, analyserAdapter)
    });
    Object.defineProperty(info, '_implements_shinysdr.client.audio.AudioStreamStatus', {});
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
    const interpolationGainNode = audio.createGain();
    
    // don't use too much bandwidth
    const requestedSampleRate = minimizeSampleRate(nativeSampleRate, ASSUMED_USEFUL_SAMPLE_RATE);
    
    retryingConnection(url + '?rate=' + encodeURIComponent(JSON.stringify(requestedSampleRate)), null, ws => {
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
          const interpolation = nativeSampleRate / streamSampleRate;  // TODO fail if not integer
          const streamRateChunk = new Float32Array(event.data);
          const nSamples = streamRateChunk.length / numAudioChannels;
          
          // Insert zeros to change sample rate, e.g. with interpolation = 3,
          //     [l r l r l r] becomes [l r 0 0 0 0 l r 0 0 0 0 l r 0 0 0 0]
          var nativeRateChunk = new Float32Array(nSamples * numAudioChannels * interpolation);  // TODO: With partial-chunk processing we could avoid allocating new buffers all the time -- use a circular buffer? (But we can't be allocation-free anyway since the WebSocket isn't.)
          var rightChannelIndex = numAudioChannels - 1;
          var step = interpolation * numAudioChannels;
          for (var i = 0; i < nSamples; i++) {
            nativeRateChunk[i * step] = streamRateChunk[i * numAudioChannels];
            nativeRateChunk[i * step + rightChannelIndex] = streamRateChunk[i * numAudioChannels + rightChannelIndex];
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
          const interpolation = nativeSampleRate / streamSampleRate;
          interpolationGainNode.gain.value = interpolation;
          
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
    
    const ascr = audio.createScriptProcessor(rxBufferSize, 0, 2);
    ascr.onaudioprocess = function audioCallback(event) {
      const abuf = event.outputBuffer;
      const outputChunkSize = abuf.length;
      outputChunkSizeSample = outputChunkSize;
      const l = abuf.getChannelData(0);
      const r = abuf.getChannelData(1);
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
      var underrun = outputChunkSize - j;
      if (underrun > 0) {
        // Fill any underrun
        for (; j < outputChunkSize; j++) {
          l[j] = fillL;
          r[j] = fillR;
        }
      }
      if (prevUnderrun !== 0 && underrun !== rxBufferSize) {
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
    
    ascr.connect(antialiasFilter);
    antialiasFilter.connect(interpolationGainNode);
    const nodeBeforeDestination = interpolationGainNode;
    
    function startStop() {
      startStopTickle = false;
      if (queue.length > 0 || audioStreamChunk !== EMPTY_CHUNK) {
        if (!started) {
          // Avoid unnecessary click because previous fill value is not being played.
          fillL = fillR = 0;
          
          started = true;
          nodeBeforeDestination.connect(audio.destination);
          analyserAdapter.connectFrom(nodeBeforeDestination);
          analyserAdapter.setLockout(false);
        }
      } else {
        if (started) {
          started = false;
          nodeBeforeDestination.disconnect(audio.destination);
          analyserAdapter.disconnectFrom(nodeBeforeDestination);
          analyserAdapter.setLockout(true);
        }
      }
    }
    
    return info;
  }
  
  exports.connectAudio = connectAudio;

  // TODO adapter should have gui settable parameters and include these
  // These options create a less meaningful and more 'decorative' result.
  const FREQ_ADJ = false;    // Compensate for typical frequency dependence in music so peaks are equal.
  const TIME_ADJ = false;    // Subtract median amplitude; hides strong beats.
  
  // Takes frequency data from an AnalyserNode and provides an interface like a MonitorSink
  function AudioAnalyserAdapter(scheduler, audioContext) {
    // Construct analyser.
    const analyserNode = audioContext.createAnalyser();
    analyserNode.smoothingTimeConstant = 0;
    analyserNode.fftSize = 16384;
    
    // Used to have the option to reduce this to remove empty high-freq bins from the view. Leaving that out for now.
    const length = analyserNode.frequencyBinCount;
    
    // Constant parameters for MonitorSink interface
    const effectiveSampleRate = analyserNode.context.sampleRate * (length / analyserNode.frequencyBinCount);
    const info = Object.freeze({freq: 0, rate: effectiveSampleRate});
    
    // State
    const fftBuffer = new Float32Array(length);
    let lastValue = [info, fftBuffer];
    const subscriptions = [];
    let isScheduled = false;
    const pausedCell = this.paused = new LocalCell(booleanT, true);
    let lockout = false;
    
    function update() {
      isScheduled = false;
      analyserNode.getFloatFrequencyData(fftBuffer);
    
      let absolute_adj;
      if (TIME_ADJ) {
        var medianBuffer = Array.prototype.slice.call(fftBuffer);
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
      
      const newValue = [info, fftBuffer];  // fresh array, same contents, good enough.
    
      // Deliver value
      lastValue = newValue;
      maybeScheduleUpdate();
      // TODO replace this with something async
      for (let i = 0; i < subscriptions.length; i++) {
        (0,subscriptions[i])(newValue);
      }
    }
    
    function maybeScheduleUpdate() {
      if (!isScheduled && subscriptions.length && !lockout) {
        if (pausedCell.get()) {
          pausedCell.n.listen(maybeScheduleUpdate);
        } else {
          isScheduled = true;
          // A basic rAF loop seems to be about the right rate to poll the AnalyserNode for new data. Using the Scheduler instead would try to run faster.
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
    // This interface allows us to in the future have per-channel analysers without requiring the caller to deal with that.
    Object.defineProperty(this, 'connectFrom', {value: function (inputNode) {
      inputNode.connect(analyserNode);
    }});
    Object.defineProperty(this, 'disconnectFrom', {value: function (inputNode) {
      inputNode.disconnect(analyserNode);
    }});
    
    // Output cell
    this.fft = new Cell(new BulkDataT('dff', 'b'));  // TODO BulkDataT really isn't properly involved here
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
    this.freq_resolution = new ConstantCell(numberT, length);
    this.signal_type = new ConstantCell(types.anyT, {kind: 'USB', sample_rate: effectiveSampleRate});
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
    
    // Cell handling and other state
    const info = {};  // dummy
    var lastValue = [info, new Float32Array(bufferSize)];
    var subscriptions = [];
    
    function sendBuffer(copyBufferSet) {
      // Do this processing now rather than in callback to minimize work done in audio callback.
      const copyL = copyBufferSet.copyL;
      const copyR = copyBufferSet.copyR;
      const outputBuffer = copyBufferSet.outputBuffer;
      for (let i = 0; i < bufferSize; i++) {
        outputBuffer[i * 2] = copyL[i];
        outputBuffer[i * 2 + 1] = copyR[i];
      }
      
      const newValue = [info, outputBuffer];
    
      // Deliver value
      lastValue = newValue;
      // TODO replace this with something async
      for (let i = 0; i < subscriptions.length; i++) {
        (0,subscriptions[i])(newValue);
      }
    }
    
    // TODO: Also disconnect processor when nobody's subscribed.
    
    Object.defineProperty(this, 'connectFrom', {value: function (inputNode) {
      inputNode.connect(captureProcessor);
    }});
    Object.defineProperty(this, 'disconnectFrom', {value: function (inputNode) {
      inputNode.disconnect(captureProcessor);
    }});
    
    // Output cell
    this.scope = new Cell(new BulkDataT('d', 'f'));  // TODO BulkDataT really isn't properly involved here
    this.scope.get = function () {
      return lastValue;
    };
    // TODO: put this on a more general and sound framework (same as BulkDataCell)
    this.scope.subscribe = function (callback) {
      subscriptions.push(callback);
    };
    
    // Other elements expected by Monitor widget
    Object.defineProperty(this, '_implements_shinysdr.i.blocks.IMonitor', {enumerable: false});
    this.freq_resolution = new ConstantCell(numberT, length);
    this.signal_type = new ConstantCell(types.anyT, {kind: 'USB', sample_rate: audioContext.sampleRate});
  }
  Object.defineProperty(AudioScopeAdapter.prototype, '_reshapeNotice', {value: new Neverfier()});
  Object.freeze(AudioScopeAdapter.prototype);
  Object.freeze(AudioScopeAdapter);
  exports.AudioScopeAdapter = AudioScopeAdapter;
  
  function handleUserMediaError(e, showMessage, whatWeWereDoing) {
    // Note: Empirically, e is a NavigatorUserMediaError but that ctor is not exposed so we can't say instanceof.
    if (e && e.name === 'PermissionDeniedError') {
      // Permission error.
      // Note: Empirically, e.message is empty but it exists, so let's mention it in case it helps.
      showMessage('Failed to ' + whatWeWereDoing + ' (permission denied). ' + e.message);
    } else if (e && e.name) {
      showMessage(e.name);
    } else if (e) {
      showMessage(String(e));
      throw e;
    } else {
      throw e;
    }
  }
  exports.handleUserMediaError_ForTesting = handleUserMediaError;
  
  function MediaDeviceSelector(mediaDevices, storage) {
    let shapeNotifier = new Notifier();
    let selectorCell = null;  // set by enumerate()
    let errorCell = this.error = new LocalReadCell(new NoticeT(false), '');
    
    Object.defineProperty(this, '_reshapeNotice', {value: shapeNotifier});
    
    let enumerate = () => {
      mediaDevices.enumerateDevices().then(deviceInfos => {
        const deviceEnumTable = {};
        let defaultDeviceId = 'default';
        Array.from(deviceInfos).forEach(deviceInfo => {
          if (deviceInfo.kind !== 'audioinput') return;
          if (!defaultDeviceId) {
            defaultDeviceId = deviceInfo.deviceId;
          }
          deviceEnumTable[deviceInfo.deviceId] = String(deviceInfo.label || deviceInfo.deviceId);
          // TODO use deviceInfo.groupId as part of enum sort key
        });
        // TODO: StorageCell isn't actually meant to be re-created in this fashion and will leak stuff. Fix StorageCell.
        this.device = selectorCell = new StorageCell(storage, new EnumT(deviceEnumTable), defaultDeviceId, 'device');
        shapeNotifier.notify();
        errorCell._update('');
      }, e => {
        handleUserMediaError(e, errorCell._update.bind(errorCell), 'list audio devices');
      });
    };
    // Note: Have not managed to see this event fired in practice (Chrome and Firefox on Mac).
    mediaDevices.addEventListener('devicechange', event => enumerate(), false);
    enumerate();
  }
  
  function UserMediaOpener(scheduler, audioContext, deviceIdCell) {
    // TODO: Does not need to be an unbreakable notify loop; have something which is a generalization of DerivedCell that handles async computations.
    const output = audioContext.createGain();  // dummy node to be switchable
    
    makeBlock(this);
    let errorCell = this.error = new LocalReadCell(new NoticeT(false), '');
    Object.defineProperty(this, 'source', {value: output});
    
    let previousSource = null;
    function setOutput(newSource) {
      if (newSource !== previousSource && previousSource !== null) {
        previousSource.disconnect(output);
      }
      if (newSource !== null) {
        newSource.connect(output);
      }
      previousSource = newSource;
    }
    
    function update() {
      const deviceId = deviceIdCell.depend(update);
      if (typeof deviceId !== 'string') {
        setOutput(null);
      } else {
        navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: { exact: deviceId },
            // If we do not disable default-enabled echoCancellation then we get mono
            // audio on Chrome. See:
            //    https://bugs.chromium.org/p/chromium/issues/detail?id=387737
            echoCancellation: { exact: false }  // using 'ideal:' doesn't help.
          }
        }).then((stream) => {
          // TODO: There is supposedly a better version of this in the future (MediaStreamTrackSource)
          // TODO: In case selector gets changed multiple times, have a token to cancel earlier requests
          setOutput(audioContext.createMediaStreamSource(stream));
          errorCell._update('');
        }, (e) => {
          setOutput(null);
          handleUserMediaError(e, errorCell._update.bind(errorCell),
              'open audio device ' + JSON.stringify(deviceId));
        });
      }
    }
    update.scheduler = scheduler;
    update();
  }

  function UserMediaSelector(scheduler, audioContext, mediaDevices, storage) {
    const mediaDeviceSelector = new MediaDeviceSelector(mediaDevices, storage);
    const userMediaOpener = new UserMediaOpener(scheduler, audioContext,
        cellPropOfBlock(scheduler, mediaDeviceSelector, 'device', false));
    
    // TODO: this is not a good block/cell structure, we are exposing our implementation organization.
    makeBlock(this);
    this.selector = new ConstantCell(types.blockT, mediaDeviceSelector);
    this.opener = new ConstantCell(types.blockT, userMediaOpener);
    Object.defineProperty(this, 'source', {value: userMediaOpener.source});
  }
  exports.UserMediaSelector = UserMediaSelector;
  
  // Given a maximum acceptable delay, calculate the largest power-of-two buffer size for a ScriptProcessorNode which does not result in more than that delay.
  function delayToBufferSize(sampleRate, maxDelayInSeconds) {
    var maxBufferSize = sampleRate * maxDelayInSeconds;
    var powerOfTwoBufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
    // Size limits defined by the Web Audio API specification.
    powerOfTwoBufferSize = Math.max(256, Math.min(16384, powerOfTwoBufferSize));
    return powerOfTwoBufferSize;
  }
  
  // Find the smallest (sample rate) number which divides highRate (so can be upsampled by the resampling implemented here) while being larger than lowerLimitRate (so as to avoid obligating the source to discard wanted frequency content) unless highRate is already lower.
  function minimizeSampleRate(highRate, lowerLimitRate) {
    let divisor = Math.floor(highRate / lowerLimitRate);
    if (highRate / divisor < lowerLimitRate) {
      // Fix up bad rounding (TODO: haven't proven this to be necessary)
      divisor--;
    }
    if (divisor === 0) {
      // highRate is already less than lowerLimitRate.
      return highRate;
    }
    const minimizedRate = highRate / divisor;
    if (minimizedRate < lowerLimitRate || !isFinite(minimizedRate)) {
      throw new Error('oops');
    }
    return minimizedRate;
  }
  exports.minimizeSampleRate_ForTesting = minimizeSampleRate;
    
  return Object.freeze(exports);
});