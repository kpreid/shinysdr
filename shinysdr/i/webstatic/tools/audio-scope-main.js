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
  'coordination',
  'events',
  'values',
  'widget',
  'widgets',
  'widgets/scope',
], (
  import_audio_analyser,
  import_audio_client_source,
  import_coordination,
  import_events,
  import_values,
  import_widget,
  widgets,
  import_widgets_scope
) => {
  const {
    AudioScopeAdapter,
  } = import_audio_analyser;
  const {
    AudioSourceSelector,
  } = import_audio_client_source;
  const {
    ClientStateObject,
  } = import_coordination;
  const {
    Scheduler,
  } = import_events;
  const {
    ConstantCell,
    StorageNamespace,
    makeBlock,
  } = import_values;
  const {
    Context,
    createWidgets,
  } = import_widget;
  const {
    ScopeParameters,
  } = import_widgets_scope;
  
  const scheduler = new Scheduler();
  const audioContext = new AudioContext();
  const storage = sessionStorage;  // TODO persistent and namespaced-from-other-pages
  
  const selector = new AudioSourceSelector(scheduler, audioContext, navigator.mediaDevices,
    new StorageNamespace(storage, 'input-selector.'));
  const adapter = new AudioScopeAdapter(scheduler, audioContext);
  adapter.connectFrom(selector.source);
  
  const root = new ConstantCell(makeBlock({
    input: new ConstantCell(selector),
    scope: adapter.scope,
    parameters: new ConstantCell(
      new ScopeParameters(
        new StorageNamespace(storage, 'scope-parameters.'))),
  }));
  
  const context = new Context({
    widgets: widgets,
    // Using sessionStorage because we want default settings and because our storage usage doesn't yet distinguish between different pages.
    clientState: new ClientStateObject(sessionStorage, null),
    scheduler: scheduler
  });
  
  createWidgets(root, context, document);
});
