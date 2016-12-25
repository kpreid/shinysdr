// Copyright 2013, 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
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

define(['/test/jasmine-glue.js',
        'coordination', 'database', 'events', 'map/map-core',
        'types', 'values', 'widget', 'widgets', 'widgets/scope'],
       ( jasmineGlue,
         coordination,   database,   events,   mapCore, 
         types,   values,   widget,   widgets,   widgets_scope) => {
  'use strict';

  const {afterEach, beforeEach, describe, expect, it} = jasmineGlue.ji;
  const ClientStateObject = coordination.ClientStateObject;
  const ConstantCell = values.ConstantCell;
  const LocalCell = values.LocalCell;
  const Index = values.Index;
  const Scheduler = events.Scheduler;
  const StorageNamespace = values.StorageNamespace;
  const Table = database.Table;
  const makeBlock = values.makeBlock;

  describe('widgets', function () {
    let scheduler, widget;
    beforeEach(function () {
      scheduler = new Scheduler(window);
      widget = undefined;
      sessionStorage.clear();
    });
    afterEach(function () {
      if (widget && widget.element && widget.element.parentNode) {
        widget.element.parentNode.removeChild(widget.element);
      }
    });
  
    function simulateKey(key, el) {
      ['keydown', 'keypress', 'keyup'].forEach(type => {
        const e = document.createEvent('KeyboardEvent');
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
  
    function mockWidgetConfig(element, cell) {
      if (!element) element = document.createElement('div');
      document.body.appendChild(element);
      function rebuildMe() { throw new Error('mock rebuildMe not implemented'); }
      rebuildMe.scheduler = scheduler;
      const index = new Index(scheduler, cell);
      const stubCoordinator = {
        actions: {
          _registerMap: function () {}  // TODO this is a stub of a kludge and should go away when the kludge does
        }
      };
      const storage = new StorageNamespace(sessionStorage, Math.random() + '.');
      return {
        storage: storage,
        freqDB: new Table('foo', false),
        element: element,
        target: cell,
        scheduler: scheduler,
        clientState: new ClientStateObject(storage, null),
        boundedFn: f => f,
        rebuildMe: rebuildMe,
        index: index,
        context: {
          widgets: {},
          scheduler: scheduler,
          index: index,
          coordinator: stubCoordinator
        },
        actions: stubCoordinator.actions,
      };
    }
  
    describe('PickWidget', function () {
      // TODO more tests
    
      function t(widgetClass, type, value) {
        const cell = new LocalCell(type, value);
        widget = new widgets.PickWidget(mockWidgetConfig(null, cell));
      
        // Loose but more informative on failure
        if (widget.constructor.name && widgetClass.name) {
          expect(widget.constructor.name).toBe(widgetClass.name);
        }
      
        expect(Object.getPrototypeOf(widget)).toBe(widgetClass.prototype);
      }
    
      // TODO add tests of the cell-is-read-only case.
      it('should pick for Block', () => t(widgets.Block, types.block, makeBlock({})));
      it('should pick for Boolean', () => t(widgets.Toggle, Boolean, false));
      it('should pick for Enum', () => t(widgets.Select, new types.Enum({}), 0));
      it('should pick for Notice', () => t(widgets.Banner, new types.Notice(), ''));
      it('should pick for Number', () => t(widgets.SmallKnob, Number, 0));
      //TODO it('should pick for Range', () => t(widgets.LinSlider, new types.Range([(0, 0)]), 0));
      it('should pick for String', () => t(widgets.TextBox, String, ''));
      it('should pick for Timestamp', () => t(widgets.TimestampWidget, new types.Timestamp(), 0));
      //TODO it('should pick for Track', () => t(widgets.TrackWidget, types.Track, {}));

      it('should pick for unknown', () => t(widgets.Generic, function sometype() {}, 1));

      // TODO: PickWidget used to be PickBlock. Add tests for its cell-type-based selection.
      it('should default to Block', function () {
        const cell = new LocalCell(types.block, makeBlock({}));
        widget = new widgets.PickWidget(mockWidgetConfig(null, cell));
        expect(Object.getPrototypeOf(widget)).toBe(widgets.Block.prototype);
      });
    
      it('should match on object interfaces', function () {
        function TestWidget(config) {
          this.element = config.element;
        }

        const block = makeBlock({});
        Object.defineProperty(block, '_implements_Foo', {value: true});  // non-enum
        const cell = new LocalCell(types.block, block);
        const config = mockWidgetConfig(null, cell);
        config.context.widgets['interface:Foo'] = TestWidget;
        widget = new widgets.PickWidget(config);
        expect(Object.getPrototypeOf(widget)).toBe(TestWidget.prototype);
      });
    });
  
    describe('Knob', function () {
      it('should hold a negative zero', function () {
        const cell = new LocalCell(types.any, 0);
        widget = new widgets.Knob(mockWidgetConfig(null, cell));
      
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
  
    describe('SmallKnob', function () {
      it('should set limits from a continuous Range type', function () {
        const cell = new LocalCell(new types.Range([[1, 2]], false, false), 0);
        widget = new widgets.SmallKnob(mockWidgetConfig(null, cell));
        const input = widget.element.querySelector('input');
        expect(input.min).toBe('1');
        expect(input.max).toBe('2');
        expect(input.step).toBe('any');
      });

      it('should set limits from an integer Range type', function () {
        const cell = new LocalCell(new types.Range([[1, 2]], false, true), 0);
        widget = new widgets.SmallKnob(mockWidgetConfig(null, cell));
        const input = widget.element.querySelector('input');
        expect(input.min).toBe('1');
        expect(input.max).toBe('2');
        expect(input.step).toBe('1');
      });
    });
  
    describe('ScopePlot', function () {
      it('should be successfully created', function () {
        // stub test to exercise the code because it's currently not in the default ui. Should have more tests.
      
        const cell = new LocalCell(types.any, [{freq:0, rate:1}, []]);
        cell.subscribe = function() {}; // TODO implement
        const root = new values.ConstantCell(types.block, values.makeBlock({
          scope: cell,
          parameters: new values.ConstantCell(types.block,
            new widgets_scope.ScopeParameters(sessionStorage)),
        }));
      
        widget = new widgets.ScopePlot(mockWidgetConfig(null, root));
      });
    });
  
    describe('PickWidget', function () {
    });
  
    describe('Radio', function () {
      it('should use the metadata', function () {
        const cell = new LocalCell(new types.Enum({
          'a': {'label': 'A', 'description': 'ALPHA', 'sort_key': '3'},
          'b': {'label': 'B', 'description': 'BETA', 'sort_key': '2'},
          'c': {'label': 'C', 'description': 'GAMMA', 'sort_key': '1'}
        }), 'a');
        widget = new widgets.Radio(mockWidgetConfig(null, cell));
        document.body.appendChild(widget.element);
        expect(widget.element.textContent).toBe('CBA');
        expect(widget.element.querySelector('label').title).toBe('GAMMA');
      });
    });
  
    // TODO: This is in a different module and arguably ought to be in a separate test file. It's here because it's a widget and has use for the widget test glue.
    describe('GeoMap', function () {
      const GeoMap = mapCore.GeoMap;
      
      function makeStubTarget() {
        // TODO stop needing this boilerplate, somehow.
        return new ConstantCell(types.block, makeBlock({
          source: new ConstantCell(types.block, makeBlock({
            freq: new ConstantCell(Number, 0),
            rx_driver: new ConstantCell(types.block, makeBlock({
              output_type: new ConstantCell(types.any, {sample_rate: 1})
            })),
            components: new ConstantCell(types.block, makeBlock({}))
          })),
          receivers: new ConstantCell(types.block, makeBlock({
          }))
        }));
      }
    
      it('exists', function () {
        expect(typeof GeoMap).toBe('function');
      });
    
      it('should be successfully created', function () {
        const cell = makeStubTarget();
        const config = mockWidgetConfig(null, cell);
        widget = new GeoMap(config);
        expect(config.storage.getItem('viewCenterLat')).toBe('0');  // TODO: test against public interface -- of some sort -- rather than storage
        expect(config.storage.getItem('viewCenterLon')).toBe('0');
        expect(config.storage.getItem('viewZoom')).toBe('1');
      });
    
      // TODO Check reading initial position from PositionedDevice
    });
  });
  
  return 'ok';
});