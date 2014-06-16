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
define(['maps'], function (maps) {
  'use strict';
  
  var projectedPoint = maps.projectedPoint;
  
  var exports = {};
  
  function addAPRSMapLayer(db, scheduler, addModeLayer, addIndexLayer) {
    addIndexLayer('APRS', 'shinysdr.plugins.aprs.IAPRSStation', {
      rendererOptions: {yOrdering: true, zIndexing: true},
      styleMap: new OpenLayers.StyleMap({
        'default':new OpenLayers.Style({
          label: '${label}\n${status}\n${symbol}',

          // TODO: Get some of these pieces from maps module to have a common style
          fontColor: 'black',
          fontSize: '.8em',
          fontFamily: 'sans-serif',
          labelYOffset: 14,
          labelOutlineColor: 'white',
          labelOutlineWidth: 3,

          pointRadius: 6,
          fillColor: "#0099ee",
          fillOpacity: 0.4, 
          strokeColor: "#0099ee"
        })
      })
    }, function(station, interested, addFeature, drawFeature) {
      var positionCell = station.position;
      
      var address = station.address.get();
      var feature = new OpenLayers.Feature.Vector(new OpenLayers.Geometry.Point(0, 0), {
        label: address
      });
      addFeature(feature);
      
      function update() {
        if (!interested()) return;
        var position = positionCell.depend(update);
        var lat, lon;
        if (position) {
          lat = position[0];
          lon = position[1];
        } else {
          lat = lon = 0; // TODO bad handling
        }
        var posProj = projectedPoint(lat, lon);
        // TODO: add dead reckoning computed positions as recommended
        feature.geometry = posProj;
        feature.attributes.status = station.status.depend(update);
        feature.attributes.symbol = station.symbol.depend(update);
        drawFeature(feature);
      }
      update.scheduler = scheduler;
      update();
    });
  }
  
  maps.register(addAPRSMapLayer);
  
  return Object.freeze(exports);
});
