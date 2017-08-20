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

define([
  '/test/jasmine-glue.js',
  'events',
], (
  import_jasmine,
  import_events
) => {
  const {ji: {
    describe,
    expect,
    it,
    jasmine
  }} = import_jasmine;
  const {
    Scheduler
  } = import_events;
  
  describe('events', () => {
    describe('Scheduler', () => {
      describe('callNow', () => {
        // TODO: figure out how to work with Jasmine async to be less awkward about use of it() here.
        
        const scheduler = new Scheduler(window);
        const cb = jasmine.createSpy('cb');
        cb.scheduler = scheduler;
      
        it('should call the function immediately', done => {
          function waiter() { done(); }
          waiter.scheduler = scheduler;
          
          scheduler.enqueue(cb);
          scheduler.enqueue(waiter);
          expect(cb.calls.count()).toBe(0);
          scheduler.callNow(cb);
          expect(cb.calls.count()).toBe(1);
        });
        
        it('and should not call the function as previously scheduled', () => {
          // Wasn't another call after the call done.
          expect(cb.calls.count()).toBe(1);
        });
      });
    
      it('should invoke callbacks after one which throws', done => {
        const scheduler = new Scheduler(window);
      
        const cb1 = jasmine.createSpy('cb1');
        cb1.scheduler = scheduler;
        const cb2base = jasmine.createSpy('cb2');
        function cb2() {
          cb2base();
          throw new Error('Uncaught error for testing.');
        }
        cb2.scheduler = scheduler;
        function cb3() {
          expect(cb1).toHaveBeenCalled();
          expect(cb2base).toHaveBeenCalled();
          // we are cb3 and were therefore called.
          done();
        }
        cb3.scheduler = scheduler;
      
        scheduler.enqueue(cb1);
        scheduler.enqueue(cb2);
        scheduler.enqueue(cb3);
      });
    });
  });
  
  return 'ok';
});