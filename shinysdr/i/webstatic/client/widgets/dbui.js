// Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
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
  './basic',
  '../domtools',
  '../math',
  '../plugins',
  '../types',
  '../values',
  '../widget',
], (
  import_widgets_basic,
  import_domtools,
  import_math,
  import_plugins,
  import_types,
  import_values,
  import_widget
) => {
  const {
    Block,
    Toggle,
  } = import_widgets_basic;
  const {
    isVisibleInLayout,
  } = import_domtools;
  const {
    formatFreqMHz,
  } = import_math;
  const {
    getModeTable,
  } = import_plugins;
  const {
    anyT,
  } = import_types;
  const {
    Cell,
  } = import_values;
  const {
    alwaysCreateReceiverFromEvent,
    createWidgetExt,
  } = import_widget;
  
  const exports = {};
  
  const modeTable = getModeTable();
  
  function FreqList(config) {
    const radioCell = config.radioCell;
    const scheduler = config.scheduler;
    const tune = config.actions.tune;
    const configKey = 'filterString';
    const dataSource = config.freqDB;  // TODO optionally filter to available receive hardware
    
    const container = this.element = document.createElement('div');
    container.classList.add('panel');
    
    const filterBox = container.appendChild(document.createElement('input'));
    filterBox.type = 'search';
    filterBox.placeholder = 'Filter channels...';
    filterBox.value = (config.storage && config.storage.getItem(configKey)) || '';
    filterBox.addEventListener('input', refilter, false);
    
    const listOuter = container.appendChild(document.createElement('div'));
    listOuter.className = 'freqlist-box';
    const list = listOuter.appendChild(document.createElement('table'))
      .appendChild(document.createElement('tbody'));
    
    const receiveAllButton = container.appendChild(document.createElement('button'));
    receiveAllButton.textContent = 'Receive all in search';
    receiveAllButton.addEventListener('click', function (event) {
      const receivers = radioCell.get().receivers.get();
      for (const key in receivers) {
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
    
    const recordElAndDrawTable = new WeakMap();
    const redrawHooks = new WeakMap();
    
    function getElementsForRecord(record) {
      const existingInfo = recordElAndDrawTable.get(record);
      if (existingInfo) {
        redrawHooks.get(existingInfo)();
        return existingInfo.elements;
      }
      
      const info = createRecordTableRows(record, tune);
      recordElAndDrawTable.set(record, info);
      
      function draw() {
        info.drawNow();
        if (isVisibleInLayout(info.elements[0])) { // rough 'is in DOM tree' test
          record.n.listen(draw);
        }
      }
      scheduler.claim(draw);
      redrawHooks.set(info, draw);
      draw();
      
      return info.elements;
    }
    
    let currentFilter = dataSource;
    let lastFilterText = null;
    function refilter() {
      if (lastFilterText !== filterBox.value) {
        lastFilterText = filterBox.value;
        if (config.storage) config.storage.setItem(configKey, lastFilterText);
        currentFilter = dataSource.string(lastFilterText);
        draw();
      }
    }
    
    function draw() {
      //console.group('draw');
      //console.log(currentFilter.getAll().map(function (r) { return r.label; }));
      currentFilter.n.listen(draw);
      //console.groupEnd();
      list.textContent = '';  // clear
      const deferredSecondHalves = [];
      currentFilter.forEach(function (record) {
        // the >= rather than = comparison is critical to get abutting band edges in the ending-then-starting order
        while (deferredSecondHalves.length && record.lowerFreq >= deferredSecondHalves[0].freq) {
          list.appendChild(deferredSecondHalves.shift().el);
        }
        const elements = getElementsForRecord(record);
        list.appendChild(elements[0]);
        if (elements[1]) {
          // TODO: Use an insert algorithm instead of sorting the whole
          deferredSecondHalves.push({freq: record.upperFreq, el: elements[1]});
          deferredSecondHalves.sort((a, b) => a.freq - b.freq);
        }
      });
      // sanity check
      var count = currentFilter.getAll().length;
      receiveAllButton.disabled = !(count > 0 && count <= 10);
    }
    config.scheduler.startNow(draw);
    
    refilter();
  }
  exports.FreqList = FreqList;

  // Like FreqList, but with no controls, no live updating, and taking an array rather than the freqDB. For FreqScale disambiguation menus.
  function BareFreqList(config) {
    const records = config.target.get();
    const actionCompleted = config.context.actionCompleted;  // TODO should have direct access not through context
    const tune = config.actions.tune;  // TODO: Wrap with close-containing-menu
    function tuneWrapper(options) {
      tune(options);
      actionCompleted();
    }
    
    var container = this.element = document.createElement('div');
    container.classList.add('panel');
    
    var listOuter = container.appendChild(document.createElement('div'));
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
      row.addEventListener('mousedown', event => {
        event.preventDefault();  // prevent shift-click-select (shift is used by alwaysCreateReceiverFromEvent)
      }, false);
      row.addEventListener('click', event => {
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
    if (record.upperFreq !== record.lowerFreq) {
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
  
  const NO_RECORD = {};
  class RecordCellPropCell extends Cell {
    constructor(recordCell, prop) {
      super(anyT);  // TODO: more specific type/metadata
      this.get = function () {
        const record = recordCell.get();
        return record ? record[prop] : NO_RECORD;
      };
      this.set = function (value) {
        recordCell.get()[prop] = value;
      };
      this.isWritable = function () {  // TODO: this is wrong, isWritable does not otherwise exist on the JS side (but something like it should)
        return recordCell.get().writable;
      };
      this.n = {
        listen: function (l) {
          const now = recordCell.get();
          if (now) now.n.listen(l);
          recordCell.n.listen(l);
        }
      };
    }
  }
  
  const dbModeTable = Object.create(null);
  dbModeTable[''] = '—';
  for (const key in modeTable) {
    dbModeTable[key] = modeTable[key].info_enum_row.label;
  }
  Object.freeze(dbModeTable);
  
  function RecordDetails(config) {
    var recordCell = config.target;
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
      config.scheduler.startNow(function draw() {
        var now = cell.depend(draw);
        if (now === NO_RECORD) {
          field.disabled = true;
        } else {
          field.disabled = !cell.isWritable();
          if (field.value !== now) field.value = now;
        }
      });
      field.addEventListener('change', event => {
        if (field.value !== cell.get()) {
          cell.set(field.value);
        }
      });
    }
    function input(cell, name) {
      var field = document.createElement('input');
      formFieldHooks(field, cell);
      return labeled(name, field);
    }
    function menu(cell, name, values) {
      var field = document.createElement('select');
      for (const key in values) {
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
      for (const key in block) {
        var match = /^enabled_(.*)$/.exec(key);
        if (match) {
          const label = list.appendChild(document.createElement('div'))
              .appendChild(document.createElement('label'));
          const input = label.appendChild(document.createElement('input'));
          input.type = 'checkbox';
          label.appendChild(document.createTextNode(match[1]));
          createWidgetExt(config.context, Toggle, input, block[key]);
          ignore(key);
        }
      }
    });
  }
  exports['interface:shinysdr.client.database.DatabasePicker'] = DatabasePickerWidget;
  
  return Object.freeze(exports);
});
