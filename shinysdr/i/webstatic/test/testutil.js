// Copyright 2016 Kevin Reid <kpreid@switchb.org>
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
        'coordination', 'database', 'events', 'values'],
       (jasmineGlue,
         coordination,   database,   events,   values) => {
  'use strict';
  
  const {afterEach, expect, fail} = jasmineGlue.ji;
  const {
    ClientStateObject,
  } = coordination;
  const {
    Table,
  } = database;
  const {
    Scheduler,
  } = events;
  const {
    Index,
    StorageNamespace,
  } = values;
  
  const exports = Object.create(null);
  
  const cleanupCallbacks = [];
  afterEach(() => {
    while (cleanupCallbacks.length) {
      cleanupCallbacks.pop()();
    }
  });
  function afterThis(cleanupCallback) {
    if (typeof cleanupCallback !== 'function') {
      throw new TypeError(cleanupCallback + ' not a function');
    }
    cleanupCallbacks.push(cleanupCallback);
  }
  
  function afterNotificationCycle(scheduler, callback) {
    function wrapper() {
      callback();
    }
    wrapper.scheduler = scheduler;
    scheduler.enqueue(wrapper);
  }
  exports.afterNotificationCycle = afterNotificationCycle;
  
  function newListener(scheduler) {
    let calls = 0;
    let pr;
    const calledPromise = new Promise(resolve => { pr = resolve; });
    function listener() {
      calls++;
      pr(null);
    }
    listener.scheduler = scheduler;
    
    listener.expectNotCalled = function (callback) {
      expect(1).toBe(1);  // dummy to suppress "SPEC HAS NO EXPECTATIONS". TODO: better way?
      afterNotificationCycle(scheduler, () => {
        if (calls !== 0) {
          fail('Expected listener not to be called but was called ' + calls + ' times.');
        }
        callback();
      });
    };
    
    listener.expectCalled = function (beforeCallback, afterCallback) {
      expect(1).toBe(1);  // dummy to suppress "SPEC HAS NO EXPECTATIONS". TODO: better way?
      afterNotificationCycle(scheduler, () => {
        if (calls !== 0) {
          fail('Expected listener not to be called yet but was called ' + calls + ' times.');
        }
        beforeCallback();
        calledPromise.then(() => {
          if (calls !== 1) {
            fail('Expected listener to be called once but was called ' + calls + ' times.');
          } else {
            afterCallback();
          }
        });
      });
    };
    
    listener.expectCalledWhenever = function (afterCallback) {
      expect(1).toBe(1);  // dummy to suppress "SPEC HAS NO EXPECTATIONS". TODO: better way?
      calledPromise.then(() => {
        if (calls !== 1) {
          fail('Expected listener to be called once but was called ' + calls + ' times.');
        } else {
          afterCallback();
        }
      });
    };
    
    return listener;
  }
  exports.newListener = newListener;
  
  class WidgetTester {
    constructor(widgetCtor, cell, {delay} = {}) {
      this._scheduler = new Scheduler(window);
      this.widgetCtor = widgetCtor;
      this.cell = cell;
      this.widget = null;
      this.config = null;
      
      sessionStorage.clear();  // TODO: use a mock storage instead
      afterThis(this.close.bind(this));
      
      this.config = this._mockWidgetConfig(null);
      if (!delay) {
        this.instantiate();
      }
    }
    
    close() {
      const widget = this.widget;
      if (widget && widget.element && widget.element.parentNode) {
        widget.element.parentNode.removeChild(widget.element);
      }
    }
    
    _mockWidgetConfig(element) {
      if (!element) element = document.createElement('div');
      const scheduler = this._scheduler;
      const cell = this.cell;
      
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
    
    instantiate() {
      if (this.widget) {
        throw new Error('Cannot reuse WidgetTester');
      }
      const widget = new (this.widgetCtor)(this.config);
      this.widget = widget;
      return widget;
    }
  }
  exports.WidgetTester = WidgetTester;
  
  return Object.freeze(exports);
});