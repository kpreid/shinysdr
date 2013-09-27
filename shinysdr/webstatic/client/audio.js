define(['./network'], function (network) {
  'use strict';
  
  var exports = {};
  
  // Currently, this parameter is set by what is needed to keep the (gnuradio.blocks.throttle)-based SimulatedSource from repeatedly overrunning and underrunning. Ideally, we ought to optimize it for cross-Internet use -- it needs to be big enough to compensate for the burstiness of stream processing and network delivery.
  // TODO: is it better to keep it in terms of chunks or samples?
  var targetQueueSize = 9;
  
  function connectAudio(url) {
    // TODO portability
    var audio = new webkitAudioContext();
    //console.log('Sample rate: ' + audio.sampleRate);

    var queue = [];
    function openWS() {
      // TODO: refactor reconnecting logic
      var ws = network.openWebSocket(url + '?rate=' + encodeURIComponent(JSON.stringify(audio.sampleRate)));
      ws.onmessage = function(event) {
        if (queue.length > 100) {
          console.log('Extreme audio overrun.');
          queue.length = 0;
          return;
        }
        queue.push(JSON.parse(event.data));
      };
      ws.onclose = function() {
        console.error('Lost WebSocket connection');
        setTimeout(openWS, 1000);
      };
    }
    openWS();
    
    // Choose buffer size
    var maxDelay = 0.20;
    var maxBufferSize = audio.sampleRate * maxDelay;
    var bufferSize = 1 << Math.floor(Math.log(maxBufferSize) / Math.LN2);
    //console.log(maxBufferSize, bufferSize);
    
    var ascr = audio.createScriptProcessor(bufferSize, 0, 2);
    var empty = [];
    var audioStreamChunk = empty;
    var chunkIndex = 0;
    var prevUnderrun = 0;
    ascr.onaudioprocess = function audioCallback(event) {
      var abuf = event.outputBuffer;
      var l = abuf.getChannelData(0);
      var r = abuf.getChannelData(1);
      var j;
      for (j = 0;
           chunkIndex < audioStreamChunk.length && j < abuf.length;
           chunkIndex += 2, j++) {
        l[j] = audioStreamChunk[chunkIndex];
        r[j] = audioStreamChunk[chunkIndex + 1];
      }
      while (j < abuf.length) {
        // Get next chunk
        // TODO: shift() is expensive
        audioStreamChunk = queue.shift() || empty;
        if (audioStreamChunk.length == 0) {
          break;
        }
        chunkIndex = 0;
        for (;
             chunkIndex < audioStreamChunk.length && j < abuf.length;
             chunkIndex += 2, j++) {
          l[j] = audioStreamChunk[chunkIndex];
          r[j] = audioStreamChunk[chunkIndex + 1];
        }
        if (queue.length > targetQueueSize) {
          var drop = (queue.length - targetQueueSize) * 3;
          if (drop > 6) {  // ignore small clock-skew-ish amounts of overrun
            console.log('Audio overrun; dropping', drop, 'samples.');
          }
          j = Math.max(0, j - drop);
        }
      }
      for (; j < abuf.length; j++) {
        // Fill any underrun
        l[j] = 0;
        r[j] = 0;
      }
      var underrun = abuf.length - j;
      if (prevUnderrun != 0 && underrun != bufferSize) {
        // Report underrun, but only if it's not just due to the stream stopping
        console.log('Audio underrun by', prevUnderrun, 'samples.');
      }
      prevUnderrun = underrun;
    };
    ascr.connect(audio.destination);
    // Workaround for Chromium bug https://code.google.com/p/chromium/issues/detail?id=82795 -- ScriptProcessor nodes are not kept live
    window.__dummy_audio_node_reference = ascr;
    //console.log('audio init done');
  }
  
  exports.connectAudio = connectAudio;
  
  return Object.freeze(exports);
});