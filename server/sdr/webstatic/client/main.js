(function () {
  'use strict';
  
  var any = sdr.values.any;
  var LocalCell = sdr.values.LocalCell;
  var StorageNamespace = sdr.values.StorageNamespace;
  
  var scheduler = new sdr.events.Scheduler();
  
  var freqDB = new sdr.database.Union();
  freqDB.add(sdr.database.allSystematic);
  freqDB.add(sdr.database.fromCatalog('dbs/'));
  
  var radio;
  sdr.network.connect('radio', function gotDesc(remote) {
    radio = remote;

    // Takes center freq as parameter so it can be used on hypotheticals and so on.
    function frequencyInRange(candidate, centerFreq) {
      var halfBandwidth = radio.input_rate.get() / 2;
      if (candidate < halfBandwidth && centerFreq === 0) {
        // recognize tuning for 0Hz gimmick
        return true;
      }
      var fromCenter = Math.abs(candidate - centerFreq) / halfBandwidth;
      return fromCenter > 0.01 && // DC peak
             fromCenter < 0.85;  // loss at edges
    }

    // Options
    //   receiver: optional receiver
    //   alwaysCreate: optional boolean (false)
    //   freq: float Hz
    //   mode: optional string
    //   moveCenter: optional boolean (false)
    function tune(options) {
      var alwaysCreate = options.alwaysCreate;
      var freq = +options.freq;
      var mode = options.mode;
      var receiver = options.receiver;
      //console.log('tune', alwaysCreate, freq, mode, receiver);
      
      var receivers = radio.receivers;
      var fit = Infinity;
      if (!receiver && !alwaysCreate) {
        // Search for nearest matching receiver
        for (var recKey in receivers) {
          var candidate = receivers[recKey];
          if (!candidate.rec_freq) continue;  // sanity check
          if (mode && candidate.mode.get() !== mode) {
            // Don't use a different mode
            continue;
          }
          var thisFit = Math.abs(candidate.rec_freq.get() - freq);
          if (thisFit < fit) {
            fit = thisFit;
            receiver = candidate;
          }
        }
      }
      
      if (receiver) {
        receiver.rec_freq.set(freq);
        if (mode && receiver.mode.get() !== mode) {
          receiver.mode.set(mode);
        }
      } else {
        // TODO less ambiguous-naming api
        receivers.create({
          mode: mode || 'AM',
          rec_freq: freq
        });
        // TODO: should return stub for receiver or have a callback or something
      }
      
      if (options.moveCenter && !frequencyInRange(freq, radio.source.freq.get())) {
        if (freq < radio.input_rate.get() / 2) {
          // recognize tuning for 0Hz gimmick
          radio.source.freq.set(0);
        } else {
          // left side, just inside of frequencyInRange's test
          radio.source.freq.set(freq + radio.input_rate.get() * 0.374);
        }
      }
      
      return receiver;
    }
    Object.defineProperty(radio, 'tune', {
      value: tune,
      configurable: true,
      enumerable: false
    });
    
    // Kludge to let frequency preset widgets do their thing
    // TODO(kpreid): Make this explicitly client state instead
    radio.preset = new LocalCell(any);
    radio.preset.set = function(freqRecord) {
      LocalCell.prototype.set.call(this, freqRecord);
      tune({
        freq: freqRecord.freq,
        mode: freqRecord.mode,
        moveCenter: true
      });
    };
    
    // kludge till we have proper editing
    var writableDB = new sdr.database.Table();
    freqDB.add(writableDB);
    radio.targetDB = writableDB; // kludge reference
  
    var view = new sdr.widget.SpectrumView({
      scheduler: scheduler,
      radio: radio,
      element: document.querySelector('.hscalegroup'), // TODO relic
      storage: new StorageNamespace(localStorage, 'sdr.viewState.spectrum.')
    });
    
    var context = new sdr.widget.Context({
      radio: radio,
      spectrumView: view,
      freqDB: freqDB,
      scheduler: scheduler
    });
    
    sdr.widget.createWidgets(radio, context, document);
    
    // audio processing - TODO move to appropriate location
    (function() {
      // TODO portability
      var audio = new webkitAudioContext();
      console.log('Sample rate: ' + audio.sampleRate);

      var targetQueueSize = 2;
      var queue = [];
      function openWS() {
        // TODO: refactor reconnecting logic
        var ws = sdr.network.openWebSocket('/audio?rate=' + encodeURIComponent(JSON.stringify(audio.sampleRate)));
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
      
      var bufferSize = 2048;
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
            console.log('Audio overrun; dropping', drop, 'samples.');
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
      console.log('audio init done');
    }());
  }); // end gotDesc
}());