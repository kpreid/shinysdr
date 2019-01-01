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

requirejs.config({
  baseUrl: '../client/'
});
define([
  'audio/analyser',
  'audio/client-source',
  'audio/util',
  'coordination', 
  'events', 
  'values', 
  'widget', 
  'widgets',
], (
  import_audio_analyser,
  import_audio_client_source,
  import_audio_util,
  import_coordination,
  import_events,
  import_values,
  import_widget,
  widgets
) => {
  const {
    AudioAnalyserAdapter,
  } = import_audio_analyser;
  const {
    AudioSourceSelector,
  } = import_audio_client_source;
  const {
    audioContextAutoplayHelper,
  } = import_audio_util;
  const {
    ClientStateObject,
  } = import_coordination;
  const {
    Scheduler,
  } = import_events;
  const {
    ConstantCell,
    StorageNamespace,
  } = import_values;
  const {
    Context,
    createWidgets,
  } = import_widget;
  
  const scheduler = new Scheduler();
  const audioContext = new AudioContext();
  const storage = sessionStorage;  // TODO persistent and namespaced-from-other-pages
  
  const selector = new AudioSourceSelector(scheduler, audioContext, navigator.mediaDevices,
    new StorageNamespace(storage, 'input-selector.'));
  const adapter = new AudioAnalyserAdapter(scheduler, audioContext);
  adapter.connectFrom(selector.source);
  adapter.paused.set(false);
  
  // kludge: stick extra property on adapter so it gets in the options menu UI.
  // TODO: Replace this by adding flexibility to the UI system.
  adapter.input = new ConstantCell(selector);
  
  const root = new ConstantCell(adapter);
  
  const context = new Context({
    widgets: widgets,
    // Using sessionStorage because we want default settings and because our storage usage doesn't yet distinguish between different pages.
    clientState: new ClientStateObject(sessionStorage, null),
    scheduler: scheduler
  });
  
  createWidgets(root, context, document);
  
  audioContextAutoplayHelper(audioContext);
});
