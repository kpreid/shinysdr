(function () {
  'use strict';
  
  var xhrput = sdr.network.xhrput;
  var makeXhrGetter = sdr.network.makeXhrGetter;
  
  var scheduler = new sdr.events.Scheduler();
  
  var freqDB = new sdr.database.Union();
  freqDB.add(sdr.database.allSystematic);
  freqDB.add(sdr.database.fromCatalog('/dbs/'));
  
  function Cell() {
    this.n = new sdr.events.Notifier();
  }
  Cell.prototype.depend = function(listener) {
    this.n.listen(listener);
    return this.get();
  };
  Cell.prototype.reload = function() {};
  
  function RemoteCell(name, assumed) {
    Cell.call(this);
    var value = assumed;
    var getter = makeXhrGetter(name, function(remote) {
      value = JSON.parse(remote);
      this.n.notify();
    }.bind(this), false);
    getter.go();
    this.reload = getter.go.bind(getter);
    this.get = function() { return value; },
    this.set = function(newValue) {
      value = newValue;
      this.n.notify();
      xhrput(name, JSON.stringify(newValue), function(r) {
        if (Math.floor(r.status / 100) !== 2) {
          // some error or something other than success; obtain new value
          this.reload();
        }
      }.bind(this));
      if (name === '/radio/mode') {
        // TODO KLUDGE: this dependency exists but there's no general way to get it. also there's no guarantee we'll get the new value. This should be replaced by having the server stream state update notifications.
        states.receiver.band_filter_shape.reload();
      }
    };
  }
  RemoteCell.prototype = Object.create(Cell.prototype, {constructor: {value: RemoteCell}});
  
  function PollingCell(name, /* initial */ value, transform, binary, pollRate) {
    Cell.call(this);
    
    // TODO: Better mechanism than XHR
    var queued = false;
    var getter = makeXhrGetter(name, function(data, xhr) {
      queued = false;
      value = transform(data, xhr);
      this.n.notify();
    }.bind(this), binary);
    
    //setInterval(function() {
    //  // TODO: Stop setInterval when not running
    //  // TODO: Don't depend on states
    //  if (states.running.get() && !queued) {
    //    getter.go();
    //    queued = true;
    //  }
    //}, pollRate);
    
    this._update = function(data) {
      value = transform(data);
      this.n.notify();
    };
    
    this.get = function() {
      return value;
    };
  }
  PollingCell.prototype = Object.create(Cell.prototype, {constructor: {value: PollingCell}});
  
  function SpectrumCell() {
    var fft = new Float32Array(0);
    var swapbuf = new Float32Array(0);
    var VSIZE = Float32Array.BYTES_PER_ELEMENT;
    var centerFreq = NaN;
    
    function transform(json) {
      centerFreq = json[0];
      var arrayFFT = json[1];

      var halfFFTSize = arrayFFT.length / 2;

      // adjust size if needed
      if (arrayFFT.length !== fft.length) {
        fft = new Float32Array(arrayFFT.length);
        swapbuf = new Float32Array(arrayFFT.length);
      }
      
      // swap first and second halves for drawing convenience so that center frequency is at halfFFTSize rather than 0
      swapbuf.set(arrayFFT);
      fft.set(swapbuf.subarray(0, halfFFTSize), halfFFTSize);
      fft.set(swapbuf.subarray(halfFFTSize, fft.length), 0);
      
      return fft;
    }
    
    PollingCell.call(this, '/radio/spectrum_fft', fft, transform, true, 1000/30);
    
    this.getCenterFreq = function() {
      return centerFreq;
    };
  }
  SpectrumCell.prototype = Object.create(PollingCell.prototype, {constructor: {value: SpectrumCell}});
  
  var pr = '/radio';
  var states = {
    running: new RemoteCell(pr + '/running', false),
    hw_freq: new RemoteCell(pr + '/hw_freq', 0),
    hw_correction_ppm: new RemoteCell(pr + '/hw_correction_ppm', 0),
    mode: new RemoteCell(pr + '/mode', ""),
    receiver: {
      rec_freq: new RemoteCell(pr + '/receiver/rec_freq', 0),
      band_filter_shape: new RemoteCell(pr + '/receiver/band_filter_shape', {low: 0, high: 0, width: 0}),
      audio_gain: new RemoteCell(pr + '/receiver/audio_gain', 0),
      squelch_threshold: new RemoteCell(pr + '/receiver/squelch_threshold', 0)
    },
    input_rate: new RemoteCell(pr + '/input_rate', 1000000),
    spectrum_fft: new SpectrumCell()
  };
  
  sdr.network.addResyncHook(function () {
    function go(block) {
      for (var key in states) {
        if (states instanceof Cell) {
          states[key].reload();
        } else {
          go(states[key]);
        }
      }
    }
    go(states);
  });
  
  // Takes center freq as parameter so it can be used on hypotheticals and so on.
  function frequencyInRange(candidate, centerFreq) {
    var halfBandwidth = states.input_rate.get() / 2;
    if (candidate < halfBandwidth && centerFreq === 0) {
      // recognize tuning for 0Hz gimmick
      return true;
    }
    var fromCenter = Math.abs(candidate - centerFreq) / halfBandwidth;
    return fromCenter > 0.01 && // DC peak
           fromCenter < 0.85;  // loss at edges
  }
  
  // Kludge to let frequency preset widgets do their thing
  states.preset = {
    reload: function() {},
    set: function(freqRecord) {
      var freq = freqRecord.freq;
      states.mode.set(freqRecord.mode);
      if (!frequencyInRange(freq, states.hw_freq.get())) {
        if (freq < states.input_rate.get() / 2) {
          // recognize tuning for 0Hz gimmick
          states.hw_freq.set(0);
        } else {
          //states.hw_freq.set(freq - 0.2e6);
          // left side, just inside of frequencyInRange's test
          states.hw_freq.set(freq + states.input_rate.get() * 0.374);
        }
      }
      states.receiver.rec_freq.set(freq);
    }
  };
  
  // WebSocket state streaming
  var ws;
  function openWS() {
    ws = new WebSocket('ws://' + document.location.hostname + ':' + (parseInt(document.location.port) + 1) + '/');
    ws.onmessage = function(event) {
      var updates = JSON.parse(event.data);
      for (var key in updates) {
        if (key === 'spectrum_fft') {
          var fft = updates.spectrum_fft;
          states.spectrum_fft._update(fft);
        }
      }
    };
    ws.onclose = function() {
      console.error('Lost WebSocket connection');
      setTimeout(openWS, 1000);
    };
  }
  openWS();
  
  // TODO better structure / move to server
  var _scanView = freqDB;
  states.scan_presets = new Cell();
  states.scan_presets.get = function () { return _scanView; };
  states.scan_presets.set = function (view) {
    _scanView = view;
    this.n.notify();
  };
  
  var view = new sdr.widget.SpectrumView({
    scheduler: scheduler,
    radio: states,
    element: document.querySelector('.hscalegroup') // TODO relic
  });
  
  var widgets = [];
  // TODO: make these widgets follow the same protocol as the others
  widgets.push(new sdr.widgets.SpectrumPlot({
    scheduler: scheduler,
    target: states.spectrum_fft,
    element: document.getElementById("spectrum"),
    view: view,
    radio: states // TODO: remove the need for this
  }));
  widgets.push(new sdr.widgets.WaterfallPlot({
    scheduler: scheduler,
    target: states.spectrum_fft,
    element: document.getElementById("waterfall"),
    view: view,
    radio: states // TODO: remove the need for this
  }));

  Array.prototype.forEach.call(document.querySelectorAll("[data-widget]"), function (el) {
    var typename = el.getAttribute('data-widget');
    var T = sdr.widgets[typename];
    if (!T) {
      console.error('Bad widget type:', el);
      return;
    }
    var stateObj;
    function lookupTarget(el) {
      if (!el || el.nodeType !== Node.ELEMENT_NODE) {
        return states;
      } else if (!el.hasAttribute('data-target')) {
        return lookupTarget(el.parentNode);
      } else {
        return lookupTarget(el.parentNode)[el.getAttribute("data-target")];
      }
    }
    if (el.hasAttribute('data-target')) {
      stateObj = lookupTarget(el);
      if (!stateObj) {
        console.error('Bad widget target:', el);
        return;
      }
    }
    var widget = new T({
      scheduler: scheduler,
      target: stateObj,
      element: el,
      view: view, // TODO should be context-dependent
      freqDB: freqDB,
      radio: states // TODO: remove the need for this
    });
    widgets.push(widget);
    el.parentNode.replaceChild(widget.element, el);
    widget.element.className += ' ' + el.className + ' widget-' + typename; // TODO kludge
  });
  
}());