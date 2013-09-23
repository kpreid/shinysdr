define(['./values', './events', './database', './network', './maps', './widget', './audio', './sections'], function (values, events, database, network, maps, widget, audio, sections) {
  'use strict';
  
  var any = values.any;
  var LocalCell = values.LocalCell;
  var StorageNamespace = values.StorageNamespace;
  
  var scheduler = new events.Scheduler();
  
  var freqDB = new database.Union();
  freqDB.add(database.allSystematic);
  freqDB.add(database.fromCatalog('dbs/')); // TODO get url from server
  
  // TODO get url from server
  network.externalGet('client/plugin-index.json', 'text', function gotPluginIndex(jsonstr) {
    var names = Array.prototype.slice.call(JSON.parse(jsonstr));
    requirejs(names, function (plugins) {
      connectRadio();
    });
  });
  
  function connectRadio() {
    var radio;
    network.connect('radio', function gotDesc(remote) {
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
      var writableDB = new database.Table();
      freqDB.add(writableDB);
      radio.targetDB = writableDB; // kludge reference
  
      var view = new widget.SpectrumView({
        scheduler: scheduler,
        radio: radio,
        element: document.querySelector('.hscalegroup'), // TODO relic
        storage: new StorageNamespace(localStorage, 'shinysdr.viewState.spectrum.')
      });
    
      var context = new widget.Context({
        radio: radio,
        spectrumView: view,
        freqDB: freqDB,
        scheduler: scheduler
      });
    
      // generic control UI widget tree
      widget.createWidgets(radio, context, document);
    
      // Map (all geographic data)
      var map = new maps.Map(document.getElementById('map'), scheduler, freqDB, radio);
    }); // end gotDesc
  
    audio.connectAudio('/audio');  // TODO get url from server
  }
});