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
    var scheduler = config.scheduler;
    var self = this;

    // used to force the container's scroll range to widen immediately
    var scrollStub = container.appendChild(document.createElement('div'));
    scrollStub.style.height = '1px';
    scrollStub.style.marginTop = '-1px';
    scrollStub.style.visibility = 'hidden';
    
    var n = this.n = new sdr.events.Notifier();
    
    // per-drawing-frame parameters
    var bandwidth, centerFreq, leftFreq, pixelWidth, pixelsPerHertz;
    
    function prepare() {
      // TODO: unbreakable notify loop here; need to be lazy
      bandwidth = radio.input_rate.depend(prepare);
      centerFreq = radio.hw_freq.depend(prepare);
      leftFreq = centerFreq - bandwidth / 2;
      pixelWidth = container.offsetWidth;
      pixelsPerHertz = pixelWidth / bandwidth * zoom;
      n.notify();
      // Note that this uses hw_freq, not the spectrum data center freq. This is correct because we want to align the coords with what we have selected, not the current data; and the WaterfallPlot is aware of this distinction.
    }
    prepare.scheduler = config.scheduler;
    prepare();
    
    window.addEventListener('resize', function (event) {
      scheduler.enqueue(prepare);
    });
    
    container.addEventListener('scroll', function (event) {
      scheduler.enqueue(prepare);
    }, false);
    
    // state
    var zoom = 1;
    
    // TODO legacy stubs
    this.minLevel = -100;
    this.maxLevel = 0;
    
    // Map a frequency to [0, 1] horizontal coordinate
    this.freqToCSSLeft = function freqToCSSLeft(freq) {
      return ((freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSRight = function freqToCSSRight(freq) {
      return (pixelWidth - (freq - leftFreq) * pixelsPerHertz) + 'px';
    };
    this.freqToCSSLength = function freqToCSSLength(freq) {
      return (freq * pixelsPerHertz) + 'px';
    };
    this.leftVisibleFreq = function leftVisibleFreq() {
      return leftFreq + container.scrollLeft / pixelsPerHertz;
    };
    this.rightVisibleFreq = function rightVisibleFreq() {
      return leftFreq + (container.scrollLeft + pixelWidth) / pixelsPerHertz;
    };
    
    // We want the zoom point to stay fixed, but scrollLeft quantizes; this stores a virtual fractional part.
    var fractionalScroll = 0;
    
    this.changeZoom = function changeZoom(delta, cursorX) {
      var maxZoom = radio.spectrum_fft.get().length / MAX_ZOOM_BINS;
      
      cursorX += fractionalScroll;
      var cursor01 = cursorX / pixelWidth;
      
      // Find frequency to keep under the cursor
      var cursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Adjust and clamp zoom
      var oldZoom = zoom;
      zoom *= Math.exp(-delta * 0.0005);
      zoom = Math.min(maxZoom, Math.max(1.0, zoom));
      
      // Recompute parameters now so we can adjust pan (scroll)
      prepare();
      
      var unadjustedCursorFreq = this.leftVisibleFreq() * (1-cursor01) + this.rightVisibleFreq() * cursor01;
      
      // Force scrollable range to update
      var w = pixelWidth * zoom;
      scrollStub.style.width = w + 'px';
      // Current virtual scroll
      var scroll = container.scrollLeft + fractionalScroll;
      // Adjust
      scroll = Math.max(0, Math.min(w - pixelWidth, scroll + (cursorFreq - unadjustedCursorFreq) * pixelsPerHertz));
      // Write back
      container.scrollLeft = scroll;
      fractionalScroll = scroll - container.scrollLeft;
      
      scheduler.enqueue(prepare);
    };
    
    this.addClickToTune = function addClickToTune(element) {
      function clickTune(event) {
        // TODO: works only because we're at the left edge
        radio.receiver.rec_freq.set(
          (event.clientX + container.scrollLeft) / pixelsPerHertz + leftFreq);
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
        if (Math.abs(event.wheelDeltaY) > Math.abs(event.wheelDeltaX)) {
          // TODO: works only because we're at the left edge
          self.changeZoom(-event.wheelDeltaY, event.clientX);
          event.preventDefault();
          event.stopPropagation();
        } else {
          // allow normal horizontal scrolling
        }
      }, true);
    }
  }
  sdr.widget.SpectrumView = SpectrumView;
  
  function SpectrumPlot(config) {
    var fftCell = config.target;
    var canvas = this.element = config.element;
    var view = config.view;
    var states = config.radio;
    
    var ctx = canvas.getContext('2d');
    ctx.lineWidth = 1;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    var cssColor = getComputedStyle(canvas).color;
    var w, h, lvf, rvf, averageBuffer; // updated in draw
    var lastDrawnCenterFreq = NaN;
    
    function freqToCoord(freq) {
      return (freq - lvf) / (rvf-lvf) * w;
    }
    function drawHair(freq) {
      var x = freqToCoord(freq);
      x = Math.floor(x) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, ctx.canvas.height);
      ctx.stroke();
    }
    function drawBand(freq1, freq2) {
      var x1 = freqToCoord(freq1);
      var x2 = freqToCoord(freq2);
      ctx.fillRect(x1, 0, x2 - x1, ctx.canvas.height);
    }
    
    function draw() {
      var buffer = fftCell.depend(draw);
      var bufferCenterFreq = fftCell.getCenterFreq();
      
      view.n.listen(draw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      
      // Fit current layout, clear
      canvas.style.marginLeft = view.freqToCSSLeft(lvf);
      w = canvas.offsetWidth;
      h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
      } else {
        ctx.clearRect(0, 0, w, h);
      }
      
      var len = buffer.length;
      
      var viewCenterFreq = states.hw_freq.depend(draw);
      var bandwidth = states.input_rate.depend(draw);
      var xZero = freqToCoord(viewCenterFreq - bandwidth/2);
      var xFullScale = freqToCoord(viewCenterFreq + bandwidth/2);
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
      
      // TODO: marks ought to be part of a distinct widget
      var squelch = Math.floor(yZero + states.receiver.squelch_threshold.depend(draw) * yScale) + 0.5;
      ctx.strokeStyle = '#700';
      ctx.beginPath();
      ctx.moveTo(0, squelch);
      ctx.lineTo(w, squelch);
      ctx.stroke();
      
      var rec_freq_now = states.receiver.rec_freq.depend(draw);
      var bandFilter = states.receiver.band_filter_shape.depend(draw);
      var fl = bandFilter.low;
      var fh = bandFilter.high;
      var fhw = bandFilter.width / 2;
      ctx.fillStyle = '#3A3A3A';
      drawBand(rec_freq_now + fl - fhw, rec_freq_now + fh + fhw);
      ctx.fillStyle = '#444444';
      drawBand(rec_freq_now + fl + fhw, rec_freq_now + fh - fhw);
      
      ctx.strokeStyle = 'gray';
      drawHair(viewCenterFreq); // center frequency
      
      ctx.strokeStyle = 'white';
      drawHair(rec_freq_now); // receiver
      
      function path() {
        ctx.beginPath();
        ctx.moveTo(-w*3, h*2);
        for (var i = 0; i < len; i++) {
          ctx.lineTo(xZero + i * xScale, yZero + averageBuffer[i] * yScale);
        }
        ctx.lineTo(w*4, h*2);
      }
      
      // Fill is deliberately over stroke. This acts to deemphasize downward stroking of spikes, which tend to occur in noise.
      ctx.fillStyle = 'rgba(64, 100, 100, 0.75)';
      ctx.strokeStyle = cssColor;
      path();
      ctx.stroke();
      path();
      ctx.fill();
    }
    draw.scheduler = config.scheduler;
    view.addClickToTune(canvas);
    
    draw();
  }
  widgets.SpectrumPlot = SpectrumPlot;
  
  function WaterfallPlot(config) {
    var fftCell = config.target;
    var canvas = this.element = config.element;
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

    var newData = false;
    function fftListener() {
      newData = true;
      draw();
    }
    fftListener.scheduler = config.scheduler;
    
    function draw() {
      var buffer = fftCell.depend(fftListener);
      var bufferCenterFreq = fftCell.getCenterFreq();

      var h = canvas.height;
      var bandwidth = states.input_rate.depend(draw);
      var viewCenterFreq = states.hw_freq.depend(draw);
      
      // adjust canvas's display width to zoom
      // TODO this can be independent of other drawing
      view.n.listen(draw);
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
        var offsetScale = w / states.input_rate.depend(draw);  // TODO parameter for rate
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
      
      newData = false;
    }
    draw.scheduler = config.scheduler;
    view.addClickToTune(canvas);
    draw();
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
        //mark.style.visibility = "hidden";
        marks.unshift(mark);
        // TODO: make marks responsive to scroll events (doesn't matter which neighbor, or split in the middle, as long as they do something).
      }
      var digit = container.appendChild(document.createElement("span"));
      digit.className = "knob-digit";
      digit.tabIndex = -1;
      var digitText = digit.appendChild(document.createTextNode('0'));
      places[i] = {element: digit, text: digitText};
      var scale = Math.pow(10, i);
      function spin(direction) {
        target.set(direction * scale + target.get());
      }
      digit.addEventListener("mousewheel", function(event) { // Not in FF
        // TODO: deal with high-res/accelerated scrolling
        spin(event.wheelDelta > 0 ? 1 : -1);
        event.preventDefault();
        event.stopPropagation();
      }, true);
      function focusNext() {
        if (i > 0) {
          places[i - 1].element.focus();
        } else {
          //digit.blur();
        }
      }
      function focusPrev() {
        if (i < places.length - 1) {
          places[i + 1].element.focus();
        } else {
          //digit.blur();
        }
      }
      digit.addEventListener('keydown', function(event) {
        switch (event.keyCode) {  // nominally poorly compatible, but best we can do
          case 0x08: // backspace
          case 0x25: // left
            focusPrev();
            break;
          case 0x27: // right
            focusNext();
            break;
          case 0x26: // up
            spin(1);
            break;
          case 0x28: // down
            spin(-1);
            break;
          default:
            return;
        }
        event.preventDefault();
        event.stopPropagation();
      }, true);
      digit.addEventListener('keypress', function(event) {
        var ch = String.fromCharCode(event.charCode);
        var value = target.get();
        
        switch (ch) {
          case '-':
          case '_':
            target.set(-Math.abs(value));
            return;
          case '+':
          case '=':
            target.set(Math.abs(value));
            return;
          default:
            break;
        }
        
        // TODO I hear there's a new 'input' event which is better for input-ish keystrokes, use that
        var input = parseInt(ch, 10);
        if (isNaN(input)) return;

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

        focusNext();
        event.preventDefault();
        event.stopPropagation();
      });
      
      // remember last place for tabbing
      digit.addEventListener('focus', function (event) {
        places.forEach(function (other) {
          other.element.tabIndex = -1;
        });
        digit.tabIndex = 0;
      }, false);
      
      // spin buttons
      digit.style.position = 'relative';
      [-1, 1].forEach(function (direction) {
        var up = direction > 0;
        var layoutShim = digit.appendChild(document.createElement('span'));
        layoutShim.className = 'knob-spin-button-shim knob-spin-' + (up ? 'up' : 'down');
        var button = layoutShim.appendChild(document.createElement('button'));
        button.className = 'knob-spin-button knob-spin-' + (up ? 'up' : 'down');
        button.textContent = up ? '+' : '-';
        button.addEventListener('click', function (event) {
          spin(direction);
          event.preventDefault();
          event.stopPropagation();
        }, false);
        // If in the normal tab order, its appearing/disappearing causes trouble
        button.tabIndex = -1;
      });
    }(i));
    
    places[places.length - 1].element.tabIndex = 0; // initial tabbable digit
    
    function draw() {
      var value = target.depend(draw);
      var valueStr = String(Math.round(value));
      var last = valueStr.length - 1;
      for (var i = 0; i < places.length; i++) {
        var digit = valueStr[last - i];
        places[i].text.data = digit || '0';
        places[i].element.classList[digit ? 'remove' : 'add']('knob-dim');
      }
      var numMarks = Math.floor((valueStr.replace("-", "").length - 1) / 3);
      for (var i = 0; i < marks.length; i++) {
        marks[i].classList[i < numMarks ? 'remove' : 'add']('knob-dim');
      }
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  widgets.Knob = Knob;
  
  // "exact" as in doesn't drop digits
  function formatFreqExact(freq) {
    var a = Math.abs(freq);
    if (a < 1e3) {
      return String(freq);
    } else if (a < 1e6) {
      return freq / 1e3 + 'k';
    } else if (a < 1e9) {
      return freq / 1e6 + 'M';
    } else {
      return freq / 1e9 + 'G';
    }
  }
  
  function FreqScale(config) {
    var tunerSource = config.target;
    var states = config.radio;
    var dataSource = config.freqDB.groupSameFreq();
    var view = config.view;

    var labelWidth = 60; // TODO actually measure styled text

    var outer = this.element = document.createElement("div");
    outer.className = "freqscale";
    var numbers = outer.appendChild(document.createElement('div'));
    numbers.className = 'freqscale-numbers';
    var labels = outer.appendChild(document.createElement('div'));
    labels.className = 'freqscale-labels';
    // TODO: reuse label nodes instead of reallocating...if that's cheaper
    function draw() {
      var centerFreq = tunerSource.depend(draw);
      view.n.listen(draw);
      
      var bandwidth = states.input_rate.depend(draw);
      var lower = centerFreq - bandwidth / 2;
      var upper = centerFreq + bandwidth / 2;
      
      // TODO: identical to waterfall's use, refactor
      outer.style.marginLeft = view.freqToCSSLeft(centerFreq - bandwidth/2);
      outer.style.width = view.freqToCSSLength(bandwidth);
      
      var maxLabels = outer.offsetWidth / labelWidth;
      
      // We could try to calculate the step using logarithms, but floating-point error would be tiresome.
      // TODO: Make these thresholds less magic-numbery.
      var step = 1;
      while (isFinite(step) && (upper - lower) / step > maxLabels) {
        step *= 10;
      }
      if ((upper - lower) / step < maxLabels * 0.25) {
        step /= 4;
      } else if ((upper - lower) / step < maxLabels * 0.5) {
        step /= 2;
      }
      
      numbers.textContent = '';
      for (var i = lower - mod(lower, step), sanity = 1000;
           sanity > 0 && i <= upper;
           sanity--, i += step) {
        var label = numbers.appendChild(document.createElement('span'));
        label.className = 'freqscale-number';
        label.textContent = formatFreqExact(i);
        label.style.left = view.freqToCSSLeft(i);
      }
      
      labels.textContent = '';
      var query = dataSource.inBand(lower, upper);
      query.n.listen(draw);
      function addChannel(record) {
        var freq = record.freq;
        var el = labels.appendChild(document.createElement('span'));
        el.className = 'freqscale-channel';
        el.textContent = record.label || record.mode;
        el.style.left = view.freqToCSSLeft(freq);
        // TODO: be an <a> or <button>
        el.addEventListener('click', function(event) {
          states.preset.set(record);
          event.stopPropagation();
        }, false);
      }
      query.forEach(function (record) {
        switch (record.type) {
          case 'group':
            // TODO: assumes groups contain only channels
            addChannel({
              freq: record.freq,
              mode: record.grouped[0].mode,
              label: '(' + record.grouped.length + ') ' + record.grouped[0].label
            });
            break;
          case 'channel':
            addChannel(record);
            break;
          case 'band':
            var el = labels.appendChild(document.createElement('span'));
            el.className = 'freqscale-band';
            el.textContent = record.label || record.mode;
            var labelLower = Math.max(record.lowerFreq, lower);
            var labelUpper = Math.min(record.upperFreq, upper);
            el.style.left = view.freqToCSSLeft(labelLower);
            el.style.width = view.freqToCSSLength(labelUpper - labelLower);
            break;
          default:
            break;
        }
      });
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  widgets.FreqScale = FreqScale;
  
  function FreqList(config) {
    var states = config.radio;
    var configKey = 'filterString';
    
    // TODO recognize hardware limits somewhere central
    // TODO should be union of 0-samplerate and 15e6-...
    var dataSource = config.freqDB.inBand(0, 2200e6); 
    
    var container = this.element = document.createElement('div');
    
    var filterBox = container.appendChild(document.createElement('input'));
    filterBox.type = 'search';
    filterBox.placeholder = 'Filter channels...';
    filterBox.value = config.storage.getItem(configKey) || '';
    filterBox.addEventListener('input', refilter, false);
    
    var listOuter = container.appendChild(document.createElement('div'))
    listOuter.className = 'freqlist-box';
    var list = listOuter.appendChild(document.createElement('table'))
      .appendChild(document.createElement('tbody'));
    
    function getElementForRecord(record) {
      // TODO caching should be a WeakMap when possible and should understand the possibility of individual records changing
      if (record._view_element) {
        return record._view_element;
      }
      
      var freq = record.freq;
      var item = document.createElement('tr');
      function cell(className, text) {
        var td = item.appendChild(document.createElement('td'));
        td.className = 'freqlist-cell-' + className;
        td.textContent = text;
        return td;
      }
      record._view_element = item;
      switch (record.type) {
        case 'channel':
          var notes = record.notes || '';
          var label = notes.indexOf(record.label) === 0 /* TODO KLUDGE for current sloppy data sources */ ? notes : record.label;
          cell('freq', (record.freq / 1e6).toFixed(2));
          cell('mode', record.mode === 'ignore' ? '' : record.mode);
          cell('label', label);
          item.title = notes;
          break;
        case 'band':
        default:
          break;
      }
      // TODO: generalize, get supported modes from server
      var supportedModes = ['WFM', 'NFM', 'AM', 'LSB', 'USB', 'VOR'];
      if (supportedModes.indexOf(record.mode) === -1) {
        item.classList.add('freqlist-item-unsupported');
      }
      item.addEventListener('click', function(event) {
        config.radio.preset.set(record);
        event.stopPropagation();
      }, false);
      return item;
    }
    
    var currentFilter = dataSource;
    var lastFilterText = null;
    function refilter() {
      if (lastFilterText !== filterBox.value) {
        lastFilterText = filterBox.value;
        config.storage.setItem(configKey, lastFilterText);
        currentFilter = dataSource.string(lastFilterText).type('channel');
        states.scan_presets.set(currentFilter);
        draw();
      }
    }
    
    function draw() {
      //console.group('draw');
      //console.log(currentFilter.getAll().map(function (r) { return r.label; }));
      currentFilter.n.listen(draw);
      //console.groupEnd();
      list.textContent = '';  // clear
      currentFilter.forEach(function (record) {
        list.appendChild(getElementForRecord(record));
      });
    }
    draw.scheduler = config.scheduler;

    refilter();
  }
  widgets.FreqList = FreqList;
  
  function Scanner(config) {
    var radio = config.radio;
    var hw_freq = radio.hw_freq;
    // TODO: Receiver object gets swapped out so this stops working - find a better design
    //var rec_freq = radio.receiver.rec_freq;
    var preset = radio.preset;
    var spectrum = radio.spectrum_fft;
    var scan_presets = radio.scan_presets;
    
    var scanInterval;
    
    function isSignalPresent() {
      var targetFreq = radio.receiver.rec_freq.get();
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
      return localPower + 10 > radio.receiver.squelch_threshold.get();
    }
    
    function findNextChannel(direction) {
      var oldFreq = radio.receiver.rec_freq.get();
      var db = scan_presets.get();
      if (direction > 0) {
        return db.inBand(oldFreq + 0.5, Infinity).first() || db.first();
      } else if (direction < 0) {
        return db.inBand(-Infinity, oldFreq - 0.5).last() || db.last();
      }
    }

    function runScan() {
      if (spectrum.getCenterFreq() !== radio.hw_freq.get()) {
        console.log('Not caught up...');
      } else if (isSignalPresent()) {
        console.log('Holding...');
      } else {
        preset.set(findNextChannel(1));
      }
    }

    var container = this.element = document.createElement('form');
    container.innerHTML = '<label><input type="checkbox">Scan</label>' +
      '<button type="button">&larr;</button>' +
      '<button type="button">&rarr;</button>';
    var toggle = container.querySelector('input');
    toggle.addEventListener('change', function () {
      if (toggle.checked && !scanInterval) {
        scanInterval = setInterval(runScan, 50);
      } else {
        clearInterval(scanInterval);
        scanInterval = undefined;
      }
    }, false);
    container.querySelectorAll('button')[0].addEventListener('click', function () {
      preset.set(findNextChannel(-1));
    }, false);
    container.querySelectorAll('button')[1].addEventListener('click', function () {
      preset.set(findNextChannel(1));
    }, false);
  }
  widgets.Scanner = Scanner;
  
  function Slider(config, getT, setT) {
    var target = config.target;
    var slider = this.element = config.element;

    slider.addEventListener('change', function(event) {
      target.set(setT(slider.valueAsNumber));
    }, false);
    function draw() {
      var value = getT(target.depend(draw));
      if (!isFinite(value)) {
        value = 0;
      }
      slider.disabled = false;
      slider.valueAsNumber = value;
    }
    draw.scheduler = config.scheduler;
    draw();
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
    function draw() {
      checkbox.checked = target.depend(draw);
    }
    draw.scheduler = config.scheduler;
    draw();
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
    function draw() {
      var value = config.target.depend(draw);
      Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
        rb.checked = rb.value === value;
      });
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  widgets.Radio = Radio;
  
  function leastSignificantSetBit(number) {
      return number & -number;
  }
  var TAU = Math.PI * 2;
  function Angle(config) {
    var target = config.target;
    var container = this.element = document.createElement('div');
    var canvas = container.appendChild(document.createElement('canvas'));
    var text = container.appendChild(document.createElement('span'))
        .appendChild(document.createTextNode(''));
    canvas.width = 61; // odd size for sharp center
    canvas.height = 61;
    var ctx = canvas.getContext('2d');
    
    var w, h, cx, cy, r;
    function polar(method, pr, angle) {
      ctx[method](cx + pr*r * Math.sin(angle), cy - pr*r * Math.cos(angle));
    }
    
    function draw() {
      var valueAngle = target.depend(draw);
      
      text.nodeValue = (valueAngle * (360 / TAU)).toFixed(2) + '\u00B0';
      
      w = canvas.width;
      h = canvas.height;
      cx = w / 2;
      cy = h / 2;
      r = Math.min(w / 2, h / 2) - 1;
      
      ctx.clearRect(0, 0, w, h);
      
      ctx.strokeStyle = '#666';
      ctx.beginPath();
      // circle
      ctx.arc(cx, cy, r, 0, TAU, false);
      // ticks
      for (var i = 0; i < 36; i++) {
        var t = TAU * i / 36;
        var d = !(i % 9) ? 3 : !(i % 3) ? 2 : 1;
        polar('moveTo', 1.0 - 0.1 * d, t);
        polar('lineTo', 1.0, t);
      }
      ctx.stroke();

      // pointer
      ctx.strokeStyle = 'black';
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      polar('lineTo', 1.0, valueAngle);
      ctx.stroke();
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  widgets.Angle = Angle;
  
  Object.freeze(widgets);
}());