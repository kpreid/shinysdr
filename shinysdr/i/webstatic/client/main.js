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
  './audio',
  './coordination',
  './database',
  './events',
  './map/map-core',
  './map/map-layers',
  './network',
  './plugins',
  './types',
  './values',
  './widget',
  './widgets',
  './window-manager',
], (
  import_audio,
  import_coordination,
  import_database,
  import_events,
  import_map_core,
  unused_map_layers,  // side effecting
  import_network,
  import_plugins,
  import_types,
  import_values,
  import_widget,
  widgets,
  unused_window_manager  // side effecting
) => {
  const {
    connectAudio,
  } = import_audio;
  const {
    ClientStateObject,
    Coordinator,
  } = import_coordination;
  const {
    DatabasePicker,
    arrayFromCatalog,
    fromURL: databaseFromURL,
    systematics,
  } = import_database;
  const {
    Scheduler,
  } = import_events;
  const {
    GeoMap,
  } = import_map_core;
  const {
    connect,
  } = import_network;
  const {
    loadCSS,
    getJSModuleIds,
  } = import_plugins;
  const {
    anyT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    StorageNamespace,
    Index,
    makeBlock,
  } = import_values;
  const {
    Context,
    createWidgetExt,
    createWidgets,
  } = import_widget;
  
  function log(progressAmount, msg) {
    console.log(msg);
    document.getElementById('loading-information-text')
        .appendChild(document.createTextNode('\n' + msg));
    const progress = document.getElementById('loading-information-progress');
    progress.value += (1 - progress.value) * progressAmount;
  }
  
  const scheduler = new Scheduler();

  const clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  
  const writableDB = databaseFromURL('wdb/');
  const databasesCell = new LocalCell(anyT, systematics.concat([
    writableDB,  // kludge till we have proper UI for selection of write targets
  ]));
  arrayFromCatalog('dbs/', dbs => {   // TODO get url from server
    databasesCell.set(databasesCell.get().concat(dbs));
  });
  const databasePicker = new DatabasePicker(
    scheduler,
    databasesCell,
    new StorageNamespace(clientStateStorage, 'databases.'));
  const freqDB = databasePicker.getUnion();
  
  // TODO(kpreid): Client state should be more closely associated with the components that use it.
  const clientState = new ClientStateObject(clientStateStorage, databasePicker);
  const clientBlockCell = new ConstantCell(clientState);
  
  function main(stateUrl, audioUrl) {
    log(0.4, 'Loading plugins…');
    loadCSS();
    requirejs(getJSModuleIds(), function (plugins) {
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
    var remoteCell = connect(stateUrl, connectionCallback);
    remoteCell.n.listen(initialStateReady);
    
    var coordinator = new Coordinator(scheduler, freqDB, remoteCell);
    
    var audioState = connectAudio(scheduler, audioUrl, new StorageNamespace(localStorage, 'shinysdr.audio.'));

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
      // TODO: Is this necessary any more, or is it just a gratuitous rebuild? We're not depending on the value of the cell here.
      remoteCell.n.listen(initialStateReady);
      
      if (firstConnection) {
        firstConnection = false;
        
        const everything = new ConstantCell(makeBlock({
          client: clientBlockCell,
          radio: remoteCell,
          actions: new ConstantCell(coordinator.actions),
          audio: new ConstantCell(audioState)
        }));
      
        var index = new Index(scheduler, everything);
      
        var context = new Context({
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
        createWidgets(everything, context, document);
        
        // Map (all geographic data)
        createWidgetExt(context, GeoMap, document.getElementById('map'), remoteCell);
      
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