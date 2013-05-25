(function () {
  "use strict";
  
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }

  function sending(name) {
    return function (obj) { obj[name](); };
  }
  
  function xhrput(url, data) {
    var r = new XMLHttpRequest();
    r.open('PUT', url, true);
    r.setRequestHeader('Content-Type', 'text/plain');
    r.send(data);
    console.log(url, data);
  }
  function makeXhrGetter(url, callback, binary) {
    var r = new XMLHttpRequest();
    if (binary) r.responseType = 'arraybuffer';
    r.onreadystatechange = function() {
      if (r.readyState === 4) {
        callback(binary ? r.response : r.responseText, r);
      }
    };
    return {
      go: function() {
        r.open('GET', url, true);
        r.send();
      }
    };
  }
  
  var freqDB = [];
  
  // Generic FM channels
  (function () {
    // Wikipedia currently says FM channels are numbered like so, but no one uses the numbers. Well, I'll use the numbers, just to start from integers. http://en.wikipedia.org/wiki/FM_broadcasting_in_the_USA
    for (var channel = 200; channel <= 300; channel++) {
      var freqMHz = (channel - 200) * 0.2 + 87.9;
      freqDB.push({
        freq: freqMHz * 1e6,
        mode: 'WFM',
        label: 'FM ' /*+ channel*/ + freqMHz.toFixed(1)
      });
    }
  }());
  
  // Prepare to load real data using JSONP callback
  window.sdr_data = function (json) {
    json.forEach(function (table) {
      var columns = table[0];
      table.slice(1).forEach(function (row) {
        var record = Object.create(null);
        columns.forEach(function (name, index) {
          record[name] = row[index];
        });
        var freqMHz = parseFloat(record.Frequency);
        if (isNaN(freqMHz)) {
          console.log('Bad freq!', record);
        }
        freqDB.push({
          freq: freqMHz * 1e6,
          // TODO: Not sure what distinction the data is actually making
          mode: record.Mode === 'FM' ? 'NFM' : record.Mode,
          label: record.Name
        });
      })
    });

    freqDB.sort(function(a, b) { return a.freq - b.freq; });
  }
  
  // TODO move this
  var view = {
    minLevel: -100,
    maxLevel: 0
  };
  
  function RemoteCell(name, assumed, parser) {
    var value = assumed;
    makeXhrGetter(name, function(remote) {
      value = parser(remote);
    }, false).go();
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
  }
  
  var states = {
    running: new RemoteCell('/running', false, JSON.parse),
    hw_freq: new RemoteCell('/hw_freq', 0, parseFloat),
    mode: new RemoteCell('/mode', "", String),
    rec_freq: new RemoteCell('/rec_freq', 0, parseFloat),
    band_filter: new RemoteCell('/band_filter', 0, parseFloat),
    audio_gain: new RemoteCell('/audio_gain', 0, parseFloat),
    squelch_threshold: new RemoteCell('/squelch_threshold', 0, parseFloat),
    input_rate: new RemoteCell('/input_rate', 1000000, parseInt),
    spectrum: new SpectrumCell(),
  };
  
  // Kludge to let frequency preset widgets do their thing
  states.preset = { set: function(freqRecord) {
    // TODO: magic number
    var freq = freqRecord.freq;
    states.hw_freq.set(freq - 0.2e6);
    states.mode.set(freqRecord.mode);
    states.rec_freq.set(freq);
  }};
  
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
    var T = sdr.widgets[el.getAttribute("data-widget")];
    if (!T) {
      console.error('Bad widget type:', el);
      return;
    }
    var stateObj = states[el.getAttribute("data-target")];
    if (!stateObj) {
      console.error('Bad widget target:', el);
      return;
    }
    var widget = new T({
      target: stateObj,
      element: el,
      freqDB: freqDB,
      radio: states // TODO: remove the need for this
    });
    widgets.push(widget);
    el.parentNode.replaceChild(widget.element, el);
  });
  
  var displayQueued = false;
  function drawWidgetCb(widget) {
    widget.draw();
  }
  function frameCb() {
    displayQueued = false;
    widgets.forEach(drawWidgetCb);
  }
  function doDisplay() {
    if (displayQueued) { return; }
    displayQueued = true;
    window.webkitRequestAnimationFrame(frameCb);
  }
}());