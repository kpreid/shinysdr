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
  
  // TODO get this from server
  var allModes = Object.create(null);
  allModes.WFM = 'Wide FM';
  allModes.NFM = 'Narrow FM';
  allModes.AM = 'AM';
  allModes.LSB = 'Lower SSB';
  allModes.USB = 'Upper SSB';
  allModes.VOR = 'VOR';
  
  // TODO this belongs somewhere else
  function StorageNamespace(base, prefix) {
    this._base = base;
    this._prefix = prefix;
  }
  StorageNamespace.prototype.getItem = function (key) {
    return this._base.getItem(this._prefix + key);
  };
  StorageNamespace.prototype.setItem = function (key, value) {
    return this._base.setItem(this._prefix + key, value);
  };
  StorageNamespace.prototype.removeItem = function (key) {
    return this._base.removeItem(this._prefix + key);
  };
  
  // TODO figure out what this does and give it a better name
  function Context(config) {
    this.radio = config.radio;
    this.scheduler = config.scheduler;
    this.freqDB = config.freqDB;
    this.spectrumView = config.spectrumView;
  }
  sdr.widget.Context = Context;
  
  function createWidgetsList(rootTarget, context, list) {
    Array.prototype.forEach.call(list, function (child) {
      createWidgets(rootTarget, context, child);
    });
  }
  function createWidgets(rootTarget, context, node) {
    var scheduler = context.scheduler;
    if (node.hasAttribute && node.hasAttribute('data-widget')) {
      var stateObj;
      var typename = node.getAttribute('data-widget');
      var T = sdr.widgets[typename];
      if (!T) {
        console.error('Bad widget type:', node);
        return;
      }
      var stateObj;
      if (node.hasAttribute('data-target')) {
        var targetStr = node.getAttribute('data-target');
        stateObj = rootTarget[targetStr];
        if (!stateObj) {
          node.parentNode.replaceChild(document.createTextNode('[Missing: ' + targetStr + ']'), node);
          return;
        }
      }
      var widget = new T({
        scheduler: scheduler,
        target: stateObj,
        element: node,
        view: context.spectrumView, // TODO should be context-dependent
        freqDB: context.freqDB, // TODO: remove the need for this
        radio: context.radio, // TODO: remove the need for this
        storage: node.hasAttribute('id') ? new StorageNamespace(localStorage, 'sdr.widgetState.' + node.getAttribute('id') + '.') : null
      });
      node.parentNode.replaceChild(widget.element, node);
      widget.element.className += ' ' + node.className + ' widget-' + typename; // TODO kludge
      
      // allow widgets to embed widgets
      createWidgetsList(stateObj || rootTarget, context, widget.element.childNodes);
    } else if (node.hasAttribute && node.hasAttribute('data-target')) (function () {
      var html = document.createDocumentFragment();
      while (node.firstChild) html.appendChild(node.firstChild);
      function go() {
        // TODO defend against JS-significant keys
        var target = rootTarget[node.getAttribute('data-target')];
        target._deathNotice.listen(go);
        
        node.textContent = ''; // fast clear
        node.appendChild(html.cloneNode(true));
        createWidgetsList(target, context, node.childNodes);
      }
      go.scheduler = scheduler;
      go();

    }()); else if (node.nodeName === 'DETAILS' && node.hasAttribute('id')) {
      // Make any ID'd <details> element persistent
      var ns = new StorageNamespace(localStorage, 'sdr.elementState.' + node.id + '.');
      var stored = ns.getItem('detailsOpen');
      if (stored !== null) node.open = JSON.parse(stored);
      new MutationObserver(function(mutations) {
        ns.setItem('detailsOpen', JSON.stringify(node.open));
      }).observe(node, {attributes: true, attributeFilter: ['open']});
      createWidgetsList(rootTarget, context, node.childNodes);

    } else {
      createWidgetsList(rootTarget, context, node.childNodes);
    }
  }
  sdr.widget.createWidgets = createWidgets;
  
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
      centerFreq = radio.source.freq.depend(prepare);
      leftFreq = centerFreq - bandwidth / 2;
      pixelWidth = container.offsetWidth;
      pixelsPerHertz = pixelWidth / bandwidth * zoom;
      n.notify();
      // Note that this uses source.freq, not the spectrum data center freq. This is correct because we want to align the coords with what we have selected, not the current data; and the WaterfallPlot is aware of this distinction.
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
    
    // exported for the sake of createWidgets -- TODO proper factoring?
    this.scheduler = scheduler;
    
    // TODO legacy stubs
    this.minLevel = -100;
    this.maxLevel = 0;
    
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
        if (radio.receiver.rec_freq) {
          // TODO: X calc works only because we're at the left edge
          radio.receiver.rec_freq.set(
            (event.clientX + container.scrollLeft) / pixelsPerHertz + leftFreq);
        }
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
    
    // used as listener by draw() for fftCell
    function newFFTFrame() {
      var buffer = fftCell.get();
      var bufferCenterFreq = fftCell.getCenterFreq();
      var len = buffer.length;
      
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
      
      draw.scheduler.enqueue(draw);
    }
    newFFTFrame.scheduler = config.scheduler;
    
    function draw() {
      fftCell.n.listen(newFFTFrame);
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
      
      var len = averageBuffer.length;
      
      var viewCenterFreq = states.source.freq.depend(draw);
      var bandwidth = states.input_rate.depend(draw);
      var xZero = freqToCoord(viewCenterFreq - bandwidth/2);
      var xFullScale = freqToCoord(viewCenterFreq + bandwidth/2);
      var xScale = (xFullScale - xZero) / len;
      var yScale = -h / (view.maxLevel - view.minLevel);
      var yZero = -view.maxLevel * yScale;
      
      // TODO: marks ought to be part of a distinct widget
      var squelch_threshold_cell = states.receiver.squelch_threshold;
      if (squelch_threshold_cell) {
        var squelch = Math.floor(yZero + squelch_threshold_cell.depend(draw) * yScale) + 0.5;
        ctx.strokeStyle = '#700';
        ctx.beginPath();
        ctx.moveTo(0, squelch);
        ctx.lineTo(w, squelch);
        ctx.stroke();
      }
      
      var rec_freq_cell = states.receiver.rec_freq;
      var band_filter_cell = states.receiver.band_filter_shape;
      if (rec_freq_cell) {
        var rec_freq_now = rec_freq_cell.depend(draw);
        if (band_filter_cell) {
          var bandFilter = band_filter_cell.depend(draw);
          var fl = bandFilter.low;
          var fh = bandFilter.high;
          var fhw = bandFilter.width / 2;
          ctx.fillStyle = '#3A3A3A';
          drawBand(rec_freq_now + fl - fhw, rec_freq_now + fh + fhw);
          ctx.fillStyle = '#444444';
          drawBand(rec_freq_now + fl + fhw, rec_freq_now + fh - fhw);
        }
      }
      
      ctx.strokeStyle = 'gray';
      drawHair(viewCenterFreq); // center frequency
      
      if (rec_freq_cell) {
        ctx.strokeStyle = 'white';
        drawHair(rec_freq_now); // receiver
      }
      
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
    
    newFFTFrame();
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
      var viewCenterFreq = states.source.freq.depend(draw);
      
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
    var scheduler = config.scheduler;
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
      // TODO caching should be a WeakMap when possible
      if (record._view_element) {
        record._view_element._sdr_drawHook();
        return record._view_element;
      }
      
      var item = document.createElement('tr');
      var drawFns = [];
      function cell(className, textFn) {
        var td = item.appendChild(document.createElement('td'));
        td.className = 'freqlist-cell-' + className;
        drawFns.push(function() {
          td.textContent = textFn();
        });
      }
      record._view_element = item;
      switch (record.type) {
        case 'channel':
          cell('freq', function () { return (record.freq / 1e6).toFixed(2); });
          cell('mode', function () { return record.mode === 'ignore' ? '' : record.mode;  });
          cell('label', function () { 
            var notes = record.notes;
            return notes.indexOf(record.label) === 0 /* TODO KLUDGE for current sloppy data sources */ ? notes : record.label;
          });
          drawFns.push(function () {
            item.title = record.notes;
          });
          break;
        case 'band':
        default:
          break;
      }
      if (!(record.mode in allModes)) {
        item.classList.add('freqlist-item-unsupported');
      }
      item.addEventListener('click', function(event) {
        config.radio.preset.set(record);
        event.stopPropagation();
      }, false);
      
      function draw() {
        drawFns.forEach(function (f) { f(); });
        if (record.offsetWidth > 0) { // rough 'is in DOM tree' test
          record.n.listen(draw);
        }
      }
      draw.scheduler = scheduler;
      item._sdr_drawHook = draw;
      draw();
      
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
    draw.scheduler = scheduler;

    refilter();
  }
  widgets.FreqList = FreqList;
  
  var NO_RECORD = {};
  function RecordCellPropCell(recordCell, prop) {
    this.get = function () {
      var record = recordCell.get();
      return record ? record[prop] : NO_RECORD;
    };
    this.set = function (value) {
      recordCell.get()[prop] = value;
    };
    this.n = {
      listen: function (l) {
        var now = recordCell.get();
        if (now) now.n.listen(l);
        recordCell.n.listen(l);
      }
    };
  }
  RecordCellPropCell.prototype = Object.create(sdr.network.Cell.prototype, {constructor: {value: RecordCellPropCell}});
  
  function RecordDetails(config) {
    var recordCell = config.target;
    var scheduler = config.scheduler;
    var container = this.element = config.element;
    
    var inner = container.appendChild(document.createElement('div'));
    inner.className = 'RecordDetails-fields';
    
    function labeled(name, field) {
      var label = inner.appendChild(document.createElement('label'));
      
      var text = label.appendChild(document.createElement('span'));
      text.className = 'RecordDetails-labeltext';
      text.textContent = name;
      
      label.appendChild(field);
      return field;
    }
    function formFieldHooks(field, cell) {
      function draw() {
        var now = cell.depend(draw);
        if (now === NO_RECORD) {
          field.disabled = true;
        } else {
          field.disabled = false;
          if (field.value !== now) field.value = now;
        }
      }
      draw.scheduler = config.scheduler;
      field.addEventListener('change', function(event) {
        if (field.value !== cell.get()) {
          cell.set(field.value);
        }
      });
      draw();
    }
    function input(cell, name) {
      var field = document.createElement('input');
      formFieldHooks(field, cell);
      return labeled(name, field);
    }
    function menu(cell, name, values) {
      var field = document.createElement('select');
      for (var key in values) {
        var option = field.appendChild(document.createElement('option'));
        option.value = key;
        option.textContent = values[key];
      }
      formFieldHooks(field, cell);
      return labeled(name, field);
    }
    function textarea(cell) {
      var field = container.appendChild(document.createElement('textarea'));
      formFieldHooks(field, cell);
      return field;
    }
    function cell(prop) {
      return new RecordCellPropCell(recordCell, prop);
    }
    menu(cell('type'), 'Type', {'channel': 'Channel', 'band': 'Band'});
    input(cell('freq'), 'Freq');  // TODO add lowerFreq/upperFreq display
    menu(cell('mode'), 'Mode', allModes);
    input(cell('label'), 'Label');
    textarea(cell('notes'));
  }
  widgets.RecordDetails = RecordDetails;
  
  // Silly single-purpose widget 'till we figure out more where the UI is going
  function SaveButton(config) {
    var radio = config.radio; // use mode, receiver
    this.element = config.element;

    var button = config.element.querySelector('button');
    button.disabled = false;
    button.onclick = function (event) {
      var record = {
        type: 'channel',
        freq: radio.receiver.rec_freq.get(),
        mode: radio.mode.get(), // TODO should be able to take from receiver
        label: 'untitled'
      };
      radio.targetDB.add(record);
      radio.preset.set(record);
    };
  }
  widgets.SaveButton = SaveButton;
  
  function Scanner(config) {
    var radio = config.radio;
    var hw_freq = radio.source.freq;
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
      if (spectrum.getCenterFreq() !== radio.source.freq.get()) {
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

    var seen = Object.create(null);
    Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
      var value = rb.value;
      seen[value] = true;
      if (target.type) {
        rb.disabled = !(rb.value in target.type.values);
      }
    });

    if (target.type) {
      Object.keys(target.type.values).forEach(function (value) {
        if (seen[value]) return;
        var label = container.appendChild(document.createElement('label'));
        var rb = label.appendChild(document.createElement('input'));
        label.appendChild(document.createTextNode(' ' + target.type.values[value]));
        rb.type = 'radio';
        rb.value = value;
      });
    }

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