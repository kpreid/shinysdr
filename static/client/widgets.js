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
  var MAX_ZOOM_BINS = 60; // Maximum zoom shows this many FFT bins
  function SpectrumView(config) {
    var radio = config.radio;
    var container = config.element;
    var self = this;
    
    // per-drawing-frame parameters updated by prepare()
    var bandwidth, centerFreq;
    
    this.prepare = function prepare() {
      bandwidth = radio.input_rate.get();
      centerFreq = radio.hw_freq.get();
      // Note that this uses hw_freq, not the spectrum data center freq. This is correct because we want to align the coords with what we have selected, not the current data; and the WaterfallPlot is aware of this distinction.
    };
    
    // state
    var pan = 0;
    var zoom = 1;
    
    // TODO legacy stubs
    this.minLevel = -100;
    this.maxLevel = 0;
    
    // Map a frequency to [0, 1] horizontal coordinate
    this.freqTo01 = function freqTo01(freq) {
      return pan + (1/2 + (freq - centerFreq) / bandwidth) * zoom;
    };
    this.freqToCSSLeft = function freqToCSSLeft(freq) {
      return this.freqTo01(freq) * 100 + '%';
    };
    this.freqToCSSRight = function freqToCSSRight(freq) {
      return (1 - this.freqTo01(freq)) * 100 + '%';
    };
    this.freqToCSSLength = function freqToCSSLength(freq) {
      return (freq / bandwidth * 100 * zoom) + '%';
    };
    // Map [0, 1] coordinate to frequency
    this.freqFrom01 = function freqFrom01(x) {
      var unzoomedX = (x - pan) / zoom;
      return centerFreq + (unzoomedX * 2 - 1) / 2 * bandwidth;
    };
    
    this.changeZoom = function changeZoom(delta, cursor01) {
      var maxZoom = radio.spectrum.get().length / MAX_ZOOM_BINS;
      
      // Find frequency to keep under the cursor
      var cursorFreq = this.freqFrom01(cursor01);
      
      // Adjust and clamp zoom
      var oldZoom = zoom;
      zoom *= Math.exp(-delta * 0.0005);
      zoom = Math.min(maxZoom, Math.max(1.0, zoom));
      
      // Adjust and clamp pan
      pan = 0; // reset for following freqTo01 calculation
      pan = cursor01 - this.freqTo01(cursorFreq);
      pan = Math.max(1 - zoom, Math.min(0, pan));
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
        if (event.button !== 0) return;  // don't react to right-clicks etc.
        event.preventDefault();
        document.addEventListener('mousemove', clickTune, true);
        document.addEventListener('mouseup', function(event) {
          document.removeEventListener('mousemove', clickTune, true);
        }, true);
        clickTune(event);
      }, false);
      element.addEventListener('mousewheel', function(event) { // Not in FF
        // TODO: works only because we're at the left edge
        var x = event.clientX / parseInt(getComputedStyle(container).width);
        self.changeZoom(event.wheelDelta, x);
        event.preventDefault();
        event.stopPropagation();
      }, true);
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
    function drawBand(freq1, freq2) {
      var x1 = w * view.freqTo01(freq1);
      var x2 = w * view.freqTo01(freq2);
      ctx.fillRect(x1, 0, x2 - x1, ctx.canvas.height);
    }
    
    var lastGeneration = 0;
    this.draw = function () {
      if (lastGeneration === (lastGeneration = fftCell.getGeneration())) return;
      var buffer = fftCell.get();
      w = ctx.canvas.width;
      h = ctx.canvas.height;
      var len = buffer.length;
      var bufferCenterFreq = fftCell.getCenterFreq();
      var viewCenterFreq = states.hw_freq.get();
      var bandwidth = states.input_rate.get();
      var xZero = view.freqTo01(viewCenterFreq - bandwidth/2) * ctx.canvas.width;
      var xFullScale = view.freqTo01(viewCenterFreq + bandwidth/2) * ctx.canvas.width;
      var xScale = (xFullScale - xZero) / len;
      var yScale = -h / (view.maxLevel - view.minLevel);
      var yZero = -view.maxLevel * yScale;
      
      // averaging
      // TODO: Get separate averaged and unaveraged FFTs from server so that averaging behavior is not dependent on frame rate over the network
      if (!averageBuffer
          || averageBuffer.length !== len
          || (lastDrawnCenterFreq !== bufferCenterFreq
              && !isNaN(bufferCenterFreq))) {
        lastDrawnCenterFreq = bufferCenterFreq;
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
      drawHair(viewCenterFreq); // center frequency
      
      ctx.strokeStyle = 'white';
      drawHair(rec_freq_now); // receiver
      
      //ctx.strokeStyle = 'currentColor';  // in spec, doesn't work
      ctx.strokeStyle = cssColor;
      ctx.beginPath();
      ctx.moveTo(xZero, yZero + averageBuffer[0] * yScale);
      for (var i = 1; i < len; i++) {
        ctx.lineTo(xZero + i * xScale, yZero + averageBuffer[i] * yScale);
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

    // I have read recommendations that color gradient scales should not involve more than two colors, as certain transitions between colors read as overly significant. However, in this case (1) we are not intending the waterfall chart to be read quantitatively, and (2) we want to have distinguishable small variations across a large dynamic range.
    var colors = [
      [0, 0, 0],
      [0, 0, 255],
      [0, 200, 255],
      [255, 255, 0],
      [255, 0, 0]
    ];

    var ctx = canvas.getContext("2d");
    // circular buffer of ImageData objects
    var slices = [];
    var slicePtr = 0;
    var lastDrawnCenterFreq = NaN;

    var lastGeneration = 0;
    this.draw = function () {
      var buffer = fftCell.get();
      var h = canvas.height;
      var bandwidth = states.input_rate.get();
      var bufferCenterFreq = fftCell.getCenterFreq();
      var viewCenterFreq = states.hw_freq.get();
      
      // adjust canvas's display width to zoom
      // TODO don't recompute
      canvas.style.marginLeft = view.freqToCSSLeft(viewCenterFreq - bandwidth/2);
      canvas.style.width = view.freqToCSSLength(bandwidth);
      
      // rescale to discovered fft size
      var w = buffer.length;
      if (canvas.width !== w) {
        // assignment clears canvas
        canvas.width = w;
        // reallocate
        slices = [];
        slicePtr = 0;
      }
      
      // can't draw with w=0
      if (w === 0) {
        return;
      }
      
      // New data, or just repainting?
      var newData = lastGeneration !== (lastGeneration = fftCell.getGeneration());
      
      if (newData) {
        // Find slice to write into
        var ibuf;
        if (slices.length < h) {
          slices.push([ibuf = ctx.createImageData(w, 1), bufferCenterFreq]);
        } else {
          var record = slices[slicePtr];
          slicePtr = mod(slicePtr + 1, h);
          ibuf = record[0];
          record[1] = bufferCenterFreq;
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
        var minInterpColor = 0;
        var maxInterpColor = colors.length - 2;
        var cScale = (colors.length - 1) / (view.maxLevel - view.minLevel);
        var cZero = (colors.length - 1) - view.maxLevel * cScale;
        var data = ibuf.data;
        for (var x = 0; x < w; x++) {
          var base = x * 4;
          var i = Math.round(x * xScale);
          var colorVal = (buffer[i] /* - hpf[i]*/) * cScale + cZero;
          var colorIndex = Math.max(minInterpColor, Math.min(maxInterpColor, Math.floor(colorVal)));
          var colorInterp1 = colorVal - colorIndex;
          var colorInterp0 = 1 - colorInterp1;
          var color0 = colors[colorIndex];
          var color1 = colors[colorIndex + 1];
          data[base    ] = color0[0] * colorInterp0 + color1[0] * colorInterp1;
          data[base + 1] = color0[1] * colorInterp0 + color1[1] * colorInterp1;
          data[base + 2] = color0[2] * colorInterp0 + color1[2] * colorInterp1;
          data[base + 3] = 255;
        }
      }
      
      if (newData && lastDrawnCenterFreq === viewCenterFreq) {
        // Scroll
        ctx.drawImage(ctx.canvas, 0, 0, w, h-1, 0, 1, w, h-1);
        // Paint newest slice
        ctx.putImageData(ibuf, 0, 0);
      } else if (lastDrawnCenterFreq !== viewCenterFreq) {
        lastDrawnCenterFreq = viewCenterFreq;
        // Paint all slices onto canvas
        ctx.fillStyle = '#777';
        var sliceCount = slices.length;
        var offsetScale = w / states.input_rate.get();  // TODO parameter for rate
        for (var i = sliceCount - 1; i >= 0; i--) {
          var slice = slices[mod(i + slicePtr, sliceCount)];
          var offset = slice[1] - viewCenterFreq;
          var y = sliceCount - i;
          
          // fill background so scrolling is of an opaque image
          ctx.fillRect(0, y, w, 1);
          
          // paint slice
          ctx.putImageData(slice[0], Math.round(offset * offsetScale), y);
        }
        ctx.fillRect(0, y+1, w, h);
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
        var currentDigitValue;
        if (scale === 1) {
          // When setting last digit, clear any hidden fractional digits as well
          currentDigitValue = (value / scale) % 10;
        } else {
          currentDigitValue = Math.floor(value / scale) % 10;
        }
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
    var numbers = outer.appendChild(document.createElement('div'));
    numbers.className = 'freqscale-numbers';
    var labels = outer.appendChild(document.createElement('div'));
    labels.className = 'freqscale-labels';
    var lastShownValue = NaN;
    var lastViewParam = NaN;
    // TODO: reuse label nodes instead of reallocating...if that's cheaper
    this.draw = function() {
      var centerFreq = tunerSource.get();
      var viewParam = '' + view.freqTo01(0) + view.freqTo01(centerFreq);  // TODO kludge
      if (centerFreq === lastShownValue && viewParam === lastViewParam) return;
      lastShownValue = centerFreq;
      lastViewParam = viewParam;
      
      var bandwidth = states.input_rate.get();
      var lower = view.freqFrom01(0);
      var upper = view.freqFrom01(1);
      
      // We could try to calculate the step using logarithms, but floating-point error would be tiresome.
      // TODO: Make these thresholds less magic-numbery, and take the font size/screen size into consideration.
      var step = 1;
      while (isFinite(step) && (upper - lower) / step > 10) {
        step *= 10;
      }
      if ((upper - lower) / step < 2) {
        step /= 4;
      } else if ((upper - lower) / step < 4) {
        step /= 2;
      }
      
      numbers.textContent = '';
      for (var i = lower - mod(lower, step), sanity = 1000;
           sanity > 0 && i <= upper;
           sanity--, i += step) {
        var label = numbers.appendChild(document.createElement('span'));
        label.className = 'freqscale-number';
        label.textContent = (i / 1e6) + 'M';  // Hz is obvious
        label.style.left = view.freqToCSSLeft(i);
      }
      
      labels.textContent = '';
      freqDB.inBand(lower, upper).forEach(function (record) {
        switch (record.type) {
          case 'channel':
            var freq = record.freq;
            var el = labels.appendChild(document.createElement('span'));
            el.className = 'freqscale-channel';
            el.textContent = record.label;
            el.style.left = view.freqToCSSLeft(freq);
            // TODO: be an <a> or <button>
            el.addEventListener('click', function(event) {
              states.preset.set(record);
              event.stopPropagation();
            }, false);
            break;
          case 'band':
            var el = labels.appendChild(document.createElement('span'));
            el.className = 'freqscale-band';
            el.textContent = record.label;
            el.style.left = view.freqToCSSLeft(record.lowerFreq);
            el.style.width = view.freqToCSSLength(record.upperFreq - record.lowerFreq);
            break;
          default:
            break;
        }
      });
    };
  }
  widgets.FreqScale = FreqScale;
  
  function FreqList(config) {
    var rec_freq = config.target;
    var states = config.radio;
    var dataSource = config.freqDB.inBand(50e6, 2200e6); // TODO recognize hardware limits somewhere central
    
    var container = this.element = document.createElement('div');
    
    var filterBox = container.appendChild(document.createElement('input'));
    filterBox.type = 'search';
    filterBox.placeholder = 'Filter channels...';
    filterBox.addEventListener('input', refilter, false);
    
    var list = container.appendChild(document.createElement('select'));
    list.multiple = true;
    list.size = 20;
    
    function getElementForRecord(record) {
      if (record._view_element) {  // TODO HORRIBLE KLUDGE
        return record._view_element;
      } else {
        var freq = record.freq;
        var item = document.createElement('option');
        record._view_element = item;
        switch (record.type) {
          case 'channel':
            var notes = record.notes || '';
            var label = notes.indexOf(record.label) === 0 /* TODO KLUDGE for current sloppy data sources */ ? notes : record.label;
            item.textContent = (record.freq / 1e6).toFixed(2) + ' (' + record.mode + ') ' + label;
            item.title = notes;
            break;
          case 'band':
          default:
            break;
        }
        // TODO: generalize, get supported modes from server
        if (!(record.mode === 'WFM' || record.mode === 'NFM' || record.mode === 'AM')) {
          item.disabled = true;
        }
        item.addEventListener('click', function(event) {
          config.radio.preset.set(record);
          event.stopPropagation();
        }, false);
        return item;
      }
    }
    
    var currentFilter = dataSource;
    var lastFilterText = null;
    function refilter() {
      if (lastFilterText !== filterBox.value) {
        lastFilterText = filterBox.value;
        currentFilter = dataSource.string(lastFilterText).type('channel');
        states.scan_presets.set(currentFilter);
      }
    }
    refilter();
    
    var lastF, lastG;
    this.draw = function () {
      if (currentFilter === lastF && currentFilter.getGeneration() === lastG) return;
      lastF = currentFilter;
      lastG = currentFilter.getGeneration();
      
      list.textContent = '';
      currentFilter.forEach(function (record) {
        list.appendChild(getElementForRecord(record));
      });
    };
  }
  widgets.FreqList = FreqList;
  
  function Scanner(config) {
    var radio = config.radio;
    var hw_freq = radio.hw_freq;
    var rec_freq = radio.rec_freq;
    var preset = radio.preset;
    var spectrum = radio.spectrum;
    var scan_presets = radio.scan_presets;

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
      var db = scan_presets.get();
      return db.inBand(oldFreq + 0.5, Infinity).first() || db.first();
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