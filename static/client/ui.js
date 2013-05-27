(function () {
  'use strict';
  
  var xhrput = sdr.network.xhrput;
  var makeXhrGetter = sdr.network.makeXhrGetter;
  
  var freqDB = [];
  
  // Generic FM channels
  (function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    for (var channel = 200; channel <= 300; channel++) {
      // not computing in MHz because that leads to roundoff error
      var freq = (channel - 200) * 2e5 + 879e5;
      freqDB.push({
        freq: freq,
        mode: 'WFM',
        label: 'FM ' /*+ channel*/ + (freq / 1e6).toFixed(1)
      });
    }
  }());
  
  // Read /dbs/ as an index containing links to CSV files in Chirp <http://chirp.danplanet.com/> generic format. No particular reason for choosing Chirp other than it was a the first source and format of machine-readable channel data I found to experiment with.
  // TODO: Move and refactor this code
  (function () {
    sdr.network.externalGet('/dbs/', 'document', function(indexDoc) {
      console.log(indexDoc);
      var anchors = indexDoc.querySelectorAll('a[href]');
      //console.log('Fetched database index with ' + anchors.length + ' links.');
      Array.prototype.forEach.call(anchors, function (anchor) {
        // Conveniently, the browser resolves URLs for us here
        //console.log(anchor.href);
        sdr.network.externalGet(anchor.href, 'text', function(csv) {
          console.group(anchor.href);
          var csvLines = csv.split(/[\r\n]+/);
          var columns = csvLines.shift().split(/,/);
          csvLines.forEach(function (line) {
            if (/^\s*$/.test(line)) return;
            var fields = line.split(/,/); // TODO handle quotes
            var record = Object.create(null);
            columns.forEach(function (name, index) {
              record[name] = fields[index];
            });
            var freqMHz = parseFloat(record.Frequency);
            if (isNaN(freqMHz)) {
              console.log('Bad freq!', line, record);
            }
            freqDB.push({
              freq: freqMHz * 1e6,
              // TODO: Not sure what distinction the data is actually making
              mode: record.Mode === 'FM' ? 'NFM' : record.Mode || '',
              label: record.Name || '',
              notes: record.Comment || ''
            });
          });
          console.groupEnd();

          freqDB.sort(function(a, b) { return a.freq - b.freq; });
        });
      });
    });
  }());
  
  function RemoteCell(name, assumed, parser) {
    var value = assumed;
    var getter = makeXhrGetter(name, function(remote) {
      value = parser(remote);
    }, false);
    getter.go();
    this.reload = getter.go.bind(getter);
    this.get = function() { return value; },
    this.set = function(newValue) {
      value = newValue;
      xhrput(name, String(newValue));
    };
  }
  function SpectrumCell() {
    var VSIZE = Float32Array.BYTES_PER_ELEMENT;
    var fft = new Float32Array(0);
    var centerFreq = NaN;
    // TODO: Better mechanism than XHR
    var spectrumQueued = false;
    var spectrumGetter = makeXhrGetter('/spectrum_fft', function(data, xhr) {
      spectrumQueued = false;
      
      // swap first and second halves for drawing convenience so that center frequency is at halfFFTSize rather than 0
      if (data.byteLength / VSIZE !== fft.length) {
        fft = new Float32Array(data.byteLength / VSIZE);
      }
      var halfFFTSize = fft.length / 2;
      fft.set(new Float32Array(data, 0, halfFFTSize), halfFFTSize);
      fft.set(new Float32Array(data, halfFFTSize * VSIZE, halfFFTSize), 0);
      
      centerFreq = parseFloat(xhr.getResponseHeader('X-SDR-Center-Frequency'));
      doDisplay();
    }, true);
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
    this.reload = function() {};
  }
  
  var states = {
    running: new RemoteCell('/running', false, JSON.parse),
    hw_freq: new RemoteCell('/hw_freq', 0, parseFloat),
    hw_correction_ppm: new RemoteCell('/hw_correction_ppm', 0, parseFloat),
    mode: new RemoteCell('/mode', "", String),
    rec_freq: new RemoteCell('/rec_freq', 0, parseFloat),
    band_filter: new RemoteCell('/band_filter', 0, parseFloat),
    audio_gain: new RemoteCell('/audio_gain', 0, parseFloat),
    squelch_threshold: new RemoteCell('/squelch_threshold', 0, parseFloat),
    input_rate: new RemoteCell('/input_rate', 1000000, parseInt),
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
        //states.hw_freq.set(freq - 0.2e6);
        // left side, just inside of frequencyInRange's test
        states.hw_freq.set(freq + states.input_rate.get() * 0.374);
      }
      states.rec_freq.set(freq);
    }
  };
  
  // TODO better structure / move to server
  var _scanList = [];
  states.scan_presets = {
    reload: function () {},
    get: function () { return _scanList; },
    set: function (list) { _scanList = list; }
  };
  
  var view = new sdr.widget.SpectrumView({
    radio: states,
    element: document.querySelector('.hscalegroup') // TODO relic
  });
  
  var widgets = [];
  // TODO: make these widgets follow the same protocol as the others
  widgets.push(new sdr.widgets.SpectrumPlot({
    target: states.spectrum,
    element: document.getElementById("spectrum"),
    view: view,
    radio: states // TODO: remove the need for this
  }));
  widgets.push(new sdr.widgets.WaterfallPlot({
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
  
  var displayQueued = false;
  function drawWidgetCb(widget) {
    widget.draw();
  }
  function frameCb() {
    displayQueued = false;
    view.prepare();
    widgets.forEach(drawWidgetCb);
  }
  function doDisplay() {
    if (displayQueued) { return; }
    displayQueued = true;
    window.webkitRequestAnimationFrame(frameCb);
  }
}());