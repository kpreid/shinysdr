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

'use strict';

describe('widget', function () {
  var context;
  var scheduler;
  beforeEach(function () {
    scheduler = new shinysdr.events.Scheduler(window);
    context = new shinysdr.widget.Context({
      widgets: {},
      scheduler: scheduler
    });
  });
  
  describe('createWidget', function () {
    it('should call lifecycle callbacks', function() {
      var calledInit = 0;
      var calledDestroy = 0;
      var poked = 0;
      var poke;
      
      function OuterWidget(config) {
        shinysdr.widgets.Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
          addWidget('inner', TestWidget);
        });
      }
      function TestWidget(config) {
        console.log('TestWidget instantiated');
        this.element = config.element;
        shinysdr.widget.addLifecycleListener(this.element, 'init', function() {
          calledInit++;
        });
        shinysdr.widget.addLifecycleListener(this.element, 'destroy', function() {
          calledDestroy++;
        });
        poke = config.boundedFn(function() {
          poked++;
        });
      }
      
      var container = document.createElement('div');
      document.body.appendChild(container);
      var wEl = container.appendChild(document.createElement('div'));
      var cell = new shinysdr.values.LocalCell(shinysdr.values.block, shinysdr.values.makeBlock({
        inner: new shinysdr.values.LocalCell(Number, 0)
      }));
      var widgetHandle = shinysdr.widget.createWidgetExt(context, OuterWidget, wEl, cell);
      expect(calledInit).toBe(1);
      expect(calledDestroy).toBe(0);
      expect(poked).toBe(0);
      poke();
      expect(poked).toBe(1);
      widgetHandle.destroy();
      expect(calledInit).toBe(1);
      expect(calledDestroy).toBe(1);
      poke();
      expect(poked).toBe(1);
    });
  });
});
