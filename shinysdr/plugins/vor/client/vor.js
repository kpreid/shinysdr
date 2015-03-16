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

// TODO: May be using the wrong relative module id -- otherwise this should have ..s
define(['maps', 'widgets'], function (maps, widgets) {
  'use strict';
  
  var projectedPoint = maps.projectedPoint;
  
  var exports = {};
  
  var TAU = Math.PI * 2;
  var RAD_TO_DEG = 360 / TAU;
  
  function mod(value, modulus) {
    return (value % modulus + modulus) % modulus;
  }
  
  function Angle(config) {
    var target = config.target;
    var container = this.element = document.createElement('div');
    var canvas = container.appendChild(document.createElement('canvas'));
    var text = container.appendChild(document.createElement('span'))
        .appendChild(document.createTextNode(''));
    canvas.width = 61; // odd size for sharp center
    canvas.height = 61;
    var ctx = canvas.getContext('2d');
    
    var w, h, cx, cy, r;
    function polar(method, pr, angle) {
      ctx[method](cx + pr*r * Math.sin(angle), cy - pr*r * Math.cos(angle));
    }
    
    function draw() {
      var valueAngle = target.depend(draw);
      
      text.nodeValue = mod(valueAngle * RAD_TO_DEG, 360).toFixed(2) + '\u00B0';
      
      w = canvas.width;
      h = canvas.height;
      cx = w / 2;
      cy = h / 2;
      r = Math.min(w / 2, h / 2) - 1;
      
      ctx.clearRect(0, 0, w, h);
      
      ctx.strokeStyle = '#666';
      ctx.beginPath();
      // circle
      ctx.arc(cx, cy, r, 0, TAU, false);
      // ticks
      for (var i = 0; i < 36; i++) {
        var t = TAU * i / 36;
        var d = !(i % 9) ? 3 : !(i % 3) ? 2 : 1;
        polar('moveTo', 1.0 - 0.1 * d, t);
        polar('lineTo', 1.0, t);
      }
      ctx.stroke();

      // pointer
      ctx.strokeStyle = 'black';
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      polar('lineTo', 1.0, valueAngle);
      ctx.stroke();
    }
    draw.scheduler = config.scheduler;
    draw();
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets.VOR$Angle = Angle;
  
  function addVORMapLayer(db, scheduler, addModeLayer) {
    addModeLayer('VOR', function(receiver, layer) {
      var angleCell = receiver.demodulator.get().angle;  // demodulator change will be handled by addModeLayer
      if (!angleCell) {
        console.warn('addVORMapLayer saw a non-VOR demodulator');
        return;  // TODO not-yet-investigated bug
      }
      var freqCell = receiver.rec_freq;
      var lengthInDegrees = 0.5;
      
      var records = db.inBand(freqCell.get(), freqCell.get()).type('channel').getAll();
      var record = records[0];
      if (!record) {
        console.log('VOR map: No record match', freqCell.get());
        return;
      }
      if (!record.location) {
        console.log('VOR map: Record has no location', record.label);
        return;
      }
      var lat = record.location[0];
      var lon = record.location[1];
      // TODO update location if db/record/freq changes
      
      var origin = projectedPoint(lat, lon);
      var lengthProjected = projectedPoint(lat + lengthInDegrees, lon).y - origin.y;
      
      var ray = new OpenLayers.Geometry.LineString([origin]);
      var rayFeature = new OpenLayers.Feature.Vector(ray, {}, {
        strokeDashstyle: 'dot'
      });
      layer.addFeatures(rayFeature);
      
      var prevEndPoint;
      function update() {
        if (!layer.interested()) return;
        var angle = angleCell.depend(update);
        // TODO: Need to apply an offset of the VOR station's difference from geographic north (which we need to put in the DB)
        var sin = Math.sin(angle);
        // The following assumes that the projection in use is conformal, and that the length is small compared to the curvature.
        var end = new OpenLayers.Geometry.Point(
          origin.x + Math.sin(angle) * lengthProjected,
          origin.y + Math.cos(angle) * lengthProjected);
        ray.addPoint(end);
        if (prevEndPoint) {
          ray.removePoint(prevEndPoint);
        }
        prevEndPoint = end;
        layer.drawFeature(rayFeature);
      }
      update.scheduler = scheduler;
      update();
    });
  }
  
  maps.register(addVORMapLayer);
  
  return Object.freeze(exports);
});
