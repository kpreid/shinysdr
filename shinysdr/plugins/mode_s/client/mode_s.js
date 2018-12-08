// Copyright 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
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
  'require',
  'map/map-core',
  'widgets',
  'widgets/basic',
], (
  require,
  import_map_core,
  widgets,
  import_widgets_basic
) => {
  const {
    register,
    renderTrackFeature,
  } = import_map_core;
  const {
    Block,
  } = import_widgets_basic;
  
  const exports = {};
  
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
        if (callsign !== null) {
          labelParts.push(callsign.replace(/^ | $/g, ''));
        }
        if (ident !== null) {
          labelParts.push(ident);
        }
        if (altitude !== null) {
          labelParts.push(altitude.toFixed(0) + ' m');
        }
        var f = renderTrackFeature(dirty, trackCell,
          labelParts.join(' • '));
        f.iconURL = require.toUrl('./aircraft.svg');
        return f;
      }
    });
  }
  
  register(addAircraftMapLayer);
  
  return Object.freeze(exports);
});
