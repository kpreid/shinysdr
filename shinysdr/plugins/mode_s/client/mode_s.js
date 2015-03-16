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
  var projectedPoint = maps.projectedPoint;
  
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
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.mode_s.IAircraft'] = AircraftWidget;
  
  function addAircraftMapLayer(db, scheduler, addModeLayer, addIndexLayer) {
    addIndexLayer('Aircraft', 'shinysdr.plugins.mode_s.IAircraft', {
      rendererOptions: {yOrdering: true, zIndexing: true},
      styleMap: new OpenLayers.StyleMap({
        'default':new OpenLayers.Style({
          label: '${call}\n${ident}\n${altitude}',

          // TODO: Get some of these pieces from maps module to have a common style
          fontColor: 'black',
          fontSize: '.8em',
          fontFamily: 'sans-serif',
          labelYOffset: 14,
          labelOutlineColor: 'white',
          labelOutlineWidth: 3,

          pointRadius: 6,
          fillColor: "#00ee99",
          fillOpacity: 0.4, 
          strokeColor: "#00ee99"
        })
      })
    }, function(aircraft, layer) {
      var positionCell = aircraft.position;
      
      var feature = new OpenLayers.Feature.Vector();
      layer.addFeatures(feature);
      
      function update() {
        if (!layer.interested()) return;
        var position = positionCell.depend(update);
        var lat, lon;
        if (position) {
          lat = position[0];
          lon = position[1];
        } else {
          lat = lon = 0; // TODO bad handling
        }
        var posProj = projectedPoint(lat, lon);
        // TODO: add dead reckoning from velocity
        layer.removeFeatures(feature);  // OL leaves ghosts behind if we merely drawFeature :(
        feature.geometry = posProj;
        feature.attributes.call = aircraft.call.depend(update);
        feature.attributes.ident = aircraft.ident.depend(update);
        feature.attributes.altitude = aircraft.altitude.depend(update);
        layer.addFeatures(feature);
      }
      update.scheduler = scheduler;
      update();
    });
  }
  
  maps.register(addAircraftMapLayer);
  
  return Object.freeze(exports);
});
