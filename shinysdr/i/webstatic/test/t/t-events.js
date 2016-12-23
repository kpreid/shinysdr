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

define(['events'], (events) => {
  'use strict';
  
  const Scheduler = events.Scheduler;
  
  describe('events', function () {
    describe('Scheduler', function () {
      it('should have callNow which cancels scheduling', function () {
        const scheduler = new Scheduler(window);
        const cb = jasmine.createSpy('cb');
        cb.scheduler = scheduler;
        const waiter = jasmine.createSpy('waiter');
        waiter.scheduler = scheduler;
      
        scheduler.enqueue(cb);
        scheduler.enqueue(waiter);
        expect(cb.calls.length).toBe(0);
        scheduler.callNow(cb);
        expect(cb.calls.length).toBe(1);
      
        waitsFor(function() {
          return waiter.calls.length;
        }, 'did a schedule', 100);
        runs(function() {
          expect(cb.calls.length).toBe(1);
        });
      });
    
      it('should invoke callbacks after one which throws', function () {
        const scheduler = new Scheduler(window);
      
        const cb1 = jasmine.createSpy('cb1');
        cb1.scheduler = scheduler;
        const cb2base = jasmine.createSpy('cb2');
        const cb2 = function () { cb2base(); throw new Error('Dummy uncaught error.'); }
        cb2.scheduler = scheduler;
        const cb3 = jasmine.createSpy('cb3');
        cb3.scheduler = scheduler;
      
        scheduler.enqueue(cb1);
        scheduler.enqueue(cb2);
        scheduler.enqueue(cb3);
      
        waitsFor(function() {
          return cb3.calls.length;
        }, 'last callback called', 100);
        runs(function() {
          expect(cb1).toHaveBeenCalled();
          expect(cb2base).toHaveBeenCalled();
          expect(cb3).toHaveBeenCalled();
        });
      });
    });
  });
  
  return 'ok';
});