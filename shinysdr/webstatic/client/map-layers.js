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

define(['./map-core', './values', './network', './events'], function (mapCore, values, network, events) {
  'use strict';
  
  var sin = Math.sin;
  var cos = Math.cos;
  
  var any = values.any;
  var Clock = events.Clock;
  var DerivedCell = values.DerivedCell;
  var Enum = values.Enum;
  var externalGet = network.externalGet;
  var LocalReadCell = values.LocalReadCell;
  var makeBlock = values.makeBlock;
  var registerMapPlugin = mapCore.register;
  var renderTrackFeature = mapCore.renderTrackFeature;
  var StorageCell = values.StorageCell;
  
  var RADIANS_PER_DEGREE = Math.PI / 180;
  function dcos(x) { return cos(RADIANS_PER_DEGREE * x); }
  function dsin(x) { return sin(RADIANS_PER_DEGREE * x); }
  
  function mod(a, b) {
    return ((a % b) + b) % b;
  }
  
  // TODO: Instead of using a blank icon, provide a way to skip the geometry entirely
  var blank = 'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22/%3E';
  
  // TODO: only needs scheduler for DerivedCell. See if DerivedCell can be made to not need a scheduler.
  function makeStaticLayer(url, scheduler) {
    // TODO: Only fetch the URL when the user makes the map visible, to speed up page loading otherwise.
    var dataCell = new LocalReadCell(Object, null);
    // TODO: externalGet into a cell ought to be factored out
    // TODO: UI-visible error report when there are parse errors at any level
    externalGet(url, 'text', function(jsonString) {
      var geojson = JSON.parse(jsonString);
      dataCell._update(geojson);
    });
    return {
      featuresCell: new DerivedCell(any, scheduler, function(dirty) {
        var geojson = dataCell.depend(dirty);
        if (!geojson) return [];
        
        // TODO: More correct parsing
        // TODO: Report this error (and others) inside the layer select UI
        if (geojson.crs.properties.name !== 'urn:ogc:def:crs:OGC:1.3:CRS84') {
          console.error('GeoJSON not in WGS84; will not be correctly displayed.', geojson.crs);
        }
        
        var rings = [];

        // TODO: Expand supported objects to include labels, etc. so that this can be used for more than just drawing polygons.
        function traverse(object) {
          switch (object.type) {
            case 'FeatureCollection':
              object.features.forEach(traverse);
              break;
            case 'Feature':
              traverse(object.geometry);
              break
            case 'MultiPolygon':
              object.coordinates.forEach(function (polygonCoords) {
                polygonCoords.forEach(function (linearRingCoords) {
                  rings.push(linearRingCoords.map(function (position) {
                    return [position[1], position[0]];
                  }));
                })
              });
              break;
            default:
              console.error('unknown GeoJSON object type:', object.type, object);
          }
        }
        traverse(geojson);

        return rings;
      }),
      featureRenderer: function stubRenderer(feature, dirty) {
        // TODO: Arrange for labels
        return {
          label: '',
          iconURL: blank,
          position: feature[0],
          line: feature
        };
      }
    };
  };
  
  registerMapPlugin(function (mapPluginConfig) {
    var addLayer = mapPluginConfig.addLayer;
    var scheduler = mapPluginConfig.scheduler;
    // TODO: .gz suffix really shouldn't be there. Configure web server appropriately.
    addLayer('Basemap', makeStaticLayer('/client/basemap.geojson.gz', scheduler));
  });
  
  function deviceTrack(device, dirty) {
    // TODO full of kludges
    var components = device.components.depend(dirty);
    // components._reshapeNotice.listen(dirty);  // can't happen
    if (!components.position) return null;
    var positionObj = components.position.depend(dirty);
    if (!positionObj['_implements_shinysdr.devices.IPositionedDevice']) return null;
    return positionObj.track.depend(dirty);
  }
  
  registerMapPlugin(function databaseLayerPlugin(mapPluginConfig) {
    var addLayer = mapPluginConfig.addLayer;
    var scheduler = mapPluginConfig.scheduler;
    var db = mapPluginConfig.db;
    var storage = mapPluginConfig.storage;
    var radioCell = mapPluginConfig.radioCell;
    var tune = mapPluginConfig.actions.tune;
    
    // Condensed info about receivers to update DB layer.
    // TODO: Use info for more than the 'current' device.
    var radioStateInfo = new DerivedCell(any, scheduler, function (dirty) {
      var radio = radioCell.depend(dirty);
      var device = radio.source.depend(dirty);
      var center = device.freq.depend(dirty);
      var track = deviceTrack(device, dirty);
      // TODO: Ask the "bandwidth" question directly rather than hardcoding logic here
      var width = device.rx_driver.depend(dirty).output_type.depend(dirty).sample_rate;
      var lower = center - width / 2;
      var upper = center + width / 2;
    
      var receiving = new Map();
      var receivers = radio.receivers.depend(dirty);
      receivers._reshapeNotice.listen(dirty);
      for (var key in receivers) (function(receiver) {
        receiving.set(receiver.rec_freq.depend(dirty), receiver);
      }(receivers[key].depend(dirty)));
    
      return {
        lower: lower,
        upper: upper,
        receiving: receiving,
        track: track
      };
    });
  
    var searchCell = new StorageCell(storage, String, '', 'databaseFilterString');
    addLayer('Database', {
      featuresCell: new DerivedCell(any, scheduler, function(dirty) {
        db.n.listen(dirty);
        return db.string(searchCell.depend(dirty)).getAll();
      }), 
      featureRenderer: function dbRenderer(record, dirty) {
        record.n.listen(dirty);
        var location = record.location;
        if (!location) return {};  // TODO use a filter on the db instead
        
        var info = radioStateInfo.depend(dirty);
        var inSourceBand = info.lower < record.freq && record.freq < info.upper;
        var isReceiving = info.receiving.has(record.freq);
        
        var line;
        if (isReceiving && info.track) {
          //var receiver = info.receiving.get(record);
          // TODO: Should be matching against receiver's device rather than selected device
          line = [[+info.track.latitude.value, +info.track.longitude.value]];
        } else {
          line = [];
        }
        
        // TODO: style for isReceiving
        return {
          iconURL: '/client/map-icons/station-generic.svg',
          position: location,
          label: record.label,
          opacity: inSourceBand ? 1.0 : 0.25,
          line: line
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
    var addLayer = mapPluginConfig.addLayer;
    var scheduler = mapPluginConfig.scheduler;
    var storage = mapPluginConfig.storage;
    var mapCamera = mapPluginConfig.mapCamera;
    
    var graticuleTypeCell = new StorageCell(storage, new Enum({
      'degrees': 'Degrees',
      'maidenhead': 'Maidenhead'
    }), 'degrees', 'graticuleType');
    
    var smoothStep = 1;
    
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
      for (var x = floorTo(lowBound, spacingStep); x < highBound + spacingStep; x += spacingStep) {
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
      for (var i = 0; i < lonDepth || i < latDepth; i++) {
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
      for (var i = granularities.length - 1; i >= 0; i--) {
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
      featuresCell: new DerivedCell(any, scheduler, function(dirty) {
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
          for (var lon = floorTo(visLonMin, lonStep); lon < visLonMax + lonStep*0.5; lon += lonStep) {
            features.push('lonLine,' + lon);
            for (var lat = floorTo(visLatMin + 90, latStep) - 90; lat < visLatMax + latStep*0.5; lat += latStep) {
              features.push('latLine,' + lat);  // duplicates will be coalesced
              features.push('maidenhead,' + (lon + lonStep*0.5) + ',' + (lat + latStep*0.5) + depthStr);
            }
          }
        }
        
        return features;
      }), 
      featureRenderer: function graticuleLineRenderer(spec, dirty) {
        var parts = spec.split(',');
        var type = parts[0];

        switch (type) {
          case 'lonLine':
            var lon = parseFloat(parts[1]);
            var line = [];
            for (var lat = -90; lat < 90 + smoothStep/2; lat += smoothStep) {
              line.push([lat, lon]);
            }
            return Object.freeze({
              position: Object.freeze([90, lon]),
              iconURL: blank,
              label: '',
              line: Object.freeze(line)
            });
          case 'latLine':
            var lat = parseFloat(parts[1]);
            var line = [];
            for (var lon = 0; lon < 360 + smoothStep/2; lon += smoothStep) {
              line.push([lat, lon]);
            }
            return Object.freeze({
              position: Object.freeze([lat, 0]),
              iconURL: blank,
              label: '',
              line: Object.freeze(line)
            });
          case 'lonLabel':
            var lon = parseFloat(parts[1]);
            var logStep = parseFloat(parts[2]);
            var lat = parseFloat(parts[3]);
            var epsilon = Math.pow(10, logStep) / 2;
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: lon > epsilon ? roundLabel(lon, logStep) + 'E' :
                     lon < -epsilon ? roundLabel(-lon, logStep) + 'W' :
                     '0',
              labelSide: lat < 0 ? 'bottom' : lat > 0 ? 'top' : 'center'
            });
          case 'latLabel':
            var lat = parseFloat(parts[1]);
            var logStep = parseFloat(parts[2]);
            var lon = parseFloat(parts[3]);
            var epsilon = Math.pow(10, logStep) / 2;
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: lat > epsilon ? roundLabel(lat, logStep) + 'N' :
                     lat < -epsilon ? roundLabel(-lat, logStep) + 'S' :
                     '0',
              labelSide: lon < 0 ? 'left' : lon < 0 ? 'right' : 'center'
            });
          case 'maidenhead':
            var lon = parseFloat(parts[1]);
            var lat = parseFloat(parts[2]);
            var lonDepth = parseInt(parts[3]);
            var latDepth = parseInt(parts[4]);
            return Object.freeze({
              position: Object.freeze([lat, lon]),
              iconURL: blank,
              label: encodeMaidenhead(lon, lat, lonDepth, latDepth)
            });
          default:
            console.error('Unexpected type in graticule renderer: ' + type);
            return {};
        }
      }
    });
  });
  
  var slowClockForTests = new Clock(1);
  
  registerMapPlugin(function (mapPluginConfig) {
    var addLayer = mapPluginConfig.addLayer;
    var scheduler = mapPluginConfig.scheduler;
    
    // TODO make this test layer more cleaned up and enableable
    var emptyItem = {value: null, timestamp: null};
    var motionTestTrackCell = new DerivedCell(any, scheduler, function(dirty) {
      var t = slowClockForTests.convertToTimestampSeconds(slowClockForTests.depend(dirty));
      var degreeSpeed = 10;
      var angle = t * degreeSpeed;
      var heading = angle + 90;
      //console.log('synthesizing track feature');
      return {
        latitude: {value: dcos(angle) * 10, timestamp: t},
        longitude: {value: dsin(angle) * 10, timestamp: t},
        altitude: emptyItem,
        track_angle: {value: heading, timestamp: t},
        h_speed: {value: 40075e3 / 360 * degreeSpeed / (Math.PI * 2), timestamp: t},  // TODO value
        v_speed: emptyItem,
        heading: {value: heading, timestamp: t}
      };
    });
    var mtNow = Date.now() / 1000;
    if (false) addLayer('Motion Test', {
      featuresCell: new DerivedCell(any, scheduler, function(dirty) {
        var speed = 40075e3/* 1 rev/second */ * 0.1;
        return [
          //{
          //  timestamp: mtNow,
          //  position: [45, 0],
          //  label: '45N 0E 0°',
          //  vangle: 0,
          //  speed: speed,
          //},
          //{
          //  timestamp: mtNow,
          //  position: [0, 0],
          //  label: '0N 0E 90°',
          //  vangle: 90,
          //  speed: speed,
          //},
          //{
          //  timestamp: mtNow,
          //  position: [0, 45],
          //  label: '0N 45E 90°',
          //  vangle: 90,
          //  speed: speed
          //},
          //{
          //  timestamp: mtNow,
          //  position: [0, 0],
          //  label: '0N 0E 0°',
          //  vangle: 0,
          //  speed: speed
          //},
          //{
          //  timestamp: mtNow,
          //  position: [0, 0],
          //  label: '0N 0E 45°',
          //  vangle: 45,
          //  speed: speed
          //},
          'TRACK',
        ];
      }),
      featureRenderer: function testRenderer(feature, dirty) {
        if (feature == 'TRACK') {
          var f = renderTrackFeature(dirty, motionTestTrackCell, 'Track feature');
          return f;
        } else {
          return feature;
        }
      }
    });

    // TODO make this test layer more cleaned up and enableable
    var addDelFeature = {
      position: [10, 10],
      label: 'Blinker'
    };
    if (false) addLayer('Add/Delete Test', {
      featuresCell: new DerivedCell(any, scheduler, function(dirty) {
        // TODO: use explicitly slow clock for less redundant updates
        var t = Math.floor(slowClockForTests.depend(dirty) / 1) * 1;
        addDelFeature.label = 'Blinker ' + t;
        return t % 2 > 0 ? [addDelFeature] : [];
      }),
      featureRenderer: function stubRenderer(feature, dirty) {
        return feature;
      }
    });
  });
  
  registerMapPlugin(function (mapPluginConfig) {
    var addLayer = mapPluginConfig.addLayer;
    var index = mapPluginConfig.index;
    
    addLayer('Station Position', {
      featuresCell: index.implementing('shinysdr.devices.IPositionedDevice'),
      featureRenderer: function (devicePositioning, dirty) {
        // TODO: Because devicePositioning is a device component, we don't have the device itself in order to display the device's name. However, the Index is in a position to provide "containing object" information and arguably should.
        var track = devicePositioning.track.depend(dirty);
        var f = renderTrackFeature(dirty, devicePositioning.track, '');
        f.iconURL = '/client/map-icons/station-user.svg';
        return f;
      }
    });
  });

  return Object.freeze({});
});