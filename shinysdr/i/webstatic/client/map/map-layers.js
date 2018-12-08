// Copyright 2013, 2014, 2015, 2016, 2017 Kevin Reid <kpreid@switchb.org>
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
  './map-core',
  '../math',
  '../network',
  '../types',
  '../values',
], (
  require,
  import_map_core,
  import_math,
  import_network,
  import_types,
  import_values
) => {
  const {
    register: registerMapPlugin,
    renderTrackFeature,
    greatCircleLineAlong,
    greatCircleLineTo,
  } = import_map_core;
  const {
    mod
  } = import_math;
  const {
    externalGet,
  } = import_network;
  const {
    EnumT,
    anyT,
    stringT,
  } = import_types;
  const {
    DerivedCell,
    LocalReadCell,
    StorageCell,
    findImplementersInBlockCell,
    makeBlock,
  } = import_values;

  const {
    cos,
  } = Math;
  
  const RADIANS_PER_DEGREE = Math.PI / 180;
  function dcos(x) { return cos(RADIANS_PER_DEGREE * x); }
  
  // TODO: Instead of using a blank icon, provide a way to skip the geometry entirely
  const blank = 'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22/%3E';
  
  // TODO: only needs scheduler for DerivedCell. See if DerivedCell can be made to not need a scheduler.
  function makeStaticLayer(url, scheduler) {
    // TODO: Only fetch the URL when the user makes the map visible, to speed up page loading otherwise.
    var dataCell = new LocalReadCell(anyT, null);
    // TODO: externalGet into a cell ought to be factored out
    // TODO: UI-visible error report when there are parse errors at any level
    externalGet(url, 'text').then(jsonString => {
      var geojson = JSON.parse(jsonString);
      dataCell._update(geojson);
    });
    return {
      featuresCell: new DerivedCell(anyT, scheduler, function(dirty) {
        var geojson = dataCell.depend(dirty);
        if (!geojson) return [];
        
        // TODO: More correct parsing
        // TODO: Report this error (and others) inside the layer select UI
        if (geojson.crs.properties.name !== 'urn:ogc:def:crs:OGC:1.3:CRS84') {
          console.error('GeoJSON not in WGS84; will not be correctly displayed.', geojson.crs);
        }
        
        var convertedFeatures = [];

        // TODO: Expand supported objects to include labels, etc. so that this can be used for more than just drawing polygons.
        function traverse(object) {
          switch (object.type) {
            case 'FeatureCollection':
              object.features.forEach(traverse);
              break;
            case 'Feature':
              // don't yet care about feature structure, break down into geometry
              traverse(object.geometry);
              break;
            case 'MultiPolygon':
              // don't yet care about structure, break down the multipolygon into rings
              object.coordinates.forEach(polygonCoords => {
                polygonCoords.forEach(linearRingCoords => {
                  const convertedLinearRing = linearRingCoords.map(position =>
                    ({position: [position[1], position[0]]}));
                  convertedFeatures.push({
                    lineWeight: 0.65,  // TODO shouldn't be hardcoded in makeStaticLayer
                    polylines: [convertedLinearRing]
                  });
                });
              });
              break;
            default:
              console.error('unknown GeoJSON object type:', object.type, object);
          }
        }
        traverse(geojson);

        return convertedFeatures;
      }),
      featureRenderer: function stubRenderer(feature, dirty) {
        return feature;
      }
    };
  }
  
  registerMapPlugin(function (mapPluginConfig) {
    var addLayer = mapPluginConfig.addLayer;
    var scheduler = mapPluginConfig.scheduler;
    // TODO: .gz suffix really shouldn't be there. Configure web server appropriately.
    addLayer('Basemap', makeStaticLayer(require.toUrl('./basemap.geojson.gz'), scheduler));
  });
  
  function deviceTracks(scheduler, device, dirty) {
    return findImplementersInBlockCell(
      scheduler,
      device.components,
      'shinysdr.devices.IPositionedDevice'
    ).depend(dirty).map(component => component.track.depend(dirty));
  }
  
  registerMapPlugin(function databaseLayerPlugin(mapPluginConfig) {
    const addLayer = mapPluginConfig.addLayer;
    const scheduler = mapPluginConfig.scheduler;
    const db = mapPluginConfig.db;
    const storage = mapPluginConfig.storage;
    const radioCell = mapPluginConfig.radioCell;
    const tune = mapPluginConfig.actions.tune;
    
    // Condensed info about receivers to update DB layer.
    // TODO: Use info for more than the 'current' device.
    const radioStateInfo = new DerivedCell(anyT, scheduler, function (dirty) {
      const radio = radioCell.depend(dirty);
      const device = radio.source.depend(dirty);
      const center = device.freq.depend(dirty);
      const tracks = deviceTracks(scheduler, device, dirty);
      // TODO: Ask the "bandwidth" question directly rather than hardcoding logic here
      const width = device.rx_driver.depend(dirty).output_type.depend(dirty).sample_rate;
      const lower = center - width / 2;
      const upper = center + width / 2;
    
      var receiving = new Map();
      var receivers = radio.receivers.depend(dirty);
      receivers._reshapeNotice.listen(dirty);
      for (const key in receivers) {
        const receiver = receivers[key].depend(dirty);
        receiving.set(receiver.rec_freq.depend(dirty), receiver);
      }
    
      return {
        lower: lower,
        upper: upper,
        receiving: receiving,
        tracks: tracks
      };
    });
  
    var searchCell = new StorageCell(storage, stringT, '', 'databaseFilterString');
    addLayer('Database', {
      featuresCell: new DerivedCell(anyT, scheduler, function(dirty) {
        db.n.listen(dirty);
        return db.string(searchCell.depend(dirty)).getAll();
      }), 
      featureRenderer: function dbRenderer(record, dirty) {
        record.n.listen(dirty);
        var location = record.location;
        if (!location) return {};  // TODO use a filter on the db instead
        
        // Smarter update than just dirty(), so that we don't rerender on every change whether it affects us or not
        function checkInfo() {
          info = radioStateInfo.get();
          if (
            inSourceBand !== (info.lower < record.freq && record.freq < info.upper) ||
            isReceiving !== info.receiving.has(record.freq)
          ) {
            dirty();
          } else {
            radioStateInfo.n.listen(checkInfo);
          }
        }
        scheduler.claim(checkInfo);
        var info = radioStateInfo.depend(checkInfo);
        var inSourceBand = info.lower < record.freq && record.freq < info.upper;
        var isReceiving = info.receiving.has(record.freq);
        
        const lines = [];
        if (isReceiving) {
          //var receiver = info.receiving.get(record);
          // TODO: Should be matching against receiver's device rather than selected device
          info.tracks.forEach(track => {
            lines.push(greatCircleLineTo(
              location[0], location[1],
              track.latitude.value, track.longitude.value));
          });
        }
        
        // TODO: style for isReceiving
        return {
          iconURL: require.toUrl('./icons/station-generic.svg'),
          position: location,
          label: record.label,
          opacity: inSourceBand ? 1.0 : 0.25,
          polylines: lines
        };
      },
      onclick: function clickOnDbFeature(feature) {
        tune({record: feature});
      },
      controls: makeBlock({
        search: searchCell
      })
    });
  });
  
  registerMapPlugin(function(mapPluginConfig) {
    const addLayer = mapPluginConfig.addLayer;
    const scheduler = mapPluginConfig.scheduler;
    const storage = mapPluginConfig.storage;
    const mapCamera = mapPluginConfig.mapCamera;
    
    const graticuleTypeCell = new StorageCell(storage, new EnumT({
      'degrees': 'Degrees',
      'maidenhead': 'Maidenhead'
    }), 'degrees', 'graticuleType');
    
    const smoothStep = 1;
    
    function dasinClamp(x) {
      var deg = Math.asin(x) / RADIANS_PER_DEGREE;
      return isFinite(deg) ? deg : 90;
    }
    function floorTo(x, step) {
      return Math.floor(x / step) * step;
    }
    function roundLabel(x, logStep) {
      return x.toFixed(Math.max(0, -logStep));
    }
    function computeLabelPosition(lowBound, highBound, logStep) {
      var spacingStep = Math.pow(10, logStep);
      
      var coord = Math.max(lowBound, Math.min(highBound, 0));
      coord = floorTo(coord, spacingStep);
      if (coord <= lowBound) coord += spacingStep;
      return coord;
    }
    function addLinesAndMarks(features, axis, otherCoord, otherAxisPos, lowBound, highBound, logStep) {
      var spacingStep = Math.pow(10, logStep);
      for (let x = floorTo(lowBound, spacingStep); x < highBound + spacingStep; x += spacingStep) {
        features.push(axis + 'Line,' + x);
        features.push(axis + 'Label,' + x + ',' + logStep + ',' + otherCoord);
      }
    }
    
    // Maidenhead encoding tables
    var symbolSets = [
      'ABCDEFGHIJKLMNOPQR',       // field
      '0123456789',               // squre
      'abcdefghijklmnopqrstuvwx', // subsquare
      '0123456789'                // extended square
    ];
    var granularities = [1];
    symbolSets.forEach(function (symbols) {
      granularities.push(granularities[granularities.length - 1] * symbols.length);
    });
    Object.freeze(granularities);
    function encodeMaidenhead(lon, lat, lonDepth, latDepth) {
      // The 'm' variables are scaled so that [0, 1) maps to {first symbol, ..., last symbol} circularly
      var mlon = (lon + 180) / 360;
      var mlat = (lat + 90) / 180;
      var code = '';
      for (let i = 0; i < lonDepth || i < latDepth; i++) {
        var table = symbolSets[i];
        var n = table.length;
        mlon *= n;
        mlat *= n;
        code += (i < lonDepth ? table[Math.floor(mod(mlon, n))] : '_')
              + (i < latDepth ? table[Math.floor(mod(mlat, n))] : '_');
      }
      return code;
    }
    var MAX_LINES_IN_VIEW = 10;
    function maidenheadDepth(x) {
      for (let i = granularities.length - 1; i >= 0; i--) {
        if (granularities[i] * x <= MAX_LINES_IN_VIEW) {
          return i;
        }
      }
      return 1;
    }
    
    addLayer('Graticule', {
      controls: makeBlock({
        type: graticuleTypeCell
      }),
      featuresCell: new DerivedCell(anyT, scheduler, function(dirty) {
        // TODO: Don't rerun this calc on every movement — have a thing which takes an 'error' window (eep computing that) and dirties if out of bounds
        var zoom = mapCamera.zoomCell.depend(dirty);
        var centerLat = mapCamera.latitudeCell.depend(dirty);
        var centerLon = mapCamera.longitudeCell.depend(dirty);
        
        // TODO: Does not account for sphericality (visible with wide aspect ratios)
        var visibleRadiusLatDeg = dasinClamp(1 / mapCamera.getEffectiveYZoom());
        
        var visLatMin = Math.max(-90, centerLat - visibleRadiusLatDeg);
        var visLatMax = Math.min(90, centerLat + visibleRadiusLatDeg);
        
        var invXZoom = 1 / mapCamera.getEffectiveXZoom();
        var contraction = Math.max(0, Math.min(
          dcos(centerLat - visibleRadiusLatDeg),
          dcos(centerLat + visibleRadiusLatDeg)));
        var expansion = Math.max(0,
          dcos(centerLat - visibleRadiusLatDeg),
          dcos(centerLat + visibleRadiusLatDeg));
        // The visible longitudes at the smallest-scale part of the viewport (what lines must be drawn)
        var visibleRadiusLonDeg = dasinClamp(invXZoom / contraction);
        // The visible longitudes at the largest-scale part of the viewport (where to put the labels)
        var visibleRadiusLonDegInner = dasinClamp(invXZoom / expansion);
        
        // this condition both avoids overdrawing and handles looking past the poles
        var fullSphere = visibleRadiusLonDeg >= 90;
        var visLonMin = fullSphere ? -180 : Math.max(centerLon - visibleRadiusLonDeg);
        var visLonMax = fullSphere ? 180 : Math.min(centerLon + visibleRadiusLonDeg);
        var visLonInnerMin = Math.max(centerLon - visibleRadiusLonDegInner);
        var visLonInnerMax = Math.min(centerLon + visibleRadiusLonDegInner);
        
        var features = [];
        
        var graticuleType = graticuleTypeCell.depend(dirty);
        if (graticuleType === 'degrees') {
          var latLogStep = Math.ceil(Math.log(10 / zoom) / Math.LN10);
          // don't draw lots of longitude lines when zoomed on a pole
          var lonStepLimit = Math.ceil(Math.log(visibleRadiusLonDeg / 20) / Math.LN10);
          var lonLogStep = Math.max(lonStepLimit, latLogStep);

          var latLabelLon = computeLabelPosition(visLonInnerMin, visLonInnerMax, lonLogStep);
          var lonLabelLat = computeLabelPosition(visLatMin, visLatMax, latLogStep);
          addLinesAndMarks(features, 'lat', latLabelLon, lonLabelLat, visLatMin, visLatMax, latLogStep);
          addLinesAndMarks(features, 'lon', lonLabelLat, latLabelLon, visLonMin, visLonMax, lonLogStep);
        } else if (graticuleType === 'maidenhead') {
          var lonDepth = maidenheadDepth(visibleRadiusLonDeg / 360);
          var latDepth = maidenheadDepth(visibleRadiusLatDeg / 180);
          latDepth = lonDepth = Math.min(latDepth, lonDepth);  // TODO do better
          var lonStep = 360 / granularities[lonDepth];
          var latStep = 180 / granularities[latDepth];
          var depthStr = ',' + lonDepth + ',' + latDepth;
          for (let lon = floorTo(visLonMin, lonStep); lon < visLonMax + lonStep*0.5; lon += lonStep) {
            features.push('lonLine,' + lon);
            for (let lat = floorTo(visLatMin + 90, latStep) - 90; lat < visLatMax + latStep*0.5; lat += latStep) {
              features.push('latLine,' + lat);  // duplicates will be coalesced
              features.push('maidenhead,' + (lon + lonStep*0.5) + ',' + (lat + latStep*0.5) + depthStr);
            }
          }
        }
        
        return features;
      }), 
      featureRenderer: function graticuleLineRenderer(spec, dirty) {
        const parts = spec.split(',');
        const type = parts[0];

        switch (type) {
          case 'lonLine': {
            const lon = parseFloat(parts[1]);
            const line = [];
            for (let lat = -90; lat < 90 + smoothStep/2; lat += smoothStep) {
              line.push(Object.freeze({position: Object.freeze([lat, lon])}));
            }
            return Object.freeze({
              lineWeight: 0.25,
              polylines: Object.freeze([Object.freeze(line)])
            });
          }
          case 'latLine': {
            const lat = parseFloat(parts[1]);
            const line = [];
            for (let lon = 0; lon < 360 + smoothStep/2; lon += smoothStep) {
              line.push(Object.freeze({position: Object.freeze([lat, lon])}));
            }
            return Object.freeze({
              lineWeight: 0.25,
              polylines: Object.freeze([Object.freeze(line)])
            });
          }
          case 'lonLabel': {
            const lon = parseFloat(parts[1]);
            const logStep = parseFloat(parts[2]);
            const lat = parseFloat(parts[3]);
            const epsilon = Math.pow(10, logStep) / 2;
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: lon > epsilon ? roundLabel(lon, logStep) + 'E' :
                     lon < -epsilon ? roundLabel(-lon, logStep) + 'W' :
                     '0',
              labelSide: lat < 0 ? 'bottom' : lat > 0 ? 'top' : 'center'
            });
          }
          case 'latLabel': {
            const lat = parseFloat(parts[1]);
            const logStep = parseFloat(parts[2]);
            const lon = parseFloat(parts[3]);
            const epsilon = Math.pow(10, logStep) / 2;
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: lat > epsilon ? roundLabel(lat, logStep) + 'N' :
                     lat < -epsilon ? roundLabel(-lat, logStep) + 'S' :
                     '0',
              labelSide: lon < 0 ? 'left' : lon < 0 ? 'right' : 'center'
            });
          }
          case 'maidenhead': {
            const lon = parseFloat(parts[1]);
            const lat = parseFloat(parts[2]);
            const lonDepth = parseInt(parts[3]);
            const latDepth = parseInt(parts[4]);
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: encodeMaidenhead(lon, lat, lonDepth, latDepth)
            });
          }
          default:
            console.error('Unexpected type in graticule renderer: ' + type);
            return {};
        }
      }
    });
  });
  
  registerMapPlugin(({addLayer, scheduler, index}) => {
    addLayer('Station Position', {
      featuresCell: new DerivedCell(anyT, scheduler, (dirty) => {
        const features = [];
        // TODO: Show only the mapPluginConfig.radio.source device, and not all devices?
        const devices = index.implementing('shinysdr.devices.IDevice').depend(dirty);
        devices.forEach(device => {
          const name = '';  // TODO: Device name doesn't appear to be available?
          const positionedDevices = findImplementersInBlockCell(scheduler, device.components, 'shinysdr.devices.IPositionedDevice').depend(dirty);
          positionedDevices.forEach(component => {
            features.push({'type': 'track', 'trackCell': component.track, 'name': name});
          });
          if (positionedDevices.length) {
            const rotators = findImplementersInBlockCell(scheduler, device.components, 'shinysdr.plugins.hamlib.IRotator').depend(dirty);
            rotators.forEach(component => {
              features.push({'type': 'rotator', 'trackCell': positionedDevices[0].track, 'azimuthCell': component.Azimuth});
            });
          }
        });
        return Object.freeze(features);
      }),
      featureRenderer: function (spec, dirty) {
        switch (spec.type) {
          case 'track': {
            const f = renderTrackFeature(dirty, spec.trackCell, spec.name);
            f.iconURL = require.toUrl('./icons/station-user.svg');
            return f;
          }
          case 'rotator': {
            // TODO: Draw azimuth line in a different color.
            const track = spec.trackCell.depend(dirty);
            const [lat, lon] = [track.latitude.value, track.longitude.value];
            // TODO: Why are these isFinite guards necessary?
            if (typeof lat === 'number' && typeof lon === 'number' && isFinite(lat) && isFinite(lon)) {
              const azimuth = spec.azimuthCell.depend(dirty);
              if (typeof azimuth === 'number' && isFinite(azimuth)) {
                return Object.freeze({
                  lineWeight: 2,
                  polylines: Object.freeze([greatCircleLineAlong(lat, lon, azimuth)]),
                });
              }
            }
            return Object.freeze({});
          }
        }
      },
    });
  });

  return Object.freeze({});
});
