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

define(['/test/jasmine-glue.js'], (jasmineGlue) => {
  'use strict';
  
  const {expect, fail} = jasmineGlue.ji;
  
  const exports = Object.create(null);
  
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
          }
          afterCallback();
        });
      });
    };
    
    return listener;
  }
  exports.newListener = newListener;
  
  return Object.freeze(exports);
});