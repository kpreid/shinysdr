// Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

// TODO: remove network module depenency
requirejs.config({
  baseUrl: '/client/'
});
define(['types', 'values', 'events', 'widget', 'widgets', 'network', 'database', 'coordination'], function (types, values, events, widget, widgets, network, database, coordination) {
  'use strict';

  const ClientStateObject = coordination.ClientStateObject;
  const ConstantCell = values.ConstantCell;
  const StorageCell = values.StorageCell;
  const StorageNamespace = values.StorageNamespace;
  const makeBlock = values.makeBlock;
  const {
    booleanT,
    numberT,
  } = types;
  
  const binCount = 4096;
  const sampleRate = 1e6;
  const minLevel = -130;
  const maxLevel = -20;
  
  const scheduler = new events.Scheduler();

  const clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  const clientState = new ClientStateObject(clientStateStorage, null);
  
  const fftcell = new network.BulkDataCell('<dummy spectrum>', [{freq: 0, rate: 0}, []], {naming: {}, value_type: new types.BulkDataT('dff', 'b')});
  const root = new ConstantCell(types.blockT, makeBlock({
    unpaused: new StorageCell(clientStateStorage, booleanT, true, '_test_unpaused'),
    source: new ConstantCell(types.blockT, makeBlock({
      freq: new ConstantCell(numberT, 0),
    })),
    receivers: new ConstantCell(types.blockT, makeBlock({})),
    client: new ConstantCell(types.blockT, clientState),
    //input_rate: new ConstantCell(numberT, sampleRate),
    monitor: new ConstantCell(types.blockT, makeBlock({
      fft: fftcell,
      freq_resolution: new ConstantCell(numberT, binCount),
      signal_type: new ConstantCell(types.anyT, {kind: 'IQ', sample_rate: sampleRate})
    }))
  }));
  
  var context = new widget.Context({
    widgets: widgets,
    radioCell: root,  // TODO: 'radio' name is bogus
    clientState: clientState,
    spectrumView: null,
    freqDB: new database.Union(),
    scheduler: scheduler
  });
  
  var buffer = new ArrayBuffer(4+8+4+4 + binCount * 1);
  var dv = new DataView(buffer);
  dv.setFloat64(4, 0, true); // freq
  dv.setFloat32(4+8, sampleRate, true);
  dv.setFloat32(4+8+4, -128 - minLevel, true); // offset
  var bytearray = new Int8Array(buffer, 4+8+4+4, binCount);
  
  var frameCount = 0;
  function updateFFT() {
    frameCount++;
    
    var i = 0;
    for (; i < binCount/2; i++) {
      bytearray[i] = Math.exp(i / binCount * 28) % ((maxLevel - minLevel) * 0.3) - 128;
    }
    for (; i < binCount; i++) {
      var bit = Math.floor((i - binCount/2) / binCount * 32);
      bytearray[i] = (frameCount >> bit) & 1 ? -30 : -120;
    }
    
    bytearray[2] = -70;

    bytearray[8] = -80;
    bytearray[9] = -70;
    bytearray[10] = -80;
    
    fftcell._update(buffer);
  }
  
  function loop() {
    if (root.get().unpaused.get()) updateFFT();
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  
  widget.createWidgets(root, context, document);
});