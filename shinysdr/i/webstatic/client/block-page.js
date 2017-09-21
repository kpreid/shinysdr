// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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
  './events',
  './network',
  './widget',
  './widgets',
], (
  import_events,
  import_network,
  import_widget,
  widgets
) => {
  const {
    Scheduler,
  } = import_events;
  const {
    connect,
  } = import_network;
  const {
    Context,
    createWidgets,
  } = import_widget;

  const exports = {};
  
  function run(stateUrl) {
    const scheduler = new Scheduler();
    
    const context = new Context({
      widgets: widgets,
      scheduler: scheduler
    });
    
    const remoteCell = connect(stateUrl);
    
    remoteCell.n.listen(scheduler.claim(function connected() {
      createWidgets(remoteCell, context, document);
      
      // globals for debugging / interactive programming purposes only
      window.Dcell = remoteCell;
    }));
  }
  exports.run = run;
  
  return Object.freeze(exports);
});