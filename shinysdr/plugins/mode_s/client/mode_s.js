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
define(['maps', 'widgets'], function (maps, widgets) {
  'use strict';
  
  var BlockSet = widgets.BlockSet;
  var Block = widgets.Block;
  
  var exports = {};
  
  function entryBuilder(setElement, block, name) {
    var container = setElement.appendChild(document.createElement('div'));
    container.className = 'frame';
    var toolbar = container.appendChild(document.createElement('div'));
    toolbar.className = 'panel frame-controls';
    
    var label = document.createElement('span');
    label.textContent = name;
    toolbar.appendChild(label);
    
    return container.appendChild(document.createElement('div'));
  };
  var ModeSInformationWidget = BlockSet(AircraftWidget, entryBuilder);
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.mode_s.IModeSInformation'] = ModeSInformationWidget;
  
  function AircraftWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      addWidget('track', widgets.TrackWidget);  // TODO: Should be handled by type information instead
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.mode_s.IAircraft'] = AircraftWidget;
  
  function addAircraftMapLayer(db, scheduler, index, addLayer, addModeLayer) {
    addLayer('Aircraft', {
      featuresCell: index.implementing('shinysdr.plugins.mode_s.IAircraft'),
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
        return maps.renderTrackFeature(dirty, trackCell,
          labelParts.join(' • '));
      }
    });
  }
  
  maps.register(addAircraftMapLayer);
  
  return Object.freeze(exports);
});
