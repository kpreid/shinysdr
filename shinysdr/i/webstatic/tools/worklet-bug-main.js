// Copyright 2018 Kevin Reid <kpreid@switchb.org>
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

requirejs.config({
  baseUrl: '../client/'
});
define([
  'audio/ws-stream',
  'coordination', 
  'events', 
  'values', 
  'widget', 
  'widgets',
], (
  import_audio_ws_stream,
  import_coordination,
  import_events,
  import_values,
  import_widget,
  widgets
) => {
  const {
    connectAudio,
  } = import_audio_ws_stream;
  const {
    ClientStateObject,
  } = import_coordination;
  const {
    Scheduler,
  } = import_events;
  const {
    ConstantCell,
  } = import_values;
  const {
    Context,
    createWidgets,
  } = import_widget;
  
  const scheduler = new Scheduler();
  const storage = sessionStorage;  // TODO persistent and namespaced-from-other-pages
  
  const context = new Context({
    widgets: widgets,
    // Using sessionStorage because we want default settings and because our storage usage doesn't yet distinguish between different pages.
    clientState: new ClientStateObject(sessionStorage, null),
    scheduler: scheduler
  });
  
  function StubAudioWebSocket() {
    this.addEventListener = function(){};
    this.close = function() { console.log('Closed!'); };
    setTimeout(() => {
      this.onmessage({data: JSON.stringify({
        type: 'audio_stream_metadata',
        signal_type: {
          kind: 'MONO',
          sample_rate: 44100,
        }
      })});
      const fakeSamples = new Float32Array(441);
      for (let i = 0; i < fakeSamples.length; i++) {
        fakeSamples[i] = Math.random() * 0.01;
      }
      setInterval(() => {
        setTimeout(() => {
          this.onmessage({data: fakeSamples.buffer});
        }, Math.random() * 200);
      }, 10);
    }, 0);
  }
  
  let info;
  for (let i = 0; i < 1; i++) {
    info = connectAudio(scheduler, 'ws://localhost/dummy', storage, StubAudioWebSocket);
  }
  
  createWidgets(new ConstantCell(info), context, document);
  
  setTimeout(() => {
    window.location.reload();
  }, 250);
});
