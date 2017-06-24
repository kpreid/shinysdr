// Copyright 2017 Kevin Reid <kpreid@switchb.org>
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

define(['widgets', 'widgets/basic'],
       (widgets, widgets_basic) => {
  'use strict';
  
  const {
    Block,
    Knob,
    PickWidget,
    Radio,
    Select,
    SmallKnob,
  } = widgets_basic;
  
  const exports = {};
  
  function ElecraftRadio(config) {
    Block.call(this, config, (block, addWidget, ignore, setInsertion, setToDetails, getAppend) => {
      // TODO: Shouldn't have to repeat label strings that the server already provides, but usages of addWidget are a hairy thing.
      
      addWidget('MC', SmallKnob, 'Memory');
      
      // KX3 first knob
      // AF is in receiver
      addWidget('SQ', null, 'Squelch');
      addWidget('ML', null, 'Monitor Level');
      // second knob
      // third knob
      addWidget('MG', null, 'Mic Gain');
      addWidget('PC', null, 'TX Power');

      function header(text) {
        const element = getAppend().appendChild(document.createElement('div'));
        element.className = 'panel frame-controls';
        element.textContent = text;
      }
      // TODO: On KX3 these should be called A and B 
      header('Main VFO');
      addWidget('rx_main');
      header('Sub VFO');
      addWidget('rx_sub');
      
      setToDetails();
    });
  }
  
  function ElecraftReceiver(config) {
    Block.call(this, config, (block, addWidget, ignore, setInsertion, setToDetails, getAppend) => {
      addWidget('freq', Knob, '');
      addWidget('MD', Select, 'Mode');
      addWidget('AG', null, 'AF Gain');
      addWidget('LK', null, 'Lock');
      addWidget('PA', null, 'RX Preamp');
      
      setToDetails();
      
      ignore('BN');
    });
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.elecraft.IElecraftRadio'] = ElecraftRadio;
  widgets['interface:shinysdr.plugins.elecraft.IElecraftReceiver'] = ElecraftReceiver;
  
  return Object.freeze(exports);
});
