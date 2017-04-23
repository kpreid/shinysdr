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
  const ValueType = types.ValueType;
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
      it('should pick for blockT', () => t(widgets.Block, types.blockT, makeBlock({})));
      it('should pick for booleanT', () => t(widgets.Toggle, types.booleanT, false));
      it('should pick for EnumT', () => t(widgets.Select, new types.EnumT({}), 0));
      it('should pick for NoticeT', () => t(widgets.Banner, new types.NoticeT(), ''));
      it('should pick for numberT', () => t(widgets.SmallKnob, types.numberT, 0));
      //TODO it('should pick for RangeT', () => t(widgets.LinSlider, new types.RangeT([(0, 0)]), 0));
      it('should pick for stringT', () => t(widgets.TextBox, types.stringT, ''));
      it('should pick for TimestampT', () => t(widgets.TimestampWidget, new types.TimestampT(), 0));
      //TODO it('should pick for trackT', () => t(widgets.TrackWidget, types.trackT, {}));

      it('should pick for unknown', () => t(widgets.Generic, new (class FooT extends ValueType {})(), 1));

      // TODO: PickWidget used to be PickBlock. Add tests for its cell-type-based selection.
      it('should default to Block', function () {
        const cell = new LocalCell(types.blockT, makeBlock({}));
        widget = new widgets.PickWidget(mockWidgetConfig(null, cell));
        expect(Object.getPrototypeOf(widget)).toBe(widgets.Block.prototype);
      });
    
      it('should match on object interfaces', function () {
        function TestWidget(config) {
          this.element = config.element;
        }

        const block = makeBlock({});
        Object.defineProperty(block, '_implements_Foo', {value: true});  // non-enum
        const cell = new LocalCell(types.blockT, block);
        const config = mockWidgetConfig(null, cell);
        config.context.widgets['interface:Foo'] = TestWidget;
        widget = new widgets.PickWidget(config);
        expect(Object.getPrototypeOf(widget)).toBe(TestWidget.prototype);
      });
    });
  
    describe('Knob', function () {
      it('should hold a negative zero', function () {
        const cell = new LocalCell(types.anyT, 0);
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
      it('should set limits from a continuous RangeT type', function () {
        const cell = new LocalCell(new types.RangeT([[1, 2]], false, false), 0);
        widget = new widgets.SmallKnob(mockWidgetConfig(null, cell));
        const input = widget.element.querySelector('input');
        expect(input.min).toBe('1');
        expect(input.max).toBe('2');
        expect(input.step).toBe('any');
      });

      it('should set limits from an integer RangeT type', function () {
        const cell = new LocalCell(new types.RangeT([[1, 2]], false, true), 0);
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
      
        const cell = new LocalCell(types.anyT, [{freq:0, rate:1}, []]);
        cell.subscribe = function() {}; // TODO implement
        const root = new values.ConstantCell(types.blockT, values.makeBlock({
          scope: cell,
          parameters: new values.ConstantCell(types.blockT,
            new widgets_scope.ScopeParameters(sessionStorage)),
        }));
      
        widget = new widgets.ScopePlot(mockWidgetConfig(null, root));
        
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });
    });
  
    describe('PickWidget', function () {
    });
  
    describe('Radio', function () {
      it('should use the metadata', function () {
        const cell = new LocalCell(new types.EnumT({
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
  
    describe('Select', function () {
      it('should use a Range type', function () {
        const cell = new LocalCell(
          new types.RangeT(
            [[1, 1], [20, 20], [300, 300]],
            false, true, {symbol: 'Hz', si_prefix_ok: true}),
          20);
        widget = new widgets.Select(mockWidgetConfig(null, cell));
        //document.body.appendChild(widget.element);
        expect(widget.element.textContent).toBe('1 Hz20 Hz300 Hz');
        expect(widget.element.querySelector('option').value).toBe('1');
      });
    });
  
    // TODO: This is in a different module and arguably ought to be in a separate test file. It's here because it's a widget and has use for the widget test glue.
    describe('GeoMap', function () {
      const GeoMap = mapCore.GeoMap;
      
      function makeStubTarget() {
        // TODO stop needing this boilerplate, somehow.
        return new ConstantCell(types.blockT, makeBlock({
          source: new ConstantCell(types.blockT, makeBlock({
            freq: new ConstantCell(types.numberT, 0),
            rx_driver: new ConstantCell(types.blockT, makeBlock({
              output_type: new ConstantCell(types.anyT, {sample_rate: 1})
            })),
            components: new ConstantCell(types.blockT, makeBlock({}))
          })),
          receivers: new ConstantCell(types.blockT, makeBlock({
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