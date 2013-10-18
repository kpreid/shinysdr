define(['./network'], function (network) {
  'use strict';
  
  var exports = {};
  
  var minQueueAdjust = 2;
  var initialQueueSize = 12;
  var maxQueueAdjust = 20;
  
  function connectAudio(url) {
    // TODO portability
    var audio = new webkitAudioContext();
    //console.log('Sample rate: ' + audio.sampleRate);

    // Queue size management
    // The queue should be large to avoid underruns due to bursty processing/delivery.
    // The queue should be small to minimize latency.
    var targetQueueSize = initialQueueSize;
    var queueHistory = new Int32Array(30);
    var queueHistoryPtr = 0;
    var hasOverrun = false;
    var hasUnderrun = false;
    
    var queue = [];
    
    network.retryingConnection(url + '?rate=' + encodeURIComponent(JSON.stringify(audio.sampleRate)), function (ws) {
      ws.binaryType = 'arraybuffer';
      ws.onmessage = function(event) {
        if (queue.length > 100) {
          console.log('Extreme audio overrun.');
          queue.length = 0;
          return;
        }
        var chunk;
        if (typeof event.data === 'string') {
          chunk = JSON.parse(event.data);
        } else if (event.data instanceof ArrayBuffer) {
          // TODO think about float format portability (endianness only...?)
          chunk = new Float32Array(event.data);
        } else {
          // TODO handle in general
          console.error('bad WS data');
          ws.close(1003);
          return;
        }
        queue.push(chunk);
        
        // Update queue size management
        queueHistory[queueHistoryPtr] = queue.length;
        queueHistoryPtr = (queueHistoryPtr + 1) % queueHistory.length;
        var least = Math.min.apply(undefined, queueHistory);
        //console.log('least=', least, queueHistory);
        if (hasUnderrun && least <= 1 && targetQueueSize < maxQueueAdjust) {
          console.log('inc', least, targetQueueSize);
          targetQueueSize++;
          hasUnderrun = false;
        } else if (hasOverrun && least > 4 && targetQueueSize > minQueueAdjust) {
          console.log('dec', least, targetQueueSize);
          targetQueueSize--;
          hasOverrun = false;
        }
      };
    });
    
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
          hasOverrun = true;
          if (drop > 12) {  // ignore small clock-skew-ish amounts of overrun
            console.log('Audio overrun; dropping', drop, 'samples.');
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
      if (prevUnderrun != 0 && underrun != bufferSize) {
        // Report underrun, but only if it's not just due to the stream stopping
        console.log('Audio underrun by', prevUnderrun, 'samples.');
        hasUnderrun = true;
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