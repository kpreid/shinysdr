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
  './pane-manager',
  './plugins',
  './types',
  './values',
  './widget',
  './widgets',
], (
  import_audio,
  import_coordination,
  import_database,
  import_events,
  import_map_core,
  unused_map_layers,  // side effecting
  import_network,
  import_pane_manager,
  import_plugins,
  import_types,
  import_values,
  import_widget,
  widgets
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
    PaneManager,
  } = import_pane_manager;
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
    const logEl = document.getElementById('loading-information-text');
    if (logEl) {
      logEl.appendChild(document.createTextNode('\n' + msg));
    }
    const progressEl = document.getElementById('loading-information-progress');
    if (progressEl) {
      progressEl.value += (1 - progressEl.value) * progressAmount;
    }
  }
  
  const scheduler = new Scheduler();
  const clientStateStorage = new StorageNamespace(localStorage, 'shinysdr.client.');
  
  function main(configuration) {
    log(0.4, 'Loading plugins…');
    loadCSS();
    requirejs(getJSModuleIds(), plugins => {
      connectRadio(configuration);
    }, err => {
      log(0, 'Failed to load plugins.\n  ' + err.requireModules + '\n  ' + err.requireType);
      // TODO: There's no reason we can't continue without the plugin. The problem is that right now there's no good way to report the failure, and silent failures are bad.
    });
  }
  
  function connectRadio({
      stateUrl,
      audioUrl,
      databasesUrl,
      writableDatabaseUrl,
  }) {
    if (!stateUrl) {
      throw new TypeError('main() cannot proceed without stateUrl');
    }

    const databasesCell = new LocalCell(anyT, systematics);
    // TODO: distinguished writableDB is a kludge till we have proper UI for selection of write targets
    let writableDB = null;
    if (writableDatabaseUrl) {
      writableDB = databaseFromURL(writableDatabaseUrl);
      databasesCell.set(databasesCell.get().concat([
        writableDB,  
      ]));
    }
    if (databasesUrl) {
      // TODO switch to Promise-based interface
      arrayFromCatalog(databasesUrl, dbs => {
        databasesCell.set(databasesCell.get().concat(dbs));
      });
    }
    const databasePicker = new DatabasePicker(
      scheduler,
      databasesCell,
      new StorageNamespace(clientStateStorage, 'databases.'));
    const freqDB = databasePicker.getUnion();
  
    // TODO: Client state should be more closely associated with the components that use it.
    const clientState = new ClientStateObject(clientStateStorage, databasePicker);
    const clientBlockCell = new ConstantCell(clientState);
    
    log(0.5, 'Connecting to server…');
    var firstConnection = true;
    var firstFailure = true;
    scheduler.claim(initialStateReady);
    var remoteCell = connect(stateUrl, connectionCallback);
    remoteCell.n.listen(initialStateReady);
    
    var coordinator = new Coordinator(scheduler, freqDB, remoteCell);
    
    let audioState;
    if (audioUrl) {
      audioState = connectAudio(scheduler, audioUrl, new StorageNamespace(localStorage, 'shinysdr.audio.'));
    } else {
      audioState = makeBlock({});
    }

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
          root_object: remoteCell,
          actions: new ConstantCell(coordinator.actions),
          audio: new ConstantCell(audioState)
        }));
      
        const index = new Index(scheduler, everything);
      
        const context = new Context({
          // TODO all of this should be narrowed down, read-only, replaced with other means to get it to the widgets that need it, etc.
          widgets: widgets,
          radioCell: remoteCell,
          index: index,
          clientState: clientState,
          freqDB: freqDB,
          writableDB: writableDB,
          scheduler: scheduler,
          coordinator: coordinator
        });
        
        // also causes widget creation
        new PaneManager(
          context,
          document,
          everything);
        
        // catch widgets not inside of panes
        createWidgets(everything, context, document);
        
        // Map (all geographic data)
        const mapEl = document.getElementById('map');
        if (mapEl) {
          createWidgetExt(context, GeoMap, mapEl, remoteCell);
        }
      
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