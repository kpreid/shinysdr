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

define(['types', 'values', 'events', 'coordination', 'database', 'network', 'map/map-core', 'map/map-layers', 'widget', 'widgets', 'audio', 'window-manager', 'plugins'], function (types, values, events, coordination, database, network, mapCore, mapLayers, widget, widgets, audio, windowManager, plugins) {
  'use strict';
  
  function log(progressAmount, msg) {
    console.log(msg);
    document.getElementById('loading-information-text')
        .appendChild(document.createTextNode('\n' + msg));
    var progress = document.getElementById('loading-information-progress');
    progress.value += (1 - progress.value) * progressAmount;
  }
  
  var any = types.any;
  var block = types.block;
  var ConstantCell = values.ConstantCell;
  var Coordinator = coordination.Coordinator;
  var createWidgetExt = widget.createWidgetExt;
  var LocalCell = values.LocalCell;
  var makeBlock = values.makeBlock;
  var StorageCell = values.StorageCell;
  var StorageNamespace = values.StorageNamespace;
  var Index = values.Index;
  
  var scheduler = new events.Scheduler();

  var clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  
  var writableDB = database.fromURL('wdb/');
  var databasesCell = new LocalCell(any, database.systematics.concat([
    writableDB,  // kludge till we have proper UI for selection of write targets
  ]));
  database.arrayFromCatalog('dbs/', function (dbs) {   // TODO get url from server
    databasesCell.set(databasesCell.get().concat(dbs));
  })
  var databasePicker = new database.DatabasePicker(
    scheduler,
    databasesCell,
    new StorageNamespace(clientStateStorage, 'databases.'));
  var freqDB = databasePicker.getUnion();
  
  // TODO(kpreid): Client state should be more closely associated with the components that use it.
  var clientState = new coordination.ClientStateObject(clientStateStorage, databasePicker);
  var clientBlockCell = new ConstantCell(block, clientState);
  
  function main(stateUrl, audioUrl) {
    log(0.4, 'Loading plugins…');
    plugins.loadCSS();
    requirejs(plugins.getJSModuleIds(), function (plugins) {
      connectRadio(stateUrl, audioUrl);
    }, function (err) {
      log(0, 'Failed to load plugins.\n  ' + err.requireModules + '\n  ' + err.requireType);
      // TODO: There's no reason we can't continue without the plugin. The problem is that right now there's no good way to report the failure, and silent failures are bad.
    });
  }
  
  function connectRadio(stateUrl, audioUrl) {
    log(0.5, 'Connecting to server…');
    var firstConnection = true;
    var firstFailure = true;
    initialStateReady.scheduler = scheduler;
    var remoteCell = network.connect(stateUrl, connectionCallback);
    remoteCell.n.listen(initialStateReady);
    
    var coordinator = new Coordinator(scheduler, freqDB, remoteCell);
    
    var audioState = audio.connectAudio(scheduler, audioUrl);

    function connectionCallback(state) {
      switch (state) {
        case 'connected':
        if (firstConnection) {
          log(0.25, 'Downloading state…');
        }
          break;
        case 'disconnected':
          break;
        case 'failed-connect':
          if (firstConnection && firstFailure) {
            firstFailure = false;
            log(0, 'WebSocket connection failed (retrying).\nIf this persists, you may have a firewall/proxy problem.');
          }
          break;
      }
    }

    function initialStateReady() {
      var radio = remoteCell.depend(initialStateReady);
      
      if (firstConnection) {
        firstConnection = false;
        
        var everything = new ConstantCell(block, makeBlock({
          client: clientBlockCell,
          radio: remoteCell,
          actions: new ConstantCell(block, coordinator.actions),
          audio: new ConstantCell(block, audioState)
        }));
      
        var index = new Index(scheduler, everything);
      
        var context = new widget.Context({
          // TODO all of this should be narrowed down, read-only, replaced with other means to get it to the widgets that need it, etc.
          widgets: widgets,
          radioCell: remoteCell,
          index: index,
          clientState: clientState,
          spectrumView: null,
          freqDB: freqDB,
          writableDB: writableDB,
          scheduler: scheduler,
          coordinator: coordinator
        });
      
        // generic control UI widget tree
        widget.createWidgets(everything, context, document);
        
        // Map (all geographic data)
        widget.createWidgetExt(context, mapCore.GeoMap, document.getElementById('map'), remoteCell);
      
        // Now that the widgets are live, show the full UI, with a tiny pause for progress display completion and in case of last-minute jank
        log(1.0, 'Ready.');
        setTimeout(function () {
          document.body.classList.remove('main-not-yet-run');
          
          // kludge to trigger js relayout effects. Needed here because main-not-yet-run hides ui.
          var resize = document.createEvent('Event');
          resize.initEvent('resize', false, false);
          window.dispatchEvent(resize);
        }, 100);
        
        // globals for debugging / interactive programming purposes only
        window.DfreqDB = freqDB;
        window.DwritableDB = writableDB;
        window.DradioCell = remoteCell;
        window.Deverything = everything;
        window.Dindex = index;
      }
    }
  }
  
  return main;
});