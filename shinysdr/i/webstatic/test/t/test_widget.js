// Copyright 2014, 2016 Kevin Reid and the ShinySDR contributors
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
  'events',
  'types',
  'values',
  'widget',
  'widgets/basic',
], (
  import_jasmine,
  import_events,
  import_types,
  import_values,
  import_widget,
  import_widgets_basic
) => {
  const {ji: {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
  }} = import_jasmine;
  const {
    Scheduler,
  } = import_events;
  const {
    blockT,
    numberT,
  } = import_types;
  const {
    ConstantCell,
    LocalCell,
    makeBlock,
  } = import_values;
  const {
    Context,
    createWidgetExt,
    createWidgets,
  } = import_widget;
  const {
    Block,
  } = import_widgets_basic;
  
  describe('widget', function () {
    let context;
    let scheduler;
    let container;
    beforeEach(() => {
      scheduler = new Scheduler(window);
      context = new Context({
        widgets: {},
        scheduler: scheduler
      });
      container = document.createElement('div');
      document.body.appendChild(container);
    });
    afterEach(() => {
      container.parentNode.removeChild(container);
    });
  
    describe('createWidget', () => {
      it('should handle a broken widget', () => {
        function TestWidget(config) {
          throw new Error('Widget construction error for testing.');
        }
      
        const wEl = container.appendChild(document.createElement('div'));
        const cell = new LocalCell(numberT, 0);
        /* const widgetHandle = */ createWidgetExt(context, TestWidget, wEl, cell);
        // implicitly expect not to throw
        expect(container.firstChild.className).toBe('widget-ErrorWidget');
      });

      it('should call lifecycle callbacks', () => {
        let calledInit = 0;
        let calledDestroy = 0;
      
        function OuterWidget(config) {
          Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
            addWidget('inner', TestWidget);
          });
        }
        function TestWidget(config) {
          console.log('TestWidget instantiated');
          this.element = config.element;
          this.element.addEventListener('shinysdr:lifecycleinit', event => {
            calledInit++;
          });
          this.element.addEventListener('shinysdr:lifecycledestroy', event => {
            calledDestroy++;
          });
        }
      
        const container = document.createElement('div');
        document.body.appendChild(container);
        const wEl = container.appendChild(document.createElement('div'));
        const cell = new LocalCell(blockT, makeBlock({
          inner: new LocalCell(numberT, 0)
        }));
        const widgetHandle = createWidgetExt(context, OuterWidget, wEl, cell);
        expect(calledInit).toBe(1);
        expect(calledDestroy).toBe(0);
        widgetHandle.destroy();
        expect(calledInit).toBe(1);
        expect(calledDestroy).toBe(1);
        // TODO: Test subscheduler being disabled
      });
    });
    
    describe('createWidgets', () => {
      // TODO: need basic tests
      
      it('should be idempotent', () => {
        let count = 0;
        
        function TestWidget(config) {
          this.element = config.element;
          this.element.textContent = 'TestWidget ' + count++;
        }
        
        const wEl = container.appendChild(document.createElement('div'));
        wEl.setAttribute('data-widget', 'TestWidget');
        
        function once() {
          // note that we are operating on container, not wEl (which will be detached by the first run).
          createWidgets(
            new ConstantCell(makeBlock({})), 
            new Context({
              widgets: {TestWidget: TestWidget},
              scheduler: scheduler
            }),
            container);
        }
        
        expect(container.textContent).toBe('');
        expect(count).toBe(0);
        once();
        expect(container.textContent).toBe('TestWidget 0');
        expect(count).toBe(1);
        once();
        expect(container.textContent).toBe('TestWidget 0');
        expect(count).toBe(1);
      });
    });
  });
  
  return 'ok';
});