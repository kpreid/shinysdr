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

define(['./basic', './spectrum', '../types', '../values', '../events', '../widget', '../gltools', '../database', '../math', '../menus', '../plugins'], function (widgets_basic, widgets_spectrum, types, values, events, widget, gltools, database, math, menus, plugins) {
  'use strict';
  
  var Banner = widgets_basic.Banner;
  var Block = widgets_basic.Block;
  var Cell = values.Cell;
  var Clock = events.Clock;
  var CommandCell = values.CommandCell;
  var ConstantCell = values.ConstantCell;
  var DerivedCell = values.DerivedCell;
  var Enum = types.Enum;
  var Generic = widgets_basic.Generic;
  var Knob = widgets_basic.Knob;
  var LinSlider = widgets_basic.LinSlider;
  var LocalCell = values.LocalCell;
  var Menu = menus.Menu;
  var Meter = widgets_basic.Meter;
  var Notice = types.Notice;
  var NumberWidget = widgets_basic.Number;
  var PickWidget = widgets_basic.PickWidget;
  var Radio = widgets_basic.Radio;
  var Range = types.Range;
  var Select = widgets_basic.Select;
  var SingleQuad = gltools.SingleQuad;
  var SmallKnob = widgets_basic.SmallKnob;
  var Timestamp = types.Timestamp;
  var Toggle = widgets_basic.Toggle;
  var Track = types.Track;
  var Union = database.Union;
  var addLifecycleListener = widget.addLifecycleListener;
  var alwaysCreateReceiverFromEvent = widget.alwaysCreateReceiverFromEvent;
  var createWidgetExt = widget.createWidgetExt;
  var emptyDatabase = database.empty;
  var formatFreqMHz = math.formatFreqMHz;
  var isSingleValued = types.isSingleValued;
  var modeTable = plugins.getModeTable();

  var exports = Object.create(null);

  // Suppresses all visibility of null objects
  function NullWidget(config) {
    Block.call(this, config, function () {}, true);
  }
  exports['interface:shinysdr.values.INull'] = NullWidget;
  
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
  exports.Top = Top;
  
  function BlockSet(widgetCtor, buildEntry) {
    return function TypeSetInst(config) {
      // We do not inherit from Block, because we don't want the rebuild-on-reshape behavior (so we can do something more efficient) and we don't need the rest of it.
      var block = config.target.depend(config.rebuildMe);
      var idPrefix = config.idPrefix;
      var childContainer = this.element = config.element;
      
      // TODO: We ought to display these in some way.
      config.element.removeAttribute('title');
      
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
  exports.BlockSet = BlockSet;
  
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
  
  var DeviceSet = exports.DeviceSet = BlockSet(Device, BlockSetInFrameEntryBuilder('Device'));
  var ReceiverSet = exports.ReceiverSet = BlockSet(Receiver, BlockSetInFrameEntryBuilder('Receiver'));
  var AccessorySet = exports.AccessorySet = BlockSet(PickWidget, BlockSetInFrameEntryBuilder('Accessory'));
  exports.WindowBlocks = BlockSet(PickWidget, windowEntryBuilder);
  
  // Widget for a device
  function Device(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      var freqCell = block.freq;
      if (!isSingleValued(freqCell.type)) {
        addWidget('freq', Knob, 'Center frequency');
      }
      addWidget('rx_driver', PickWidget);
      addWidget('tx_driver', PickWidget);
      addWidget('components', ComponentSet);
    });
  }
  exports['interface:shinysdr.devices.IDevice'] = Device;
  var ComponentSet = BlockSet(PickWidget, blockSetNoHeader);
  
  // Widget for a RX driver block -- TODO break this stuff up
  function RXDriverWidget(config) {
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
          let singleGainSliderWidgetEl = singleGainPanel.appendChild(document.createElement('div'));
          singleGainSliderWidgetEl.title = '';
          createWidgetExt(config.context, LinSlider, singleGainSliderWidgetEl, block.gain);
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
      
      ignore('output_type');
    }, true);
  }
  exports['interface:shinysdr.devices.IRXDriver'] = RXDriverWidget;
  
  function TXDriverWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('input_type');  // TODO this should be handled by server-defined metadata
    }, true);
  }
  exports['interface:shinysdr.devices.ITXDriver'] = TXDriverWidget;
  
  // Widget for a receiver block
  function Receiver(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
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
      
      var outOfRangeNotice = new DerivedCell(Notice, config.scheduler, function(dirty) {
        return block.is_valid.depend(dirty)
          ? ''
          : 'Outside of device bandwidth; disabled.';
      });
      addWidget(outOfRangeNotice, Banner);
      ignore('is_valid');
      
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
  exports.Receiver = Receiver;
  
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
      addWidget('angle', config.context.widgets.VOR$Angle, '');
      ignore('zero_point');
    }, true);
  }
  exports['interface:shinysdr.interfaces.IDemodulator'] = Demodulator;
  
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
  exports.SaveButton = SaveButton;
  
  // TODO: Needs to be more than just a BlockSet: eventually a table with grouped headings and sorting, maybe
  var TelemetryStoreWidget = BlockSet(PickWidget, BlockSetInFrameEntryBuilder(''));
  exports['interface:shinysdr.telemetry.ITelemetryStore'] = TelemetryStoreWidget;
  
  return Object.freeze(exports);
});
