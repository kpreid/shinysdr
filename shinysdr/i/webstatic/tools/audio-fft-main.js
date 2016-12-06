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
require.config({
  baseUrl: '/client/'
});
define(['audio', 'types', 'values', 'events', 'widget', 'widgets', 'network', 'database', 'coordination'], function (audio, types, values, events, widget, widgets, network, database, coordination) {
  'use strict';
  
  var AudioAnalyserAdapter = audio.AudioAnalyserAdapter;
  var ClientStateObject = coordination.ClientStateObject;
  var ConstantCell = values.ConstantCell;
  var makeBlock = values.makeBlock;
  
  var scheduler = new events.Scheduler();
  
  var ctx = new AudioContext();
  var sampleRate = ctx.sampleRate;
  
  var adapter = new AudioAnalyserAdapter(scheduler, ctx);
  adapter.paused.set(false);
  
  navigator.mediaDevices.getUserMedia({audio: true}).then(function getUserMediaSuccess(stream) {
    var source = ctx.createMediaStreamSource(stream);
    adapter.connectFrom(source);
  }, function getUserMediaFailure(e) {
    var d = document.createElement('dialog');
    // e is a DOMException
    d.textContent = 'Failed to get audio input: ' + e.name;
    document.body.appendChild(d);
    d.show();
  });
  
  var root = new ConstantCell(types.block, makeBlock({
    monitor: new ConstantCell(types.block, adapter)
  }));
  
  var context = new widget.Context({
    widgets: widgets,
    clientState: new ClientStateObject(sessionStorage, null),  // TODO: using sessionStorage as an approximation for "no storage".
    spectrumView: null,
    freqDB: new database.Union(),
    scheduler: scheduler
  });
  
  widget.createWidgets(root, context, document);
});