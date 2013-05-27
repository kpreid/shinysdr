var sdr = sdr || {};
(function () {
  'use strict';
  
  // support components module
  var widget = sdr.widget = {};
  
  // sdr.widgets contains *only* widget types and can be used as a lookup namespace
  var widgets = sdr.widgets = Object.create(null);
  
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }
  
  // Defines the display parameters and coordinate calculations of the spectrum widgets
  function SpectrumView(config) {
    var radio = config.radio;
    var container = config.element;
    var self = this;
    
    var bandwidth, centerFreq;
    
    this.prepare = function prepare() {
      bandwidth = radio.input_rate.get();
      centerFreq = radio.spectrum.getCenterFreq();
    };
    
    // TODO legacy stubs
    this.minLevel = -100;
    this.maxLevel = 0;
    
    // Map a frequency to [0, 1] horizontal coordinate
    this.freqTo01 = function freqTo01(freq) {
      return (1/2 + (freq - centerFreq) / bandwidth);
    };
    this.freqToCSSLeft = function freqToCSSLeft(freq) {
      return this.freqTo01(freq) * 100 + '%';
    };
    this.freqToCSSRight = function freqToCSSRight(freq) {
      return (1 - this.freqTo01(freq)) * 100 + '%';
    };
    // Map [0, 1] coordinate to frequency
    this.freqFrom01 = function freqTo01(x) {
      return centerFreq + (x * 2 - 1) / 2 * bandwidth;
    };
    
    this.addClickToTune = function addClickToTune(element) {
      function clickTune(event) {
        // TODO: works only because we're at the left edge
        var x = event.clientX / parseInt(getComputedStyle(container).width);
        radio.rec_freq.set(self.freqFrom01(x));
        event.stopPropagation();
        event.preventDefault(); // no selection
      }
      element.addEventListener('mousedown', function(event) {
        event.preventDefault();
        document.addEventListener('mousemove', clickTune, true);
        document.addEventListener('mouseup', function(event) {
          document.removeEventListener('mousemove', clickTune, true);
        }, true);
        clickTune(event);
      }, false);
    }
  }
  sdr.widget.SpectrumView = SpectrumView;
  
  function SpectrumPlot(config) {
    var fftCell = config.target;
    var canvas = config.element;
    var view = config.view;
    var states = config.radio;
    
    var ctx = canvas.getContext('2d');
    ctx.canvas.width = parseInt(getComputedStyle(canvas).width); // TODO on resize
    ctx.canvas.height = parseInt(getComputedStyle(canvas).height);
    ctx.lineWidth = 1;
    var cssColor = getComputedStyle(canvas).color;
    var w, h, averageBuffer; // updated in draw
    var lastDrawnCenterFreq = NaN;
    
    function relFreqToX(freq) {
      return w * (1/2 + freq);
    }
    function drawHair(freq) {
      var x = w * view.freqTo01(freq);
      x = Math.floor(x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, ctx.canvas.height);
      ctx.stroke();
    }
    function drawBand(freq1, freq2, center) {
      var x1 = w * view.freqTo01(freq1, center);
      var x2 = w * view.freqTo01(freq2, center);
      ctx.fillRect(x1, 0, x2 - x1, ctx.canvas.height);
    }
    
    this.draw = function () {
      var buffer = fftCell.get();
      w = ctx.canvas.width;
      h = ctx.canvas.height;
      var len = buffer.length;
      var xScale = ctx.canvas.width / len;
      var yScale = -h / (view.maxLevel - view.minLevel);
      var yZero = -view.maxLevel * yScale;
      
      // averaging
      // TODO: Get separate averaged and unaveraged FFTs from server so that averaging behavior is not dependent on frame rate over the network
      if (!averageBuffer
          || averageBuffer.length !== len
          || lastDrawnCenterFreq !== fftCell.getCenterFreq()) {
        console.log('reset');
        lastDrawnCenterFreq = fftCell.getCenterFreq();
        averageBuffer = new Float32Array(buffer);
      }
      for (var i = 0; i < len; i++) {
        averageBuffer[i] = averageBuffer[i] * 0.5 + buffer[i] * 0.5;
      }
      
      ctx.clearRect(0, 0, w, h);
      
      // TODO: marks ought to be part of a distinct widget
      var squelch = Math.floor(yZero + states.squelch_threshold.get() * yScale) + 0.5;
      ctx.strokeStyle = '#700';
      ctx.beginPath();
      ctx.moveTo(0, squelch);
      ctx.lineTo(w, squelch);
      ctx.stroke();
      
      var rec_freq_now = states.rec_freq.get();
      ctx.fillStyle = '#444';
      var bandFilter = states.band_filter.get();
      drawBand(rec_freq_now - bandFilter, rec_freq_now + bandFilter);
      
      ctx.strokeStyle = 'gray';
      drawHair(lastDrawnCenterFreq); // center frequency
      
      ctx.strokeStyle = 'white';
      drawHair(rec_freq_now); // receiver
      
      //ctx.strokeStyle = 'currentColor';  // in spec, doesn't work
      ctx.strokeStyle = cssColor;
      ctx.beginPath();
      ctx.moveTo(0, yZero + averageBuffer[0] * yScale);
      for (var i = 1; i < len; i++) {
        ctx.lineTo(i * xScale, yZero + averageBuffer[i] * yScale);
      }
      ctx.stroke();
      
    };
    view.addClickToTune(canvas);
  }
  widgets.SpectrumPlot = SpectrumPlot;
  
  function WaterfallPlot(config) {
    var fftCell = config.target;
    var canvas = config.element;
    var view = config.view;
    var states = config.radio;

    var ctx = canvas.getContext("2d");
    // circular buffer of ImageData objects
    var slices = [];
    var slicePtr = 0;
    var lastDrawnCenterFreq = NaN;
    this.draw = function () {
      var buffer = fftCell.get();
      var h = canvas.height;
      var currentCenterFreq = fftCell.getCenterFreq();
      
      // rescale to discovered fft size
      var w = buffer.length;
      if (canvas.width !== w) {
        // assignment clears canvas
        canvas.width = w;
        // reallocate
        slices = [];
        slicePtr = 0;
      }
      
      // Find slice to write into
      var ibuf;
      if (slices.length < h) {
        slices.push([ibuf = ctx.createImageData(w, 1), currentCenterFreq]);
      } else {
        var record = slices[slicePtr];
        slicePtr = mod(slicePtr + 1, h);
        ibuf = record[0];
        record[1] = currentCenterFreq;
      }
      
      // low-pass filter to remove the edge-to-center variation from the spectrum (disabled because I'm not sure fiddling with the data like this is a good idea until such time as I make it an option, and so on)
      if (false) {
        var filterspan = 160;
        var filtersum = 0;
        var count = 0;
        var hpf = new Float32Array(w);
        for (var i = -filterspan; i < w + filterspan; i++) {
          if (i + filterspan < w) {
            filtersum += buffer[i + filterspan];
            count++;
          }
          if (i - filterspan >= 0) {
            filtersum -= buffer[i - filterspan];
            count--;
          }
          if (i >= 0 && i < w) {
            hpf[i] = filtersum / count;
          }
        }
      }
      
      // Generate image slice from latest FFT data.
      var xScale = buffer.length / w;
      var cScale = 255 / (view.maxLevel - view.minLevel);
      var cZero = 255 - view.maxLevel * cScale;
      var data = ibuf.data;
      for (var x = 0; x < w; x++) {
        var base = x * 4;
        var i = Math.round(x * xScale);
        var intensity = (buffer[i] /* - hpf[i]*/) * cScale + cZero;
        var redBound = 255 - intensity / 4;
        data[base] = intensity;
        data[base + 1] = Math.min(intensity * 2, redBound);
        data[base + 2] = Math.min(intensity * 4, redBound);
        data[base + 3] = 255;
      }
      
      if (lastDrawnCenterFreq === currentCenterFreq) {
        // Scroll
        ctx.drawImage(ctx.canvas, 0, 0, w, h-1, 0, 1, w, h-1);
        // Paint newest slice
        ctx.putImageData(ibuf, 0, 0);
      } else {
        // Paint slices onto canvas
        ctx.clearRect(0, 0, w, h);
        var sliceCount = slices.length;
        var offsetScale = w / states.input_rate.get();  // TODO parameter for rate
        for (var i = sliceCount - 1; i >= 0; i--) {
          var slice = slices[mod(i + slicePtr, sliceCount)];
          var offset = slice[1] - currentCenterFreq;
          ctx.putImageData(slice[0], Math.round(offset * offsetScale), sliceCount - i);
        }
      }
    };
    view.addClickToTune(canvas);
  }
  widgets.WaterfallPlot = WaterfallPlot;
  
  function Knob(config) {
    var target = config.target;

    var container = this.element = document.createElement("span");
    container.className = "knob";
    var places = [];
    var marks = [];
    for (var i = 9; i >= 0; i--) (function(i) {
      if (i % 3 == 2) {
        var mark = container.appendChild(document.createElement("span"));
        mark.className = "knob-mark";
        mark.textContent = ",";
        mark.style.visibility = "hidden";
        marks.unshift(mark);
        // TODO: make marks responsive to scroll events (doesn't matter which neighbor, or split in the middle, as long as they do something).
      }
      var digit = container.appendChild(document.createElement("span"));
      digit.className = "knob-digit";
      digit.tabIndex = -1;
      var digitText = digit.appendChild(document.createTextNode("\u00A0"));
      places[i] = {element: digit, text: digitText};
      var scale = Math.pow(10, i);
      digit.addEventListener("mousewheel", function(event) { // Not in FF
        // TODO: deal with high-res/accelerated scrolling
        var adjust = event.wheelDelta > 0 ? 1 : -1;
        target.set(adjust * scale + target.get());
        event.preventDefault();
        event.stopPropagation();
      }, true);
      digit.addEventListener("keypress", function(event) {
        // TODO: arrow keys/backspace
        var input = parseInt(String.fromCharCode(event.charCode), 10);
        if (isNaN(input)) return;
        
        var value = target.get();
        var negative = value < 0;
        if (negative) { value = -value; }
        var currentDigitValue = Math.floor(value / scale) % 10;
        value += (input - currentDigitValue) * scale;
        if (negative) { value = -value; }
        target.set(value);
        
        if (i > 0) {
          places[i - 1].element.focus();
        } else {
          digit.blur();
        }
        
        event.preventDefault();
        event.stopPropagation();
      }, true);
    }(i));
    var lastShownValue = -1;
    
    this.draw = function () {
      var value = target.get();
      if (value === lastShownValue) return;
      lastShownValue = value;
      var valueStr = String(Math.round(value));
      var last = valueStr.length - 1;
      for (var i = 0; i < places.length; i++) {
        places[i].text.data = valueStr[last - i] || '\u00A0';
      }
      var numMarks = Math.floor((valueStr.replace("-", "").length - 1) / 3);
      for (var i = 0; i < marks.length; i++) {
        marks[i].style.visibility = i < numMarks ? "visible" : "hidden";
      }
    };
  }
  widgets.Knob = Knob;
  
  function FreqScale(config) {
    var tunerSource = config.target;
    var states = config.radio;
    var freqDB = config.freqDB;
    var view = config.view;

    var outer = this.element = document.createElement("div");
    outer.className = "freqscale";
    var numbers = outer.appendChild(document.createElement("div"));
    numbers.className = "freqscale-numbers";
    var stations = outer.appendChild(document.createElement("div"));
    stations.className = "freqscale-stations";
    var lastShownValue = NaN;
    // TODO: reuse label nodes instead of reallocating...if that's cheaper
    this.draw = function() {
      var centerFreq = tunerSource.get();
      if (centerFreq === lastShownValue) return;
      lastShownValue = centerFreq;
      
      var bandwidth = states.input_rate.get();
      var step = 0.5e6;
      var lower = centerFreq - bandwidth / 2;
      var upper = centerFreq + bandwidth / 2;
      
      numbers.textContent = "";
      for (var i = lower - mod(lower, step); i <= upper; i += step) {
        var label = numbers.appendChild(document.createElement("span"));
        label.className = "freqscale-number";
        label.textContent = (i / 1e6) + "MHz";
        label.style.left = view.freqToCSSLeft(i);
      }
      
      stations.textContent = "";
      freqDB.forEach(function (record) {
        var freq = record.freq;
        if (freq >= lower && freq <= upper) {
          var el = stations.appendChild(document.createElement("span"));
          el.className = "freqscale-station";
          el.textContent = record.label;
          el.style.left = view.freqToCSSLeft(freq);
          // TODO: be an <a> or <button>
          el.addEventListener('click', function(event) {
            states.preset.set(record);
            event.stopPropagation();
          }, false);
        }
      });
    };
  }
  widgets.FreqScale = FreqScale;
  
  function FreqList(config) {
    var rec_freq = config.target;
    var states = config.radio;
    var freqDB = config.freqDB;

    var container = this.element = document.createElement('div');
    container.className = 'freq-list';
    // TODO: general class for widget containers
    
    var filterBox = container.appendChild(document.createElement('input'));
    filterBox.type = 'search';
    filterBox.addEventListener('input', refilter, false);
    
    var list = container.appendChild(document.createElement('select'));
    list.multiple = true;
    list.size = 20;
    
    var last = 0;
    var recordElements = [];
    function updateElements() {
      // TODO proper strategy for detecting freqDB changes
      if (freqDB.length === last) { return false; }
      last = freqDB.length;
      
      recordElements.length = 0;
      freqDB.forEach(function (record) {
        if (record.mode === 'ignore') return;
        var freq = record.freq;
        var item = document.createElement('option');
        item._freq_record = record;
        recordElements.push(item);
        item.textContent = (record.freq / 1e6).toFixed(2) + '  ' + record.mode + '  ' + record.label;
        // TODO: generalize, get supported modes from server
        if (!(record.mode === 'WFM' || record.mode === 'NFM' || record.mode === 'AM')) {
          item.disabled = true;
        }
        item.addEventListener('click', function(event) {
          config.radio.preset.set(record);
          event.stopPropagation();
        }, false);
      });
      
      return true;
    }
    
    function addIfInFilter(item) {
      if (item._freq_record.label.indexOf(lastFilter) !== -1) {
        list.appendChild(item);
      }
    }
    
    var lastFilter;
    function refilter() {
      if (lastFilter !== filterBox.value) {
        updateView();
      }
    }
    function updateView() {
      lastFilter = filterBox.value;
      list.textContent = '';  // clear
      recordElements.forEach(addIfInFilter);
    }
    
    this.draw = function () {
      if (updateElements()) {
        updateView();
      }
      
    };
  }
  widgets.FreqList = FreqList;
  
  function Scanner(config) {
    var radio = config.radio;
    var hw_freq = radio.hw_freq;
    var rec_freq = radio.rec_freq;
    var preset = radio.preset;
    var spectrum = radio.spectrum;
    var freqDB = config.freqDB;

    var scanInterval;
    
    function isSignalPresent() {
      var targetFreq = rec_freq.get();
      var band = 10e3;
      
      var curSpectrum = spectrum.get();
      var bandwidth = radio.input_rate.get();
      var scale = curSpectrum.length / bandwidth;
      var centerFreq = spectrum.getCenterFreq();
      function index(freq) {
        return Math.floor((freq - centerFreq) * scale + curSpectrum.length / 2);
      }
      // TODO needs some averaging to avoid skipping at weak moments
      var low = index(targetFreq - band);
      var high = index(targetFreq + band);
      var localPower = -Infinity;
      for (var i = low; i < high; i++) {
        if (i >= 0 && i < curSpectrum.length) {
          localPower = Math.max(localPower, curSpectrum[i]);
        }
      }
      // Arbitrary fudge factor because our algorithm here is lousy and doesn't match the server's squelch
      return localPower + 10 > radio.squelch_threshold.get();
    }
    
    function findNextChannel() {
      var oldFreq = rec_freq.get();
      // TODO: spatial index for freqDB
      for (var i = 0; i < freqDB.length; i++) {
        var record = freqDB[i];
        var freq = record.freq;
        if (freq <= oldFreq) continue;
        if (record.mode === 'ignore') continue;
        return record;
      }
      // loop around
      return freqDB[0];
    }

    function runScan() {
      if (spectrum.getCenterFreq() !== radio.hw_freq.get()) {
        console.log('Not caught up...');
      } else if (isSignalPresent()) {
        console.log('Holding...');
      } else {
        preset.set(findNextChannel());
      }
    }

    var container = this.element = document.createElement('form');
    container.innerHTML = '<label><input type="checkbox">Scan</label>';
    var toggle = container.querySelector('input');
    toggle.addEventListener('change', function () {
      if (toggle.checked && !scanInterval) {
        scanInterval = setInterval(runScan, 50);
      } else {
        clearInterval(scanInterval);
        scanInterval = undefined;
      }
    }, false);

    this.draw = function () {};
  }
  widgets.Scanner = Scanner;
  
  function Slider(config, getT, setT) {
    var target = config.target;
    var slider = this.element = config.element;

    slider.addEventListener('change', function(event) {
      target.set(setT(slider.valueAsNumber));
    }, false);
    this.draw = function () {
      var value = getT(target.get());
      var shown = slider.valueAsNumber;
      if (Math.abs(value - shown) < 1e-8) return;  // TODO adaptive
      slider.valueAsNumber = value;
    };
  }
  widgets.LinSlider = function(c) { return new Slider(c,
    function (v) { return v; },
    function (v) { return v; }); };
  widgets.LogSlider = function(c) { return new Slider(c,
    function (v) { return Math.log(v) / Math.LN10; },
    function (v) { return Math.pow(10, v); }); };
  
  function Toggle(config) {
    var target = config.target;
    var checkbox = this.element = config.element;

    checkbox.addEventListener('change', function(event) {
      target.set(checkbox.checked);
    }, false);
    this.draw = function () {
      var value = target.get();
      if (value === checkbox.checked) return;
      checkbox.checked = value;
    };
  }
  widgets.Toggle = Toggle;
  
  function Radio(config) {
    var target = config.target;
    var container = this.element = config.element;

    Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
      rb.addEventListener('change', function(event) {
        target.set(rb.value);
      }, false);
    });
    var seen = '';
    this.draw = function () {
      var value = config.target.get();
      if (value === seen) return;
      seen = value;
      Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
        rb.checked = rb.value === seen;
      });
    };
  }
  widgets.Radio = Radio;
  
  Object.freeze(widgets);
}());