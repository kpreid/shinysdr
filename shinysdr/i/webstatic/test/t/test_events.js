// Copyright 2013, 2014 Kevin Reid and the ShinySDR contributors
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
    beforeEach,
    describe,
    expect,
    it,
    jasmine
  }} = import_jasmine;
  const {
    AddKeepDrop,
    Scheduler,
    SubScheduler,
  } = import_events;
  
  describe('events', () => {
    function itIsAScheduler(factory) {
      describe('startNow', () => {
        it('should do that', () => {
          const scheduler = factory();
          const cb = jasmine.createSpy('cb');
          scheduler.startNow(cb);
          expect(cb.calls.count()).toBe(1);
          scheduler.enqueue(cb);  // If this succeeds then the function was associated with the scheduler.
        });
      });

      describe('startLater', () => {
        it('should do that', done => {
          const scheduler = factory();
          const cb = jasmine.createSpy('cb');
          scheduler.startLater(cb);
          expect(cb.calls.count()).toBe(0);
          scheduler.startLater(() => {
            expect(cb.calls.count()).toBe(1);
            done();
          });
        });
      });
      
      describe('callNow', () => {
        // TODO: figure out how to work with Jasmine async to be less awkward about use of it() here.
        
        const scheduler = factory();
        const cb = jasmine.createSpy('cb');
        scheduler.claim(cb);
      
        it('should call the function immediately', done => {
          function waiter() { done(); }
          scheduler.claim(waiter);
          
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
        const scheduler = factory();
      
        const cb1 = jasmine.createSpy('cb1');
        scheduler.claim(cb1);
        const cb2base = jasmine.createSpy('cb2');
        function cb2() {
          cb2base();
          throw new Error('Uncaught error for testing.');
        }
        scheduler.claim(cb2);
        function cb3() {
          expect(cb1).toHaveBeenCalled();
          expect(cb2base).toHaveBeenCalled();
          // we are cb3 and were therefore called.
          done();
        }
        scheduler.claim(cb3);
      
        scheduler.enqueue(cb1);
        scheduler.enqueue(cb2);
        scheduler.enqueue(cb3);
      });
      
      // TODO: Test just basic functionality (.claim and .enqueue, deduplicating enqueues, etc)
      // TODO: Test behavior of .syncEventCallback
    }
    
    describe('Scheduler', () => {
      itIsAScheduler(() => new Scheduler(window));
    });
    
    describe('SubScheduler', () => {
      // Run basic scheduler tests. (This will have an extra beforeEach but that's harmless.)
      itIsAScheduler(() => new SubScheduler(new Scheduler(window), () => {}));
      
      let disable, rootScheduler, scheduler;
      beforeEach(() => {
        rootScheduler = new Scheduler(window);
        scheduler = new SubScheduler(rootScheduler, (d) => {
          disable = d;
        });
      });
      
      it('should not call callbacks previously scheduled', done => {
        const cb1 = jasmine.createSpy('cb1');
        scheduler.claim(cb1);
        scheduler.enqueue(cb1);
        disable();
        rootScheduler.startLater(() => {
          expect(cb1.calls.count()).toBe(0);
          done();
        });
      });
      
      it('should not call callbacks newly scheduled', done => {
        const cb1 = jasmine.createSpy('cb1');
        scheduler.claim(cb1);
        disable();
        scheduler.enqueue(cb1);
        rootScheduler.startLater(() => {
          expect(cb1.calls.count()).toBe(0);
          done();
        });
      });
      
      it('should startNow even if disabled', done => {
        // Rationale: Code that does startNow may depend on the side effects of the callback for it to finish successfully.
        const cb1 = jasmine.createSpy('cb1');
        disable();
        scheduler.startNow(cb1);
        expect(cb1.calls.count()).toBe(1);
        rootScheduler.startLater(() => {
          expect(cb1.calls.count()).toBe(1);
          done();
        });
      });
      
      it('should callNow even if disabled', done => {
        // Rationale: Code that does callNow may depend on the side effects of the callback for it to finish successfully.
        const cb1 = jasmine.createSpy('cb1');
        scheduler.claim(cb1);
        disable();
        scheduler.callNow(cb1);
        expect(cb1.calls.count()).toBe(1);
        rootScheduler.startLater(() => {
          expect(cb1.calls.count()).toBe(1);
          done();
        });
      });
      
      // TODO: Decide on and test behavior of .syncEventCallback
    });
    
    describe('AddKeepDrop', () => {
      function akdLogger() {
        const log = [];
        let i = 0;
        return [
          new AddKeepDrop({
            add: function (...a) { log.push(['add'].concat(a)); return i++; },
            remove: function (...a) { log.push(['remove'].concat(a)); },
          }),
          log
        ];
      }
      
      it('should add and remove things', () => {
        const [akd, log] = akdLogger();
        akd.update(['a', 'b']);
        akd.update(['a', 'c']);
        expect(log).toEqual([
          ['add', 'a'],
          ['add', 'b'],
          ['remove', 'b', 1],
          ['add', 'c'],
        ]);
      });
      
      it('should ignore duplicate adds', () => {
        const [akd, log] = akdLogger();
        akd.update(['a', 'a']);
        akd.update([]);
        expect(log).toEqual([
          ['add', 'a'],
          ['remove', 'a', 0],
        ]);
      });
    });
  });
  
  return 'ok';
});