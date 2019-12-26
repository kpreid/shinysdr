// Copyright 2014, 2015, 2016 Kevin Reid and the ShinySDR contributors
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

// TODO: remove network module depenency
requirejs.config({
  baseUrl: '/client/'
});
define([
  'coordination',
  'database',
  'events',
  'network',
  'types',
  'values',
  'widget',
  'widgets',
], (
  import_coordination,
  import_database,
  import_events,
  import_network,
  import_types,
  import_values,
  import_widget,
  widgets
) => {
  const {
    ClientStateObject,
  } = import_coordination;
  const {
    empty,
  } = import_database;
  const {
    Scheduler,
  } = import_events;
  const {
    BulkDataCell,
  } = import_network;
  const {
    BulkDataT,
    anyT,
    booleanT,
  } = import_types;
  const {
    ConstantCell,
    StorageCell,
    StorageNamespace,
    makeBlock,
  } = import_values;
  const {
    Context,
    createWidgets,
  } = import_widget;
  
  const centerFreq = 100;
  const binCount = 4096;
  const sampleRate = 1e6;
  const minLevel = -130;
  const maxLevel = -20;
  
  const scheduler = new Scheduler();

  const clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  const clientState = new ClientStateObject(clientStateStorage, null);
  
  const fftcell = new BulkDataCell('<dummy spectrum>', [], {naming: {}, value_type: new BulkDataT('dff', 'b')});
  const root = new ConstantCell(makeBlock({
    unpaused: new StorageCell(clientStateStorage, booleanT, true, '_test_unpaused'),
    source: new ConstantCell(makeBlock({
      freq: new ConstantCell(centerFreq),
    })),
    receivers: new ConstantCell(makeBlock({})),
    client: new ConstantCell(clientState),
    //input_rate: new ConstantCell(sampleRate),
    monitor: new ConstantCell(makeBlock({
      fft: fftcell,
      freq_resolution: new ConstantCell(binCount),
      signal_type: new ConstantCell({kind: 'IQ', sample_rate: sampleRate}, anyT)
    }))
  }));
  
  var context = new Context({
    widgets: widgets,
    radioCell: root,  // TODO: 'radio' name is bogus
    clientState: clientState,
    freqDB: empty,
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
  
  createWidgets(root, context, document);
});