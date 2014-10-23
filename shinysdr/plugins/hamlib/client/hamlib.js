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
define(['widgets'], function (widgets) {
  'use strict';
  
  var Banner = widgets.Banner;
  var Block = widgets.Block;
  var Knob = widgets.Knob;
  var Meter = widgets.Meter;
  var Radio = widgets.Radio;
  
  var exports = {};
  
  function ExtRig(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      ignore('freq');  // is merged into vfo
      if ('Mode' in block) {
        addWidget('Mode', Radio, 'Mode');
      }
      addWidget('errors', Banner);
      if ('STRENGTH level' in block) {
        addWidget('STRENGTH level', Meter, 'S');
        ignore('RAWSTR level');
      }
      
      setToDetails();
    });
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.hamlib.IRig'] = ExtRig;
  
  return Object.freeze(exports);
});
