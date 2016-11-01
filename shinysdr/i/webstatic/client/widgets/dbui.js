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
  var PickBlock = widgets_basic.PickBlock;
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
  exports.FreqList = FreqList;

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
  exports.BareFreqList = BareFreqList;
  
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
    dbModeTable[key] = modeTable[key].info_enum_row.label;
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
  exports.RecordDetails = RecordDetails;
  
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
  exports['interface:shinysdr.client.database.DatabasePicker'] = DatabasePickerWidget;
  
  return Object.freeze(exports);
});
