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
define(['map-core', 'widgets'], function (mapCore, widgets) {
  'use strict';
  
  var BlockSet = widgets.BlockSet;
  var Block = widgets.Block;
  var renderTrackFeature = mapCore.renderTrackFeature;
  
  var exports = {};
  
  function AircraftWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      addWidget('track', widgets.TrackWidget);
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.mode_s.IAircraft'] = AircraftWidget;
  
  function addAircraftMapLayer(mapPluginConfig) {
    mapPluginConfig.addLayer('Aircraft', {
      featuresCell: mapPluginConfig.index.implementing('shinysdr.plugins.mode_s.IAircraft'),
      featureRenderer: function renderAircraft(aircraft, dirty) {
        var trackCell = aircraft.track;
        var callsign = aircraft.call.depend(dirty);
        var ident = aircraft.ident.depend(dirty);
        var altitude = trackCell.depend(dirty).altitude.value;
        var labelParts = [];
        if (callsign != null) {
          labelParts.push(callsign.replace(/^ | $/g, ''));
        }
        if (ident != null) {
          labelParts.push(ident);
        }
        if (altitude != null) {
          labelParts.push(altitude.toFixed(0) + ' m');
        }
        var f = renderTrackFeature(dirty, trackCell,
          labelParts.join(' • '));
        f.iconURL = '/client/plugins/shinysdr.plugins.mode_s/aircraft.svg';
        return f;
      }
    });
  }
  
  mapCore.register(addAircraftMapLayer);
  
  return Object.freeze(exports);
});
