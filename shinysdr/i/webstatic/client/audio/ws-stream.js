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
  'require',
  '../audio/analyser',
  '../audio/bufferer',
  '../audio/util',
  '../network',
  '../types',
  '../values',
], (
  require,
  import_audio_analyser,
  import_audio_bufferer,
  import_audio_util,
  import_network,
  import_types,
  import_values
) => {
  const {
    AudioAnalyserAdapter,
  } = import_audio_analyser;
  const {
    AudioBuffererImpl,
    MessageHandlerAdapter,
  } = import_audio_bufferer;
  const {
    AudioContext,
  } = import_audio_util;
  const {
    retryingConnection,
  } = import_network;
  const {
    NoticeT,
    QuantityT,
    RangeT,
  } = import_types;
  const {
    ConstantCell,
    LocalReadCell,
    StorageCell,
    makeBlock,
  } = import_values;

  const exports = {};
  
  // In connectAudio, we assume that the maximum audio bandwidth is lower than that suiting this sample rate, so that if the native sample rate is much higher than this we can send a lower one over the network without losing anything of interest.
  const ASSUMED_USEFUL_SAMPLE_RATE = 40000;
  
  function logAutoplayBehavior() {
    console.info.apply(console, ['audio playback debug:'].concat(Array.from(arguments)));
  }
  
  function connectAudio(scheduler, url, storage, webSocketCtor = WebSocket) {
    const audio = new AudioContext();
    const nativeSampleRate = audio.sampleRate;
    const useScriptProcessor = !('audioWorklet' in audio);
    logAutoplayBehavior('initial state is', audio.state);
    
    // Stream parameters
    let numAudioChannels = null;
    let streamSampleRate = null;
    
    let queueNotEmpty = false;
    
    // Flags for start/stop handling
    let started = false;
    let startStopTickle = false;
    
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
      requested_sample_rate: makeRequestedSampleRateCell(nativeSampleRate, storage),
      buffered: new LocalReadCell(new RangeT([[0, 2]], false, false), 0),
      target: new LocalReadCell({
        value_type: new QuantityT({symbol: 's', si_prefix_ok: false}),
        naming: { label: 'Target latency' }}, ''),
      error: new LocalReadCell(new NoticeT(true), ''),
      //averageSkew: new LocalReadCell(Number, 0),
      monitor: new ConstantCell(analyserAdapter)
    });
    Object.defineProperty(info, '_implements_shinysdr.client.audio.AudioStreamStatus', {});
    function setStatus({bufferedFraction, targetSeconds, queueNotEmpty: newQueueNotEmpty}) {
      info.buffered._update(bufferedFraction);
      info.target._update(+targetSeconds.toFixed(2));  // TODO formatting kludge, should be in type instead
      if (errorTime < Date.now()) {
        info.error._update('');
      }
      queueNotEmpty = newQueueNotEmpty;
    }
    
     // Force sample rate to be a value valid for the current nativeSampleRate, which may not be the same as when the value was written to localStorage.
     info.requested_sample_rate.set(
         info.requested_sample_rate.type.round(
           info.requested_sample_rate.get(), 0));
    
    // Antialiasing filters for interpolated signal, cascaded for more attenuation.
    // Note that the cutoff frequency is set from the network callback, not here.
    const antialiasFilters = [];
    for (let i = 0; i < 12; i++) {
      const filter = audio.createBiquadFilter();
      // highshelf type, empirically, has a sharper cutoff than lowpass.
      // TODO: Learn enough about IIR filtering and what the Web Audio filter facilities are actually doing to get this to be actually optimal.
      filter.type = 'highshelf';
      filter.gain.value = -40;
      if (antialiasFilters.length) {
        antialiasFilters[antialiasFilters.length - 1].connect(filter);
      }
      antialiasFilters.push(filter);
    }
    
    const interpolationGainNode = audio.createGain();
    
    // TODO: If interpolation is 1, omit the filter from the chain. (This requires reconnecting dynamically.)
    let nodeAfterSampleSource = antialiasFilters[0];
    antialiasFilters[antialiasFilters.length - 1].connect(interpolationGainNode);
    const nodeBeforeDestination = interpolationGainNode;
    
    let buffererMessagePortPromise;
    if (useScriptProcessor) {
      const buffererMessageChannel = new MessageChannel();
      const buffererMessagePort = buffererMessageChannel.port1;
      buffererMessagePortPromise = Promise.resolve(buffererMessagePort);
      const audioBufferer = new AudioBuffererImpl(nativeSampleRate, buffererMessageChannel.port2);
      const ascr = audio.createScriptProcessor(audioBufferer.rxBufferSize, 0, 2);
      ascr.onaudioprocess = function audioprocessEventHandler(event) {
        const abuf = event.outputBuffer;
        const l = abuf.getChannelData(0);
        const r = abuf.getChannelData(1);
        audioBufferer.produceSamples(l, r);
      };
      ascr.connect(nodeAfterSampleSource);
    } else {
      buffererMessagePortPromise = audio.audioWorklet.addModule(require.toUrl('audio/bufferer.js')).then(() => {
        const workletNode = new AudioWorkletNode(audio, 'WorkletBufferer', {
          numberOfInputs: 0,
          numberOfOutputs: 1,
          outputChannelCount: [2],
        });
        workletNode.addEventListener('processorstatechange', event => {
          if (workletNode.processorState !== 'running') {
            console.error('Audio: Unexpected WorkletNode state change to', workletNode.processorState);
          }
        });
        
        // TODO need to handle port not being ready
        workletNode.connect(nodeAfterSampleSource);
        
        return workletNode.port;
      }, e => {
        error('' + e);
      });
    }
    
    buffererMessagePortPromise.then(buffererMessagePort => {
      buffererMessagePort.onmessage = new MessageHandlerAdapter({
        error: error,
        setStatus: setStatus,
        checkStartStop: function checkStartStop() {
          if (!startStopTickle) {
            setTimeout(startStop, 1000);
            startStopTickle = true;
          }
        }
      });
      retryingConnection(
        () => new webSocketCtor(
          url + '?rate=' + encodeURIComponent(JSON.stringify(info.requested_sample_rate.get()))),
        null,
        ws => handleWebSocket(ws, buffererMessagePort));
    });
    
    function handleWebSocket(ws, buffererMessagePort) {
      ws.addEventListener('open', event => {
        ws.send(''); // dummy required due to server limitation
      }, true);

      ws.binaryType = 'arraybuffer';
      function lose(reason) {
        // TODO: Arrange to trigger exponential backoff if we get this kind of error promptly (maybe retryingConnection should just have a time threshold)
        console.error('Audio:', reason);
        ws.close(4000);  // first "application-specific" error code
      }
      scheduler.claim(lose);
      function changeSampleRate() {
        lose('changing sample rate');
      }
      scheduler.claim(changeSampleRate);
      info.requested_sample_rate.n.listen(changeSampleRate);
      ws.onmessage = function(event) {
        var wsDataValue = event.data;
        if (wsDataValue instanceof ArrayBuffer) {
          // Audio data.
          if (numAudioChannels === null) {
            lose('Did not receive number-of-channels message before first chunk');
            return;
          }
          
          buffererMessagePort.postMessage(['acceptSamples', wsDataValue]);
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
          buffererMessagePort.postMessage(['setFormat', numAudioChannels, streamSampleRate]);
          
          // TODO: We should not update the filter frequency now, but when the AudioBuffererImpl starts reading the new-rate samples. We will need to keep track of the relationship of AudioContext timestamps to samples in order to do this.
          antialiasFilters.forEach(filter => {
            // Yes, this cutoff value is above the Nyquist limit, but the actual cascaded filter works out to be about what we want.
            filter.frequency.value = Math.min(streamSampleRate * 0.8, nativeSampleRate * 0.5);
          });
          const interpolation = nativeSampleRate / streamSampleRate;
          interpolationGainNode.gain.value = interpolation;
          
          console.log('Streaming using', useScriptProcessor ? 'ScriptProcessor' : 'AudioWorklet', streamSampleRate, numAudioChannels + 'ch', 'audio and converting to', nativeSampleRate);
          
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
    }
    
    nodeBeforeDestination.connect(audio.destination);
    analyserAdapter.connectFrom(nodeBeforeDestination);
    
    function startStop() {
      startStopTickle = false;
      if (queueNotEmpty) {
        if (!started) {
          // Avoid unnecessary click because previous fill value is not being played.
          buffererMessagePortPromise.then(port => { port.postMessage(['resetFill']); });
          
          started = true;
          logAutoplayBehavior('attempting resume, immediate state is ' + audio.state);
          audio.resume().then(() => {
            logAutoplayBehavior('resume resolved');
          });
          logAutoplayBehavior('attempted resume, immediate state is ' + audio.state);
        }
      } else {
        if (started) {
          started = false;
          logAutoplayBehavior('attempting suspend, immediate state is ' + audio.state);
          audio.suspend().then(() => {
            logAutoplayBehavior('suspend resolved');
          });
          logAutoplayBehavior('attempted suspend, immediate state is ' + audio.state);
        }
      }
    }
    
    return info;
  }
  exports.connectAudio = connectAudio;
  
  function makeRequestedSampleRateCell(nativeSampleRate, storage) {
    const defaultRate = minimizeSampleRate(nativeSampleRate, ASSUMED_USEFUL_SAMPLE_RATE);
    const ranges = [];
    for (let rate = nativeSampleRate; rate >= 6000 && rate == rate | 0; rate /= 2) {
      ranges.push([rate, rate]);
    }
    if (ranges.length === 0) {
      ranges.push([defaultRate, defaultRate]);
    }
    return new StorageCell(
      storage,
      new RangeT(ranges, false, true, {symbol: 'Hz', si_prefix_ok: true}),
      defaultRate,
      'requested_sample_rate');
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
