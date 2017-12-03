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

'use strict';

define([
  '/test/jasmine-glue.js',
  '/test/testutil.js', 
  'types', 
  'values', 
  'widgets',
  'widgets/scope',
], ( 
  import_jasmine,
  import_testutil,
  import_types,
  import_values,
  widgets,
  import_widgets_scope
) => {
  const {ji: {
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    WidgetTester,
  } = import_testutil;
  const {
    EnumT,
    NoticeT,
    RangeT,
    ValueType,
    anyT,
    blockT,
    booleanT,
    numberT,
    stringT,
    TimestampT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    makeBlock,
  } = import_values;
  const {
    ScopeParameters,
  } = import_widgets_scope;
  
  describe('widgets', () => {
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
  
    describe('PickWidget', function () {
      // TODO more tests
    
      function t(widgetClass, type, value) {
        const cell = new LocalCell(type, value);
        const wt = new WidgetTester(widgets.PickWidget, cell);
        const widget = wt.widget;
      
        // Loose but more informative on failure
        if (widget.constructor.name && widgetClass.name) {
          expect(widget.constructor.name).toBe(widgetClass.name);
        }
      
        expect(Object.getPrototypeOf(widget)).toBe(widgetClass.prototype);
      }
    
      // TODO add tests of the cell-is-read-only case.
      it('should pick for blockT', () => t(widgets.Block, blockT, makeBlock({})));
      it('should pick for booleanT', () => t(widgets.Toggle, booleanT, false));
      it('should pick for EnumT', () => t(widgets.Select, new EnumT({}), 0));
      it('should pick for NoticeT', () => t(widgets.Banner, new NoticeT(), ''));
      it('should pick for numberT', () => t(widgets.SmallKnob, numberT, 0));
      //TODO it('should pick for RangeT', () => t(widgets.LinSlider, new RangeT([(0, 0)]), 0));
      it('should pick for stringT', () => t(widgets.TextBox, stringT, ''));
      it('should pick for TimestampT', () => t(widgets.TimestampWidget, new TimestampT(), 0));
      //TODO it('should pick for trackT', () => t(widgets.TrackWidget, trackT, {}));

      it('should pick for unknown', () => t(widgets.Generic, new (class FooT extends ValueType {})(), 1));

      // TODO: PickWidget used to be PickBlock. Add tests for its cell-type-based selection.
      it('should default to Block', function () {
        const cell = new LocalCell(blockT, makeBlock({}));
        const widget = new WidgetTester(widgets.PickWidget, cell).widget;
        expect(Object.getPrototypeOf(widget)).toBe(widgets.Block.prototype);
      });
    
      it('should match on object interfaces', function () {
        function TestWidget(config) {
          this.element = wt.config.element;
        }

        const block = makeBlock({});
        Object.defineProperty(block, '_implements_Foo', {value: true});  // non-enum
        const cell = new LocalCell(blockT, block);
        const wt = new WidgetTester(widgets.PickWidget, cell, {delay: true});
        wt.config.context.widgets['interface:Foo'] = TestWidget;
        const widget = wt.instantiate();
        expect(Object.getPrototypeOf(widget)).toBe(TestWidget.prototype);
      });
    });
  
    describe('Knob', function () {
      it('should hold a negative zero', function () {
        const cell = new LocalCell(anyT, 0);
        const widget = new WidgetTester(widgets.Knob, cell).widget;
      
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
        const cell = new LocalCell(new RangeT([[1, 2]], false, false), 0);
        const widget = new WidgetTester(widgets.SmallKnob, cell).widget;
        const input = widget.element.querySelector('input');
        expect(input.min).toBe('1');
        expect(input.max).toBe('2');
        expect(input.step).toBe('any');
      });

      it('should set limits from an integer RangeT type', function () {
        const cell = new LocalCell(new RangeT([[1, 2]], false, true), 0);
        const widget = new WidgetTester(widgets.SmallKnob, cell).widget;
        const input = widget.element.querySelector('input');
        expect(input.min).toBe('1');
        expect(input.max).toBe('2');
        expect(input.step).toBe('1');
      });
    });
  
    describe('ScopePlot', function () {
      it('should be successfully created', function () {
        // stub test to exercise the code because it's currently not in the default ui. Should have more tests.
      
        const cell = new LocalCell(anyT, [{freq:0, rate:1}, []]);
        cell.subscribe = function() {}; // TODO implement
        const root = new ConstantCell(makeBlock({
          scope: cell,
          parameters: new ConstantCell(
            new ScopeParameters(sessionStorage)),
        }));
      
        /* const widget = */ new WidgetTester(widgets.ScopePlot, root);
        
        expect(1).toBe(1);  // dummy expect for "this does not throw" test
      });
    });
  
    describe('Radio', function () {
      it('should use the metadata', function () {
        const cell = new LocalCell(new EnumT({
          'a': {'label': 'A', 'description': 'ALPHA', 'sort_key': '3'},
          'b': {'label': 'B', 'description': 'BETA', 'sort_key': '2'},
          'c': {'label': 'C', 'description': 'GAMMA', 'sort_key': '1'}
        }), 'a');
        const widget = new WidgetTester(widgets.Radio, cell).widget;
        document.body.appendChild(widget.element);
        expect(widget.element.textContent).toBe('CBA');
        expect(widget.element.querySelector('label').title).toBe('GAMMA');
      });
    });
  
    describe('Select', function () {
      it('should use a Range type', function () {
        const cell = new LocalCell(
          new RangeT(
            [[1, 1], [20, 20], [300, 300]],
            false, true, {symbol: 'Hz', si_prefix_ok: true}),
          20);
        const widget = new WidgetTester(widgets.Select, cell).widget;
        //document.body.appendChild(widget.element);
        expect(widget.element.textContent).toBe('1 Hz20 Hz300 Hz');
        expect(widget.element.querySelector('option').value).toBe('1');
      });
    });
    
    describe('BlockSet', () => {
      it('should be successfully created', function () {
        const cell = new ConstantCell(makeBlock({
          a: new ConstantCell(makeBlock({label: new ConstantCell('A')})),
          b: new ConstantCell(makeBlock({label: new ConstantCell('B')})),
        }));
        
        function entryBuilder(setElement, block, name, setInsertion) {
          const el = setElement.appendChild(document.createElement('div'));
          el.appendChild(document.createTextNode('[' + name + ']'));
          return el;
        }
        const TestBlockSet = widgets.BlockSet(widgets.PickWidget, entryBuilder);
        
        const widget = new WidgetTester(TestBlockSet, cell).widget;
        
        expect(widget.element.textContent).toBe('[a]label: A[b]label: B');
      });
    });
  });
  
  return 'ok';
});