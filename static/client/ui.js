(function () {
  'use strict';
  
  var xhrput = sdr.network.xhrput;
  var makeXhrGetter = sdr.network.makeXhrGetter;
  
  var scheduler = new sdr.events.Scheduler();
  
  var freqDB = new sdr.Database();
  freqDB.addAllSystematic();
  freqDB.addFromCatalog('/dbs/');
  
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
        states.band_filter_shape.reload();
      }
    };
  }
  RemoteCell.prototype = Object.create(Cell.prototype, {constructor: {value: RemoteCell}});
  function SpectrumCell() {
    Cell.call(this);
    var VSIZE = Float32Array.BYTES_PER_ELEMENT;
    var fft = new Float32Array(0);
    var centerFreq = NaN;
    // TODO: Better mechanism than XHR
    var spectrumQueued = false;
    var spectrumGetter = makeXhrGetter('/radio/spectrum_fft', function(data, xhr) {
      spectrumQueued = false;
      
      // swap first and second halves for drawing convenience so that center frequency is at halfFFTSize rather than 0
      if (data.byteLength / VSIZE !== fft.length) {
        fft = new Float32Array(data.byteLength / VSIZE);
      }
      var halfFFTSize = fft.length / 2;
      fft.set(new Float32Array(data, 0, halfFFTSize), halfFFTSize);
      fft.set(new Float32Array(data, halfFFTSize * VSIZE, halfFFTSize), 0);
      
      centerFreq = parseFloat(xhr.getResponseHeader('X-SDR-Center-Frequency'));
      
      this.n.notify();
    }.bind(this), true);
    setInterval(function() {
      // TODO: Stop setInterval when not running
      if (states.running.get() && !spectrumQueued) {
        spectrumGetter.go();
        spectrumQueued = true;
      }
    }, 1000/30);
    
    this.get = function() {
      return fft;
    };
    this.getCenterFreq = function() {
      return centerFreq;
    };
  }
  SpectrumCell.prototype = Object.create(Cell.prototype, {constructor: {value: SpectrumCell}});
  
  var pr = '/radio';
  var states = {
    running: new RemoteCell(pr + '/running', false),
    hw_freq: new RemoteCell(pr + '/hw_freq', 0),
    hw_correction_ppm: new RemoteCell(pr + '/hw_correction_ppm', 0),
    mode: new RemoteCell(pr + '/mode', ""),
    rec_freq: new RemoteCell(pr + '/receiver/rec_freq', 0),
    band_filter_shape: new RemoteCell(pr + '/receiver/band_filter_shape', {low: 0, high: 0, width: 0}),
    audio_gain: new RemoteCell(pr + '/receiver/audio_gain', 0),
    squelch_threshold: new RemoteCell(pr + '/receiver/squelch_threshold', 0),
    input_rate: new RemoteCell(pr + '/input_rate', 1000000),
    spectrum: new SpectrumCell(),
  };
  
  sdr.network.addResyncHook(function () {
    for (var key in states) {
      states[key].reload();
    }
  });
  
  // Takes center freq as parameter so it can be used on hypotheticals and so on.
  function frequencyInRange(candidate, centerFreq) {
    var halfBandwidth = states.input_rate.get() / 2;
    if (candidate < halfBandwidth && centerFreq === 0) {
      // recognize tuning for 0Hz gimmick
      return true;
    }
    var fromCenter = Math.abs(candidate - centerFreq) / halfBandwidth;
    return fromCenter > 0.1 && // DC peak
           fromCenter < 0.75;  // loss at edges
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
      states.rec_freq.set(freq);
    }
  };
  
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
    target: states.spectrum,
    element: document.getElementById("spectrum"),
    view: view,
    radio: states // TODO: remove the need for this
  }));
  widgets.push(new sdr.widgets.WaterfallPlot({
    scheduler: scheduler,
    target: states.spectrum,
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
    if (el.hasAttribute('data-target')) {
      stateObj = states[el.getAttribute("data-target")];
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