// Copyright 2014 Kevin Reid <kpreid@switchb.org>
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
require.config({
  baseUrl: '/client/'
});
define(['values', 'events', 'widget', 'widgets', 'network', 'database', 'coordination'], function (values, events, widget, widgets, network, database, coordination) {
  'use strict';

  var ClientStateObject = coordination.ClientStateObject;
  var ConstantCell = values.ConstantCell;
  var StorageCell = values.StorageCell;
  var StorageNamespace = values.StorageNamespace;
  var makeBlock = values.makeBlock;
  
  var binCount = 4096;
  var sampleRate = 1e6;
  var minLevel = -130;
  var maxLevel = -20;
  
  var scheduler = new events.Scheduler();

  var clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  var clientState = new ClientStateObject(clientStateStorage, null);
  
  var fftcell = new network.BulkDataCell('<dummy spectrum>', new values.BulkDataType('dff', 'b'));
  var root = new ConstantCell(values.block, makeBlock({
    unpaused: new StorageCell(clientStateStorage, Boolean, true, '_test_unpaused'),
    source: new ConstantCell(values.block, makeBlock({
      freq: new ConstantCell(Number, 0),
    })),
    receivers: new ConstantCell(values.block, makeBlock({})),
    client: new ConstantCell(values.block, clientState),
    //input_rate: new ConstantCell(Number, sampleRate),
    monitor: new ConstantCell(values.block, makeBlock({
      fft: fftcell,
      freq_resolution: new ConstantCell(Number, binCount),
      signal_type: new ConstantCell(values.any, {kind: 'IQ', sample_rate: sampleRate})
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