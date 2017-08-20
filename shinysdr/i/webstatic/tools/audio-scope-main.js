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

'use strict';

requirejs.config({
  baseUrl: '../client/'
});
define(['audio', 'coordination', 'events', 'types', 'values', 'widget',
        'widgets', 'widgets/scope'],
       ( audio,   coordination,   events,   types,   values,   widget,
         widgets,   widgets_scope) => {
  const scheduler = new events.Scheduler();
  const audioContext = new AudioContext();
  const storage = sessionStorage;  // TODO persistent and namespaced-from-other-pages
  
  const selector = new audio.UserMediaSelector(scheduler, audioContext, navigator.mediaDevices,
    new values.StorageNamespace(storage, 'input-selector.'));
  const adapter = new audio.AudioScopeAdapter(scheduler, audioContext);
  adapter.connectFrom(selector.source);
  
  const root = new values.ConstantCell(values.makeBlock({
    input: new values.ConstantCell(selector),
    scope: adapter.scope,
    parameters: new values.ConstantCell(
      new widgets_scope.ScopeParameters(
        new values.StorageNamespace(storage, 'scope-parameters.'))),
  }));
  
  const context = new widget.Context({
    widgets: widgets,
    // Using sessionStorage because we want default settings and because our storage usage doesn't yet distinguish between different pages.
    clientState: new coordination.ClientStateObject(sessionStorage, null),
    scheduler: scheduler
  });
  
  widget.createWidgets(root, context, document);
});
