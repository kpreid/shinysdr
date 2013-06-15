(function () {
  'use strict';
  
  var xhrput = sdr.network.xhrput;
  
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
  
  function ReadWriteCell(name, assumed) {
    Cell.call(this);
    var value = assumed;
    var remoteValue = assumed;
    var inhibit = 0;
    var resetTimeout = undefined;
    this.get = function() { return value; },
    this.set = function(newValue) {
      value = newValue;
      this.n.notify();
      inhibit = Date.now() + 1000;  // TODO adjust value to observed latency
      xhrput(name, JSON.stringify(newValue), function(r) {
        if (Math.floor(r.status / 100) !== 2) {
          // some error or something other than success; revert
          inhibit = 0;
          this._update(remoteValue);
        }
      }.bind(this));
    };
    this._update = function(newValue) {
      remoteValue = newValue;
      if (resetTimeout) clearTimeout(resetTimeout);
      resetTimeout = setTimeout(acceptFromNetwork, inhibit - Date.now());
    };
    var acceptFromNetwork = function() {
      value = remoteValue;
      this.n.notify();
    }.bind(this);
  }
  ReadWriteCell.prototype = Object.create(Cell.prototype, {constructor: {value: ReadWriteCell}});
  
  function ReadCell(name, /* initial */ value, transform) {
    Cell.call(this);
    
    this._update = function(data) {
      value = transform(data);
      this.n.notify();
    };
    
    this.get = function() {
      return value;
    };
  }
  ReadCell.prototype = Object.create(Cell.prototype, {constructor: {value: ReadCell}});
  
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
    
    ReadCell.call(this, '/radio/spectrum_fft', fft, transform);
    
    this.getCenterFreq = function() {
      return centerFreq;
    };
  }
  SpectrumCell.prototype = Object.create(ReadCell.prototype, {constructor: {value: SpectrumCell}});
  
  function buildFromDesc(url, desc) {
    switch (desc.kind) {
      case 'value':
        if (url === '/radio/spectrum_fft') {
          // TODO special case
          return new SpectrumCell();
        } else if (desc.writable) {
          return new ReadWriteCell(url, desc.current);
        } else {
          return new ReadCell(url, desc.current, function (x) { return x; });
        }
      case 'block':
        var sub = {};
        for (var k in desc.children) {
          // TODO: URL should come from server instead of being constructed here
          sub[k] = buildFromDesc(url + '/' + encodeURIComponent(k), desc.children[k]);
        }
        return sub;
      default:
        console.error(url + ': Unknown kind ' + desc.kind + ' in', desc);
        return {};
    }
  }
  
  var rootURL = '/radio';
  var states;
  sdr.network.externalGet(rootURL, 'string', function(text) {
    var desc = JSON.parse(text);
    states = buildFromDesc(rootURL, desc);
    console.log(states);
    gotDesc();
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
  
  function gotDesc() {
    // Kludge to let frequency preset widgets do their thing
    states.preset = {
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
        function go(local, updates) {
          for (var key in updates) {
            if (!local.hasOwnProperty(key)) continue; // TODO warn
            var lobj = local[key];
            if (lobj instanceof Cell) {
              lobj._update(updates[key]); // TODO use parallel write facet structure instead
            } else {
              go(lobj, updates[key]);
            }
          }
        }
        go(states, JSON.parse(event.data));
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
  } // end gotDesc
}());