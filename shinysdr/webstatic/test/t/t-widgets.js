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

'use strict';

describe('widgets', function () {
  var scheduler, widget;
  beforeEach(function () {
    scheduler = new shinysdr.events.Scheduler(window);
    widget = undefined;
  });
  afterEach(function () {
    if (widget && widget.element && widget.element.parentNode) {
      widget.element.parentNode.removeChild(widget.element);
    }
  });
  
  function simulateKey(key, el) {
    ['keydown', 'keypress', 'keyup'].forEach(function (type) {
      var e = document.createEvent('KeyboardEvent');
      // kludge from http://stackoverflow.com/questions/10455626/keydown-simulation-in-chrome-fires-normally-but-not-the-correct-key
      Object.defineProperty(e, 'charCode', {
        get: function () { return key.charCodeAt(0); }
      });
      Object.defineProperty(e, 'keyCode', {
        get: function () { return key.charCodeAt(0); }
      });
      e.initKeyboardEvent(type, false, false, window, key, key, 0, '', false, '');
      el.dispatchEvent(e);
    });
  }
  
  describe('Knob', function () {
    it('should hold a negative zero', function () {
      var cell = new shinysdr.values.LocalCell(shinysdr.values.any, 0);
      widget = new shinysdr.widgets.Knob({
        target: cell,
        scheduler: scheduler,
        boundedFn: function(f) { return f; }
      });
      
      document.body.appendChild(widget.element);
      
      expect(cell.get()).toBe(0);
      expect(1 / cell.get()).toBe(Infinity);
      
      simulateKey('-', widget.element.querySelector('.knob-digit:last-child'));
      
      expect(cell.get()).toBe(0);
      expect(1 / cell.get()).toBe(-Infinity);
      
      simulateKey('5', widget.element.querySelector('.knob-digit:last-child'));
      
      expect(cell.get()).toBe(-5);
    });
  });
});
