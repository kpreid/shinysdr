// Copyright 2014 Kevin Reid <kpreid@switchb.org>
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

// TODO: May be using the wrong relative module id -- otherwise this should have ..s
define(['widgets', 'map-core', 'events'], function (widgets, mapCore, events) {
  'use strict';
  
  var Block = widgets.Block;
  var BlockSet = widgets.BlockSet;
  var Clock = events.Clock;
  var renderTrackFeature = mapCore.renderTrackFeature;
  
  var exports = {};
  
  function APRSStationWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('address'); // in header
      addWidget('track', widgets.TrackWidget);
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.aprs.IAPRSStation'] = APRSStationWidget;
  
  // 30 minutes, standard maximum APRS net cycle time
  // TODO: Make this configurable, and share this constant between client and server
  var APRS_TIMEOUT_SECONDS = 60 * 30;

  var OPACITY_STEPS = 20;
  
  var opacityClock = new Clock(APRS_TIMEOUT_SECONDS / OPACITY_STEPS);
  var blinkClock = new Clock(1/30);
  
  function addAPRSMapLayer(mapPluginConfig) {
    mapPluginConfig.addLayer('APRS', {
      featuresCell: mapPluginConfig.index.implementing('shinysdr.plugins.aprs.IAPRSStation'),
      featureRenderer: function renderStation(station, dirty) {
        var text = station.address.depend(dirty) + ' • ' + station.symbol.depend(dirty) +
        ' • ' + (station.status.depend(dirty) || station.last_comment.depend(dirty));
        // TODO: Add multiline text rendering and use it
        var f = renderTrackFeature(dirty, station.track, text);
        
        // TODO: Get an APRS icon set and use it.
        
        var now = opacityClock.convertToTimestampSeconds(opacityClock.depend(dirty));
        var age = now - station.last_heard_time.depend(dirty);
        if (age < 1) {
          blinkClock.depend(dirty);  // cause fast updates
          f.opacity = Math.cos(age * 4 * Math.PI) * 0.5 + 0.5;
        } else {
          f.opacity = 1 - age / APRS_TIMEOUT_SECONDS;
        }
        
        return f;
      }
    });
  }
  
  mapCore.register(addAPRSMapLayer);
  
  return Object.freeze(exports);
});
