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
define(['values', 'events', 'widget', 'widgets', 'network', 'database'], function (values, events, widget, widgets, network, database) {
  'use strict';

  var ConstantCell = values.ConstantCell;
  var StorageCell = values.StorageCell;
  var StorageNamespace = values.StorageNamespace;
  var makeBlock = values.makeBlock;
  
  var binCount = 512;
  var sampleRate = 1e6;
  var minLevel = -130;
  var maxLevel = -20;
  
  var scheduler = new events.Scheduler();

  // TODO duplicated code w/ regular shinysdr
  var clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  function cc(key, type, value) {
    return new StorageCell(clientStateStorage, type, value, key);
  }
  var clientState = makeBlock({
    opengl: cc('opengl', Boolean, true),
    opengl_float: cc('opengl_float', Boolean, true),
    spectrum_split: cc('spectrum_split', new values.Range([[0, 1]], false, false), 0.5),
    spectrum_average: cc('spectrum_average', new values.Range([[0.05, 1]], true, false), 0.25)
  });
  
  var fftcell = new network.BulkDataCell('<dummy spectrum>', new values.BulkDataType('dff', 'b'));
  var root = new ConstantCell(values.block, makeBlock({
    unpaused: cc('_test_unpaused', Boolean, true),
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
      bytearray[i] = Math.exp(i / binCount * 14) % (maxLevel - minLevel) - 128;
    }
    for (; i < binCount; i++) {
      var bit = Math.floor((i - binCount/2) / binCount * 32);
      bytearray[i] = (frameCount >> bit) & 1 ? -30 : -120;
    }
    
    fftcell._update(buffer);
  }
  
  function loop() {
    if (root.get().unpaused.get()) updateFFT();
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  
  widget.createWidgets(root, context, document);
});