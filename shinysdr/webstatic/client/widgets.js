// Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

define(['./values', './events', './widget', './gltools', './database', './menus', './plugins'], function (values, events, widget, gltools, database, menus, plugins) {
  'use strict';
  
  var Cell = values.Cell;
  var CommandCell = values.CommandCell;
  var ConstantCell = values.ConstantCell;
  var DerivedCell = values.DerivedCell;
  var Enum = values.Enum;
  var LocalCell = values.LocalCell;
  var Menu = menus.Menu;
  var Notice = values.Notice;
  var Range = values.Range;
  var SingleQuad = gltools.SingleQuad;
  var Track = values.Track;
  var Union = database.Union;
  var addLifecycleListener = widget.addLifecycleListener;
  var alwaysCreateReceiverFromEvent = widget.alwaysCreateReceiverFromEvent;
  var createWidgetExt = widget.createWidgetExt;
  var modeTable = plugins.getModeTable();
  
  // contains *only* widget types and can be used as a lookup namespace
  var widgets = Object.create(null);
  
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }
  
  function isSingleValued(type) {
    // TODO: Stop using Boolean etc. as type objects and remove the need for this feature test
    return type.isSingleValued && type.isSingleValued();
  }
  
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
      } else {
        targetCell = new ConstantCell(values.block, block);
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
        // TODO: Add a dispatch table of some sort to de-centralize this
        if (member.type instanceof Range) {
          if (member.set) {
            addWidget(name, member.type.logarithmic ? LogSlider : LinSlider, name);
          } else {
            addWidget(name, Meter, name);
          }
        } else if (member.type instanceof Enum) {
          addWidget(name, Radio, name);
        } else if (member.type === Boolean) {
          addWidget(name, Toggle, name);
        } else if (member.type === String && member.set) {
          addWidget(name, TextBox, name);
        } else if (member.type === Track) {
          addWidget(name, TrackWidget, name);
        } else if (member.type instanceof Notice) {
          addWidget(name, Banner, name);
        } else if (member instanceof CommandCell) {
          addWidget(name, CommandButton, name);
        } else if (member.type === values.block) {  // TODO colliding name
          // TODO: Add hook to choose a widget class based on interfaces
          // Furthermore, use that for the specific block widget classes too, rather than each one knowing the types of its sub-widgets.
          addWidget(name, PickBlock);
        } else {
          addWidget(name, Generic, name);
        }
      } else {
        console.warn('Block scan got unexpected object:', member);
      }
    });
  }
  widgets.Block = Block;
  
  // Delegate to a block widget based on the block's interfaces, or default to Block.
  function PickBlock(config) {
    if (Object.getPrototypeOf(this) !== PickBlock.prototype) {
      throw new Error('cannot inherit from PickBlock');
    }
    
    var targetCell = config.target;
    var context = config.context;
    
    var ctorCell = new DerivedCell(values.block, config.scheduler, function (dirty) {
      var block = targetCell.depend(dirty);
      
      // TODO kludgy, need better representation of interfaces
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
    });
    
    return new (ctorCell.depend(config.rebuildMe))(config);
  }
  widgets.PickBlock = PickBlock;
  
  // Suppresses all visibility of null objects
  function NullWidget(config) {
    Block.call(this, config, function () {}, true);
  }
  widgets['interface:shinysdr.values.INull'] = NullWidget;
  
  // Widget for the top block
  function Top(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      // TODO: It's a lousy design to require widgets to know what not to show. We should have a generic system for multiple widgets to decide "OK, you'll display this and I won't".
      ignore('monitor');  // displayed separately
      ignore('telemetry_store');  // displayed separately
      
      var sourceToolbar = this.element.appendChild(document.createElement('div'));
      sourceToolbar.className = 'panel frame-controls';
      sourceToolbar.appendChild(document.createTextNode('RF source '));
      if ('source_name' in block) {
        ignore('source_name');
        var sourceEl = sourceToolbar.appendChild(document.createElement('select'));
        createWidgetExt(config.context, Select, sourceEl, block.source_name);
      }
      
      // TODO: Figure out a good way to display options for all devices
      ignore('sources');
      addWidget('source', Device);

      addWidget('clip_warning', Banner);
      addWidget('receivers', ReceiverSet);
      addWidget('accessories', AccessorySet);
      
      setToDetails();
    });
  }
  widgets.Top = Top;
  
  function BlockSet(widgetCtor, buildEntry) {
    return function TypeSetInst(config) {
      // We do not inherit from Block, because we don't want the rebuild-on-reshape behavior (so we can do something more efficient) and we don't need the rest of it.
      var block = config.target.depend(config.rebuildMe);
      var idPrefix = config.idPrefix;
      var childContainer = this.element = config.element;

      // Keys are block keys
      var childWidgetElements = Object.create(null);

      var createChild = function (name) {
        var toolbar;
        var widgetContainer = childContainer;
        function setInsertion(element) {
          widgetContainer = element;
        }
        // buildContainer must append exactly one child. TODO: cleaner
        var widgetPlaceholder = buildEntry(childContainer, block, name);
        if (idPrefix) {
          widgetPlaceholder.id = idPrefix + name;
        }
        var widgetContainer = childContainer.lastChild;
        var widgetHandle = createWidgetExt(config.context, widgetCtor, widgetPlaceholder, block[name]);
        return {
          toolbar: toolbar,
          widgetHandle: widgetHandle,
          element: widgetContainer
        };
      }.bind(this);

      function handleReshape() {
        block._reshapeNotice.listen(handleReshape);
        Object.keys(block).forEach(function (name) {
          if (!childWidgetElements[name]) {
            childWidgetElements[name] = createChild(name);
          }
        });
        for (var oldName in childWidgetElements) {
          if (!(oldName in block)) {
            childWidgetElements[oldName].widgetHandle.destroy();
            childContainer.removeChild(childWidgetElements[oldName].element);
            delete childWidgetElements[oldName];
          }
        }
      }
      handleReshape.scheduler = config.scheduler;
      handleReshape();
    };
  }
  widgets.BlockSet = BlockSet;
  
  function BlockSetInFrameEntryBuilder(userTypeName) {
    return function blockSetInFrameEntryBuilder(setElement, block, name) {
      var container = setElement.appendChild(document.createElement('div'));
      container.className = 'frame';
      var toolbar = container.appendChild(document.createElement('div'));
      toolbar.className = 'panel frame-controls';
      
      if (block['_implements_shinysdr.values.IWritableCollection']) {
        var del = document.createElement('button');
        del.textContent = '\u2573';
        del.className = 'frame-delete-button';
        toolbar.appendChild(del);
        del.addEventListener('click', function(event) {
          block.delete(name);
        });
      }
      
      toolbar.appendChild(document.createTextNode(' ' + userTypeName + ' '));
      
      var label = document.createElement('span');
      label.textContent = name;
      toolbar.appendChild(label);
      
      return container.appendChild(document.createElement('div'));
    };
  }
  
  function windowEntryBuilder(setElement, block, name, setInsertion) {
    var subwindow = document.createElement('shinysdr-subwindow');
    subwindow.id = 'section-' + name;  // TODO match block id system instead of this (need context)
    var header = subwindow.appendChild(document.createElement('h2'));
    header.appendChild(document.createTextNode(name));  // TODO formatting
    var body = subwindow.appendChild(document.createElement('div'));
    body.classList.add('sidebar');  // TODO not quite right class -- we want main-ness but scrolling
    body.classList.add('frame');
    
    setElement.appendChild(subwindow);
    return body.appendChild(document.createElement('div'));
  }
  
  function blockSetNoHeader(setElement, block, name, setInsertion) {
    return setElement.appendChild(document.createElement('div'));
  }
  
  var DeviceSet = widgets.DeviceSet = BlockSet(Device, BlockSetInFrameEntryBuilder('Device'));
  var ReceiverSet = widgets.ReceiverSet = BlockSet(Receiver, BlockSetInFrameEntryBuilder('Receiver'));
  var AccessorySet = widgets.AccessorySet = BlockSet(PickBlock, BlockSetInFrameEntryBuilder('Accessory'));
  widgets.WindowBlocks = BlockSet(PickBlock, windowEntryBuilder);
  
  // Widget for a device
  function Device(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      var freqCell = block.freq;
      if (!isSingleValued(freqCell.type)) {
        addWidget('freq', Knob, 'Center frequency');
      }
      addWidget('rx_driver', PickBlock);
      addWidget('tx_driver', PickBlock);
      addWidget('components', ComponentSet);
    });
  }
  widgets['interface:shinysdr.devices.IDevice'] = Device;
  var ComponentSet = BlockSet(PickBlock, blockSetNoHeader);
  
  // Widget for a RX driver block -- TODO break this stuff up
  function RXDriver(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      // If we have multiple gain-related controls, do a combined UI
      // TODO: Better feature-testing strategy
      var hasAGC = 'agc' in block && !isSingleValued(block.agc.type);
      var hasSingleGain = 'gain' in block;
      var hasMultipleGain = 'gains' in block;
      if (hasAGC + hasSingleGain + hasMultipleGain > 1) (function () {
        var gainModes = {};
        if (hasAGC) { gainModes['auto'] = 'AGC On'; ignore('agc'); }
        if (hasSingleGain) { gainModes['single'] = 'Manual Gain'; }
        if (hasMultipleGain && !(hasSingleGain && Object.keys(block.gains.depend(config.rebuildMe)).length == 1)) {
          // show gain stages UI only if there's more than one
          gainModes['stages'] = 'Stages';
        }
        Object.freeze(gainModes);
        var gainModeType = new Enum(gainModes);
        var gainModeCell = new LocalCell(gainModeType, block.agc.get() ? 'auto' : 'single');

        var gainPanel = getAppend().appendChild(document.createElement('div'));
        //gainPanel.appendChild(document.createTextNode('Gain '));
        var gainModeControl = gainPanel.appendChild(document.createElement('span'));
        createWidgetExt(config.context, Radio, gainModeControl, gainModeCell);
        
        var singleGainPanel;
        if (hasSingleGain) {
          singleGainPanel = gainPanel.appendChild(document.createElement('div'));
          createWidgetExt(config.context, LinSlider, singleGainPanel.appendChild(document.createElement('div')), block.gain);
          ignore('gain');
        }
        var multipleGainPanel;
        if (hasMultipleGain) {
          multipleGainPanel = gainPanel.appendChild(document.createElement('div'));
          createWidgetExt(config.context, Block, multipleGainPanel.appendChild(document.createElement('div')), block.gains);
          ignore('gains');
        }
        
        function bindGainModeSet() {
          var mode = gainModeCell.depend(bindGainModeSet);
          if (mode === 'auto' && !block.agc.get()) {
            block.agc.set(true);
          } else if (hasAGC) {
            block.agc.set(false);
          }
        }
        bindGainModeSet.scheduler = config.scheduler;
        bindGainModeSet();
        function bindGainModeGet() {
          if (hasAGC && block.agc.depend(bindGainModeGet)) {
            gainModeCell.set('auto');
          } else if (gainModeCell.get() === 'auto') {
            gainModeCell.set('single');
          }
        }
        bindGainModeGet.scheduler = config.scheduler;
        bindGainModeGet();

        function updateUI() {
          var mode = gainModeCell.depend(updateUI);
          if (hasSingleGain) {
            singleGainPanel.style.display = mode === 'single' ? 'block' : 'none';
          }
          if (hasMultipleGain) {
            multipleGainPanel.style.display = mode === 'stages' ? 'block' : 'none';
          }
        }
        updateUI.scheduler = config.scheduler;
        updateUI();
      }());
      
      setToDetails();
      
      addWidget('correction_ppm', SmallKnob, 'Freq.corr. (PPM)');
      
      ignore('output_type');
    }, true);
  }
  widgets.RXDriver = RXDriver;
  widgets['interface:shinysdr.devices.IRXDriver'] = RXDriver;
  
  // Widget for a receiver block
  function Receiver(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('is_valid');
      
      var deviceAndFreqPanel = getAppend().appendChild(document.createElement('div'));
      deviceAndFreqPanel.classList.add('panel');

      // RF source and link option
      var deviceSection = deviceAndFreqPanel.appendChild(document.createElement('div'));
      deviceSection.classList.add('widget-Receiver-device-controls');
      var hasDeviceMenu = !block.device_name.type.isSingleValued();
      if (hasDeviceMenu) {
        // deviceSection.appendChild(document.createTextNode('Input from '));
        var deviceMenu = deviceSection.appendChild(document.createElement('select'));
        createWidgetExt(config.context, Select, deviceMenu, block.device_name);
        ignore('device_name');
      } else {
        deviceSection.appendChild(document.createTextNode('Frequency '));
        ignore('device_name');
      }
      if ('freq_linked_to_device' in block) {
        var linkLabel = deviceSection.appendChild(document.createElement('label'));
        var linkCheckbox = linkLabel.appendChild(document.createElement('input'));
        linkLabel.appendChild(document.createTextNode(' Follow device'));
        linkCheckbox.type = 'checkbox';
        createWidgetExt(config.context, Toggle, linkCheckbox, block.freq_linked_to_device);
        ignore('freq_linked_to_device');
      }
      
      var knobContainer = deviceAndFreqPanel.appendChild(document.createElement('div'));
      createWidgetExt(config.context, Knob, knobContainer, block.rec_freq);
      ignore('rec_freq');
      
      addWidget('mode', Radio);
      addWidget('demodulator', Demodulator);
      
      var saveInsert = getAppend();
      var audioPanel = saveInsert.appendChild(document.createElement('table'));
      audioPanel.classList.add('panel');
      audioPanel.classList.add('aligned-controls-table');
      setInsertion(audioPanel);

      // TODO pick some cleaner way to produce all this html
      ignore('audio_power');
      var powerRow = audioPanel.appendChild(document.createElement('tr'));
      powerRow.appendChild(document.createElement('th')).appendChild(document.createTextNode('Audio'));
      var meter = powerRow.appendChild(document.createElement('td')).appendChild(document.createElement('meter'));
      createWidgetExt(config.context, Meter, meter, block.audio_power);
      var meterNumber = powerRow.appendChild(document.createElement('td')).appendChild(document.createElement('tt'));
      createWidgetExt(config.context, NumberWidget, meterNumber, block.audio_power);

      ignore('audio_gain');
      var gainRow = audioPanel.appendChild(document.createElement('tr'));
      gainRow.appendChild(document.createElement('th')).appendChild(document.createTextNode('Vol'));
      var gainSlider = gainRow.appendChild(document.createElement('td')).appendChild(document.createElement('input'));
      gainSlider.type = 'range';
      createWidgetExt(config.context, LinSlider, gainSlider, block.audio_gain);
      var gainNumber = gainRow.appendChild(document.createElement('td')).appendChild(document.createElement('tt'));
      createWidgetExt(config.context, NumberWidget, gainNumber, block.audio_gain);
      
      var otherRow = audioPanel.appendChild(document.createElement('tr'));
      otherRow.appendChild(document.createElement('th')).appendChild(document.createTextNode('Dest'));
      var otherCell = otherRow.appendChild(document.createElement('td'));
      otherCell.colSpan = 2;
      var otherBox = otherCell.appendChild(document.createElement('span'));
      ignore('audio_destination');
      var dest = otherBox.appendChild(document.createElement('select'));
      createWidgetExt(config.context, Select, dest, block.audio_destination);
      if (!block.audio_pan.type.isSingleValued()) {
        ignore('audio_pan');
        otherBox.appendChild(document.createTextNode('L'));
        var panSlider = otherBox.appendChild(document.createElement('input'));
        panSlider.type = 'range';
        createWidgetExt(config.context, LinSlider, panSlider, block.audio_pan);
        otherBox.appendChild(document.createTextNode('R'));
      }
      
      setInsertion(saveInsert);
      
      if ('rec_freq' in block) {
        addWidget(null, SaveButton);
      }
    });
  }
  widgets.Receiver = Receiver;
  
  // Widget for a demodulator block
  function Demodulator(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('band_filter_shape');
      if ('rf_power' in block && 'squelch_threshold' in block) (function() {
        var squelchAndPowerPanel = this.element.appendChild(document.createElement('table'));
        squelchAndPowerPanel.classList.add('panel');
        squelchAndPowerPanel.classList.add('aligned-controls-table');
        function addRow(label, wtarget, wclass, wel) {
          ignore(wtarget);
          var row = squelchAndPowerPanel.appendChild(document.createElement('tr'));
          row.appendChild(document.createElement('th'))
            .appendChild(document.createTextNode(label));
          var widgetEl = row.appendChild(document.createElement('td'))
            .appendChild(document.createElement(wel));
          if (wel === 'input') widgetEl.type = 'range';
          createWidgetExt(config.context, wclass, widgetEl, block[wtarget]);
          var numberEl = row.appendChild(document.createElement('td'))
            .appendChild(document.createElement('tt'));
          createWidgetExt(config.context, NumberWidget, numberEl, block[wtarget]);
        }
        addRow('RF', 'rf_power', Meter, 'meter');
        addRow('Squelch', 'squelch_threshold', LinSlider, 'input');
      }.call(this)); else {
        // one of these is missing, use independently-conditional fallback
        addWidget('rf_power', Meter, 'Power');
        addWidget('squelch_threshold', LinSlider, 'Squelch');
      }
      
      // TODO: VOR plugin stuff; let the plugin handle it
      addWidget('angle', widgets.VOR$Angle, '');
      ignore('zero_point');
    }, true);
  }
  widgets['interface:shinysdr.modes.IDemodulator'] = Demodulator;
  
  // Widget for a monitor block
  function Monitor(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      var element = this.element = config.element;
      element.classList.add('hscalegroup');
      element.id = config.element.id;
      
      var overlayContainer = element.appendChild(document.createElement('div'));
      overlayContainer.classList.add('hscale');

      // TODO: shouldn't need to have this declared, should be implied by context
      var isRFSpectrum = config.element.hasAttribute('data-is-rf-spectrum');
      var context = config.context.withSpectrumView(element, overlayContainer, block, isRFSpectrum);
      
      function makeOverlayPiece(name) {
        var el = overlayContainer.appendChild(document.createElement(name));
        el.classList.add('overlay');
        return el;
      }
      if (isRFSpectrum) createWidgetExt(context, ReceiverMarks, makeOverlayPiece('div'), block.fft);
      createWidgetExt(context, WaterfallPlot, makeOverlayPiece('canvas'), block.fft);
      ignore('fft');
      
      // TODO this is clunky. (Note we're not just using rebuildMe because we don't want to lose waterfall history and reinit GL and and and...)
      var radioCell = config.radioCell;
      var freqCell = new DerivedCell(Number, config.scheduler, function (dirty) {
        return radioCell.depend(dirty).source.depend(dirty).freq.depend(dirty);
      });
      var freqScaleEl = overlayContainer.appendChild(document.createElement('div'));
      createWidgetExt(context, FreqScale, freqScaleEl, freqCell);
      
      ignore('scope');
      ignore('time_length');
      
      // TODO should logically be doing this -- need to support "widget with possibly multiple target elements"
      //addWidget(null, MonitorParameters);
      ignore('signal_type');
      ignore('frame_rate');
      ignore('freq_resolution');
      ignore('paused');
      
      // kludge to trigger SpectrumView layout computations after it's added to the DOM :(
      setTimeout(function() {
        var resize = document.createEvent('Event');
        resize.initEvent('resize', false, false);
        window.dispatchEvent(resize);
      }, 0);
    });
  }
  widgets.Monitor = Monitor;
  
  // Widget for incidental controls for a monitor block
  function MonitorParameters(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('signal_type');
      ignore('fft');
      ignore('scope');
      addWidget('frame_rate', LogSlider, 'Rate');
      addWidget('freq_resolution', LogSlider, 'Resolution');
      if ('paused' in block) {
        var pausedLabel = getAppend().appendChild(document.createElement('label'));
        var pausedEl = pausedLabel.appendChild(document.createElement('input'));
        pausedEl.type = 'checkbox';
        pausedLabel.appendChild(document.createTextNode('Pause'));
        createWidgetExt(config.context, Toggle, pausedEl, block.paused);
        ignore('paused');
      }
      ignore('time_length');
    });
  }
  widgets.MonitorParameters = MonitorParameters;

  // Abstract
  function CanvasSpectrumWidget(config, buildGL, build2D) {
    var self = this;
    var fftCell = config.target;
    var view = config.view;
    
    var canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
    }
    this.element = canvas;
    view.addClickToTune(canvas);
    
    var glOptions = {
      alpha: true,
      depth: false,
      stencil: false,
      antialias: false,
      preserveDrawingBuffer: false
    };
    var gl = gltools.getGL(config, canvas, glOptions);
    var ctx2d = canvas.getContext('2d');
    
    var dataHook = function () {}, drawOuter = function () {};
    
    var draw = config.boundedFn(function drawOuterTrampoline() {
      view.n.listen(draw);
      
      // Update canvas position and dimensions.
      var cleared = false;
      var lvf = view.leftVisibleFreq();
      var rvf = view.rightVisibleFreq();
      canvas.style.marginLeft = view.freqToCSSLeft(lvf);
      canvas.style.width = view.freqToCSSLength(view.rightVisibleFreq() - view.leftVisibleFreq());
      var w = canvas.offsetWidth;
      var h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
        cleared = true;
      }
      
      drawOuter(cleared);
    });
    draw.scheduler = config.scheduler;
    
    if (gl) (function() {
      function initContext() {
        var drawImpl = buildGL(gl, draw);
        dataHook = drawImpl.newData.bind(drawImpl);
        
        drawOuter = drawImpl.performDraw.bind(drawImpl);
      }
      
      initContext();
      gltools.handleContextLoss(canvas, initContext);
    }.call(this)); else if (ctx2d) (function () {
      var drawImpl = build2D(ctx2d, draw);
      dataHook = drawImpl.newData.bind(drawImpl);
      drawOuter = drawImpl.performDraw.bind(drawImpl);
    }.call(this));
    
    function newFFTFrame(bundle) {
      dataHook(bundle);
      draw.scheduler.enqueue(draw);
    }
    newFFTFrame.scheduler = config.scheduler;

    fftCell.subscribe(newFFTFrame);
    draw();
  }
  
  function ScopePlot(config) {
    var self = this;
    var scopeCell = config.target;
    var storage = config.storage;
    var scheduler = config.scheduler;
    
    var canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
    }
    this.element = canvas;
    
    var viewAngle = storage ? (+storage.getItem('angle')) || 0 : 0;
    
    var bufferToDraw = null;
    var lastLength = NaN;
    
    var gl = gltools.getGL(config, canvas, {
      alpha: false,
      depth: true,
      stencil: false,
      antialias: true,
      preserveDrawingBuffer: false
    });
    gl.enable(gl.DEPTH_TEST);
    
    var att_time;
    var att_signal;
    
    var timeBuffer = gl.createBuffer();
    var signalBuffer = gl.createBuffer();
    
    var vertexShaderSource = ''
      + 'attribute float time;\n'
      + 'attribute vec2 signal;\n'
      + 'uniform mat4 projection;\n'
      + 'uniform bool channel;\n'
      + 'varying mediump float v_time;\n'
      + 'varying mediump vec2 v_signal;\n'
      + 'void main(void) {\n'
      + '  float y = channel ? signal.x : signal.y;\n'
      + '  //gl_Position = vec4(time * 2.0 - 1.0, y, 0.0, 1.0);\n'
      + '  vec4 basePos = vec4(signal, time * 2.0 - 1.0, 1.0);\n'
      + '  gl_Position = basePos * projection;\n'
      + '  v_time = time;\n'
      + '  v_signal = signal;\n'
      + '}\n';
    var fragmentShaderSource = ''
      + 'varying mediump float v_time;\n'
      + 'void main(void) {\n'
      + '  gl_FragColor = vec4(v_time, 1.0 - v_time, 0.0, 1.0);\n'
      + '}\n';
    var program = gltools.buildProgram(gl, vertexShaderSource, fragmentShaderSource);
    var att_time = gl.getAttribLocation(program, 'time');
    var att_signal = gl.getAttribLocation(program, 'signal');
    gl.enableVertexAttribArray(att_time);
    gl.enableVertexAttribArray(att_signal);
    gl.bindBuffer(gl.ARRAY_BUFFER, timeBuffer);
    gl.vertexAttribPointer(
      att_time,
      1, // components
      gl.FLOAT,
      false,
      0,
      0);
    gl.bindBuffer(gl.ARRAY_BUFFER, signalBuffer);
    gl.vertexAttribPointer(
      att_signal,
      2, // components
      gl.FLOAT,
      false,
      0,
      0);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    
    gltools.handleContextLoss(canvas, config.rebuildMe);
    
    // dragging
    function drag(event) {
      viewAngle += event.movementX * 0.01;
      viewAngle = Math.min(Math.PI / 2, Math.max(0, viewAngle));
      if (storage) storage.setItem('angle', viewAngle);
      scheduler.enqueue(draw);
      event.stopPropagation();
      event.preventDefault(); // no drag selection
    }
    canvas.addEventListener('mousedown', function(event) {
      if (event.button !== 0) return;  // don't react to right-clicks etc.
      event.preventDefault();
      document.addEventListener('mousemove', drag, true);
      document.addEventListener('mouseup', function(event) {
        document.removeEventListener('mousemove', drag, true);
      }, true);
    }, false);
    
    var draw = config.boundedFn(function drawImpl() {
      if (!bufferToDraw) return;
      
      var w, h;
      // Fit current layout
      w = canvas.offsetWidth;
      h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
      }
      var aspect = w / h;
      gl.viewport(0, 0, w, h);
      
      if (lastLength != bufferToDraw.length / 2) {
        lastLength = bufferToDraw.length / 2;
        gl.bindBuffer(gl.ARRAY_BUFFER, timeBuffer);
        var timeIndexes = new Float32Array(lastLength);
        for (var i = 0; i < lastLength; i++) {
          timeIndexes[i] = i / lastLength;
        }
        if (bufferToDraw) gl.bufferData(gl.ARRAY_BUFFER, timeIndexes, gl.STREAM_DRAW);
      }
      
      if (bufferToDraw) {
        gl.bindBuffer(gl.ARRAY_BUFFER, signalBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, bufferToDraw, gl.STREAM_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, null);
      }

      gl.uniformMatrix4fv(gl.getUniformLocation(program, 'projection'), false, new Float32Array([
        Math.cos(viewAngle) / aspect, 0, -Math.sin(viewAngle), 0,
        0, 1, 0, 0,
        Math.sin(viewAngle) / aspect, 0, Math.cos(viewAngle), 0,
        0, 0, 0, 1,
      ]));
      
      gl.uniform1f(gl.getUniformLocation(program, 'channel'), 0);
      gl.drawArrays(gl.LINE_STRIP, 0, lastLength);
      gl.uniform1f(gl.getUniformLocation(program, 'channel'), 1);
      gl.drawArrays(gl.LINE_STRIP, 0, lastLength);
    });
    draw.scheduler = config.scheduler;
    
    function newScopeFrame(bundle) {
      bufferToDraw = bundle[1];
      draw.scheduler.enqueue(draw);
    }
    newScopeFrame.scheduler = config.scheduler;

    scopeCell.subscribe(newScopeFrame);
    draw();
  }
  widgets.ScopePlot = ScopePlot;
  
  function WaterfallPlot(config) {
    var self = this;
    var fftCell = config.target;
    var view = config.view;
    var avgAlphaCell = config.clientState.spectrum_average;
    
    var minLevelCell = config.clientState.spectrum_level_min;
    var maxLevelCell = config.clientState.spectrum_level_max;
    
    // I have read recommendations that color gradient scales should not involve more than two colors, as certain transitions between colors read as overly significant. However, in this case (1) we are not intending the waterfall chart to be read quantitatively, and (2) we want to have distinguishable small variations across a large dynamic range.
    var colors = [
      [0, 0, 0],
      [0, 0, 255],
      [0, 200, 255],
      [255, 255, 0],
      [255, 0, 0]
    ];
    var colorCountForScale = colors.length - 1;
    var colorCountForIndex = colors.length - 2;
    // value from 0 to 1, writes 0..255 into 4 elements of outArray
    function interpolateColor(value, outArray, base) {
      value *= colorCountForScale;
      var colorIndex = Math.max(0, Math.min(colorCountForIndex, Math.floor(value)));
      var colorInterp1 = value - colorIndex;
      var colorInterp0 = 1 - colorInterp1;
      var color0 = colors[colorIndex];
      var color1 = colors[colorIndex + 1];
      outArray[base    ] = color0[0] * colorInterp0 + color1[0] * colorInterp1;
      outArray[base + 1] = color0[1] * colorInterp0 + color1[1] * colorInterp1;
      outArray[base + 2] = color0[2] * colorInterp0 + color1[2] * colorInterp1;
      outArray[base + 3] = 255;
    }
    
    var backgroundColor = [119, 119, 119];
    var backgroundColorCSS = '#' + backgroundColor.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('');
    var backgroundColorGLSL = 'vec4(' + backgroundColor.map(function (v) { return v / 255; }).join(', ') + ', 1.0)';
    
    // TODO: Instead of hardcoding this, implement dynamic resizing of the history buffers. Punting for now because reallocating the GL textures would be messy.
    var historyCount = Math.max(
      1024,
      config.element.nodeName === 'CANVAS' ? config.element.height : 0);
    
    var canvas;
    var cleared = true;
    
    CanvasSpectrumWidget.call(this, config, buildGL, build2D);
    
    var lvf, rvf, w, h;
    function commonBeforeDraw(scheduledDraw) {
      view.n.listen(scheduledDraw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      w = canvas.width;
      h = canvas.height;
    }
    
    function buildGL(gl, draw) {
      canvas = self.element;

      var useFloatTexture =
        config.clientState.opengl_float.depend(config.rebuildMe) &&
        !!gl.getExtension('OES_texture_float') &&
        !!gl.getExtension('OES_texture_float_linear');

      var commonShaderCode = ''
        + 'uniform sampler2D centerFreqHistory;\n'
        + 'uniform highp float currentFreq;\n'
        + 'uniform mediump float freqScale;\n'
        + 'highp float getFreqOffset(highp vec2 c) {\n'
        + '  c = vec2(0.0, mod(c.t, 1.0));\n'
        + (useFloatTexture
              ? '  return currentFreq - texture2D(centerFreqHistory, c).r;\n'
              : '  highp vec4 hFreqVec = texture2D(centerFreqHistory, c);\n'
              + '  return currentFreq - (((hFreqVec.a * 255.0 * 256.0 + hFreqVec.b * 255.0) * 256.0 + hFreqVec.g * 255.0) * 256.0 + hFreqVec.r * 255.0);\n')
        + '}\n'

      var graphProgram = gltools.buildProgram(gl, 
        // vertex shader
        commonShaderCode
          + 'attribute vec4 position;\n'
          + 'uniform mediump float xZero, xScale;\n'
          + 'varying highp vec2 v_position;\n'
          + 'void main(void) {\n'
          + '  gl_Position = position;\n'
          + '  mediump vec2 basePos = (position.xy + vec2(1.0)) / 2.0;\n'
          + '  v_position = vec2(xScale * basePos.x + xZero, basePos.y);\n'
          + '}\n',
        // fragment shader
        commonShaderCode
          + 'uniform sampler2D data;\n'
          + 'uniform mediump float xScale, xRes, yRes, valueZero, valueScale;\n'
          + 'uniform highp float scroll;\n'
          + 'uniform highp float historyStep;\n'
          + 'uniform lowp float avgAlpha;\n'
          + 'varying highp vec2 v_position;\n'
          + 'const int stepRange = 2;\n'
          + 'highp vec2 stepStep;\n'  // initialized in main
          + 'const lowp float stepSumScale = 1.0/(float(stepRange) * 2.0 + 1.0);\n'
          + 'const int averaging = 32;\n'
          + 'mediump vec4 cmix(mediump vec4 before, mediump vec4 after, mediump float a) {\n'
          + '  return mix(before, after, clamp(a, 0.0, 1.0));\n'
          + '}\n'
          + 'mediump vec4 cut(mediump float boundary, mediump float offset, mediump vec4 before, mediump vec4 after) {\n'
          + '  mediump float case = (boundary - v_position.y) * yRes + offset;\n'
          + '  return cmix(before, after, case);\n'
          + '}\n'
          + 'lowp float filler(highp float value) {\n'
          + '  return cmix(vec4(0.0), vec4(value), value).r;\n'
          + '}\n'
          + 'mediump vec4 line(lowp float plus, lowp float average, lowp float intensity, mediump vec4 bg, mediump vec4 fg) {\n'
          + '  return cmix(bg, cut(average + plus, 0.5, bg, cut(average, -0.5, fg, bg)), intensity);\n'
          + '}\n'
          + 'highp vec2 coords(highp float framesBack) {\n'
          + '  // compute texture coords -- must be moduloed aterward\n'
          + '  return vec2(v_position.x, scroll - (framesBack + 0.5) * historyStep);\n'
          + '}\n'
          + 'highp float pointValueAt(highp vec2 c) {\n'
          + '  return valueZero + valueScale * texture2D(data, mod(c, 1.0)).r;\n'
          + '}\n'
          + 'highp float shiftedPointValueAt(highp vec2 c) {\n'
          + '  highp float offset = getFreqOffset(c) * freqScale;\n'
          + '  return pointValueAt(c + vec2(offset, 0.0));\n'
          + '}\n'
          + 'highp float pointAverageAt(highp vec2 c) {\n'
          + '  lowp float average = 0.0;\n'
          + '  for (int t = averaging - 1; t >= 0; t--) {\n'
          // note: FIR emulation of IIR filter because IIR is what the non-GL version uses
          + '      average = mix(average, shiftedPointValueAt(c + vec2(0.0, -float(t) * historyStep)), t >= averaging - 1 ? 1.0 : avgAlpha);\n'
          + '    }\n'
          + '  return average;\n'
          + '}\n'
          + 'void fetchSmoothValueAt(highp float t, out mediump float plus, out mediump float average) {\n'
          + '  highp vec2 texLookup = coords(t);\n'
          + '  average = 0.0;\n'
          + '  mediump float peak = -1.0;\n'
          + '  mediump float valley = 2.0;\n'
          + '  for (int i = -stepRange; i <= stepRange; i++) {\n'
          + '    mediump float value = shiftedPointValueAt(texLookup + stepStep * float(i));\n'
          + '    average += value;\n'
          + '    peak = max(peak, value);\n'
          + '    valley = min(valley, value);\n'
          + '  }\n'
          + '  average *= stepSumScale;\n'
          + '  plus = peak - average;\n'
          + '}\n'
          + 'void fetchSmoothAverageValueAt(out mediump float plus, out mediump float average) {\n'
          + '  highp vec2 texLookup = coords(0.0);\n'
          + '  average = 0.0;\n'
          + '  mediump float peak = -1.0;\n'
          + '  mediump float valley = 2.0;\n'
          + '  for (int i = -stepRange; i <= stepRange; i++) {\n'
          + '    mediump float value = pointAverageAt(texLookup + stepStep * float(i));\n'
          + '    average += value;\n'
          + '    peak = max(peak, value);\n'
          + '    valley = min(valley, value);\n'
          + '  }\n'
          + '  average *= stepSumScale;\n'
          + '  plus = peak - average;\n'
          + '}\n'
          + 'lowp float accumFillIntensity() {\n'
          + '  lowp float accumFill = 0.0;\n'
          + '  for (highp float i = 0.0; i < float(averaging); i += 1.0) {\n'
          + '    lowp float average;\n'
          + '    lowp float plus;\n'
          + '    fetchSmoothValueAt(i, plus, average);\n'
          + '    accumFill += cut(average, 1.0, vec4(0.0), vec4(average)).r;\n'
          + '  }\n'
          + '  return accumFill * (1.0 / float(averaging));'
          + '}\n'
          + 'void main(void) {\n'
          + '  // initialize globals\n'
          + '  stepStep = vec2(xScale / xRes * (1.0 / float(stepRange)), 0.0);\n'
          + '  \n'
          + '  mediump float aaverage;\n'
          + '  mediump float aplus;\n'
          + '  fetchSmoothAverageValueAt(aplus, aaverage);\n'
          + '  mediump float laverage;\n'
          + '  mediump float lplus;\n'
          + '  fetchSmoothValueAt(0.0, lplus, laverage);\n'
          + '  gl_FragColor = vec4(0.0, 0.5, 1.0, 1.0) * accumFillIntensity() * 3.0;\n'
          + '  gl_FragColor = line(aplus, aaverage, 0.75, gl_FragColor, vec4(0.0, 1.0, 0.6, 1.0));\n'
          + '  gl_FragColor = line(lplus, laverage, max(0.0, laverage - aaverage) * 4.0, gl_FragColor, vec4(1.0, 0.2, 0.2, 1.0));\n'
        + '}\n');
      var graphQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(graphProgram, 'position'));

      var waterfallProgram = gltools.buildProgram(gl,
        // vertex shader
        commonShaderCode
          + 'attribute vec4 position;\n'
          + 'varying highp vec2 v_position;\n'
          + 'uniform highp float scroll;\n'
          + 'uniform highp float xTranslate, xScale;\n'
          + 'uniform highp float yScale;\n'
          + 'void main(void) {\n'
          // TODO use a single input matrix instead of this
          + '  mat3 viewToTexture = mat3(0.5, 0.0, 0.0, 0.0, 0.5, 0.0, 0.5, 0.5, 1.0);\n'
          + '  mat3 zoom = mat3(xScale, 0.0, 0.0, 0.0, 1.0, 0.0, xTranslate, 0.0, 1.0);\n'
          + '  mat3 applyYScale = mat3(1.0, 0.0, 0.0, 0.0, yScale, 0.0, 0.0, -yScale, 1.0);\n'
          + '  mat3 viewMatrix = applyYScale * zoom * viewToTexture;\n'
          + '  gl_Position = position;\n'
          + '  v_position = (viewMatrix * position.xyw).xy + vec2(0.0, scroll);\n'
          + '}\n',
        // fragment shader
        commonShaderCode
          + 'uniform sampler2D data;\n'
          + 'uniform sampler2D gradient;\n'
          + 'uniform mediump float gradientZero;\n'
          + 'uniform mediump float gradientScale;\n'
          + 'varying mediump vec2 v_position;\n'
          + 'uniform highp float textureRotation;\n'
          + 'void main(void) {\n'
          + '  highp vec2 texLookup = mod(v_position, 1.0);\n'
          + '  highp float freqOffset = getFreqOffset(texLookup) * freqScale;\n'
          + '  mediump vec2 shift = texLookup + vec2(freqOffset, 0.0);\n'
          + '  if (shift.x < 0.0 || shift.x > 1.0) {\n'
          + '    gl_FragColor = ' + backgroundColorGLSL + ';\n'
          + '  } else {\n'
          + '    mediump float data = texture2D(data, shift + vec2(textureRotation, 0.0)).r;\n'
          + '    gl_FragColor = texture2D(gradient, vec2(0.5, gradientZero + gradientScale * data));\n'
          //+ '    gl_FragColor = texture2D(gradient, vec2(0.5, v_position.x));\n'
          //+ '    gl_FragColor = vec4(gradientZero + gradientScale * data * 4.0 - 0.5);\n'
          + '  }\n'
          + '}\n');
      var waterfallQuad = new SingleQuad(gl, -1, 1, -1, 1, gl.getAttribLocation(waterfallProgram, 'position'));
      
      var u_scroll = gl.getUniformLocation(waterfallProgram, 'scroll');
      var u_xTranslate = gl.getUniformLocation(waterfallProgram, 'xTranslate');
      var u_xScale = gl.getUniformLocation(waterfallProgram, 'xScale');
      var u_yScale = gl.getUniformLocation(waterfallProgram, 'yScale');
      var wu_currentFreq = gl.getUniformLocation(waterfallProgram, 'currentFreq');
      var gu_currentFreq = gl.getUniformLocation(graphProgram, 'currentFreq');
      var wu_freqScale = gl.getUniformLocation(waterfallProgram, 'freqScale');
      var gu_freqScale = gl.getUniformLocation(graphProgram, 'freqScale');
      var u_textureRotation = gl.getUniformLocation(waterfallProgram, 'textureRotation');
      
      var fftSize = Math.max(1, config.target.get().length);
      

      var bufferTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      // Ideally we would be linear in S (freq) and nearest in T (time), but that's not an option.
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      var historyFreqTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

      var gradientTexture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      (function() {
        var components = 4;
        // stretch = number of texels to generate per color. If we generate only the minimum and fully rely on hardware gl.LINEAR interpolation then certain pixels in the display tends to flicker as it scrolls, on some GPUs.
        var stretch = 10;
        var limit = (colors.length - 1) * stretch + 1;
        var gradientInit = new Uint8Array(limit * components);
        for (var i = 0; i < limit; i++) {
          interpolateColor(i / (limit - 1), gradientInit, i * 4);
        }

        gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0, // level
          gl.RGBA, // internalformat
          1, // width
          gradientInit.length / components, // height
          0, // border
          gl.RGBA, // format
          gl.UNSIGNED_BYTE, // type
          gradientInit);

        // gradientZero and gradientScale set the scaling from data texture values to gradient texture coordinates
        // gradientInset is the amount to compensate for half-texel edges
        function computeGradientScale() {
          var gradientInset = 0.5 / (gradientInit.length / components);
          var insetZero = gradientInset;
          var insetScale = 1 - gradientInset * 2;
          var valueZero, valueScale;
          if (useFloatTexture) {
            var minLevel = minLevelCell.depend(computeGradientScale);
            var maxLevel = maxLevelCell.depend(computeGradientScale);
            valueScale = 1 / (maxLevel - minLevel);
            valueZero = valueScale * -minLevel;
          } else {
            valueZero = 0;
            valueScale = 1;
          }
        
          gl.useProgram(graphProgram);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'valueZero'), valueZero);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'valueScale'), valueScale);

          gl.useProgram(waterfallProgram);
          gl.uniform1f(gl.getUniformLocation(waterfallProgram, 'gradientZero'), insetZero + insetScale * valueZero);
          gl.uniform1f(gl.getUniformLocation(waterfallProgram, 'gradientScale'), insetScale * valueScale);
          draw.scheduler.enqueue(draw);
        }
        computeGradientScale.scheduler = config.scheduler;
        computeGradientScale();
      }());

      gl.bindTexture(gl.TEXTURE_2D, null);

      function configureTexture() {
        if (useFloatTexture) {
          var init = new Float32Array(fftSize*historyCount);
          for (var i = 0; i < fftSize*historyCount; i++) {
            init[i] = -1000;  // well below minimum display level
          }
          gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0, // level
            gl.LUMINANCE, // internalformat
            fftSize, // width (= fft size)
            historyCount, // height (= history size)
            0, // border
            gl.LUMINANCE, // format
            gl.FLOAT, // type -- TODO use non-float textures if needed
            init);

          var init = new Float32Array(historyCount);
          for (var i = 0; i < historyCount; i++) {
            init[i] = -1e20;  // dummy value which we hope will not land within the viewport
          }
          gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0, // level
            gl.LUMINANCE, // internalformat
            1, // width
            historyCount, // height (= history size)
            0, // border
            gl.LUMINANCE, // format
            gl.FLOAT, // type
            init);
        } else {
          var init = new Uint8Array(fftSize*historyCount*4);
          gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0, // level
            gl.LUMINANCE, // internalformat
            fftSize, // width (= fft size)
            historyCount, // height (= history size)
            0, // border
            gl.LUMINANCE, // format
            gl.UNSIGNED_BYTE, // type
            init);

          var init = new Uint8Array(historyCount*4);
          gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
          gl.texImage2D(
            gl.TEXTURE_2D,
            0, // level
            gl.RGBA, // internalformat
            1, // width
            historyCount, // height (= history size)
            0, // border
            gl.RGBA, // format
            gl.UNSIGNED_BYTE,
            init);
        }

        gl.bindTexture(gl.TEXTURE_2D, null);
      }
      configureTexture();

      // initial state of graph program
      gl.useProgram(graphProgram);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'data'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(graphProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE0);
      
      // initial state of waterfall program
      gl.useProgram(waterfallProgram);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'data'), 1);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'centerFreqHistory'), 2);
      gl.activeTexture(gl.TEXTURE3);
      gl.bindTexture(gl.TEXTURE_2D, gradientTexture);
      gl.uniform1i(gl.getUniformLocation(waterfallProgram, 'gradient'), 3);
      gl.activeTexture(gl.TEXTURE0);

      var slicePtr = 0;

      var freqWriteBuffer = useFloatTexture ? new Float32Array(1) : new Uint8Array(4);
      var intConversionBuffer, intConversionOut;
      
      return {
        newData: function (fftBundle) {
          var buffer = fftBundle[1];
          var bufferCenterFreq = fftBundle[0].freq;
          
          if (buffer.length === 0) {
            return;
          }
          
          if (buffer.length !== fftSize || !useFloatTexture && !intConversionBuffer) {
            fftSize = buffer.length;
            configureTexture();
            intConversionBuffer = useFloatTexture ? null : new Uint8ClampedArray(fftSize);
            intConversionOut = useFloatTexture ? null : new Uint8Array(intConversionBuffer.buffer);
          }

          // TODO: This doesn't need to be updated every frame, but it does depend on the view unlike other things
          // Shift (with wrapping) the texture data by 1/2 minus half a bin width, to align the GL texels with the FFT bins.
          gl.uniform1f(u_textureRotation, config.view.isRealFFT() ? 0 : -(0.5 - 0.5/fftSize));

          if (useFloatTexture) {
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                fftSize,
                1,
                gl.LUMINANCE,
                gl.FLOAT,
                buffer);

            freqWriteBuffer[0] = bufferCenterFreq;
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                1,
                1,
                gl.LUMINANCE,
                gl.FLOAT,
                freqWriteBuffer);
          } else {
            gl.bindTexture(gl.TEXTURE_2D, bufferTexture);
            // TODO: By doing the level shift at this point, we are locking in the current settings. It would be better to arrange for min/max changes to rescale historical data as well, as it does in float-texture mode (would require keeping the original data as well as the texture contents and recopying it).
            var minLevel = minLevelCell.get();
            var maxLevel = maxLevelCell.get();
            var cscale = 255 / (maxLevel - minLevel);
            for (var i = 0; i < fftSize; i++) {
              intConversionBuffer[i] = (buffer[i] - minLevel) * cscale;
            }
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                fftSize,
                1,
                gl.LUMINANCE,
                gl.UNSIGNED_BYTE,
                intConversionOut);

            freqWriteBuffer[0] = (bufferCenterFreq >> 0) & 0xFF;
            freqWriteBuffer[1] = (bufferCenterFreq >> 8) & 0xFF;
            freqWriteBuffer[2] = (bufferCenterFreq >> 16) & 0xFF;
            freqWriteBuffer[3] = (bufferCenterFreq >> 24) & 0xFF;
            gl.bindTexture(gl.TEXTURE_2D, historyFreqTexture);
            gl.texSubImage2D(
                gl.TEXTURE_2D,
                0, // level
                0, // xoffset
                slicePtr, // yoffset
                1,
                1,
                gl.RGBA,
                gl.UNSIGNED_BYTE,
                freqWriteBuffer);
          }

          gl.bindTexture(gl.TEXTURE_2D, null);
          slicePtr = mod(slicePtr + 1, historyCount);
        },
        performDraw: function (didResize) {
          commonBeforeDraw(draw);
          var viewCenterFreq = view.getCenterFreq();
          var split = Math.round(canvas.height * config.clientState.spectrum_split.depend(draw));
          
          // common calculations
          var fs = 1.0 / (view.rightFreq() - view.leftFreq());
          
          gl.viewport(0, split, w, h - split);
          
          gl.useProgram(graphProgram);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xRes'), w);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'yRes'), h - split);
          gl.uniform1f(gu_freqScale, fs);
          gl.uniform1f(gu_currentFreq, viewCenterFreq);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'avgAlpha'), avgAlphaCell.depend(draw));
          // Adjust drawing region
          var viewCenterFreq = view.getCenterFreq();
          var lsf = view.leftFreq();
          var rsf = view.rightFreq();
          var bandwidth = rsf - lsf;
          var halfBinWidth = bandwidth / fftSize / 2;
          var xScale = (rvf-lvf)/(rsf-lsf);
          // The half bin width correction is because OpenGL texture coordinates put (0,0) between texels, not centered on one.
          var xZero = (lvf - viewCenterFreq + halfBinWidth)/(rsf-lsf);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xZero'), xZero);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'xScale'), xScale);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'scroll'), slicePtr / historyCount);
          gl.uniform1f(gl.getUniformLocation(graphProgram, 'historyStep'), 1.0 / historyCount);
          
          graphQuad.draw();
          
          gl.viewport(0, 0, w, split);
          
          gl.useProgram(waterfallProgram);
          gl.uniform1f(u_scroll, slicePtr / historyCount);
          gl.uniform1f(u_yScale, split / historyCount);
          gl.uniform1f(wu_freqScale, fs);
          gl.uniform1f(wu_currentFreq, viewCenterFreq);
          var xScale = (view.rightVisibleFreq() - view.leftVisibleFreq()) * fs;
          gl.uniform1f(u_xTranslate, (view.leftVisibleFreq() - view.leftFreq()) * fs);
          gl.uniform1f(u_xScale, xScale);

          waterfallQuad.draw();
          cleared = false;
        }
      };
    }
    
    function build2D(ctx, draw) {
      canvas = self.element;
      
      // secondary canvas to use for image scaling
      var scaler = document.createElement('canvas');
      scaler.height = 1;
      scaler.width = 4096;  // typical maximum supported width -- TODO use minimum
      var scalerCtx = scaler.getContext('2d');
      if (!scalerCtx) { throw new Error('failed to get headless canvas context'); }
      
      // view parameters recomputed on draw
      var freqToCanvasPixelFactor;
      var xTranslateFreq;
      var pixelWidthOfFFT;
      
      function paintSlice(imageData, freqOffset, y) {
        // TODO deal with left/right edge interpolation fringes
        scalerCtx.putImageData(imageData, 0, 0);
        ctx.drawImage(
          scaler,
          0, 0, imageData.width, 1,  // source rect
          freqToCanvasPixelFactor * (freqOffset - xTranslateFreq), y, pixelWidthOfFFT, 1);  // destination rect
      }
      
      // circular buffer of ImageData objects, and info to invalidate it
      var slices = [];
      var slicePtr = 0;
      var lastDrawnLeftVisibleFreq = NaN;
      var lastDrawnRightVisibleFreq = NaN;
      
      // for detecting when to invalidate the averaging buffer
      var lastDrawnCenterFreq = NaN;
      
      // Graph drawing parameters and functions
      // Each variable is updated in draw()
      // This is done so that the functions need not be re-created
      // each frame.
      var gxZero, xScale, xNegBandwidthCoord, xPosBandwidthCoord, yZero, yScale, firstPoint, lastPoint, fftLen, graphDataBuffer;
      function freqToCoord(freq) {
        return (freq - lvf) / (rvf-lvf) * w;
      }
      function graphPath() {
        ctx.beginPath();
        ctx.moveTo(xNegBandwidthCoord - xScale, h + 2);
        for (var i = firstPoint; i <= lastPoint; i++) {
          ctx.lineTo(gxZero + i * xScale, yZero + graphDataBuffer[mod(i, fftLen)] * yScale);
        }
        ctx.lineTo(xPosBandwidthCoord + xScale, h + 2);
      }
      
      // Drawing state for graph
      ctx.lineWidth = 1;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      
      var fillStyle = 'white';
      var strokeStyle = 'white';
      addLifecycleListener(canvas, 'init', function() {
        fillStyle = getComputedStyle(canvas).fill;
        strokeStyle = getComputedStyle(canvas).stroke;
      });
      
      function changedSplit() {
        cleared = true;
        draw.scheduler.enqueue(draw);
      }
      changedSplit.scheduler = config.scheduler;
      
      var performDraw = config.boundedFn(function performDrawImpl(clearedIn) {
        commonBeforeDraw(draw);
        
        cleared = cleared || clearedIn;
        var viewLVF = view.leftVisibleFreq();
        var viewRVF = view.rightVisibleFreq();
        var viewCenterFreq = view.getCenterFreq();
        freqToCanvasPixelFactor = w / (viewRVF - viewLVF);
        xTranslateFreq = viewLVF - view.leftFreq();
        pixelWidthOfFFT = view.getTotalPixelWidth();

        var split = Math.round(canvas.height * config.clientState.spectrum_split.depend(changedSplit));
        var topOfWaterfall = h - split;
        var heightOfWaterfall = split;

        var buffer, bufferCenterFreq;
        if (dataToDraw) {
          buffer = dataToDraw[1];
          bufferCenterFreq = dataToDraw[0].freq;
          var fftLength = buffer.length;

          // can't draw with w=0
          if (w === 0 || fftLength === 0) {
            return;
          }

          // Find slice to write into
          var ibuf;
          if (slices.length < historyCount) {
            slices.push([ibuf = ctx.createImageData(fftLength, 1), bufferCenterFreq]);
          } else {
            var record = slices[slicePtr];
            slicePtr = mod(slicePtr + 1, historyCount);
            ibuf = record[0];
            if (ibuf.width != fftLength) {
              ibuf = record[0] = ctx.createImageData(fftLength, 1);
            }
            record[1] = bufferCenterFreq;
          }

          // Generate image slice from latest FFT data.
          // TODO get half-pixel alignment right elsewhere, and supply wraparound on both ends in this data
          // TODO: By converting to color at this point, we are locking in the current min/max settings. It would be better to arrange for min/max changes to rescale historical data as well, as it does in GL-float-texture mode (would require keeping the original data as well as the texture contents and recopying it).
          var xZero = view.isRealFFT() ? 0 : Math.floor(fftLength / 2);
          var cScale = 1 / (maxLevelCell.get() - minLevelCell.get());
          var cZero = 1 - maxLevelCell.get() * cScale;
          var data = ibuf.data;
          for (var x = 0; x < fftLength; x++) {
            var base = x * 4;
            var colorVal = buffer[mod(x + xZero, fftLength)] * cScale + cZero;
            interpolateColor(colorVal, data, base);
          }
        }

        ctx.fillStyle = backgroundColorCSS;

        var sameView = lastDrawnLeftVisibleFreq === viewLVF && lastDrawnRightVisibleFreq === viewRVF;
        if (dataToDraw && sameView && !cleared) {
          // Scroll
          ctx.drawImage(ctx.canvas,
            0, topOfWaterfall, w, heightOfWaterfall-1,
            0, topOfWaterfall+1, w, heightOfWaterfall-1);

          // fill background of new line, if needed
          if (bufferCenterFreq !== viewCenterFreq) {
            ctx.fillRect(0, topOfWaterfall, w, 1);
          }

          // Paint newest slice
          paintSlice(ibuf, bufferCenterFreq - viewCenterFreq, topOfWaterfall);
        } else if (cleared || !sameView) {
          // Horizontal position changed, paint all slices onto canvas
          
          lastDrawnLeftVisibleFreq = viewLVF;
          lastDrawnRightVisibleFreq = viewRVF;
          // fill background so scrolling is of an opaque image
          ctx.fillRect(0, 0, w, h);
          
          var sliceCount = slices.length;
          for (var i = sliceCount - 1; i >= 0; i--) {
            var slice = slices[mod(i + slicePtr, sliceCount)];
            var y = topOfWaterfall + sliceCount - i - 1;
            if (y >= h) break;

            // paint slice
            paintSlice(slice[0], slice[1] - viewCenterFreq, y);
          }
          ctx.fillRect(0, y+1, w, h);
        }

        // Done with waterfall, now draw graph
        (function() {
          if (!graphDataBuffer) return;
          
          fftLen = graphDataBuffer.length;  // TODO name collisionish
          var halfFFTLen = Math.floor(fftLen / 2);
        
          if (halfFFTLen <= 0) {
            // no data yet, don't try to draw
            return;
          }

          var viewCenterFreq = view.getCenterFreq();
          gxZero = freqToCoord(viewCenterFreq);
          xNegBandwidthCoord = freqToCoord(view.leftFreq());
          xPosBandwidthCoord = freqToCoord(view.rightFreq());
          xScale = (xPosBandwidthCoord - xNegBandwidthCoord) / fftLen;
          yScale = -topOfWaterfall / (maxLevelCell.depend(draw) - minLevelCell.depend(draw));
          yZero = -maxLevelCell.depend(draw) * yScale;

          // choose points to draw
          firstPoint = Math.floor(-gxZero / xScale) - 1;
          lastPoint = Math.ceil((w - gxZero) / xScale) + 1;

          // clip so our oversized path doesn't hit waterfall
          ctx.save();
          ctx.beginPath();
          ctx.rect(0, 0, w, topOfWaterfall);
          ctx.clip();
          
          // Draw graph.
          // Fill is deliberately over stroke. This acts to deemphasize downward stroking of spikes, which tend to occur in noise.
          ctx.clearRect(0, 0, w, topOfWaterfall);
          ctx.fillStyle = fillStyle;
          ctx.strokeStyle = strokeStyle;
          graphPath();
          ctx.stroke();
          graphPath();
          ctx.fill();
          
          // unclip
          ctx.restore();
        }());

        dataToDraw = null;
        cleared = false;
      });

      var dataToDraw = null;  // TODO this is a data flow kludge
      return {
        newData: function (fftBundle) {
          var buffer = fftBundle[1];
          var bufferCenterFreq = fftBundle[0].freq;
          var len = buffer.length;
          var alpha = avgAlphaCell.get();
          var invAlpha = 1 - alpha;

          // averaging
          // TODO: Get separate averaged and unaveraged FFTs from server so that averaging behavior is not dependent on frame rate over the network
          if (!graphDataBuffer
              || graphDataBuffer.length !== len
              || (lastDrawnCenterFreq !== bufferCenterFreq
                  && !isNaN(bufferCenterFreq))) {
            lastDrawnCenterFreq = bufferCenterFreq;
            graphDataBuffer = new Float32Array(buffer);
          }

          for (var i = 0; i < len; i++) {
            graphDataBuffer[i] = graphDataBuffer[i] * invAlpha + buffer[i] * alpha;
          }
          
          // Hand data over to waterfall drawing immediately, so that the scrolling occurs and every frame is painted.
          // TODO: It would be more efficient to queue things so that if we _do_ have multiple frames to draw, we don't do multiple one-pixel scrolling steps
          dataToDraw = fftBundle;
          performDraw(false);
        },
        performDraw: performDraw
      };
    }
  }
  widgets.WaterfallPlot = WaterfallPlot;

  function to_dB(x) {
    return Math.log(x) / (Math.LN10 / 10);
  }

  function ReceiverMarks(config) {
    /* does not use config.target */
    var view = config.view;
    var radioCell = config.radioCell;
    var others = config.index.implementing('shinysdr.top.IHasFrequency');
    // TODO: That this cell matters here is shared knowledge between this and ReceiverMarks. Should instead be managed by SpectrumView (since it already handles freq coordinates), in the form "get Y position of minLevel".
    var splitCell = config.clientState.spectrum_split;
    var minLevelCell = config.clientState.spectrum_level_min;
    var maxLevelCell = config.clientState.spectrum_level_max;
    
    var canvas = config.element;
    if (canvas.tagName !== 'CANVAS') {
      canvas = document.createElement('canvas');
      canvas.classList.add('overlay');
    }
    this.element = canvas;
    
    var ctx = canvas.getContext('2d');
    var textOffsetFromTop =
        //ctx.measureText('j').fontBoundingBoxAscent; -- not yet supported
        10 + 2; // default font size is "10px", ignoring effect of baseline
    var textSpacing = 10 + 1;
    
    // Drawing parameters and functions
    // Each variable is updated in draw()
    // This is done so that the functions need not be re-created
    // each frame.
    var w, h, lvf, rvf;
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
    
    var draw = config.boundedFn(function drawImpl() {
      view.n.listen(draw);
      var visibleDevice = radioCell.depend(draw).source_name.depend(draw);
      lvf = view.leftVisibleFreq();
      rvf = view.rightVisibleFreq();
      
      canvas.style.marginLeft = view.freqToCSSLeft(lvf);
      canvas.style.width = view.freqToCSSLength(rvf - lvf);

      w = canvas.offsetWidth;
      h = canvas.offsetHeight;
      if (canvas.width !== w || canvas.height !== h) {
        // implicitly clears
        canvas.width = w;
        canvas.height = h;
      } else {
        ctx.clearRect(0, 0, w, h);
      }
      
      var yScale = -(h * (1 - splitCell.depend(draw))) / (maxLevelCell.depend(draw) - minLevelCell.depend(draw));
      var yZero = -maxLevelCell.depend(draw) * yScale;
      
      ctx.strokeStyle = 'gray';
      drawHair(view.getCenterFreq()); // center frequency
      
      others.depend(draw).forEach(function (object) {
        ctx.strokeStyle = 'green';
        drawHair(object.freq.depend(draw));
      });
      
      var receivers = radioCell.depend(draw).receivers.depend(draw);
      receivers._reshapeNotice.listen(draw);
      for (var recKey in receivers) {
        var receiver = receivers[recKey].depend(draw);
        var device_name_now = receiver.device_name.depend(draw);
        var rec_freq_now = receiver.rec_freq.depend(draw);
        
        if (!(lvf <= rec_freq_now && rec_freq_now <= rvf && device_name_now == visibleDevice)) {
          continue;
        }
        
        var band_filter_cell = receiver.demodulator.depend(draw).band_filter_shape;
        if (band_filter_cell) {
          var band_filter_now = band_filter_cell.depend(draw);
        }

        if (band_filter_now) {
          var fl = band_filter_now.low;
          var fh = band_filter_now.high;
          var fhw = band_filter_now.width / 2;
          ctx.fillStyle = '#3A3A3A';
          drawBand(rec_freq_now + fl - fhw, rec_freq_now + fh + fhw);
          ctx.fillStyle = '#444444';
          drawBand(rec_freq_now + fl + fhw, rec_freq_now + fh - fhw);
        }

        // TODO: marks ought to be part of a distinct widget
        var squelch_threshold_cell = receiver.demodulator.depend(draw).squelch_threshold;
        if (squelch_threshold_cell) {
          var squelchPower = squelch_threshold_cell.depend(draw);
          var squelchL, squelchR, bandwidth;
          if (band_filter_now) {
            squelchL = freqToCoord(rec_freq_now + band_filter_now.low);
            squelchR = freqToCoord(rec_freq_now + band_filter_now.high);
            bandwidth = band_filter_now.high - band_filter_now.low;
          } else {
            // dummy
            squelchL = 0;
            squelchR = w;
            bandwidth = 10e3;
          }
          var squelchPSD = squelchPower - to_dB(bandwidth);
          var squelchY = Math.floor(yZero + squelchPSD * yScale) + 0.5;
          var minSquelchHairWidth = 30;
          if (squelchR - squelchL < minSquelchHairWidth) {
            var squelchMid = (squelchR + squelchL) / 2;
            squelchL = squelchMid - minSquelchHairWidth/2;
            squelchR = squelchMid + minSquelchHairWidth/2;
          }
          ctx.strokeStyle = '#F00';
          ctx.beginPath();
          ctx.moveTo(squelchL, squelchY);
          ctx.lineTo(squelchR, squelchY);
          ctx.stroke();
        }

        ctx.strokeStyle = 'white';
        drawHair(rec_freq_now); // receiver
        ctx.fillStyle = 'white';
        var textX = freqToCoord(rec_freq_now) + 2;
        var textY = textOffsetFromTop - textSpacing;

        ctx.fillText(recKey, textX, textY += textSpacing);
        ctx.fillText(formatFreqExact(receiver.rec_freq.depend(draw)), textX, textY += textSpacing);
        ctx.fillText(receiver.mode.depend(draw), textX, textY += textSpacing);
      }
    });
    draw.scheduler = config.scheduler;
    config.scheduler.enqueue(draw);  // must draw after widget inserted to get proper layout
  }
  widgets.ReceiverMarks = ReceiverMarks;
  
  function Knob(config) {
    var target = config.target;

    var type = target.type;
    // TODO: use integer flag of Range, w decimal points?
    function clamp(value, direction) {
      if (type instanceof values.Range) {  // TODO: better type protocol
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
      digit.tabIndex = -1;
      var digitText = digit.appendChild(document.createTextNode('0'));
      places[i] = {element: digit, text: digitText};
      var scale = Math.pow(10, i);
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
  widgets.Knob = Knob;
  
  function formatFreqMHz(freq) {
    return (freq / 1e6).toFixed(2);
  }
  
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
  
  // minimal ES-Harmony shim for use by VisibleItemCache
  // O(n) but fast
  var Map = window.Map || (function() {
    function Map() {
      this._keys = [];
      this._values = [];
    }
    Map.prototype.delete = function (key) {
      var i = this._keys.indexOf(key);
      if (i >= 0) {
        var last = this._keys.length - 1;
        if (i < last) {
          this._keys[i] = this._keys[last];
          this._values[i] = this._values[last];
        }
        this._keys.length = last;
        this._values.length = last;
        return true;
      } else {
        return false;
      }
    };
    Map.prototype.get = function (key) {
      var i = this._keys.indexOf(key);
      if (i >= 0) {
        return this._values[i];
      } else {
        return undefined;
      }
    };
    Map.prototype.set = function (key, value) {
      var i = this._keys.indexOf(key);
      if (i >= 0) {
        this._values[i] = value;
      } else {
        this._keys.push(key);
        this._values.push(value);
      }
    };
    Object.defineProperty(Map.prototype, 'size', {
      get: function () {
        return this._keys.length;
      }
    });
    return Map;
  }());
  
  // Keep track of elements corresponding to keys and insert/remove as needed
  // maker() returns an element or falsy
  function VisibleItemCache(parent, maker) {
    var cache = new Map();
    var count = 0;
    
    this.add = function(key) {
      count++;
      var element = cache.get(key);
      if (!element) {
        element = maker(key);
        if (!element) {
          return;
        }
        parent.appendChild(element);
        element.my_cacheKey = key;
        cache.set(key, element);
      }
      if (!element.parentNode) throw new Error('oops');
      element.my_inUse = true;
      return element;
    };
    this.flush = function() {
      var active = parent.childNodes;
      for (var i = active.length - 1; i >= 0; i--) {
        var element = active[i];
        if (element.my_inUse) {
          element.my_inUse = false;
        } else {
          parent.removeChild(element);
          if (!'my_cacheKey' in element) throw new Error('oops2');
          cache.delete(element.my_cacheKey);
        }
      }
      if (active.length !== count || active.length !== cache.size) throw new Error('oops3');
      count = 0;
    };
  }
  
  // A collection/algorithm which allocates integer indexes to provided intervals such that no overlapping intervals have the same index.
  // Intervals are treated as open, unless the endpoints are equal in which case they are treated as closed (TODO: slightly inconsistently but it doesn't matter for the application).
  function IntervalStacker() {
    this._elements = [];
  }
  IntervalStacker.prototype.clear = function () {
    this._elements.length = 0;
  };
  // Find index of value in the array, or index to insert at
  IntervalStacker.prototype._search1 = function (position) {
    // if it turns out to matter, replace this with a binary search
    var array = this._elements;
    for (var i = 0; i < array.length; i++) {
      if (array[i].key >= position) return i;
    }
    return i;
  };
  IntervalStacker.prototype._ensure1 = function (position, which) {
    var index = this._search1(position);
    var el = this._elements[index];
    if (!(el && el.key === position)) {
      // insert
      var newEl = {key: position, below: Object.create(null), above: Object.create(null)};
      // insert neighbors' info
      var lowerNeighbor = this._elements[index - 1];
      if (lowerNeighbor) {
        Object.keys(lowerNeighbor.above).forEach(function (value) {
          newEl.below[value] = newEl.above[value] = true;
        });
      }
      var upperNeighbor = this._elements[index + 1];
      if (upperNeighbor) {
        Object.keys(upperNeighbor.below).forEach(function (value) {
          newEl.below[value] = newEl.above[value] = true;
        });
      }
      
      // TODO: if it turns out to be worthwhile, use a more efficient insertion
      this._elements.push(newEl);
      this._elements.sort(function (a, b) { return a.key - b.key; });
      var index2 = this._search1(position);
      if (index2 !== index) throw new Error('assumption violated');
      if (this._elements[index].key !== position) { debugger; throw new Error('assumption2 violated'); }
    }
    return index;
  };
  // Given an interval, which may be zero-length, claim and return the lowest index (>= 0) which has not previously been used for an overlapping interval.
  IntervalStacker.prototype.claim = function (low, high) {
    // TODO: Optimize by not _storing_ zero-length intervals
    // note must be done in this order to not change the low index
    var lowIndex = this._ensure1(low);
    var highIndex = this._ensure1(high);
    //console.log(this._elements.map(function(x){return x.key;}), lowIndex, highIndex);
    
    for (var value = 0; value < 1000; value++) {
      var free = true;
      for (var i = lowIndex; i <= highIndex; i++) {
        var element = this._elements[i];
        if (i > lowIndex || lowIndex === highIndex) {
          free = free && !element.below[value];
        }
        if (i < highIndex || lowIndex === highIndex) {
          free = free && !element.above[value];
        }
      }
      if (!free) continue;
      for (var i = lowIndex; i <= highIndex; i++) {
        var element = this._elements[i];
        if (i > lowIndex) {
          element.below[value] = true;
        }
        if (i < highIndex) {
          element.above[value] = true;
        }
      }
      return value;
    }
    return null;
  };
  
  function createRecordTableRows(record, tune) {
    var drawFns = [];
    
    function rowCommon(row, freq) {
      row.classList.add('freqlist-item');
      row.classList.add('freqlist-item-' + record.type);  // freqlist-item-channel, freqlist-item-band
      if (!(record.mode in modeTable)) {
        row.classList.add('freqlist-item-unsupported');
      }
      if (record.upperFreq !== freq) {
        row.classList.add('freqlist-item-band-start');
      }
      if (record.lowerFreq !== freq) {
        row.classList.add('freqlist-item-band-end');
      }
      row.addEventListener('click', function(event) {
        tune({
          record: record,
          alwaysCreate: alwaysCreateReceiverFromEvent(event)
        });
        event.stopPropagation();
      }, false);
      
      // row content
      function cell(className, textFn) {
        var td = row.appendChild(document.createElement('td'));
        td.className = 'freqlist-cell-' + className;
        drawFns.push(function() {
          td.textContent = textFn();
        });
      }
      switch (record.type) {
        case 'channel':
        case 'band':
          cell('freq', function () {
            return formatFreqMHz(freq);
          });
          cell('mode', function () { return record.mode === 'ignore' ? '' : record.mode;  });
          cell('label', function () { return record.label; });
          drawFns.push(function () {
            firstRow.title = record.notes;
          });
          break;
        default:
          break;
      }
    }
    
    var firstRow = document.createElement('tr');
    rowCommon(firstRow, record.lowerFreq);
    var secondRow;
    if (record.upperFreq != record.lowerFreq) {
      secondRow = document.createElement('tr');
      rowCommon(secondRow, record.upperFreq);
    }
    // TODO: The fact that we decide on 1 or 2 rows based on the data makes the drawFns strategy invalid and we need to recreate things on record change. Or, we could construct a blank row...
    
    return {
      elements: secondRow ? [firstRow, secondRow] : [firstRow],
      drawNow: function () {
        drawFns.forEach(function (f) { f(); });
      }
    };
  }
  
  function FreqScale(config) {
    var tunerSource = config.target;
    var dataSource = config.freqDB.groupSameFreq();
    var view = config.view;
    var tune = config.actions.tune;
    var menuContext = config.context;

    // cache query
    var query, qLower = NaN, qUpper = NaN;

    var labelWidth = 60; // TODO actually measure styled text
    
    // view parameters closed over
    var lower, upper;
    
    
    var stacker = new IntervalStacker();
    function pickY(lowerFreq, upperFreq) {
      return (stacker.claim(lowerFreq, upperFreq) + 1) * 1.15;
    }

    var outer = this.element = document.createElement("div");
    outer.className = "freqscale";
    var numbers = outer.appendChild(document.createElement('div'));
    numbers.className = 'freqscale-numbers';
    var labels = outer.appendChild(document.createElement('div'));
    labels.className = 'freqscale-labels';
    
    outer.style.position = 'absolute';
    function doLayout() {
      // TODO: This is shared knowledge between this, WaterfallPlot, and ReceiverMarks. Should instead be managed by SpectrumView (since it already handles freq coordinates), in the form "get Y position of minLevel".
      outer.style.bottom = (config.clientState.spectrum_split.depend(doLayout) * 100).toFixed(2) + '%';
    }
    doLayout.scheduler = config.scheduler;
    doLayout();
    
    // label maker fns
    function addChannel(record) {
      var isGroup = record.type === 'group';
      var channel = isGroup ? record.grouped[0] : record;
      var freq = record.freq;
      var mode = channel.mode;
      var el = document.createElement('button');
      el.className = 'freqscale-channel';
      el.textContent =
        (isGroup ? '(' + record.grouped.length + ') ' : '')
        + (channel.label || channel.mode);
      el.addEventListener('click', function(event) {
        if (isGroup) {
          var isAllSameMode = record.grouped.every(function (groupRecord) {
            return groupRecord.mode == channel.mode;
          });
          if (isAllSameMode) {
            tune({
              record: channel,
              alwaysCreate: alwaysCreateReceiverFromEvent(event)
            });
          }
          // TODO: It would make sense to, once the user picks a record from the group, to show that record as the arbitrary-choice-of-label in this widget.
          var menu = new Menu(menuContext, BareFreqList, record.grouped);
          menu.openAt(el);
        } else {
          tune({
            record: channel,
            alwaysCreate: alwaysCreateReceiverFromEvent(event)
          });
        }
      }, false);
      el.my_update = function() {
        el.style.left = view.freqToCSSLeft(freq);
        // TODO: the 2 is a fudge factor
        el.style.bottom = (pickY(freq, freq) - 2) + 'em';
      };
      return el;
    }
    function addBand(record) {
      var el = document.createElement('span');
      el.className = 'freqscale-band';
      el.textContent = record.label || record.mode;
      el.my_update = function() {
        var labelLower = Math.max(record.lowerFreq, lower);
        var labelUpper = Math.min(record.upperFreq, upper);
        el.style.left = view.freqToCSSLeft(labelLower);
        el.style.width = view.freqToCSSLength(labelUpper - labelLower);
        el.style.bottom = pickY(record.lowerFreq, record.upperFreq) + 'em';
      }
      return el;
    }

    var numberCache = new VisibleItemCache(numbers, function (freq) {
      var label = document.createElement('span');
      label.className = 'freqscale-number';
      label.textContent = formatFreqExact(freq);
      label.my_update = function() {
        label.style.left = view.freqToCSSLeft(freq);
      }
      return label;
    });
    var labelCache = new VisibleItemCache(labels, function makeLabel(record) {
      switch (record.type) {
        case 'group':
        case 'channel':
          return addChannel(record);
        case 'band':
          return addBand(record);
      }
    });
    
    var scale_coarse = 10;
    var scale_fine1 = 4;
    var scale_fine2 = 2;
    
    var draw = config.boundedFn(function drawImpl() {
      var centerFreq = tunerSource.depend(draw);
      view.n.listen(draw);
      
      lower = view.leftFreq();
      upper = view.rightFreq();
      
      // TODO: identical to waterfall's use, refactor
      outer.style.marginLeft = view.freqToCSSLeft(lower);
      outer.style.width = view.freqToCSSLength(upper - lower);
      
      // Minimum spacing between labels in Hz
      var MinHzPerLabel = (upper - lower) * labelWidth / view.getTotalPixelWidth();
      
      var step = 1;
      // Widen label spacing exponentially until they have sufficient separation.
      // We could try to calculate the step using logarithms, but floating-point error would be tiresome.
      while (isFinite(step) && step < MinHzPerLabel) {
        step *= scale_coarse;
      }
      // Try to narrow the spacing using two possible fine scales.
      if (step / scale_fine1 > MinHzPerLabel) {
        step /= scale_fine1;
      } else if (step / scale_fine2 > MinHzPerLabel) {
        step /= scale_fine2;
      }
      
      for (var i = lower - mod(lower, step), sanity = 1000;
           sanity > 0 && i <= upper;
           sanity--, i += step) {
        numberCache.add(i).my_update();
      }
      numberCache.flush();
      
      stacker.clear();
      if (!(lower === qLower && upper === qUpper)) {
        query = dataSource.inBand(lower, upper);
        qLower = lower;
        qUpper = upper;
      }
      query.n.listen(draw);
      query.forEach(function (record) {
        var label = labelCache.add(record);
        if (label) label.my_update();
      });
      labelCache.flush();
    });
    draw.scheduler = config.scheduler;
    draw();
  }
  widgets.FreqScale = FreqScale;
  
  function FreqList(config) {
    var radioCell = config.radioCell;
    var scheduler = config.scheduler;
    var tune = config.actions.tune;
    var configKey = 'filterString';
    var dataSource = config.freqDB;  // TODO optionally filter to available receive hardware
    
    var container = this.element = document.createElement('div');
    container.classList.add('panel');
    
    var filterBox = container.appendChild(document.createElement('input'));
    filterBox.type = 'search';
    filterBox.placeholder = 'Filter channels...';
    filterBox.value = (config.storage && config.storage.getItem(configKey)) || '';
    filterBox.addEventListener('input', refilter, false);
    
    var listOuter = container.appendChild(document.createElement('div'))
    listOuter.className = 'freqlist-box';
    var list = listOuter.appendChild(document.createElement('table'))
      .appendChild(document.createElement('tbody'));
    
    var receiveAllButton = container.appendChild(document.createElement('button'));
    receiveAllButton.textContent = 'Receive all in search';
    receiveAllButton.addEventListener('click', function (event) {
      var receivers = radioCell.get().receivers.get();
      for (var key in receivers) {
        receivers.delete(key);
      }
      currentFilter.forEach(function(p) {
        tune({
          freq: p.freq,
          mode: p.mode,
          alwaysCreate: true
        });
      });
    }, false);
    
    var recordElAndDrawTable = new WeakMap();
    var redrawHooks = new WeakMap();
    
    function getElementsForRecord(record) {
      var info = recordElAndDrawTable.get(record);
      if (info) {
        redrawHooks.get(info)();
        return info.elements;
      }
      
      info = createRecordTableRows(record, tune);
      var elements = info.element;
      recordElAndDrawTable.set(record, info);
      
      function draw() {
        info.drawNow();
        if (record.offsetWidth > 0) { // rough 'is in DOM tree' test
          record.n.listen(draw);
        }
      }
      draw.scheduler = scheduler;
      redrawHooks.set(info, draw);
      draw();
      
      return info.elements;
    }
    
    var currentFilter = dataSource;
    var lastFilterText = null;
    function refilter() {
      if (lastFilterText !== filterBox.value) {
        lastFilterText = filterBox.value;
        if (config.storage) config.storage.setItem(configKey, lastFilterText);
        currentFilter = dataSource.string(lastFilterText);
        draw();
      }
    }
    
    var draw = config.boundedFn(function drawImpl() {
      //console.group('draw');
      //console.log(currentFilter.getAll().map(function (r) { return r.label; }));
      currentFilter.n.listen(draw);
      //console.groupEnd();
      list.textContent = '';  // clear
      var deferredSecondHalves = [];
      currentFilter.forEach(function (record) {
        // the >= rather than = comparison is critical to get abutting band edges in the ending-then-starting order
        while (deferredSecondHalves.length && record.lowerFreq >= deferredSecondHalves[0].freq) {
          list.appendChild(deferredSecondHalves.shift().el);
        }
        var elements = getElementsForRecord(record);
        list.appendChild(elements[0]);
        if (elements[1]) {
          // TODO: Use an insert algorithm instead of sorting the whole
          deferredSecondHalves.push({freq: record.upperFreq, el: elements[1]});
          deferredSecondHalves.sort(function (a, b) { return a.freq - b.freq });
        }
      });
      // sanity check
      var count = currentFilter.getAll().length;
      receiveAllButton.disabled = !(count > 0 && count <= 10);
    });
    draw.scheduler = scheduler;

    refilter();
  }
  widgets.FreqList = FreqList;

  // Like FreqList, but with no controls, no live updating, and taking an array rather than the freqDB. For FreqScale disambiguation menus.
  function BareFreqList(config) {
    var records = config.target.get();
    var scheduler = config.scheduler;
    var actionCompleted = config.context.actionCompleted;  // TODO should have direct access not through context
    var tune = config.actions.tune;  // TODO: Wrap with close-containing-menu
    function tuneWrapper(options) {
      tune(options);
      actionCompleted();
    }
    
    var container = this.element = document.createElement('div');
    container.classList.add('panel');
    
    var listOuter = container.appendChild(document.createElement('div'))
    listOuter.className = 'freqlist-box';
    var list = listOuter.appendChild(document.createElement('table'))
      .appendChild(document.createElement('tbody'));
    
    records.forEach(function (record) {
      var r = createRecordTableRows(record, tuneWrapper);
      // This incomplete implementation of createRecordTableRows' expectations is sufficient because we never see a band here. TODO: Consider refactoring so we don't do this and instead BareFreqList is part of the implementation of FreqList.
      list.appendChild(r.elements[0]);
      r.drawNow();
    });
  }
  
  var NO_RECORD = {};
  function RecordCellPropCell(recordCell, prop) {
    this.get = function () {
      var record = recordCell.get();
      return record ? record[prop] : NO_RECORD;
    };
    this.set = function (value) {
      recordCell.get()[prop] = value;
    };
    this.isWritable = function () {
      return recordCell.get().writable;
    };
    this.n = {
      listen: function (l) {
        var now = recordCell.get();
        if (now) now.n.listen(l);
        recordCell.n.listen(l);
      }
    };
  }
  RecordCellPropCell.prototype = Object.create(Cell.prototype, {constructor: {value: RecordCellPropCell}});
  
  var dbModeTable = Object.create(null);
  dbModeTable[''] = '—';
  for (var key in modeTable) {
    dbModeTable[key] = modeTable[key].label;
  }
  
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
      var draw = config.boundedFn(function drawImpl() {
        var now = cell.depend(draw);
        if (now === NO_RECORD) {
          field.disabled = true;
        } else {
          field.disabled = !cell.isWritable();
          if (field.value !== now) field.value = now;
        }
      });
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
    menu(cell('mode'), 'Mode', dbModeTable);
    input(cell('location'), 'Location').readOnly = true;  // can't edit yet
    input(cell('label'), 'Label');
    textarea(cell('notes'));
  }
  widgets.RecordDetails = RecordDetails;
  
  function DatabasePickerWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      var list = getAppend(); // TODO should be a <ul> with styling
      for (var key in block) {
        var match = /^enabled_(.*)$/.exec(key);
        if (match) {
          var label = list.appendChild(document.createElement('div')).appendChild(document.createElement('label'));
          var input = label.appendChild(document.createElement('input'));
          input.type = 'checkbox';
          label.appendChild(document.createTextNode(match[1]))
          createWidgetExt(config.context, Toggle, input, block[key]);
          ignore(key);
        }
      }
    });
  }
  widgets['interface:shinysdr.client.database.DatabasePicker'] = DatabasePickerWidget;
  
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
  widgets.CommandButton = CommandButton;
  
  // Silly single-purpose widget 'till we figure out more where the UI is going
  // TODO: Inherit from CommandButton
  function SaveButton(config) {
    var receiver = config.target.get();
    var selectedRecord = config.actions.selectedRecord;
    var panel = this.element = config.element;
    panel.classList.add('panel');
    
    var button = panel.querySelector('button');
    if (!button) {
      button = panel.appendChild(document.createElement('button'));
      button.textContent = '+ Save to database';
    }
    button.disabled = false;
    button.onclick = function (event) {
      var record = {
        type: 'channel',
        freq: receiver.rec_freq.get(),
        mode: receiver.mode.get(),
        label: 'untitled'
      };
      selectedRecord.set(config.writableDB.add(record));
    };
  }
  widgets.SaveButton = SaveButton;
  
  // TODO: Needs to be more than just a BlockSet: eventually a table with grouped headings and sorting, maybe
  var TelemetryStoreWidget = BlockSet(PickBlock, BlockSetInFrameEntryBuilder(''));
  widgets['interface:shinysdr.telemetry.ITelemetryStore'] = TelemetryStoreWidget;
  
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
      update(value);
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
        return function updateGeneric(value) {
          node.textContent = value;
        };
      });
  }
  widgets.Generic = Generic;
  
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
        return function updateGeneric(value) {
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
  widgets.Banner = Banner;
  
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
        input.addEventListener('input', function(event) {
          target.set(input.value);
        }, false);
        
        return function updateTextBox(value) {
          input.value = value;
        };
      });
  }
  widgets.TextBox = TextBox;
  
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
  widgets.Number = NumberWidget;
  
  function SmallKnob(config) {
    SimpleElementWidget.call(this, config, 'INPUT',
      function buildPanelForSmallKnob(container) {
        container.classList.add('widget-SmallKnob-panel');
        
        if (container.hasAttribute('title')) {
          var labelEl = container.appendChild(document.createElement('span'));
          labelEl.classList.add('widget-SmallKnob-label');
          labelEl.appendChild(document.createTextNode(container.getAttribute('title')));
          container.removeAttribute('title');
        }
        
        var input = container.appendChild(document.createElement('input'));
        input.type = 'number';
        input.step = 'any';
        
        return input;
      },
      function initSmallKnob(input, target) {
        var type = target.type;
        if (type instanceof values.Range) {
          input.min = getT(type.getMin());
          input.max = getT(type.getMax());
          input.step = (type.integer && !type.logarithmic) ? 1 : 'any';
        }

        input.addEventListener('input', function(event) {
          if (type instanceof values.Range) {
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
  widgets.SmallKnob = SmallKnob;
  
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
        if (type instanceof values.Range) {
          slider.min = getT(type.getMin());
          slider.max = getT(type.getMax());
          slider.step = (type.integer) ? 1 : 'any';
          if (type.integer) {
            format = function(n) { return '' + n; };
          }
        }

        function listener(event) {
          if (type instanceof values.Range) {
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
          slider.disabled = false;
          slider.valueAsNumber = sValue;
          if (text) {
            text.data = format(value);
          }
        };
      });
  }
  var LinSlider = widgets.LinSlider = function(c) { return new Slider(c,
    function (v) { return v; },
    function (v) { return v; }); };
  var LogSlider = widgets.LogSlider = function(c) { return new Slider(c,
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
        if (type instanceof values.Range) {
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
  widgets.Meter = Meter;
  
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
        checkbox.addEventListener('change', function(event) {
          target.set(checkbox.checked);
        }, false);
        return function updateToggle(value) {
          checkbox.checked = value;
        };
      });
  }
  widgets.Toggle = Toggle;
  
  // Create children of 'container' according to target's enum type, unless appropriate children already exist.
  function initEnumElements(container, selector, target, createElement) {
    var type = target.type;
    if (!(type instanceof values.Enum)) type = null;
    
    var seen = Object.create(null);
    Array.prototype.forEach.call(container.querySelectorAll(selector), function (element) {
      var value = element.value;
      seen[value] = true;
      if (type) {
        element.disabled = !(element.value in type.values);
      }
    });

    if (type) {
      var array = Object.keys(target.type.values || {});
      array.sort();
      array.forEach(function (value) {
        if (seen[value]) return;
        var element = createElement(type.values[value]);
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
        initEnumElements(select, 'option', target, function createOption(name) {
          var option = select.appendChild(document.createElement('option'));
          option.appendChild(document.createTextNode(name));
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
  widgets.Select = Select;
  
  function Radio(config) {
    var target = config.target;
    var container = this.element = config.element;
    container.classList.add('panel');

    initEnumElements(container, 'input[type=radio]', target, function createRadio(name) {
      var label = container.appendChild(document.createElement('label'));
      var rb = label.appendChild(document.createElement('input'));
      var textEl = label.appendChild(document.createElement('span'));  // styling hook
      textEl.textContent = name;
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
  widgets.Radio = Radio;
  
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
  widgets.TrackWidget = TrackWidget;
  
  // TODO: This is currently used by plugins to extend the widget namespace. Create a non-single-namespace widget type lookup and then freeze this.
  return widgets;
});
