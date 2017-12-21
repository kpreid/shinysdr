// Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

'use strict';

define([
  '../events',
  '../math',
  '../measviz',
  '../types',
  '../values',
  '../widget',
], (
  import_events,
  import_math,
  unused_measviz,  // not a module, creates globals
  import_types,
  import_values,
  import_widget
) => {
  const {
    AddKeepDrop,
    Clock,
  } = import_events;
  const {
    mod,
  } = import_math;
  const {
    EnumT,
    NoticeT,
    QuantityT,
    RangeT,
    TimestampT,
    anyT,
    blockT,
    booleanT,
    numberT,
    stringT,
    trackT,
  } = import_types;
  const {
    Cell,
    CommandCell,
    ConstantCell,
    DerivedCell,
    LocalReadCell,
    getInterfaces,
  } = import_values;
  const {
    createWidgetExt,
  } = import_widget;
  
  const exports = {};
  
  function insertUnitIfPresent(type, container) {
    const unitSymbol = type.getNumericUnit().symbol;
    if (unitSymbol !== '') {
      // TODO: use SI prefixes for large/small values when OK
      const el = container.appendChild(document.createElement('span'));
      el.classList.add('unit-symbol');
      el.appendChild(document.createTextNode('\u00A0' + unitSymbol));
    }
  }

  // Superclass for a sub-block widget
  function Block(config, optSpecial, optEmbed) {
    const block = config.target.depend(config.rebuildMe);
    block._reshapeNotice.listen(config.rebuildMe);
    const container = this.element = config.element;
    let appendTarget = container;
    const claimed = Object.create(null);
    let claimedEverything = false;
    
    //container.textContent = '';
    container.classList.add('frame');
    if (config.shouldBePanel && !optEmbed) {
      container.classList.add('panel');
    }
    
    // TODO: We ought to display these in some way. But right now the only labels-for-blocks are displayed separately using explicit code...
    container.removeAttribute('title');
    
    function getAppend() {
      if (appendTarget === 'details') {
        appendTarget = container.appendChild(document.createElement('details'));
        if (config.idPrefix) {
          // hook for state persistence
          appendTarget.id = config.idPrefix + '_details';
        }
        appendTarget.appendChild(document.createElement('summary')).textContent = 'More';
      }
      
      return appendTarget;
    }
    
    function addWidget(name, widgetType, optBoxLabel) {
      var wEl = document.createElement('div');
      if (optBoxLabel !== undefined) { wEl.classList.add('panel'); }
      
      var targetCell;
      if (typeof name === 'string') {
        claimed[name] = true;
        targetCell = block[name];
        if (!targetCell) {
          return;
        }
        if (config.idPrefix) {
          wEl.id = config.idPrefix + name;
        }
      } else if (name === null) {
        targetCell = new ConstantCell(block, blockT);
      } else if ('get' in name) {  // sanity check, not to be used as type discrimination
        targetCell = name;
      } else {
        throw new Error('not understood target for addWidget: ' + name);
      }
      
      let widgetCtor;
      if (typeof widgetType === 'string') {
        throw new Error('string widget types being deprecated, not supported here');
      } else if (typeof widgetType === 'function') {
        widgetCtor = widgetType;
      } else if (widgetType === undefined || widgetType === null) {
        widgetCtor = PickWidget;
        if (typeof name === 'string' && typeof optBoxLabel !== 'string') {
          // TODO kludge; this is not the right thing
          optBoxLabel = name;
        }
      } else {
        throw new Error('bad widgetType: ' + widgetType);
      }
      
      if (optBoxLabel !== undefined) {
        wEl.setAttribute('title', optBoxLabel);
      }
      
      getAppend().appendChild(wEl);
      // TODO: Maybe createWidgetExt should be a method of the context?
      createWidgetExt(config.context, widgetCtor, wEl, targetCell);
    }
    
    function ignore(name) {
      if (name === '*') {
        claimedEverything = true;
      } else {
        claimed[name] = true;
      }
    }
    
    // TODO be less imperative
    function setInsertion(el) {
      appendTarget = el;
    }
    
    function setToDetails() {
      // special value which is instantiated if anything actually gets appended
      appendTarget = 'details';
    }
    
    // Ignore anything named in an "ignore: <name>" comment as an immediate child node.
    // TODO: Write a test for this feature
    (function() {
      for (var node = config.element.firstChild; node; node = node.nextSibling) {
        if (node.nodeType === 8 /* comment */) {
          var match = /^\s*ignore:\s*(\S*)\s*$/.exec(node.nodeValue);
          if (match) {
            ignore(match[1]);
          }
        }
      }
    }());
    
    if (optSpecial) {
      optSpecial.call(this, block, addWidget, ignore, setInsertion, setToDetails, getAppend);
    }
    
    const sortTable = [];
    for (var key in block) {
      if (claimed[key] || claimedEverything) continue;
      
      const member = block[key];
      if (member instanceof Cell) {
        if (member.type.isSingleValued()) {
          continue;
        }
        sortTable.push({
          key: key,
          cell: member,
          sortKey: typeof(member.metadata.naming.sort_key) === 'string' ? member.metadata.naming.sort_key : key
        });
      } else {
        console.warn('Block scan got unexpected object:', member);
      }
    }
    
    sortTable.sort((a, b) => {
      return a.sortKey < b.sortKey ? -1 : a.sortKey > b.sortKey ? 1 : 0;
    });
    
    sortTable.forEach(function ({key, cell}) {
      // TODO: gimmick to support local metadata-less cells; stop passing key once metadata usage is more established.
      let label = cell.metadata.naming.label ? undefined : key;
      addWidget(key, PickWidget, label);
    });
  }
  exports.Block = Block;
  
  // Delegate to a widget based on the target's cell type or interfaces.
  function PickWidget(config) {
    if (Object.getPrototypeOf(this) !== PickWidget.prototype) {
      throw new Error('cannot inherit from PickWidget');
    }
    
    const targetCell = config.target;
    const context = config.context;
    const cellType = targetCell.type;
    
    const ctorCell = new DerivedCell(anyT, config.scheduler, function (dirty) {
      if (cellType === blockT) {
        const block = targetCell.depend(dirty);
      
        // TODO kludgy, need better representation of interfaces. At least pull this into a function itself.
        let ctor;
        Object.getOwnPropertyNames(block).some(function (key) {
          var match = /^_implements_(.*)$/.exec(key);
          if (match) {
            var interface_ = match[1];
            // TODO better scheme for registering widgets for interfaces
            ctor = context.widgets['interface:' + interface_];
            if (ctor) return true;
          }
        });
      
        return ctor || Block;
        
      // TODO: Figure out how to have a dispatch table for this.
      } else if (cellType instanceof RangeT) {
        if (targetCell.set) {
          return cellType.logarithmic ? LogSlider : LinSlider;
        } else {
          return Meter;
        }
      } else if (cellType === numberT || cellType instanceof QuantityT) {
        return SmallKnob;
      } else if (cellType instanceof EnumT) {
        // Our EnumT-type widgets are Radio and Select; Select is a better default for arbitrarily-long lists.
        return Select;
      } else if (cellType === booleanT) {
        return Toggle;
      } else if (cellType === stringT && targetCell.set) {
        return TextBox;
      } else if (cellType === trackT) {
        return TrackWidget;
      } else if (cellType instanceof NoticeT) {
        return Banner;
      } else if (cellType instanceof TimestampT) {
        return TimestampWidget;
      } else if (targetCell instanceof CommandCell) {
        return CommandButton;
      } else {
        return Generic;
      }
    });
    
    return new (ctorCell.depend(config.rebuildMe))(config);
  }
  exports.PickWidget = PickWidget;
  
  // TODO: lousy name
  // This abstract widget class is for widgets which use an INPUT or similar element and optionally wrap it in a panel.
  function SimpleElementWidget(config, expectedNodeName, buildPanel, initDataEl) {
    const target = config.target;
    
    let dataElement;
    if (config.element.nodeName !== expectedNodeName) {
      const container = this.element = config.element;
      if (config.shouldBePanel) container.classList.add('panel');
      dataElement = buildPanel(container);
    } else {
      this.element = dataElement = config.element;
    }
    
    const update = initDataEl(dataElement, target);
    
    config.scheduler.startNow(function draw() {
      var value = target.depend(draw);
      update(value, draw);
    });
  }
  
  function Generic(config) {
    SimpleElementWidget.call(this, config, undefined,
      function buildPanel(container) {
        container.appendChild(document.createTextNode(container.getAttribute('title') + ': '));
        container.removeAttribute('title');
        const node = container.appendChild(document.createTextNode(''));
        insertUnitIfPresent(config.target.type, container);
        return node;
      },
      function init(node, target) {
        return function updateGeneric(value, draw) {
          node.textContent = value;
        };
      });
  }
  exports.Generic = Generic;
  
  // widget for NoticeT type
  function Banner(config) {
    const type = config.target.type;
    const alwaysVisible = type instanceof NoticeT && type.alwaysVisible;  // TODO something better than instanceof...?
    
    const textNode = document.createTextNode('');
    SimpleElementWidget.call(this, config, undefined,
      function buildPanel(container) {
        // TODO: use title in some way
        container.appendChild(textNode);
        return container;
      },
      function init(node, target) {
        return function updateBanner(value, draw) {
          value = String(value);
          textNode.textContent = value;
          var active = value !== '';
          if (active) {
            node.classList.add('widget-Banner-active');
          } else {
            node.classList.remove('widget-Banner-active');
          }
          if (active || alwaysVisible) {
            node.classList.remove('widget-Banner-hidden');
          } else {
            node.classList.add('widget-Banner-hidden');
          }
        };
      });
  }
  exports.Banner = Banner;
  
  class TextTerminal {
    constructor(config) {
      const target = config.target;
      this.element = config.element;
      
      const textarea = config.element.appendChild(document.createElement('textarea'));
      textarea.readOnly = true;
      textarea.rows = 3;
      textarea.cols = 40;
      
      config.scheduler.startNow(function draw() {
        textarea.textContent = String(target.depend(draw));
        textarea.scrollTop = textarea.scrollHeight;  // TODO better sticky behavior
      });
    }
  }
  exports.TextTerminal = TextTerminal;
  
  // widget for TimestampT type
  var timestampUpdateClock = new Clock(1);
  function TimestampWidget(config) {
    SimpleElementWidget.call(this, config, undefined,
      function buildPanel(container) {
        container.appendChild(document.createTextNode(container.getAttribute('title') + ': '));
        container.removeAttribute('title');
        var holder = container.appendChild(document.createTextNode(''));
        container.appendChild(document.createTextNode(' seconds ago'));
        return holder;
      },
      function init(holder, target) {
        var element = holder.parentNode;
        return function updateTimestamp(value, draw) {
          var relativeTime = timestampUpdateClock.convertToTimestampSeconds(timestampUpdateClock.depend(draw)) - value;
          holder.textContent = '' + Math.round(relativeTime);
          
          var date = new Date(0);
          date.setUTCSeconds(value);
          element.title = '' + date;
        };
      });
  }
  exports.TimestampWidget = TimestampWidget;
  
  function TextBox(config) {
    SimpleElementWidget.call(this, config, 'INPUT',
      function buildPanelForTextBox(container) {
        container.classList.add('widget-TextBox-panel');
        
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.classList.add('widget-TextBox-label');
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.removeAttribute('title');
        }
        
        var input = container.appendChild(document.createElement('input'));
        input.type = 'text';
        
        return input;
      },
      function initTextBox(input, target) {
        input.readOnly = !target.set;
        
        input.addEventListener('input', function(event) {
          target.set(input.value);
        }, false);
        
        return function updateTextBox(value) {
          input.value = value;
        };
      });
  }
  exports.TextBox = TextBox;
  
  function NumberWidget(config) {
    SimpleElementWidget.call(this, config, 'TT',
      function buildPanel(container) {
        if (config.shouldBePanel) {
          container.appendChild(document.createTextNode(container.getAttribute('title') + ': '));
          container.removeAttribute('title');
          return container.appendChild(document.createElement('tt'));
        } else {
          return container;
        }
      },
      function init(container, target) {
        var textNode = container.appendChild(document.createTextNode(''));
        return function updateGeneric(value) {
          textNode.textContent = (+value).toFixed(2);
        };
      });
  }
  exports.Number = NumberWidget;
  
  function Knob(config) {
    const target = config.target;
    const writable = 'set' in target; // TODO better type protocol

    const type = target.type;
    // TODO: use integer flag of RangeT, w decimal points?
    function clamp(value, direction) {
      if (type instanceof RangeT) {  // TODO: better type protocol
        return type.round(value, direction);
      } else {
        return value;
      }
    }
    
    const container = document.createElement('span');
    container.classList.add('widget-Knob-outer');
    
    if (config.shouldBePanel) {
      const panel = document.createElement('div');
      panel.classList.add('panel');
      if (config.element.hasAttribute('title')) {
        panel.appendChild(document.createTextNode(config.element.getAttribute('title')));
        config.element.removeAttribute('title');
      }
      panel.appendChild(container);
      this.element = panel;
    } else {
      this.element = container;
    }
    
    const places = [];
    const marks = [];
    function createPlace(i) {
      if (i % 3 === 2) {
        const mark = container.appendChild(document.createElement("span"));
        mark.className = "knob-mark";
        mark.textContent = ",";
        //mark.style.visibility = "hidden";
        marks.unshift(mark);
        // TODO: make marks responsive to scroll events (doesn't matter which neighbor, or split in the middle, as long as they do something).
      }
      const digit = container.appendChild(document.createElement("span"));
      digit.className = "knob-digit";
      const digitText = digit.appendChild(document.createTextNode('0'));
      places[i] = {element: digit, text: digitText};
      const scale = Math.pow(10, i);
      
      if (!writable) return;
      
      digit.tabIndex = -1;
      
      function spin(direction) {
        target.set(clamp(direction * scale + target.get(), direction));
      }
      digit.addEventListener("mousewheel", function(event) { // Not in FF
        // TODO: deal with high-res/accelerated scrolling
        spin(event.wheelDelta > 0 ? 1 : -1);
        event.preventDefault();
        event.stopPropagation();
      }, {capture: true, passive: false});
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
      digit.addEventListener('keydown', event => {
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
      digit.addEventListener('keypress', event => {
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
          case 'z':
          case 'Z':
            // zero all digits here and to the right
            // | 0 is used to round towards zero
            var zeroFactor = scale * 10;
            target.set(((value / zeroFactor) | 0) * zeroFactor);
            return;
          default:
            break;
        }
        
        // TODO I hear there's a new 'input' event which is better for input-ish keystrokes, use that
        var input = parseInt(ch, 10);
        if (isNaN(input)) return;

        var negative = value < 0 || (value === 0 && 1/value === -Infinity);
        if (negative) { value = -value; }
        var currentDigitValue;
        if (scale === 1) {
          // When setting last digit, clear anyT hidden fractional digits as well
          currentDigitValue = (value / scale) % 10;
        } else {
          currentDigitValue = Math.floor(value / scale) % 10;
        }
        value += (input - currentDigitValue) * scale;
        if (negative) { value = -value; }
        target.set(clamp(value, 0));

        focusNext();
        event.preventDefault();
        event.stopPropagation();
      });
    
      // remember last place for tabbing
      digit.addEventListener('focus', event => {
        places.forEach(other => {
          other.element.tabIndex = -1;
        });
        digit.tabIndex = 0;
      }, false);
    
      // spin buttons
      digit.style.position = 'relative';
      [-1, 1].forEach(direction => {
        var up = direction > 0;
        var layoutShim = digit.appendChild(document.createElement('span'));
        layoutShim.className = 'knob-spin-button-shim knob-spin-' + (up ? 'up' : 'down');
        var button = layoutShim.appendChild(document.createElement('button'));
        button.className = 'knob-spin-button knob-spin-' + (up ? 'up' : 'down');
        button.textContent = up ? '+' : '-';
        function pushListener(event) {
          spin(direction);
          event.preventDefault();
          event.stopPropagation();
        }
        // Using these events instead of click event allows the button to work despite the auto-hide-on-focus-loss, in Chrome.
        button.addEventListener('touchstart', pushListener, {capture: true, passive: false});
        button.addEventListener('mousedown', pushListener, {capture: true, passive: false});
        //button.addEventListener('click', pushListener, false);
        // If in the normal tab order, its appearing/disappearing causes trouble
        button.tabIndex = -1;
      });
    }
    
    for (let i = 9; i >= 0; i--) {
      createPlace(i);
    }
    
    places[places.length - 1].element.tabIndex = 0; // initial tabbable digit
    
    config.scheduler.startNow(function draw() {
      const value = target.depend(draw);
      let valueStr = String(Math.round(value));
      if (valueStr === '0' && value === 0 && 1/value === -Infinity) {
        // allow user to see progress in entering negative values
        valueStr = '-0';
      }
      const last = valueStr.length - 1;
      for (let i = 0; i < places.length; i++) {
        const digit = valueStr[last - i];
        places[i].text.data = digit || '0';
        places[i].element.classList[digit ? 'remove' : 'add']('knob-dim');
      }
      const numMarks = Math.floor((valueStr.replace("-", "").length - 1) / 3);
      for (let i = 0; i < marks.length; i++) {
        marks[i].classList[i < numMarks ? 'remove' : 'add']('knob-dim');
      }
    });
  }
  exports.Knob = Knob;
  
  function SmallKnob(config) {
    SimpleElementWidget.call(this, config, 'INPUT',
      function buildPanelForSmallKnob(container) {
        container.classList.add('widget-SmallKnob-panel');
        
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.classList.add('widget-SmallKnob-label');
          labelEl.appendChild(document.createTextNode(container.getAttribute('title') + '\u00A0'));
          container.removeAttribute('title');
        }
        
        var input = container.appendChild(document.createElement('input'));
        input.type = 'number';
        input.step = 'any';
        
        insertUnitIfPresent(config.target.type, container);
        
        return input;
      },
      function initSmallKnob(input, target) {
        var type = target.type;
        if (type instanceof RangeT) {
          input.min = type.getMin();
          input.max = type.getMax();
          input.step = (type.integer && !type.logarithmic) ? 1 : 'any';
        }
        
        input.readOnly = !target.set;
        
        input.addEventListener('input', function(event) {
          if (type instanceof RangeT) {
            target.set(type.round(input.valueAsNumber, 0));
          } else {
            target.set(input.valueAsNumber);
          }
        }, false);
        
        return function updateSmallKnob(value) {
          var sValue = +value;
          if (!isFinite(sValue)) {
            sValue = 0;
          }
          input.disabled = false;
          input.valueAsNumber = sValue;
        };
      });
  }
  exports.SmallKnob = SmallKnob;
  
  function Slider(config, getT, setT) {
    var text;
    SimpleElementWidget.call(this, config, 'INPUT',
      function buildPanelForSlider(container) {
        container.classList.add('widget-Slider-panel');
        
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.classList.add('widget-Slider-label');
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.removeAttribute('title');
        }
        
        var slider = container.appendChild(document.createElement('input'));
        slider.type = 'range';
        slider.step = 'any';
        
        var textEl = container.appendChild(document.createElement('span'));
        textEl.classList.add('widget-Slider-text');
        text = textEl.appendChild(document.createTextNode(''));
        
        insertUnitIfPresent(config.target.type, container);
        
        return slider;
      },
      function initSlider(slider, target) {
        var format = function(n) { return n.toFixed(2); };

        var type = target.type;
        if (type instanceof RangeT) {
          slider.min = getT(type.getMin());
          slider.max = getT(type.getMax());
          slider.step = (type.integer) ? 1 : 'any';
          if (type.integer) {
            format = function(n) { return '' + n; };
          }
        }
        
        // readOnly is not available for input type=range
        slider.disabled = !target.set;
        
        function listener(event) {
          if (type instanceof RangeT) {
            target.set(type.round(setT(slider.valueAsNumber), 0));
          } else {
            target.set(setT(slider.valueAsNumber));
          }
        }
        // Per HTML5 spec, dragging fires 'input', but not 'change', event. However Chrome only recently (observed 2014-04-12) got this right, so we had better listen to both.
        slider.addEventListener('change', listener, false);
        slider.addEventListener('input', listener, false);  
        return function updateSlider(value) {
          var sValue = getT(value);
          if (!isFinite(sValue)) {
            sValue = 0;
          }
          slider.valueAsNumber = sValue;
          if (text) {
            text.data = format(value);
          }
        };
      });
  }
  var LinSlider = exports.LinSlider = function(c) { return new Slider(c,
    function (v) { return v; },
    function (v) { return v; }); };
  var LogSlider = exports.LogSlider = function(c) { return new Slider(c,
    function (v) { return Math.log(v) / Math.LN2; },
    function (v) { return Math.pow(2, v); }); };

  function Meter(config) {
    var text;
    SimpleElementWidget.call(this, config, 'METER',
      function buildPanelForMeter(container) {
        // TODO: Reusing styles for another widget -- rename to suit
        container.classList.add('widget-Slider-panel');
        
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.classList.add('widget-Slider-label');
          labelEl.appendChild(document.createTextNode(
              container.getAttribute('title') + '\u00A0'));
          container.removeAttribute('title');
        }
        
        var meter = container.appendChild(document.createElement('meter'));
        
        var textEl = container.appendChild(document.createElement('span'));
        textEl.classList.add('widget-Slider-text');
        text = textEl.appendChild(document.createTextNode(''));
        
        insertUnitIfPresent(config.target.type, container);
        
        return meter;
      },
      function initMeter(meter, target) {
        var format = function(n) { return n.toFixed(2); };
        
        var type = target.type;
        if (type instanceof RangeT) {
          meter.min = type.getMin();
          meter.max = type.getMax();
          if (type.integer) {
            format = function(n) { return '' + n; };
          }
        }
        
        return function updateMeter(value) {
          value = +value;
          meter.value = value;
          if (text) {
            text.data = format(value);
          }
        };
      });
  }
  exports.Meter = Meter;
  
  function Toggle(config) {
    SimpleElementWidget.call(this, config, 'INPUT',
      function buildPanelForToggle(container) {
        var label = container.appendChild(document.createElement('label'));
        var checkbox = label.appendChild(document.createElement('input'));
        checkbox.type = 'checkbox';
        label.appendChild(document.createTextNode(container.getAttribute('title')));
        container.removeAttribute('title');
        return checkbox;
      },
      function initToggle(checkbox, target) {
        checkbox.disabled = !target.set;
        checkbox.addEventListener('change', function(event) {
          target.set(checkbox.checked);
        }, false);
        return function updateToggle(value) {
          checkbox.checked = value;
        };
      });
  }
  exports.Toggle = Toggle;
  
  // Create children of 'container' according to target's EnumT (or RangeT) type, unless appropriate children already exist.
  function initEnumElements(container, selector, target, createElement) {
    const enumTable = target.type.getEnumTable();
    
    const seen = new Set();
    Array.prototype.forEach.call(container.querySelectorAll(selector), function (element) {
      var value = element.value;
      seen.add(value);
      if (enumTable) {
        element.disabled = !enumTable.has(element.value);  // TODO: handle non-string values
      }
    });

    if (enumTable) {
      const array = Array.from(enumTable.keys());
      array.sort((a, b) => {
        const aKey = enumTable.get(a).sort_key;
        const bKey = enumTable.get(b).sort_key;
        return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
      });
      array.forEach(value => {
        const metadataRow = enumTable.get(value);
        if (seen.has(value)) return;
        const element = createElement(metadataRow.label, metadataRow.description);
        element.value = value;
      });
    }
  }
  
  function Select(config) {
    SimpleElementWidget.call(this, config, 'SELECT',
      function buildPanelForSelect(container) {
        //container.classList.add('widget-Popup-panel');
        
        // TODO: recurring pattern -- extract
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.appendChild(document.createTextNode(' '));
          container.removeAttribute('title');
        }
        
        return container.appendChild(document.createElement('select'));
      },
      function initSelect(select, target) {
        const numeric = target.type instanceof RangeT;  // TODO better test, provide coercion in the types
        select.disabled = !target.set;
        initEnumElements(select, 'option', target, function createOption(name, longDesc) {
          var option = select.appendChild(document.createElement('option'));
          option.appendChild(document.createTextNode(name));
          if (longDesc !== null) {
            option.title = longDesc;  // TODO: This probably isn't visible.
          }
          return option;
        });

        select.addEventListener('change', event => {
          target.set(numeric ? +select.value : select.value);
        }, false);
        
        return function updateSelect(value) {
          select.value = '' + value;
        };
      });
  }
  exports.Select = Select;
  
  function Radio(config) {
    var target = config.target;
    const numeric = target.type instanceof RangeT;  // TODO better test, provide coercion in the types
    var container = this.element = config.element;
    container.classList.add('panel');

    initEnumElements(container, 'input[type=radio]', target, function createRadio(name, longDesc) {
      var label = container.appendChild(document.createElement('label'));
      var rb = label.appendChild(document.createElement('input'));
      var textEl = label.appendChild(document.createElement('span'));  // styling hook
      textEl.textContent = name;
      if (longDesc !== null) {
        label.title = longDesc;
      }
      rb.type = 'radio';
      if (!target.set) rb.disabled = true;
      return rb;
    });

    Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
      rb.addEventListener('change', function(event) {
        target.set(numeric ? +rb.value : rb.value);
      }, false);
    });
    config.scheduler.startNow(function draw() {
      var value = config.target.depend(draw);
      Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
        rb.checked = rb.value === '' + value;
      });
    });
  }
  exports.Radio = Radio;
  
  function CommandButton(config) {
    var commandCell = config.target;
    var panel = this.element = config.element;
    var isDirectlyButton = panel.tagName === 'BUTTON';
    if (!isDirectlyButton) panel.classList.add('panel');
    
    var button = isDirectlyButton ? panel : panel.querySelector('button');
    if (!button) {
      button = panel.appendChild(document.createElement('button'));
      if (panel.hasAttribute('title')) {
        button.textContent = panel.getAttribute('title');
        panel.removeAttribute('title');
      } else {
        button.textContent = '<unknown action>'; 
      }
    }
    
    button.disabled = false;
    button.onclick = function (event) {
      button.disabled = true;  // TODO: Some buttons should be rapid-fireable, this is mainly to give a latency cue
      commandCell.invoke(function completionCallback() {
        button.disabled = false;
      });
    };
  }
  exports.CommandButton = CommandButton;
  
  // widget for the shinysdr.telemetry.Track type
  function TrackWidget(config) {
    var actions = config.actions;
    
    // TODO not _really_ a SimpleElementWidget
    SimpleElementWidget.call(this, config, 'TABLE',
      function buildPanelForTrack(container) {
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('div'));
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.removeAttribute('title');
        }
        
        var valueEl = container.appendChild(document.createElement('TABLE'));
        
        return valueEl;
      },
      function initEl(valueEl, target) {
        function addRow(label, linked) {
          var rowEl = valueEl.appendChild(document.createElement('tr'));
          rowEl.appendChild(document.createElement('th'))
            .appendChild(document.createTextNode(label));
          var textNode = document.createTextNode('');
          var textCell = rowEl.appendChild(document.createElement('td'));
          if (linked) {  // TODO: make this && actions.<can navigateMap>
            textCell = textCell.appendChild(document.createElement('a'));
            // TODO: Consider using an actual href and putting the map view state (as well as other stuff) into the fragment!
            textCell.href = '#i-apologize-for-not-being-a-real-link';
            textCell.addEventListener('click', function (event) {
              actions.navigateMap(target);
              event.preventDefault();  // no navigation
            }, false);
          }
          textCell.appendChild(document.createElement('tt'))  // fixed width formatting
              .appendChild(textNode);
          return {
            row: rowEl,
            text: textNode
          };
        }
        var posRow = addRow('Position', true);
        var velRow = addRow('Velocity', false);
        var vertRow = addRow('Vertical', false);
        
        function formatitude(value, p, n) {
          value = +value;
          if (value < 0) {
            value = -value;
            p = n;
          }
          // TODO: Arrange to get precision data and choose digits based on it
          return value.toFixed(4) + p;
        }
        function formatAngle(value) {
          return Math.round(value) + '\u00B0';
        }
        function formatSigned(value, digits) {
          var text = (+value).toFixed(digits);
          if (/^0-9/.test(text[0])) {
            text = '+' + text;
          }
          return text;
        }
        function formatGroup(row, f) {
          var out = [];
          f(function write(telemetryItem, text) {
            if (telemetryItem.value !== null) out.push(text);
          });
          if (out.length > 0) {
            row.row.style.removeProperty('display');
            row.text.data = out.join(' ');
          } else {
            row.row.style.display = 'none';
          }
        }
        
        return function updateEl(track) {
          // TODO: Rewrite this to comply with some kind of existing convention for position reporting formatting.
          // TODO: Display the timestamp.
          
          // horizontal position/orientation
          formatGroup(posRow, function(write) {
            write(track.latitude, formatitude(track.latitude.value, 'N', 'S'));
            write(track.longitude, formatitude(track.longitude.value, 'E', 'W'));
            write(track.heading, formatAngle(track.heading.value));
          });
          
          // horizontal velocity
          formatGroup(velRow, function(write) {
            write(track.h_speed, (+track.h_speed.value).toFixed(1) + ' m/s');
            write(track.track_angle, formatAngle(track.track_angle.value));
          });
          
          // vertical pos/vel
          formatGroup(vertRow, function(write) {
            write(track.altitude, (+track.altitude.value).toFixed(1) + ' m');
            write(track.v_speed, formatSigned(track.track_angle.value, 1) + ' m/s\u00B2');
          });
        };
      });
  }
  exports.TrackWidget = TrackWidget;
  
  function MeasvizWidget(config) {
    const target = config.target;
    const container = this.element = config.element;
        
    const isRange = target.type instanceof RangeT;
    const scale = (isRange && target.type.integer) ? 1 : 1000;
    
    const buffer = new Float32Array(128);  // TODO magic number
    let index = 0;
    
    const graph = new measviz.Graph({
      buffer: buffer,
      getBufferIndex() { return index; },
      getHeight() { return 16; },  // TODO magic number
      min: isRange ? scale * target.type.getMin() : 0,
      low: isRange ? scale * target.type.getMin() : 0,
      high: isRange ? scale * target.type.getMax() : Infinity,
      max: isRange ? scale * target.type.getMax() : Infinity
    });
    
    if (config.shouldBePanel) {
      container.classList.add('panel');
      if (container.hasAttribute('title')) {
        container.appendChild(document.createTextNode(container.getAttribute('title') + ' '));
        container.removeAttribute('title');
      }
    }
    container.appendChild(graph.element);
    
    config.scheduler.startNow(function draw() {
      buffer[index] = target.depend(draw) * scale;
      index = mod(index + 1, buffer.length);
      graph.draw();
    });
  }
  exports.MeasvizWidget = MeasvizWidget;
  
  // TODO: Better name
  class ObjectInspector {
    constructor(config) {
      const target = config.target;
      const container = this.element = config.element;
      const baseId = config.element.id;
      
      const metaField = container.appendChild(document.createElement(container.tagName === 'DETAILS' ? 'summary' : 'div'));
      
      if (config.element.title) {
        const t = document.createTextNode(config.element.title);
        config.element.removeAttribute('title');
        metaField.appendChild(t);
        metaField.appendChild(oiMetasyntactic(' = '));
      }
      
      metaField.appendChild(document.createTextNode(String(target.type) + ' '));
      metaField.appendChild(oiMetasyntactic(target.set ? 'RW' : 'RO'));
      
      const singleLineContainer = metaField.appendChild(document.createElement('span'));
      singleLineContainer.classList.add('widget-ObjectInspector-single-line');
      
      //container.appendChild(document.createTextNode('\u00A0'));
      
      config.scheduler.startNow(function updateValue() {
        singleLineContainer.textContent = '';
        while (container.lastChild && container.lastChild !== metaField) {
          container.removeChild(container.lastChild);
        }
        
        const value = config.target.depend(updateValue);
        if (typeof value === 'object' && value !== null) {
          getInterfaces(value).forEach(i => {
            container.appendChild(document.createTextNode(' ' + i));
          });
          if (value._reshapeNotice) {
            // TODO: Use AddKeepDrop instead
            value._reshapeNotice.listen(updateValue);
          }
          const list = container.appendChild(document.createElement('ul'));
          for (var prop in value) {
            const childField = list.appendChild(document.createElement('li'));
            const propValue = value[prop];
            if (propValue instanceof Cell) {
              const childDetails = childField.appendChild(document.createElement('details'));
              childDetails.open = true;
              childDetails.id = baseId + '.' + prop;
              childDetails.title = prop;
              createWidgetExt(config.context, ObjectInspector, childDetails, propValue);
            } else {
              childField.appendChild(document.createTextNode(prop));
              childField.appendChild(oiMetasyntactic(' = not a cell '));
              childField.appendChild(oiStringify(propValue));
            }
          }
        } else {
          singleLineContainer.appendChild(oiMetasyntactic(' value= '));
          singleLineContainer.appendChild(document.createTextNode(typeof value));
          singleLineContainer.appendChild(oiMetasyntactic(' '));
          
          singleLineContainer.appendChild(oiStringify(value));
        }
      });
    }
  }
  exports.ObjectInspector = ObjectInspector;
  
  function oiMetasyntactic(text) {
    const el = document.createElement('span');
    el.textContent = text;
    el.classList.add('widget-ObjectInspector-metasyntactic');
    return el;
  }
  
  function oiStringify(value) {
    try {
      return document.createTextNode(JSON.stringify(value));
    } catch (e) {
      try {
        return document.createTextNode(String(value));
      } catch (e) {
        return oiMetasyntactic('<error displaying value>');
      }
    }
  }
  
  const TABLE_COLUMN_HEADER_MARKER = '_HEADER';  // could be any unique object but this is helpful
  const TABLE_ROW_HEADER_COLUMN = {
    headerText() {
      return '';
    },
    lookupIn(block, rowName) {
      if (typeof rowName === 'string') {
        return new ConstantCell(rowName);
      } else {
        return undefined;
      }
    }
  };
  
  class TableLayoutContext {
    constructor() {
      this._columnLookup = new Map();
      this._columnsCell = new LocalReadCell(anyT, Object.freeze([TABLE_ROW_HEADER_COLUMN]));
    }
    
    extractColumns(block) {
      const newColumns = [];
      for (var key in block) {
        const cell = block[key];
        if (!(cell instanceof Cell)) continue;  // don't crash...
        
        // Use the entire metadata as a lookup key so that we don't conflate different titles
        const metadata = cell.metadata;
        const keyWithMetadata = JSON.stringify([key, metadata]);
        
        if (!this._columnLookup.has(keyWithMetadata)) {
          const keyConst = key;
          const column = {
            headerText() {
              return metadata.naming.label || keyConst;
            },
            lookupIn(block, rowName) {
              return block[keyConst];
            }
          };
          this._columnLookup.set(keyWithMetadata, column);
          newColumns.push(column);
        }
      }
      // TODO: sort
      this._columnsCell._update(Object.freeze(this._columnsCell.get().concat(newColumns)));
    }
    
    columnsCell() {
      return this._columnsCell;
    }
  }
  
  function TableWidget(config) {
    const block = config.target.depend(config.rebuildMe);
    const idPrefix = config.idPrefix;
    const tableContext = config.context.withLayoutContext(new TableLayoutContext());
    
    // TODO: We ought to display these in some way.
    config.element.removeAttribute('title');
    
    let tableEl = config.element;
    if (tableEl.tagName !== 'TABLE') {
      tableEl = document.createElement('table');
    }
    this.element = tableEl;
    
    const headerRowEl = tableEl.appendChild(document.createElement('tr'));
    createWidgetExt(tableContext, TableRowWidget, headerRowEl, new ConstantCell(TABLE_COLUMN_HEADER_MARKER));
    
    const childrenAKD = new AddKeepDrop({
      add(name) {
        // TODO: allow multi-row entries
        const rowEl = tableEl.appendChild(document.createElement('tr'));
        if (idPrefix) {
          rowEl.id = idPrefix + name;
        }
        rowEl.title = name;  // TODO use metadata? have widget get it from id?
        const widgetHandle = createWidgetExt(tableContext, TableRowWidget, rowEl, block[name]);
        return {
          widgetHandle: widgetHandle,
          element: rowEl
        };
      },
      remove(name, parts) {
        parts.widgetHandle.destroy();
        tableEl.removeChild(parts.element);
      }
    });

    config.scheduler.startNow(function handleReshape() {
      block._reshapeNotice.listen(handleReshape);
      childrenAKD.update(Object.keys(block));
    });
  }
  exports.TableWidget = TableWidget;
  
  // Helper for TableWidget
  function TableRowWidget(config) {
    // Currently not bothering to check and substitute element.
    const block = config.target.depend(config.rebuildMe);
    const rowEl = config.element;
    this.element = rowEl;
    const tableContext = config.getLayoutContext(TableLayoutContext);
    
    let label = null;
    if (config.element.title) {
      label = config.element.title;
      config.element.removeAttribute('title');
    }
    
    const childrenAKD = new AddKeepDrop({
      add(column) {
        const cellEl = rowEl.appendChild(document.createElement(block === TABLE_COLUMN_HEADER_MARKER ? 'th' : 'td'));
        
        let widgetHandle, cell;
        if (block === TABLE_COLUMN_HEADER_MARKER) {
          cellEl.textContent = column.headerText();
        } else if (cell = column.lookupIn(block, label)) {
          cellEl.title = '';  // Specify we want to hide titles.
          widgetHandle = createWidgetExt(config.context, PickWidget, cellEl, cell);
        } else {
          cellEl.textContent = 'n/a';
        }
        
        return () => {
          if (widgetHandle) widgetHandle.destroy();
          rowEl.removeChild(cellEl);
        };
      },
      remove(column, remover) {
        remover();
      }
    });

    // Send local shape info to table context
    if (block !== TABLE_COLUMN_HEADER_MARKER) {
      config.scheduler.startNow(function handleReshape() {
        block._reshapeNotice.listen(handleReshape);
        tableContext.extractColumns(block);
      });
    }
    
    // Get aggregated shape info from table context.
    config.scheduler.startNow(function handleColumnChange() {
      childrenAKD.update(tableContext.columnsCell().depend(handleColumnChange));
    });
  }
  
  return Object.freeze(exports);
});
