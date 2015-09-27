// Copyright 2013, 2014, 2015 Kevin Reid <kpreid@switchb.org>
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

define(['./values', './events', './coordination', './database', './network', './map-core', './map-layers', './widget', './widgets', './audio', './window-manager'], function (values, events, coordination, database, network, mapCore, mapLayers, widget, widgets, audio, windowManager) {
  'use strict';
  
  function log(progressAmount, msg) {
    console.log(msg);
    document.getElementById('loading-information-text')
        .appendChild(document.createTextNode('\n' + msg));
    var progress = document.getElementById('loading-information-progress');
    progress.value += (1 - progress.value) * progressAmount;
  }
  
  var any = values.any;
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
  function cc(key, type, value) {
    return new StorageCell(clientStateStorage, type, value, key);
  }
  var clientState = makeBlock({
    opengl: cc('opengl', Boolean, true),
    opengl_float: cc('opengl_float', Boolean, true),
    spectrum_split: cc('spectrum_split', new values.Range([[0, 1]], false, false), 0.5),
    spectrum_average: cc('spectrum_average', new values.Range([[0.1, 1]], true, false), 0.25),
    databases: new ConstantCell(values.block, databasePicker)
  });
  var clientBlockCell = new ConstantCell(values.block, clientState);
  
  // TODO get url from server
  log(0.4, 'Loading plugins…');
  network.externalGet('/client/plugin-index.json', 'text', function gotPluginIndex(jsonstr) {
    var pluginIndex = JSON.parse(jsonstr);
    Array.prototype.forEach.call(pluginIndex.css, function (cssUrl) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = String(cssUrl);
      document.querySelector('head').appendChild(link);
    })
    requirejs(Array.prototype.slice.call(pluginIndex.js), function (plugins) {
      connectRadio();
    }, function (err) {
      log(0, 'Failed to load plugins.\n  ' + err.requireModules + '\n  ' + err.requireType);
      // TODO: There's no reason we can't continue without the plugin. The problem is that right now there's no good way to report the failure, and silent failures are bad.
    });
  });
  
  function connectRadio() {
    log(0.5, 'Connecting to server…');
    var firstConnection = true;
    var firstFailure = true;
    initialStateReady.scheduler = scheduler;
    var remoteCell = network.connect(network.convertToWebSocketURL('radio'), connectionCallback);
    remoteCell.n.listen(initialStateReady);

    var audioState = audio.connectAudio(network.convertToWebSocketURL('audio'));  // TODO get url from server

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
      
      // Kludge to let frequency preset widgets do their thing
      // TODO(kpreid): Replace this with Coordinator functions
      radio.preset = new LocalCell(any, undefined);
      radio.preset.set = function(freqRecord) {
        LocalCell.prototype.set.call(this, freqRecord);
        coordinator.actions.tune({
          record: freqRecord
        });
      };
      
      if (firstConnection) {
        firstConnection = false;
        
        var everything = new ConstantCell(values.block, makeBlock({
          client: clientBlockCell,
          radio: remoteCell,
          audio: new ConstantCell(values.block, audioState)
        }));
      
        var index = new Index(scheduler, everything);
      
        var coordinator = new Coordinator(scheduler, freqDB, remoteCell);
      
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
});