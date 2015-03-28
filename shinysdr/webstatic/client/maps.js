// Copyright 2013, 2014 Kevin Reid <kpreid@switchb.org>
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

// Note OpenLayers dependency; OpenLayers is not an AMD module
define(['./values'], function (values) {
  'use strict';
  
  var any = values.any;
  var DerivedCell = values.DerivedCell;
  
  var exports = {};
  
  function projectedPoint(lat, lon) {
    return new OpenLayers.Geometry.Point(lon, lat).transform('EPSG:4326', 'EPSG:3857');
  }
  exports.projectedPoint = projectedPoint;

  function Map(element, scheduler, db, radioCell, index) {
    var baseLayer = new OpenLayers.Layer('Blank', {
      isBaseLayer: true,
      displayInLayerSwitcher: false,  // only one, not useful
    });
    // var baseLayer = new OpenLayers.Layer.OSM();
    var olm = new OpenLayers.Map(element, {
      projection: 'EPSG:3857',
      layers: [baseLayer],
      // Center and zoom will be updated later with station location if available.
      center: new OpenLayers.LonLat(0, 0),
      zoom: 1
    });
    
    var positionInitialized = false;
    olm.events.register('movestart', olm, function () {
      positionInitialized = true;
    });
    
    // Since we don't have a data-ful base layer, add a grid to make it not bare.
    olm.addControl(new OpenLayers.Control.Graticule({
      numPoints: 2,
      labelled: true,
      targetSize: 300,
      labelFormat: 'dm'  // decimal degrees only
    }));
    
    olm.addControl(new OpenLayers.Control.LayerSwitcher());
    
    var radioStateInfo = new DerivedCell(any, scheduler, function (dirty) {
      var radio = radioCell.depend(dirty);
      var source = radio.source.depend(dirty);
      var center = source.freq.depend(dirty);
      // TODO: Ask the "bandwidth" question directly rather than hardcoding logic here
      var width = source.rx_driver.depend(dirty).output_type.depend(dirty).sample_rate;
      var lower = center - width / 2;
      var upper = center + width / 2;
      
      var receiving = [];
      var receivers = radio.receivers.depend(dirty);
      receivers._reshapeNotice.listen(dirty);
      for (var key in receivers) (function(receiver) {
        receiving.push(receiver.rec_freq.depend(dirty));
      }(receivers[key].depend(dirty)));
      
      return {
        lower: lower,
        upper: upper,
        receiving: receiving
      };
    });
    
    var dbLayer = new OpenLayers.Layer.Vector('Database', {
      rendererOptions: {yOrdering: true, zIndexing: true},
      styleMap: new OpenLayers.StyleMap({
        'default':new OpenLayers.Style({
          label: '${label}',

          fontColor: 'black',
          fontSize: '.8em',
          fontFamily: 'sans-serif',
          labelYOffset: 20,
          labelOutlineColor: 'white',
          labelOutlineWidth: 3,

          externalGraphic: '/client/openlayers/img/marker-green.png',
          graphicHeight: 21,
          graphicWidth: 16
        }, {
          rules: [
            new OpenLayers.Rule({
              filter: new OpenLayers.Filter.Comparison({
                type: OpenLayers.Filter.Comparison.NOT_EQUAL_TO,
                property: 'isReceiving',
                value: false
              }),
              symbolizer: {
                externalGraphic: '/client/openlayers/img/marker-gold.png',
              }
            }),
            new OpenLayers.Rule({
              filter: new OpenLayers.Filter.Comparison({
                type: OpenLayers.Filter.Comparison.NOT_EQUAL_TO,
                property: 'inSourceBand',
                value: false
              }),
              symbolizer: {
                fontColor: 'black',
                // Unfortunately, there is no labelZIndex so this ordering doesn't help much
                // https://github.com/openlayers/openlayers/issues/1167
                graphicZIndex: 2
              }
            }),
            new OpenLayers.Rule({
              elseFilter: true,
              symbolizer: {
                // TODO: Better presentation; say, add a highlighting around in-band rather than fading out-of-band
                fontColor: 'gray',
                graphicOpacity: 0.25,
                graphicZIndex: 1
              }
            })
          ]
        })
      }),
      eventListeners: {
        featureclick: function (event) {
          radioCell.get().preset.set(event.feature.attributes.record);
        }
      }
    });
    olm.addLayer(dbLayer);
    var dbLayerMarkerVersion;
    function updateDBLayer() {
      dbLayerMarkerVersion = {};
      db.n.listen(updateDBLayer);
      dbLayer.removeAllFeatures();
      db.forEach(function(record) {  // TODO: Add geographic bounds query and let openlayers use it as a 'strategy'
        if (!record.location) return;
        var markerVersion = dbLayerMarkerVersion;
        var feature = new OpenLayers.Feature.Vector(
          projectedPoint(record.location[0], record.location[1]),
          {
            label: record.label,
            record: record,
            inSourceBand: false,
            isSelected: false
          });
        function updateMarker() {
          if (markerVersion !== dbLayerMarkerVersion) return;  // kill update loop
          
          var info = radioStateInfo.depend(updateMarker);
          
          feature.attributes.inSourceBand = info.lower < record.freq && record.freq < info.upper;
          feature.attributes.isReceiving = info.receiving.indexOf(record.freq) !== -1;
          
          dbLayer.drawFeature(feature);
        }
        updateMarker.scheduler = scheduler;
        updateMarker();
        dbLayer.addFeatures([feature]);
      });
    }
    updateDBLayer.scheduler = scheduler;
    updateDBLayer();
    
    // No good way to listen for layout updates, so poll
    // TODO: build a generic resize hook that SpectrumView can use too
    setInterval(function() {
      olm.updateSize();
    }, 1000);
    
    function makeLayerFacet(layer) {
      var dead = false;
      return {
        facet: {
          interested: function interested() { return !dead; },
          addFeatures: function addFeatures(features) {
            if (dead) throw new Error('dead');
            layer.addFeatures(features);
          },
          drawFeature: function drawFeature(feature) {
            if (dead) throw new Error('dead');
            layer.drawFeature(feature);
          },
          removeFeatures: function removeFeatures(features) {
            if (dead) throw new Error('dead');
            layer.removeFeatures(features);
          }
        },
        kill: function () { dead = true; }
      };
    }
    
    // Receiver-derived data
    // TODO: Either replace uses of this with addIndexLayer or make them share an implementation
    function addModeLayer(filterMode, prepare) {
      var modeLayer = new OpenLayers.Layer.Vector(filterMode);
      olm.addLayer(modeLayer);
      
      var currentRun = {};
      var cancellers = [];

      function updateOnReceivers() {
        //console.log('updateOnReceivers');
        var radio = radioCell.depend(updateOnReceivers);
        var receivers = radio.receivers.depend(updateOnReceivers);
        receivers._reshapeNotice.listen(updateOnReceivers);  // TODO break loop if map is dead
        modeLayer.removeAllFeatures();
        cancellers.forEach(function (f) { f(); });
        cancellers = [];
        var runToken = currentRun = {};
        for (var key in receivers) (function(receiver) {
          var layerFacetPair = makeLayerFacet(modeLayer);
          cancellers.push(layerFacetPair.kill);
          function updateOnReceiver() {
            if (currentRun !== runToken) return;
            
            // note this calls updateOnReceivers so we clear out features if the receiver switches away from the mode
            var rMode = receiver.mode.depend(updateOnReceivers);  // TODO break loop if map is dead
            receiver.demodulator.n.listen(updateOnReceiver);  // not necessary, but useful for our clients
            
            if (rMode !== filterMode) {
              return;
            }
            
            //console.log('clearing to rebuild');
            modeLayer.removeAllFeatures();  // clear old state
            
            prepare(receiver, layerFacetPair.facet);
          }
          updateOnReceiver.scheduler = scheduler;
          updateOnReceiver();
        }(receivers[key].depend(updateOnReceivers)));
      }
      updateOnReceivers.scheduler = scheduler;
      updateOnReceivers();
    }

    function addIndexLayer(name, interfaceName, options, prepare) {
      var layerIndex = index.implementing(interfaceName);
      
      var dynamicLayer = new OpenLayers.Layer.Vector(name, options);
      olm.addLayer(dynamicLayer);
      
      var cancellers = [];

      function updateOnIndex() {
        var objects = layerIndex.depend(updateOnIndex);
        dynamicLayer.removeAllFeatures();
        cancellers.forEach(function (f) { f(); });
        cancellers = [];
        objects.forEach(function (object) {
          var layerFacetPair = makeLayerFacet(dynamicLayer);
          cancellers.push(layerFacetPair.kill);
          var features = [];
          function updateOnObject() {
            dynamicLayer.removeFeatures(features);  // clear old state
            features.length = 0;
            
            prepare(object, layerFacetPair.facet);
          }
          updateOnObject.scheduler = scheduler;
          updateOnObject();
        });
      }
      updateOnIndex.scheduler = scheduler;
      updateOnIndex();
    }

    addIndexLayer('Station Position', 'shinysdr.devices.IPositionedDevice', {
      rendererOptions: {},
      styleMap: new OpenLayers.StyleMap({
        'default':new OpenLayers.Style({
          pointRadius: 6,
          fillColor: "#cc7777",
          fillOpacity: 0.4, 
          strokeColor: "#cc0000"
        })
      })
    }, function(devicePositioning, layer) {
      // TODO: Because devicePositioning is a device component, we don't have the device itself in order to display the device's name. However, the Index is in a position to provide "containing object" information and arguably should.
      var positionCell = devicePositioning.position;
      
      var feature = new OpenLayers.Feature.Vector();
      layer.addFeatures(feature);
      
      function update() {
        if (!layer.interested()) return;
        var position = positionCell.depend(update);
        feature.geometry = projectedPoint(+position[0], +position[1]);
        layer.drawFeature(feature);
        
        // Borrow station position to set initial map view
        if (!positionInitialized) {
          positionInitialized = true;
          olm.setCenter(
            feature.geometry.getBounds().getCenterLonLat(),
            9); // zoom level
        }
      }
      update.scheduler = scheduler;
      update();
    });

    plugins.forEach(function(pluginFunc) {
      // TODO provide an actually designed interface
      pluginFunc(db, scheduler, addModeLayer, addIndexLayer);
    });
  }
  exports.Map = Map;
  
  var plugins = [];
  exports.register = function(pluginFunc) {
    plugins.push(pluginFunc);
  };
  
  function addTrackFeaturesToLayer(scheduler, layer, trackCell, markFeatures) {
    // TODO either the history needs to be more persistent than this, or we need to stop doing removeAllFeatures in addIndexLayer and addModeLayer; as it is history is cleared whenever something is added or removed
    var trackHistory = new OpenLayers.Geometry.LineString([]);
    var trackFeature = new OpenLayers.Feature.Vector(trackHistory, {}, {
      // TODO set some styles
    });
    layer.addFeatures(trackFeature);
    layer.addFeatures(markFeatures);
    
    function updatePos() {
      if (!layer.interested()) return;
      var track = trackCell.depend(updatePos);
      var lat = track.latitude.value;
      var lon = track.longitude.value;
      if (!(isFinite(lat) && isFinite(lon))) {
        lat = lon = 0; // TODO bad handling
      }
      var posProj = projectedPoint(lat, lon);
      // TODO: add dead reckoning computed positions as recommended

      layer.removeFeatures(markFeatures);  // OL leaves ghosts behind if we merely drawFeature a moved point feature :(
      markFeatures.forEach(function (markFeature) {
        markFeature.geometry = posProj;
      });
      trackHistory.addPoint(posProj);
      layer.addFeatures(markFeatures);
      layer.drawFeature(trackFeature);
    }
    updatePos.scheduler = scheduler;
    updatePos();
  }
  exports.addTrackFeaturesToLayer = addTrackFeaturesToLayer;
  
  return Object.freeze(exports);
});