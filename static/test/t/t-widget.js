'use strict';

describe('widget', function () {
  var scheduler, widget;
  beforeEach(function () {
    scheduler = new sdr.events.Scheduler(window);
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
      var cell = new sdr.values.LocalCell(sdr.values.any);
      cell.set(0);
      widget = new sdr.widgets.Knob({
        target: cell,
        scheduler: scheduler
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
