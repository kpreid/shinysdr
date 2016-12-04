// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

// TODO post split, reduce deps here
define(['../types', '../values', '../events', '../widget', '../gltools', '../database', '../menus'], function (types, values, events, widget, gltools, database, menus) {
  'use strict';
  
  var Cell = values.Cell;
  var Clock = events.Clock;
  var CommandCell = values.CommandCell;
  var ConstantCell = values.ConstantCell;
  var DerivedCell = values.DerivedCell;
  var Enum = types.Enum;
  var LocalCell = values.LocalCell;
  var Menu = menus.Menu;
  var Notice = types.Notice;
  var Range = types.Range;
  var SingleQuad = gltools.SingleQuad;
  var Timestamp = types.Timestamp;
  var Track = types.Track;
  var Union = database.Union;
  var addLifecycleListener = widget.addLifecycleListener;
  var alwaysCreateReceiverFromEvent = widget.alwaysCreateReceiverFromEvent;
  var createWidgetExt = widget.createWidgetExt;
  var emptyDatabase = database.empty;
  var isSingleValued = types.isSingleValued;
  
  var exports = Object.create(null);

  // Superclass for a sub-block widget
  function Block(config, optSpecial, optEmbed) {
    var block = config.target.depend(config.rebuildMe);
    block._reshapeNotice.listen(config.rebuildMe);
    var container = this.element = config.element;
    var appendTarget = container;
    var claimed = Object.create(null);
    
    //container.textContent = '';
    container.classList.add('frame');
    if (config.shouldBePanel && !optEmbed) {
      container.classList.add('panel');
    }
    
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
        targetCell = new ConstantCell(types.block, block);
      } else if ('get' in name) {  // sanity check, not to be used as type discrimination
        targetCell = name;
      } else {
        throw new Error('not understood target for addWidget: ' + name);
      }
      
      if (optBoxLabel !== undefined) {
        wEl.setAttribute('title', optBoxLabel);
      }
      
      var widgetCtor;
      if (typeof widgetType === 'string') {
        throw new Error('string widget types being deprecated, not supported here');
      } else {
        widgetCtor = widgetType;
      }
      
      getAppend().appendChild(wEl);
      // TODO: Maybe createWidgetExt should be a method of the context?
      createWidgetExt(config.context, widgetCtor, wEl, targetCell);
    }
    
    function ignore(name) {
      claimed[name] = true;
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
        if (node.nodeType == 8 /* comment */) {
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
    
    var names = [];
    for (var name in block) names.push(name);
    names.sort();
    names.forEach(function (name) {
      if (claimed[name]) return;
      
      var member = block[name];
      if (member instanceof Cell) {
        if (isSingleValued(member.type)) {
          return;
        }
        addWidget(name, PickWidget, name);
      } else {
        console.warn('Block scan got unexpected object:', member);
      }
    });
  }
  exports.Block = Block;
  
  // Delegate to a widget based on the target's cell type or interfaces.
  function PickWidget(config) {
    if (Object.getPrototypeOf(this) !== PickWidget.prototype) {
      throw new Error('cannot inherit from PickWidget');
    }
    
    var targetCell = config.target;
    var context = config.context;
    var cellType = targetCell.type;
    
    var ctorCell = new DerivedCell(types.any, config.scheduler, function (dirty) {
      if (cellType == types.block) {
        var block = targetCell.depend(dirty);
      
        // TODO kludgy, need better representation of interfaces. At least pull this into a function itself.
        var ctor;
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
      } else if (cellType instanceof Range) {
        if (targetCell.set) {
          return cellType.logarithmic ? LogSlider : LinSlider;
        } else {
          return Meter;
        }
      } else if (cellType === Number) {
        return SmallKnob;
      } else if (cellType instanceof Enum) {
        // Our Enum-type widgets are Radio and Select; Select is a better default for arbitrarily-long lists.
        return Select;
      } else if (cellType === Boolean) {
        return Toggle;
      } else if (cellType === String && targetCell.set) {
        return TextBox;
      } else if (cellType === Track) {
        return TrackWidget;
      } else if (cellType instanceof Notice) {
        return Banner;
      } else if (cellType instanceof Timestamp) {
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
  function SimpleElementWidget(config, expectedNodeName, buildPanel, initDataEl, update) {
    var target = config.target;
    
    var dataElement;
    if (config.element.nodeName !== expectedNodeName) {
      var container = this.element = config.element;
      if (config.shouldBePanel) container.classList.add('panel');
      dataElement = buildPanel(container);
    } else {
      this.element = dataElement = config.element;
    }
    
    var update = initDataEl(dataElement, target);
    
    var draw = config.boundedFn(function drawImpl() {
      var value = target.depend(draw);
      update(value, draw);
    });
    draw.scheduler = config.scheduler;
    draw();
  }
  
  function Generic(config) {
    SimpleElementWidget.call(this, config, undefined,
      function buildPanel(container) {
        container.appendChild(document.createTextNode(container.getAttribute('title') + ': '));
        container.removeAttribute('title');
        return container.appendChild(document.createTextNode(''));
      },
      function init(node, target) {
        return function updateGeneric(value, draw) {
          node.textContent = value;
        };
      });
  }
  exports.Generic = Generic;
  
  // widget for Notice type
  function Banner(config) {
    var type = config.target.type;
    var alwaysVisible = type instanceof Notice && type.alwaysVisible;  // TODO something better than instanceof...?
    
    var textNode = document.createTextNode('');
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
  
  // widget for Timestamp type
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
    var target = config.target;
    var writable = 'set' in target; // TODO better type protocol

    var type = target.type;
    // TODO: use integer flag of Range, w decimal points?
    function clamp(value, direction) {
      if (type instanceof types.Range) {  // TODO: better type protocol
        return type.round(value, direction);
      } else {
        return value;
      }
    }
    
    var container = document.createElement('span');
    container.classList.add('widget-Knob-outer');
    
    if (config.shouldBePanel) {
      var panel = document.createElement('div');
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
      var digitText = digit.appendChild(document.createTextNode('0'));
      places[i] = {element: digit, text: digitText};
      var scale = Math.pow(10, i);
      if (writable) {
        digit.tabIndex = -1;
        
        function spin(direction) {
          target.set(clamp(direction * scale + target.get(), direction));
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
            // When setting last digit, clear any hidden fractional digits as well
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
          function pushListener(event) {
            spin(direction);
            event.preventDefault();
            event.stopPropagation();
          }
          // Using these events instead of click event allows the button to work despite the auto-hide-on-focus-loss, in Chrome.
          button.addEventListener('touchstart', pushListener, false);
          button.addEventListener('mousedown', pushListener, false);
          //button.addEventListener('click', pushListener, false);
          // If in the normal tab order, its appearing/disappearing causes trouble
          button.tabIndex = -1;
        });
      } // if (writable)
    }(i));
    
    places[places.length - 1].element.tabIndex = 0; // initial tabbable digit
    
    var draw = config.boundedFn(function drawImpl() {
      var value = target.depend(draw);
      var valueStr = String(Math.round(value));
      if (valueStr === '0' && value === 0 && 1/value === -Infinity) {
        // allow user to see progress in entering negative values
        valueStr = '-0';
      }
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
    });
    draw.scheduler = config.scheduler;
    draw();
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
        
        return input;
      },
      function initSmallKnob(input, target) {
        var type = target.type;
        if (type instanceof types.Range) {
          input.min = getT(type.getMin());
          input.max = getT(type.getMax());
          input.step = (type.integer && !type.logarithmic) ? 1 : 'any';
        }
        
        input.readOnly = !target.set;
        
        input.addEventListener('input', function(event) {
          if (type instanceof types.Range) {
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
        }
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
        
        return slider;
      },
      function initSlider(slider, target) {
        var format = function(n) { return n.toFixed(2); };

        var type = target.type;
        if (type instanceof types.Range) {
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
          if (type instanceof types.Range) {
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
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.removeAttribute('title');
        }
        
        var meter = container.appendChild(document.createElement('meter'));
        
        var textEl = container.appendChild(document.createElement('span'));
        textEl.classList.add('widget-Slider-text');
        text = textEl.appendChild(document.createTextNode(''));
        
        return meter;
      },
      function initMeter(meter, target) {
        var format = function(n) { return n.toFixed(2); };
        
        var type = target.type;
        if (type instanceof types.Range) {
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
    var text;
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
  
  // Create children of 'container' according to target's enum type, unless appropriate children already exist.
  function initEnumElements(container, selector, target, createElement) {
    var type = target.type;
    if (!(type instanceof types.Enum)) type = null;
    
    var seen = Object.create(null);
    Array.prototype.forEach.call(container.querySelectorAll(selector), function (element) {
      var value = element.value;
      seen[value] = true;
      if (type) {
        element.disabled = !(element.value in type.values);
      }
    });

    if (type) {
      var table = type.getTable();
      var array = Object.keys(table);
      array.sort(function (a, b) {
        var aKey = table[a].sort_key;
        var bKey = table[b].sort_key;
        return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
      });
      array.forEach(function (value) {
        var metadataRow = table[value];
        if (seen[value]) return;
        var element = createElement(metadataRow.label, metadataRow.description);
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
        select.disabled = !target.set;
        initEnumElements(select, 'option', target, function createOption(name, longDesc) {
          var option = select.appendChild(document.createElement('option'));
          option.appendChild(document.createTextNode(name));
          if (longDesc !== null) {
            option.title = longDesc;  // TODO: This probably isn't visible.
          }
          return option;
        })

        select.addEventListener('change', function(event) {
          target.set(select.value);
        }, false);
        
        return function updateSelect(value) {
          select.value = value;
        };
      });
  }
  exports.Select = Select;
  
  function Radio(config) {
    var target = config.target;
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
        target.set(rb.value);
      }, false);
    });
    var draw = config.boundedFn(function drawImpl() {
      var value = config.target.depend(draw);
      Array.prototype.forEach.call(container.querySelectorAll('input[type=radio]'), function (rb) {
        rb.checked = rb.value === value;
      });
    });
    draw.scheduler = config.scheduler;
    draw();
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
  
  return Object.freeze(exports);
});
